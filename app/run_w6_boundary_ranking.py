"""Generate a W6-compatible Boundary-Aware ranking package."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

from src.w5_baseline_export import capture_generation_environment
from src.w6_boundary_ranking import (
    DEFAULT_METHOD_ID,
    DeterministicLexicalBoundaryBackend,
    build_w6_boundary_method_package,
    load_boundary_ranking_config,
)
from src.w6_contracts import validate_w6_bootstrap_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = (
    PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap" / "valid" / "bundle_manifest.json"
)
DEFAULT_CONFIG = (
    PROJECT_ROOT / "configs" / "w6" / "boundary_aware_structured_lexical_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the deterministic W6 Boundary-Aware prototype package."
    )
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--method-id", default=DEFAULT_METHOD_ID)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        environment = capture_generation_environment(PROJECT_ROOT)
        bundle = validate_w6_bootstrap_bundle(args.bundle)
        configuration = load_boundary_ranking_config(args.config)
        now = datetime.now().astimezone().replace(microsecond=0)
        payloads = bundle["payloads"]
        manifest = build_w6_boundary_method_package(
            topics=bundle["topics"],
            pool_members=bundle["pool_members"],
            records=bundle["records"],
            artifact_registry=bundle["registry"],
            topic_reference=bundle["registry"][payloads["topic_set"]["artifact_id"]],
            candidate_pool_reference=bundle["registry"][payloads["candidate_pool"]["artifact_id"]],
            source_records_reference=bundle["registry"][payloads["source_records"]["artifact_id"]],
            output_dir=args.output_dir,
            is_fixture=bool(bundle["manifest"]["is_fixture"]),
            generated_at=now.isoformat(),
            frozen_at=(now + timedelta(seconds=1)).isoformat(),
            git_revision=environment["git_revision"],
            git_worktree_clean=environment["git_worktree_clean"],
            backend=DeterministicLexicalBoundaryBackend(),
            method_id=args.method_id,
            artifact_id=f"w6_{args.method_id}",
            config=configuration,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"W6 Boundary-Aware ranking generation FAILED: {error}")
        return 1
    print(f"W6 Boundary-Aware method package PASSED self-validation: {manifest}")
    print("Generation used no Dev/Hidden relevance labels or external model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
