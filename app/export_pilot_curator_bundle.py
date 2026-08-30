"""Export a fillable Pilot curator bundle outside the Git repository."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from src.pilot_selection import capture_git_state, export_curator_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT / "configs" / "pilot" / "srtp_pilot_v0.2_selection_context_v1.json"
)
DEFAULT_PACKAGE = (
    PROJECT_ROOT / "data" / "research" / "pilot" / "v0.2" / "selection-preparation-v1"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Copy one curator's instructions, two task Markdown files, and two "
            "blank responses to a repository-external workspace."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument(
        "--curator-slot", choices=("curator_a", "curator_b"), required=True
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--exported-at")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        git_state = capture_git_state(PROJECT_ROOT)
        if not git_state["git_worktree_clean"]:
            raise ValueError("curator export requires a clean Git worktree.")
        exported_at = args.exported_at or datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        manifest_path = export_curator_bundle(
            package_dir=args.package_dir,
            curator_slot=args.curator_slot,
            output_dir=args.output_dir,
            config_path=args.config,
            project_root=PROJECT_ROOT,
            exported_at=exported_at,
            git_revision=git_state["git_revision"],
        )
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        print(f"Pilot curator export FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot curator export PASSED: "
        f"slot={args.curator_slot}, external_manifest={manifest_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
