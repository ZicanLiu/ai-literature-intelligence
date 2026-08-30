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
    load_boundary_ranking_config_artifact,
    load_w6_boundary_generation_inputs,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUTS = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "w6_bootstrap"
    / "valid"
    / "boundary_generation_inputs.json"
)
DEFAULT_CONFIG = (
    PROJECT_ROOT / "configs" / "w6" / "boundary_aware_structured_lexical_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the deterministic W6 Boundary-Aware prototype package."
    )
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        environment = capture_generation_environment(PROJECT_ROOT)
        inputs = load_w6_boundary_generation_inputs(args.inputs)
        config_artifact = load_boundary_ranking_config_artifact(args.config)
        now = datetime.now().astimezone().replace(microsecond=0)
        payloads = inputs.payloads
        manifest = build_w6_boundary_method_package(
            topics=inputs.topics,
            pool_members=inputs.pool_members,
            records=inputs.records,
            artifact_registry=inputs.registry,
            topic_reference=inputs.registry[payloads["topic_set"]["artifact_id"]],
            candidate_pool_reference=inputs.registry[
                payloads["candidate_pool"]["artifact_id"]
            ],
            source_records_reference=inputs.registry[
                payloads["source_records"]["artifact_id"]
            ],
            retrieval_reference=inputs.registry[
                payloads["retrieval_provenance"]["artifact_id"]
            ],
            canonical_reference=inputs.registry[
                payloads["canonical_entities"]["artifact_id"]
            ],
            frozen_input_paths=[inputs.manifest_path, *inputs.paths.values()],
            config_artifact=config_artifact,
            output_dir=args.output_dir,
            is_fixture=bool(inputs.manifest["is_fixture"]),
            generated_at=now.isoformat(),
            frozen_at=(now + timedelta(seconds=1)).isoformat(),
            git_revision=environment["git_revision"],
            git_worktree_clean=environment["git_worktree_clean"],
            backend=DeterministicLexicalBoundaryBackend(),
            method_id=DEFAULT_METHOD_ID,
            artifact_id=f"w6_{DEFAULT_METHOD_ID}",
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"W6 Boundary-Aware ranking generation FAILED: {error}")
        return 1
    print(f"W6 Boundary-Aware method package PASSED self-validation: {manifest}")
    print("Generation used no Dev/Hidden relevance labels or external model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
