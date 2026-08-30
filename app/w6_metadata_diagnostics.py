"""Thin CLI for W6 metadata and retrieval diagnostics."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from src.w6_metadata_diagnostics import run_diagnostics


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate four W6 artifacts and generate label-free candidate metadata "
            "and retrieval diagnostics."
        )
    )
    parser.add_argument("--topics", type=Path, required=True, help="W6 topic-set JSON")
    parser.add_argument(
        "--retrieval", type=Path, required=True, help="W6 retrieval runs/hits JSON"
    )
    parser.add_argument(
        "--source-records", type=Path, required=True, help="W6 source-records JSON"
    )
    parser.add_argument(
        "--precanonical-pool",
        type=Path,
        required=True,
        help="W6 pre-canonical candidate-pool JSON",
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Output directory for JSON/CSV"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        revision = _git_revision(PROJECT_ROOT)
        result = run_diagnostics(
            topics_path=args.topics,
            retrieval_path=args.retrieval,
            source_records_path=args.source_records,
            precanonical_pool_path=args.precanonical_pool,
            output_dir=args.output_dir,
            git_revision=revision,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"W6 metadata diagnostics FAILED: {error}", file=sys.stderr)
        return 1
    counts = result["report"]["counts"]
    print(
        "W6 metadata diagnostics PASSED: "
        f"topics={counts['topic_count']}, "
        f"runs={counts['retrieval_run_count']}, "
        f"hits={counts['retrieval_hit_count']}, "
        f"records={counts['source_record_count']}, "
        f"pool_members={counts['precanonical_pool_member_count']}."
    )
    print(f"Report: {result['paths']['report']}")
    print(f"Metadata CSV: {result['paths']['metadata_csv']}")
    return 0


def _git_revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    revision = result.stdout.strip() if result.returncode == 0 else ""
    if not GIT_REVISION_PATTERN.fullmatch(revision):
        raise RuntimeError("cannot resolve a complete Git revision for report provenance.")
    return revision


if __name__ == "__main__":
    raise SystemExit(main())
