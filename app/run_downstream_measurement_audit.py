"""Run the downstream measurement audit (Phases E-K, M, P) from a registry.

Consumes the canonical registry produced by build_downstream_evidence_registry
(rebuilding it in memory only if absent), independently reproduces the frozen
first look from canonical judgements, and derives diagnostic measurement
analyses. Nothing outside --output-dir is written.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.downstream_measurement import TOOL_ID, TOOL_VERSION
from src.downstream_measurement.canonical import build_canonical
from src.downstream_measurement.counterfactual import build_counterfactual
from src.downstream_measurement.decomposition import build_decomposition
from src.downstream_measurement.error_audit import build_error_audit
from src.downstream_measurement.figures import render_all
from src.downstream_measurement.first_look import assess_frozen_comparison, reproduce_first_look
from src.downstream_measurement.influence import build_influence
from src.downstream_measurement.integrity import load_frozen_macro_source, load_integrity_summary
from src.downstream_measurement.inventory import FORMAL_CHAIN_PACKAGES, resolve_package_directory
from src.downstream_measurement.report_manifest import build_manifest
from src.downstream_measurement.sensitivity import build_sensitivity
from src.downstream_measurement.integrity import collect_missing_source_rows
from src.downstream_measurement.util import (
    atomic_write_json,
    atomic_write_text,
    mark_staging_partial,
    prepare_staging_target,
    publish_staging,
    safe_output_dir,
    load_json,
    sha256_file,
    write_csv,
)


def _verify_registry_matches_reconstruction(loaded: dict, evidence_root: Path,
                                            supplement_zip: Path | None) -> list[str]:
    """C1: a persisted canonical registry must equal a fresh rebuild.

    The registry file's own hash is not the trust anchor; the strongest check
    is deterministic reconstruction from the current raw evidence. A loaded
    registry containing Full Pro sensitivity rows without a reconstructable
    supplement source fails closed instead of silently skipping it.
    """
    has_sensitivity = any(row.get("role") != "PRIMARY_JUDGE" for row in loaded.get("claim_judgements", []))
    if has_sensitivity and not (supplement_zip and Path(supplement_zip).exists()):
        return ["loaded registry contains sensitivity rows but no supplement source was provided "
                "for reconstruction; refusing to silently drop Full Pro"]
    from src.downstream_measurement.canonical import build_canonical
    from src.downstream_measurement.util import canonical_json_bytes

    rebuilt = build_canonical(Path(evidence_root), Path(supplement_zip) if supplement_zip else None).to_dict()
    if canonical_json_bytes(rebuilt) != canonical_json_bytes(loaded):
        return ["persisted canonical_registry.json differs from fresh reconstruction over the "
                "current evidence root (rows or provenance were tampered after the build)"]
    return []


def _verify_registry_matches_evidence(registry: dict, evidence_root: Path) -> list[str]:
    """Bind a loaded registry to the CURRENT evidence root, fail-closed.

    Two independent layers:
    1. identity layer — registry-recorded source identities are recomputed
       from the current evidence root (protocol, condition mapping, plan,
       rubric, schema, formal manifest, package manifests);
    2. byte layer — every formal-chain package's current bytes are re-verified
       against its own SHA256 manifest (catches tampering that leaves the
       manifest file itself untouched), with the single pre-documented
       blank-template exception still honoured, never regenerated.
    """
    prep = resolve_package_directory(evidence_root, "experiment_prep")
    formal = resolve_package_directory(evidence_root, "formal_execution")
    identities = registry.get("source_identities", {})
    protocol = load_json(prep / "protocol" / "downstream_experiment_protocol_v1.json")
    mapping_rel = protocol["blinding"]["private_condition_map"]
    current = {
        "protocol_sha256": prep / "protocol" / "downstream_experiment_protocol_v1.json",
        "condition_mapping_sha256": prep / mapping_rel,
        "execution_plan_sha256": prep / "protocol" / "private_execution_plan.json",
        "rubric_sha256": prep / "protocol" / "HUMAN_EVALUATION_RUBRIC_V1.md",
        "human_evaluation_schema_sha256": prep / "protocol" / "human_evaluation_schema.json",
        "formal_execution_manifest_sha256": formal / "formal_execution_manifest.json",
        "formal_package_manifest_sha256": formal / "SHA256_manifest.txt",
        "gpt_package_manifest_sha256": resolve_package_directory(evidence_root, "ai_eval_gpt") / "SHA256_manifest.txt",
        "deepseek_package_manifest_sha256": resolve_package_directory(evidence_root, "ai_eval_deepseek") / "SHA256_manifest.txt",
        "glm_package_manifest_sha256": resolve_package_directory(evidence_root, "ai_eval_glm") / "SHA256_manifest.txt",
    }
    mismatches = []
    for key, path in sorted(current.items()):
        expected = identities.get(key)
        if expected is None:
            mismatches.append(f"{key}: identity missing in registry")
        elif not Path(path).is_file():
            mismatches.append(f"{key}: source file missing at current evidence root")
        elif sha256_file(path) != expected:
            mismatches.append(f"{key}: hash drift between registry and current evidence root")
    from src.downstream_measurement.integrity import (
        DOCUMENTED_EXCEPTIONS,
        verify_documented_exception,
        verify_package,
    )

    # byte-layer scope: exactly the packages this registry's identities prove
    # it consumed (prep + formal + the three judge packages)
    identity_packages = {
        "experiment_prep", "formal_execution",
        "ai_eval_gpt", "ai_eval_deepseek", "ai_eval_glm",
    } & set(FORMAL_CHAIN_PACKAGES) if any(
        k.endswith("_package_manifest_sha256") for k in identities
    ) else set(FORMAL_CHAIN_PACKAGES)
    for package_id in sorted(identity_packages):
        package_dir = resolve_package_directory(evidence_root, package_id)
        if not package_dir.is_dir():
            mismatches.append(f"byte-layer: formal chain package {package_id} missing at evidence root")
            continue
        result = verify_package(package_dir, package_id)
        for row in result["rows"]:
            if row["verification_level"] == "BYTES_MISMATCH":
                exception = next((e for e in DOCUMENTED_EXCEPTIONS
                                  if e["package"] == package_id and e["file"] == row["file"]), None)
                if exception and verify_documented_exception(Path(evidence_root), exception, row):
                    continue
                mismatches.append(f"byte-layer: {package_id}/{row['file']} hash drift vs its SHA256 manifest")
            elif row["verification_level"] == "MISSING_SOURCE_BYTES":
                mismatches.append(f"byte-layer: {package_id}/{row['file']} missing")
    return mismatches


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--supplement-zip", default=None)
    parser.add_argument("--registry-dir", default=None, help="output dir of build_downstream_evidence_registry")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--formal-verification", action="store_true",
                        help="require the complete frozen first-look comparison to MATCH; otherwise fail with partial staging")
    args = parser.parse_args(argv)

    evidence_root = Path(args.evidence_root)
    supplement_zip = Path(args.supplement_zip) if args.supplement_zip else None
    final_target = safe_output_dir(args.output_dir, [evidence_root] + ([supplement_zip] if supplement_zip else []))
    try:
        output_dir = prepare_staging_target(final_target)
    except FileExistsError as error:
        print(f"[audit] FAIL CLOSED — {error}", file=sys.stderr)
        return 7
    try:
        return _run_audit(args, evidence_root, supplement_zip, final_target, output_dir)
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 - staging must be marked partial
        mark_staging_partial(output_dir, f"{type(error).__name__}: {error}")
        print(f"[audit] FAILED (staging marked partial): {type(error).__name__}: {error}", file=sys.stderr)
        return 6


def _run_audit(args, evidence_root: Path, supplement_zip: Path | None,
               final_target: Path, output_dir: Path) -> int:
    registry_dir = Path(args.registry_dir) if args.registry_dir else final_target

    canonical_path = registry_dir / "canonical" / "canonical_registry.json"
    if canonical_path.exists():
        registry = json.loads(canonical_path.read_bytes().decode("utf-8"))
        print(f"[audit] canonical registry loaded from {canonical_path}")
        mismatch = _verify_registry_matches_evidence(registry, evidence_root)
        if mismatch:
            print(f"[audit] FAIL CLOSED — registry identities do not match current evidence root: {mismatch}",
                  file=sys.stderr)
            mark_staging_partial(output_dir, f"registry/evidence drift: {mismatch[:2]}")
            return 3
        reconstruction_mismatch = _verify_registry_matches_reconstruction(registry, evidence_root, supplement_zip)
        if reconstruction_mismatch:
            print(f"[audit] FAIL CLOSED — canonical registry does not match fresh reconstruction: "
                  f"{reconstruction_mismatch}", file=sys.stderr)
            mark_staging_partial(output_dir, f"registry reconstruction drift: {reconstruction_mismatch[:1]}")
            return 3
        print("[audit] registry identities re-verified; persisted canonical registry equals fresh "
              "reconstruction over current evidence")
    else:
        print("[audit] canonical registry missing; rebuilding in memory from evidence root")
        registry = build_canonical(evidence_root, supplement_zip).to_dict()
    v = registry["validation"]
    print(f"[audit] outputs={v['outputs']} claims={v['claims']} "
          f"primary_units={v['primary_claim_judgements']} sensitivity_units={v['sensitivity_claim_judgements']}")

    # Phase E: independent reproduction + comparison against the frozen table.
    reproduction = reproduce_first_look(registry)
    first_look_dir = output_dir / "first_look"
    first_look_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(first_look_dir / "FIRST_LOOK_INDEPENDENT_REPRODUCTION.json", reproduction)
    macro_rows = []
    for role_key in ("primary", "sensitivity"):
        for evaluator, agg in sorted(reproduction[role_key].items()):
            if "macro" not in agg:
                macro_rows.append({"evaluator": evaluator,
                                   "role": "PRIMARY_JUDGE" if role_key == "primary" else "SENSITIVITY_EVALUATOR",
                                   "grain": agg.get("status", "ERROR"), "BM25_mean_U": "", "MCA_mean_U": "",
                                   "Delta_U": "", "exact_Delta_U": agg.get("error", ""), "BM25_mean_E": "",
                                   "MCA_mean_E": "", "Delta_E": "", "exact_Delta_E": "", "U_direction": "",
                                   "E_direction": ""})
                continue
            m = agg["macro"]
            macro_rows.append({
                "evaluator": evaluator, "role": "PRIMARY_JUDGE" if role_key == "primary" else "SENSITIVITY_EVALUATOR",
                "grain": "macro",
                "BM25_mean_U": float(m["BM25_mean_U"]), "MCA_mean_U": float(m["MCA_mean_U"]),
                "Delta_U": float(m["Delta_U"]), "exact_Delta_U": str(m["Delta_U"]),
                "BM25_mean_E": float(m["BM25_mean_E"]), "MCA_mean_E": float(m["MCA_mean_E"]),
                "Delta_E": float(m["Delta_E"]), "exact_Delta_E": str(m["Delta_E"]),
                "U_direction": m["U_direction"], "E_direction": m["E_direction"],
            })
            for cell in agg["cells"]:
                macro_rows.append({
                    "evaluator": evaluator, "role": "PRIMARY_JUDGE" if role_key == "primary" else "SENSITIVITY_EVALUATOR",
                    "grain": f"{cell['topic_id']}|{cell['task_id']}",
                    "BM25_mean_U": float(cell["BM25_mean_U"]), "MCA_mean_U": float(cell["MCA_mean_U"]),
                    "Delta_U": float(cell["Delta_U"]), "exact_Delta_U": str(cell["Delta_U"]),
                    "BM25_mean_E": float(cell["BM25_mean_E"]), "MCA_mean_E": float(cell["MCA_mean_E"]),
                    "Delta_E": float(cell["Delta_E"]), "exact_Delta_E": str(cell["Delta_E"]),
                    "U_direction": cell["U_direction"], "E_direction": cell["E_direction"],
                })
    write_csv(first_look_dir / "FIRST_LOOK_INDEPENDENT_REPRODUCTION.csv",
              ["evaluator", "role", "grain", "BM25_mean_U", "MCA_mean_U", "Delta_U", "exact_Delta_U",
               "BM25_mean_E", "MCA_mean_E", "Delta_E", "exact_Delta_E", "U_direction", "E_direction"],
              macro_rows)
    integrity_summary_path = registry_dir / "integrity" / "integrity_summary.json"
    integrity_summary = (load_integrity_summary(integrity_summary_path)
                         if integrity_summary_path.is_file() else {"packages": {}, "counts": {}})
    source_packages = integrity_summary.get("packages", {})
    frozen_csv, source_verification = load_frozen_macro_source(
        evidence_root, source_packages.get("unblinded_analysis"))
    comparison = assess_frozen_comparison(reproduction, frozen_csv)
    comparison["value_comparison_status"] = comparison["status"]
    comparison["source_verification"] = source_verification
    if source_verification["status"] != "VERIFIED_BYTES":
        comparison["status"] = source_verification["status"]
        comparison["problems"].extend(source_verification["problems"])
    comparison["mode"] = "formal_verification" if args.formal_verification else "diagnostic"
    atomic_write_json(first_look_dir / "comparison_vs_frozen_first_look.json", comparison)
    print(f"[first-look] comparison vs frozen first-look: {comparison['status']} "
          f"({comparison['fields_compared']}/{comparison['expected_fields']} field comparisons)")
    if comparison["status"] != "MATCH":
        for problem in comparison["problems"]:
            print("  comparison:", problem)
        for row in comparison["rows"]:
            if not row.get("match", False):
                print("  mismatch:", row)
        if args.formal_verification:
            mark_staging_partial(output_dir, f"formal first-look verification failed: {comparison['status']}")
            print("[audit] FAIL CLOSED — formal first-look verification failed; staging marked partial",
                  file=sys.stderr)
            return 8
        print("[first-look] diagnostic mode continues; formal reproduction is not verified")

    # Phases G-K.
    decomposition = build_decomposition(registry)
    sensitivity = build_sensitivity(registry, reproduction)
    influence = build_influence(registry)
    counterfactual = build_counterfactual(registry)
    error_audit = build_error_audit(registry)
    atomic_write_json(output_dir / "decomposition" / "component_decomposition.json", decomposition)
    write_csv(output_dir / "decomposition" / "component_decomposition_per_output.csv",
              list(decomposition["per_output"][0].keys()) if decomposition["per_output"] else ["evaluator"],
              decomposition["per_output"])
    atomic_write_json(output_dir / "sensitivity" / "evaluator_sensitivity.json", sensitivity)
    write_csv(output_dir / "sensitivity" / "treatment_contrasts.csv",
              ["evaluator", "role", "BM25_mean_U", "MCA_mean_U", "Delta_U",
               "BM25_mean_E", "MCA_mean_E", "Delta_E", "U_direction", "E_direction"],
              sensitivity["treatment_contrasts"])
    write_csv(output_dir / "sensitivity" / "pairwise_agreement.csv",
              ["field", "pair", "n", "raw_agreement", "kappa", "kappa_status",
               "prevalence_a", "prevalence_b", "contingency"],
              sensitivity["pairwise_agreement"])
    atomic_write_json(output_dir / "influence" / "influence_diagnostics.json", influence)
    write_csv(output_dir / "influence" / "leave_one_output_out.csv",
              list(influence["leave_one_output_out"][0].keys()) if influence["leave_one_output_out"] else ["evaluator"],
              influence["leave_one_output_out"])
    write_csv(output_dir / "influence" / "per_repetition_arm_contrasts.csv",
              list(influence["per_repetition_arm_contrasts"][0].keys()),
              influence["per_repetition_arm_contrasts"])
    atomic_write_json(output_dir / "counterfactual" / "metric_sensitivity.json", counterfactual)
    write_csv(output_dir / "counterfactual" / "metric_variants.csv",
              ["evaluator", "role", "variant", "BM25_mean", "MCA_mean", "Delta", "exact_delta", "direction"],
              counterfactual["variants"])
    write_csv(output_dir / "counterfactual" / "lambda_sensitivity.csv",
              ["evaluator", "role", "lambda", "exact_lambda", "BM25_mean", "MCA_mean", "Delta", "exact_delta", "direction"],
              counterfactual["lambda_sensitivity"])
    atomic_write_json(output_dir / "error_audit" / "error_event_audit.json", error_audit)
    write_csv(output_dir / "error_audit" / "error_events.csv",
              ["evaluator", "role", "output_id", "arm", "topic_id", "task_id",
               "error_id", "error_types", "affected_appearance_indices"],
              error_audit["event_records"])

    from src.downstream_measurement.figures import REQUIRED_FIGURES

    figure_result = render_all(
        {"reproduction": reproduction, "sensitivity": sensitivity, "decomposition": decomposition,
         "influence": influence, "counterfactual": counterfactual,
         "integrity": integrity_summary},
        output_dir / "figures",
    )
    print(f"[figures] written: {figure_result['written']} failed: {figure_result['failed']}")
    if figure_result["failed"] or set(figure_result["written"]) != set(REQUIRED_FIGURES):
        message = f"required figure roster incomplete: {figure_result['failed']}"
        mark_staging_partial(output_dir, message)
        print(f"[audit] FAIL CLOSED — {message}", file=sys.stderr)
        return 5

    limitation_flags = [
        "pilot has 2 fixed topics; repetitions do not replicate topic selection",
        "claims are nested annotations, not iid n=144; three judges are not independent truth confirmations",
        "full Pro audit is a post-hoc SENSITIVITY_EVALUATOR without frozen schema; never a primary judge",
        "counterfactual metric variants are diagnostic sensitivity, not new endpoints and not rescoring",
        "first-look comparison relies on the frozen analysis package bytes verified in Phase B",
    ]
    integrity_csv_path = registry_dir / "integrity" / "evidence_integrity.csv"
    missing_rows = []
    if integrity_csv_path.exists():
        import csv as _csv

        with open(integrity_csv_path, encoding="utf-8", newline="") as handle:
            missing_rows = collect_missing_source_rows(list(_csv.DictReader(handle)))
    formal_ids_missing = FORMAL_CHAIN_PACKAGES - set(source_packages)
    if formal_ids_missing:
        print(f"[audit] FAIL CLOSED — manifest source_packages missing formal chain packages: "
              f"{sorted(formal_ids_missing)}", file=sys.stderr)
        mark_staging_partial(output_dir, f"manifest source_packages missing: {sorted(formal_ids_missing)[:3]}")
        return 4
    manifest = build_manifest(
        output_dir, Path(__file__).resolve().parents[1],
        source_identities=registry["source_identities"],
        source_packages={pid: {
            "identity_kind": info.get("identity_kind"),
            "manifest_sha256": info.get("manifest_sha256"),
            "package_identity_sha256": info.get("package_identity_sha256"),
            "summary": info.get("summary"),
        } for pid, info in source_packages.items()},
        registry_inputs={
            name: sha256_file(registry_dir / rel)
            for name, rel in (
                ("canonical_registry_sha256", "canonical/canonical_registry.json"),
                ("integrity_summary_sha256", "integrity/integrity_summary.json"),
                ("evidence_integrity_sha256", "integrity/evidence_integrity.csv"),
                ("evidence_dag_sha256", "evidence_dag.json"),
            )
            if (registry_dir / rel).is_file()
        },
        analysis_config={"lattice": "2x2x2x3", "first_n_units": 6, "difference_direction": "MCA - BM25",
                         "verification_mode": comparison["mode"],
                         "first_look_comparison_status": comparison["status"],
                         "first_look_source": source_verification,
                         "lambda_grid": counterfactual["lambda_grid"],
                         "sensitivity_evaluator": "FullPro"},
        limitation_flags=limitation_flags,
        missing_source_bytes=missing_rows,
    )
    publish_staging(output_dir, final_target)
    print(f"[manifest] {len(manifest['outputs'])} derived outputs hashed; git={manifest['git']}")
    print(f"[publish] {final_target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
