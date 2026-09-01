"""Validate one SRTP Pilot v0.2 matched-context artifact."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.pilot_context import validate_matched_context
from src.pilot_selection import load_pilot_selection_inputs
from src.w6_contracts import load_json_object


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT / "configs" / "pilot" / "srtp_pilot_v0.2_selection_context_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct exact context text, ordering, snapshots, truncation, token "
            "counts, identities, and hashes from frozen inputs."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--selection", type=Path, required=True)
    freeze_group = parser.add_mutually_exclusive_group()
    freeze_group.add_argument("--human-selection-freeze", type=Path)
    freeze_group.add_argument("--reference-selection-freeze", type=Path)
    parser.add_argument("--context", type=Path, required=True)
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
        reference_freeze = (
            load_json_object(
                args.reference_selection_freeze,
                label="Reference selection freeze",
            )
            if args.reference_selection_freeze
            else None
        )
        context = load_json_object(args.context, label="Pilot matched context")
        validated = validate_matched_context(
            context,
            selection=selection,
            inputs=inputs,
            human_selection_freeze=human_freeze,
            reference_selection_freeze=reference_freeze,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Pilot matched-context validation FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot matched-context validation PASSED: "
        f"topic={validated['topic_id']}, k={validated['k']}, "
        f"tokens={validated['actual_total_token_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
