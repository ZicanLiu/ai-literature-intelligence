"""Coordinator CLI for external, provider-neutral RCP-v0.3.1 execution."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from src.pilot_reference_curation import (
    build_ai_task_package,
    build_judgement_aggregation,
    build_model_judgement_batch,
    build_model_roster,
    build_reference_execution_manifest,
    build_response_envelopes_from_import_records,
    build_safe_zero_audit_outcome,
    build_safe_zero_audit_plan,
    export_ai_task_package,
    load_reference_curation_inputs,
    validate_external_output_path,
    validate_model_roster,
    validate_safe_zero_audit_outcome,
    validate_safe_zero_audit_plan,
)
from src.pilot_reference_review import (
    build_anonymized_h2_evidence_packet,
    build_cutoff_task_package,
    build_final_human_labels,
    build_human_task_package,
    compute_r3_triggers,
    derive_h1_candidate_ids,
    export_cutoff_task_package,
    export_human_task_package,
    import_cutoff_submission,
    import_human_submission,
)
from src.pilot_reference_selection import (
    build_cutoff_decision_from_submissions,
    build_final_reference,
    build_rcp_quality_report,
    build_reference_selection_artifact,
)
from src.pilot_selection import capture_git_state, write_json
from src.w6_contracts import load_json_object


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT
    / "configs"
    / "pilot"
    / "srtp_pilot_v0.3.1_reference_curation_v1.json"
)


def _add_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)


def _add_time_and_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output", type=Path, required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Offline/external RCP-v0.3.1 coordinator. This CLI never calls a model API."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    roster = subparsers.add_parser("validate-roster")
    _add_config(roster)
    roster.add_argument("--roster", type=Path, required=True)

    freeze_roster = subparsers.add_parser("freeze-roster")
    _add_config(freeze_roster)
    freeze_roster.add_argument("--roster-input", type=Path, required=True)
    freeze_roster.add_argument("--frozen-at", required=True)
    freeze_roster.add_argument("--output", type=Path, required=True)

    export = subparsers.add_parser("export-ai-tasks")
    _add_config(export)
    export.add_argument("--roster", type=Path, required=True)
    export.add_argument("--roster-entry-id", required=True)
    export.add_argument("--topic-id", required=True)
    export.add_argument("--created-at", required=True)
    export.add_argument("--model-output-dir", type=Path, required=True)
    export.add_argument("--coordinator-map-output", type=Path, required=True)

    batch = subparsers.add_parser("import-model-batch")
    _add_config(batch)
    batch.add_argument("--roster", type=Path, required=True)
    batch.add_argument("--task-package", type=Path, required=True)
    batch.add_argument("--mapping", type=Path, required=True)
    batch.add_argument("--responses", type=Path, required=True)
    batch.add_argument("--started-at", required=True)
    batch.add_argument("--completed-at", required=True)
    batch.add_argument("--output", type=Path, required=True)

    aggregate = subparsers.add_parser("aggregate")
    _add_config(aggregate)
    aggregate.add_argument("--roster", type=Path, required=True)
    aggregate.add_argument("--run-descriptor", type=Path, required=True)
    _add_time_and_output(aggregate)

    execution = subparsers.add_parser("build-execution-manifest")
    _add_config(execution)
    execution.add_argument("--roster", type=Path, required=True)
    execution.add_argument("--run-descriptor", type=Path, required=True)
    execution.add_argument("--frozen-at", required=True)
    execution.add_argument("--output", type=Path, required=True)

    audit = subparsers.add_parser("plan-audit")
    _add_config(audit)
    audit.add_argument("--aggregation", type=Path, required=True)
    _add_time_and_output(audit)

    audit_outcome = subparsers.add_parser("record-audit-outcome")
    _add_config(audit_outcome)
    audit_outcome.add_argument("--audit-plan", type=Path, required=True)
    audit_outcome.add_argument("--aggregation", type=Path, required=True)
    audit_outcome.add_argument("--human-labels", type=Path, required=True)
    audit_outcome.add_argument("--completed-at", required=True)
    audit_outcome.add_argument("--output", type=Path, required=True)

    human_export = subparsers.add_parser("export-human-task")
    _add_config(human_export)
    human_export.add_argument("--aggregation", type=Path, required=True)
    human_export.add_argument("--audit-plan", type=Path)
    human_export.add_argument("--audit-outcome", type=Path)
    human_export.add_argument("--audit-human-labels", type=Path)
    human_export.add_argument("--h2-packet", type=Path)
    human_export.add_argument("--prior-r3-h1", type=Path)
    human_export.add_argument("--candidate-roster", type=Path)
    human_export.add_argument(
        "--reviewer-slot", choices=("r1", "r2", "r3"), required=True
    )
    human_export.add_argument(
        "--stage", choices=("h1", "h2", "r3_h1", "r3_h2"), required=True
    )
    human_export.add_argument("--created-at", required=True)
    human_export.add_argument("--output-dir", type=Path, required=True)
    human_export.add_argument("--coordinator-map-output", type=Path, required=True)

    human_import = subparsers.add_parser("import-human")
    _add_config(human_import)
    human_import.add_argument("--task-package", type=Path, required=True)
    human_import.add_argument("--mapping", type=Path, required=True)
    human_import.add_argument("--response", type=Path, required=True)
    human_import.add_argument("--imported-at", required=True)
    human_import.add_argument("--output", type=Path, required=True)

    h2 = subparsers.add_parser("build-h2")
    _add_config(h2)
    h2.add_argument("--aggregation", type=Path, required=True)
    h2.add_argument("--r1-h1", type=Path, required=True)
    h2.add_argument("--r2-h1", type=Path, required=True)
    h2.add_argument("--cutoff-frontier", type=Path)
    _add_time_and_output(h2)

    r3 = subparsers.add_parser("build-r3-roster")
    _add_config(r3)
    r3.add_argument("--aggregation", type=Path, required=True)
    r3.add_argument("--r1-h1", type=Path, required=True)
    r3.add_argument("--r2-h1", type=Path, required=True)
    r3.add_argument("--r1-h2", type=Path)
    r3.add_argument("--r2-h2", type=Path)
    r3.add_argument("--cutoff-tie", type=Path)
    r3.add_argument("--output", type=Path, required=True)

    cutoff_export = subparsers.add_parser("export-cutoff-task")
    _add_config(cutoff_export)
    cutoff_export.add_argument("--aggregation", type=Path, required=True)
    cutoff_export.add_argument("--tie-group", type=Path, required=True)
    cutoff_export.add_argument("--slots-required", type=int, required=True)
    cutoff_export.add_argument(
        "--reviewer-slot", choices=("r1", "r2", "r3"), required=True
    )
    cutoff_export.add_argument("--created-at", required=True)
    cutoff_export.add_argument("--output-dir", type=Path, required=True)
    cutoff_export.add_argument("--coordinator-map-output", type=Path, required=True)

    cutoff_import = subparsers.add_parser("import-cutoff")
    _add_config(cutoff_import)
    cutoff_import.add_argument("--task-package", type=Path, required=True)
    cutoff_import.add_argument("--mapping", type=Path, required=True)
    cutoff_import.add_argument("--response", type=Path, required=True)
    cutoff_import.add_argument("--imported-at", required=True)
    cutoff_import.add_argument("--output", type=Path, required=True)

    cutoff = subparsers.add_parser("build-cutoff-decision")
    _add_config(cutoff)
    cutoff.add_argument("--r1-submission", type=Path, required=True)
    cutoff.add_argument("--r2-submission", type=Path, required=True)
    cutoff.add_argument("--r3-submission", type=Path)
    cutoff.add_argument(
        "--tie-break-seed",
        default="srtp-rcp-v0.3-cutoff-tie-v1",
    )
    cutoff.add_argument("--created-at", required=True)
    cutoff.add_argument("--output", type=Path, required=True)

    labels = subparsers.add_parser("finalize-human-labels")
    _add_config(labels)
    labels.add_argument("--aggregation", type=Path, required=True)
    labels.add_argument("--r1-h1", type=Path, required=True)
    labels.add_argument("--r2-h1", type=Path, required=True)
    labels.add_argument("--r1-h2", type=Path)
    labels.add_argument("--r2-h2", type=Path)
    labels.add_argument("--r3", type=Path)
    labels.add_argument("--r3-h2", type=Path)
    labels.add_argument("--required-candidates", type=Path, required=True)
    _add_time_and_output(labels)

    final = subparsers.add_parser("finalize-reference")
    _add_config(final)
    final.add_argument("--roster", type=Path, required=True)
    final.add_argument("--execution-manifest", type=Path, required=True)
    final.add_argument("--aggregation", type=Path, required=True)
    final.add_argument("--audit-plan", type=Path, required=True)
    final.add_argument("--audit-outcome", type=Path, required=True)
    final.add_argument("--human-labels", type=Path, required=True)
    final.add_argument("--cutoff-decision", type=Path)
    final.add_argument("--run-descriptor", type=Path, required=True)
    final.add_argument("--created-at", required=True)
    final.add_argument("--finalization-output", type=Path, required=True)
    final.add_argument("--selection-output", type=Path, required=True)

    quality = subparsers.add_parser("quality-report")
    _add_config(quality)
    quality.add_argument("--aggregation", type=Path, required=True)
    quality.add_argument("--human-submissions", type=Path)
    quality.add_argument("--audit-outcome", type=Path)
    quality.add_argument("--cutoff-decision", type=Path)
    quality.add_argument("--output", type=Path, required=True)
    return parser


def _load(path: Path, label: str) -> dict[str, Any]:
    return load_json_object(path, label=label)


def _load_optional(path: Path | None, label: str) -> dict[str, Any] | None:
    return _load(path, label) if path else None


def _load_run_bundles(path: Path) -> list[dict[str, Any]]:
    descriptor = _load(path, "RCP run descriptor")
    rows = descriptor.get("runs")
    if not isinstance(rows, list) or not rows:
        raise ValueError("run descriptor 必须包含非空 runs array。")
    bundles = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "batch",
            "task_package",
            "mapping",
        }:
            raise ValueError("run descriptor row fields drift。")
        bundles.append(
            {
                "batch": _load(Path(row["batch"]), "model batch"),
                "task_package": _load(Path(row["task_package"]), "AI task package"),
                "mapping": _load(Path(row["mapping"]), "private AI task map"),
            }
        )
    return bundles


def _external_output(path: Path, label: str) -> Path:
    output = validate_external_output_path(path, project_root=PROJECT_ROOT, label=label)
    if output.exists():
        raise ValueError(f"{label} 已存在；禁止覆盖。")
    return output


def _git_revision() -> str:
    return capture_git_state(PROJECT_ROOT)["git_revision"]


def _require_clean_formal_worktree() -> str:
    state = capture_git_state(PROJECT_ROOT)
    if not state["git_worktree_clean"]:
        raise ValueError("formal RCP-v0.3.1 execution requires a clean Git worktree。")
    return state["git_revision"]


def _candidate_ids_file(path: Path, label: str) -> list[str]:
    payload = _load(path, label)
    values = payload.get("candidate_ids")
    if not isinstance(values, list):
        raise ValueError(f"{label} 必须包含 candidate_ids array。")
    return values


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inputs = load_reference_curation_inputs(args.config, project_root=PROJECT_ROOT)
        if args.command != "validate-roster":
            _require_clean_formal_worktree()
        if args.command == "validate-roster":
            roster = _load(args.roster, "RCP model roster")
            result = validate_model_roster(roster, inputs=inputs)
            print(
                "RCP model roster PASSED: "
                f"entries={len(result['entries'])}, fixture={result['is_fixture']}"
            )
            return 0
        if args.command == "freeze-roster":
            roster_input = _load(args.roster_input, "RCP roster freeze input")
            expected_fields = {
                "entries",
                "created_by",
                "downstream_generator_family",
                "run_scope",
                "allow_snapshot_unavailable_exception",
            }
            if set(roster_input) != expected_fields:
                raise ValueError("roster freeze input fields drift。")
            entries = roster_input["entries"]
            if not isinstance(entries, list):
                raise ValueError("roster freeze input entries 必须是 array。")
            payload = build_model_roster(
                inputs=inputs,
                entries=entries,
                frozen_at=args.frozen_at,
                git_revision=_git_revision(),
                created_by=roster_input["created_by"],
                downstream_generator_family=roster_input["downstream_generator_family"],
                run_scope=roster_input["run_scope"],
                allow_snapshot_unavailable_exception=roster_input[
                    "allow_snapshot_unavailable_exception"
                ],
                is_fixture=False,
            )
            write_json(
                _external_output(args.output, "frozen model roster output"), payload
            )
            print(
                "RCP model roster freeze PASSED: "
                f"artifact={payload['artifact_id']}, entries={len(payload['entries'])}"
            )
            return 0
        if args.command == "export-ai-tasks":
            roster = _load(args.roster, "RCP model roster")
            package, mapping = build_ai_task_package(
                inputs=inputs,
                roster=roster,
                roster_entry_id=args.roster_entry_id,
                topic_id=args.topic_id,
                created_at=args.created_at,
                git_revision=_git_revision(),
            )
            result = export_ai_task_package(
                package=package,
                mapping=mapping,
                roster=roster,
                inputs=inputs,
                model_output_dir=args.model_output_dir,
                coordinator_map_output=args.coordinator_map_output,
            )
            print(
                "RCP AI task export PASSED: "
                f"task_package={result['task_package']}, map={result['coordinator_map']}"
            )
            return 0
        if args.command == "import-model-batch":
            roster = _load(args.roster, "RCP model roster")
            task_package = _load(args.task_package, "AI task package")
            mapping = _load(args.mapping, "AI task map")
            responses = _load(args.responses, "model response envelopes")
            envelopes = responses.get("envelopes")
            records = responses.get("records")
            if isinstance(records, list) and envelopes is None:
                envelopes = build_response_envelopes_from_import_records(
                    records,
                    task_package=task_package,
                )
            elif not isinstance(envelopes, list) or records is not None:
                raise ValueError(
                    "responses file 必须且只能包含 records 或 legacy envelopes array。"
                )
            payload = build_model_judgement_batch(
                inputs=inputs,
                roster=roster,
                task_package=task_package,
                mapping=mapping,
                envelopes=envelopes,
                started_at=args.started_at,
                completed_at=args.completed_at,
                git_revision=_git_revision(),
            )
            write_json(_external_output(args.output, "model batch output"), payload)
        elif args.command == "aggregate":
            roster = _load(args.roster, "RCP model roster")
            payload = build_judgement_aggregation(
                inputs=inputs,
                roster=roster,
                run_bundles=_load_run_bundles(args.run_descriptor),
                created_at=args.created_at,
                git_revision=_git_revision(),
            )
            write_json(_external_output(args.output, "aggregation output"), payload)
        elif args.command == "build-execution-manifest":
            payload = build_reference_execution_manifest(
                inputs=inputs,
                roster=_load(args.roster, "RCP model roster"),
                run_bundles=_load_run_bundles(args.run_descriptor),
                frozen_at=args.frozen_at,
                git_revision=_git_revision(),
            )
            write_json(
                _external_output(args.output, "execution manifest output"), payload
            )
        elif args.command == "plan-audit":
            aggregation = _load(args.aggregation, "RCP aggregation")
            payload = build_safe_zero_audit_plan(
                aggregation,
                inputs=inputs,
                created_at=args.created_at,
                git_revision=_git_revision(),
            )
            write_json(_external_output(args.output, "audit plan output"), payload)
        elif args.command == "record-audit-outcome":
            aggregation = _load(args.aggregation, "RCP aggregation")
            audit_plan = _load(args.audit_plan, "safe-zero audit plan")
            final_human_labels = _load(
                args.human_labels, "validated final Human labels"
            )
            validate_safe_zero_audit_plan(
                audit_plan,
                aggregation=aggregation,
                inputs=inputs,
            )
            payload = build_safe_zero_audit_outcome(
                audit_plan,
                inputs=inputs,
                aggregation=aggregation,
                final_human_labels=final_human_labels,
                completed_at=args.completed_at,
                git_revision=_git_revision(),
            )
            write_json(_external_output(args.output, "audit outcome output"), payload)
        elif args.command == "export-human-task":
            aggregation = _load(args.aggregation, "RCP aggregation")
            audit_plan = _load_optional(args.audit_plan, "safe-zero audit plan")
            audit_outcome = _load_optional(
                args.audit_outcome, "safe-zero audit outcome"
            )
            h2_packet = _load_optional(args.h2_packet, "H2 evidence packet")
            prior_r3_h1 = _load_optional(
                args.prior_r3_h1, "prior blind R3 H1 submission"
            )
            if args.stage == "h1":
                if audit_plan is None:
                    raise ValueError("H1 export requires --audit-plan。")
                validate_safe_zero_audit_plan(
                    audit_plan,
                    aggregation=aggregation,
                    inputs=inputs,
                )
                if audit_outcome is not None:
                    if args.audit_human_labels is None:
                        raise ValueError(
                            "H1 escalation export requires --audit-human-labels。"
                        )
                    audit_human_labels = _load(
                        args.audit_human_labels, "safe-zero audit Human labels"
                    )
                    validate_safe_zero_audit_outcome(
                        audit_outcome,
                        audit_plan=audit_plan,
                        inputs=inputs,
                        aggregation=aggregation,
                        final_human_labels=audit_human_labels,
                    )
                candidate_ids = derive_h1_candidate_ids(
                    aggregation, audit_plan, audit_outcome=audit_outcome
                )
            else:
                if args.candidate_roster is None:
                    raise ValueError("non-H1 export requires --candidate-roster。")
                candidate_ids = _candidate_ids_file(
                    args.candidate_roster, "human candidate roster"
                )
            package, mapping = build_human_task_package(
                inputs=inputs,
                aggregation=aggregation,
                reviewer_slot=args.reviewer_slot,
                stage=args.stage,
                candidate_ids=candidate_ids,
                created_at=args.created_at,
                git_revision=_git_revision(),
                h2_evidence_packet=h2_packet,
                prior_r3_h1_submission=prior_r3_h1,
            )
            export_result = export_human_task_package(
                package=package,
                mapping=mapping,
                inputs=inputs,
                aggregation=aggregation,
                candidate_ids=candidate_ids,
                human_output_dir=args.output_dir,
                coordinator_map_output=args.coordinator_map_output,
                h2_evidence_packet=h2_packet,
                prior_r3_h1_submission=prior_r3_h1,
            )
            print(
                "RCP human task export PASSED: "
                f"cases={package['candidate_count']}, "
                f"output={export_result['human_output_dir']}"
            )
            return 0
        elif args.command == "import-human":
            payload = import_human_submission(
                _load(args.response, "human response"),
                task_package=_load(args.task_package, "human task package"),
                mapping=_load(args.mapping, "human task map"),
                imported_at=args.imported_at,
                git_revision=_git_revision(),
            )
            write_json(
                _external_output(args.output, "human submission output"), payload
            )
        elif args.command == "build-h2":
            aggregation = _load(args.aggregation, "RCP aggregation")
            frontier = (
                _candidate_ids_file(args.cutoff_frontier, "cutoff frontier")
                if args.cutoff_frontier
                else []
            )
            r1_h1 = _load(args.r1_h1, "R1 H1 submission")
            r2_h1 = _load(args.r2_h1, "R2 H1 submission")
            payload = build_anonymized_h2_evidence_packet(
                aggregation,
                r1_h1=r1_h1,
                r2_h1=r2_h1,
                cutoff_frontier_ids=frontier,
                created_at=args.created_at,
                git_revision=_git_revision(),
            )
            write_json(_external_output(args.output, "H2 packet output"), payload)
        elif args.command == "build-r3-roster":
            tie_ids = (
                _candidate_ids_file(args.cutoff_tie, "cutoff tie roster")
                if args.cutoff_tie
                else []
            )
            triggers = compute_r3_triggers(
                _load(args.aggregation, "RCP aggregation"),
                _load(args.r1_h1, "R1 H1 submission"),
                _load(args.r2_h1, "R2 H1 submission"),
                r1_h2=_load_optional(args.r1_h2, "R1 H2 submission"),
                r2_h2=_load_optional(args.r2_h2, "R2 H2 submission"),
                cutoff_tie_ids=tie_ids,
            )
            payload = {
                "protocol_id": inputs.config["protocol_id"],
                "candidate_ids": sorted(triggers),
                "trigger_reasons": triggers,
            }
            write_json(_external_output(args.output, "R3 roster output"), payload)
        elif args.command == "export-cutoff-task":
            aggregation = _load(args.aggregation, "RCP aggregation")
            tie_group = _candidate_ids_file(args.tie_group, "cutoff tie group")
            package, mapping = build_cutoff_task_package(
                inputs=inputs,
                aggregation=aggregation,
                reviewer_slot=args.reviewer_slot,
                tie_group_candidate_ids=tie_group,
                slots_required=args.slots_required,
                created_at=args.created_at,
                git_revision=_git_revision(),
            )
            result = export_cutoff_task_package(
                package=package,
                mapping=mapping,
                inputs=inputs,
                aggregation=aggregation,
                tie_group_candidate_ids=tie_group,
                slots_required=args.slots_required,
                human_output_dir=args.output_dir,
                coordinator_map_output=args.coordinator_map_output,
            )
            print(
                "RCP cutoff task export PASSED: "
                f"reviewer={args.reviewer_slot}, output={result['human_output_dir']}"
            )
            return 0
        elif args.command == "import-cutoff":
            payload = import_cutoff_submission(
                _load(args.response, "cutoff response"),
                task_package=_load(args.task_package, "cutoff task package"),
                mapping=_load(args.mapping, "cutoff private map"),
                imported_at=args.imported_at,
                git_revision=_git_revision(),
            )
            write_json(
                _external_output(args.output, "cutoff submission output"), payload
            )
        elif args.command == "build-cutoff-decision":
            payload = build_cutoff_decision_from_submissions(
                r1_submission=_load(args.r1_submission, "R1 cutoff submission"),
                r2_submission=_load(args.r2_submission, "R2 cutoff submission"),
                r3_submission=_load_optional(
                    args.r3_submission, "R3 cutoff submission"
                ),
                tie_break_seed=args.tie_break_seed,
                created_at=args.created_at,
                git_revision=_git_revision(),
            )
            write_json(_external_output(args.output, "cutoff decision output"), payload)
        elif args.command == "finalize-human-labels":
            payload = build_final_human_labels(
                _load(args.aggregation, "RCP aggregation"),
                r1_h1=_load(args.r1_h1, "R1 H1 submission"),
                r2_h1=_load(args.r2_h1, "R2 H1 submission"),
                r1_h2=_load_optional(args.r1_h2, "R1 H2 submission"),
                r2_h2=_load_optional(args.r2_h2, "R2 H2 submission"),
                r3=_load_optional(args.r3, "R3 submission"),
                r3_h2=_load_optional(args.r3_h2, "R3 H2 submission"),
                required_candidate_ids=_candidate_ids_file(
                    args.required_candidates, "required human candidates"
                ),
                created_at=args.created_at,
                git_revision=_git_revision(),
            )
            write_json(
                _external_output(args.output, "final human labels output"), payload
            )
        elif args.command == "finalize-reference":
            aggregation = _load(args.aggregation, "RCP aggregation")
            audit_plan = _load(args.audit_plan, "safe-zero audit plan")
            audit_outcome = _load(args.audit_outcome, "safe-zero audit outcome")
            final_human_labels = _load(args.human_labels, "final human labels")
            cutoff_decision = _load_optional(args.cutoff_decision, "cutoff decision")
            finalization = build_final_reference(
                inputs=inputs,
                roster=_load(args.roster, "RCP model roster"),
                execution_manifest=_load(
                    args.execution_manifest, "RCP execution manifest"
                ),
                aggregation=aggregation,
                audit_plan=audit_plan,
                audit_outcome=audit_outcome,
                final_human_labels=final_human_labels,
                cutoff_decision=cutoff_decision,
                created_at=args.created_at,
                git_revision=_git_revision(),
                run_bundles=_load_run_bundles(args.run_descriptor),
            )
            selection = build_reference_selection_artifact(
                inputs=inputs,
                final_reference=finalization,
                aggregation=aggregation,
                audit_plan=audit_plan,
                audit_outcome=audit_outcome,
                final_human_labels=final_human_labels,
                cutoff_decision=cutoff_decision,
                created_at=args.created_at,
                git_revision=_git_revision(),
            )
            write_json(
                _external_output(
                    args.finalization_output, "Reference finalization output"
                ),
                finalization,
            )
            write_json(
                _external_output(args.selection_output, "Reference Selection output"),
                selection,
            )
            print(
                "RCP Reference finalization PASSED: "
                f"topic={selection['topic']['topic_id']}, k={selection['k']}"
            )
            return 0
        elif args.command == "quality-report":
            submissions = []
            if args.human_submissions:
                descriptor = _load(
                    args.human_submissions, "human submission descriptor"
                )
                submissions = [
                    _load(Path(path), "human submission")
                    for path in descriptor.get("submissions", [])
                ]
            payload = build_rcp_quality_report(
                aggregation=_load(args.aggregation, "RCP aggregation"),
                human_submissions=submissions,
                audit_outcome=_load_optional(args.audit_outcome, "audit outcome"),
                cutoff_decision=_load_optional(args.cutoff_decision, "cutoff decision"),
            )
            write_json(_external_output(args.output, "quality report output"), payload)
        else:
            raise ValueError("unknown RCP coordinator command。")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Pilot RCP coordinator FAILED: {error}", file=sys.stderr)
        return 1
    print(f"Pilot {inputs.config['protocol_version']} {args.command} PASSED。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
