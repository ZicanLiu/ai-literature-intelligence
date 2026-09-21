"""Build the downstream evidence registry (Phases A-D).

Reads the external evidence root strictly read-only; persists a machine
readable inventory, independently recomputed byte integrity, the verified
evidence DAG and the canonical experimental registry into a derived output
directory. Fails closed on any formal-chain hash mismatch.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.downstream_measurement import TOOL_ID, TOOL_VERSION
from src.downstream_measurement.canonical import build_canonical
from src.downstream_measurement.dag import build_dag, dag_markdown
from src.downstream_measurement.inventory import (
    FORMAL_CHAIN_PACKAGES,
    resolve_package_directories,
    build_inventory,
    persist_inventory,
)
from src.downstream_measurement.integrity import build_integrity, persist_integrity
from src.downstream_measurement.util import (
    assert_no_absolute_paths,
    atomic_write_json,
    atomic_write_text,
    mark_staging_partial,
    prepare_staging_target,
    publish_staging,
    safe_output_dir,
    write_csv,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", required=True, help="read-only external evidence root")
    parser.add_argument("--supplement-zip", default=None, help="supplement ZIP or extracted directory (full Pro audit)")
    parser.add_argument("--output-dir", required=True, help="derived output directory (never inside evidence root)")
    args = parser.parse_args(argv)

    evidence_root = Path(args.evidence_root)
    supplement_zip = Path(args.supplement_zip) if args.supplement_zip else None
    final_target = safe_output_dir(args.output_dir, [evidence_root] + ([supplement_zip] if supplement_zip else []))
    try:
        output_dir = prepare_staging_target(final_target)
    except FileExistsError as error:
        print(f"[registry] FAIL CLOSED — {error}", file=sys.stderr)
        return 7
    try:
        return _build(evidence_root, supplement_zip, final_target, output_dir)
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 - staging must be marked partial
        mark_staging_partial(output_dir, f"{type(error).__name__}: {error}")
        print(f"[registry] FAILED (staging marked partial): {type(error).__name__}: {error}", file=sys.stderr)
        return 6


def _build(evidence_root: Path, supplement_zip: Path | None, final_target: Path, output_dir: Path) -> int:
    package_dirs = resolve_package_directories(evidence_root)
    print(f"[registry] evidence root: {evidence_root}")
    print(f"[registry] packages declared: {len(package_dirs)} + supplement")

    inventory = build_inventory(evidence_root, supplement_zip)
    persist_inventory(inventory, output_dir)
    print(f"[inventory] {len(inventory['packages'])} packages, "
          f"unknown dirs: {inventory['unknown_top_level_directories']}")

    integrity = build_integrity(evidence_root, package_dirs, supplement_zip, FORMAL_CHAIN_PACKAGES)
    persist_integrity(integrity, output_dir)
    counts = integrity["counts"]
    print(f"[integrity] verified={counts['files_verified']} mismatch={counts['bytes_mismatch']} "
          f"missing={counts['missing_source_bytes']} formal_chain_mismatch={counts['formal_chain_mismatch']}")
    if integrity["fail_closed"]:
        bad = [r for r in integrity["rows"]
               if r["verification_level"] in ("BYTES_MISMATCH", "MISSING_SOURCE_BYTES")
               and r["package"] in FORMAL_CHAIN_PACKAGES][:10]
        print("[integrity] FAIL CLOSED — formal chain byte mismatch:", bad, file=sys.stderr)
        mark_staging_partial(output_dir, f"formal chain byte mismatch: {bad[:2]}")
        return 2

    dag = build_dag(evidence_root, package_dirs, supplement_zip, integrity["rows"])
    atomic_write_json(output_dir / "evidence_dag.json", dag)
    atomic_write_text(output_dir / "evidence_dag.md", dag_markdown(dag))
    print(f"[dag] {dag['summary']}")

    registry = build_canonical(evidence_root, supplement_zip)
    canonical_dir = output_dir / "canonical"
    canonical_dir.mkdir(parents=True, exist_ok=True)
    registry_dict = registry.to_dict()
    atomic_write_json(canonical_dir / "canonical_registry.json", registry_dict)
    assert_no_absolute_paths(registry_dict, "canonical_registry")
    write_csv(canonical_dir / "canonical_outputs.csv",
              ["output_id", "topic_id", "task_id", "arm", "repetition", "opaque_condition_id",
               "context_sha256", "context_token_count", "context_units_definition", "input_sha256",
               "generator_output_sha256", "claims_count", "source_locator"],
              registry.outputs)
    write_csv(canonical_dir / "canonical_claims.csv",
              ["output_id", "appearance_index", "slot_id", "claim_text_sha256", "claim_text_length",
               "scope_qualification_sha256", "evidence_quotes_count", "source_titles_count",
               "generator_output_sha256", "source_locator"],
              registry.claims)
    write_csv(canonical_dir / "canonical_evaluations.csv",
              ["evaluator", "role", "output_id", "evaluation_id", "rubric_sha256", "task_binding_sha256",
               "context_binding_sha256", "generator_output_sha256", "judgement_file_sha256",
               "schema_status", "valid_abstention", "source_locator"],
              registry.evaluations)
    write_csv(canonical_dir / "canonical_claim_judgements.csv",
              ["evaluator", "role", "output_id", "topic_id", "task_id", "arm", "repetition",
               "appearance_index", "atomic", "support", "scope", "redundancy", "error_ids",
               "has_linked_error", "source_package_id", "source_file_sha256", "source_locator"],
              registry.claim_judgements)
    write_csv(canonical_dir / "canonical_error_events.csv",
              ["evaluator", "role", "output_id", "topic_id", "task_id", "arm", "repetition",
               "error_id", "affected_appearance_indices", "error_types",
               "source_package_id", "source_file_sha256", "source_locator"],
              registry.error_events)
    v = registry.validation
    print(f"[canonical] outputs={v['outputs']} claims={v['claims']} "
          f"primary_evaluations={v['primary_evaluations']} "
          f"primary_units={v['primary_claim_judgements']} "
          f"sensitivity_units={v['sensitivity_claim_judgements']} "
          f"lattice_complete={v['lattice_complete']} e_status={v['e_status_counts']}")
    atomic_write_json(output_dir / "registry_build_summary.json", {
        "tool": {"id": TOOL_ID, "version": TOOL_VERSION},
        "inventory_packages": len(inventory["packages"]),
        "integrity_counts": counts,
        "dag_summary": dag["summary"],
        "canonical_counts": {k: v[k] for k in ("outputs", "claims", "primary_evaluations",
                                               "sensitivity_evaluations", "primary_claim_judgements",
                                               "sensitivity_claim_judgements", "lattice")},
        "source_identities": registry.source_identities,
    })
    publish_staging(output_dir, final_target)
    print(f"[publish] {final_target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
