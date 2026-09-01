"""RCP-v0.3 final Reference selection and BM25 freeze integration."""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.annotation_tasks import sha256_file
from src.pilot_reference_curation import (
    CUTOFF_IDENTITY_PREFIX,
    FINAL_REFERENCE_IDENTITY_PREFIX,
    QUALITY_REPORT_IDENTITY_PREFIX,
    RCP_PROTOCOL_ID,
    RCP_SCHEMA_VERSION,
    REFERENCE_METHOD_ID,
    ReferenceCurationInputs,
    _artifact_id,
    _artifact_reference,
    _bool,
    _datetime,
    _exact,
    _git_revision,
    _identity_without,
    _integer,
    _list,
    _mapping,
    _strings,
    _text,
    load_reference_curation_inputs,
    validate_model_roster,
    validate_judgement_aggregation,
    validate_reference_execution_manifest,
    validate_safe_zero_audit_plan,
    validate_safe_zero_audit_outcome,
)
from src.pilot_selection import (
    BM25_METHOD_ID,
    SELECTION_K,
    PilotSelectionInputs,
    build_selection_artifact,
    payload_sha256,
    rank_pilot_bm25_candidates,
    topic_config,
    validate_selection_artifact,
)
from src.w6_contracts import deterministic_identity
from src.pilot_reference_review import (
    validate_cutoff_submission_identity,
    validate_final_human_labels_identity,
)


DEFAULT_RCP_CONFIG = Path("configs/pilot/srtp_pilot_v0.3_reference_curation_v1.json")


def build_cutoff_decision(
    *,
    tie_group_canonical_entity_ids: Sequence[str],
    slots_required: int,
    r1_selected_ids: Sequence[str],
    r2_selected_ids: Sequence[str],
    r3_priority_groups: Sequence[Sequence[str]],
    tie_break_seed: str,
    created_at: str,
    git_revision: str,
    is_fixture: bool,
    source_submissions: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    tie_group = _strings(list(tie_group_canonical_entity_ids), "cutoff tie group")
    slots = _integer(slots_required, "cutoff slots required", minimum=1)
    if slots >= len(tie_group):
        raise ValueError("cutoff tie decision 只适用于 slots < tie-group size。")
    r1 = _strings(list(r1_selected_ids), "R1 cutoff choices", count=slots)
    r2 = _strings(list(r2_selected_ids), "R2 cutoff choices", count=slots)
    tie_set = set(tie_group)
    if not set(r1).issubset(tie_set) or not set(r2).issubset(tie_set):
        raise ValueError("R1/R2 cutoff choices 必须来自完整 tie group。")
    intersection = sorted(set(r1) & set(r2))
    selected = list(intersection)
    remaining_slots = slots - len(selected)
    r3_required = remaining_slots > 0
    groups: list[list[str]] = []
    flattened: list[str] = []
    for raw_group in r3_priority_groups:
        group = _strings(list(raw_group), "R3 priority group")
        if not group:
            raise ValueError("R3 priority group 不得为空。")
        groups.append(group)
        flattened.extend(group)
    if remaining_slots and set(flattened) != tie_set:
        raise ValueError("需要 R3 时必须对完整 tie group 独立 priority。")
    if len(flattened) != len(set(flattened)):
        raise ValueError("R3 priority groups 不得重复 candidates。")
    hash_last_resort: list[str] = []
    for group in groups:
        available = [
            candidate_id for candidate_id in group if candidate_id not in selected
        ]
        if not remaining_slots:
            break
        if len(available) <= remaining_slots:
            selected.extend(available)
            remaining_slots -= len(available)
            continue
        ordered = sorted(
            available,
            key=lambda candidate_id: (
                hashlib.sha256(
                    f"{tie_break_seed}|{candidate_id}".encode("utf-8")
                ).hexdigest(),
                candidate_id,
            ),
        )
        chosen = ordered[:remaining_slots]
        selected.extend(chosen)
        hash_last_resort.extend(chosen)
        remaining_slots = 0
    if remaining_slots:
        raise ValueError("cutoff tie decision 未能补足 required slots。")
    submission_snapshots = [copy.deepcopy(dict(row)) for row in source_submissions]
    if not is_fixture and not submission_snapshots:
        raise ValueError("formal cutoff decision 必须绑定 blind human submissions。")
    submission_refs = []
    if submission_snapshots:
        roles = []
        reviewer_ids = []
        by_role: dict[str, Mapping[str, Any]] = {}
        for submission in submission_snapshots:
            validated = validate_cutoff_submission_identity(submission)
            role = validated["reviewer_slot"]
            if role in by_role:
                raise ValueError("cutoff blind submission reviewer roster duplicate。")
            if (
                validated["tie_group_canonical_entity_ids"] != tuple(tie_group)
                or validated["slots_required"] != slots
                or validated["is_fixture"] is not is_fixture
            ):
                raise ValueError(
                    "cutoff blind submission tie/slot/fixture binding drift。"
                )
            by_role[role] = submission
            roles.append(role)
            reviewer_ids.append(
                _text(submission.get("reviewer_id"), "cutoff reviewer_id")
            )
            submission_refs.append(
                {
                    "artifact_id": validated["artifact_id"],
                    "submission_identity": validated["submission_identity"],
                    "sha256": validated["sha256"],
                    "reviewer_slot": role,
                    "stage": submission["stage"],
                }
            )
        expected_roles = {"r1", "r2", "r3"} if r3_required else {"r1", "r2"}
        if set(roles) != expected_roles or len(roles) != len(expected_roles):
            raise ValueError("cutoff blind submission reference roster drift。")
        if len(set(reviewer_ids)) != len(reviewer_ids):
            raise ValueError("同一 Topic 的 cutoff R1/R2/R3 reviewer_id 必须互异。")
        if list(by_role["r1"].get("selected_canonical_entity_ids") or []) != r1:
            raise ValueError("cutoff R1 canonical selection/raw response drift。")
        if list(by_role["r2"].get("selected_canonical_entity_ids") or []) != r2:
            raise ValueError("cutoff R2 canonical selection/raw response drift。")
        if (
            r3_required
            and list(by_role["r3"].get("canonical_priority_groups") or []) != groups
        ):
            raise ValueError("cutoff R3 canonical priority/raw response drift。")
    payload: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_cutoff_decision",
        "artifact_id": "pending",
        "cutoff_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "tie_group_canonical_entity_ids": tie_group,
        "slots_required": slots,
        "blind_r1_selected_ids": r1,
        "blind_r2_selected_ids": r2,
        "intersection_priority_ids": intersection,
        "r3_priority_groups": groups,
        "hash_tie_break": {
            "seed": _text(tie_break_seed, "cutoff tie-break seed"),
            "algorithm": "sha256_seed_canonical_entity_id_v1",
            "used_for_ids": hash_last_resort,
            "interpretation": "mechanical_last_resort_not_scientific_superiority",
        },
        "selected_from_tie": selected,
        "blind_submission_refs": submission_refs,
        "blind_submission_snapshots": submission_snapshots,
        "created_at": _datetime(created_at, "cutoff decision created_at"),
        "is_fixture": is_fixture,
        "provenance": {
            "created_by": "src.pilot_reference_selection",
            "git_revision": _git_revision(git_revision, "cutoff git_revision"),
        },
    }
    identity = _identity_without(
        payload,
        prefix=CUTOFF_IDENTITY_PREFIX,
        omitted={"artifact_id", "cutoff_identity"},
    )
    payload["cutoff_identity"] = identity
    payload["artifact_id"] = _artifact_id("srtp_rcp_cutoff", identity)
    return payload


def validate_cutoff_decision(
    cutoff_decision: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = _mapping(dict(cutoff_decision), "cutoff decision")
    provenance = _mapping(artifact.get("provenance"), "cutoff provenance")
    reconstructed = build_cutoff_decision(
        tie_group_canonical_entity_ids=artifact.get("tie_group_canonical_entity_ids"),
        slots_required=artifact.get("slots_required"),
        r1_selected_ids=artifact.get("blind_r1_selected_ids"),
        r2_selected_ids=artifact.get("blind_r2_selected_ids"),
        r3_priority_groups=artifact.get("r3_priority_groups"),
        tie_break_seed=_mapping(
            artifact.get("hash_tie_break"), "cutoff hash tie-break"
        ).get("seed"),
        created_at=artifact.get("created_at"),
        git_revision=provenance.get("git_revision"),
        is_fixture=_bool(artifact.get("is_fixture"), "cutoff is_fixture"),
        source_submissions=artifact.get("blind_submission_snapshots", []),
    )
    if artifact != reconstructed:
        raise ValueError("cutoff decision deterministic reconstruction drift。")
    return {
        "artifact_id": artifact["artifact_id"],
        "cutoff_identity": artifact["cutoff_identity"],
        "sha256": payload_sha256(artifact),
        "selected_from_tie": tuple(artifact["selected_from_tie"]),
        "is_fixture": artifact["is_fixture"],
    }


def build_cutoff_decision_from_submissions(
    *,
    r1_submission: Mapping[str, Any],
    r2_submission: Mapping[str, Any],
    r3_submission: Mapping[str, Any] | None,
    tie_break_seed: str,
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    r1 = validate_cutoff_submission_identity(r1_submission)
    r2 = validate_cutoff_submission_identity(r2_submission)
    if r1["reviewer_slot"] != "r1" or r2["reviewer_slot"] != "r2":
        raise ValueError("cutoff decision requires blind R1 and R2 submissions。")
    for key in (
        "topic_id",
        "tie_group_canonical_entity_ids",
        "slots_required",
        "is_fixture",
    ):
        if r1[key] != r2[key]:
            raise ValueError(f"cutoff R1/R2 {key} binding drift。")
    r1_selected = _strings(
        r1_submission.get("selected_canonical_entity_ids"),
        "R1 cutoff selected IDs",
    )
    r2_selected = _strings(
        r2_submission.get("selected_canonical_entity_ids"),
        "R2 cutoff selected IDs",
    )
    remaining = r1["slots_required"] - len(set(r1_selected) & set(r2_selected))
    r3_groups: Sequence[Sequence[str]] = ()
    source_artifacts = [r1_submission, r2_submission]
    if remaining:
        if r3_submission is None:
            raise ValueError(
                "cutoff R1/R2 intersection 未补足时必须有 blind R3 priority。"
            )
        r3 = validate_cutoff_submission_identity(r3_submission)
        if r3["reviewer_slot"] != "r3":
            raise ValueError("cutoff third submission must be R3。")
        for key in (
            "topic_id",
            "tie_group_canonical_entity_ids",
            "slots_required",
            "is_fixture",
        ):
            if r3[key] != r1[key]:
                raise ValueError(f"cutoff R3 {key} binding drift。")
        r3_groups = _list(
            r3_submission.get("canonical_priority_groups"),
            "R3 canonical priority groups",
            nonempty=True,
        )
        source_artifacts.append(r3_submission)
    elif r3_submission is not None:
        raise ValueError("R1/R2 intersection 已补足时不得注入 R3 cutoff decision。")
    return build_cutoff_decision(
        tie_group_canonical_entity_ids=list(r1["tie_group_canonical_entity_ids"]),
        slots_required=r1["slots_required"],
        r1_selected_ids=r1_selected,
        r2_selected_ids=r2_selected,
        r3_priority_groups=r3_groups,
        tie_break_seed=tie_break_seed,
        created_at=created_at,
        git_revision=git_revision,
        is_fixture=r1["is_fixture"],
        source_submissions=source_artifacts,
    )


def _final_reference_identity_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dict(payload))
    body.pop("artifact_id", None)
    body.pop("final_reference_identity", None)
    return body


def _validate_reference_human_closure(
    *,
    inputs: ReferenceCurationInputs,
    aggregation: Mapping[str, Any],
    audit_plan: Mapping[str, Any],
    audit_outcome: Mapping[str, Any],
    final_human_labels: Mapping[str, Any],
) -> None:
    validate_safe_zero_audit_plan(
        audit_plan,
        aggregation=aggregation,
        inputs=inputs,
    )
    validate_final_human_labels_identity(
        final_human_labels,
        aggregation=aggregation,
    )
    validate_safe_zero_audit_outcome(
        audit_outcome,
        audit_plan=audit_plan,
        inputs=inputs,
        aggregation=aggregation,
        final_human_labels=final_human_labels,
    )
    if audit_outcome.get("audit_plan") != _artifact_reference(
        audit_plan
    ) or audit_outcome.get("human_audit_labels") != _artifact_reference(
        final_human_labels
    ):
        raise ValueError("final Reference audit outcome parent binding drift。")
    required_review = {
        row["canonical_entity_id"]
        for row in aggregation["judgement_matrix"]
        if row["human_route"]
    }
    required_review.update(audit_plan["audit_sample_canonical_entity_ids"])
    if audit_outcome.get("escalation_required") is True:
        required_review.update(audit_outcome["escalated_review_canonical_entity_ids"])
    label_ids = {
        row["canonical_entity_id"]
        for row in _list(final_human_labels.get("labels"), "final human labels")
    }
    if label_ids != required_review:
        raise ValueError("final Reference selective human review coverage drift。")


def _derive_reference_ranking(
    *,
    aggregation: Mapping[str, Any],
    final_human_labels: Mapping[str, Any],
    cutoff_decision: Mapping[str, Any] | None,
) -> dict[str, Any]:
    matrix = {
        row["canonical_entity_id"]: row for row in aggregation["judgement_matrix"]
    }
    labels = {
        row["canonical_entity_id"]: row
        for row in _list(final_human_labels.get("labels"), "final human labels")
    }
    eligible = []
    for candidate_id, human in labels.items():
        relevance = human["final_human_relevance"]
        if relevance in {1, 2}:
            eligible.append(
                {
                    "canonical_entity_id": candidate_id,
                    "final_human_relevance": relevance,
                    "n_core_label_2": matrix[candidate_id]["n_core_label_2"],
                    "n_core_label_ge_1": matrix[candidate_id]["n_core_label_ge_1"],
                }
            )
    if len(eligible) < SELECTION_K:
        raise ValueError(
            "insufficient_eligible_candidates：不得用 relevance=0 填满 Top-8。"
        )
    eligible.sort(
        key=lambda row: (
            -row["final_human_relevance"],
            -row["n_core_label_2"],
            -row["n_core_label_ge_1"],
            row["canonical_entity_id"],
        )
    )

    def score_key(row: Mapping[str, Any]) -> tuple[int, int, int]:
        return (
            row["final_human_relevance"],
            row["n_core_label_2"],
            row["n_core_label_ge_1"],
        )

    cutoff_key = score_key(eligible[SELECTION_K - 1])
    tie_group = [row for row in eligible if score_key(row) == cutoff_key]
    before_tie = [row for row in eligible if score_key(row) > cutoff_key]
    slots_from_tie = SELECTION_K - len(before_tie)
    if len(tie_group) > slots_from_tie:
        if cutoff_decision is None:
            raise ValueError("exact cutoff tie 缺少 blind R1/R2/R3 decision。")
        validate_cutoff_decision(cutoff_decision)
        if (
            cutoff_decision.get("tie_group_canonical_entity_ids")
            != [row["canonical_entity_id"] for row in tie_group]
            or cutoff_decision.get("slots_required") != slots_from_tie
            or cutoff_decision.get("is_fixture") != aggregation["is_fixture"]
        ):
            raise ValueError("cutoff decision/tie group binding drift。")
        selected_ids = [row["canonical_entity_id"] for row in before_tie] + list(
            cutoff_decision["selected_from_tie"]
        )
    else:
        if cutoff_decision is not None:
            raise ValueError("不存在跨 cutoff tie 时不得注入 cutoff decision。")
        selected_ids = [row["canonical_entity_id"] for row in eligible[:SELECTION_K]]
    if len(selected_ids) != SELECTION_K or len(set(selected_ids)) != SELECTION_K:
        raise ValueError("final Reference Top-8 duplicate/count drift。")
    if not set(selected_ids).issubset(labels):
        raise ValueError(
            "no AI-only Top-8 inclusion：所有入选项必须有人类 review/support。"
        )
    ranked_eligible = [
        {"rank": rank, **row} for rank, row in enumerate(eligible, start=1)
    ]
    return {
        "eligible_count": len(eligible),
        "ranked_eligible": ranked_eligible,
        "selected_canonical_entity_ids": selected_ids,
        "frontier_8_9_10": [
            row for row in ranked_eligible if row["rank"] in {8, 9, 10}
        ],
    }


def build_final_reference(
    *,
    inputs: ReferenceCurationInputs,
    roster: Mapping[str, Any],
    execution_manifest: Mapping[str, Any],
    aggregation: Mapping[str, Any],
    audit_plan: Mapping[str, Any],
    audit_outcome: Mapping[str, Any],
    final_human_labels: Mapping[str, Any],
    cutoff_decision: Mapping[str, Any] | None,
    created_at: str,
    git_revision: str,
    run_bundles: Sequence[Mapping[str, Any]] | None = None,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    roster_validation = validate_model_roster(
        roster, inputs=inputs, allow_fixture=allow_fixture
    )
    execution_validation = validate_reference_execution_manifest(
        execution_manifest,
        inputs=inputs,
        roster=roster,
        run_bundles=run_bundles,
        allow_fixture=allow_fixture,
    )
    if run_bundles is None and not allow_fixture:
        raise ValueError(
            "formal Reference finalization requires the exact 10-batch run closure。"
        )
    if run_bundles is not None:
        topic_id_for_aggregation = aggregation.get("topic", {}).get("topic_id")
        topic_bundles = [
            bundle
            for bundle in run_bundles
            if bundle.get("batch", {}).get("topic", {}).get("topic_id")
            == topic_id_for_aggregation
        ]
        validate_judgement_aggregation(
            aggregation,
            inputs=inputs,
            roster=roster,
            run_bundles=topic_bundles,
            allow_fixture=allow_fixture,
        )
    if aggregation.get("model_roster") != {
        "artifact_id": roster_validation["artifact_id"],
        "roster_identity": roster_validation["roster_identity"],
        "sha256": roster_validation["sha256"],
    }:
        raise ValueError("final Reference aggregation/roster binding drift。")
    if aggregation.get("is_fixture") != roster_validation["is_fixture"]:
        raise ValueError("final Reference fixture status drift。")
    _validate_reference_human_closure(
        inputs=inputs,
        aggregation=aggregation,
        audit_plan=audit_plan,
        audit_outcome=audit_outcome,
        final_human_labels=final_human_labels,
    )
    topic_id = aggregation["topic"]["topic_id"]
    if final_human_labels.get("topic", {}).get("topic_id") != topic_id:
        raise ValueError("final Reference human labels wrong Topic。")
    ranking = _derive_reference_ranking(
        aggregation=aggregation,
        final_human_labels=final_human_labels,
        cutoff_decision=cutoff_decision,
    )
    created = _datetime(created_at, "final Reference created_at")
    payload: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_final_reference",
        "artifact_id": "pending",
        "final_reference_identity": "pending",
        "protocol": {
            "protocol_id": RCP_PROTOCOL_ID,
            "config_identity": inputs.config["config_identity"],
            "config_sha256": sha256_file(inputs.config_path),
        },
        "pilot_version": inputs.pilot_inputs.config["pilot_version"],
        "selection_method_id": REFERENCE_METHOD_ID,
        "topic": copy.deepcopy(aggregation["topic"]),
        "u80": copy.deepcopy(aggregation["u80"]),
        "model_roster": {
            "artifact_id": roster_validation["artifact_id"],
            "roster_identity": roster_validation["roster_identity"],
            "sha256": roster_validation["sha256"],
        },
        "execution_manifest": {
            "artifact_id": execution_validation["artifact_id"],
            "execution_identity": execution_validation["execution_identity"],
            "sha256": execution_validation["sha256"],
            "model_batch_count": execution_validation["batch_count"],
        },
        "model_judgement_batch_refs": copy.deepcopy(
            execution_manifest["model_batches"]
        ),
        "aggregation": _artifact_reference(aggregation),
        "safe_zero_audit_plan": _artifact_reference(audit_plan),
        "safe_zero_audit_outcome": _artifact_reference(audit_outcome),
        "human_labels": _artifact_reference(final_human_labels),
        "cutoff_decision": (
            _artifact_reference(cutoff_decision)
            if cutoff_decision is not None
            else None
        ),
        "eligible_count": ranking["eligible_count"],
        "ranked_eligible": ranking["ranked_eligible"],
        "selected_canonical_entity_ids": ranking["selected_canonical_entity_ids"],
        "k": SELECTION_K,
        "all_top8_human_reviewed": True,
        "sentinel_used_for_ranking": False,
        "frontier_8_9_10": ranking["frontier_8_9_10"],
        "one_swap_sensitivity_status": "deferred_not_primary_rcp_v0.3",
        "one_swap_sensitivity_sets": [],
        "status": "fixture_complete"
        if aggregation["is_fixture"]
        else "reference_frozen",
        "claim_boundary": "auditable_internal_reference_selection_not_expert_gold",
        "created_at": created,
        "is_fixture": aggregation["is_fixture"],
        "provenance": {
            "created_by": "src.pilot_reference_selection",
            "git_revision": _git_revision(git_revision, "final Reference git_revision"),
        },
    }
    identity = deterministic_identity(
        FINAL_REFERENCE_IDENTITY_PREFIX, _final_reference_identity_payload(payload)
    )
    payload["final_reference_identity"] = identity
    payload["artifact_id"] = _artifact_id("srtp_rcp_final_reference", identity)
    validate_final_reference(
        payload,
        inputs=inputs,
        aggregation=aggregation,
        audit_plan=audit_plan,
        audit_outcome=audit_outcome,
        final_human_labels=final_human_labels,
        cutoff_decision=cutoff_decision,
    )
    return payload


def validate_final_reference(
    final_reference: Mapping[str, Any],
    *,
    inputs: ReferenceCurationInputs,
    aggregation: Mapping[str, Any],
    audit_plan: Mapping[str, Any],
    audit_outcome: Mapping[str, Any],
    final_human_labels: Mapping[str, Any],
    cutoff_decision: Mapping[str, Any] | None,
) -> dict[str, Any]:
    artifact = _mapping(dict(final_reference), "final Reference")
    if (
        artifact.get("protocol", {}).get("protocol_id") != RCP_PROTOCOL_ID
        or artifact.get("protocol", {}).get("config_identity")
        != inputs.config["config_identity"]
        or artifact.get("selection_method_id") != REFERENCE_METHOD_ID
        or artifact.get("k") != SELECTION_K
        or artifact.get("all_top8_human_reviewed") is not True
        or artifact.get("sentinel_used_for_ranking") is not False
        or artifact.get("topic") != aggregation.get("topic")
        or artifact.get("u80") != aggregation.get("u80")
        or artifact.get("aggregation") != _artifact_reference(aggregation)
        or artifact.get("safe_zero_audit_plan") != _artifact_reference(audit_plan)
        or artifact.get("safe_zero_audit_outcome") != _artifact_reference(audit_outcome)
        or artifact.get("human_labels") != _artifact_reference(final_human_labels)
        or artifact.get("cutoff_decision")
        != (
            _artifact_reference(cutoff_decision)
            if cutoff_decision is not None
            else None
        )
    ):
        raise ValueError("final Reference protocol/parent/K/human semantics drift。")
    _validate_reference_human_closure(
        inputs=inputs,
        aggregation=aggregation,
        audit_plan=audit_plan,
        audit_outcome=audit_outcome,
        final_human_labels=final_human_labels,
    )
    ranking = _derive_reference_ranking(
        aggregation=aggregation,
        final_human_labels=final_human_labels,
        cutoff_decision=cutoff_decision,
    )
    selected = _strings(
        artifact.get("selected_canonical_entity_ids"),
        "final Reference selected IDs",
        count=SELECTION_K,
    )
    for field in (
        "eligible_count",
        "ranked_eligible",
        "selected_canonical_entity_ids",
        "frontier_8_9_10",
    ):
        if artifact.get(field) != ranking[field]:
            raise ValueError(
                f"final Reference stored {field} 与 protocol reconstruction 不一致。"
            )
    if (
        artifact.get("one_swap_sensitivity_status") != "deferred_not_primary_rcp_v0.3"
        or artifact.get("one_swap_sensitivity_sets") != []
    ):
        raise ValueError("RCP-v0.3 Primary one-swap 必须保持 deferred。")
    topic_id = artifact.get("topic", {}).get("topic_id")
    if not set(selected).issubset(set(inputs.pilot_inputs.u80_by_topic[topic_id])):
        raise ValueError("final Reference selected IDs 超出 frozen U80。")
    if artifact.get("execution_manifest", {}).get("model_batch_count") != 10:
        raise ValueError("final Reference 必须绑定 exact 10 model judgement batches。")
    if len(artifact.get("model_judgement_batch_refs", [])) != 10:
        raise ValueError("final Reference model batch refs count drift。")
    expected_status = (
        "fixture_complete" if aggregation.get("is_fixture") else "reference_frozen"
    )
    if (
        artifact.get("is_fixture") != aggregation.get("is_fixture")
        or artifact.get("status") != expected_status
    ):
        raise ValueError("final Reference fixture/status drift。")
    identity = deterministic_identity(
        FINAL_REFERENCE_IDENTITY_PREFIX, _final_reference_identity_payload(artifact)
    )
    if artifact.get("final_reference_identity") != identity or artifact.get(
        "artifact_id"
    ) != _artifact_id("srtp_rcp_final_reference", identity):
        raise ValueError("final Reference identity/hash drift。")
    return {
        "artifact_id": artifact["artifact_id"],
        "final_reference_identity": identity,
        "sha256": payload_sha256(artifact),
        "topic_id": topic_id,
        "selected_canonical_entity_ids": tuple(selected),
        "is_fixture": artifact["is_fixture"],
    }


def _reference_method_provenance(
    final_reference: Mapping[str, Any],
    *,
    aggregation: Mapping[str, Any] | None = None,
    audit_plan: Mapping[str, Any] | None = None,
    audit_outcome: Mapping[str, Any] | None = None,
    final_human_labels: Mapping[str, Any] | None = None,
    cutoff_decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    provenance = {
        "protocol_id": RCP_PROTOCOL_ID,
        "protocol_config_identity": final_reference["protocol"]["config_identity"],
        "protocol_config_sha256": final_reference["protocol"]["config_sha256"],
        "reference_finalization": {
            "artifact_id": final_reference["artifact_id"],
            "final_reference_identity": final_reference["final_reference_identity"],
            "sha256": payload_sha256(final_reference),
        },
        "model_roster": copy.deepcopy(final_reference["model_roster"]),
        "execution_manifest": copy.deepcopy(final_reference["execution_manifest"]),
        "model_judgement_batch_refs": copy.deepcopy(
            final_reference["model_judgement_batch_refs"]
        ),
        "aggregation": copy.deepcopy(final_reference["aggregation"]),
        "safe_zero_audit_plan": copy.deepcopy(final_reference["safe_zero_audit_plan"]),
        "safe_zero_audit_outcome": copy.deepcopy(
            final_reference["safe_zero_audit_outcome"]
        ),
        "human_labels": copy.deepcopy(final_reference["human_labels"]),
        "cutoff_decision": copy.deepcopy(final_reference["cutoff_decision"]),
        "selected_canonical_entity_ids": copy.deepcopy(
            final_reference["selected_canonical_entity_ids"]
        ),
        "all_top8_human_reviewed": True,
        "sentinel_used_for_ranking": False,
        "external_lookup": False,
        "pipeline_is_fixture": final_reference["is_fixture"],
    }
    if final_reference["is_fixture"] is False:
        if any(
            parent is None
            for parent in (
                aggregation,
                audit_plan,
                audit_outcome,
                final_human_labels,
            )
        ):
            raise ValueError(
                "formal Reference Selection 缺少 Final reconstruction closure。"
            )
        provenance["final_reference_reconstruction_closure"] = {
            "final_reference": copy.deepcopy(dict(final_reference)),
            "aggregation": copy.deepcopy(dict(aggregation)),
            "safe_zero_audit_plan": copy.deepcopy(dict(audit_plan)),
            "safe_zero_audit_outcome": copy.deepcopy(dict(audit_outcome)),
            "final_human_labels": copy.deepcopy(dict(final_human_labels)),
            "cutoff_decision": (
                copy.deepcopy(dict(cutoff_decision))
                if cutoff_decision is not None
                else None
            ),
        }
    return provenance


def validate_reference_selection_method_provenance(
    details: Mapping[str, Any],
    selected: Sequence[str],
    *,
    inputs: PilotSelectionInputs,
    is_fixture: bool,
    purpose: str,
) -> None:
    provenance = _mapping(dict(details), "Reference selection provenance")
    base_fields = {
        "protocol_id",
        "protocol_config_identity",
        "protocol_config_sha256",
        "reference_finalization",
        "model_roster",
        "execution_manifest",
        "model_judgement_batch_refs",
        "aggregation",
        "safe_zero_audit_plan",
        "safe_zero_audit_outcome",
        "human_labels",
        "cutoff_decision",
        "selected_canonical_entity_ids",
        "all_top8_human_reviewed",
        "sentinel_used_for_ranking",
        "external_lookup",
        "pipeline_is_fixture",
    }
    _exact(
        provenance,
        base_fields
        | ({"final_reference_reconstruction_closure"} if not is_fixture else set()),
        "Reference selection provenance",
    )
    rcp_inputs = load_reference_curation_inputs(
        DEFAULT_RCP_CONFIG, project_root=inputs.project_root
    )
    if (
        provenance["protocol_id"] != RCP_PROTOCOL_ID
        or provenance["protocol_config_identity"]
        != rcp_inputs.config["config_identity"]
        or provenance["protocol_config_sha256"] != sha256_file(rcp_inputs.config_path)
    ):
        raise ValueError("Reference selection protocol/config binding drift。")
    if list(selected) != provenance["selected_canonical_entity_ids"]:
        raise ValueError("Reference selection selected IDs/finalization drift。")
    if provenance["execution_manifest"].get("model_batch_count") != 10:
        raise ValueError("Reference selection 必须绑定 10 model judgement batches。")
    batch_refs = _list(
        provenance["model_judgement_batch_refs"], "Reference model batch refs"
    )
    if (
        len(batch_refs) != 10
        or len(
            {(row.get("topic_id"), row.get("roster_entry_id")) for row in batch_refs}
        )
        != 10
    ):
        raise ValueError("Reference selection model batch roster drift。")
    _bool(
        provenance["all_top8_human_reviewed"],
        "Reference all Top-8 human reviewed",
        expected=True,
    )
    _bool(
        provenance["sentinel_used_for_ranking"],
        "Reference sentinel ranking use",
        expected=False,
    )
    _bool(
        provenance["external_lookup"],
        "Reference external lookup",
        expected=False,
    )
    if provenance["pipeline_is_fixture"] is not is_fixture:
        raise ValueError("Reference selection fixture provenance drift。")
    if is_fixture:
        if purpose != "plumbing_only":
            raise ValueError("fixture Reference selection 只能用于 plumbing_only。")
        return
    if purpose != "formal_internal_reference_selection":
        raise ValueError("formal Reference selection purpose drift。")
    closure = _mapping(
        provenance["final_reference_reconstruction_closure"],
        "formal Final Reference reconstruction closure",
    )
    _exact(
        closure,
        {
            "final_reference",
            "aggregation",
            "safe_zero_audit_plan",
            "safe_zero_audit_outcome",
            "final_human_labels",
            "cutoff_decision",
        },
        "formal Final Reference reconstruction closure",
    )
    final_reference = _mapping(
        closure["final_reference"], "trusted Final Reference"
    )
    aggregation = _mapping(closure["aggregation"], "trusted aggregation")
    audit_plan = _mapping(
        closure["safe_zero_audit_plan"], "trusted safe-zero audit plan"
    )
    audit_outcome = _mapping(
        closure["safe_zero_audit_outcome"], "trusted safe-zero audit outcome"
    )
    final_human_labels = _mapping(
        closure["final_human_labels"], "trusted final Human labels"
    )
    cutoff_decision = closure["cutoff_decision"]
    if cutoff_decision is not None:
        cutoff_decision = _mapping(cutoff_decision, "trusted cutoff decision")
    validated_final = validate_final_reference(
        final_reference,
        inputs=rcp_inputs,
        aggregation=aggregation,
        audit_plan=audit_plan,
        audit_outcome=audit_outcome,
        final_human_labels=final_human_labels,
        cutoff_decision=cutoff_decision,
    )
    if validated_final["is_fixture"]:
        raise ValueError("formal Reference Selection 不接受 fixture Final closure。")
    if list(selected) != list(validated_final["selected_canonical_entity_ids"]):
        raise ValueError(
            "Reference Selection selected IDs 与 reconstructed Final Top-8 不一致。"
        )
    reconstructed_provenance = _reference_method_provenance(
        final_reference,
        aggregation=aggregation,
        audit_plan=audit_plan,
        audit_outcome=audit_outcome,
        final_human_labels=final_human_labels,
        cutoff_decision=cutoff_decision,
    )
    if provenance != reconstructed_provenance:
        raise ValueError(
            "formal Reference Selection provenance 与 Final reconstruction closure 不一致。"
        )


def build_reference_selection_artifact(
    *,
    inputs: ReferenceCurationInputs,
    final_reference: Mapping[str, Any],
    aggregation: Mapping[str, Any],
    audit_plan: Mapping[str, Any],
    audit_outcome: Mapping[str, Any],
    final_human_labels: Mapping[str, Any],
    cutoff_decision: Mapping[str, Any] | None,
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    validated = validate_final_reference(
        final_reference,
        inputs=inputs,
        aggregation=aggregation,
        audit_plan=audit_plan,
        audit_outcome=audit_outcome,
        final_human_labels=final_human_labels,
        cutoff_decision=cutoff_decision,
    )
    return build_selection_artifact(
        inputs=inputs.pilot_inputs,
        topic_id=validated["topic_id"],
        selection_method={
            "method_id": REFERENCE_METHOD_ID,
            "family": "ai_assisted_human_reference",
            "config_identity": inputs.config["config_identity"],
        },
        selected_canonical_entity_ids=list(validated["selected_canonical_entity_ids"]),
        method_specific_provenance=_reference_method_provenance(
            final_reference,
            aggregation=aggregation,
            audit_plan=audit_plan,
            audit_outcome=audit_outcome,
            final_human_labels=final_human_labels,
            cutoff_decision=cutoff_decision,
        ),
        created_at=created_at,
        git_revision=git_revision,
        is_fixture=validated["is_fixture"],
        purpose=(
            "plumbing_only"
            if validated["is_fixture"]
            else "formal_internal_reference_selection"
        ),
    )


def build_reference_selection_freeze_reference(
    reference_selection: Mapping[str, Any],
) -> dict[str, Any]:
    selection = _mapping(dict(reference_selection), "Reference selection freeze")
    topic = _mapping(selection.get("topic"), "Reference selection topic")
    return {
        "reference_selection_artifact_id": _text(
            selection.get("artifact_id"), "Reference artifact_id"
        ),
        "reference_selection_identity": _text(
            selection.get("selection_identity"), "Reference selection identity"
        ),
        "reference_selection_sha256": payload_sha256(selection),
        "reference_selection_frozen_at": _datetime(
            selection.get("created_at"), "Reference selection frozen_at"
        ),
        "topic_id": _text(topic.get("topic_id"), "Reference topic_id"),
        "question_id": _text(topic.get("question_id"), "Reference question_id"),
        "research_question_identity": _text(
            topic.get("research_question_identity"),
            "Reference research question identity",
        ),
        "u80": copy.deepcopy(selection.get("u80")),
        "k": selection.get("k"),
        "expected_reference_method_id": REFERENCE_METHOD_ID,
    }


def validate_reference_selection_freeze_reference(
    reference: Mapping[str, Any],
    reference_selection: Mapping[str, Any],
    *,
    inputs: PilotSelectionInputs,
    require_formal: bool,
) -> dict[str, Any]:
    supplied = _mapping(dict(reference), "BM25 Reference-freeze reference")
    expected = build_reference_selection_freeze_reference(reference_selection)
    if supplied != expected:
        raise ValueError("BM25/Reference selection freeze hash binding drift。")
    validated = validate_selection_artifact(reference_selection, inputs=inputs)
    if validated["method_id"] != REFERENCE_METHOD_ID:
        raise ValueError("Reference freeze expected method ID drift。")
    if require_formal and validated["is_fixture"]:
        raise ValueError("formal BM25 不接受 fixture Reference freeze。")
    for key in ("topic_id", "question_id", "u80", "k"):
        if expected[key] != validated[key]:
            raise ValueError(f"Reference freeze {key} binding drift。")
    return expected


def build_bm25_selection_after_reference(
    inputs: ReferenceCurationInputs,
    *,
    topic_id: str,
    reference_selection_freeze: Mapping[str, Any],
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    validated_reference = validate_selection_artifact(
        reference_selection_freeze, inputs=inputs.pilot_inputs
    )
    if (
        validated_reference["method_id"] != REFERENCE_METHOD_ID
        or validated_reference["is_fixture"]
        or validated_reference["topic_id"] != topic_id
    ):
        raise ValueError(
            "formal BM25 requires same-Topic non-fixture finalized Reference。"
        )
    freeze = build_reference_selection_freeze_reference(reference_selection_freeze)
    validate_reference_selection_freeze_reference(
        freeze,
        reference_selection_freeze,
        inputs=inputs.pilot_inputs,
        require_formal=True,
    )
    bm25_time = _datetime(created_at, "BM25 created_at")
    if datetime.fromisoformat(
        bm25_time.replace("Z", "+00:00")
    ) < datetime.fromisoformat(
        freeze["reference_selection_frozen_at"].replace("Z", "+00:00")
    ):
        raise ValueError("BM25 created_at 不得早于 Reference freeze。")
    topic = topic_config(inputs.pilot_inputs, topic_id)
    candidates = {
        entity_id: inputs.pilot_inputs.view_by_topic_entity[(topic_id, entity_id)]
        for entity_id in inputs.pilot_inputs.u80_by_topic[topic_id]
    }
    bm25 = inputs.pilot_inputs.config["bm25"]
    ranked = rank_pilot_bm25_candidates(
        research_question=topic["research_question"],
        candidates=candidates,
        k=SELECTION_K,
        k1=float(bm25["k1"]),
        b=float(bm25["b"]),
    )
    return build_selection_artifact(
        inputs=inputs.pilot_inputs,
        topic_id=topic_id,
        selection_method={
            "method_id": BM25_METHOD_ID,
            "family": "lexical",
            "config_identity": bm25["config_identity"],
        },
        selected_canonical_entity_ids=[row["canonical_entity_id"] for row in ranked],
        method_specific_provenance={
            "query": topic["research_question"],
            "query_field": bm25["query_field"],
            "paper_representation": bm25["paper_representation"],
            "tokenizer": bm25["tokenizer"],
            "k1": bm25["k1"],
            "b": bm25["b"],
            "corpus_document_count": len(candidates),
            "ranking": ranked,
            "bm25_config_identity": bm25["config_identity"],
            "formal_execution_policy": "after_reference_selection_freeze",
            "reference_selection_freeze": freeze,
        },
        created_at=bm25_time,
        git_revision=git_revision,
        is_fixture=False,
        purpose="formal_bm25_condition_after_reference_selection_freeze",
        reference_selection_freeze=reference_selection_freeze,
    )


def build_rcp_quality_report(
    *,
    aggregation: Mapping[str, Any],
    human_submissions: Sequence[Mapping[str, Any]] = (),
    audit_outcome: Mapping[str, Any] | None = None,
    cutoff_decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    matrix = aggregation["judgement_matrix"]
    core_pairs = [(0, 1), (0, 2), (1, 2)]
    pairwise = {}
    for left, right in core_pairs:
        comparable = [
            row
            for row in matrix
            if row["core_labels"][left] is not None
            and row["core_labels"][right] is not None
        ]
        pairwise[f"core_{left + 1}_vs_{right + 1}"] = (
            sum(
                row["core_labels"][left] == row["core_labels"][right]
                for row in comparable
            )
            / len(comparable)
            if comparable
            else None
        )
    total_outcomes = len(matrix) * 5
    abstains = sum(
        outcome["abstain"]
        for row in matrix
        for outcome in row["core"] + row["sentinels"]
    )
    invalids = sum(
        outcome["status"] != "valid"
        for row in matrix
        for outcome in row["core"] + row["sentinels"]
    )
    sentinel_challenges = sum(
        "sentinel_challenge" in row["routing_reasons"] for row in matrix
    )
    h1_r1 = next(
        (
            submission
            for submission in human_submissions
            if submission.get("stage") == "h1"
            and submission.get("reviewer_slot") == "r1"
        ),
        None,
    )
    h1_r2 = next(
        (
            submission
            for submission in human_submissions
            if submission.get("stage") == "h1"
            and submission.get("reviewer_slot") == "r2"
        ),
        None,
    )
    human_agreement = None
    if h1_r1 is not None and h1_r2 is not None:
        left = {
            row["canonical_entity_id"]: row["relevance"]
            for row in h1_r1["canonical_records"]
        }
        right = {
            row["canonical_entity_id"]: row["relevance"]
            for row in h1_r2["canonical_records"]
        }
        common = sorted(set(left) & set(right))
        human_agreement = (
            sum(left[candidate_id] == right[candidate_id] for candidate_id in common)
            / len(common)
            if common
            else None
        )
    h1_by_reviewer = {
        submission.get("reviewer_slot"): submission
        for submission in human_submissions
        if submission.get("stage") == "h1"
        and submission.get("reviewer_slot") in {"r1", "r2"}
    }
    h2_changes = 0
    h2_comparisons = 0
    for submission in human_submissions:
        reviewer = submission.get("reviewer_slot")
        if submission.get("stage") != "h2" or reviewer not in h1_by_reviewer:
            continue
        h1_records = {
            row["canonical_entity_id"]: row["relevance"]
            for row in h1_by_reviewer[reviewer]["canonical_records"]
        }
        for row in submission.get("canonical_records", []):
            candidate_id = row["canonical_entity_id"]
            if candidate_id in h1_records:
                h2_comparisons += 1
                h2_changes += row["relevance"] != h1_records[candidate_id]
    h1_to_h2_change_rate = h2_changes / h2_comparisons if h2_comparisons else None
    r3_ids = {
        row["canonical_entity_id"]
        for submission in human_submissions
        if submission.get("reviewer_slot") == "r3"
        for row in submission.get("canonical_records", [])
    }
    payload: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_stability_quality_report",
        "artifact_id": "pending",
        "report_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "aggregation": _artifact_reference(aggregation),
        "model_layer": {
            "core_unanimity_rate": sum(
                row["core_unanimous_label"] is not None for row in matrix
            )
            / len(matrix),
            "core_pairwise_agreement": pairwise,
            "boundary_full_agreement_rate": sum(
                "boundary_conflict" not in row["routing_reasons"] for row in matrix
            )
            / len(matrix),
            "abstain_rate": abstains / total_outcomes,
            "invalid_span_or_schema_rate": invalids / total_outcomes,
            "sentinel_unique_challenge_rate": sentinel_challenges / len(matrix),
        },
        "human_layer": {
            "h1_r1_r2_agreement_rate": human_agreement,
            "h1_to_h2_change_rate": h1_to_h2_change_rate,
            "r3_case_count": len(r3_ids),
            "r3_case_rate_over_human_route": (
                len(r3_ids) / aggregation["human_route_count"]
                if aggregation["human_route_count"]
                else 0.0
            ),
            "safe_zero_audit_workload": (
                len(audit_outcome.get("reviewed_canonical_entity_ids", []))
                if audit_outcome is not None
                else None
            ),
            "final_cutoff_disagreement": (
                {
                    "r1_r2_choices_differ": cutoff_decision["blind_r1_selected_ids"]
                    != cutoff_decision["blind_r2_selected_ids"],
                    "intersection_count": len(
                        cutoff_decision["intersection_priority_ids"]
                    ),
                    "hash_last_resort_used": bool(
                        cutoff_decision["hash_tie_break"]["used_for_ids"]
                    ),
                }
                if cutoff_decision is not None
                else None
            ),
        },
        "interpretation": "stability_and_workflow_metrics_not_astronomy_correctness",
        "is_fixture": aggregation["is_fixture"],
    }
    identity = _identity_without(
        payload,
        prefix=QUALITY_REPORT_IDENTITY_PREFIX,
        omitted={"artifact_id", "report_identity"},
    )
    payload["report_identity"] = identity
    payload["artifact_id"] = _artifact_id("srtp_rcp_quality", identity)
    return payload


__all__ = [
    "DEFAULT_RCP_CONFIG",
    "build_bm25_selection_after_reference",
    "build_cutoff_decision",
    "build_cutoff_decision_from_submissions",
    "build_final_reference",
    "build_rcp_quality_report",
    "build_reference_selection_artifact",
    "build_reference_selection_freeze_reference",
    "validate_cutoff_decision",
    "validate_final_reference",
    "validate_reference_selection_freeze_reference",
    "validate_reference_selection_method_provenance",
]
