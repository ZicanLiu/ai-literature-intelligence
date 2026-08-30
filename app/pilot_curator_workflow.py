"""CLI for response import, overlap, adjudication, and final human selection."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from src.pilot_selection import (
    build_adjudication_task,
    build_curator_comparison,
    build_final_human_selection,
    capture_git_state,
    import_adjudication_submission,
    import_curator_submission,
    load_pilot_selection_inputs,
    payload_sha256,
    validate_completed_curator_response,
    write_json,
)
from src.w6_contracts import load_json_object


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT
    / "configs"
    / "pilot"
    / "srtp_pilot_v0.2_selection_context_v1.json"
)


def _add_output_and_time(parser: argparse.ArgumentParser, time_flag: str) -> None:
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(time_flag)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Import independent curator data and enforce the frozen overlap/"
            "symmetric-difference adjudication protocol."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-response")
    validate.add_argument("--task", type=Path, required=True)
    validate.add_argument("--candidate-map", type=Path, required=True)
    validate.add_argument("--response", type=Path, required=True)

    import_response = commands.add_parser("import-response")
    import_response.add_argument("--task", type=Path, required=True)
    import_response.add_argument("--candidate-map", type=Path, required=True)
    import_response.add_argument("--response", type=Path, required=True)
    _add_output_and_time(import_response, "--imported-at")

    compare = commands.add_parser("compare")
    compare.add_argument("--submission-a", type=Path, required=True)
    compare.add_argument("--submission-b", type=Path, required=True)
    _add_output_and_time(compare, "--created-at")

    adjudication_task = commands.add_parser("build-adjudication-task")
    adjudication_task.add_argument("--comparison", type=Path, required=True)
    adjudication_task.add_argument("--candidate-map", type=Path, required=True)
    _add_output_and_time(adjudication_task, "--created-at")

    import_adjudication = commands.add_parser("import-adjudication")
    import_adjudication.add_argument("--task", type=Path, required=True)
    import_adjudication.add_argument("--candidate-map", type=Path, required=True)
    import_adjudication.add_argument("--response", type=Path, required=True)
    _add_output_and_time(import_adjudication, "--imported-at")

    final = commands.add_parser("build-final-selection")
    final.add_argument("--comparison", type=Path, required=True)
    final.add_argument("--adjudication", type=Path)
    _add_output_and_time(final, "--created-at")
    return parser


def _load(path: Path, label: str) -> dict[str, Any]:
    return load_json_object(path, label=label)


def _now(value: str | None) -> str:
    return value or datetime.now().astimezone().isoformat(timespec="seconds")


def _provenance_revision() -> str:
    state = capture_git_state(PROJECT_ROOT)
    if not state["git_worktree_clean"]:
        raise ValueError("human workflow artifact import/build requires a clean worktree.")
    return state["git_revision"]


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise ValueError(f"output 已存在；禁止覆盖：{path}")
    write_json(path, payload)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inputs = load_pilot_selection_inputs(args.config, project_root=PROJECT_ROOT)
        if args.command == "validate-response":
            validated = validate_completed_curator_response(
                _load(args.response, "curator response"),
                task=_load(args.task, "curator task"),
                mapping=_load(args.candidate_map, "candidate map"),
            )
            print(
                "Pilot curator response validation PASSED: "
                f"slot={validated['curator_slot']}, selected=8"
            )
            return 0

        revision = _provenance_revision()
        if args.command == "import-response":
            payload = import_curator_submission(
                _load(args.response, "curator response"),
                task=_load(args.task, "curator task"),
                mapping=_load(args.candidate_map, "candidate map"),
                imported_at=_now(args.imported_at),
                git_revision=revision,
            )
        elif args.command == "compare":
            payload = build_curator_comparison(
                _load(args.submission_a, "curator submission A"),
                _load(args.submission_b, "curator submission B"),
                created_at=_now(args.created_at),
                git_revision=revision,
            )
        elif args.command == "build-adjudication-task":
            payload = build_adjudication_task(
                _load(args.comparison, "curator comparison"),
                mapping=_load(args.candidate_map, "candidate map"),
                inputs=inputs,
                created_at=_now(args.created_at),
                git_revision=revision,
            )
        elif args.command == "import-adjudication":
            payload = import_adjudication_submission(
                _load(args.response, "adjudication response"),
                task=_load(args.task, "adjudication task"),
                mapping=_load(args.candidate_map, "candidate map"),
                imported_at=_now(args.imported_at),
                git_revision=revision,
            )
        else:
            comparison = _load(args.comparison, "curator comparison")
            adjudication = (
                _load(args.adjudication, "adjudication submission")
                if args.adjudication
                else None
            )
            payload = build_final_human_selection(
                comparison,
                inputs=inputs,
                comparison_sha256=payload_sha256(comparison),
                adjudication=adjudication,
                adjudication_sha256=(
                    payload_sha256(adjudication) if adjudication is not None else None
                ),
                created_at=_now(args.created_at),
                git_revision=revision,
            )
        _write_new(args.output, payload)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Pilot curator workflow FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot curator workflow PASSED: "
        f"command={args.command}, artifact={payload['artifact_id']}, output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
