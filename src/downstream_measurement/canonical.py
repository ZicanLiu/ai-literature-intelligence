"""Phase D: canonical experimental registry built from raw/near-raw evidence.

Independently loads protocol -> condition mapping -> execution plan -> formal
outputs -> three frozen judge packages (+ full Pro sensitivity audit from the
supplement ZIP), re-verifies identities from bytes, and emits canonical rows.
No original aggregation code is imported.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from .inventory import package_directory_names, resolve_package_directory
from .util import canonical_json_bytes, load_json, sha256_bytes, sha256_file

PRIMARY_JUDGES = ["GPT", "DeepSeek", "GLM"]
SENSITIVITY_EVALUATOR = "FullPro"
ARMS = ["BM25", "MCA"]
REPETITIONS = [1, 2, 3]


class CanonicalBuildError(AssertionError):
    """Fail-closed error for identity/structure violations."""


def _task_hash(judge: str, research_question: str, task_instruction: str) -> str:
    """Judge-protocol task binding convention (GPT binds RQ+task, others task only)."""
    if judge == "GPT":
        payload = json.dumps(
            {"research_question": research_question, "task_definition": task_instruction},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return sha256_bytes(payload)
    return sha256_bytes(task_instruction.encode("utf-8"))


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    raise CanonicalBuildError(f"non-boolean atomic flag: {value!r}")


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise CanonicalBuildError(message)


class CanonicalRegistry:
    def __init__(self) -> None:
        self.outputs: list[dict] = []
        self.claims: list[dict] = []
        self.evaluations: list[dict] = []
        self.claim_judgements: list[dict] = []
        self.error_events: list[dict] = []
        self.validation: dict = {}
        self.source_identities: dict = {}
        self.full_pro_binding: dict | None = None

    def to_dict(self) -> dict:
        return {
            "outputs": self.outputs,
            "claims": self.claims,
            "evaluations": self.evaluations,
            "claim_judgements": self.claim_judgements,
            "error_events": self.error_events,
            "validation": self.validation,
            "source_identities": self.source_identities,
        }


def build_canonical(evidence_root: Path, supplement_zip: Path | None) -> CanonicalRegistry:
    evidence_root = Path(evidence_root)
    prep = resolve_package_directory(evidence_root, "experiment_prep")
    formal = resolve_package_directory(evidence_root, "formal_execution")
    judge_dirs = {
        "GPT": resolve_package_directory(evidence_root, "ai_eval_gpt"),
        "DeepSeek": resolve_package_directory(evidence_root, "ai_eval_deepseek"),
        "GLM": resolve_package_directory(evidence_root, "ai_eval_glm"),
    }
    formal_manifest_hashes = _parse_formal_manifest_hashes(formal)

    protocol = load_json(prep / "protocol" / "downstream_experiment_protocol_v1.json")
    mapping_rel = protocol["blinding"]["private_condition_map"]
    mapping = load_json(prep / mapping_rel)
    plan = load_json(prep / "protocol" / "private_execution_plan.json")
    schema = load_json(prep / "protocol" / "human_evaluation_schema.json")
    rubric_bytes = (prep / "protocol" / "HUMAN_EVALUATION_RUBRIC_V1.md").read_bytes()
    rubric_sha = sha256_bytes(rubric_bytes)

    _check(protocol["source_files"]["protocol/private_execution_plan.json"]
           == sha256_file(prep / "protocol" / "private_execution_plan.json"), "plan hash drift vs protocol")
    _check(len(mapping) == 4, "condition mapping must have 4 entries")
    conditions = {c["opaque_condition_id"]: c for c in mapping}
    _check(len(conditions) == 4, "duplicate opaque_condition_id")

    topics = [t["topic_id"] for t in protocol["topics"]]
    tasks = list(protocol["matrix"]["tasks"])
    _check(protocol["matrix"]["arms"] == ARMS, "unexpected arm set")

    runs = plan["runs"]
    run_ids = [r["output_id"] for r in runs]
    expected_lattice = {(t, k, a, rep) for t in topics for k in tasks for a in ARMS for rep in REPETITIONS}
    _check(len(set(run_ids)) == len(run_ids), "duplicate output_id in execution plan")
    lattice = {(r["topic_id"], r["task_id"], r["arm"], r["repetition"]) for r in runs}
    _check(lattice == expected_lattice,
           "run lattice does not match protocol matrix x 3 repetitions")

    formal_manifest = load_json(formal / "formal_execution_manifest.json")
    _check(formal_manifest["status"] == "COMPLETE", "formal execution not COMPLETE")
    _check(formal_manifest["operational_summary"]["technically_completed_outputs"] == len(run_ids),
           "formal outputs count mismatch")
    _check(formal_manifest["preparation_protocol_sha256"]
           == sha256_file(prep / "protocol" / "downstream_experiment_protocol_v1.json"),
           "formal manifest protocol hash drift")
    freeze_binding = load_json(formal / "source_freeze_binding.json")
    snapshot = None
    for key in freeze_binding.get("source_snapshot", {}):
        if key.replace("\\", "/").split("/")[-1] in package_directory_names("experiment_prep"):
            snapshot = freeze_binding["source_snapshot"][key]
            break
    _check(snapshot is not None, "formal snapshot does not bind prep package")
    _check(snapshot.get(mapping_rel) == sha256_file(prep / mapping_rel),
           "condition mapping hash drift vs formal source snapshot")
    _check(snapshot.get("protocol/private_execution_plan.json")
           == sha256_file(prep / "protocol" / "private_execution_plan.json"),
           "execution plan hash drift vs formal source snapshot")

    generator_identity = {
        "provider": formal_manifest.get("provider"),
        "model": formal_manifest.get("model"),
        "reasoning_effort": formal_manifest.get("reasoning_effort"),
        "codex_cli": formal_manifest.get("codex_cli"),
        "generator_freeze_v2_sha256": formal_manifest.get("generator_freeze_v2_sha256"),
    }

    registry = CanonicalRegistry()
    registry.source_identities = {
        "protocol_sha256": sha256_file(prep / "protocol" / "downstream_experiment_protocol_v1.json"),
        "condition_mapping_sha256": sha256_file(prep / mapping_rel),
        "execution_plan_sha256": sha256_file(prep / "protocol" / "private_execution_plan.json"),
        "rubric_sha256": rubric_sha,
        "human_evaluation_schema_sha256": sha256_file(prep / "protocol" / "human_evaluation_schema.json"),
        "formal_execution_manifest_sha256": sha256_file(formal / "formal_execution_manifest.json"),
        "formal_package_manifest_sha256": sha256_file(formal / "SHA256_manifest.txt"),
    }

    outputs_by_id: dict[str, dict] = {}
    claims_by_output: dict[str, list[dict]] = {}
    task_instruction_by_oid: dict[str, str] = {}
    research_question_by_oid: dict[str, str] = {}
    for run in runs:
        oid = run["output_id"]
        condition = conditions[run["opaque_condition_id"]]
        _check(run["arm"] == condition["arm"] and run["topic_id"] == condition["topic_id"]
               and run["context_sha256"] == condition["context_sha256"],
               f"run/condition binding mismatch for {oid}")
        input_doc = load_json(formal / "public_blinded_outputs" / oid / "input.json")
        gen_doc = load_json(formal / "public_blinded_outputs" / oid / "generator_output.json")
        gen_hash = formal_manifest_hashes[f"public_blinded_outputs/{oid}/generator_output.json"]
        input_hash = formal_manifest_hashes[f"public_blinded_outputs/{oid}/input.json"]
        _check(input_doc["output_id"] == oid and gen_doc["task_id"] == run["task_id"],
               f"formal output identity mismatch for {oid}")
        _check(input_doc["task_instruction"] == run["exact_task_instruction"],
               f"task instruction drift for {oid}")
        _check(sha256_bytes(input_doc["evidence_context"].encode("utf-8")) == condition["context_sha256"],
               f"context hash drift for {oid}")
        _check(sha256_file(formal / "public_blinded_outputs" / oid / "generator_output.json") == gen_hash,
               f"generator output byte hash drift for {oid}")
        row = {
            "output_id": oid,
            "topic_id": run["topic_id"],
            "task_id": run["task_id"],
            "arm": run["arm"],
            "repetition": run["repetition"],
            "opaque_condition_id": run["opaque_condition_id"],
            "context_sha256": condition["context_sha256"],
            "context_token_count": condition["context_token_count"],
            "context_units_definition": "pilot_unicode_word_v1",
            "input_sha256": input_hash,
            "generator_output_sha256": gen_hash,
            "claims_count": len(gen_doc["claims"]),
            "generator_identity": generator_identity,
            "source_locator": f"formal_execution:public_blinded_outputs/{oid}/generator_output.json",
        }
        registry.outputs.append(row)
        outputs_by_id[oid] = row
        for claim in gen_doc["claims"]:
            _check("slot_id" in claim and "claim_text" in claim, f"malformed claim in {oid}")
            registry.claims.append({
                "output_id": oid,
                "appearance_index": int(claim["slot_id"].lstrip("S")) if str(claim["slot_id"]).startswith("S") else None,
                "slot_id": claim["slot_id"],
                "claim_text": claim["claim_text"],
                "claim_text_sha256": sha256_bytes(claim["claim_text"].encode("utf-8")),
                "claim_text_length": len(claim["claim_text"]),
                "scope_qualification_sha256": sha256_bytes((claim.get("scope_or_qualification") or "").encode("utf-8")),
                "evidence_quotes_count": len(claim.get("evidence_quotes", [])),
                "source_titles_count": len(claim.get("source_titles", [])),
                "generator_output_sha256": gen_hash,
                "source_locator": f"formal_execution:public_blinded_outputs/{oid}/generator_output.json#/claims",
            })
        claims_by_output[oid] = gen_doc["claims"]
        task_instruction_by_oid[oid] = input_doc["task_instruction"]
        research_question_by_oid[oid] = input_doc["research_question"]

    validation_rows = []
    for judge in PRIMARY_JUDGES:
        jdir = judge_dirs[judge]
        judgement_files = sorted((jdir / "judgements").glob("*.json"))
        _check({p.stem for p in judgement_files} == set(run_ids),
               f"{judge}: judgement file set does not match 24 outputs")
        for path in judgement_files:
            oid = path.stem
            run = next(r for r in runs if r["output_id"] == oid)
            condition = conditions[run["opaque_condition_id"]]
            input_doc = load_json(formal / "public_blinded_outputs" / oid / "input.json")
            gen_doc = load_json(formal / "public_blinded_outputs" / oid / "generator_output.json")
            judgement = load_json(path)
            _check(judgement["output_id"] == oid, f"{judge}/{oid}: output_id mismatch")
            expected_binding = {
                "context": condition["context_sha256"],
                "generator_output": formal_manifest_hashes[f"public_blinded_outputs/{oid}/generator_output.json"],
                "task": _task_hash(judge, input_doc["research_question"], input_doc["task_instruction"]),
                "rubric": rubric_sha,
            }
            _check(judgement["input_sha256"] == expected_binding,
                   f"{judge}/{oid}: input binding mismatch {judgement['input_sha256']} != {expected_binding}")
            units = judgement["claim_units"]
            _check(len(units) == len(gen_doc["claims"]), f"{judge}/{oid}: claim count mismatch")
            _check([u["appearance_index"] for u in units] == list(range(1, len(units) + 1)),
                   f"{judge}/{oid}: appearance_index not 1..n")
            span_defects = 0
            for unit, claim in zip(units, gen_doc["claims"]):
                _check(unit["submitted_slot_id"] == claim["slot_id"], f"{judge}/{oid}: slot mismatch")
                _check(unit["redundancy"] in ("REDUNDANT", "NONREDUNDANT"), f"{judge}/{oid}: bad redundancy label")
                _check(bool(unit["redundancy_of_indices"]) == (unit["redundancy"] == "REDUNDANT"),
                       f"{judge}/{oid}: redundancy prior inconsistency at {unit['appearance_index']}")
                if unit.get("exact_output_span") != claim["claim_text"]:
                    span_defects += 1
            events = judgement.get("substantive_error_events")
            issues = []
            if not isinstance(events, list):
                issues.append("missing event set")
            else:
                event_ids = [e["error_id"] for e in events]
                if len(set(event_ids)) != len(event_ids):
                    issues.append("duplicate event ids")
                for event in events:
                    affected = set(event["affected_appearance_indices"])
                    if not affected <= {u["appearance_index"] for u in units}:
                        issues.append("orphan affected indices")
                    linked = {u["appearance_index"] for u in units if event["error_id"] in u["error_ids"]}
                    if linked != affected:
                        issues.append("nonreciprocal event links")
                for unit in units:
                    if not set(unit["error_ids"]) <= set(event_ids):
                        issues.append("unknown event link")
                    if ((unit["support"] in ("UNSUPPORTED", "CONTRADICTED") or unit["scope"] == "OUT_OF_SCOPE")
                            and not unit["error_ids"]):
                        issues.append("missing required event coverage")
            e_status = "PASS" if not issues else "BLOCKED_FOR_EVENT_GROUPING"
            validation_rows.append({
                "evaluator": judge, "output_id": oid, "role": "PRIMARY_JUDGE",
                "schema": "PASS", "input_identity": "PASS", "claim_alignment": "PASS",
                "event_structure": e_status, "event_issues": issues, "span_transcription_defects": span_defects,
            })
            registry.evaluations.append({
                "evaluator": judge,
                "role": "PRIMARY_JUDGE",
                "output_id": oid,
                "evaluation_id": judgement["evaluation_id"],
                "rubric_sha256": rubric_sha,
                "task_binding_sha256": expected_binding["task"],
                "context_binding_sha256": expected_binding["context"],
                "generator_output_sha256": expected_binding["generator_output"],
                "judgement_file_sha256": sha256_file(path),
                "schema_status": "STRUCTURALLY_VALIDATED",
                "valid_abstention": bool(judgement.get("valid_abstention")),
                "exact_match_checks": judgement.get("exact_match_checks"),
                "source_locator": f"ai_eval_{judge.lower()}:judgements/{oid}.json",
            })
            for unit in units:
                registry.claim_judgements.append({
                    "evaluator": judge,
                    "role": "PRIMARY_JUDGE",
                    "output_id": oid,
                    "topic_id": run["topic_id"],
                    "task_id": run["task_id"],
                    "arm": run["arm"],
                    "repetition": run["repetition"],
                    "appearance_index": unit["appearance_index"],
                    "atomic": _as_bool(unit["atomic"]),
                    "support": unit["support"],
                    "scope": unit["scope"],
                    "redundancy": unit["redundancy"],
                    "error_ids": list(unit["error_ids"]),
                    "has_linked_error": bool(unit["error_ids"]),
                    "source_package_id": f"ai_eval_{judge.lower()}",
                    "source_file_sha256": sha256_file(path),
                    "source_locator": f"ai_eval_{judge.lower()}:judgements/{oid}.json#/claim_units/{unit['appearance_index'] - 1}",
                })
            for event in events or []:
                registry.error_events.append({
                    "evaluator": judge,
                    "role": "PRIMARY_JUDGE",
                    "output_id": oid,
                    "topic_id": run["topic_id"],
                    "task_id": run["task_id"],
                    "arm": run["arm"],
                    "repetition": run["repetition"],
                    "error_id": event["error_id"],
                    "affected_appearance_indices": list(event["affected_appearance_indices"]),
                    "error_types": list(event["error_types"]),
                    "source_package_id": f"ai_eval_{judge.lower()}",
                    "source_file_sha256": sha256_file(path),
                    "source_locator": f"ai_eval_{judge.lower()}:judgements/{oid}.json#/substantive_error_events",
                })

    for judge in PRIMARY_JUDGES:
        registry.source_identities[f"{judge.lower()}_package_manifest_sha256"] = sha256_file(
            judge_dirs[judge] / "SHA256_manifest.txt")

    if supplement_zip and Path(supplement_zip).exists():
        _load_full_pro(registry, supplement_zip, outputs_by_id, claims_by_output,
                       formal_manifest_hashes, rubric_sha=rubric_sha,
                       task_instructions=task_instruction_by_oid,
                       research_questions=research_question_by_oid)

    primary_units = [r for r in registry.claim_judgements if r["role"] == "PRIMARY_JUDGE"]
    primary_evals = [r for r in registry.evaluations if r["role"] == "PRIMARY_JUDGE"]
    registry.validation = {
        "outputs": len(registry.outputs),
        "claims": len(registry.claims),
        "primary_evaluations": len(primary_evals),
        "sensitivity_evaluations": len(registry.evaluations) - len(primary_evals),
        "primary_claim_judgements": len(primary_units),
        "sensitivity_claim_judgements": len(registry.claim_judgements) - len(primary_units),
        "lattice": "2x2x2x3",
        "lattice_complete": lattice == {(t, k, a, rep) for t in topics for k in tasks for a in ARMS for rep in REPETITIONS},
        "per_judge": validation_rows,
        "e_status_counts": {
            status: sum(1 for r in validation_rows if r["event_structure"] == status)
            for status in sorted({r["event_structure"] for r in validation_rows})
        },
        "claims_per_output": sorted({r["claims_count"] for r in registry.outputs}),
        "sensitivity_evaluator_excluded_from_primary": all(
            r["role"] != "PRIMARY_JUDGE" or r["evaluator"] in PRIMARY_JUDGES for r in registry.evaluations
        ),
    }
    _check(len(registry.claims) == sum(r["claims_count"] for r in registry.outputs), "claim count mismatch")
    registry.validation["full_pro_binding"] = registry.full_pro_binding or {"status": "NOT_LOADED"}
    return registry


def _load_full_pro(registry: CanonicalRegistry, supplement_path: Path, outputs_by_id, claims_by_output,
                   formal_manifest_hashes: dict, rubric_sha: str | None = None,
                   task_instructions: dict[str, str] | None = None,
                   research_questions: dict[str, str] | None = None,
                   allow_partial_sensitivity: bool = False) -> None:
    supplement_path = Path(supplement_path)
    if supplement_path.is_dir():
        pro_file = next(supplement_path.rglob("PRO_FULL_BLIND_AUDIT_144.json"))
        pro_bytes = pro_file.read_bytes()
    else:
        with zipfile.ZipFile(supplement_path) as archive:
            member = next(m for m in archive.namelist() if m.endswith("PRO_FULL_BLIND_AUDIT_144.json"))
            pro_bytes = archive.read(member)
    pro_sha = sha256_bytes(pro_bytes)
    doc = json.loads(pro_bytes.decode("utf-8"))
    pro_package = "meeting_supplement_pro_full"

    # R2: exact output roster — the sensitivity evaluator must cover exactly
    # the formal 24 outputs, uniquely, with no missing/unexpected entries.
    doc_output_ids = [out.get("output_id") for out in doc.get("outputs", [])]
    expected_ids = set(outputs_by_id)
    seen = set()
    for oid in doc_output_ids:
        if oid in seen:
            raise CanonicalBuildError(f"FullPro: duplicate output_id {oid} in supplement")
        seen.add(oid)
    if not allow_partial_sensitivity:
        missing = sorted(expected_ids - seen)
        unexpected = sorted(seen - expected_ids)
        if missing or unexpected or len(doc_output_ids) != len(outputs_by_id):
            raise CanonicalBuildError(
                f"FullPro output roster mismatch: missing={missing[:3]} unexpected={unexpected[:3]} "
                f"doc={len(doc_output_ids)} expected={len(outputs_by_id)}")
    evaluation_ids = [out.get("evaluation_id") for out in doc.get("outputs", [])]
    if len(set(evaluation_ids)) != len(evaluation_ids):
        raise CanonicalBuildError("FullPro: duplicate evaluation_id in supplement")

    binding_checked = binding_matched = 0
    binding_unverifiable = 0
    for output_index, out in enumerate(doc["outputs"]):
        oid = out["output_id"]
        if oid not in outputs_by_id:
            continue
        run = outputs_by_id[oid]
        gen_claims = claims_by_output[oid]
        pro_claims = out["claims"]
        if len(pro_claims) != len(gen_claims):
            raise CanonicalBuildError(f"FullPro/{oid}: claim count mismatch")

        # R14/C2: verify every binding field whose source bytes are obtainable.
        # A present expected digest over obtainable source bytes MUST match --
        # mismatch fails closed; only genuinely unavailable sources stay
        # unverifiable (QUALIFIED), never silently accepted.
        binding = out.get("source_binding", {})
        obtainable = {
            "context_sha256_utf8": run["context_sha256"],
            "output_sha256_raw_bytes": formal_manifest_hashes.get(
                f"public_blinded_outputs/{oid}/generator_output.json"),
            "input_sha256_raw_bytes": formal_manifest_hashes.get(
                f"public_blinded_outputs/{oid}/input.json"),
        }
        if task_instructions and oid in task_instructions:
            obtainable["task_sha256_utf8"] = sha256_bytes(task_instructions[oid].encode("utf-8"))
        if research_questions and oid in research_questions:
            obtainable["research_question_sha256_utf8"] = sha256_bytes(
                research_questions[oid].encode("utf-8"))
        if rubric_sha:
            obtainable["rubric_sha256_raw_bytes"] = rubric_sha
        for field, actual in obtainable.items():
            expected = binding.get(field)
            if not expected:
                continue
            binding_checked += 1
            if expected == actual:
                binding_matched += 1
            else:
                raise CanonicalBuildError(
                    f"FullPro/{oid}: binding field {field} does not match current source bytes "
                    f"(expected {expected[:12]}, computed {str(actual)[:12]})")
        binding_unverifiable += sum(
            1 for field in ("semantic_constraints_sha256_raw_bytes",)
            if binding.get(field) and field not in obtainable
        )

        registry.evaluations.append({
            "evaluator": SENSITIVITY_EVALUATOR,
            "role": "SENSITIVITY_EVALUATOR",
            "output_id": oid,
            "evaluation_id": out["evaluation_id"],
            "rubric_sha256": binding.get("rubric_sha256_raw_bytes", ""),
            "task_binding_sha256": binding.get("task_sha256_utf8", ""),
            "context_binding_sha256": binding.get("context_sha256_utf8", ""),
            "generator_output_sha256": binding.get("output_sha256_raw_bytes", ""),
            "judgement_file_sha256": pro_sha,
            "schema_status": "NO_FROZEN_SCHEMA_AT_CREATION_SENSITIVITY_ONLY",
            "valid_abstention": False,
            "exact_match_checks": None,
            "source_locator": f"meeting_supplement_pro_full:PRO_FULL_BLIND_AUDIT_144.json#/outputs/{output_index}",
        })
        # R3: event structural validation uses the same frozen rules as the
        # primary judges; the sensitivity role never relaxes E-structure checks.
        pro_events = out.get("error_events", [])
        event_ids = [str(event.get("error_id")) for event in pro_events]
        if len(set(event_ids)) != len(event_ids):
            raise CanonicalBuildError(f"FullPro/{oid}: duplicate error_id in supplement events")
        for event in pro_events:
            affected = {int(i) for i in _as_list(event.get("affected_appearance_indices"))}
            if not affected <= {claim.get("appearance_index") for claim in
                                [{**c, "appearance_index": idx + 1} for idx, c in enumerate(pro_claims)]}:
                raise CanonicalBuildError(f"FullPro/{oid}: orphan affected index in event {event.get('error_id')}")
            linked = {idx + 1 for idx, claim in enumerate(pro_claims)
                      if str(event.get("error_id")) in [str(e) for e in _as_list(claim.get("error_ids"))]}
            if linked != affected:
                raise CanonicalBuildError(f"FullPro/{oid}: nonreciprocal event link {event.get('error_id')}")
        known_events = set(event_ids)
        for idx, claim in enumerate(pro_claims, start=1):
            linked_ids = [str(e) for e in _as_list(claim.get("error_ids"))]
            if not set(linked_ids) <= known_events:
                raise CanonicalBuildError(f"FullPro/{oid}: unknown event link at claim {idx}")
            support = str(claim.get("support", ""))
            scope = str(claim.get("scope", ""))
            if ((support in ("UNSUPPORTED", "CONTRADICTED") or scope == "OUT_OF_SCOPE")
                    and not linked_ids):
                raise CanonicalBuildError(f"FullPro/{oid}: missing required event coverage at claim {idx}")

        # Strict per-claim alignment (F3): each sensitivity row must be proven
        # to judge the exact generator claim it claims to judge.
        for claim_index, (claim, gen_claim) in enumerate(zip(pro_claims, gen_claims), start=1):
            appearance = claim.get("appearance_index")
            if isinstance(appearance, str):
                appearance = appearance.strip()
                appearance = int(appearance) if appearance.isdigit() else None
            if appearance != claim_index:
                raise CanonicalBuildError(
                    f"FullPro/{oid}: appearance_index {claim.get('appearance_index')!r} != expected {claim_index}")
            slot = str(claim.get("slot_id", ""))
            if slot and slot != str(gen_claim["slot_id"]):
                raise CanonicalBuildError(f"FullPro/{oid}: slot_id drift at {claim_index}")
            if claim.get("claim_text") != gen_claim["claim_text"]:
                raise CanonicalBuildError(f"FullPro/{oid}: claim_text drift at appearance_index {claim_index}")
            pro_scope = claim.get("scope_or_qualification")
            if pro_scope is not None and str(pro_scope) != str(gen_claim.get("scope_or_qualification") or ""):
                raise CanonicalBuildError(f"FullPro/{oid}: scope_or_qualification drift at {claim_index}")
            registry.claim_judgements.append({
                "evaluator": SENSITIVITY_EVALUATOR,
                "role": "SENSITIVITY_EVALUATOR",
                "output_id": oid,
                "topic_id": run["topic_id"],
                "task_id": run["task_id"],
                "arm": run["arm"],
                "repetition": run["repetition"],
                "appearance_index": claim_index,
                "atomic": _as_bool(claim["atomic"]),
                "support": str(claim["support"]),
                "scope": str(claim["scope"]),
                "redundancy": str(claim["redundancy"]),
                "error_ids": [str(e) for e in _as_list(claim.get("error_ids"))],
                "has_linked_error": bool(_as_list(claim.get("error_ids"))),
                "source_package_id": pro_package,
                "source_file_sha256": pro_sha,
                "source_locator": (f"meeting_supplement_pro_full:PRO_FULL_BLIND_AUDIT_144.json"
                                   f"#/outputs/{output_index}/claims/{claim_index - 1}"),
            })
        for event_index, event in enumerate(out.get("error_events", [])):
            registry.error_events.append({
                "evaluator": SENSITIVITY_EVALUATOR,
                "role": "SENSITIVITY_EVALUATOR",
                "output_id": oid,
                "topic_id": run["topic_id"],
                "task_id": run["task_id"],
                "arm": run["arm"],
                "repetition": run["repetition"],
                "error_id": str(event.get("error_id")),
                "affected_appearance_indices": [int(i) for i in _as_list(event.get("affected_appearance_indices"))],
                "error_types": [str(t) for t in _as_list(event.get("error_types"))],
                "source_package_id": pro_package,
                "source_file_sha256": pro_sha,
                "source_locator": (f"meeting_supplement_pro_full:PRO_FULL_BLIND_AUDIT_144.json"
                                   f"#/outputs/{output_index}/error_events/{event_index}"),
            })
    roster_closed = (set(doc_output_ids) == set(outputs_by_id)
                     and len(doc_output_ids) == len(outputs_by_id))
    binding_closed = binding_checked > 0 and binding_matched == binding_checked
    registry.full_pro_binding = {
        "output_roster_closed": roster_closed,
        "claim_alignment_closed": True,  # any drift raised above
        "binding_fields_checked": binding_checked,
        "binding_fields_matched": binding_matched,
        "binding_fields_unverifiable_no_source": binding_unverifiable,
        "supplement_pro_file_sha256": pro_sha,
        "status": ("VERIFIED_EDGE" if (roster_closed and binding_closed and binding_unverifiable == 0)
                   else "QUALIFIED"),
    }


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value.replace("'", '"'))
            return parsed if isinstance(parsed, list) else [parsed]
        except ValueError:
            return [value] if value else []
    return list(value)


def _parse_formal_manifest_hashes(formal_dir: Path) -> dict[str, str]:
    from .integrity import parse_sha_manifest

    return parse_sha_manifest(formal_dir / "SHA256_manifest.txt")
