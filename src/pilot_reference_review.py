"""Blind selective-human-review workflow for RCP-v0.3.

Human-facing tasks never contain model identity, votes, routing state, BM25, or
retrieval signals.  H2 reveals only deterministic, anonymized exact evidence
cards.  Imported H1/H2/R3 submissions remain immutable content-addressed
artifacts and are never written back over a prior stage.
"""

from __future__ import annotations

import copy
import hashlib
import math
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.pilot_reference_curation import (
    BOUNDARY_DIMENSIONS,
    BOUNDARY_VALUES,
    H2_IDENTITY_PREFIX,
    HUMAN_LABEL_IDENTITY_PREFIX,
    HUMAN_MAP_IDENTITY_PREFIX,
    HUMAN_REVIEWER_SLOTS,
    HUMAN_SUBMISSION_IDENTITY_PREFIX,
    HUMAN_TASK_FORBIDDEN_KEYS,
    HUMAN_TASK_IDENTITY_PREFIX,
    HUMAN_TASK_PACKAGE_IDENTITY_PREFIX,
    RCP_PROTOCOL_ID,
    RCP_SCHEMA_VERSION,
    ReferenceCurationInputs,
    _all_keys,
    _artifact_id,
    _artifact_reference,
    _bool,
    _datetime,
    _exact,
    _git_revision,
    _identity_without,
    _list,
    _mapping,
    _source_snapshot,
    _strings,
    _text,
    _topic_boundary,
    _u80_reference,
    _validate_evidence_spans,
)
from src.pilot_selection import (
    payload_sha256,
    topic_config,
    validate_external_output_path,
    write_json,
)
from src.w6_contracts import deterministic_identity


HUMAN_STAGES = frozenset({"h1", "h2", "r3_h1", "r3_h2"})
CUTOFF_TASK_PACKAGE_IDENTITY_PREFIX = "srtp-rcp-cutoff-task-package"
CUTOFF_MAP_IDENTITY_PREFIX = "srtp-rcp-cutoff-map"
CUTOFF_SUBMISSION_IDENTITY_PREFIX = "srtp-rcp-cutoff-submission"


def derive_h1_candidate_ids(
    aggregation: Mapping[str, Any],
    audit_plan: Mapping[str, Any],
    *,
    audit_outcome: Mapping[str, Any] | None = None,
) -> list[str]:
    matrix = _list(aggregation.get("judgement_matrix"), "judgement matrix")
    u80_order = [row["canonical_entity_id"] for row in matrix]
    required = {
        row["canonical_entity_id"] for row in matrix if row.get("human_route") is True
    }
    if audit_plan.get("aggregation") != _artifact_reference(aggregation):
        raise ValueError("H1 audit plan/aggregation binding drift。")
    required.update(
        _strings(
            audit_plan.get("audit_sample_canonical_entity_ids"), "audit sample IDs"
        )
    )
    if audit_outcome is not None:
        if audit_outcome.get("audit_plan") != _artifact_reference(audit_plan):
            raise ValueError("H1 audit outcome/plan binding drift。")
        if audit_outcome.get("escalation_required") is True:
            required.update(
                _strings(
                    audit_outcome.get("escalated_review_canonical_entity_ids"),
                    "escalated safe-zero IDs",
                )
            )
    unknown = required - set(u80_order)
    if unknown:
        raise ValueError("H1 candidate roster 含 U80 外 canonical IDs。")
    return [candidate_id for candidate_id in u80_order if candidate_id in required]


def _human_candidate_id(
    *,
    reviewer_slot: str,
    stage: str,
    topic_id: str,
    canonical_entity_id: str,
) -> str:
    digest = hashlib.sha256(
        "|".join(
            [
                "srtp-rcp-v0.3-human-opaque-v1",
                reviewer_slot,
                stage,
                topic_id,
                canonical_entity_id,
            ]
        ).encode("utf-8")
    ).hexdigest()
    return f"case_{digest[:20]}"


def _human_order_key(
    *,
    reviewer_slot: str,
    stage: str,
    topic_id: str,
    canonical_entity_id: str,
) -> str:
    return hashlib.sha256(
        "|".join(
            [
                "srtp-rcp-v0.3-human-order-v1",
                reviewer_slot,
                stage,
                topic_id,
                canonical_entity_id,
            ]
        ).encode("utf-8")
    ).hexdigest()


def _human_task_identity_payload(task: Mapping[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dict(task))
    body.pop("artifact_id", None)
    body.pop("task_identity", None)
    return body


def build_human_task_package(
    *,
    inputs: ReferenceCurationInputs,
    aggregation: Mapping[str, Any],
    reviewer_slot: str,
    stage: str,
    candidate_ids: Sequence[str],
    created_at: str,
    git_revision: str,
    h2_evidence_packet: Mapping[str, Any] | None = None,
    prior_r3_h1_submission: Mapping[str, Any] | None = None,
    _skip_validation: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reviewer = _text(reviewer_slot, "human reviewer slot")
    if reviewer not in HUMAN_REVIEWER_SLOTS:
        raise ValueError("human reviewer slot 必须是 r1/r2/r3。")
    if stage not in HUMAN_STAGES:
        raise ValueError("human review stage 非法。")
    if stage.startswith("r3") and reviewer != "r3":
        raise ValueError("R3 stage 只能分配给 r3。")
    if stage in {"h1", "h2"} and reviewer not in {"r1", "r2"}:
        raise ValueError("H1/H2 stage 只能分配给 r1/r2。")
    if (stage in {"h2", "r3_h2"}) != (h2_evidence_packet is not None):
        raise ValueError("H2 stage 必须且只能绑定 anonymized evidence packet。")
    if (stage == "r3_h2") != (prior_r3_h1_submission is not None):
        raise ValueError("R3 H2 必须且只能在同 roster 的 blind R3 H1 提交后导出。")
    if (
        aggregation.get("protocol", {}).get("config_identity")
        != inputs.config["config_identity"]
    ):
        raise ValueError("human task wrong RCP protocol config。")
    topic_id = aggregation["topic"]["topic_id"]
    u80_order = list(inputs.pilot_inputs.u80_by_topic[topic_id])
    requested = _strings(list(candidate_ids), "human task candidate IDs")
    if not requested:
        raise ValueError("human task candidate roster 不得为空。")
    if not set(requested).issubset(set(u80_order)):
        raise ValueError("human task candidate roster 含 U80 外 ID。")
    if h2_evidence_packet is not None:
        if h2_evidence_packet.get("aggregation") != _artifact_reference(aggregation):
            raise ValueError("H2 evidence packet/aggregation binding drift。")
        evidence_by_id = {
            row["canonical_entity_id"]: row["cards"]
            for row in h2_evidence_packet["cases"]
        }
        if stage == "h2" and set(requested) != set(evidence_by_id):
            raise ValueError("H2 evidence packet candidate roster drift。")
        if stage == "r3_h2" and not set(requested).issubset(set(evidence_by_id)):
            raise ValueError("R3 H2 roster 超出 H2 evidence packet triggers。")
    else:
        evidence_by_id = {}
    if prior_r3_h1_submission is not None:
        prior_records = _validate_submission_identity_and_scope(
            prior_r3_h1_submission,
            aggregation=aggregation,
            reviewer_slot="r3",
            allowed_stages={"r3_h1"},
        )
        if set(prior_records) != set(requested):
            raise ValueError("R3 H2 roster 必须精确等于 prior blind R3 H1 roster。")
    rows = sorted(
        requested,
        key=lambda candidate_id: (
            _human_order_key(
                reviewer_slot=reviewer,
                stage=stage,
                topic_id=topic_id,
                canonical_entity_id=candidate_id,
            ),
            candidate_id,
        ),
    )
    topic = topic_config(inputs.pilot_inputs, topic_id)
    visible_topic = {
        "topic_id": topic_id,
        "question_id": topic["question_id"],
        "research_question": topic["research_question"],
        "research_question_identity": topic["research_question_identity"],
        "boundary": _topic_boundary(inputs.pilot_inputs, topic_id),
    }
    tasks: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    for position, canonical_id in enumerate(rows, start=1):
        source = _source_snapshot(inputs.pilot_inputs, topic_id, canonical_id)
        candidate_id = _human_candidate_id(
            reviewer_slot=reviewer,
            stage=stage,
            topic_id=topic_id,
            canonical_entity_id=canonical_id,
        )
        task: dict[str, Any] = {
            "schema_version": RCP_SCHEMA_VERSION,
            "artifact_type": "srtp_rcp_human_review_task",
            "artifact_id": "pending",
            "task_identity": "pending",
            "protocol_id": RCP_PROTOCOL_ID,
            "reviewer_slot": reviewer,
            "stage": stage,
            "topic": copy.deepcopy(visible_topic),
            "candidate": {
                "candidate_id": candidate_id,
                "title": source["title"],
                "abstract": source["abstract"],
            },
            "anonymous_ai_evidence_cards": copy.deepcopy(
                evidence_by_id.get(canonical_id, [])
            ),
            "external_lookup": False,
            "independent_review_required": True,
            "is_fixture": aggregation["is_fixture"],
        }
        identity = deterministic_identity(
            HUMAN_TASK_IDENTITY_PREFIX, _human_task_identity_payload(task)
        )
        task["task_identity"] = identity
        task["artifact_id"] = _artifact_id("srtp_rcp_human_task", identity)
        tasks.append(task)
        mapping_rows.append(
            {
                "position": position,
                "candidate_id": candidate_id,
                "canonical_entity_id": canonical_id,
                "selection_item_id": source["selection_item_id"],
                "source_snapshot_sha256": source["source_snapshot_sha256"],
                "task_artifact_id": task["artifact_id"],
                "task_identity": task["task_identity"],
            }
        )
    created = _datetime(created_at, "human task package created_at")
    package: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_human_task_package",
        "artifact_id": "pending",
        "package_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "protocol_config_identity": inputs.config["config_identity"],
        "reviewer_slot": reviewer,
        "stage": stage,
        "topic": copy.deepcopy(aggregation["topic"]),
        "u80": _u80_reference(inputs.pilot_inputs),
        "aggregation": _artifact_reference(aggregation),
        "h2_evidence_packet": (
            _artifact_reference(h2_evidence_packet)
            if h2_evidence_packet is not None
            else None
        ),
        "prior_r3_h1_submission": (
            _artifact_reference(prior_r3_h1_submission)
            if prior_r3_h1_submission is not None
            else None
        ),
        "candidate_count": len(tasks),
        "tasks": tasks,
        "status": "prepared_not_started",
        "created_at": created,
        "is_fixture": aggregation["is_fixture"],
        "provenance": {
            "created_by": "src.pilot_reference_review",
            "git_revision": _git_revision(git_revision, "human task git_revision"),
        },
    }
    identity = _identity_without(
        package,
        prefix=HUMAN_TASK_PACKAGE_IDENTITY_PREFIX,
        omitted={"artifact_id", "package_identity"},
    )
    package["package_identity"] = identity
    package["artifact_id"] = _artifact_id("srtp_rcp_human_tasks", identity)
    private_map: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_human_task_map",
        "artifact_id": "pending",
        "map_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "task_package": _artifact_reference(package),
        "reviewer_slot": reviewer,
        "stage": stage,
        "topic_id": topic_id,
        "candidate_map": mapping_rows,
        "visibility": "private_coordinator_only",
        "is_fixture": aggregation["is_fixture"],
    }
    map_identity = _identity_without(
        private_map,
        prefix=HUMAN_MAP_IDENTITY_PREFIX,
        omitted={"artifact_id", "map_identity"},
    )
    private_map["map_identity"] = map_identity
    private_map["artifact_id"] = _artifact_id("srtp_rcp_human_map", map_identity)
    if not _skip_validation:
        validate_human_task_package(
            package,
            mapping=private_map,
            inputs=inputs,
            aggregation=aggregation,
            candidate_ids=requested,
            h2_evidence_packet=h2_evidence_packet,
            prior_r3_h1_submission=prior_r3_h1_submission,
        )
    return package, private_map


def validate_human_task_package(
    package: Mapping[str, Any],
    *,
    mapping: Mapping[str, Any],
    inputs: ReferenceCurationInputs,
    aggregation: Mapping[str, Any],
    candidate_ids: Sequence[str],
    h2_evidence_packet: Mapping[str, Any] | None = None,
    prior_r3_h1_submission: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    artifact = _mapping(dict(package), "human task package")
    private_map = _mapping(dict(mapping), "human task mapping")
    reconstructed, reconstructed_map = build_human_task_package(
        inputs=inputs,
        aggregation=aggregation,
        reviewer_slot=artifact.get("reviewer_slot"),
        stage=artifact.get("stage"),
        candidate_ids=candidate_ids,
        created_at=artifact.get("created_at"),
        git_revision=_mapping(artifact.get("provenance"), "human task provenance").get(
            "git_revision"
        ),
        h2_evidence_packet=h2_evidence_packet,
        prior_r3_h1_submission=prior_r3_h1_submission,
        _skip_validation=True,
    )
    if artifact != reconstructed or private_map != reconstructed_map:
        raise ValueError("human task/map deterministic reconstruction drift。")
    forbidden = _all_keys(artifact) & HUMAN_TASK_FORBIDDEN_KEYS
    if forbidden:
        raise ValueError(
            "human task 泄露 model/vote/ranking fields：" + ", ".join(sorted(forbidden))
        )
    if artifact["stage"] in {"h1", "r3_h1"} and any(
        task["anonymous_ai_evidence_cards"] for task in artifact["tasks"]
    ):
        raise ValueError("blind-first H1/R3 task 不得包含 AI evidence。")
    return {
        "artifact_id": artifact["artifact_id"],
        "package_identity": artifact["package_identity"],
        "sha256": payload_sha256(artifact),
        "map_sha256": payload_sha256(private_map),
        "reviewer_slot": artifact["reviewer_slot"],
        "stage": artifact["stage"],
        "topic_id": artifact["topic"]["topic_id"],
        "candidate_count": artifact["candidate_count"],
        "is_fixture": artifact["is_fixture"],
    }


def build_blank_human_response(package: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_human_review_response",
        "protocol_id": RCP_PROTOCOL_ID,
        "task_package_artifact_id": package["artifact_id"],
        "task_package_identity": package["package_identity"],
        "reviewer_slot": package["reviewer_slot"],
        "stage": package["stage"],
        "status": "blank_not_started",
        "reviewer_id": "",
        "judgements": [
            {
                "candidate_id": task["candidate"]["candidate_id"],
                "relevance": "defer",
                "boundary": {
                    dimension: "not_stated" for dimension in BOUNDARY_DIMENSIONS
                },
                "evidence_sufficiency": "insufficient",
                "evidence_spans": [],
                "short_reason": "",
            }
            for task in package["tasks"]
        ],
        "timing": {
            "started_at": "",
            "completed_at": "",
            "elapsed_minutes": 0,
        },
        "external_lookup": False,
        "independent_submission_acknowledged": False,
        "submitted_at": "",
    }


def render_human_review_instructions(package: Mapping[str, Any]) -> str:
    stage = _text(package.get("stage"), "human task stage")
    evidence_note = (
        "This H2 stage includes only anonymized, deduplicated exact evidence cards."
        if stage in {"h2", "r3_h2"}
        else "This is a blind-first stage and contains no AI evidence."
    )
    return f"""# RCP-v0.3 Selective Human Review

Review each case independently using only the frozen Research Question, Topic
boundary, Title, Abstract, and any evidence cards explicitly included in this
stage. {evidence_note}

Do not browse, retrieve full text, consult BM25/rank/score data, ask another
reviewer, or attempt to identify the paper from its opaque ID. Record 0, 1, 2,
or `defer`, the four boundary values, 1–2 exact spans for a numeric judgement,
and a short auditable reason. Set `external_lookup=false`, complete timing, and
acknowledge independent submission. Do not overwrite an earlier submission.
"""


def export_human_task_package(
    *,
    package: Mapping[str, Any],
    mapping: Mapping[str, Any],
    inputs: ReferenceCurationInputs,
    aggregation: Mapping[str, Any],
    candidate_ids: Sequence[str],
    human_output_dir: str | Path,
    coordinator_map_output: str | Path,
    h2_evidence_packet: Mapping[str, Any] | None = None,
    prior_r3_h1_submission: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    validate_human_task_package(
        package,
        mapping=mapping,
        inputs=inputs,
        aggregation=aggregation,
        candidate_ids=candidate_ids,
        h2_evidence_packet=h2_evidence_packet,
        prior_r3_h1_submission=prior_r3_h1_submission,
    )
    output = validate_external_output_path(
        human_output_dir,
        project_root=inputs.project_root,
        label="RCP human-facing task output",
    )
    coordinator = validate_external_output_path(
        coordinator_map_output,
        project_root=inputs.project_root,
        label="RCP private human coordinator map output",
    )
    if output.exists() and any(output.iterdir()):
        raise ValueError("RCP human-facing output directory 必须不存在或为空。")
    if coordinator.exists():
        raise ValueError("RCP human coordinator map output 已存在；禁止覆盖。")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "task_package.json", package)
    write_json(output / "response.json", build_blank_human_response(package))
    (output / "HUMAN_REVIEW_INSTRUCTIONS.md").write_text(
        render_human_review_instructions(package),
        encoding="utf-8",
        newline="\n",
    )
    write_json(coordinator, mapping)
    return {
        "human_output_dir": str(output),
        "task_package": str(output / "task_package.json"),
        "response": str(output / "response.json"),
        "coordinator_map": str(coordinator),
    }


def build_cutoff_task_package(
    *,
    inputs: ReferenceCurationInputs,
    aggregation: Mapping[str, Any],
    reviewer_slot: str,
    tie_group_candidate_ids: Sequence[str],
    slots_required: int,
    created_at: str,
    git_revision: str,
    _skip_validation: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reviewer = _text(reviewer_slot, "cutoff reviewer slot")
    if reviewer not in {"r1", "r2", "r3"}:
        raise ValueError("cutoff reviewer slot 必须是 r1/r2/r3。")
    tie_group = _strings(list(tie_group_candidate_ids), "cutoff tie group")
    slots = slots_required
    if isinstance(slots, bool) or not isinstance(slots, int) or slots < 1:
        raise ValueError("cutoff slots_required 必须是正整数。")
    if len(tie_group) <= slots:
        raise ValueError("cutoff blind task requires tie-group size > slots。")
    topic_id = aggregation.get("topic", {}).get("topic_id")
    u80 = set(inputs.pilot_inputs.u80_by_topic.get(topic_id, ()))
    if not set(tie_group).issubset(u80):
        raise ValueError("cutoff tie group 包含 frozen U80 外 candidate。")
    stage = f"cutoff_{reviewer}"
    ordered = sorted(
        tie_group,
        key=lambda candidate_id: (
            _human_order_key(
                reviewer_slot=reviewer,
                stage=stage,
                topic_id=topic_id,
                canonical_entity_id=candidate_id,
            ),
            candidate_id,
        ),
    )
    topic = topic_config(inputs.pilot_inputs, topic_id)
    visible_topic = {
        "topic_id": topic_id,
        "question_id": topic["question_id"],
        "research_question": topic["research_question"],
        "research_question_identity": topic["research_question_identity"],
        "boundary": _topic_boundary(inputs.pilot_inputs, topic_id),
    }
    candidates = []
    map_rows = []
    for position, canonical_id in enumerate(ordered, start=1):
        source = _source_snapshot(inputs.pilot_inputs, topic_id, canonical_id)
        candidate_id = _human_candidate_id(
            reviewer_slot=reviewer,
            stage=stage,
            topic_id=topic_id,
            canonical_entity_id=canonical_id,
        )
        candidates.append(
            {
                "candidate_id": candidate_id,
                "title": source["title"],
                "abstract": source["abstract"],
            }
        )
        map_rows.append(
            {
                "position": position,
                "candidate_id": candidate_id,
                "canonical_entity_id": canonical_id,
                "selection_item_id": source["selection_item_id"],
                "source_snapshot_sha256": source["source_snapshot_sha256"],
            }
        )
    response_mode = (
        "blind_select_exact_s"
        if reviewer in {"r1", "r2"}
        else "blind_priority_partition_full_tie_group"
    )
    created = _datetime(created_at, "cutoff task created_at")
    package: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_cutoff_human_task_package",
        "artifact_id": "pending",
        "package_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "protocol_config_identity": inputs.config["config_identity"],
        "reviewer_slot": reviewer,
        "stage": stage,
        "response_mode": response_mode,
        "slots_required": slots,
        "tie_group_count": len(tie_group),
        "topic": visible_topic,
        "u80": _u80_reference(inputs.pilot_inputs),
        "aggregation": _artifact_reference(aggregation),
        "candidates": candidates,
        "external_lookup": False,
        "independent_review_required": True,
        "status": "prepared_not_started",
        "created_at": created,
        "is_fixture": aggregation["is_fixture"],
        "provenance": {
            "created_by": "src.pilot_reference_review",
            "git_revision": _git_revision(git_revision, "cutoff task git revision"),
        },
    }
    identity = _identity_without(
        package,
        prefix=CUTOFF_TASK_PACKAGE_IDENTITY_PREFIX,
        omitted={"artifact_id", "package_identity"},
    )
    package["package_identity"] = identity
    package["artifact_id"] = _artifact_id("srtp_rcp_cutoff_tasks", identity)
    mapping: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_cutoff_human_map",
        "artifact_id": "pending",
        "map_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "task_package": _artifact_reference(package),
        "reviewer_slot": reviewer,
        "stage": stage,
        "topic_id": topic_id,
        "slots_required": slots,
        "candidate_map": map_rows,
        "visibility": "private_coordinator_only",
        "is_fixture": aggregation["is_fixture"],
    }
    map_identity = _identity_without(
        mapping,
        prefix=CUTOFF_MAP_IDENTITY_PREFIX,
        omitted={"artifact_id", "map_identity"},
    )
    mapping["map_identity"] = map_identity
    mapping["artifact_id"] = _artifact_id("srtp_rcp_cutoff_map", map_identity)
    if not _skip_validation:
        validate_cutoff_task_package(
            package,
            mapping=mapping,
            inputs=inputs,
            aggregation=aggregation,
            tie_group_candidate_ids=tie_group,
            slots_required=slots,
        )
    return package, mapping


def validate_cutoff_task_package(
    package: Mapping[str, Any],
    *,
    mapping: Mapping[str, Any],
    inputs: ReferenceCurationInputs,
    aggregation: Mapping[str, Any],
    tie_group_candidate_ids: Sequence[str],
    slots_required: int,
) -> dict[str, Any]:
    artifact = _mapping(dict(package), "cutoff human task package")
    private_map = _mapping(dict(mapping), "cutoff human task map")
    reconstructed, reconstructed_map = build_cutoff_task_package(
        inputs=inputs,
        aggregation=aggregation,
        reviewer_slot=artifact.get("reviewer_slot"),
        tie_group_candidate_ids=tie_group_candidate_ids,
        slots_required=slots_required,
        created_at=artifact.get("created_at"),
        git_revision=_mapping(artifact.get("provenance"), "cutoff task provenance").get(
            "git_revision"
        ),
        _skip_validation=True,
    )
    if artifact != reconstructed or private_map != reconstructed_map:
        raise ValueError("cutoff task/map deterministic reconstruction drift。")
    forbidden = _all_keys(artifact) & HUMAN_TASK_FORBIDDEN_KEYS
    if forbidden:
        raise ValueError("cutoff task 泄露 model/vote/ranking fields。")
    return {
        "artifact_id": artifact["artifact_id"],
        "package_identity": artifact["package_identity"],
        "sha256": payload_sha256(artifact),
        "map_sha256": payload_sha256(private_map),
        "reviewer_slot": artifact["reviewer_slot"],
        "topic_id": artifact["topic"]["topic_id"],
        "candidate_count": artifact["tie_group_count"],
        "is_fixture": artifact["is_fixture"],
    }


def build_blank_cutoff_response(package: Mapping[str, Any]) -> dict[str, Any]:
    is_r3 = package.get("reviewer_slot") == "r3"
    return {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_cutoff_human_response",
        "protocol_id": RCP_PROTOCOL_ID,
        "task_package_artifact_id": package["artifact_id"],
        "task_package_identity": package["package_identity"],
        "reviewer_slot": package["reviewer_slot"],
        "stage": package["stage"],
        "status": "blank_not_started",
        "reviewer_id": "",
        "selected_candidate_ids": [] if not is_r3 else None,
        "priority_groups": [] if is_r3 else None,
        "short_reason": "",
        "timing": {"started_at": "", "completed_at": "", "elapsed_minutes": 0},
        "external_lookup": False,
        "independent_submission_acknowledged": False,
        "submitted_at": "",
    }


def render_cutoff_review_instructions(package: Mapping[str, Any]) -> str:
    if package.get("reviewer_slot") in {"r1", "r2"}:
        action = (
            f"Select exactly {package['slots_required']} opaque candidates from the "
            "complete task roster."
        )
    else:
        action = (
            "Place every opaque candidate exactly once into ordered priority groups; "
            "candidates in one group are tied."
        )
    return f"""# RCP-v0.3 Blind Cutoff Review

{action} Use only the frozen Research Question, Topic boundary, Title, and
Abstract. Do not browse, identify papers, consult AI/BM25/rank/score data, or
ask another reviewer. Complete the response JSON, timing, `external_lookup=false`,
and the independent-submission acknowledgement. The coordinator mapping is not
part of this bundle and must not be shown to the reviewer.
"""


def export_cutoff_task_package(
    *,
    package: Mapping[str, Any],
    mapping: Mapping[str, Any],
    inputs: ReferenceCurationInputs,
    aggregation: Mapping[str, Any],
    tie_group_candidate_ids: Sequence[str],
    slots_required: int,
    human_output_dir: str | Path,
    coordinator_map_output: str | Path,
) -> dict[str, str]:
    validate_cutoff_task_package(
        package,
        mapping=mapping,
        inputs=inputs,
        aggregation=aggregation,
        tie_group_candidate_ids=tie_group_candidate_ids,
        slots_required=slots_required,
    )
    output = validate_external_output_path(
        human_output_dir,
        project_root=inputs.project_root,
        label="RCP cutoff human-facing output",
    )
    coordinator = validate_external_output_path(
        coordinator_map_output,
        project_root=inputs.project_root,
        label="RCP cutoff private coordinator map output",
    )
    if output.exists() and any(output.iterdir()):
        raise ValueError("RCP cutoff output directory 必须不存在或为空。")
    if coordinator.exists():
        raise ValueError("RCP cutoff coordinator map 已存在；禁止覆盖。")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "task_package.json", package)
    write_json(output / "response.json", build_blank_cutoff_response(package))
    (output / "CUTOFF_REVIEW_INSTRUCTIONS.md").write_text(
        render_cutoff_review_instructions(package),
        encoding="utf-8",
        newline="\n",
    )
    write_json(coordinator, mapping)
    return {
        "human_output_dir": str(output),
        "task_package": str(output / "task_package.json"),
        "response": str(output / "response.json"),
        "coordinator_map": str(coordinator),
    }


def import_cutoff_submission(
    response: Mapping[str, Any],
    *,
    task_package: Mapping[str, Any],
    mapping: Mapping[str, Any],
    imported_at: str,
    git_revision: str,
    _skip_validation: bool = False,
) -> dict[str, Any]:
    form = _mapping(dict(response), "cutoff human response")
    _exact(
        form,
        {
            "schema_version",
            "artifact_type",
            "protocol_id",
            "task_package_artifact_id",
            "task_package_identity",
            "reviewer_slot",
            "stage",
            "status",
            "reviewer_id",
            "selected_candidate_ids",
            "priority_groups",
            "short_reason",
            "timing",
            "external_lookup",
            "independent_submission_acknowledged",
            "submitted_at",
        },
        "cutoff human response",
    )
    if (
        form["schema_version"] != RCP_SCHEMA_VERSION
        or form["artifact_type"] != "srtp_rcp_cutoff_human_response"
        or form["protocol_id"] != RCP_PROTOCOL_ID
        or form["status"] != "completed"
        or form["task_package_artifact_id"] != task_package["artifact_id"]
        or form["task_package_identity"] != task_package["package_identity"]
        or form["reviewer_slot"] != task_package["reviewer_slot"]
        or form["stage"] != task_package["stage"]
    ):
        raise ValueError("cutoff response protocol/task/reviewer binding drift。")
    _text(form["reviewer_id"], "cutoff reviewer_id")
    _bool(form["external_lookup"], "cutoff external lookup", expected=False)
    _bool(
        form["independent_submission_acknowledged"],
        "cutoff independent acknowledgement",
        expected=True,
    )
    _datetime(form["submitted_at"], "cutoff submitted_at")
    reason = _text(form["short_reason"], "cutoff short reason")
    if len(reason) > 240:
        raise ValueError("cutoff short_reason 超过 240 characters。")
    timing = _mapping(form["timing"], "cutoff timing")
    _exact(timing, {"started_at", "completed_at", "elapsed_minutes"}, "cutoff timing")
    started = _datetime(timing["started_at"], "cutoff started_at")
    completed = _datetime(timing["completed_at"], "cutoff completed_at")
    elapsed = timing["elapsed_minutes"]
    if (
        datetime.fromisoformat(completed.replace("Z", "+00:00"))
        < datetime.fromisoformat(started.replace("Z", "+00:00"))
        or isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(float(elapsed))
        or float(elapsed) <= 0
    ):
        raise ValueError("cutoff timing 非法。")
    map_rows = _list(mapping.get("candidate_map"), "cutoff candidate map")
    canonical_by_opaque = {
        row["candidate_id"]: row["canonical_entity_id"] for row in map_rows
    }
    if len(canonical_by_opaque) != len(map_rows):
        raise ValueError("cutoff private map duplicate opaque ID。")
    reviewer = task_package["reviewer_slot"]
    canonical_selected: list[str] | None
    canonical_groups: list[list[str]] | None
    if reviewer in {"r1", "r2"}:
        opaque = _strings(
            form["selected_candidate_ids"],
            "cutoff selected opaque IDs",
            count=task_package["slots_required"],
        )
        if form["priority_groups"] is not None or not set(opaque).issubset(
            canonical_by_opaque
        ):
            raise ValueError("R1/R2 cutoff response selection schema/ID drift。")
        canonical_selected = [canonical_by_opaque[item] for item in opaque]
        canonical_groups = None
    else:
        if form["selected_candidate_ids"] is not None:
            raise ValueError("R3 cutoff response 不得使用 selected_candidate_ids。")
        raw_groups = _list(
            form["priority_groups"], "R3 cutoff priority groups", nonempty=True
        )
        opaque_groups = [
            _strings(group, "R3 cutoff priority group") for group in raw_groups
        ]
        flattened = [item for group in opaque_groups for item in group]
        if len(flattened) != len(set(flattened)) or set(flattened) != set(
            canonical_by_opaque
        ):
            raise ValueError("R3 cutoff priority 必须精确覆盖完整 tie group 一次。")
        canonical_selected = None
        canonical_groups = [
            [canonical_by_opaque[item] for item in group] for group in opaque_groups
        ]
    payload: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_cutoff_human_submission",
        "artifact_id": "pending",
        "submission_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "reviewer_slot": reviewer,
        "reviewer_id": form["reviewer_id"],
        "stage": form["stage"],
        "topic": copy.deepcopy(task_package["topic"]),
        "task_package": _artifact_reference(task_package),
        "private_map_sha256": payload_sha256(mapping),
        "tie_group_canonical_entity_ids": sorted(canonical_by_opaque.values()),
        "slots_required": task_package["slots_required"],
        "selected_canonical_entity_ids": canonical_selected,
        "canonical_priority_groups": canonical_groups,
        "raw_response": copy.deepcopy(form),
        "raw_response_sha256": payload_sha256(form),
        "external_lookup": False,
        "independent_submission_acknowledged": True,
        "imported_at": _datetime(imported_at, "cutoff imported_at"),
        "is_fixture": task_package["is_fixture"],
        "provenance": {
            "created_by": "src.pilot_reference_review",
            "git_revision": _git_revision(git_revision, "cutoff import git revision"),
        },
    }
    identity = _identity_without(
        payload,
        prefix=CUTOFF_SUBMISSION_IDENTITY_PREFIX,
        omitted={"artifact_id", "submission_identity"},
    )
    payload["submission_identity"] = identity
    payload["artifact_id"] = _artifact_id("srtp_rcp_cutoff_submission", identity)
    if not _skip_validation:
        validate_cutoff_submission(
            payload,
            task_package=task_package,
            mapping=mapping,
        )
    return payload


def validate_cutoff_submission(
    submission: Mapping[str, Any],
    *,
    task_package: Mapping[str, Any],
    mapping: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = _mapping(dict(submission), "cutoff submission")
    reconstructed = import_cutoff_submission(
        artifact.get("raw_response"),
        task_package=task_package,
        mapping=mapping,
        imported_at=artifact.get("imported_at"),
        git_revision=_mapping(
            artifact.get("provenance"), "cutoff submission provenance"
        ).get("git_revision"),
        _skip_validation=True,
    )
    if artifact != reconstructed:
        raise ValueError("cutoff submission immutable identity/content drift。")
    return {
        "artifact_id": artifact["artifact_id"],
        "submission_identity": artifact["submission_identity"],
        "sha256": payload_sha256(artifact),
        "reviewer_slot": artifact["reviewer_slot"],
        "topic_id": artifact["topic"]["topic_id"],
        "is_fixture": artifact["is_fixture"],
    }


def validate_cutoff_submission_identity(
    submission: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = _mapping(dict(submission), "cutoff submission")
    reviewer = artifact.get("reviewer_slot")
    if (
        artifact.get("artifact_type") != "srtp_rcp_cutoff_human_submission"
        or artifact.get("protocol_id") != RCP_PROTOCOL_ID
        or reviewer not in {"r1", "r2", "r3"}
        or artifact.get("stage") != f"cutoff_{reviewer}"
        or artifact.get("raw_response_sha256")
        != payload_sha256(_mapping(artifact.get("raw_response"), "cutoff raw response"))
    ):
        raise ValueError("cutoff submission protocol/reviewer/raw hash drift。")
    identity = _identity_without(
        artifact,
        prefix=CUTOFF_SUBMISSION_IDENTITY_PREFIX,
        omitted={"artifact_id", "submission_identity"},
    )
    if artifact.get("submission_identity") != identity or artifact.get(
        "artifact_id"
    ) != _artifact_id("srtp_rcp_cutoff_submission", identity):
        raise ValueError("cutoff submission identity drift。")
    return {
        "artifact_id": artifact["artifact_id"],
        "submission_identity": identity,
        "sha256": payload_sha256(artifact),
        "reviewer_slot": reviewer,
        "topic_id": artifact.get("topic", {}).get("topic_id"),
        "tie_group_canonical_entity_ids": tuple(
            _strings(
                artifact.get("tie_group_canonical_entity_ids"),
                "cutoff submission tie group",
            )
        ),
        "slots_required": artifact.get("slots_required"),
        "is_fixture": artifact.get("is_fixture"),
    }


def _validate_human_judgement(
    judgement: Mapping[str, Any],
    *,
    task: Mapping[str, Any],
) -> dict[str, Any]:
    row = _mapping(dict(judgement), "human judgement")
    _exact(
        row,
        {
            "candidate_id",
            "relevance",
            "boundary",
            "evidence_sufficiency",
            "evidence_spans",
            "short_reason",
        },
        "human judgement",
    )
    if row["candidate_id"] != task["candidate"]["candidate_id"]:
        raise ValueError("human judgement wrong opaque candidate ID。")
    relevance = row["relevance"]
    if relevance != "defer" and (
        isinstance(relevance, bool) or relevance not in {0, 1, 2}
    ):
        raise ValueError("human relevance 必须是 0/1/2/defer。")
    boundary = _mapping(row["boundary"], "human boundary")
    _exact(boundary, set(BOUNDARY_DIMENSIONS), "human boundary")
    if any(value not in BOUNDARY_VALUES for value in boundary.values()):
        raise ValueError("human boundary value 非法。")
    sufficiency = _text(row["evidence_sufficiency"], "human evidence sufficiency")
    if sufficiency not in {"sufficient", "insufficient"}:
        raise ValueError("human evidence_sufficiency 非法。")
    minimum_spans = 0 if relevance == "defer" else 1
    _validate_evidence_spans(
        row["evidence_spans"], task=task, minimum=minimum_spans, maximum=2
    )
    reason = _text(row["short_reason"], "human short reason")
    if len(reason) > 240:
        raise ValueError("human short_reason 超过 240 characters。")
    uncertain = any(value in {"unclear", "not_stated"} for value in boundary.values())
    if relevance == "defer":
        if sufficiency != "insufficient":
            raise ValueError("defer 必须记录 evidence insufficient。")
    elif uncertain or sufficiency != "sufficient":
        raise ValueError("uncertain/insufficient human case 必须 defer。")
    if relevance == 2 and any(value != "match" for value in boundary.values()):
        raise ValueError("human relevance=2 要求四维 match。")
    if relevance == 0 and "mismatch" not in set(boundary.values()):
        raise ValueError("human relevance=0 必须有明确 hard mismatch dimension。")
    return {
        "candidate_id": row["candidate_id"],
        "relevance": relevance,
        "boundary": copy.deepcopy(boundary),
        "evidence_sufficiency": sufficiency,
        "evidence_spans": copy.deepcopy(row["evidence_spans"]),
        "short_reason": reason,
    }


def import_human_submission(
    response: Mapping[str, Any],
    *,
    task_package: Mapping[str, Any],
    mapping: Mapping[str, Any],
    imported_at: str,
    git_revision: str,
    _skip_validation: bool = False,
) -> dict[str, Any]:
    form = _mapping(dict(response), "human response")
    _exact(
        form,
        {
            "schema_version",
            "artifact_type",
            "protocol_id",
            "task_package_artifact_id",
            "task_package_identity",
            "reviewer_slot",
            "stage",
            "status",
            "reviewer_id",
            "judgements",
            "timing",
            "external_lookup",
            "independent_submission_acknowledged",
            "submitted_at",
        },
        "human response",
    )
    if (
        form["schema_version"] != RCP_SCHEMA_VERSION
        or form["artifact_type"] != "srtp_rcp_human_review_response"
        or form["protocol_id"] != RCP_PROTOCOL_ID
        or form["status"] != "completed"
    ):
        raise ValueError("human response protocol/status drift。")
    if (
        form["task_package_artifact_id"] != task_package["artifact_id"]
        or form["task_package_identity"] != task_package["package_identity"]
        or form["reviewer_slot"] != task_package["reviewer_slot"]
        or form["stage"] != task_package["stage"]
    ):
        raise ValueError("human response task/reviewer/stage binding drift。")
    reviewer_id = _text(form["reviewer_id"], "human reviewer_id")
    _bool(form["external_lookup"], "human external_lookup", expected=False)
    _bool(
        form["independent_submission_acknowledged"],
        "independent submission acknowledgement",
        expected=True,
    )
    _datetime(form["submitted_at"], "human submitted_at")
    timing = _mapping(form["timing"], "human timing")
    _exact(timing, {"started_at", "completed_at", "elapsed_minutes"}, "human timing")
    elapsed = timing["elapsed_minutes"]
    if (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(float(elapsed))
        or float(elapsed) <= 0
    ):
        raise ValueError("human elapsed_minutes 必须是 >0 的有限数值。")
    if timing["started_at"] or timing["completed_at"]:
        started = _datetime(timing["started_at"], "human started_at")
        completed = _datetime(timing["completed_at"], "human completed_at")
        if datetime.fromisoformat(
            completed.replace("Z", "+00:00")
        ) < datetime.fromisoformat(started.replace("Z", "+00:00")):
            raise ValueError("human completed_at 早于 started_at。")
    tasks = {task["candidate"]["candidate_id"]: task for task in task_package["tasks"]}
    map_by_candidate = {row["candidate_id"]: row for row in mapping["candidate_map"]}
    if set(tasks) != set(map_by_candidate):
        raise ValueError("human task/map roster drift。")
    raw_rows = _list(form["judgements"], "human judgements")
    if len(raw_rows) != len(tasks):
        raise ValueError("human response 必须精确覆盖 task roster。")
    by_candidate: dict[str, dict[str, Any]] = {}
    for raw in raw_rows:
        candidate_id = _text(
            _mapping(raw, "human judgement").get("candidate_id"),
            "human candidate_id",
        )
        if candidate_id in by_candidate or candidate_id not in tasks:
            raise ValueError("human response duplicate/unknown candidate ID。")
        by_candidate[candidate_id] = _validate_human_judgement(
            raw, task=tasks[candidate_id]
        )
    if set(by_candidate) != set(tasks):
        raise ValueError("human response candidate coverage drift。")
    canonical_records = []
    for task in task_package["tasks"]:
        candidate_id = task["candidate"]["candidate_id"]
        canonical_records.append(
            {
                "canonical_entity_id": map_by_candidate[candidate_id][
                    "canonical_entity_id"
                ],
                **copy.deepcopy(by_candidate[candidate_id]),
            }
        )
    imported = _datetime(imported_at, "human import time")
    payload: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_human_review_submission",
        "artifact_id": "pending",
        "submission_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "reviewer_slot": form["reviewer_slot"],
        "reviewer_id": reviewer_id,
        "stage": form["stage"],
        "topic": copy.deepcopy(task_package["topic"]),
        "task_package": _artifact_reference(task_package),
        "private_map_sha256": payload_sha256(mapping),
        "raw_response": copy.deepcopy(form),
        "raw_response_sha256": payload_sha256(form),
        "canonical_records": canonical_records,
        "external_lookup": False,
        "independent_submission_acknowledged": True,
        "imported_at": imported,
        "is_fixture": task_package["is_fixture"],
        "provenance": {
            "created_by": "src.pilot_reference_review",
            "git_revision": _git_revision(git_revision, "human import git_revision"),
        },
    }
    identity = _identity_without(
        payload,
        prefix=HUMAN_SUBMISSION_IDENTITY_PREFIX,
        omitted={"artifact_id", "submission_identity"},
    )
    payload["submission_identity"] = identity
    payload["artifact_id"] = _artifact_id("srtp_rcp_human_submission", identity)
    if not _skip_validation:
        validate_human_submission(payload, task_package=task_package, mapping=mapping)
    return payload


def validate_human_submission(
    submission: Mapping[str, Any],
    *,
    task_package: Mapping[str, Any],
    mapping: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = _mapping(dict(submission), "human submission")
    reconstructed = import_human_submission(
        artifact.get("raw_response"),
        task_package=task_package,
        mapping=mapping,
        imported_at=artifact.get("imported_at"),
        git_revision=_mapping(artifact.get("provenance"), "human provenance").get(
            "git_revision"
        ),
        _skip_validation=True,
    )
    if artifact != reconstructed:
        raise ValueError("human submission immutable identity/content drift。")
    return {
        "artifact_id": artifact["artifact_id"],
        "submission_identity": artifact["submission_identity"],
        "sha256": payload_sha256(artifact),
        "reviewer_slot": artifact["reviewer_slot"],
        "stage": artifact["stage"],
        "topic_id": artifact["topic"]["topic_id"],
        "candidate_count": len(artifact["canonical_records"]),
        "is_fixture": artifact["is_fixture"],
    }


def _records_by_canonical(submission: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["canonical_entity_id"]: row
        for row in _list(submission.get("canonical_records"), "canonical records")
    }


def _validate_submission_identity_and_scope(
    submission: Mapping[str, Any],
    *,
    aggregation: Mapping[str, Any],
    reviewer_slot: str,
    allowed_stages: set[str],
) -> dict[str, dict[str, Any]]:
    artifact = _mapping(dict(submission), "human submission")
    if (
        artifact.get("artifact_type") != "srtp_rcp_human_review_submission"
        or artifact.get("protocol_id") != RCP_PROTOCOL_ID
        or artifact.get("reviewer_slot") != reviewer_slot
        or artifact.get("stage") not in allowed_stages
        or artifact.get("topic", {}).get("topic_id")
        != aggregation.get("topic", {}).get("topic_id")
        or artifact.get("is_fixture") != aggregation.get("is_fixture")
    ):
        raise ValueError("human submission reviewer/stage/topic/fixture scope drift。")
    identity = _identity_without(
        artifact,
        prefix=HUMAN_SUBMISSION_IDENTITY_PREFIX,
        omitted={"artifact_id", "submission_identity"},
    )
    if (
        artifact.get("submission_identity") != identity
        or artifact.get("artifact_id")
        != _artifact_id("srtp_rcp_human_submission", identity)
        or artifact.get("raw_response_sha256")
        != payload_sha256(_mapping(artifact.get("raw_response"), "human raw response"))
    ):
        raise ValueError("human submission identity/raw-response hash drift。")
    records = _records_by_canonical(artifact)
    if len(records) != len(artifact.get("canonical_records", [])):
        raise ValueError("human submission canonical candidate duplicate。")
    known = {row["canonical_entity_id"] for row in aggregation["judgement_matrix"]}
    if not set(records).issubset(known):
        raise ValueError("human submission 包含 U80/aggregation 外 candidate。")
    return records


def _essential_boundary_conflict(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> bool:
    return any(
        {left["boundary"][dimension], right["boundary"][dimension]}
        == {"match", "mismatch"}
        for dimension in BOUNDARY_DIMENSIONS
    )


def compute_h2_triggers(
    aggregation: Mapping[str, Any],
    r1_h1: Mapping[str, Any],
    r2_h1: Mapping[str, Any],
    *,
    cutoff_frontier_ids: Sequence[str] = (),
) -> dict[str, list[str]]:
    r1 = _records_by_canonical(r1_h1)
    r2 = _records_by_canonical(r2_h1)
    if set(r1) != set(r2):
        raise ValueError("R1/R2 H1 candidate roster drift。")
    matrix = {
        row["canonical_entity_id"]: row for row in aggregation["judgement_matrix"]
    }
    frontier = set(cutoff_frontier_ids)
    triggers: dict[str, list[str]] = {}
    for candidate_id in r1:
        reasons: list[str] = []
        left = r1[candidate_id]
        right = r2[candidate_id]
        if left["relevance"] != right["relevance"]:
            reasons.append("r1_r2_h1_label_difference")
        if "defer" in {left["relevance"], right["relevance"]}:
            reasons.append("human_defer")
        if _essential_boundary_conflict(left, right):
            reasons.append("essential_boundary_conflict")
        core_label = matrix[candidate_id]["core_unanimous_label"]
        if (
            left["relevance"] == right["relevance"]
            and isinstance(left["relevance"], int)
            and isinstance(core_label, int)
            and abs(left["relevance"] - core_label) == 2
        ):
            reasons.append("human_consensus_vs_core_unanimous_two_level_gap")
        if candidate_id in frontier:
            reasons.append("cutoff_frontier_dispute")
        if reasons:
            triggers[candidate_id] = sorted(set(reasons))
    return triggers


def build_anonymized_h2_evidence_packet(
    aggregation: Mapping[str, Any],
    *,
    r1_h1: Mapping[str, Any],
    r2_h1: Mapping[str, Any],
    cutoff_frontier_ids: Sequence[str] = (),
    created_at: str,
    git_revision: str,
    _skip_validation: bool = False,
) -> dict[str, Any]:
    _validate_submission_identity_and_scope(
        r1_h1,
        aggregation=aggregation,
        reviewer_slot="r1",
        allowed_stages={"h1"},
    )
    _validate_submission_identity_and_scope(
        r2_h1,
        aggregation=aggregation,
        reviewer_slot="r2",
        allowed_stages={"h1"},
    )
    frontier = _strings(list(cutoff_frontier_ids), "H2 cutoff frontier IDs")
    trigger_reasons = compute_h2_triggers(
        aggregation,
        r1_h1,
        r2_h1,
        cutoff_frontier_ids=frontier,
    )
    matrix = {
        row["canonical_entity_id"]: row for row in aggregation["judgement_matrix"]
    }
    if not trigger_reasons:
        raise ValueError("H2 evidence packet requires at least one protocol trigger。")
    cases: list[dict[str, Any]] = []
    for candidate_id in sorted(trigger_reasons):
        if candidate_id not in matrix:
            raise ValueError("H2 trigger candidate 不属于 aggregation。")
        raw_cards: dict[tuple[Any, ...], dict[str, Any]] = {}
        for outcome in matrix[candidate_id]["core"] + matrix[candidate_id]["sentinels"]:
            if outcome["status"] != "valid" or outcome["boundary"] is None:
                continue
            criteria = [
                f"{dimension}:{outcome['boundary'][dimension]}"
                for dimension in BOUNDARY_DIMENSIONS
            ]
            for span in outcome["evidence_spans"]:
                key = (
                    span["field"],
                    span["start_char"],
                    span["end_char"],
                    span["text"],
                    span["content_sha256"],
                )
                card = raw_cards.setdefault(
                    key,
                    {
                        "field": span["field"],
                        "start_char": span["start_char"],
                        "end_char": span["end_char"],
                        "text": span["text"],
                        "content_sha256": span["content_sha256"],
                        "boundary_criteria": set(),
                        "short_verifiable_claim": "Exact input span for the listed boundary criteria.",
                    },
                )
                card["boundary_criteria"].update(criteria)
        cards: list[dict[str, Any]] = []
        for key, raw in raw_cards.items():
            card = {**raw, "boundary_criteria": sorted(raw["boundary_criteria"])}
            card_identity = deterministic_identity(
                "srtp-rcp-h2-card", {"candidate_id": candidate_id, **card}
            )
            card["card_id"] = f"evidence_{card_identity.rsplit(':', 1)[-1][:16]}"
            card["order_key_sha256"] = hashlib.sha256(
                "|".join(
                    [
                        "srtp-rcp-v0.3-h2-card-order-v1",
                        candidate_id,
                        card["card_id"],
                    ]
                ).encode("utf-8")
            ).hexdigest()
            cards.append(card)
        cards.sort(key=lambda card: (card["order_key_sha256"], card["card_id"]))
        cases.append(
            {
                "canonical_entity_id": candidate_id,
                "trigger_reasons": sorted(set(trigger_reasons[candidate_id])),
                "cards": cards,
            }
        )
    payload: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_anonymized_h2_evidence_packet",
        "artifact_id": "pending",
        "packet_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "aggregation": _artifact_reference(aggregation),
        "topic": copy.deepcopy(aggregation["topic"]),
        "trigger_source_submissions": [
            {
                "artifact_id": submission["artifact_id"],
                "submission_identity": submission["submission_identity"],
                "sha256": payload_sha256(submission),
                "reviewer_slot": submission["reviewer_slot"],
                "stage": submission["stage"],
            }
            for submission in (r1_h1, r2_h1)
        ],
        "cutoff_frontier_canonical_entity_ids": frontier,
        "anonymization_policy": {
            "model_identity_visible": False,
            "model_family_visible": False,
            "vote_count_visible": False,
            "majority_visible": False,
            "numeric_confidence_visible": False,
            "candidate_rank_visible": False,
            "full_model_reason_visible": False,
            "exact_spans_deduplicated": True,
        },
        "cases": cases,
        "created_at": _datetime(created_at, "H2 packet created_at"),
        "is_fixture": aggregation["is_fixture"],
        "provenance": {
            "created_by": "src.pilot_reference_review",
            "git_revision": _git_revision(git_revision, "H2 packet git_revision"),
        },
    }
    identity = _identity_without(
        payload,
        prefix=H2_IDENTITY_PREFIX,
        omitted={"artifact_id", "packet_identity"},
    )
    payload["packet_identity"] = identity
    payload["artifact_id"] = _artifact_id("srtp_rcp_h2_packet", identity)
    forbidden = _all_keys(payload) & {
        "provider",
        "model_family",
        "roster_entry_id",
        "core_labels",
        "sentinel_labels",
        "vote",
        "votes",
        "majority",
        "numeric_confidence",
        "rank",
        "full_model_reason",
    }
    if forbidden:
        raise ValueError("H2 evidence packet anonymization leak。")
    if not _skip_validation:
        validate_anonymized_h2_evidence_packet(
            payload,
            aggregation=aggregation,
            r1_h1=r1_h1,
            r2_h1=r2_h1,
        )
    return payload


def validate_anonymized_h2_evidence_packet(
    packet: Mapping[str, Any],
    *,
    aggregation: Mapping[str, Any],
    r1_h1: Mapping[str, Any],
    r2_h1: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = _mapping(dict(packet), "H2 evidence packet")
    provenance = _mapping(artifact.get("provenance"), "H2 packet provenance")
    reconstructed = build_anonymized_h2_evidence_packet(
        aggregation,
        r1_h1=r1_h1,
        r2_h1=r2_h1,
        cutoff_frontier_ids=artifact.get("cutoff_frontier_canonical_entity_ids", []),
        created_at=artifact.get("created_at"),
        git_revision=provenance.get("git_revision"),
        _skip_validation=True,
    )
    if artifact != reconstructed:
        raise ValueError("H2 evidence packet deterministic trigger/content drift。")
    return {
        "artifact_id": artifact["artifact_id"],
        "packet_identity": artifact["packet_identity"],
        "sha256": payload_sha256(artifact),
        "candidate_count": len(artifact["cases"]),
        "is_fixture": artifact["is_fixture"],
    }


def _overlay_records(
    base: Mapping[str, Any], override: Mapping[str, Any] | None
) -> dict[str, dict[str, Any]]:
    result = _records_by_canonical(base)
    if override is not None:
        result.update(_records_by_canonical(override))
    return result


def compute_r3_triggers(
    aggregation: Mapping[str, Any],
    r1_h1: Mapping[str, Any],
    r2_h1: Mapping[str, Any],
    *,
    r1_h2: Mapping[str, Any] | None = None,
    r2_h2: Mapping[str, Any] | None = None,
    cutoff_tie_ids: Sequence[str] = (),
) -> dict[str, list[str]]:
    r1 = _overlay_records(r1_h1, r1_h2)
    r2 = _overlay_records(r2_h1, r2_h2)
    if set(r1) != set(r2):
        raise ValueError("R1/R2 latest human roster drift。")
    matrix = {
        row["canonical_entity_id"]: row for row in aggregation["judgement_matrix"]
    }
    tie = set(cutoff_tie_ids)
    triggers: dict[str, list[str]] = {}
    for candidate_id in r1:
        left = r1[candidate_id]
        right = r2[candidate_id]
        reasons: list[str] = []
        if left["relevance"] != right["relevance"]:
            reasons.append("r1_r2_latest_label_difference")
        if "defer" in {left["relevance"], right["relevance"]}:
            reasons.append("persistent_human_defer")
        if _essential_boundary_conflict(left, right):
            reasons.append("essential_dimension_match_vs_mismatch")
        core_label = matrix[candidate_id]["core_unanimous_label"]
        if (
            left["relevance"] == right["relevance"]
            and isinstance(left["relevance"], int)
            and isinstance(core_label, int)
            and abs(left["relevance"] - core_label) == 2
        ):
            reasons.append("human_final_vs_core_unanimous_two_level_gap")
        if candidate_id in tie:
            reasons.append("top8_exact_cutoff_tie")
        if reasons:
            triggers[candidate_id] = sorted(set(reasons))
    return triggers


def build_final_human_labels(
    aggregation: Mapping[str, Any],
    *,
    r1_h1: Mapping[str, Any],
    r2_h1: Mapping[str, Any],
    r1_h2: Mapping[str, Any] | None = None,
    r2_h2: Mapping[str, Any] | None = None,
    r3: Mapping[str, Any] | None = None,
    r3_h2: Mapping[str, Any] | None = None,
    required_candidate_ids: Sequence[str],
    created_at: str,
    git_revision: str,
    _skip_validation: bool = False,
) -> dict[str, Any]:
    _validate_submission_identity_and_scope(
        r1_h1,
        aggregation=aggregation,
        reviewer_slot="r1",
        allowed_stages={"h1"},
    )
    _validate_submission_identity_and_scope(
        r2_h1,
        aggregation=aggregation,
        reviewer_slot="r2",
        allowed_stages={"h1"},
    )
    if r1_h2 is not None:
        _validate_submission_identity_and_scope(
            r1_h2,
            aggregation=aggregation,
            reviewer_slot="r1",
            allowed_stages={"h2"},
        )
    if r2_h2 is not None:
        _validate_submission_identity_and_scope(
            r2_h2,
            aggregation=aggregation,
            reviewer_slot="r2",
            allowed_stages={"h2"},
        )
    if r3 is not None:
        _validate_submission_identity_and_scope(
            r3,
            aggregation=aggregation,
            reviewer_slot="r3",
            allowed_stages={"r3_h1"},
        )
    if r3_h2 is not None:
        if r3 is None:
            raise ValueError("R3 H2 finalization 缺少 prior blind R3 H1 submission。")
        r3_h1_records = _records_by_canonical(r3)
        r3_h2_records = _validate_submission_identity_and_scope(
            r3_h2,
            aggregation=aggregation,
            reviewer_slot="r3",
            allowed_stages={"r3_h2"},
        )
        if set(r3_h2_records) != set(r3_h1_records):
            raise ValueError("R3 H2/H1 candidate roster drift。")
    r1 = _overlay_records(r1_h1, r1_h2)
    r2 = _overlay_records(r2_h1, r2_h2)
    r3_records = _overlay_records(r3, r3_h2) if r3 is not None else {}
    required = _strings(list(required_candidate_ids), "required human label IDs")
    if not set(required).issubset(set(r1)) or not set(required).issubset(set(r2)):
        raise ValueError("final human labels 缺少 R1/R2 coverage。")
    matrix = {
        row["canonical_entity_id"]: row for row in aggregation["judgement_matrix"]
    }
    final_rows = []
    for candidate_id in required:
        left = r1[candidate_id]["relevance"]
        right = r2[candidate_id]["relevance"]
        if left == right and isinstance(left, int):
            final_label = left
            rule = "r1_r2_agreement"
            participant_labels = {"r1": left, "r2": right}
        else:
            third = r3_records.get(candidate_id, {}).get("relevance")
            if not all(isinstance(value, int) for value in (left, right, third)):
                raise ValueError(
                    "reference_not_freezable：R1/R2 disagreement/defer 后缺少三个 numeric labels。"
                )
            final_label = int(statistics.median([left, right, third]))
            rule = "three_numeric_label_median"
            participant_labels = {"r1": left, "r2": right, "r3": third}
        final_rows.append(
            {
                "canonical_entity_id": candidate_id,
                "final_human_relevance": final_label,
                "resolution_rule": rule,
                "participant_labels": participant_labels,
                "n_core_label_2": matrix[candidate_id]["n_core_label_2"],
                "n_core_label_ge_1": matrix[candidate_id]["n_core_label_ge_1"],
            }
        )
    source_submissions = [r1_h1, r2_h1]
    source_submissions.extend(
        submission for submission in (r1_h2, r2_h2, r3, r3_h2) if submission is not None
    )
    payload: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_final_human_labels",
        "artifact_id": "pending",
        "human_label_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "topic": copy.deepcopy(aggregation["topic"]),
        "aggregation": _artifact_reference(aggregation),
        "source_submissions": [
            {
                "artifact_id": submission["artifact_id"],
                "submission_identity": submission["submission_identity"],
                "sha256": payload_sha256(submission),
                "reviewer_slot": submission["reviewer_slot"],
                "stage": submission["stage"],
            }
            for submission in source_submissions
        ],
        "candidate_count": len(final_rows),
        "labels": final_rows,
        "created_at": _datetime(created_at, "final human labels created_at"),
        "is_fixture": aggregation["is_fixture"],
        "provenance": {
            "created_by": "src.pilot_reference_review",
            "git_revision": _git_revision(git_revision, "human labels git_revision"),
        },
    }
    identity = _identity_without(
        payload,
        prefix=HUMAN_LABEL_IDENTITY_PREFIX,
        omitted={"artifact_id", "human_label_identity"},
    )
    payload["human_label_identity"] = identity
    payload["artifact_id"] = _artifact_id("srtp_rcp_human_labels", identity)
    if not _skip_validation:
        validate_final_human_labels(
            payload,
            aggregation=aggregation,
            r1_h1=r1_h1,
            r2_h1=r2_h1,
            r1_h2=r1_h2,
            r2_h2=r2_h2,
            r3=r3,
            r3_h2=r3_h2,
            required_candidate_ids=required,
        )
    return payload


def validate_final_human_labels(
    final_human_labels: Mapping[str, Any],
    *,
    aggregation: Mapping[str, Any],
    r1_h1: Mapping[str, Any],
    r2_h1: Mapping[str, Any],
    r1_h2: Mapping[str, Any] | None = None,
    r2_h2: Mapping[str, Any] | None = None,
    r3: Mapping[str, Any] | None = None,
    r3_h2: Mapping[str, Any] | None = None,
    required_candidate_ids: Sequence[str],
) -> dict[str, Any]:
    artifact = _mapping(dict(final_human_labels), "final human labels")
    provenance = _mapping(artifact.get("provenance"), "human labels provenance")
    reconstructed = build_final_human_labels(
        aggregation,
        r1_h1=r1_h1,
        r2_h1=r2_h1,
        r1_h2=r1_h2,
        r2_h2=r2_h2,
        r3=r3,
        r3_h2=r3_h2,
        required_candidate_ids=required_candidate_ids,
        created_at=artifact.get("created_at"),
        git_revision=provenance.get("git_revision"),
        _skip_validation=True,
    )
    if artifact != reconstructed:
        raise ValueError("final human labels deterministic reconstruction drift。")
    return {
        "artifact_id": artifact["artifact_id"],
        "human_label_identity": artifact["human_label_identity"],
        "sha256": payload_sha256(artifact),
        "candidate_count": artifact["candidate_count"],
        "is_fixture": artifact["is_fixture"],
    }


def validate_final_human_labels_identity(
    final_human_labels: Mapping[str, Any],
    *,
    aggregation: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = _mapping(dict(final_human_labels), "final human labels")
    if (
        artifact.get("artifact_type") != "srtp_rcp_final_human_labels"
        or artifact.get("protocol_id") != RCP_PROTOCOL_ID
        or artifact.get("aggregation") != _artifact_reference(aggregation)
        or artifact.get("topic") != aggregation.get("topic")
        or artifact.get("is_fixture") != aggregation.get("is_fixture")
    ):
        raise ValueError("final human labels protocol/aggregation scope drift。")
    identity = _identity_without(
        artifact,
        prefix=HUMAN_LABEL_IDENTITY_PREFIX,
        omitted={"artifact_id", "human_label_identity"},
    )
    if artifact.get("human_label_identity") != identity or artifact.get(
        "artifact_id"
    ) != _artifact_id("srtp_rcp_human_labels", identity):
        raise ValueError("final human labels identity drift。")
    records = _list(artifact.get("labels"), "final human label records")
    candidate_ids = [row.get("canonical_entity_id") for row in records]
    if artifact.get("candidate_count") != len(records) or len(candidate_ids) != len(
        set(candidate_ids)
    ):
        raise ValueError("final human labels count/duplicate drift。")
    matrix = {
        row["canonical_entity_id"]: row for row in aggregation["judgement_matrix"]
    }
    if not set(candidate_ids).issubset(set(matrix)):
        raise ValueError("final human labels contain non-U80 candidate。")
    for row in records:
        candidate_id = row["canonical_entity_id"]
        if (
            isinstance(row.get("final_human_relevance"), bool)
            or row.get("final_human_relevance") not in {0, 1, 2}
            or row.get("n_core_label_2") != matrix[candidate_id]["n_core_label_2"]
            or row.get("n_core_label_ge_1") != matrix[candidate_id]["n_core_label_ge_1"]
        ):
            raise ValueError("final human label/relevance/Core diagnostics drift。")
    return {
        "artifact_id": artifact["artifact_id"],
        "human_label_identity": identity,
        "sha256": payload_sha256(artifact),
        "candidate_count": len(records),
        "is_fixture": artifact["is_fixture"],
    }


__all__ = [
    "build_anonymized_h2_evidence_packet",
    "build_blank_human_response",
    "build_blank_cutoff_response",
    "build_cutoff_task_package",
    "build_final_human_labels",
    "build_human_task_package",
    "compute_h2_triggers",
    "compute_r3_triggers",
    "derive_h1_candidate_ids",
    "export_cutoff_task_package",
    "export_human_task_package",
    "import_cutoff_submission",
    "import_human_submission",
    "render_cutoff_review_instructions",
    "render_human_review_instructions",
    "validate_cutoff_submission",
    "validate_cutoff_submission_identity",
    "validate_cutoff_task_package",
    "validate_human_submission",
    "validate_human_task_package",
    "validate_anonymized_h2_evidence_packet",
    "validate_final_human_labels",
    "validate_final_human_labels_identity",
]
