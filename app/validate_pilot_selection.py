"""Validate one generic SRTP Pilot v0.2 selection artifact."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.pilot_selection import load_pilot_selection_inputs, validate_selection_artifact
from src.w6_contracts import load_json_object


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT
    / "configs"
    / "pilot"
    / "srtp_pilot_v0.2_selection_context_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate generic selection schema, Topic/Question/U80 binding, K=8, "
            "method provenance, fixture separation, and artifact identity."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--selection", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inputs = load_pilot_selection_inputs(args.config, project_root=PROJECT_ROOT)
        selection = load_json_object(args.selection, label="Pilot selection")
        validated = validate_selection_artifact(selection, inputs=inputs)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Pilot selection validation FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot selection validation PASSED: "
        f"topic={validated['topic_id']}, method={validated['method_id']}, "
        f"k={validated['k']}, fixture={validated['is_fixture']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
