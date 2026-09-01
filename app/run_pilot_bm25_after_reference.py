"""Run frozen Pilot BM25 only after finalized RCP Reference freeze."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from src.pilot_reference_curation import load_reference_curation_inputs
from src.pilot_reference_selection import build_bm25_selection_after_reference
from src.pilot_selection import capture_git_state, write_json
from src.w6_contracts import load_json_object


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT / "configs" / "pilot" / "srtp_pilot_v0.3_reference_curation_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute unchanged Pilot BM25 only after the exact same-Topic finalized "
            "non-fixture RCP Reference Selection is frozen."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--topic-id", required=True)
    parser.add_argument("--reference-selection-freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--created-at")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inputs = load_reference_curation_inputs(args.config, project_root=PROJECT_ROOT)
        reference = load_json_object(
            args.reference_selection_freeze, label="finalized Reference selection"
        )
        output = args.output.resolve()
        if output.exists():
            raise ValueError("BM25 output 已存在；禁止覆盖。")
        git_state = capture_git_state(PROJECT_ROOT)
        if not git_state["git_worktree_clean"]:
            raise ValueError("formal BM25 execution requires a clean worktree。")
        created_at = args.created_at or datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        selection = build_bm25_selection_after_reference(
            inputs,
            topic_id=args.topic_id,
            reference_selection_freeze=reference,
            created_at=created_at,
            git_revision=git_state["git_revision"],
        )
        write_json(output, selection)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Pilot BM25-after-Reference FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot BM25-after-Reference PASSED: "
        f"topic={args.topic_id}, k={selection['k']}, output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
