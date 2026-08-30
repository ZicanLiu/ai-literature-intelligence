"""Thin offline validator for the SRTP Pilot v0.2 real-data package."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.pilot_real_data_foundation import validate_pilot_package


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT
    / "configs"
    / "pilot"
    / "srtp_pilot_v0.2_real_data_foundation_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the canonical U80 package and all input/output hash closure."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--package-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = validate_pilot_package(
            args.package_dir,
            config_path=args.config,
            project_root=PROJECT_ROOT,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Pilot real-data foundation validation FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot real-data foundation validation PASSED: "
        f"topics={manifest['counts']['topic_count']}, "
        f"runs={manifest['counts']['query_run_count']}, "
        f"u80_total={manifest['counts']['u80_total_count']}, "
        f"u80_identity={manifest['identities']['u80_identity']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
