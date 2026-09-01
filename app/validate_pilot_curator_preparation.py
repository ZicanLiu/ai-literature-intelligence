"""Validate the committed SRTP Pilot v0.2 curator preparation package."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.pilot_selection import validate_curator_preparation_package


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT
    / "configs"
    / "pilot"
    / "srtp_pilot_v0.2_selection_context_v1.json"
)
DEFAULT_PACKAGE = (
    PROJECT_ROOT
    / "data"
    / "research"
    / "pilot"
    / "v0.2"
    / "selection-preparation-v1"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate blind tasks, coordinator maps, blank templates, file closure, "
            "hashes, and deterministic reconstruction."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = validate_curator_preparation_package(
            args.package_dir,
            config_path=args.config,
            project_root=PROJECT_ROOT,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Pilot curator preparation validation FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot curator preparation validation PASSED: "
        f"tasks={manifest['task_count']}, topics={manifest['topic_count']}, "
        f"status={manifest['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
