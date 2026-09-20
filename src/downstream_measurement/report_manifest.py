"""Phase M: research artifact manifests for every derived output bundle."""
from __future__ import annotations

import datetime
import platform
import subprocess
import sys
from pathlib import Path

from . import TOOL_ID, TOOL_VERSION
from .util import assert_no_absolute_paths, atomic_write_json, sha256_file


def git_state(worktree: Path) -> dict:
    def run(args):
        result = subprocess.run(["git", *args], cwd=str(worktree), capture_output=True, text=True, encoding="utf-8")
        return result.stdout.strip() if result.returncode == 0 else None

    return {
        "revision": run(["rev-parse", "HEAD"]),
        "branch": run(["branch", "--show-current"]),
        "clean": run(["status", "--porcelain"]) == "",
    }


def build_manifest(output_dir: Path, worktree: Path, source_identities: dict, source_packages: dict,
                   analysis_config: dict, limitation_flags: list[str], missing_source_bytes: list[dict],
                   registry_inputs: dict | None = None) -> dict:
    output_dir = Path(output_dir)
    outputs = {}
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.name not in {"manifest.json"}:
            outputs[path.relative_to(output_dir).as_posix()] = sha256_file(path)
    manifest = {
        "schema_version": "1.0",
        "artifact_type": "downstream_measurement_derived_analysis",
        "tool": {"id": TOOL_ID, "version": TOOL_VERSION},
        "created_at": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
        "git": git_state(worktree),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "source_identities": source_identities,
        "source_packages": source_packages,
        "registry_inputs": registry_inputs or {},
        "analysis_config": analysis_config,
        "labels": {
            "primary": ["first_look_reproduction (reproduction of frozen primary first-look)"],
            "diagnostic": [
                "decomposition", "sensitivity (incl. Full Pro SENSITIVITY_EVALUATOR)",
                "influence", "counterfactual metric variants", "error event audit",
            ],
        },
        "limitation_flags": limitation_flags,
        "known_missing_source_bytes": missing_source_bytes,
        "outputs": outputs,
    }
    assert_no_absolute_paths(manifest, "manifest")
    atomic_write_json(output_dir / "manifest.json", manifest)
    return manifest
