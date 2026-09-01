"""Trusted-package CLI for Pilot curator import and adjudication workflow."""

from __future__ import annotations

import argparse
import subprocess
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
    load_curator_import_chain_from_package,
    load_pilot_selection_inputs,
    validate_completed_curator_response,
    validate_curator_submission_against_package,
    validate_external_output_path,
    write_json,
)
from src.w6_contracts import load_json_object


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT / "configs" / "pilot" / "srtp_pilot_v0.2_selection_context_v1.json"
)
DEFAULT_PACKAGE = (
    PROJECT_ROOT / "data" / "research" / "pilot" / "v0.2" / "selection-preparation-v1"
)


def _add_package(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)


def _add_output_and_time(parser: argparse.ArgumentParser, time_flag: str) -> None:
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(time_flag)


def _add_original_submissions(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--submission-a", type=Path, required=True)
    parser.add_argument("--submission-b", type=Path, required=True)


def _add_adjudication_chain(parser: argparse.ArgumentParser) -> None:
    _add_original_submissions(parser)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument(
        "--source-curator-slot",
        choices=("curator_a", "curator_b"),
        default="curator_a",
        help="Private map used only to decode adjudication opaque IDs.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Import repository-external human responses by reconstructing the "
            "trusted committed preparation-package identity chain."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-response")
    _add_package(validate)
    validate.add_argument(
        "--curator-slot", choices=("curator_a", "curator_b"), required=True
    )
    validate.add_argument("--response", type=Path, required=True)

    import_response = commands.add_parser("import-response")
    _add_package(import_response)
    import_response.add_argument(
        "--curator-slot", choices=("curator_a", "curator_b"), required=True
    )
    import_response.add_argument("--response", type=Path, required=True)
    _add_output_and_time(import_response, "--imported-at")

    compare = commands.add_parser("compare")
    _add_package(compare)
    _add_original_submissions(compare)
    _add_output_and_time(compare, "--created-at")

    adjudication_task = commands.add_parser("build-adjudication-task")
    _add_package(adjudication_task)
    _add_adjudication_chain(adjudication_task)
    _add_output_and_time(adjudication_task, "--created-at")

    import_adjudication = commands.add_parser("import-adjudication")
    _add_package(import_adjudication)
    _add_adjudication_chain(import_adjudication)
    import_adjudication.add_argument("--task", type=Path, required=True)
    import_adjudication.add_argument("--response", type=Path, required=True)
    _add_output_and_time(import_adjudication, "--imported-at")

    final = commands.add_parser("build-final-selection")
    _add_package(final)
    _add_adjudication_chain(final)
    final.add_argument("--adjudication-task", type=Path)
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
        raise ValueError(
            "human workflow artifact import/build requires a clean worktree."
        )
    return state["git_revision"]


def _write_new(path: Path, payload: dict[str, Any]) -> Path:
    output = validate_external_output_path(path, project_root=PROJECT_ROOT)
    if output.exists():
        raise ValueError(f"output 已存在；禁止覆盖：{output}")
    write_json(output, payload)
    return output


def _load_originals(args, inputs):
    submission_a = _load(args.submission_a, "curator submission A")
    submission_b = _load(args.submission_b, "curator submission B")
    chain_a = validate_curator_submission_against_package(
        submission_a, package_dir=args.package_dir, inputs=inputs
    )
    chain_b = validate_curator_submission_against_package(
        submission_b, package_dir=args.package_dir, inputs=inputs
    )
    if chain_a["manifest_sha256"] != chain_b["manifest_sha256"]:
        raise ValueError("A/B submissions trusted package hash 不一致。")
    return submission_a, submission_b, chain_a, chain_b


def _source_chain(args, submission_a, submission_b, inputs):
    source_submission = (
        submission_a if args.source_curator_slot == "curator_a" else submission_b
    )
    return validate_curator_submission_against_package(
        source_submission, package_dir=args.package_dir, inputs=inputs
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        external_output = (
            validate_external_output_path(args.output, project_root=PROJECT_ROOT)
            if hasattr(args, "output")
            else None
        )
        inputs = load_pilot_selection_inputs(args.config, project_root=PROJECT_ROOT)
        if args.command in {"validate-response", "import-response"}:
            response = _load(args.response, "repository-external curator response")
            chain = load_curator_import_chain_from_package(
                package_dir=args.package_dir,
                response=response,
                inputs=inputs,
                expected_curator_slot=args.curator_slot,
            )
            validated = validate_completed_curator_response(
                response, task=chain["task"], mapping=chain["mapping"]
            )
            if args.command == "validate-response":
                print(
                    "Pilot external curator response validation PASSED: "
                    f"slot={validated['curator_slot']}, selected=8"
                )
                return 0
            payload = import_curator_submission(
                response,
                task=chain["task"],
                mapping=chain["mapping"],
                preparation_manifest=chain["manifest"],
                preparation_manifest_sha256=chain["manifest_sha256"],
                inputs=inputs,
                expected_curator_slot=args.curator_slot,
                imported_at=_now(args.imported_at),
                git_revision=_provenance_revision(),
            )
        else:
            revision = _provenance_revision()
            submission_a, submission_b, chain_a, _ = _load_originals(args, inputs)
            manifest = chain_a["manifest"]
            manifest_sha256 = chain_a["manifest_sha256"]
            if args.command == "compare":
                payload = build_curator_comparison(
                    submission_a,
                    submission_b,
                    inputs=inputs,
                    preparation_manifest=manifest,
                    preparation_manifest_sha256=manifest_sha256,
                    created_at=_now(args.created_at),
                    git_revision=revision,
                )
            else:
                comparison = _load(args.comparison, "curator comparison")
                source = _source_chain(args, submission_a, submission_b, inputs)
                if args.command == "build-adjudication-task":
                    payload = build_adjudication_task(
                        comparison,
                        submission_a=submission_a,
                        submission_b=submission_b,
                        source_task=source["task"],
                        mapping=source["mapping"],
                        inputs=inputs,
                        preparation_manifest=manifest,
                        preparation_manifest_sha256=manifest_sha256,
                        created_at=_now(args.created_at),
                        git_revision=revision,
                    )
                elif args.command == "import-adjudication":
                    task = _load(args.task, "adjudication task")
                    payload = import_adjudication_submission(
                        _load(args.response, "adjudication response"),
                        task=task,
                        comparison=comparison,
                        submission_a=submission_a,
                        submission_b=submission_b,
                        source_task=source["task"],
                        mapping=source["mapping"],
                        inputs=inputs,
                        preparation_manifest=manifest,
                        preparation_manifest_sha256=manifest_sha256,
                        imported_at=_now(args.imported_at),
                        git_revision=revision,
                    )
                else:
                    adjudication_task = (
                        _load(args.adjudication_task, "adjudication task")
                        if args.adjudication_task
                        else None
                    )
                    adjudication = (
                        _load(args.adjudication, "adjudication submission")
                        if args.adjudication
                        else None
                    )
                    payload = build_final_human_selection(
                        comparison,
                        inputs=inputs,
                        submission_a=submission_a,
                        submission_b=submission_b,
                        preparation_manifest=manifest,
                        preparation_manifest_sha256=manifest_sha256,
                        adjudication_task=adjudication_task,
                        adjudication_source_task=(
                            source["task"] if adjudication_task else None
                        ),
                        adjudication_mapping=(
                            source["mapping"] if adjudication_task else None
                        ),
                        adjudication=adjudication,
                        created_at=_now(args.created_at),
                        git_revision=revision,
                    )
        assert external_output is not None
        written_output = _write_new(external_output, payload)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        print(f"Pilot curator workflow FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "Pilot curator workflow PASSED: "
        f"command={args.command}, artifact={payload['artifact_id']}, "
        f"output={written_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
