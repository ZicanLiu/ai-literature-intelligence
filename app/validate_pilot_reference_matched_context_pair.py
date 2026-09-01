"""Validate formal BM25-vs-RCP-Reference matched-context pairing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.pilot_context import validate_formal_reference_matched_context_pair
from src.pilot_reference_curation import load_reference_curation_inputs
from src.pilot_selection import write_json
from src.w6_contracts import load_json_object


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT / "configs" / "pilot" / "srtp_pilot_v0.3_reference_curation_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the exact BM25/Reference roster from frozen comparison config, "
            "the Reference-freeze binding, and matched-context fairness."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--left-selection", type=Path, required=True)
    parser.add_argument("--left-context", type=Path, required=True)
    parser.add_argument("--right-selection", type=Path, required=True)
    parser.add_argument("--right-context", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inputs = load_reference_curation_inputs(args.config, project_root=PROJECT_ROOT)
        left_selection = load_json_object(
            args.left_selection, label="left Pilot selection"
        )
        left_context = load_json_object(args.left_context, label="left context")
        right_selection = load_json_object(
            args.right_selection, label="right Pilot selection"
        )
        right_context = load_json_object(args.right_context, label="right context")
        report = validate_formal_reference_matched_context_pair(
            left_context,
            right_context,
            left_selection=left_selection,
            right_selection=right_selection,
            inputs=inputs.pilot_inputs,
            comparison_policy=inputs.config["comparison_policy"],
        )
        if args.report:
            output = args.report.resolve()
            if output.exists():
                raise ValueError("pair report 已存在；禁止覆盖。")
            write_json(output, report)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Pilot BM25-vs-Reference pair FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot BM25-vs-Reference pair PASSED: "
        f"topic={report['topic']['topic_id']}, "
        f"token_delta={report['actual_token_delta_left_minus_right']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
