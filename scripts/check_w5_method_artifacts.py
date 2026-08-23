"""Validate every formal W5 method package committed to the promotion directory."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.w5_formal_policy import (
    FORMAL_METHOD_IDS,
    validate_formal_method_roster,
)
from src.w5_method_contract import validate_method_output


FORMAL_ARTIFACT_ROOT = PROJECT_ROOT / "data" / "analysis" / "w5_methods"


def discover_formal_manifests(artifact_root: str | Path) -> list[Path]:
    """Discover only ``<method-id>/manifest.json`` below the formal W5 root."""
    root = Path(artifact_root).resolve()
    if not root.is_dir():
        return []
    return sorted(
        path.resolve()
        for path in root.glob("*/manifest.json")
        if path.is_file()
    )


def check_formal_artifacts(
    *,
    project_root: str | Path = PROJECT_ROOT,
    artifact_root: str | Path = FORMAL_ARTIFACT_ROOT,
) -> int:
    """Validate the exact W5 final roster and return a CI-compatible exit code."""
    root = Path(project_root).resolve()
    formal_root = Path(artifact_root).resolve()
    if not formal_root.is_dir():
        print(f"FAIL formal artifact root 不存在或不是目录：{formal_root}")
        return 1

    package_dirs = sorted(path for path in formal_root.iterdir() if path.is_dir())
    if not package_dirs:
        print(f"FAIL formal artifact root 为空：{formal_root}")
        return 1

    failures = 0
    packages_by_directory = {}
    print(
        f"Discovered {len(package_dirs)} formal W5 package directories; "
        f"expected {len(FORMAL_METHOD_IDS)}."
    )
    for package_dir in package_dirs:
        manifest_path = package_dir / "manifest.json"
        if not manifest_path.is_file():
            failures += 1
            print(f"FAIL {package_dir}: 缺少顶层 manifest.json")
            continue
        try:
            result = validate_method_output(manifest_path, project_root=root)
        except (OSError, UnicodeError, ValueError) as error:
            failures += 1
            print(f"FAIL {manifest_path}: {error}")
        else:
            print(
                f"PASS {manifest_path}: method_id={result['method_id']}, "
                f"pairs={len(result['ranking_rows'])}"
            )
            packages_by_directory[package_dir.name] = result

    try:
        validate_formal_method_roster(packages_by_directory)
    except ValueError as error:
        failures += 1
        print(f"FAIL formal roster policy: {error}")

    if failures:
        print(f"W5 formal artifact check failed: {failures} failure(s).")
        return 1
    print(
        "W5 formal artifact check passed: "
        f"{len(packages_by_directory)}/{len(FORMAL_METHOD_IDS)} formal packages valid."
    )
    return 0


def main() -> int:
    return check_formal_artifacts()


if __name__ == "__main__":
    raise SystemExit(main())
