"""Build the blind SRTP Pilot v0.2 dual-curator preparation package."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from src.pilot_selection import build_curator_preparation_package


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT
    / "configs"
    / "pilot"
    / "srtp_pilot_v0.2_selection_context_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build deterministic blind curator tasks and blank response templates; "
            "this command does not perform human or BM25 selection."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest_path = build_curator_preparation_package(
            config_path=args.config,
            output_dir=args.output_dir,
            project_root=PROJECT_ROOT,
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        print(f"Pilot curator preparation build FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot curator preparation build PASSED: "
        f"tasks={manifest['task_count']}, "
        f"human_selection={manifest['human_selection_status']}, "
        f"bm25={manifest['bm25_execution_status']}, "
        f"manifest={manifest_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
