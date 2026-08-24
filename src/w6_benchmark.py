"""W6 Leader workflow for topic freeze, annotation review, and benchmark packages.

The public :mod:`src.w6_contracts` module remains the shared Bootstrap contract.
This module composes those validators into the Issue #64 workflow without
weakening or changing the public contract.  It deliberately does not implement
formal ``approved`` promotion or hidden-label reveal.
"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.annotation_tasks import sha256_file
from src.w6_artifact_safety import ensure_output_separate_from_inputs
from src.w6_contracts import (
    BLIND_TASK_FORBIDDEN_KEYS,
    BLIND_VIEW_POLICY,
    PRIVATE_REASONING_KEYS,
    W6_SCHEMA_VERSION,
    _find_forbidden_keys,
    _validate_annotation_provenance,
    canonical_json_sha256,
    compute_benchmark_identity,
    deterministic_identity,
    load_json_object,
    normalize_title,
    validate_annotation_results,
    validate_annotation_reviews,
    validate_annotation_task_map,
    validate_benchmark_manifest,
    validate_blind_annotation_tasks,
    validate_candidate_pool,
    validate_canonical_entities,
    validate_hidden_label_anchor,
    validate_retrieval_provenance,
    validate_source_records,
    validate_topic_set,
    validate_topic_split,
)


WORKFLOW_CONTRACT_NAME = "w6_benchmark_workflow"
WORKFLOW_CONTRACT_VERSION = "0.2-alpha"
PACKAGE_ARTIFACT_TYPE = "w6_benchmark_package"
ANNOTATION_PROTOCOL_ARTIFACT_TYPE = "w6_annotation_protocol"
REVIEW_PLAN_ARTIFACT_TYPE = "w6_annotation_review_plan"
TOPIC_RESEARCH_ARTIFACT_TYPE = "w6_topic_viability_research"
SECOND_ANNOTATION_ARTIFACT_TYPE = "w6_second_annotations"

BENCHMARK_INPUT_NAMES = (
    "topic_set",
    "retrieval_provenance",
    "source_records",
    "canonical_entities",
    "candidate_pool",
    "annotation_task_map",
    "annotation_tasks",
    "split_manifest",
    "annotation_results",
    "annotation_reviews",
    "hidden_label_anchor",
)
PACKAGE_ARTIFACT_NAMES = BENCHMARK_INPUT_NAMES + (
    "annotation_protocol",
    "second_annotation_results",
    "review_plan",
    "benchmark_manifest",
)
LOOKUP_STATUSES = frozenset({"not_needed", "completed", "insufficient", "failed"})
MANDATORY_REVIEW_TRIGGERS = frozenset(
    {
        "low_confidence",
        "nonempty_uncertainty",
        "evidence_insufficient",
        "boundary_case",
        "annotation_conflict",
        "missing_abstract",
        "random_high_confidence_qa",
    }
)


def validate_frozen_topic_roster(
    payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Validate a real frozen roster plus cross-topic/boundary invariants."""
    topics = validate_topic_set(payload)
    if payload["status"] != "frozen":
        raise ValueError("Issue #64 final topic set 必须 frozen。")
    if any(topic["lifecycle_status"] != "frozen" for topic in topics.values()):
        raise ValueError(
            "frozen topic set 中每个 topic lifecycle_status 都必须 frozen。"
        )

    questions: dict[str, str] = {}
    signatures: dict[tuple[str, ...], str] = {}
    query_texts: dict[str, str] = {}
    for topic_id, topic in topics.items():
        question_key = normalize_title(topic["research_question"])
        if question_key in questions:
            raise ValueError(
                f"near-duplicate research question：{questions[question_key]} / {topic_id}。"
            )
        questions[question_key] = topic_id
        signature = tuple(
            normalize_title(topic[field])
            for field in (
                "scientific_object",
                "data_modality",
                "target_task",
                "method_role",
            )
        )
        if signature in signatures:
            raise ValueError(
                f"duplicate topic coverage signature：{signatures[signature]} / {topic_id}。"
            )
        signatures[signature] = topic_id

        scope_in = {normalize_title(value) for value in topic["scope_in"]}
        scope_out = {normalize_title(value) for value in topic["scope_out"]}
        boundaries = {normalize_title(value) for value in topic["boundary_cases"]}
        if scope_in & scope_out or scope_in & boundaries:
            raise ValueError(f"{topic_id} scope-in 与 scope-out/boundary 自相矛盾。")
        if any(not value for value in scope_in | scope_out | boundaries):
            raise ValueError(f"{topic_id} boundary statement 规范化后为空。")
        for variant in topic["acquisition_query_variants"]:
            if variant["status"] != "frozen":
                raise ValueError(f"{topic_id} acquisition query 尚未 frozen。")
            query_key = normalize_title(variant["query_text"])
            if query_key in query_texts:
                raise ValueError(
                    f"duplicate acquisition query：{query_texts[query_key]} / {topic_id}。"
                )
            query_texts[query_key] = topic_id
    return topics


def validate_topic_research_artifact(
    payload: dict[str, Any],
    *,
    topics: Mapping[str, dict[str, Any]],
    topic_set_created_at: str,
    split: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Validate candidate research, public viability evidence, and freeze decisions."""
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "status",
            "is_fixture",
            "created_at",
            "selection_frozen_before_labels",
            "criteria",
            "candidates",
            "viability_evidence",
            "freeze_decision",
            "split_decision",
            "provenance",
        },
        "topic research artifact",
    )
    _require_header(payload, TOPIC_RESEARCH_ARTIFACT_TYPE)
    if (
        payload["status"] != "frozen"
        or payload["selection_frozen_before_labels"] is not True
    ):
        raise ValueError("Topic research 必须在 labels 前 frozen。")
    _require_datetime(payload["created_at"], "topic research created_at")
    criteria = _require_string_list(
        payload["criteria"], "topic criteria", nonempty=True
    )
    required_criteria = {
        "scientific_object",
        "data_modality",
        "target_task",
        "method_role",
        "scope_in_out",
        "hard_negative_potential",
        "literature_viability",
        "query_variant_feasibility",
        "w4_w5_overlap",
        "cross_topic_overlap",
    }
    if set(criteria) != required_criteria:
        raise ValueError("Topic viability/diversity criteria roster 不完整。")

    candidates: dict[str, dict[str, Any]] = {}
    for raw in _require_nonempty_list(payload["candidates"], "topic candidates"):
        candidate = _require_mapping(raw, "topic candidate")
        _require_exact_fields(
            candidate,
            {
                "candidate_id",
                "title",
                "scientific_object",
                "data_modality",
                "target_task",
                "method_role",
                "scope_summary",
                "hard_negative_potential",
                "query_variant_feasibility",
                "overlap_risk",
                "decision",
                "decision_reason",
                "final_topic_id",
            },
            "topic candidate",
        )
        candidate_id = _require_id(candidate["candidate_id"], "candidate_id")
        if candidate_id in candidates:
            raise ValueError(f"duplicate topic candidate：{candidate_id}。")
        for field in (
            "title",
            "scientific_object",
            "data_modality",
            "target_task",
            "method_role",
            "scope_summary",
            "hard_negative_potential",
            "query_variant_feasibility",
            "overlap_risk",
            "decision_reason",
        ):
            _require_nonempty_string(candidate[field], f"{candidate_id}.{field}")
        if candidate["decision"] not in {"selected", "excluded"}:
            raise ValueError(f"{candidate_id}.decision 非法。")
        final_topic_id = candidate["final_topic_id"]
        if candidate["decision"] == "selected":
            _require_id(final_topic_id, f"{candidate_id}.final_topic_id")
        elif final_topic_id is not None:
            raise ValueError("excluded candidate 的 final_topic_id 必须为 null。")
        candidates[candidate_id] = candidate

    evidence_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in _require_nonempty_list(
        payload["viability_evidence"], "viability evidence"
    ):
        evidence = _require_mapping(raw, "viability evidence")
        _require_exact_fields(
            evidence,
            {
                "candidate_id",
                "provider",
                "checked_at",
                "query",
                "filters",
                "hit_count",
                "query_url",
                "representative_works",
                "interpretation",
            },
            "viability evidence",
        )
        candidate_id = evidence["candidate_id"]
        if candidate_id not in candidates:
            raise ValueError(
                f"viability evidence 引用 unknown candidate：{candidate_id}。"
            )
        for field in ("provider", "query", "filters", "query_url", "interpretation"):
            _require_nonempty_string(evidence[field], f"viability.{field}")
        _require_datetime(evidence["checked_at"], "viability checked_at")
        count = evidence["hit_count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("viability hit_count 必须是非负整数。")
        works = _require_list(evidence["representative_works"], "representative works")
        for work in works:
            work_map = _require_mapping(work, "representative work")
            _require_exact_fields(
                work_map, {"openalex_id", "title", "year", "doi"}, "representative work"
            )
            _require_nonempty_string(
                work_map["openalex_id"], "representative openalex_id"
            )
            _require_nonempty_string(work_map["title"], "representative title")
            if isinstance(work_map["year"], bool) or not isinstance(
                work_map["year"], int
            ):
                raise ValueError("representative work year 必须是 integer。")
            if work_map["doi"] is not None:
                _require_nonempty_string(work_map["doi"], "representative DOI")
        evidence_by_candidate[candidate_id].append(evidence)
    if set(evidence_by_candidate) != set(candidates):
        raise ValueError("每个 candidate 必须有公开 viability query/count evidence。")

    freeze = _require_mapping(payload["freeze_decision"], "freeze decision")
    _require_exact_fields(
        freeze,
        {
            "selected_candidate_ids",
            "excluded_candidate_ids",
            "final_topic_ids",
            "frozen_at",
            "decision_rule",
        },
        "freeze decision",
    )
    selected = set(
        _require_string_list(
            freeze["selected_candidate_ids"], "selected candidates", nonempty=True
        )
    )
    excluded = set(
        _require_string_list(
            freeze["excluded_candidate_ids"], "excluded candidates", nonempty=True
        )
    )
    if selected & excluded or selected | excluded != set(candidates):
        raise ValueError("candidate selection 必须无交叠且完整覆盖 candidate roster。")
    expected_selected = {
        candidate_id
        for candidate_id, candidate in candidates.items()
        if candidate["decision"] == "selected"
    }
    if selected != expected_selected:
        raise ValueError("freeze selected roster 与 candidate decisions 不一致。")
    final_topic_ids = set(
        _require_string_list(
            freeze["final_topic_ids"], "final topic IDs", nonempty=True
        )
    )
    candidate_topic_ids = {
        candidate["final_topic_id"]
        for candidate in candidates.values()
        if candidate["decision"] == "selected"
    }
    if final_topic_ids != set(topics) or candidate_topic_ids != set(topics):
        raise ValueError("candidate → final Topic roster mapping 不闭合。")
    _require_datetime(freeze["frozen_at"], "topic freeze frozen_at")
    topic_freeze_time = _parse_datetime(freeze["frozen_at"])
    if any(
        _parse_datetime(evidence["checked_at"]) > topic_freeze_time
        for evidence_rows in evidence_by_candidate.values()
        for evidence in evidence_rows
    ):
        raise ValueError("viability checked_at 不得晚于 Topic research freeze。")
    if topic_freeze_time > _parse_datetime(topic_set_created_at):
        raise ValueError("Topic research freeze 不得晚于 Topic Set freeze。")
    _require_nonempty_string(freeze["decision_rule"], "topic freeze decision_rule")

    split_decision = _require_mapping(payload["split_decision"], "split decision")
    _require_exact_fields(
        split_decision,
        {
            "strategy",
            "alternatives_considered",
            "decision_rule",
            "seed",
            "frozen_before_labels",
            "dev_topic_ids",
            "hidden_test_topic_ids",
            "custodian_policy",
        },
        "split decision",
    )
    for field in ("strategy", "decision_rule", "seed", "custodian_policy"):
        _require_nonempty_string(split_decision[field], f"split_decision.{field}")
    _require_string_list(
        split_decision["alternatives_considered"], "split alternatives", nonempty=True
    )
    if split_decision["frozen_before_labels"] is not True:
        raise ValueError("split decision 必须在 labels 前冻结。")
    if split is not None:
        if (
            split_decision["dev_topic_ids"] != split["dev_topic_ids"]
            or split_decision["hidden_test_topic_ids"] != split["hidden_test_topic_ids"]
        ):
            raise ValueError(
                "research split decision 与 frozen split artifact 不一致。"
            )
    _validate_provenance(payload["provenance"], "topic research provenance")
    return candidates


def validate_topic_freeze_files(
    topic_set_path: str | Path,
    split_path: str | Path,
    *,
    research_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate the frozen real Topic roster, split hash, and optional research record."""
    topic_file = Path(topic_set_path).resolve()
    split_file = Path(split_path).resolve()
    topic_payload = load_json_object(topic_file, label="W6 frozen topic set")
    topics = validate_frozen_topic_roster(topic_payload)
    split_payload = load_json_object(split_file, label="W6 frozen topic split")
    split_sets = validate_topic_split(split_payload, topics=topics)
    expected_ref = {
        "artifact_id": topic_payload["artifact_id"],
        "sha256": sha256_file(topic_file),
    }
    if split_payload["topic_set"] != expected_ref:
        raise ValueError("topic split 未绑定实际 frozen Topic Set hash。")
    if _parse_datetime(split_payload["frozen_at"]) < _parse_datetime(
        topic_payload["created_at"]
    ):
        raise ValueError("topic split frozen_at 不得早于 Topic Set freeze。")
    research = None
    if research_path is not None:
        research = load_json_object(research_path, label="W6 topic research")
        validate_topic_research_artifact(
            research,
            topics=topics,
            topic_set_created_at=topic_payload["created_at"],
            split=split_payload,
        )
        if _parse_datetime(split_payload["frozen_at"]) < _parse_datetime(
            research["freeze_decision"]["frozen_at"]
        ):
            raise ValueError("split 必须发生在 Topic roster freeze 之后。")
    return {
        "topic_payload": topic_payload,
        "topics": topics,
        "split_payload": split_payload,
        "split_sets": split_sets,
        "research": research,
        "topic_sha256": expected_ref["sha256"],
        "split_sha256": sha256_file(split_file),
    }


def validate_annotation_protocol(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the preregistered blind AI-assisted annotation/review policy."""
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "status",
            "is_fixture",
            "version",
            "frozen_at",
            "frozen_before_annotations",
            "label_scheme",
            "blind_view",
            "evidence_policy",
            "primary_annotation",
            "review_policy",
            "adjudication_policy",
            "provenance",
        },
        "annotation protocol",
    )
    _require_header(payload, ANNOTATION_PROTOCOL_ARTIFACT_TYPE)
    if (
        payload["status"] != "frozen"
        or payload["frozen_before_annotations"] is not True
    ):
        raise ValueError("annotation/review protocol 必须在 labels 前 frozen。")
    _require_nonempty_string(payload["version"], "annotation protocol version")
    _require_datetime(payload["frozen_at"], "annotation protocol frozen_at")
    if payload["label_scheme"] != {
        "type": "graded_query_relevance",
        "allowed_values": [0, 1, 2],
        "version": "query_relevance_0_1_2_v1",
    }:
        raise ValueError(
            "annotation protocol 必须使用 W4-compatible 0/1/2 Query Relevance。"
        )

    blind = _require_mapping(payload["blind_view"], "blind view")
    _require_exact_fields(
        blind, {"view_policy", "visible_fields", "forbidden_signals"}, "blind view"
    )
    if blind["view_policy"] != BLIND_VIEW_POLICY:
        raise ValueError("annotation protocol blind view policy 与 Bootstrap 不一致。")
    visible = set(
        _require_string_list(
            blind["visible_fields"], "blind visible fields", nonempty=True
        )
    )
    if (
        not {
            "research_question",
            "scope_in",
            "scope_out",
            "boundary_cases",
            "title",
            "abstract",
            "public_paper_identity",
        }
        <= visible
    ):
        raise ValueError("blind annotation visible-field whitelist 不完整。")
    forbidden = set(
        _require_string_list(
            blind["forbidden_signals"], "blind forbidden signals", nonempty=True
        )
    )
    if not set(BLIND_TASK_FORBIDDEN_KEYS) <= forbidden:
        raise ValueError(
            "blind protocol 未覆盖 Bootstrap retrieval/ranking leakage keys。"
        )

    evidence = _require_mapping(payload["evidence_policy"], "evidence policy")
    _require_exact_fields(
        evidence,
        {
            "lookup_status_values",
            "source_priority",
            "required_result_fields",
            "private_reasoning_storage",
        },
        "evidence policy",
    )
    if set(evidence["lookup_status_values"]) != LOOKUP_STATUSES:
        raise ValueError("evidence lookup status vocabulary 不完整。")
    _require_string_list(
        evidence["source_priority"], "evidence source priority", nonempty=True
    )
    required_result_fields = set(
        _require_string_list(
            evidence["required_result_fields"],
            "evidence required fields",
            nonempty=True,
        )
    )
    if (
        not {
            "label",
            "confidence",
            "uncertainty",
            "evidence_source",
            "evidence_reference",
            "lookup_status",
            "justification_summary",
            "actor_type",
            "model_or_tool",
            "protocol_version",
            "timestamp",
            "review_status",
        }
        <= required_result_fields
    ):
        raise ValueError("annotation evidence/provenance required fields 不完整。")
    if evidence["private_reasoning_storage"] != "forbidden":
        raise ValueError("annotation protocol 不得保存 private chain-of-thought。")

    primary = _require_mapping(payload["primary_annotation"], "primary annotation")
    _require_exact_fields(
        primary,
        {"actor_types", "round", "independence_rule", "prompt_version"},
        "primary annotation",
    )
    if set(primary["actor_types"]) != {"ai_assistant", "human", "ai_assisted_human"}:
        raise ValueError("primary annotation actor provenance vocabulary 不完整。")
    if primary["round"] != "independent_primary":
        raise ValueError("primary annotation round 非法。")
    _require_nonempty_string(primary["independence_rule"], "primary independence_rule")
    _require_nonempty_string(primary["prompt_version"], "primary prompt_version")

    review = _require_mapping(payload["review_policy"], "review policy")
    _require_exact_fields(
        review,
        {
            "policy_id",
            "selection_frozen_before_labels",
            "mandatory_triggers",
            "second_annotation_fraction_per_topic",
            "second_annotation_seed",
            "random_high_confidence_qa_fraction",
            "random_qa_seed",
            "reviewer_independence_required",
            "ranking_signals_allowed",
        },
        "review policy",
    )
    _require_id(review["policy_id"], "review policy_id")
    if review["selection_frozen_before_labels"] is not True:
        raise ValueError("review selection policy 必须在 labels 前冻结。")
    if set(review["mandatory_triggers"]) != MANDATORY_REVIEW_TRIGGERS:
        raise ValueError("review mandatory triggers roster 不完整。")
    _require_fraction(
        review["second_annotation_fraction_per_topic"], "second annotation fraction"
    )
    _require_fraction(
        review["random_high_confidence_qa_fraction"], "random QA fraction"
    )
    _require_nonempty_string(review["second_annotation_seed"], "second annotation seed")
    _require_nonempty_string(review["random_qa_seed"], "random QA seed")
    if review["reviewer_independence_required"] is not True:
        raise ValueError("annotation review 必须由独立 reviewer 完成。")
    if review["ranking_signals_allowed"] is not False:
        raise ValueError("review selection 不得使用 ranking/retrieval signals。")

    adjudication = _require_mapping(
        payload["adjudication_policy"], "adjudication policy"
    )
    _require_exact_fields(
        adjudication,
        {
            "required_for_conflicts",
            "reviewer_types",
            "allowed_decisions",
            "preserve_primary_history",
            "required_fields",
        },
        "adjudication policy",
    )
    if (
        adjudication["required_for_conflicts"] is not True
        or adjudication["preserve_primary_history"] is not True
    ):
        raise ValueError("conflict adjudication 必须保留 primary judgement history。")
    if set(adjudication["reviewer_types"]) != {"human", "ai_assisted_human"}:
        raise ValueError("adjudication reviewer types 非法。")
    if set(adjudication["allowed_decisions"]) != {"approve", "modify"}:
        raise ValueError("adjudication decisions 非法。")
    if not {"reviewer_id", "final_label", "reviewed_at", "review_note"} <= set(
        adjudication["required_fields"]
    ):
        raise ValueError("adjudication required fields 不完整。")
    private_keys = _find_forbidden_keys(payload, PRIVATE_REASONING_KEYS)
    if private_keys:
        raise ValueError("annotation protocol 不得要求 private reasoning fields。")
    _validate_provenance(payload["provenance"], "annotation protocol provenance")
    return payload


def select_second_annotation_tasks(
    *,
    task_mappings: Mapping[str, dict[str, Any]],
    dev_topic_ids: Iterable[str],
    fraction_per_topic: float,
    seed: str,
) -> list[str]:
    """Preselect independent second annotations using task identity only."""
    _require_fraction(fraction_per_topic, "second annotation fraction")
    dev = set(dev_topic_ids)
    by_topic: dict[str, list[str]] = defaultdict(list)
    for task_id, mapping in task_mappings.items():
        if mapping["topic_id"] in dev:
            by_topic[mapping["topic_id"]].append(task_id)
    selected: list[str] = []
    for topic_id in sorted(by_topic):
        task_ids = by_topic[topic_id]
        count = (
            math.ceil(len(task_ids) * fraction_per_topic) if fraction_per_topic else 0
        )
        ranked = sorted(
            task_ids,
            key=lambda task_id: (
                canonical_json_sha256([seed, topic_id, task_id]),
                task_id,
            ),
        )
        selected.extend(ranked[:count])
    return sorted(selected)


def build_empty_second_annotation_payload(
    *,
    primary_annotation_reference: Mapping[str, str],
    protocol_reference: Mapping[str, str],
    is_fixture: bool,
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    """Create the versioned Issue #64 extension before second judgements exist."""
    return {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": SECOND_ANNOTATION_ARTIFACT_TYPE,
        "artifact_id": "w6_second_annotations_v1",
        "is_fixture": is_fixture,
        "primary_annotations": dict(primary_annotation_reference),
        "annotation_protocol": dict(protocol_reference),
        "created_at": created_at,
        "provenance": {
            "kind": "independent_second_annotation_extension",
            "created_by": "w6_benchmark_workflow",
            "created_at": created_at,
            "git_revision": git_revision,
        },
        "annotations": [],
    }


def validate_second_annotation_results(
    payload: dict[str, Any],
    *,
    annotations: Mapping[str, dict[str, Any]],
    tasks: Mapping[str, dict[str, Any]],
    task_mappings: Mapping[str, dict[str, Any]],
    selected_task_ids: Iterable[str],
    protocol: Mapping[str, Any],
    primary_annotation_reference: Mapping[str, str],
    protocol_reference: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Validate independent second judgements without changing Bootstrap primary semantics."""
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "primary_annotations",
            "annotation_protocol",
            "created_at",
            "provenance",
            "annotations",
        },
        "second annotation artifact",
    )
    _require_header(payload, SECOND_ANNOTATION_ARTIFACT_TYPE)
    if payload["primary_annotations"] != dict(primary_annotation_reference) or payload[
        "annotation_protocol"
    ] != dict(protocol_reference):
        raise ValueError("second annotations input identity/hash drift。")
    _require_datetime(payload["created_at"], "second annotations created_at")
    _validate_provenance(payload["provenance"], "second annotations provenance")
    private_keys = _find_forbidden_keys(payload, PRIVATE_REASONING_KEYS)
    if private_keys:
        raise ValueError("second annotations 不得保存 private reasoning。")

    selected = set(selected_task_ids)
    primary_by_task = {
        annotation["annotation_task_id"]: annotation
        for annotation in annotations.values()
    }
    validated: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    protocol_time = _parse_datetime(protocol["frozen_at"])
    artifact_created_time = _parse_datetime(payload["created_at"])
    for raw in _require_list(payload["annotations"], "second annotations"):
        row = _require_mapping(raw, "second annotation")
        _require_exact_fields(
            row,
            {
                "second_annotation_id",
                "annotation_task_id",
                "annotation_round",
                "topic_id",
                "pool_item_id",
                "record_id",
                "relevance_label",
                "confidence",
                "evidence_sources",
                "justification_summary",
                "uncertainty",
                "annotation_provenance",
            },
            "second annotation",
        )
        second_id = _require_id(row["second_annotation_id"], "second_annotation_id")
        task_id = _require_id(row["annotation_task_id"], "second annotation task_id")
        if second_id in seen_ids or task_id in validated:
            raise ValueError("second annotations 不得重复 ID/task。")
        if second_id in annotations:
            raise ValueError("second_annotation_id 不得复用 primary annotation_id。")
        seen_ids.add(second_id)
        if row["annotation_round"] != "independent_second":
            raise ValueError("second annotation round 必须是 independent_second。")
        if task_id not in selected:
            raise ValueError(f"second annotation 不在冻结 selection 中：{task_id}。")
        task = tasks.get(task_id)
        mapping = task_mappings.get(task_id)
        primary = primary_by_task.get(task_id)
        if task is None or mapping is None or primary is None:
            raise ValueError(
                f"second annotation 缺少 matching primary/task：{task_id}。"
            )
        expected = (mapping["topic_id"], mapping["pool_item_id"], mapping["record_id"])
        actual = (row["topic_id"], row["pool_item_id"], row["record_id"])
        if actual != expected:
            raise ValueError(
                f"second annotation candidate identity mismatch：{second_id}。"
            )
        if type(row["relevance_label"]) is not int or row["relevance_label"] not in {
            0,
            1,
            2,
        }:
            raise ValueError(f"second annotation relevance label 非法：{second_id}。")
        if row["confidence"] not in {"high", "medium", "low"}:
            raise ValueError(f"second annotation confidence 非法：{second_id}。")
        evidence = _require_nonempty_list(
            row["evidence_sources"], f"{second_id}.evidence_sources"
        )
        for source in evidence:
            source_map = _require_mapping(source, "second annotation evidence")
            _require_exact_fields(
                source_map,
                {"source_type", "source_reference", "checked_at"},
                "second annotation evidence",
            )
            _require_nonempty_string(source_map["source_type"], "evidence source_type")
            _require_nonempty_string(
                source_map["source_reference"], "evidence source_reference"
            )
            _require_datetime(source_map["checked_at"], "evidence checked_at")
        _require_nonempty_string(row["justification_summary"], "second justification")
        if not isinstance(row["uncertainty"], str):
            raise ValueError("second annotation uncertainty 必须是 string。")
        provenance = _validate_annotation_provenance(
            row["annotation_provenance"], second_id
        )
        if (
            provenance["prompt_or_protocol_version"]
            != protocol["primary_annotation"]["prompt_version"]
        ):
            raise ValueError(f"second annotation protocol version drift：{second_id}。")
        primary_provenance = primary["annotation_provenance"]
        if provenance["actor_id"] == primary_provenance["actor_id"]:
            raise ValueError(f"second annotator 不独立：{second_id}。")
        second_time = _parse_datetime(provenance["created_at"])
        if protocol_time > _parse_datetime(primary_provenance["created_at"]):
            raise ValueError("annotation protocol freeze 晚于 primary annotation。")
        if second_time < _parse_datetime(primary_provenance["created_at"]):
            raise ValueError(f"second annotation 时间早于 primary：{second_id}。")
        if second_time < protocol_time:
            raise ValueError(
                f"second annotation 时间早于 protocol freeze：{second_id}。"
            )
        if artifact_created_time < second_time:
            raise ValueError(
                f"second annotation artifact created_at 早于 judgement：{second_id}。"
            )
        validated[task_id] = row
    return validated


def build_review_plan_payload(
    *,
    annotations: Mapping[str, dict[str, Any]],
    reviews: Mapping[str, dict[str, Any]],
    tasks: Mapping[str, dict[str, Any]],
    task_mappings: Mapping[str, dict[str, Any]],
    split_sets: Mapping[str, set[str]],
    protocol: Mapping[str, Any],
    protocol_reference: Mapping[str, str],
    annotation_reference: Mapping[str, str],
    second_annotation_reference: Mapping[str, str],
    review_reference: Mapping[str, str],
    second_annotations: Mapping[str, dict[str, Any]],
    is_fixture: bool,
    created_at: str,
    git_revision: str,
    evidence_lookup_statuses: Mapping[str, str] | None = None,
    boundary_case_annotation_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Build a deterministic, ranking-blind review plan from annotation-safe signals."""
    validate_annotation_protocol(dict(protocol))
    protocol_time = _parse_datetime(protocol["frozen_at"])
    plan_created_time = _parse_datetime(created_at)
    for annotation in annotations.values():
        primary_time = _parse_datetime(
            annotation["annotation_provenance"]["created_at"]
        )
        if protocol_time > primary_time:
            raise ValueError("annotation protocol freeze 晚于 primary annotation。")
        if plan_created_time < primary_time:
            raise ValueError("review plan created_at 早于 primary annotation。")
    for second in second_annotations.values():
        if plan_created_time < _parse_datetime(
            second["annotation_provenance"]["created_at"]
        ):
            raise ValueError("review plan created_at 早于 second annotation。")
    lookup = dict(evidence_lookup_statuses or {})
    boundary_ids = set(boundary_case_annotation_ids)
    unknown = (boundary_ids | set(lookup)).difference(annotations)
    if unknown:
        raise ValueError(
            "review plan signal 引用 unknown annotation："
            + ", ".join(sorted(unknown))
            + "。"
        )
    for annotation_id, annotation in annotations.items():
        if annotation_id not in lookup:
            lookup[annotation_id] = (
                "completed"
                if annotation["annotation_provenance"]["evidence_lookup_performed"]
                else "not_needed"
            )
        if lookup[annotation_id] not in LOOKUP_STATUSES:
            raise ValueError(f"{annotation_id} evidence lookup status 非法。")

    policy = protocol["review_policy"]
    second_tasks = select_second_annotation_tasks(
        task_mappings=task_mappings,
        dev_topic_ids=split_sets["dev"],
        fraction_per_topic=float(policy["second_annotation_fraction_per_topic"]),
        seed=policy["second_annotation_seed"],
    )
    if not set(second_annotations) <= set(second_tasks):
        raise ValueError("second annotation result 不在冻结 task selection 中。")
    primary_by_task = {
        annotation["annotation_task_id"]: annotation
        for annotation in annotations.values()
    }
    conflict_ids = {
        primary_by_task[task_id]["annotation_id"]
        for task_id, second in second_annotations.items()
        if task_id in primary_by_task
        and primary_by_task[task_id]["relevance_label"] != second["relevance_label"]
    }
    reasons_by_annotation: dict[str, set[str]] = defaultdict(set)
    for annotation_id, annotation in annotations.items():
        if annotation["confidence"] == "low":
            reasons_by_annotation[annotation_id].add("low_confidence")
        if annotation["uncertainty"].strip():
            reasons_by_annotation[annotation_id].add("nonempty_uncertainty")
        if lookup[annotation_id] in {"insufficient", "failed"}:
            reasons_by_annotation[annotation_id].add("evidence_insufficient")
        if annotation_id in boundary_ids:
            reasons_by_annotation[annotation_id].add("boundary_case")
        if annotation_id in conflict_ids:
            reasons_by_annotation[annotation_id].add("annotation_conflict")
        task = tasks[annotation["annotation_task_id"]]
        if task["candidate"]["abstract"] is None:
            reasons_by_annotation[annotation_id].add("missing_abstract")

    high_confidence = [
        annotation_id
        for annotation_id, annotation in annotations.items()
        if annotation["confidence"] == "high"
        and not reasons_by_annotation[annotation_id]
    ]
    qa_fraction = float(policy["random_high_confidence_qa_fraction"])
    qa_count = math.ceil(len(high_confidence) * qa_fraction) if qa_fraction else 0
    qa_ids = sorted(
        high_confidence,
        key=lambda annotation_id: (
            canonical_json_sha256([policy["random_qa_seed"], annotation_id]),
            annotation_id,
        ),
    )[:qa_count]
    for annotation_id in qa_ids:
        reasons_by_annotation[annotation_id].add("random_high_confidence_qa")

    review_by_annotation = {
        review["annotation_id"]: review for review in reviews.values()
    }
    if len(review_by_annotation) != len(reviews):
        raise ValueError("review plan 不得接受 duplicate annotation reviews。")
    for review in reviews.values():
        annotation = annotations[review["annotation_id"]]
        if review["provenance"]["created_by"] != review["reviewer_id"]:
            raise ValueError(
                f"review {review['review_id']} provenance actor 与 reviewer_id 不一致。"
            )
        if review["reviewer_id"] == annotation["annotation_provenance"]["actor_id"]:
            raise ValueError(f"review {review['review_id']} reviewer 不独立。")
        task_id = annotation["annotation_task_id"]
        second = second_annotations.get(task_id)
        if (
            second is not None
            and review["reviewer_id"] == second["annotation_provenance"]["actor_id"]
        ):
            raise ValueError(
                f"review {review['review_id']} reviewer 与 second annotator 不独立。"
            )
        prerequisite_times = [
            _parse_datetime(annotation["annotation_provenance"]["created_at"])
        ]
        if second is not None:
            prerequisite_times.append(
                _parse_datetime(second["annotation_provenance"]["created_at"])
            )
        if _parse_datetime(review["reviewed_at"]) < max(prerequisite_times):
            raise ValueError(
                f"review {review['review_id']} 时间早于 annotation workflow。"
            )
        if plan_created_time < _parse_datetime(review["reviewed_at"]):
            raise ValueError(
                f"review plan created_at 早于 review {review['review_id']}。"
            )
    review_items = []
    for annotation_id in sorted(
        annotation_id
        for annotation_id, reasons in reasons_by_annotation.items()
        if reasons
    ):
        review = review_by_annotation.get(annotation_id)
        annotation = annotations[annotation_id]
        review_items.append(
            {
                "annotation_id": annotation_id,
                "annotation_task_id": annotation["annotation_task_id"],
                "reasons": sorted(reasons_by_annotation[annotation_id]),
                "review_status": "completed" if review is not None else "pending",
                "review_id": review["review_id"] if review is not None else None,
            }
        )
    missing = [
        item["annotation_id"]
        for item in review_items
        if item["review_status"] == "pending"
    ]
    missing_second = sorted(set(second_tasks).difference(second_annotations))
    missing_conflict_adjudication = sorted(
        annotation_id
        for annotation_id in conflict_ids
        if annotation_id not in review_by_annotation
    )
    payload = {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": REVIEW_PLAN_ARTIFACT_TYPE,
        "artifact_id": "w6_annotation_review_plan_v1",
        "status": "in_review" if missing or missing_second else "review_complete",
        "is_fixture": is_fixture,
        "protocol": dict(protocol_reference),
        "annotations": dict(annotation_reference),
        "second_annotations": dict(second_annotation_reference),
        "reviews": dict(review_reference),
        "created_at": created_at,
        "evidence_lookup_statuses": [
            {"annotation_id": annotation_id, "lookup_status": lookup[annotation_id]}
            for annotation_id in sorted(lookup)
        ],
        "boundary_case_annotation_ids": sorted(boundary_ids),
        "conflicting_annotation_ids": sorted(conflict_ids),
        "second_annotation_task_ids": second_tasks,
        "review_items": review_items,
        "coverage": {
            "public_annotation_count": len(annotations),
            "selected_second_annotation_task_count": len(second_tasks),
            "completed_second_annotation_task_count": len(second_annotations),
            "missing_second_annotation_task_ids": missing_second,
            "conflict_annotation_ids": sorted(conflict_ids),
            "missing_conflict_adjudication_annotation_ids": missing_conflict_adjudication,
            "required_review_count": len(review_items),
            "completed_review_count": len(review_items) - len(missing),
            "missing_review_annotation_ids": missing,
        },
        "provenance": {
            "kind": "deterministic_blind_review_selection",
            "created_by": "w6_benchmark_workflow",
            "created_at": created_at,
            "git_revision": git_revision,
        },
    }
    return payload


def validate_review_plan(
    payload: dict[str, Any],
    *,
    annotations: Mapping[str, dict[str, Any]],
    reviews: Mapping[str, dict[str, Any]],
    tasks: Mapping[str, dict[str, Any]],
    task_mappings: Mapping[str, dict[str, Any]],
    split_sets: Mapping[str, set[str]],
    protocol: Mapping[str, Any],
    protocol_reference: Mapping[str, str],
    annotation_reference: Mapping[str, str],
    second_annotation_reference: Mapping[str, str],
    review_reference: Mapping[str, str],
    second_annotations: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "status",
            "is_fixture",
            "protocol",
            "annotations",
            "second_annotations",
            "reviews",
            "created_at",
            "evidence_lookup_statuses",
            "boundary_case_annotation_ids",
            "conflicting_annotation_ids",
            "second_annotation_task_ids",
            "review_items",
            "coverage",
            "provenance",
        },
        "review plan",
    )
    _require_header(payload, REVIEW_PLAN_ARTIFACT_TYPE)
    if (
        payload["protocol"] != dict(protocol_reference)
        or payload["annotations"] != dict(annotation_reference)
        or payload["second_annotations"] != dict(second_annotation_reference)
        or payload["reviews"] != dict(review_reference)
    ):
        raise ValueError("review plan input identity/hash drift。")
    lookup = {
        item["annotation_id"]: item["lookup_status"]
        for item in _require_list(
            payload["evidence_lookup_statuses"], "lookup statuses"
        )
    }
    expected = build_review_plan_payload(
        annotations=annotations,
        reviews=reviews,
        tasks=tasks,
        task_mappings=task_mappings,
        split_sets=split_sets,
        protocol=protocol,
        protocol_reference=protocol_reference,
        annotation_reference=annotation_reference,
        second_annotation_reference=second_annotation_reference,
        review_reference=review_reference,
        second_annotations=second_annotations,
        is_fixture=payload["is_fixture"],
        created_at=payload["created_at"],
        git_revision=payload["provenance"]["git_revision"],
        evidence_lookup_statuses=lookup,
        boundary_case_annotation_ids=payload["boundary_case_annotation_ids"],
    )
    if payload != expected:
        raise ValueError("review plan 与冻结 policy/annotation/review inputs 不一致。")
    return payload


def artifact_paths_from_bootstrap_bundle(
    bundle_path: str | Path,
) -> dict[str, Path]:
    """Adapt only the public Leader fixtures into the generic package builder."""
    from src.w6_contracts import validate_w6_bootstrap_bundle

    bundle = validate_w6_bootstrap_bundle(bundle_path)
    return {name: bundle["paths"][name] for name in BENCHMARK_INPUT_NAMES}


def build_w6_benchmark_package(
    *,
    artifact_paths: Mapping[str, str | Path],
    annotation_protocol_path: str | Path,
    second_annotation_path: str | Path | None = None,
    output_dir: str | Path,
    status: str,
    created_at: str,
    git_revision: str,
    git_worktree_clean: bool,
    reference_year: int = 2026,
    trusted_input_registry: Mapping[str, Mapping[str, Any]] | None = None,
) -> Path:
    """Build and self-validate a hash-pinned W6 Benchmark workflow package."""
    if set(artifact_paths) != set(BENCHMARK_INPUT_NAMES):
        raise ValueError("benchmark builder input artifact roster 不完整。")
    if status == "approved":
        raise ValueError("Issue #64 不实现 formal approved promotion gate。")
    if status not in {"bootstrap_fixture", "draft", "proposed", "sealed_candidate"}:
        raise ValueError("benchmark package status 非法。")
    _require_datetime(created_at, "benchmark package created_at")
    _require_git_revision(git_revision, "benchmark package git_revision")
    if git_worktree_clean is not True:
        raise ValueError("Benchmark package 必须从 clean Git snapshot 构建。")
    if isinstance(reference_year, bool) or not isinstance(reference_year, int):
        raise ValueError("reference_year 必须是 integer。")

    source_paths = {name: Path(path).resolve() for name, path in artifact_paths.items()}
    for name, path in source_paths.items():
        if not path.is_file():
            raise ValueError(f"benchmark input 不存在：{name}={path}")
    protocol_source = Path(annotation_protocol_path).resolve()
    if not protocol_source.is_file():
        raise ValueError(f"annotation protocol 不存在：{protocol_source}")
    protocol = load_json_object(protocol_source, label="W6 annotation protocol")
    validate_annotation_protocol(protocol)
    source_graph = _load_and_validate_graph(source_paths)
    is_fixture_values = {
        bool(source_graph["payloads"][name]["is_fixture"])
        for name in BENCHMARK_INPUT_NAMES
    }
    is_fixture_values.add(bool(protocol["is_fixture"]))
    if len(is_fixture_values) != 1:
        raise ValueError("benchmark inputs 不得混用 fixture/real artifacts。")
    is_fixture = is_fixture_values.pop()
    if status == "bootstrap_fixture" and not is_fixture:
        raise ValueError("bootstrap_fixture status 只能用于明确 synthetic inputs。")
    if status != "bootstrap_fixture" and is_fixture:
        raise ValueError(
            "synthetic fixture 不得冒充 draft/proposed/sealed research Benchmark。"
        )
    second_source = (
        Path(second_annotation_path).resolve()
        if second_annotation_path is not None
        else None
    )
    if status != "bootstrap_fixture" and second_source is None:
        raise ValueError(
            "real Benchmark status 必须提供外部 second annotation artifact。"
        )
    if second_source is not None and not second_source.is_file():
        raise ValueError(f"second annotation artifact 不存在：{second_source}")

    output = ensure_output_separate_from_inputs(
        output_dir,
        input_paths=[
            *{path.parent for path in source_paths.values()},
            protocol_source,
            *([second_source] if second_source is not None else []),
        ],
    )
    _ensure_empty_output(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.build_", dir=output.parent
    ) as temp_dir:
        staging = Path(temp_dir)
        copied_paths: dict[str, Path] = {}
        inputs_dir = staging / "inputs"
        inputs_dir.mkdir()
        for name in BENCHMARK_INPUT_NAMES:
            target = inputs_dir / f"{name}.json"
            shutil.copy2(source_paths[name], target)
            copied_paths[name] = target
        protocol_path = staging / "annotation_protocol.json"
        shutil.copy2(protocol_source, protocol_path)
        copied_paths["annotation_protocol"] = protocol_path

        graph = _load_and_validate_graph(
            {name: copied_paths[name] for name in BENCHMARK_INPUT_NAMES}
        )
        refs = {
            name: _artifact_reference(copied_paths[name])
            for name in BENCHMARK_INPUT_NAMES
        }
        protocol_ref = _artifact_reference(protocol_path)
        second_tasks = select_second_annotation_tasks(
            task_mappings=graph["task_mappings"],
            dev_topic_ids=graph["split_sets"]["dev"],
            fraction_per_topic=float(
                protocol["review_policy"]["second_annotation_fraction_per_topic"]
            ),
            seed=protocol["review_policy"]["second_annotation_seed"],
        )
        second_path = staging / "second_annotation_results.json"
        if second_source is None:
            second_payload = build_empty_second_annotation_payload(
                primary_annotation_reference=refs["annotation_results"],
                protocol_reference=protocol_ref,
                is_fixture=is_fixture,
                created_at=created_at,
                git_revision=git_revision,
            )
            _write_json(second_path, second_payload)
        else:
            shutil.copy2(second_source, second_path)
            second_payload = load_json_object(
                second_path, label="W6 second annotations"
            )
        copied_paths["second_annotation_results"] = second_path
        second_ref = _artifact_reference(second_path)
        second_annotations = validate_second_annotation_results(
            second_payload,
            annotations=graph["annotations"],
            tasks=graph["tasks"],
            task_mappings=graph["task_mappings"],
            selected_task_ids=second_tasks,
            protocol=protocol,
            primary_annotation_reference=refs["annotation_results"],
            protocol_reference=protocol_ref,
        )
        _validate_annotation_workflow_chronology(
            graph=graph,
            protocol=protocol,
            second_annotations=second_annotations,
        )
        review_plan = build_review_plan_payload(
            annotations=graph["annotations"],
            reviews=graph["reviews"],
            tasks=graph["tasks"],
            task_mappings=graph["task_mappings"],
            split_sets=graph["split_sets"],
            protocol=protocol,
            protocol_reference=protocol_ref,
            annotation_reference=refs["annotation_results"],
            second_annotation_reference=second_ref,
            review_reference=refs["annotation_reviews"],
            second_annotations=second_annotations,
            is_fixture=is_fixture,
            created_at=created_at,
            git_revision=git_revision,
        )
        review_plan_path = staging / "review_plan.json"
        _write_json(review_plan_path, review_plan)
        copied_paths["review_plan"] = review_plan_path
        review_plan_ref = _artifact_reference(review_plan_path)

        benchmark = _build_benchmark_manifest(
            graph=graph,
            refs=refs,
            status=status,
            is_fixture=is_fixture,
            reference_year=reference_year,
            created_at=created_at,
            git_revision=git_revision,
            review_plan=review_plan,
        )
        benchmark_path = staging / "benchmark_manifest.json"
        _write_json(benchmark_path, benchmark)
        copied_paths["benchmark_manifest"] = benchmark_path
        benchmark_ref = _artifact_reference(benchmark_path)

        package_artifacts: dict[str, dict[str, str]] = {}
        for name in PACKAGE_ARTIFACT_NAMES:
            path = copied_paths[name]
            package_artifacts[name] = {
                "artifact_id": load_json_object(path)["artifact_id"],
                "path": path.relative_to(staging).as_posix(),
                "sha256": sha256_file(path),
            }
        package = {
            "schema_version": W6_SCHEMA_VERSION,
            "contract_name": WORKFLOW_CONTRACT_NAME,
            "contract_version": WORKFLOW_CONTRACT_VERSION,
            "artifact_type": PACKAGE_ARTIFACT_TYPE,
            "package_id": "w6_query_relevance_v0.2_alpha_package_v1",
            "is_fixture": is_fixture,
            "status": status,
            "created_at": created_at,
            "artifacts": package_artifacts,
            "generation": {
                "git_revision": git_revision,
                "git_worktree_clean": True,
                "labels_used_for_generation": False,
            },
            "package_identity": "",
        }
        package["package_identity"] = compute_package_identity(package)
        package_path = staging / "package_manifest.json"
        _write_json(package_path, package)
        validate_w6_benchmark_package(
            package_path,
            trusted_input_registry=trusted_input_registry,
        )
        if output.exists():
            output.rmdir()
        staging.replace(output)
    return output / "package_manifest.json"


def validate_w6_benchmark_package(
    package_path: str | Path,
    *,
    trusted_input_registry: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate hashes, all Bootstrap graph contracts, review policy, and status gates."""
    manifest_file = Path(package_path).resolve()
    root = manifest_file.parent
    package = load_json_object(manifest_file, label="W6 benchmark package")
    _require_exact_fields(
        package,
        {
            "schema_version",
            "contract_name",
            "contract_version",
            "artifact_type",
            "package_id",
            "is_fixture",
            "status",
            "created_at",
            "artifacts",
            "generation",
            "package_identity",
        },
        "benchmark package",
    )
    if (
        package["schema_version"] != W6_SCHEMA_VERSION
        or package["contract_name"] != WORKFLOW_CONTRACT_NAME
        or package["contract_version"] != WORKFLOW_CONTRACT_VERSION
        or package["artifact_type"] != PACKAGE_ARTIFACT_TYPE
    ):
        raise ValueError("W6 benchmark package header/version 非法。")
    _require_id(package["package_id"], "benchmark package_id")
    if not isinstance(package["is_fixture"], bool):
        raise ValueError("benchmark package is_fixture 必须是 boolean。")
    if package["status"] == "approved":
        raise ValueError("Issue #64 package 不得自报 approved。")
    if package["status"] not in {
        "bootstrap_fixture",
        "draft",
        "proposed",
        "sealed_candidate",
    }:
        raise ValueError("benchmark package status 非法。")
    if package["status"] == "bootstrap_fixture" and package["is_fixture"] is not True:
        raise ValueError(
            "bootstrap_fixture status 必须绑定 synthetic fixture artifacts。"
        )
    if package["status"] != "bootstrap_fixture" and package["is_fixture"] is not False:
        raise ValueError("real Benchmark status 不得绑定 fixture artifacts。")
    _require_datetime(package["created_at"], "benchmark package created_at")
    generation = _require_mapping(package["generation"], "benchmark generation")
    if (
        generation.get("git_worktree_clean") is not True
        or generation.get("labels_used_for_generation") is not False
    ):
        raise ValueError(
            "Benchmark builder 必须 clean 且不得用 labels 生成 inputs/config。"
        )
    _require_git_revision(
        generation.get("git_revision"), "benchmark generation git_revision"
    )
    if package["package_identity"] != compute_package_identity(package):
        raise ValueError("benchmark package identity/hash drift。")

    artifact_entries = _require_mapping(package["artifacts"], "package artifacts")
    if set(artifact_entries) != set(PACKAGE_ARTIFACT_NAMES):
        raise ValueError("benchmark package artifact roster 不完整。")
    paths: dict[str, Path] = {}
    registry: dict[str, dict[str, str]] = {}
    for name, raw in artifact_entries.items():
        entry = _require_mapping(raw, f"package artifact {name}")
        _require_exact_fields(
            entry, {"artifact_id", "path", "sha256"}, f"package artifact {name}"
        )
        _require_id(entry["artifact_id"], f"{name}.artifact_id")
        _require_sha256(entry["sha256"], f"{name}.sha256")
        path = _resolve_within(entry["path"], root)
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"benchmark package hash drift：{name}。")
        payload = load_json_object(path, label=f"package artifact {name}")
        if payload.get("artifact_id") != entry["artifact_id"]:
            raise ValueError(f"benchmark artifact identity mismatch：{name}。")
        if payload.get("is_fixture") is not package["is_fixture"]:
            raise ValueError(f"benchmark artifact fixture identity mismatch：{name}。")
        if entry["artifact_id"] in registry:
            raise ValueError("benchmark package duplicate artifact_id。")
        registry[entry["artifact_id"]] = {
            "artifact_id": entry["artifact_id"],
            "sha256": entry["sha256"],
        }
        paths[name] = path

    if package["status"] != "bootstrap_fixture":
        _validate_trusted_real_inputs(
            artifact_entries=artifact_entries,
            trusted_input_registry=trusted_input_registry,
        )

    graph = _load_and_validate_graph(
        {name: paths[name] for name in BENCHMARK_INPUT_NAMES}, registry=registry
    )
    protocol = load_json_object(paths["annotation_protocol"])
    validate_annotation_protocol(protocol)
    second_tasks = select_second_annotation_tasks(
        task_mappings=graph["task_mappings"],
        dev_topic_ids=graph["split_sets"]["dev"],
        fraction_per_topic=float(
            protocol["review_policy"]["second_annotation_fraction_per_topic"]
        ),
        seed=protocol["review_policy"]["second_annotation_seed"],
    )
    second_payload = load_json_object(paths["second_annotation_results"])
    second_annotations = validate_second_annotation_results(
        second_payload,
        annotations=graph["annotations"],
        tasks=graph["tasks"],
        task_mappings=graph["task_mappings"],
        selected_task_ids=second_tasks,
        protocol=protocol,
        primary_annotation_reference=_identity_hash(
            artifact_entries["annotation_results"]
        ),
        protocol_reference=_identity_hash(artifact_entries["annotation_protocol"]),
    )
    _validate_annotation_workflow_chronology(
        graph=graph,
        protocol=protocol,
        second_annotations=second_annotations,
    )
    review_plan = load_json_object(paths["review_plan"])
    validate_review_plan(
        review_plan,
        annotations=graph["annotations"],
        reviews=graph["reviews"],
        tasks=graph["tasks"],
        task_mappings=graph["task_mappings"],
        split_sets=graph["split_sets"],
        protocol=protocol,
        protocol_reference=_identity_hash(artifact_entries["annotation_protocol"]),
        annotation_reference=_identity_hash(artifact_entries["annotation_results"]),
        second_annotation_reference=_identity_hash(
            artifact_entries["second_annotation_results"]
        ),
        review_reference=_identity_hash(artifact_entries["annotation_reviews"]),
        second_annotations=second_annotations,
    )
    benchmark = load_json_object(paths["benchmark_manifest"])
    validate_benchmark_manifest(
        benchmark,
        registry=registry,
        topics=graph["topics"],
        pool_members=graph["pool_members"],
        canonical=graph["canonical"],
        annotations=graph["annotations"],
        reviews=graph["reviews"],
        split_sets=graph["split_sets"],
    )
    if (
        benchmark["status"] != package["status"]
        or benchmark["is_fixture"] != package["is_fixture"]
    ):
        raise ValueError(
            "package 与 Benchmark manifest status/fixture identity 不一致。"
        )
    validate_benchmark_status_gate(
        package["status"], graph=graph, review_plan=review_plan
    )
    return {
        "package": package,
        "paths": paths,
        "registry": registry,
        "graph": graph,
        "protocol": protocol,
        "second_annotations": second_annotations,
        "review_plan": review_plan,
        "benchmark": benchmark,
    }


def compute_package_identity(package: Mapping[str, Any]) -> str:
    return deterministic_identity(
        "w6-benchmark-package",
        {
            "package_id": package.get("package_id"),
            "is_fixture": package.get("is_fixture"),
            "status": package.get("status"),
            "created_at": package.get("created_at"),
            "artifacts": package.get("artifacts"),
            "generation": package.get("generation"),
        },
    )


def _load_and_validate_graph(
    paths: Mapping[str, Path],
    *,
    registry: Mapping[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    if set(paths) != set(BENCHMARK_INPUT_NAMES):
        raise ValueError("benchmark graph artifact roster 不完整。")
    payloads = {
        name: load_json_object(path, label=name) for name, path in paths.items()
    }
    trusted = dict(registry or {})
    for name, path in paths.items():
        artifact_id = payloads[name].get("artifact_id")
        _require_id(artifact_id, f"{name}.artifact_id")
        reference = {"artifact_id": artifact_id, "sha256": sha256_file(path)}
        existing = trusted.get(artifact_id)
        if existing is not None and existing != reference:
            raise ValueError(f"benchmark graph registry drift：{name}。")
        trusted[artifact_id] = reference

    topics = validate_frozen_topic_roster(payloads["topic_set"])
    retrieval = validate_retrieval_provenance(
        payloads["retrieval_provenance"], topics=topics
    )
    records = validate_source_records(
        payloads["source_records"], topics=topics, retrieval=retrieval
    )
    canonical = validate_canonical_entities(
        payloads["canonical_entities"], records=records, retrieval=retrieval
    )
    pool_members = validate_candidate_pool(
        payloads["candidate_pool"],
        topics=topics,
        records=records,
        retrieval=retrieval,
        registry=trusted,
        canonical=canonical,
    )
    task_mappings = validate_annotation_task_map(
        payloads["annotation_task_map"],
        records=records,
        pool_members=pool_members,
        registry=trusted,
    )
    tasks = validate_blind_annotation_tasks(
        payloads["annotation_tasks"],
        topics=topics,
        records=records,
        task_mappings=task_mappings,
        registry=trusted,
    )
    split_sets = validate_topic_split(payloads["split_manifest"], topics=topics)
    expected_topic_ref = trusted[payloads["topic_set"]["artifact_id"]]
    if payloads["split_manifest"]["topic_set"] != expected_topic_ref:
        raise ValueError("benchmark split 未绑定实际 topic artifact hash。")
    annotations = validate_annotation_results(
        payloads["annotation_results"],
        tasks=tasks,
        task_mappings=task_mappings,
        split=payloads["split_manifest"],
        split_sets=split_sets,
        registry=trusted,
    )
    reviews = validate_annotation_reviews(
        payloads["annotation_reviews"], annotations=annotations
    )
    validate_hidden_label_anchor(
        payloads["hidden_label_anchor"],
        split=payloads["split_manifest"],
        split_sets=split_sets,
        registry=trusted,
    )
    return {
        "payloads": payloads,
        "registry": trusted,
        "topics": topics,
        "retrieval": retrieval,
        "records": records,
        "canonical": canonical,
        "pool_members": pool_members,
        "task_mappings": task_mappings,
        "tasks": tasks,
        "split_sets": split_sets,
        "annotations": annotations,
        "reviews": reviews,
    }


def _build_benchmark_manifest(
    *,
    graph: Mapping[str, Any],
    refs: Mapping[str, dict[str, str]],
    status: str,
    is_fixture: bool,
    reference_year: int,
    created_at: str,
    git_revision: str,
    review_plan: Mapping[str, Any],
) -> dict[str, Any]:
    review_status = (
        "in_review"
        if review_plan["coverage"]["missing_review_annotation_ids"]
        else "not_started"
    )
    benchmark = {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": "w6_benchmark_manifest",
        "artifact_id": "w6_query_relevance_v0.2_alpha_manifest_v1",
        "is_fixture": is_fixture,
        "benchmark_name": "W6 Query-Relevance Benchmark v0.2-alpha",
        "benchmark_version": (
            "w6_query_relevance_v0.2-alpha.bootstrap-fixture"
            if is_fixture
            else "w6_query_relevance_v0.2-alpha"
        ),
        "status": status,
        "evaluation_target": "query_relevance",
        "label_scheme": {
            "type": "graded_relevance",
            "allowed_values": [0, 1, 2],
            "version": "query_relevance_0_1_2_v1",
        },
        "record_unit": "topic_id + pool_item_id",
        "entity_policy": (
            "source records remain auditable; confirmed aliases map to canonical entities "
            "without silent deletion; suspected duplicates remain separate pending review"
        ),
        "reference_year": reference_year,
        "topic_set": refs["topic_set"],
        "split": refs["split_manifest"],
        "candidate_pool": refs["candidate_pool"],
        "canonical_entities": refs["canonical_entities"],
        "annotations": refs["annotation_results"],
        "reviews": refs["annotation_reviews"],
        "hidden_label_anchor": refs["hidden_label_anchor"],
        "counts": {
            "topic_count": len(graph["topics"]),
            "dev_topic_count": len(graph["split_sets"]["dev"]),
            "hidden_test_topic_count": len(graph["split_sets"]["hidden"]),
            "pool_item_count": len(graph["pool_members"]),
            "canonical_entity_count": len(graph["canonical"]["entities"]),
            "public_annotation_count": len(graph["annotations"]),
            "public_review_count": len(graph["reviews"]),
        },
        "benchmark_identity": "",
        "generation_provenance": {
            "kind": "w6_benchmark_workflow_builder",
            "created_by": "w6_benchmark_workflow",
            "created_at": created_at,
            "git_revision": git_revision,
        },
        "review_provenance": {
            "status": review_status,
            "reviewers": sorted(
                {review["reviewer_id"] for review in graph["reviews"].values()}
            ),
            "note": (
                "Fixture-driven workflow validation only; formal approved promotion is not implemented."
                if is_fixture
                else "AI-assisted judgements require completion of the frozen independent review policy."
            ),
        },
    }
    benchmark["benchmark_identity"] = compute_benchmark_identity(benchmark)
    return benchmark


def validate_benchmark_status_gate(
    status: str, *, graph: Mapping[str, Any], review_plan: Mapping[str, Any]
) -> None:
    if status in {"bootstrap_fixture", "draft"}:
        return
    dev_pool_ids = {
        item_id
        for item_id, member in graph["pool_members"].items()
        if member["topic_id"] in graph["split_sets"]["dev"]
    }
    annotated_pool_ids = {row["pool_item_id"] for row in graph["annotations"].values()}
    if annotated_pool_ids != dev_pool_ids:
        raise ValueError(
            "proposed/sealed_candidate 必须完整覆盖 Dev Candidate Pool annotations。"
        )
    if status == "sealed_candidate":
        coverage = review_plan["coverage"]
        if coverage["missing_second_annotation_task_ids"]:
            raise ValueError(
                "sealed_candidate 仍有 incomplete selected second annotation。"
            )
        if coverage["missing_conflict_adjudication_annotation_ids"]:
            raise ValueError(
                "sealed_candidate 仍有 unadjudicated annotation conflict。"
            )
        if coverage["missing_review_annotation_ids"]:
            raise ValueError("sealed_candidate 仍有 incomplete mandatory review。")


def _validate_annotation_workflow_chronology(
    *,
    graph: Mapping[str, Any],
    protocol: Mapping[str, Any],
    second_annotations: Mapping[str, dict[str, Any]],
) -> None:
    split_time = _parse_datetime(graph["payloads"]["split_manifest"]["frozen_at"])
    protocol_time = _parse_datetime(protocol["frozen_at"])
    if split_time > protocol_time:
        raise ValueError("annotation protocol freeze 不得早于 split freeze。")
    annotation_started_time = _parse_datetime(
        graph["payloads"]["annotation_results"]["annotation_started_at"]
    )
    if protocol_time > annotation_started_time:
        raise ValueError("annotation protocol freeze 晚于 annotation_started_at。")
    primary_by_id = graph["annotations"]
    for annotation in primary_by_id.values():
        if (
            annotation["annotation_provenance"]["prompt_or_protocol_version"]
            != protocol["primary_annotation"]["prompt_version"]
        ):
            raise ValueError("primary annotation protocol version drift。")
        primary_time = _parse_datetime(
            annotation["annotation_provenance"]["created_at"]
        )
        if protocol_time > primary_time:
            raise ValueError("annotation protocol freeze 晚于 primary annotation。")
    for review in graph["reviews"].values():
        primary = primary_by_id[review["annotation_id"]]
        prerequisite_times = [
            _parse_datetime(primary["annotation_provenance"]["created_at"])
        ]
        second = second_annotations.get(primary["annotation_task_id"])
        if second is not None:
            prerequisite_times.append(
                _parse_datetime(second["annotation_provenance"]["created_at"])
            )
        review_time = _parse_datetime(review["reviewed_at"])
        provenance_time = _parse_datetime(review["provenance"]["created_at"])
        if review_time < max(prerequisite_times):
            raise ValueError(
                f"review {review['review_id']} 时间早于 annotation workflow。"
            )
        if provenance_time < review_time:
            raise ValueError(
                f"review {review['review_id']} provenance 时间早于 reviewed_at。"
            )


def _validate_trusted_real_inputs(
    *,
    artifact_entries: Mapping[str, Any],
    trusted_input_registry: Mapping[str, Mapping[str, Any]] | None,
) -> None:
    if trusted_input_registry is None:
        raise ValueError(
            "real Benchmark validation 需要 package 外部 trusted input registry。"
        )
    trusted_names = BENCHMARK_INPUT_NAMES + (
        "annotation_protocol",
        "second_annotation_results",
    )
    for name in trusted_names:
        entry = artifact_entries[name]
        artifact_id = entry["artifact_id"]
        trusted = trusted_input_registry.get(artifact_id)
        expected = {
            "artifact_id": artifact_id,
            "sha256": entry["sha256"],
            "is_fixture": False,
        }
        if not isinstance(trusted, Mapping) or dict(trusted) != expected:
            raise ValueError(
                f"real Benchmark input 缺少外部 trusted identity/hash：{name}。"
            )


def _artifact_reference(path: Path) -> dict[str, str]:
    payload = load_json_object(path)
    return {"artifact_id": payload["artifact_id"], "sha256": sha256_file(path)}


def _identity_hash(entry: Mapping[str, str]) -> dict[str, str]:
    return {"artifact_id": entry["artifact_id"], "sha256": entry["sha256"]}


def _ensure_empty_output(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"输出目录已存在且非空，拒绝覆盖：{path}")


def _resolve_within(value: Any, root: Path) -> Path:
    text = str(value or "").strip()
    if not text or Path(text).is_absolute():
        raise ValueError("package artifact path 必须是相对路径。")
    path = (root / text).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("package artifact path 不得离开 package。") from error
    if not path.is_file():
        raise ValueError(f"package artifact 不存在：{path}")
    return path


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _validate_provenance(value: Any, label: str) -> None:
    provenance = _require_mapping(value, label)
    _require_exact_fields(
        provenance, {"kind", "created_by", "created_at", "git_revision"}, label
    )
    _require_nonempty_string(provenance["kind"], f"{label}.kind")
    _require_nonempty_string(provenance["created_by"], f"{label}.created_by")
    _require_datetime(provenance["created_at"], f"{label}.created_at")
    _require_git_revision(provenance["git_revision"], f"{label}.git_revision")


def _require_header(payload: Mapping[str, Any], artifact_type: str) -> None:
    if payload.get("schema_version") != W6_SCHEMA_VERSION:
        raise ValueError(f"{artifact_type} schema_version 非法。")
    if payload.get("artifact_type") != artifact_type:
        raise ValueError(f"artifact_type 必须是 {artifact_type}。")
    _require_id(payload.get("artifact_id"), f"{artifact_type}.artifact_id")
    if not isinstance(payload.get("is_fixture"), bool):
        raise ValueError(f"{artifact_type}.is_fixture 必须是 boolean。")


def _require_exact_fields(
    payload: Mapping[str, Any], expected: set[str], label: str
) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{label} 字段不符合 contract：missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}。"
        )


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON object。")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是 JSON array。")
    return value


def _require_nonempty_list(value: Any, label: str) -> list[Any]:
    result = _require_list(value, label)
    if not result:
        raise ValueError(f"{label} 不能为空。")
    return result


def _require_string_list(value: Any, label: str, *, nonempty: bool) -> list[str]:
    values = _require_list(value, label)
    if nonempty and not values:
        raise ValueError(f"{label} 不能为空。")
    if any(
        not isinstance(item, str) or not item.strip() or item != item.strip()
        for item in values
    ):
        raise ValueError(f"{label} 必须只含无首尾空白的非空字符串。")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} 不得重复。")
    return values


def _require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} 必须是无首尾空白的非空字符串。")
    return value


def _require_id(value: Any, label: str) -> str:
    import re

    text = _require_nonempty_string(value, label)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._:-]*", text):
        raise ValueError(f"{label} 必须是小写稳定机器标识。")
    return text


def _require_sha256(value: Any, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{label} 必须是 64 位小写 SHA-256。")
    return text


def _require_git_revision(value: Any, label: str) -> str:
    text = str(value or "")
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{label} 必须是 40 位小写 Git SHA。")
    return text


def _require_datetime(value: Any, label: str) -> None:
    try:
        _parse_datetime(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} 必须是带时区 ISO-8601 时间。") from error


def _parse_datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").strip())
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("datetime 缺少时区。")
    return parsed


def _require_fraction(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} 必须是 0..1 finite number。")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError(f"{label} 必须是 0..1 finite number。")
    return number
