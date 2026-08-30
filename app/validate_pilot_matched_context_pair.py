"""Validate pairwise matched-context fairness for SRTP Pilot v0.2."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.pilot_context import validate_formal_matched_context_pair
from src.pilot_selection import load_pilot_selection_inputs, write_json
from src.w6_contracts import load_json_object


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT / "configs" / "pilot" / "srtp_pilot_v0.2_selection_context_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Require same Pilot/Topic/Question/U80/K/context policy/tokenizer/"
            "representation/ordering and report the natural token delta."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--left-selection", type=Path, required=True)
    parser.add_argument("--left-context", type=Path, required=True)
    parser.add_argument("--right-selection", type=Path, required=True)
    parser.add_argument("--right-context", type=Path, required=True)
    parser.add_argument(
        "--human-selection-freeze",
        type=Path,
        required=True,
        help="Final Dual-Curator artifact hash-bound by the BM25 selection.",
    )
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inputs = load_pilot_selection_inputs(args.config, project_root=PROJECT_ROOT)
        left_selection = load_json_object(
            args.left_selection, label="left Pilot selection"
        )
        left_context = load_json_object(args.left_context, label="left context")
        right_selection = load_json_object(
            args.right_selection, label="right Pilot selection"
        )
        right_context = load_json_object(args.right_context, label="right context")
        human_freeze = load_json_object(
            args.human_selection_freeze, label="Human selection freeze"
        )
        report = validate_formal_matched_context_pair(
            left_context,
            right_context,
            left_selection=left_selection,
            right_selection=right_selection,
            inputs=inputs,
            left_human_selection_freeze=human_freeze,
            right_human_selection_freeze=human_freeze,
        )
        if args.report:
            if args.report.exists():
                raise ValueError("pair validation report 已存在；禁止覆盖。")
            write_json(args.report, report)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Pilot matched-context pair validation FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot matched-context pair validation PASSED: "
        f"topic={report['topic']['topic_id']}, "
        f"token_delta={report['actual_token_delta_left_minus_right']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
