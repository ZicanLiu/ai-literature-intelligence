"""Build one selection-method-agnostic SRTP Pilot v0.2 evidence context."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from src.pilot_context import build_matched_context
from src.pilot_selection import (
    capture_git_state,
    load_pilot_selection_inputs,
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
            "Build exact Title+Abstract evidence context from a validated generic "
            "selection. This does not build an LLM prompt or call an LLM."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--human-selection-freeze", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--created-at")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inputs = load_pilot_selection_inputs(args.config, project_root=PROJECT_ROOT)
        selection = load_json_object(args.selection, label="Pilot selection")
        human_freeze = (
            load_json_object(
                args.human_selection_freeze, label="Human selection freeze"
            )
            if args.human_selection_freeze
            else None
        )
        output = args.output.resolve()
        if output.exists():
            raise ValueError("matched context output 已存在；禁止覆盖。")
        git_state = capture_git_state(PROJECT_ROOT)
        if not git_state["git_worktree_clean"]:
            raise ValueError("formal matched-context build requires a clean worktree.")
        created_at = args.created_at or datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        context = build_matched_context(
            inputs=inputs,
            selection=selection,
            human_selection_freeze=human_freeze,
            created_at=created_at,
            git_revision=git_state["git_revision"],
        )
        write_json(output, context)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Pilot matched-context build FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot matched-context build PASSED: "
        f"topic={context['topic']['topic_id']}, k={context['k']}, "
        f"tokens={context['actual_total_token_count']}, output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
