"""Validate every formal W5 method package committed to the promotion directory."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
    """Validate all discovered packages and return a CI-compatible exit code."""
    root = Path(project_root).resolve()
    manifests = discover_formal_manifests(artifact_root)
    if not manifests:
        print(
            "No formal W5 artifacts found under "
            "data/analysis/w5_methods/<method-id>/manifest.json; check passed."
        )
        return 0

    failures = 0
    print(f"Discovered {len(manifests)} formal W5 artifact(s).")
    for manifest_path in manifests:
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

    if failures:
        print(f"W5 formal artifact check failed: {failures}/{len(manifests)} invalid.")
        return 1
    print(f"W5 formal artifact check passed: {len(manifests)}/{len(manifests)} valid.")
    return 0


def main() -> int:
    return check_formal_artifacts()


if __name__ == "__main__":
    raise SystemExit(main())
