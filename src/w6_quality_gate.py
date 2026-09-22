"""Reusable orchestration for the W6 data-quality and leakage gate."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.annotation_tasks import sha256_file
from src.w6_contracts import _iter_w6_bootstrap_validation


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

    Basic and Full consume the same validation stages. Full continues from the
    verified base snapshot into annotation/method/fusion/synthesis/benchmark checks.
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

    checks = BASIC_CHECKS + (FULL_ONLY_CHECKS if normalized_mode == "full" else ())
    stages = _iter_w6_bootstrap_validation(requested_path, include_full=normalized_mode == "full")
    inventory = None
    try:
        for index, (name, category) in enumerate(checks):
            try:
                completed_name, value = next(stages)
            except (OSError, ValueError) as exc:
                _record_failed_check(report, name, category, str(exc))
                _append_skipped_checks(report, checks[index + 1:])
                break
            if completed_name != name:
                raise RuntimeError(f"unexpected W6 validation stage: {completed_name}")
            report["checks"].append(
                {"name": name, "category": category, "status": "PASS", "detail": None}
            )
            if name == "bundle_inventory":
                inventory = BundleInventory(**value)
                report["input"]["sha256"] = sha256_file(inventory.manifest_path)
                report["inventory"] = _serialize_inventory(inventory)
            elif name == "full_bundle_contract":
                _add_full_inventory(report, inventory.bundle_dir, value)
    finally:
        stages.close()

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
