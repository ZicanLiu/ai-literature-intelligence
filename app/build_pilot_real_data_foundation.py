"""Thin CLI for the SRTP Pilot v0.2 real-data foundation build."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from src.pilot_real_data_foundation import build_pilot_package


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT
    / "configs"
    / "pilot"
    / "srtp_pilot_v0.2_real_data_foundation_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the committed OpenAlex audit package and build the two-Topic "
            "canonical U80 calibration foundation completely offline."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest_path = build_pilot_package(
            config_path=args.config,
            output_dir=args.output_dir,
            project_root=PROJECT_ROOT,
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        print(f"Pilot real-data foundation build FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot real-data foundation build PASSED: "
        f"package_identity={manifest['package_identity']}, "
        f"u80_total={manifest['counts']['u80_total_count']}, "
        f"manifest={manifest_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
