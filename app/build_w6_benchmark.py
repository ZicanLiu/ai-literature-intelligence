"""Build a fixture-driven W6 Benchmark v0.2-alpha workflow package."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from src.w5_baseline_export import capture_generation_environment
from src.w6_benchmark import (
    artifact_paths_from_bootstrap_bundle,
    build_w6_benchmark_package,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "w6_bootstrap"
    / "valid"
    / "bundle_manifest.json"
)
DEFAULT_PROTOCOL = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "w6_issue64"
    / "annotation_protocol_fixture.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a hash-pinned W6 Benchmark workflow package from declared artifacts."
    )
    parser.add_argument("--source-bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--annotation-protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        environment = capture_generation_environment(PROJECT_ROOT)
        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        package = build_w6_benchmark_package(
            artifact_paths=artifact_paths_from_bootstrap_bundle(args.source_bundle),
            annotation_protocol_path=args.annotation_protocol,
            output_dir=args.output_dir,
            status="bootstrap_fixture",
            created_at=created_at,
            git_revision=environment["git_revision"],
            git_worktree_clean=environment["git_worktree_clean"],
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"W6 Benchmark package build FAILED: {error}")
        return 1
    print(f"W6 Benchmark workflow package PASSED self-validation: {package}")
    print(
        "Status is non-approved; real Multi-Retriever/annotation integration remains deferred."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
