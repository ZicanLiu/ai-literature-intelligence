"""Validate the committed RCP-v0.3 preparation package."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.pilot_reference_curation import validate_reference_preparation_package


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT / "configs" / "pilot" / "srtp_pilot_v0.3_reference_curation_v1.json"
)
DEFAULT_PACKAGE = (
    PROJECT_ROOT
    / "data"
    / "research"
    / "pilot"
    / "v0.3"
    / "reference-curation-preparation-v1"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate RCP-v0.3 protocol/config/prompt/roster-template closure and "
            "confirm that real execution remains not started."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = validate_reference_preparation_package(
            args.package_dir,
            config_path=args.config,
            project_root=PROJECT_ROOT,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Pilot RCP-v0.3 validation FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot RCP-v0.3 validation PASSED: "
        f"status={result['status']}, real_model_judgements_started=false, "
        f"manifest_sha256={result['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
