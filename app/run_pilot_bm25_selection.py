"""Run frozen Pilot BM25 only after formal human-selection freeze attestation."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from src.pilot_selection import (
    HUMAN_METHOD_ID,
    build_bm25_selection,
    capture_git_state,
    load_pilot_selection_inputs,
    validate_selection_artifact,
    write_json,
)
from src.w6_contracts import load_json_object


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT / "configs" / "pilot" / "srtp_pilot_v0.2_selection_context_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute frozen BM25 lexical Top-8. A validated final Dual-Curator "
            "selection for the same Topic is required as a blinding checkpoint."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--topic-id", required=True)
    parser.add_argument(
        "--human-selection-freeze",
        type=Path,
        required=True,
        help=(
            "Final non-fixture Dual-Curator selection whose artifact ID, identity, "
            "SHA-256, and frozen_at will be embedded in the BM25 artifact."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--created-at")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inputs = load_pilot_selection_inputs(args.config, project_root=PROJECT_ROOT)
        human_freeze = load_json_object(
            args.human_selection_freeze,
            label="final human selection freeze",
        )
        validated = validate_selection_artifact(human_freeze, inputs=inputs)
        if (
            validated["method_id"] != HUMAN_METHOD_ID
            or validated["is_fixture"]
            or validated["topic_id"] != args.topic_id
        ):
            raise ValueError(
                "BM25 formal execution requires a same-Topic final non-fixture "
                "Dual-Curator selection attestation."
            )
        output = args.output.resolve()
        if output.exists():
            raise ValueError("BM25 output 已存在；禁止覆盖。")
        git_state = capture_git_state(PROJECT_ROOT)
        if not git_state["git_worktree_clean"]:
            raise ValueError("BM25 formal execution requires a clean worktree.")
        created_at = args.created_at or datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        selection = build_bm25_selection(
            inputs,
            topic_id=args.topic_id,
            human_selection_freeze=human_freeze,
            created_at=created_at,
            git_revision=git_state["git_revision"],
        )
        write_json(output, selection)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Pilot BM25 selection FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot BM25 selection PASSED: "
        f"topic={args.topic_id}, k={selection['k']}, output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
