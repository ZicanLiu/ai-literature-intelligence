"""Reusable orchestration for the W6 data-quality and leakage gate."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.annotation_tasks import sha256_file
from src.w6_contracts import (
    PARALLEL_MODULE_FIXTURE_REQUIREMENTS,
    load_w6_bootstrap_bundle_inventory,
    validate_annotation_task_map,
    validate_artifact_identity_reference,
    validate_blind_annotation_tasks,
    validate_candidate_pool,
    validate_canonical_entities,
    validate_hidden_label_anchor,
    validate_retrieval_provenance,
    validate_source_records,
    validate_topic_set,
    validate_topic_split,
    validate_w6_bootstrap_bundle,
)


REPORT_SCHEMA_VERSION = "1.0"
GATE_NAME = "w6_data_quality_leakage_artifact_gate"
GATE_MODES = frozenset({"basic", "full"})

BASIC_CHECKS: tuple[tuple[str, str], ...] = (
    ("bundle_inventory", "artifact_inventory"),
    ("quality_gate_dependency_closure", "dependency_closure"),
    ("topic_identity", "identity"),
    ("retrieval_provenance", "provenance"),
    ("source_record_provenance", "provenance"),
    ("canonical_identity", "identity_provenance"),
    ("precanonical_pool_closure", "identity_provenance"),
    ("candidate_pool_closure", "identity_provenance"),
    ("blind_task_mapping", "identity_leakage"),
    ("blind_annotation_view", "leakage"),
    ("topic_split_leakage", "leakage"),
    ("hidden_label_seal", "leakage"),
)
FULL_ONLY_CHECKS: tuple[tuple[str, str], ...] = (
    ("full_bundle_contract", "full_contract"),
)


@dataclass(frozen=True)
class BundleInventory:
    """Manifest data loaded once for the staged Basic checks."""

    manifest_path: Path
    bundle_dir: Path
    manifest: dict[str, Any]
    registry: dict[str, dict[str, str]]
    payloads: dict[str, dict[str, Any]]
    paths: dict[str, Path]


def run_w6_quality_gate(manifest_path: str | Path, *, mode: str = "basic") -> dict[str, Any]:
    """Run the deterministic W6 gate and return a machine-readable report.

    Basic validates the public data, identity, provenance, blind-view, split, and
    hidden-label boundary. Full first runs Basic and then delegates the complete
    annotation/method/fusion/synthesis/benchmark contract to the public bundle
    validator.
    """

    normalized_mode = mode.lower()
    if normalized_mode not in GATE_MODES:
        raise ValueError(f"unsupported W6 gate mode: {mode}")

    requested_path = Path(manifest_path)
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "gate": GATE_NAME,
        "mode": normalized_mode,
        "result": "PASS",
        "input": {
            "manifest": requested_path.name,
            "sha256": None,
        },
        "inventory": {
            "bundle_id": None,
            "artifacts": [],
            "files": [],
        },
        "checks": [],
        "summary": {},
        "errors": [],
        "warnings": [],
        "failed_checks": [],
    }

    state: dict[str, Any] = {}
    check_index = 0

    def run_check(operation: Callable[[], Any]) -> bool:
        nonlocal check_index
        check_name, category = BASIC_CHECKS[check_index]
        check_index += 1
        try:
            value = operation()
        except (OSError, ValueError) as exc:
            _record_failed_check(report, check_name, category, str(exc))
            _append_skipped_checks(report, BASIC_CHECKS[check_index:])
            if normalized_mode == "full":
                _append_skipped_checks(report, FULL_ONLY_CHECKS)
            _finalize_report(report)
            return False
        report["checks"].append(
            {"name": check_name, "category": category, "status": "PASS", "detail": None}
        )
        state[check_name] = value
        return True

    if not run_check(lambda: _load_bundle_inventory(requested_path)):
        return report
    inventory: BundleInventory = state["bundle_inventory"]
    report["input"]["sha256"] = sha256_file(inventory.manifest_path)
    report["inventory"] = _serialize_inventory(inventory)

    if not run_check(lambda: _validate_quality_gate_dependency_closure(inventory.manifest)):
        return report
    if not run_check(lambda: validate_topic_set(inventory.payloads["topic_set"])):
        return report
    topics = state["topic_identity"]
    if not run_check(
        lambda: validate_retrieval_provenance(
            inventory.payloads["retrieval_provenance"], topics=topics
        )
    ):
        return report
    retrieval = state["retrieval_provenance"]
    if not run_check(
        lambda: validate_source_records(
            inventory.payloads["source_records"], topics=topics, retrieval=retrieval
        )
    ):
        return report
    records = state["source_record_provenance"]
    if not run_check(
        lambda: validate_canonical_entities(
            inventory.payloads["canonical_entities"], records=records, retrieval=retrieval
        )
    ):
        return report
    canonical = state["canonical_identity"]
    if not run_check(
        lambda: validate_candidate_pool(
            inventory.payloads["precanonical_candidate_pool"],
            topics=topics,
            records=records,
            retrieval=retrieval,
            registry=inventory.registry,
        )
    ):
        return report
    if not run_check(
        lambda: validate_candidate_pool(
            inventory.payloads["candidate_pool"],
            topics=topics,
            records=records,
            retrieval=retrieval,
            registry=inventory.registry,
            canonical=canonical,
        )
    ):
        return report
    pool_members = state["candidate_pool_closure"]
    if not run_check(
        lambda: validate_annotation_task_map(
            inventory.payloads["annotation_task_map"],
            records=records,
            pool_members=pool_members,
            registry=inventory.registry,
        )
    ):
        return report
    task_mappings = state["blind_task_mapping"]
    if not run_check(
        lambda: validate_blind_annotation_tasks(
            inventory.payloads["annotation_tasks"],
            topics=topics,
            records=records,
            task_mappings=task_mappings,
            registry=inventory.registry,
        )
    ):
        return report
    if not run_check(lambda: _validate_split(inventory, topics)):
        return report
    split_sets = state["topic_split_leakage"]
    if not run_check(
        lambda: validate_hidden_label_anchor(
            inventory.payloads["hidden_label_anchor"],
            split=inventory.payloads["split_manifest"],
            split_sets=split_sets,
            registry=inventory.registry,
        )
    ):
        return report

    if normalized_mode == "full":
        name, category = FULL_ONLY_CHECKS[0]
        try:
            validated_bundle = validate_w6_bootstrap_bundle(inventory.manifest_path)
        except (OSError, ValueError) as exc:
            _record_failed_check(report, name, category, str(exc))
        else:
            report["checks"].append(
                {"name": name, "category": category, "status": "PASS", "detail": None}
            )
            _add_full_inventory(report, inventory.bundle_dir, validated_bundle)

    _finalize_report(report)
    return report


def exit_code_for_report(report: dict[str, Any]) -> int:
    """Return the CI-friendly process code for a completed report."""

    return 0 if report.get("result") == "PASS" else 1


def write_w6_gate_report(report: dict[str, Any], output_path: str | Path) -> Path:
    """Atomically write a deterministic JSON report."""

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(rendered)
        temporary_path.replace(target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass
    return target


def remove_previous_gate_report(output_path: str | Path) -> None:
    """Remove only an existing report owned by this gate.

    This prevents an unexpected programming error from leaving a stale PASS file,
    while refusing to overwrite an unrelated user file.
    """

    target = Path(output_path)
    if not target.exists():
        return
    try:
        previous = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"refusing to overwrite non-gate output: {target}") from exc
    if not isinstance(previous, dict) or previous.get("gate") != GATE_NAME:
        raise ValueError(f"refusing to overwrite non-gate output: {target}")
    target.unlink()


def _load_bundle_inventory(manifest_path: Path) -> BundleInventory:
    loaded = load_w6_bootstrap_bundle_inventory(manifest_path)
    return BundleInventory(
        manifest_path=loaded["manifest_path"],
        bundle_dir=loaded["bundle_dir"],
        manifest=loaded["manifest"],
        registry=loaded["registry"],
        payloads=loaded["payloads"],
        paths=loaded["paths"],
    )


def _validate_quality_gate_dependency_closure(manifest: dict[str, Any]) -> None:
    parallel = manifest.get("parallel_development")
    if not isinstance(parallel, dict):
        raise ValueError("parallel_development must be an object")
    quality_gate = parallel.get("quality_gate")
    if not isinstance(quality_gate, dict):
        raise ValueError("quality_gate dependency declaration is missing")
    if set(quality_gate) != {"depends_on", "artifacts"}:
        raise ValueError("quality_gate dependency declaration fields invalid")
    if quality_gate["depends_on"] != ["w6_bootstrap"]:
        raise ValueError("quality_gate may depend only on the merged w6_bootstrap contract")
    artifacts = quality_gate["artifacts"]
    if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
        raise ValueError("quality_gate artifact dependency list invalid")
    if len(artifacts) != len(set(artifacts)):
        raise ValueError("quality_gate artifact dependency list contains duplicates")
    expected = PARALLEL_MODULE_FIXTURE_REQUIREMENTS["quality_gate"]
    if set(artifacts) != expected:
        missing = sorted(expected.difference(artifacts))
        extra = sorted(set(artifacts).difference(expected))
        raise ValueError(
            f"quality_gate dependency closure drift: missing={missing}, extra={extra}"
        )


def _validate_split(inventory: BundleInventory, topics: dict[str, Any]) -> dict[str, set[str]]:
    split = inventory.payloads["split_manifest"]
    split_sets = validate_topic_split(split, topics=topics)
    reference = validate_artifact_identity_reference(split["topic_set"], "split.topic_set")
    expected = inventory.registry.get(reference["artifact_id"])
    if expected != reference:
        raise ValueError("split.topic_set does not match the bundle artifact registry")
    return split_sets


def _serialize_inventory(inventory: BundleInventory) -> dict[str, Any]:
    artifacts = []
    files = [
        {
            "path": inventory.manifest_path.name,
            "sha256": sha256_file(inventory.manifest_path),
        }
    ]
    for name in sorted(inventory.paths):
        path = inventory.paths[name]
        reference = inventory.manifest["artifacts"][name]
        relative_path = path.relative_to(inventory.bundle_dir).as_posix()
        artifacts.append(
            {
                "name": name,
                "artifact_id": reference["artifact_id"],
                "path": relative_path,
                "sha256": reference["sha256"],
            }
        )
        files.append({"path": relative_path, "sha256": reference["sha256"]})
    return {
        "bundle_id": inventory.manifest["bundle_id"],
        "artifacts": artifacts,
        "files": sorted(files, key=lambda row: row["path"]),
    }


def _add_full_inventory(
    report: dict[str, Any], bundle_dir: Path, validated_bundle: dict[str, Any]
) -> None:
    files_by_path = {row["path"]: row for row in report["inventory"]["files"]}
    for method_package in validated_bundle["method_packages"].values():
        ranking_path = method_package["ranking_path"]
        relative_path = ranking_path.relative_to(bundle_dir).as_posix()
        files_by_path[relative_path] = {
            "path": relative_path,
            "sha256": method_package["ranking_sha256"],
        }
    report["inventory"]["files"] = sorted(files_by_path.values(), key=lambda row: row["path"])


def _record_failed_check(
    report: dict[str, Any], name: str, category: str, detail: str
) -> None:
    report["result"] = "FAIL"
    report["checks"].append(
        {"name": name, "category": category, "status": "FAIL", "detail": detail}
    )
    report["errors"].append({"check": name, "detail": detail})
    report["failed_checks"].append(name)


def _append_skipped_checks(
    report: dict[str, Any], checks: tuple[tuple[str, str], ...]
) -> None:
    for name, category in checks:
        report["checks"].append(
            {
                "name": name,
                "category": category,
                "status": "SKIP",
                "detail": "blocked by an earlier failed dependency",
            }
        )


def _finalize_report(report: dict[str, Any]) -> None:
    status_counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for check in report["checks"]:
        status_counts[check["status"]] += 1
    report["failed_checks"] = sorted(set(report["failed_checks"]))
    report["inventory"]["artifacts"] = sorted(
        report["inventory"]["artifacts"], key=lambda row: row["name"]
    )
    report["inventory"]["files"] = sorted(
        report["inventory"]["files"], key=lambda row: row["path"]
    )
    report["summary"] = {
        "artifact_count": len(report["inventory"]["artifacts"]),
        "file_count": len(report["inventory"]["files"]),
        "check_count": len(report["checks"]),
        "passed": status_counts["PASS"],
        "failed": status_counts["FAIL"],
        "skipped": status_counts["SKIP"],
        "error_count": len(report["errors"]),
        "warning_count": len(report["warnings"]),
    }
