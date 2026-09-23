"""Automated tests for the downstream measurement infrastructure.

Deterministic, offline, synthetic: a miniature evidence root with the real
package layout is generated inside a temp directory. No external evidence,
network, LLM, or repository mutation is involved.
"""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from fractions import Fraction
from pathlib import Path

from src.downstream_measurement import util
from src.downstream_measurement.canonical import (
    CanonicalBuildError,
    build_canonical,
)
from src.downstream_measurement.counterfactual import build_counterfactual, unit_score_variant
from src.downstream_measurement.dag import _walk_hash_bindings
from src.downstream_measurement.decomposition import decompose_output
from src.downstream_measurement.error_audit import build_error_audit
from src.downstream_measurement.first_look import (
    aggregate,
    output_score_rows,
    reproduce_first_look,
    useful_slots,
)
from src.downstream_measurement.influence import build_influence
from src.downstream_measurement.integrity import parse_sha_manifest, verify_package
from src.downstream_measurement.sensitivity import pairwise_agreement, unit_table
from src.downstream_measurement.inventory import _declared_status


def unit(index=1, atomic=True, support="SUPPORTED", scope="IN_SCOPE",
         redundancy="NONREDUNDANT", role="PRIMARY_JUDGE", **run):
    row = {
        "evaluator": "J", "role": role, "output_id": "o1", "topic_id": "t1", "task_id": "A",
        "arm": "BM25", "repetition": 1, "appearance_index": index, "atomic": atomic,
        "support": support, "scope": scope, "redundancy": redundancy,
        "error_ids": [], "has_linked_error": False, "source_locator": "synthetic",
    }
    row.update(run)
    return row


class MiniEvidenceRoot:
    """Builds a minimal but structurally faithful evidence root in a temp dir."""

    TOPICS = ["topic_x", "topic_y"]
    TASKS = ["A", "B"]
    ARMS = ["BM25", "MCA"]
    JUDGES = ["GPT", "DeepSeek", "GLM"]

    def __init__(self, root: Path):
        self.root = root
        self.prep = root / "DOWNSTREAM_EXPERIMENT_PREP_20260906"
        self.formal = root / "DOWNSTREAM_CODEX_FORMAL_EXECUTION_20260906"
        self.runs = []
        self._build()

    def _build(self):
        conditions = []
        for topic in self.TOPICS:
            for arm in self.ARMS:
                conditions.append({
                    "arm": arm,
                    "topic_id": topic,
                    "context_sha256": util.sha256_bytes(f"context-{topic}-{arm}".encode()),
                    "context_token_count": 1000 + len(topic),
                    "opaque_condition_id": f"cond_{topic}_{arm}",
                    "ordered_canonical_entity_ids": [],
                })
        (self.prep / "contexts" / "private_mapping").mkdir(parents=True)
        (self.prep / "protocol").mkdir(parents=True)
        mapping_rel = "contexts/private_mapping/condition_mapping.json"
        (self.prep / mapping_rel).write_text(json.dumps(conditions), encoding="utf-8")

        plan_runs = []
        for topic in self.TOPICS:
            for task in self.TASKS:
                for arm in self.ARMS:
                    for rep in (1, 2, 3):
                        oid = f"output_{topic[-1]}{task}{arm}{rep}"
                        condition = next(c for c in conditions if c["topic_id"] == topic and c["arm"] == arm)
                        plan_runs.append({
                            "output_id": oid, "topic_id": topic, "task_id": task, "arm": arm,
                            "repetition": rep, "opaque_condition_id": condition["opaque_condition_id"],
                            "context_sha256": condition["context_sha256"],
                            "exact_task_instruction": f"do task {task} for {topic}",
                        })
        self.runs = plan_runs
        plan = {"runs": plan_runs}
        (self.prep / "protocol" / "private_execution_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (self.prep / "protocol" / "HUMAN_EVALUATION_RUBRIC_V1.md").write_text("# rubric", encoding="utf-8")
        (self.prep / "protocol" / "human_evaluation_schema.json").write_text("{}", encoding="utf-8")
        protocol = {
            "topics": [{"topic_id": t} for t in self.TOPICS],
            "matrix": {"tasks": self.TASKS, "arms": self.ARMS},
            "blinding": {"private_condition_map": mapping_rel},
            "source_files": {
                "protocol/private_execution_plan.json": util.sha256_file(
                    self.prep / "protocol" / "private_execution_plan.json"),
            },
        }
        (self.prep / "protocol" / "downstream_experiment_protocol_v1.json").write_text(
            json.dumps(protocol), encoding="utf-8")

        self.formal.mkdir(parents=True)
        public = self.formal / "public_blinded_outputs"
        for run in plan_runs:
            out_dir = public / run["output_id"]
            out_dir.mkdir(parents=True)
            context = f"context-{run['topic_id']}-{run['arm']}"
            input_doc = {
                "output_id": run["output_id"], "research_question": f"rq-{run['topic_id']}",
                "task_id": run["task_id"], "task_instruction": run["exact_task_instruction"],
                "evidence_context": context,
            }
            claims = [{"slot_id": f"S{i}", "claim_text": f"claim {run['output_id']} #{i}",
                       "evidence_quotes": ["q"], "source_titles": ["t"],
                       "scope_or_qualification": ""} for i in (1, 2)]
            gen_doc = {"task_id": run["task_id"], "claims": claims, "abstained": False}
            (out_dir / "input.json").write_text(json.dumps(input_doc), encoding="utf-8")
            (out_dir / "generator_output.json").write_text(json.dumps(gen_doc), encoding="utf-8")
        self._write_formal_manifest()

        snapshot_key = str(self.prep)
        freeze_binding = {"source_snapshot": {snapshot_key: {
            mapping_rel: util.sha256_file(self.prep / mapping_rel),
            "protocol/private_execution_plan.json": util.sha256_file(
                self.prep / "protocol" / "private_execution_plan.json"),
        }}}
        (self.formal / "source_freeze_binding.json").write_text(json.dumps(freeze_binding), encoding="utf-8")
        formal_manifest = {
            "status": "COMPLETE",
            "operational_summary": {"technically_completed_outputs": len(plan_runs)},
            "preparation_protocol_sha256": util.sha256_file(
                self.prep / "protocol" / "downstream_experiment_protocol_v1.json"),
            "provider": "synthetic", "model": "mini", "reasoning_effort": "none", "codex_cli": "test",
            "generator_freeze_v2_sha256": "0" * 64,
        }
        self.formal_manifest = formal_manifest
        (self.formal / "formal_execution_manifest.json").write_text(json.dumps(formal_manifest), encoding="utf-8")

        self.judgement_specs = {}
        for judge in self.JUDGES:
            jdir = self.root / f"DOWNSTREAM_AI_EVAL_{judge.upper()}_20260915" / "judgements"
            jdir.mkdir(parents=True)
            for run in plan_runs:
                units = []
                for i in (1, 2):
                    fail = (judge == "GPT" and run["arm"] == "BM25" and i == 1)
                    units.append({
                        "appearance_index": i, "submitted_slot_id": f"S{i}",
                        "atomic": not fail, "support": "SUPPORTED", "scope": "IN_SCOPE",
                        "redundancy": "NONREDUNDANT", "redundancy_of_indices": [],
                        "error_ids": ["E1"] if fail else [], "exact_output_span": f"claim {run['output_id']} #{i}",
                    })
                events = ([{"error_id": "E1", "affected_appearance_indices": [1],
                            "error_types": ["task_boundary_misuse"]}]
                          if judge == "GPT" and run["arm"] == "BM25" else [])
                judgement = {
                    "output_id": run["output_id"], "evaluation_id": f"eval-{judge}-{run['output_id']}",
                    "input_sha256": None, "claim_units": units, "substantive_error_events": events,
                    "output_schema_valid": True, "valid_abstention": False,
                    "exact_match_checks": {"quote_occurrences": 0, "source_title_occurrences": 0,
                                           "valid_quote_occurrences": 0, "valid_source_title_occurrences": 0},
                }
                self.judgement_specs[(judge, run["output_id"])] = judgement
        self._write_judgements()
        self._write_required_package_manifests()

    def _write_required_package_manifests(self):
        # The byte-integrity chain requires every formal package. Minimal
        # synthetic placeholders cover packages whose contents this fixture
        # does not model; no production evidence or frozen fixture is changed.
        from src.downstream_measurement.inventory import FORMAL_CHAIN_PACKAGES, resolve_package_directory

        for package_id in sorted(FORMAL_CHAIN_PACKAGES):
            package = resolve_package_directory(self.root, package_id)
            package.mkdir(exist_ok=True)
            manifest = package / "SHA256_manifest.txt"
            if manifest.exists():
                continue
            files = sorted(p for p in package.rglob("*") if p.is_file())
            if not files:
                marker = package / "synthetic_fixture.txt"
                marker.write_text("Synthetic byte-integrity fixture only.\n", encoding="utf-8")
                files = [marker]
            manifest.write_text("".join(
                f"{util.sha256_file(p)}  {p.relative_to(package).as_posix()}\n" for p in files
            ), encoding="utf-8")

    def _write_formal_manifest(self):
        lines = []
        for path in sorted((self.formal / "public_blinded_outputs").rglob("*")):
            if path.is_file():
                lines.append(f"{util.sha256_file(path)}  {path.relative_to(self.formal).as_posix()}")
        (self.formal / "SHA256_manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_judgements(self):
        from src.downstream_measurement.canonical import _task_hash

        rubric_sha = util.sha256_file(self.prep / "protocol" / "HUMAN_EVALUATION_RUBRIC_V1.md")
        for (judge, oid), judgement in self.judgement_specs.items():
            run = next(r for r in self.runs if r["output_id"] == oid)
            input_doc = json.loads((self.formal / "public_blinded_outputs" / oid / "input.json").read_text("utf-8"))
            gen_hash = util.sha256_file(self.formal / "public_blinded_outputs" / oid / "generator_output.json")
            judgement["input_sha256"] = {
                "context": run["context_sha256"], "generator_output": gen_hash,
                "task": _task_hash(judge, input_doc["research_question"], input_doc["task_instruction"]),
                "rubric": rubric_sha,
            }
            jdir = self.root / f"DOWNSTREAM_AI_EVAL_{judge.upper()}_20260915" / "judgements"
            (jdir / f"{oid}.json").write_text(json.dumps(judgement), encoding="utf-8")
        self._write_judge_package_manifests()

    def _write_judge_package_manifests(self):
        for judge in self.JUDGES:
            package = self.root / f"DOWNSTREAM_AI_EVAL_{judge.upper()}_20260915"
            lines = []
            for path in sorted(package.rglob("*.json")):
                lines.append(f"{util.sha256_file(path)}  {path.relative_to(package).as_posix()}")
            content = chr(10).join(lines) + chr(10)
            (package / "SHA256_manifest.txt").write_text(content, encoding="utf-8")

    def write_supplement_zip(self, path: Path, atomic_override=None, support_override=None):
        pro_outputs = []
        for run in self.runs:
            units = []
            for i in (1, 2):
                fail = run["arm"] == "MCA" and i == 2 and run["task_id"] == "B"
                units.append({
                    "appearance_index": i, "slot_id": f"S{i}",
                    "claim_text": f"claim {run['output_id']} #{i}",
                    "atomic": (atomic_override if atomic_override is not None else not fail),
                    "support": support_override or "SUPPORTED", "scope": "IN_SCOPE",
                    "redundancy": "NONREDUNDANT", "redundancy_of_indices": [],
                    "error_types": [], "error_ids": [],
                })
            pro_outputs.append({
                "evaluation_id": f"pro-{run['output_id']}", "output_id": run["output_id"],
                "claims": units, "error_events": [],
                "source_binding": {"context_sha256_utf8": run["context_sha256"]},
            })
        rubric_sha = util.sha256_file(self.prep / "protocol" / "HUMAN_EVALUATION_RUBRIC_V1.md")
        formal_manifest = {}
        for line in (self.formal / "SHA256_manifest.txt").read_text(encoding="utf-8").splitlines():
            if line.strip():
                digest, rel = line.split(None, 1)
                formal_manifest[rel.strip()] = digest
        for out in pro_outputs:
            oid = out["output_id"]
            input_doc = json.loads((self.formal / "public_blinded_outputs" / oid / "input.json").read_text("utf-8"))
            out["source_binding"] = {
                "context_sha256_utf8": next(r["context_sha256"] for r in self.runs if r["output_id"] == oid),
                "output_sha256_raw_bytes": formal_manifest[f"public_blinded_outputs/{oid}/generator_output.json"],
                "input_sha256_raw_bytes": formal_manifest[f"public_blinded_outputs/{oid}/input.json"],
                "task_sha256_utf8": util.sha256_bytes(input_doc["task_instruction"].encode("utf-8")),
                "research_question_sha256_utf8": util.sha256_bytes(input_doc["research_question"].encode("utf-8")),
                "rubric_sha256_raw_bytes": rubric_sha,
                "semantic_constraints_sha256_raw_bytes": "f" * 64,  # genuinely unavailable source
            }
        doc = {"audit_id": "mini", "outputs": pro_outputs}
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("SRTP_MEETING_LATEST_SUPPLEMENT_20260919/PRO_FULL_BLIND_AUDIT_144.json",
                             json.dumps(doc))


class TestUtil(unittest.TestCase):
    def test_absolute_path_leak_detection(self):
        leaks = util.find_absolute_path_leaks({"a": "D:\\UserData\\desktop\\MVP", "b": "C:/x", "c": "relative/path"})
        self.assertEqual(len(leaks), 2)

    def test_assert_no_absolute_paths_raises(self):
        with self.assertRaises(AssertionError):
            util.assert_no_absolute_paths({"x": "/" + "Users" + "/foo/bar"}, "test")

    def test_safe_output_dir_rejects_inside_evidence_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                util.safe_output_dir(root / "inside", [root])

    def test_atomic_write_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sub" / "f.json"
            util.atomic_write_json(target, {"a": 1})
            util.atomic_write_json(target, {"a": 2})
            self.assertEqual(json.loads(target.read_text("utf-8"))["a"], 2)
            leftovers = [p for p in target.parent.iterdir() if p.name.startswith(".")]
            self.assertEqual(leftovers, [])


class TestMetricSemantics(unittest.TestCase):
    def test_useful_slots_first_six_only(self):
        units = [unit(i) for i in range(1, 9)]
        self.assertEqual(useful_slots(units), 6)

    def test_useful_slots_four_way_predicate_no_partial_credit(self):
        for key, value in (("atomic", False), ("support", "PARTIALLY_SUPPORTED"),
                           ("scope", "OUT_OF_SCOPE"), ("redundancy", "REDUNDANT")):
            self.assertEqual(useful_slots([dict(unit(1), **{key: value})]), 0)

    def test_error_count_is_event_cardinality(self):
        events = [
            {"evaluator": "J", "output_id": "o1", "error_id": "E1",
             "affected_appearance_indices": [1, 2], "error_types": ["a", "b"]},
            {"evaluator": "J", "output_id": "o1", "error_id": "E2",
             "affected_appearance_indices": [1], "error_types": ["c"]},
        ]
        scores = output_score_rows([unit(1, role="PRIMARY_JUDGE")], events)
        self.assertEqual(scores[0]["substantive_error_count"], 2)

    def test_aggregate_macro_exact_rational(self):
        rows = []
        for topic in ("t1", "t2"):
            for task in ("A", "B"):
                for arm, u_values in (("BM25", [4, 5, 6]), ("MCA", [6, 5, 6])):
                    for rep, u in zip((1, 2, 3), u_values):
                        rows.append({"evaluator": "J", "output_id": f"{topic}{task}{arm}{rep}",
                                     "topic_id": topic, "task_id": task, "arm": arm,
                                     "repetition": rep, "useful_information_slots": u,
                                     "substantive_error_count": 1, "submitted_claim_count": 6,
                                     "role": "PRIMARY_JUDGE"})
        result = aggregate(rows, "J")
        self.assertEqual(result["macro"]["BM25_mean_U"], Fraction(5))
        self.assertEqual(result["macro"]["MCA_mean_U"], Fraction(Fraction(17, 3)))
        self.assertEqual(result["macro"]["Delta_U"], Fraction(2, 3))
        self.assertEqual(result["macro"]["U_direction"], "MCA_HIGHER")

    def test_direction_fixed_mca_minus_bm25(self):
        rows = []
        for topic in ("t1", "t2"):
            for task in ("A", "B"):
                for arm, u_values in (("BM25", [6, 6, 6]), ("MCA", [4, 4, 4])):
                    for rep, u in zip((1, 2, 3), u_values):
                        rows.append({"evaluator": "J", "output_id": f"{topic}{task}{arm}{rep}",
                                     "topic_id": topic, "task_id": task, "arm": arm, "repetition": rep,
                                     "useful_information_slots": u, "substantive_error_count": 0,
                                     "submitted_claim_count": 6, "role": "PRIMARY_JUDGE"})
        result = aggregate(rows, "J")
        self.assertEqual(result["macro"]["U_direction"], "MCA_LOWER")


class TestDecomposition(unittest.TestCase):
    def test_partition_identity(self):
        units = [
            unit(1),
            unit(2, atomic=False),
            unit(3, scope="OUT_OF_SCOPE"),
            unit(4, support="UNSUPPORTED"),
            unit(5, redundancy="REDUNDANT"),
            unit(6, atomic=False, scope="OUT_OF_SCOPE"),
        ]
        d = decompose_output(units)
        self.assertEqual(d["U_original"], 1)
        self.assertEqual(d["B_atomic_only_failure"], 1)
        self.assertEqual(d["E_f_fail_SCN"], 4)
        self.assertTrue(d["identity_holds"])
        self.assertEqual(d["failure_combinations"]["A"], 1)
        self.assertEqual(d["failure_combinations"]["C"], 1)
        self.assertEqual(d["failure_combinations"]["A+C"], 1)


class TestSensitivity(unittest.TestCase):
    def test_kappa_not_computed_for_degenerate_rater(self):
        table = {
            ("A", "o", 1): {"atomic": "True"}, ("A", "o", 2): {"atomic": "True"},
            ("B", "o", 1): {"atomic": "True"}, ("B", "o", 2): {"atomic": "False"},
        }
        row = pairwise_agreement(table, "A", "B", lambda u: u["atomic"])
        self.assertIsNone(row["kappa"])
        self.assertIn("DEGENERATE", row["kappa_status"])
        self.assertEqual(row["raw_agreement"], 0.5)

    def test_kappa_computed_when_both_vary(self):
        table = {
            ("A", "o", 1): {"atomic": "True"}, ("A", "o", 2): {"atomic": "False"},
            ("A", "o", 3): {"atomic": "True"},
            ("B", "o", 1): {"atomic": "True"}, ("B", "o", 2): {"atomic": "False"},
            ("B", "o", 3): {"atomic": "False"},
        }
        row = pairwise_agreement(table, "A", "B", lambda u: u["atomic"])
        self.assertIsInstance(row["kappa"], float)
        self.assertGreater(row["kappa"], -1.0)
        self.assertEqual(row["raw_agreement"], 2 / 3)

    def test_full_pro_never_enters_primary_aggregate(self):
        rows = []
        for topic in ("t1", "t2"):
            for task in ("A", "B"):
                for arm in ("BM25", "MCA"):
                    for rep in (1, 2, 3):
                        rows.append(unit(1, evaluator="GPT", topic_id=topic, task_id=task,
                                         arm=arm, repetition=rep, output_id=f"{topic}{task}{arm}{rep}"))
        rows.append(unit(1, evaluator="FullPro", role="SENSITIVITY_EVALUATOR",
                         topic_id="t1", task_id="A", arm="BM25", repetition=1, output_id="s1"))
        registry = {"claim_judgements": rows, "error_events": []}
        result = reproduce_first_look(registry)
        self.assertEqual(result["roles"]["primary_evaluators"], ["GPT"])
        self.assertEqual(result["roles"]["sensitivity_evaluators"], ["FullPro"])
        self.assertNotIn("FullPro", result["primary"])


class TestCounterfactual(unittest.TestCase):
    def test_unit_scores(self):
        good = unit(1)
        self.assertEqual(unit_score_variant(good, "U_original"), Fraction(1))
        self.assertEqual(unit_score_variant(good, "U_lambda", Fraction(1, 2)), Fraction(1))
        non_atomic = unit(2, atomic=False)
        self.assertEqual(unit_score_variant(non_atomic, "U_lambda", Fraction(1, 4)), Fraction(1, 4))
        self.assertEqual(unit_score_variant(non_atomic, "U_original"), Fraction(0))
        self.assertEqual(unit_score_variant(non_atomic, "U_without_atomicity"), Fraction(1))
        out_scope = unit(3, scope="OUT_OF_SCOPE")
        self.assertEqual(unit_score_variant(out_scope, "U_without_atomicity"), Fraction(0))
        self.assertEqual(unit_score_variant(out_scope, "U_without_scope"), Fraction(1))
        unsupported = unit(4, support="UNSUPPORTED")
        self.assertEqual(unit_score_variant(unsupported, "U_without_scope"), Fraction(0))
        self.assertEqual(unit_score_variant(unsupported, "U_support_only"), Fraction(0))

    def test_lambda_flip_detected_on_synthetic(self):
        registry = {"claim_judgements": []}
        result = build_counterfactual(registry)
        self.assertEqual(result["status"].startswith("DIAGNOSTIC"), True)


class TestErrorAudit(unittest.TestCase):
    def test_generic_and_subtype_counting(self):
        registry = {
            "error_events": [
                {"evaluator": "J", "role": "PRIMARY_JUDGE", "output_id": "o1", "topic_id": "t", "task_id": "A",
                 "arm": "BM25", "repetition": 1, "error_id": "E1",
                 "affected_appearance_indices": [1], "error_types": ["task_boundary_misuse"]},
                {"evaluator": "J", "role": "PRIMARY_JUDGE", "output_id": "o2", "topic_id": "t", "task_id": "A",
                 "arm": "MCA", "repetition": 1, "error_id": "E2",
                 "affected_appearance_indices": [2], "error_types": ["wrong_target_task"]},
            ],
        }
        audit = build_error_audit(registry)
        self.assertEqual(audit["counts"]["events_with_generic_boundary_tag"], 1)
        self.assertEqual(audit["counts"]["events_with_subtype_tag_but_without_generic"], 1)
        self.assertIn("wrong_target_task", audit["counts"]["subtype_tags_outside_generic"])
        self.assertFalse(audit["generic_boundary_counting_semantics"]["current_first_look_affected"])


class TestIntegrityAndDagHelpers(unittest.TestCase):
    def test_parse_sha_manifest_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "pkg"
            (package / "a").mkdir(parents=True)
            (package / "a" / "f.txt").write_text("x", encoding="utf-8")
            (package / "SHA256_manifest.txt").write_text(
                util.sha256_file(package / "a" / "f.txt") + "  a/f.txt\n", encoding="utf-8")
            entries = parse_sha_manifest(package / "SHA256_manifest.txt")
            self.assertEqual(entries, {"a/f.txt": util.sha256_file(package / "a" / "f.txt")})
            result = verify_package(package, "pkg")
            self.assertEqual(result["summary"]["verified"], 1)
            (package / "a" / "f.txt").write_text("tampered", encoding="utf-8")
            result = verify_package(package, "pkg")
            self.assertEqual(result["summary"]["mismatched"], 1)

    def test_walk_hash_bindings(self):
        found = list(_walk_hash_bindings({"k": "a" * 64, "n": "notahash", "path": "x/related.json"}))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["pointer"], "$/k")
        self.assertEqual(found[0]["path_hints"], ["x/related.json"])

    def test_declared_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "README.md"
            p.write_text("# t\n\nSTATUS = BLOCKED\n", encoding="utf-8")
            self.assertEqual(_declared_status(p), "STATUS = BLOCKED")


class TestCanonicalMiniEvidence(unittest.TestCase):
    def _build_root(self, tmp):
        return MiniEvidenceRoot(Path(tmp))

    def test_happy_path_counts_and_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = self._build_root(tmp)
            registry = build_canonical(mini.root, None)
            v = registry.validation
            self.assertEqual(v["outputs"], 24)
            self.assertEqual(v["claims"], 48)
            self.assertEqual(v["primary_evaluations"], 72)
            self.assertEqual(v["primary_claim_judgements"], 144)
            self.assertEqual(v["sensitivity_claim_judgements"], 0)
            self.assertTrue(v["lattice_complete"])
            self.assertEqual(set(v["e_status_counts"]), {"PASS"})
            reproduction = reproduce_first_look(registry.to_dict())
            gpt = reproduction["primary"]["GPT"]
            self.assertEqual(gpt["macro"]["Delta_U"], Fraction(1))
            self.assertEqual(reproduction["primary"]["GLM"]["macro"]["Delta_U"], Fraction(0))

    def test_supplement_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = self._build_root(tmp)
            zpath = Path(tmp) / "supp.zip"
            mini.write_supplement_zip(zpath)
            registry = build_canonical(mini.root, zpath)
            v = registry.validation
            self.assertEqual(v["sensitivity_evaluations"], 24)
            self.assertEqual(v["sensitivity_claim_judgements"], 48)
            binding = v["full_pro_binding"]
            self.assertTrue(binding["output_roster_closed"])
            self.assertEqual(binding["binding_fields_matched"], binding["binding_fields_checked"])
            self.assertGreaterEqual(binding["binding_fields_unverifiable_no_source"], 24)
            self.assertEqual(binding["status"], "QUALIFIED")  # semantic_constraints source unavailable -> QUALIFIED, not VERIFIED
            roles = {row["role"] for row in registry.evaluations if row["evaluator"] == "FullPro"}
            self.assertEqual(roles, {"SENSITIVITY_EVALUATOR"})
            result = reproduce_first_look(registry.to_dict())
            self.assertNotIn("FullPro", result["primary"])
            self.assertIn("FullPro", result["sensitivity"])

    def test_hash_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = self._build_root(tmp)
            victim = mini.formal / "public_blinded_outputs" / mini.runs[0]["output_id"] / "generator_output.json"
            victim.write_text(json.dumps({"task_id": "A", "claims": [{"slot_id": "S1", "claim_text": "x",
                                                                      "evidence_quotes": [], "source_titles": []}]}),
                              encoding="utf-8")
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, None)

    def test_duplicate_output_id_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = self._build_root(tmp)
            plan_path = mini.prep / "protocol" / "private_execution_plan.json"
            plan = json.loads(plan_path.read_text("utf-8"))
            plan["runs"][1]["output_id"] = plan["runs"][0]["output_id"]
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            protocol_path = mini.prep / "protocol" / "downstream_experiment_protocol_v1.json"
            protocol = json.loads(protocol_path.read_text("utf-8"))
            protocol["source_files"]["protocol/private_execution_plan.json"] = util.sha256_file(plan_path)
            protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
            (mini.formal / "formal_execution_manifest.json").write_text(
                json.dumps({**mini.formal_manifest,
                            "preparation_protocol_sha256": util.sha256_file(protocol_path)}), encoding="utf-8")
            snapshot = json.loads((mini.formal / "source_freeze_binding.json").read_text("utf-8"))
            key = next(iter(snapshot["source_snapshot"]))
            snapshot["source_snapshot"][key]["protocol/private_execution_plan.json"] = util.sha256_file(plan_path)
            (mini.formal / "source_freeze_binding.json").write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, None)

    def test_missing_judge_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = self._build_root(tmp)
            victim = next((mini.root / "DOWNSTREAM_AI_EVAL_GLM_20260915" / "judgements").glob("*.json"))
            victim.unlink()
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, None)

    def test_lattice_hole_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = self._build_root(tmp)
            plan_path = mini.prep / "protocol" / "private_execution_plan.json"
            plan = json.loads(plan_path.read_text("utf-8"))
            plan["runs"] = plan["runs"][:-1]
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaises(CanonicalBuildError):
                build_canonical(mini.root, None)

    def test_score_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = self._build_root(tmp)
            registry = build_canonical(mini.root, None)
            scores = output_score_rows(registry.claim_judgements, registry.error_events)
            for row in scores:
                self.assertGreaterEqual(row["useful_information_slots"], 0)
                self.assertLessEqual(row["useful_information_slots"], 6)
                self.assertGreaterEqual(row["substantive_error_count"], 0)

    def test_influence_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini = self._build_root(tmp)
            registry = build_canonical(mini.root, None)
            result = build_influence(registry.to_dict())
            self.assertEqual(len(result["leave_one_output_out"]), 24 * 3 * 2)


class TestUnitTableIndex(unittest.TestCase):
    def test_unit_table(self):
        table = unit_table([unit(1), unit(2, evaluator="K")])
        self.assertIn(("J", "o1", 1), table)
        self.assertIn(("K", "o1", 2), table)


if __name__ == "__main__":
    unittest.main()
