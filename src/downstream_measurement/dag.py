"""Phase C: evidence dependency DAG with path/field-aware edge verification.

An edge is VERIFIED_EDGE only when specific binding fields (or per-case
entries, or snapshot keys) in the downstream package match the independently
verified byte hash of SPECIFIC upstream files. "Some hash in the binding
document equals some hash in the upstream package" is never sufficient;
unanchored or report-level references degrade to QUALIFIED / UNVERIFIED_EDGE.
"""
from __future__ import annotations

import json
from pathlib import Path

from .util import load_json

_PATH_KEYS = ("path", "absolute_path", "file", "relative_path", "package_copy", "member")


def _walk_hash_bindings(obj, pointer="$", parent_paths=None):
    """Yield {pointer, sha256, path_hints} from a binding document.

    path_hints collects sibling path-like strings of each hash value so a
    hash can only strictly bind the file its own record names.
    """
    if isinstance(obj, dict):
        hashes = []
        path_hints = []
        for key, value in obj.items():
            if isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value):
                hashes.append((f"{pointer}/{key}", value))
            elif isinstance(value, str) and (key in _PATH_KEYS or key.endswith("_path") or key.endswith("_file")):
                path_hints.append(value)
        for ptr, digest in hashes:
            hints = list(path_hints) + list(parent_paths or [])
            yield {"pointer": ptr, "sha256": digest, "path_hints": hints}
        for key, value in obj.items():
            if isinstance(value, (dict, list)) and not (isinstance(value, str)):
                child_hints = [v for k, v in obj.items() if k in _PATH_KEYS and isinstance(v, str)]
                yield from _walk_hash_bindings(value, f"{pointer}/{key}", child_hints)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from _walk_hash_bindings(value, f"{pointer}[{index}]", parent_paths)


def _sha_looks(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _tail_match(hint: str, rel_path: str) -> bool:
    """A path hint strictly names the upstream file if its tail equals the
    package-relative path (or its basename plus a distinctive parent)."""
    hint_norm = hint.replace("\\", "/")
    rel_norm = rel_path.replace("\\", "/")
    if hint_norm.endswith(rel_norm):
        return True
    hint_parts = hint_norm.split("/")
    rel_parts = rel_norm.split("/")
    if len(rel_parts) >= 2 and len(hint_parts) >= 2 and hint_parts[-2:] == rel_parts[-2:]:
        return True
    return hint_norm.split("/")[-1] == rel_norm.split("/")[-1] and len(rel_norm.split("/")) == 1


class DagContext:
    def __init__(self, evidence_root: Path, package_dirs: dict[str, str],
                 supplement_path: Path | None, integrity_rows: list[dict]):
        self.roots = {pid: Path(evidence_root) / dirname for pid, dirname in package_dirs.items()}
        self.supplement_path = supplement_path
        self.verified: dict[str, dict[str, str]] = {}
        rows_by_package: dict[str, list[dict]] = {}
        for row in integrity_rows:
            rows_by_package.setdefault(row["package"], []).append(row)
        for pid, rows in rows_by_package.items():
            self.verified[pid] = {
                row["file"]: row["actual_sha256"]
                for row in rows if row["verification_level"] == "VERIFIED_BYTES" and row.get("match")
            }
        # Package identity anchor = SHA256 of the package's own SHA256_manifest.txt.
        self.anchors: dict[str, str] = {}
        for pid, root in self.roots.items():
            manifest = root / "SHA256_manifest.txt"
            if manifest.is_file():
                from .util import sha256_file as _sha_file

                self.anchors[pid] = _sha_file(manifest)

    def strict_path_hint_matches(self, package_id: str, bindings: list[dict]) -> tuple[int, int]:
        """Return (file_level_matches, package_anchor_matches).

        file-level: a binding record names the upstream file (path hint) and
        its digest equals that file's verified byte hash.
        anchor-level: the digest equals the upstream package's manifest anchor
        and the record explicitly refers to the package or its manifest.
        """
        upstream = self.verified.get(package_id, {})
        anchor = self.anchors.get(package_id)
        dir_name = self.roots.get(package_id, Path(package_id)).name
        matched_files = set()
        anchor_matches = 0
        for binding in bindings:
            digest = binding["sha256"]
            hints = binding["path_hints"]
            matched_file = None
            for rel, file_digest in upstream.items():
                if file_digest == digest and any(_tail_match(hint, rel) for hint in hints):
                    matched_file = rel
                    break
            if matched_file:
                matched_files.add(matched_file)
                continue
            if (anchor and digest == anchor
                    and any(hint.replace("\\", "/").endswith("SHA256_manifest.txt")
                            or dir_name in hint.replace("\\", "/") for hint in hints)):
                anchor_matches += 1
        return len(matched_files), anchor_matches

    def strict_identity_anchor_matches(self, package_id: str, doc) -> int:
        """Count identity-style bindings of the upstream package anchor.

        Accepted forms: a string value 'name:sha256:<anchor>' naming the
        package, or a dict entry whose KEY mentions package/manifest/identity
        and whose VALUE equals the anchor.
        """
        anchor = self.anchors.get(package_id)
        if not anchor or doc is None:
            return 0
        dir_name = self.roots.get(package_id, Path(package_id)).name
        count = 0

        def walk(node):
            nonlocal count
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(value, str):
                        if f"sha256:{anchor}" in value or value == anchor:
                            if any(tag in str(key).lower() for tag in ("package", "manifest", "identity", "integration")) or dir_name.lower().replace("_", "") in str(key).lower().replace("_", ""):
                                count += 1
                    else:
                        walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(doc)
        return count

    def load_binding_doc(self, package_id: str, rel: str):
        target = self.roots.get(package_id) / rel
        if not target.is_file():
            return None
        try:
            return load_json(target)
        except (ValueError, OSError):
            return None


def _verify_snapshot_edge(ctx: DagContext, upstream: str) -> dict:
    doc = ctx.load_binding_doc("formal_execution", "source_freeze_binding.json")
    if doc is None:
        return {"extracted": 0, "strict": 0}
    upstream_map = ctx.verified.get(upstream, {})
    strict = 0
    extracted = 0
    for root_dir, snapshot in doc.get("source_snapshot", {}).items():
        for rel, digest in snapshot.items():
            if not _sha_looks(digest):
                continue
            extracted += 1
            if upstream_map.get(rel.replace("\\", "/")) == digest:
                strict += 1
    return {"extracted": extracted, "strict": strict}


def _verify_named_field_edge(ctx: DagContext, upstream: str, field_files: dict[str, str]) -> dict:
    doc = ctx.load_binding_doc("formal_execution", "formal_execution_manifest.json")
    if doc is None:
        return {"extracted": 0, "strict": 0}
    strict = 0
    extracted = 0
    for field, upstream_rel in field_files.items():
        value = doc.get(field)
        if not _sha_looks(value):
            continue
        extracted += 1
        expected = ctx.verified.get(upstream, {}).get(upstream_rel) or ctx.anchors.get(upstream)
        if expected and value == expected:
            strict += 1
    return {"extracted": extracted, "strict": strict}


def _verify_judge_edge(ctx: DagContext, judge_dir_pid: str) -> dict:
    doc = ctx.load_binding_doc(judge_dir_pid, "source_binding.json")
    if doc is None or not isinstance(doc.get("cases"), list):
        return {"extracted": 0, "strict": 0, "cases": 0,
                "schema_note": "judge package uses a non-case source_binding schema; per-case identity is "
                               "instead verified in the canonical loader (judgement input_sha256 four-tuple "
                               "vs formal manifest hashes)"}
    upstream_map = ctx.verified.get("formal_execution", {})
    strict = 0
    cases = 0
    for case in doc.get("cases", []):
        oid = case.get("output_id")
        value = case.get("public_output_file_sha256")
        if not oid or not _sha_looks(value):
            continue
        cases += 1
        rel = f"public_blinded_outputs/{oid}/generator_output.json"
        if upstream_map.get(rel) == value:
            strict += 1
    return {"extracted": cases, "strict": strict, "cases": cases}


def _verify_supplement_edge(ctx: DagContext) -> dict:
    path = Path(ctx.supplement_path) if ctx.supplement_path else None
    if not path or not path.exists():
        return {"extracted": 0, "strict": 0}
    if path.is_dir():
        pro = next(path.glob("PRO_FULL_BLIND_AUDIT_144.json"), None)
        if pro is None:
            return {"extracted": 0, "strict": 0}
        doc = load_json(pro)
    else:
        import zipfile as _zf

        with _zf.ZipFile(path) as archive:
            member = next(m for m in archive.namelist() if m.endswith("PRO_FULL_BLIND_AUDIT_144.json"))
            doc = json.loads(archive.read(member).decode("utf-8"))
    upstream_map = ctx.verified.get("formal_execution", {})
    strict = 0
    extracted = 0
    for out in doc.get("outputs", []):
        oid = out.get("output_id")
        value = out.get("source_binding", {}).get("output_sha256_raw_bytes")
        if not oid or not _sha_looks(value):
            continue
        extracted += 1
        if upstream_map.get(f"public_blinded_outputs/{oid}/generator_output.json") == value:
            strict += 1
    return {"extracted": extracted, "strict": strict}


def _verify_path_hint_edge(ctx: DagContext, upstream: str, package_id: str, rel: str) -> dict:
    doc = ctx.load_binding_doc(package_id, rel)
    if doc is None:
        return {"extracted": 0, "strict": 0, "anchor_strict": 0}
    bindings = list(_walk_hash_bindings(doc))
    strict, anchor_strict = ctx.strict_path_hint_matches(upstream, bindings)
    return {"extracted": len(bindings), "strict": strict, "anchor_strict": anchor_strict}


def _verify_identity_anchor_edge(ctx: DagContext, upstream: str, package_id: str, rel: str) -> dict:
    doc = ctx.load_binding_doc(package_id, rel)
    if doc is None:
        return {"extracted": 0, "strict": 0, "anchor_strict": 0}
    identity_matches = ctx.strict_identity_anchor_matches(upstream, doc)
    bindings = list(_walk_hash_bindings(doc))
    file_strict, anchor_strict = ctx.strict_path_hint_matches(upstream, bindings)
    return {"extracted": len(bindings), "strict": file_strict,
            "anchor_strict": max(anchor_strict, identity_matches)}


EDGE_SPECS = [
    {"edge_id": "rcp_screening_codex->rcp_integration", "upstream": "rcp_screening_codex",
     "downstream": "rcp_integration", "relation": "runner results integrated into 160-case matrix",
     "mode": "zip_unanchored",
     "note": "upstream bytes exist only as unzipped directories; integration binds ZIPs whose digests have no in-tree anchor"},
    {"edge_id": "rcp_screening_codex_ultra->rcp_integration", "upstream": "rcp_screening_codex_ultra",
     "downstream": "rcp_integration", "relation": "sensitivity re-run integrated as Ultra views only",
     "mode": "zip_unanchored", "note": "same ZIP-anchor limitation"},
    {"edge_id": "rcp_screening_deepseek->rcp_integration", "upstream": "rcp_screening_deepseek",
     "downstream": "rcp_integration", "relation": "runner results integrated into 160-case matrix",
     "mode": "zip_unanchored", "note": "same ZIP-anchor limitation"},
    {"edge_id": "rcp_integration->mca_protocol_audit", "upstream": "rcp_integration",
     "downstream": "mca_protocol_audit", "relation": "integration package identity pinned in frozen MCA protocol",
     "mode": "identity_anchor", "binding": {"package": "mca_protocol_audit", "file": "mca_v1_protocol.json"}},
    {"edge_id": "mca_protocol_audit->mca_human_aggregation", "upstream": "mca_protocol_audit",
     "downstream": "mca_human_aggregation", "relation": "protocol package manifest anchored by aggregation import manifest",
     "mode": "identity_anchor", "binding": {"package": "mca_human_aggregation", "file": "import_manifest.json"}},
    {"edge_id": "mca_human_aggregation->mca_final", "upstream": "mca_human_aggregation",
     "downstream": "mca_final", "relation": "R3 adjudication over aggregated audit outputs",
     "mode": "path_hint", "binding": {"package": "mca_final", "file": "checks/upstream_integrity_report.json"},
     "minimum_strict": 3},
    {"edge_id": "mca_final->experiment_prep", "upstream": "mca_final",
     "downstream": "experiment_prep", "relation": "MCA Top-8 treatment consumed by matched contexts / BM25 control replay",
     "mode": "path_hint", "binding": {"package": "experiment_prep", "file": "validation_report.json"},
     "minimum_strict": 2},
    {"edge_id": "generator_freeze_v2->formal_execution", "upstream": "generator_freeze_v2",
     "downstream": "formal_execution", "relation": "formal execution under frozen generator identity",
     "mode": "named_fields",
     "field_files": {"generator_freeze_v2_sha256": "generator_freeze_v2.json",
                     "generator_v2_manifest_sha256": "SHA256_manifest.txt"},
     "minimum_strict": 2},
    {"edge_id": "experiment_prep->formal_execution", "upstream": "experiment_prep",
     "downstream": "formal_execution", "relation": "protocol + mapping + plan hash-bound in formal source snapshot",
     "mode": "snapshot", "minimum_strict": 3},
    {"edge_id": "formal_execution->ai_eval_gpt", "upstream": "formal_execution",
     "downstream": "ai_eval_gpt", "relation": "blind GPT judge consumed public blinded outputs",
     "mode": "judge_cases", "judge": "ai_eval_gpt"},
    {"edge_id": "formal_execution->ai_eval_deepseek", "upstream": "formal_execution",
     "downstream": "ai_eval_deepseek", "relation": "blind DeepSeek judge consumed public blinded outputs",
     "mode": "judge_cases", "judge": "ai_eval_deepseek"},
    {"edge_id": "formal_execution->ai_eval_glm", "upstream": "formal_execution",
     "downstream": "ai_eval_glm", "relation": "blind GLM judge consumed public blinded outputs",
     "mode": "judge_cases", "judge": "ai_eval_glm"},
    {"edge_id": "ai_eval_gpt->judge_agreement_v2", "upstream": "ai_eval_gpt",
     "downstream": "judge_agreement_v2", "relation": "identity alignment and blinded agreement",
     "mode": "path_hint", "binding": {"package": "judge_agreement_v2", "file": "source_verification.json"},
     "minimum_strict": 5},
    {"edge_id": "ai_eval_deepseek->judge_agreement_v2", "upstream": "ai_eval_deepseek",
     "downstream": "judge_agreement_v2", "relation": "identity alignment and blinded agreement",
     "mode": "path_hint", "binding": {"package": "judge_agreement_v2", "file": "source_verification.json"},
     "minimum_strict": 5},
    {"edge_id": "ai_eval_glm->judge_agreement_v2", "upstream": "ai_eval_glm",
     "downstream": "judge_agreement_v2", "relation": "identity alignment and blinded agreement",
     "mode": "path_hint", "binding": {"package": "judge_agreement_v2", "file": "source_verification.json"},
     "minimum_strict": 5},
    {"edge_id": "pro_targeted_audit->pre_unblinding_closure", "upstream": "pro_targeted_audit",
     "downstream": "pre_unblinding_closure", "relation": "targeted Pro audit registered into closure",
     "mode": "path_hint", "binding": {"package": "pre_unblinding_closure", "file": "SOURCE_BINDINGS.json"},
     "minimum_strict": 2},
    {"edge_id": "pre_unblinding_closure->unblinding_authorization", "upstream": "pre_unblinding_closure",
     "downstream": "unblinding_authorization", "relation": "closure manifest hash inherited by authorization",
     "mode": "path_hint", "binding": {"package": "unblinding_authorization", "file": "APPROVED_SOURCE_BINDINGS.json"},
     "minimum_strict": 2},
    {"edge_id": "unblinding_authorization->unblinded_analysis", "upstream": "unblinding_authorization",
     "downstream": "unblinded_analysis", "relation": "authorization package bound as first-look allowlist input",
     "mode": "path_hint", "binding": {"package": "unblinded_analysis", "file": "SOURCE_BINDINGS.json"},
     "minimum_strict": 2},
    {"edge_id": "formal_execution->meeting_supplement_pro_full", "upstream": "formal_execution",
     "downstream": "meeting_supplement_pro_full",
     "relation": "full Pro blind audit of all 24 outputs (SENSITIVITY_EVALUATOR)",
     "mode": "supplement_per_output"},
    {"edge_id": "unblinded_analysis->meeting_prep", "upstream": "unblinded_analysis",
     "downstream": "meeting_prep", "relation": "meeting preparation cites first-look results (report-level)",
     "mode": "report_level"},
    {"edge_id": "meeting_supplement_pro_full->meeting_prep", "upstream": "meeting_supplement_pro_full",
     "downstream": "meeting_prep", "relation": "meeting preparation cites supplement diagnostics (report-level)",
     "mode": "report_level"},
]


def build_dag(evidence_root: Path, package_dirs: dict[str, str], supplement_zip: Path | None,
              integrity_rows: list[dict]) -> dict:
    ctx = DagContext(evidence_root, package_dirs, supplement_zip, integrity_rows)
    nodes = []
    for spec in EDGE_SPECS:
        for pid in (spec["upstream"], spec["downstream"]):
            if pid not in {n["package_id"] for n in nodes}:
                nodes.append({"package_id": pid,
                              "kind": "supplement" if pid == "meeting_supplement_pro_full" else "directory"})
    edges = []
    for spec in EDGE_SPECS:
        mode = spec["mode"]
        if mode == "report_level":
            result, status, rule = {"extracted": 0, "strict": 0}, "QUALIFIED", "report-level citation; no byte binding"
        elif mode == "zip_unanchored":
            result, status, rule = {"extracted": 0, "strict": 0}, "QUALIFIED", \
                "binding references ZIP digests without an in-tree byte anchor"
        elif mode == "snapshot":
            result = _verify_snapshot_edge(ctx, spec["upstream"])
            status = "VERIFIED_EDGE" if result["strict"] >= spec["minimum_strict"] else (
                "QUALIFIED" if result["strict"] else "UNVERIFIED_EDGE")
            rule = "snapshot keys name upstream files; digest must equal verified bytes of that file"
        elif mode == "named_fields":
            result = _verify_named_field_edge(ctx, spec["upstream"], spec["field_files"])
            status = "VERIFIED_EDGE" if result["strict"] >= spec["minimum_strict"] else (
                "QUALIFIED" if result["strict"] else "UNVERIFIED_EDGE")
            rule = "named manifest field must equal hash of the named upstream file/anchor"
        elif mode == "judge_cases":
            result = _verify_judge_edge(ctx, spec["judge"])
            if result.get("schema_note"):
                status, rule = "QUALIFIED", result["schema_note"]
            elif result["cases"] and result["strict"] == result["cases"]:
                status = "VERIFIED_EDGE"
                rule = "per-case public_output_file_sha256 must equal verified hash of that output's generator_output.json"
            elif result["strict"]:
                status, rule = "QUALIFIED", "partial per-case binding"
            else:
                status, rule = "UNVERIFIED_EDGE", "no per-case binding matched"
        elif mode == "supplement_per_output":
            result = _verify_supplement_edge(ctx)
            status = ("VERIFIED_EDGE" if result["extracted"] and result["strict"] == result["extracted"]
                      else "QUALIFIED" if result["strict"] else "UNVERIFIED_EDGE")
            rule = "per-output output_sha256_raw_bytes must equal verified hash of that output's generator_output.json"
        elif mode == "identity_anchor":
            result = _verify_identity_anchor_edge(ctx, spec["upstream"], spec["binding"]["package"], spec["binding"]["file"])
            status = ("VERIFIED_EDGE" if result["anchor_strict"] >= 1
                      else "QUALIFIED" if result["extracted"] else "UNVERIFIED_EDGE")
            rule = "identity-style field must pin the upstream package manifest anchor (sha256 of its SHA256_manifest.txt)"
        else:  # path_hint
            result = _verify_path_hint_edge(ctx, spec["upstream"], spec["binding"]["package"], spec["binding"]["file"])
            verified = result["strict"] >= spec["minimum_strict"] or result.get("anchor_strict", 0) >= 1
            status = ("VERIFIED_EDGE" if verified
                      else "QUALIFIED" if result["extracted"] else "UNVERIFIED_EDGE")
            rule = "binding record must name the upstream file and match its verified digest, or pin the package manifest anchor"
        edges.append({
            "edge_id": spec["edge_id"], "from": spec["upstream"], "to": spec["downstream"],
            "relation": spec["relation"], "verification_rule": rule,
            "hashes_extracted": result["extracted"], "strict_file_matches": result["strict"],
            "status": status,
        })
    return {
        "schema_version": "1.1",
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "edges_total": len(edges),
            "verified": sum(1 for e in edges if e["status"] == "VERIFIED_EDGE"),
            "qualified": sum(1 for e in edges if e["status"] == "QUALIFIED"),
            "unverified": sum(1 for e in edges if e["status"] == "UNVERIFIED_EDGE"),
        },
    }


def dag_markdown(dag: dict) -> str:
    lines = ["# Evidence DAG", ""]
    lines.append(f"Edges: {dag['summary']['edges_total']} total, "
                 f"{dag['summary']['verified']} VERIFIED_EDGE, "
                 f"{dag['summary']['qualified']} QUALIFIED, "
                 f"{dag['summary']['unverified']} UNVERIFIED_EDGE. "
                 "VERIFIED_EDGE requires a specific binding field/per-case entry/snapshot key to match "
                 "the independently verified digest of a specific upstream file.")
    lines.append("")
    lines.append("| edge | relation | status | strict matches | rule |")
    lines.append("| --- | --- | --- | --- | --- |")
    for edge in dag["edges"]:
        lines.append(
            f"| {edge['from']} → {edge['to']} | {edge['relation']} | {edge['status']} | "
            f"{edge['strict_file_matches']}/{edge['hashes_extracted']} | {edge['verification_rule']} |"
        )
    lines.append("")
    lines.append("Chronological chain (blinding state at creation):")
    lines.append("")
    lines.append("```text")
    lines.append("RCP screening (blind) -> RCP integration (blind)")
    lines.append("  -> MCA protocol/human audit/final treatment (blind)")
    lines.append("  -> experiment prep: condition mapping + matched contexts (blind by private mapping)")
    lines.append("  -> generator freeze v2 (blind) -> formal 24 outputs (public blinded view)")
    lines.append("  -> three AI judges (blind) -> agreement V2 (blind)")
    lines.append("  -> targeted Pro audit (blind) -> pre-unblinding closure (blind; STATUS BLOCKED)")
    lines.append("  -> authority recovery (blind) -> authorization APPROVED_EFFECTIVE (process-aware)")
    lines.append("  -> unblinded first-look analysis (treatment-aware)")
    lines.append("  -> full Pro blind audit supplement (SENSITIVITY_EVALUATOR, post-hoc diagnostics)")
    lines.append("  -> meeting prep (report-only, treatment-aware)")
    lines.append("```")
    return "\n".join(lines) + "\n"
