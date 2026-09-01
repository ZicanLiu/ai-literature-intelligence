"""RCP-v0.3 AI-assisted internal Reference curation contracts.

This module is deliberately provider-neutral and offline.  It exports one-
candidate Title+Abstract tasks, validates externally produced structured
judgements, applies the frozen 3-Core + 2-Sentinel routing policy, prepares
blind selective human review, and finalizes provenance-complete fixture or
future formal Reference selections.  It never calls a model API and never
claims astronomy expert ground truth.
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.annotation_tasks import sha256_file
from src.pilot_selection import (
    BM25_METHOD_ID,
    PILOT_VERSION,
    SELECTION_K,
    PilotSelectionInputs,
    load_pilot_selection_inputs,
    payload_sha256,
    topic_config,
    validate_external_output_path,
    write_json,
)
from src.w6_contracts import (
    canonical_json_sha256,
    deterministic_identity,
    load_json_object,
)


RCP_SCHEMA_VERSION = "1.0"
RCP_PROTOCOL_ID = "srtp_reference_curation_v0.3"
REFERENCE_METHOD_ID = "pilot_ai_assisted_reference_abstract_v1"
CORE_COUNT = 3
SENTINEL_COUNT = 2
PANEL_COUNT = CORE_COUNT + SENTINEL_COUNT
U80_COUNT = 80

BOUNDARY_DIMENSIONS = (
    "scientific_object",
    "data_modality",
    "target_task",
    "method_role",
)
BOUNDARY_VALUES = frozenset({"match", "mismatch", "unclear", "not_stated"})
EVIDENCE_SUFFICIENCY_VALUES = frozenset({"sufficient", "insufficient"})
MODEL_ROLES = frozenset({"core", "sentinel"})
HUMAN_REVIEWER_SLOTS = frozenset({"r1", "r2", "r3"})
HARD_MISMATCH_CODES = {
    f"hard_mismatch_{dimension}": dimension for dimension in BOUNDARY_DIMENSIONS
}
PRIVATE_REASONING_KEYS = frozenset(
    {"chain_of_thought", "private_reasoning", "reasoning_trace", "hidden_reasoning"}
)
AI_TASK_FORBIDDEN_KEYS = frozenset(
    {
        "canonical_entity_id",
        "openalex_id",
        "doi",
        "authors",
        "venue",
        "publication_year",
        "year",
        "citation_count",
        "cited_by_count",
        "source_rank",
        "source_score",
        "query_support",
        "query_support_count",
        "bm25",
        "bm25_score",
        "bm25_rank",
        "human_judgement",
        "model_judgement",
        "downstream_result",
        "selection_rank",
        "selection_score",
        "roster_entry_id",
        "role",
    }
)
HUMAN_TASK_FORBIDDEN_KEYS = AI_TASK_FORBIDDEN_KEYS | frozenset(
    {
        "model",
        "provider",
        "model_family",
        "independence_group",
        "core_labels",
        "sentinel_labels",
        "safe_zero",
        "routing_reason",
        "routing_reasons",
        "vote",
        "votes",
        "majority",
        "confidence",
    }
)

CONFIG_IDENTITY_PREFIX = "srtp-rcp-config"
PROMPT_IDENTITY_PREFIX = "srtp-rcp-screening-prompt"
ROSTER_IDENTITY_PREFIX = "srtp-rcp-model-roster"
TASK_IDENTITY_PREFIX = "srtp-rcp-ai-task"
TASK_PACKAGE_IDENTITY_PREFIX = "srtp-rcp-ai-task-package"
TASK_MAP_IDENTITY_PREFIX = "srtp-rcp-ai-task-map"
MODEL_BATCH_IDENTITY_PREFIX = "srtp-rcp-model-batch"
EXECUTION_IDENTITY_PREFIX = "srtp-rcp-execution"
AGGREGATION_IDENTITY_PREFIX = "srtp-rcp-aggregation"
AUDIT_IDENTITY_PREFIX = "srtp-rcp-safe-zero-audit"
AUDIT_OUTCOME_IDENTITY_PREFIX = "srtp-rcp-safe-zero-audit-outcome"
HUMAN_TASK_IDENTITY_PREFIX = "srtp-rcp-human-task"
HUMAN_TASK_PACKAGE_IDENTITY_PREFIX = "srtp-rcp-human-task-package"
HUMAN_MAP_IDENTITY_PREFIX = "srtp-rcp-human-map"
HUMAN_SUBMISSION_IDENTITY_PREFIX = "srtp-rcp-human-submission"
H2_IDENTITY_PREFIX = "srtp-rcp-h2-evidence"
HUMAN_LABEL_IDENTITY_PREFIX = "srtp-rcp-final-human-labels"
CUTOFF_IDENTITY_PREFIX = "srtp-rcp-cutoff-decision"
FINAL_REFERENCE_IDENTITY_PREFIX = "srtp-rcp-final-reference"
QUALITY_REPORT_IDENTITY_PREFIX = "srtp-rcp-quality-report"


@dataclass(frozen=True)
class ReferenceCurationInputs:
    project_root: Path
    config_path: Path
    config: dict[str, Any]
    pilot_inputs: PilotSelectionInputs
    prompt_path: Path
    prompt_package: dict[str, Any]
    roster_template_path: Path
    roster_template: dict[str, Any]


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON object。")
    return value


def _list(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = "非空数组" if nonempty else "数组"
        raise ValueError(f"{label} 必须是{suffix}。")
    return value


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} 必须是字符串。")
    text = value.strip()
    if not allow_empty and not text:
        raise ValueError(f"{label} 必须是非空字符串。")
    return text


def _bool(value: Any, label: str, *, expected: bool | None = None) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} 必须是布尔值。")
    if expected is not None and value is not expected:
        raise ValueError(f"{label} 必须是 {expected}。")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} 必须是 >= {minimum} 的整数。")
    return value


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} 必须是有限数值。")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"{label} 必须是合法有限数值。")
    return result


def _datetime(value: Any, label: str) -> str:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} 必须是 ISO-8601 时间。") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} 必须包含时区。")
    return text


def _git_revision(value: Any, label: str) -> str:
    revision = _text(value, label)
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError(f"{label} 必须是 40 位 lowercase Git SHA。")
    return revision


def _sha256(value: Any, label: str) -> str:
    digest = _text(value, label)
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"{label} 必须是 64 位 lowercase SHA-256。")
    return digest


def _exact(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    actual = set(value)
    if actual != fields:
        raise ValueError(
            f"{label} 字段漂移：missing={sorted(fields - actual)}, "
            f"extra={sorted(actual - fields)}。"
        )


def _strings(
    value: Any,
    label: str,
    *,
    count: int | None = None,
    unique: bool = True,
) -> list[str]:
    result = [_text(item, f"{label} item") for item in _list(value, label)]
    if count is not None and len(result) != count:
        raise ValueError(f"{label} 必须精确包含 {count} 项。")
    if unique and len(result) != len(set(result)):
        raise ValueError(f"{label} 不得重复。")
    return result


def _identity_without(
    payload: Mapping[str, Any],
    *,
    prefix: str,
    omitted: Iterable[str],
) -> str:
    body = copy.deepcopy(dict(payload))
    for field in omitted:
        body.pop(field, None)
    return deterministic_identity(prefix, body)


def _artifact_id(prefix: str, identity: str) -> str:
    return f"{prefix}_{identity.rsplit(':', 1)[-1][:24]}"


def _artifact_reference(payload: Mapping[str, Any]) -> dict[str, str]:
    return {
        "artifact_id": _text(payload.get("artifact_id"), "artifact_id"),
        "sha256": payload_sha256(payload),
    }


def _resolve_repo_path(root: Path, value: Any, label: str) -> Path:
    relative = Path(_text(value, label))
    if relative.is_absolute():
        raise ValueError(f"{label} 必须是仓库相对路径。")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} 逃逸仓库根目录。") from error
    return resolved


def _all_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).casefold())
            keys.update(_all_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_all_keys(child))
    return keys


def compute_rcp_config_identity(config: Mapping[str, Any]) -> str:
    return _identity_without(
        config,
        prefix=CONFIG_IDENTITY_PREFIX,
        omitted={"artifact_id", "config_identity"},
    )


def compute_prompt_identity(prompt: Mapping[str, Any]) -> str:
    return _identity_without(
        prompt,
        prefix=PROMPT_IDENTITY_PREFIX,
        omitted={"artifact_id", "prompt_identity"},
    )


def _validate_prompt_package(prompt: Mapping[str, Any]) -> None:
    artifact = _mapping(dict(prompt), "RCP prompt package")
    _exact(
        artifact,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "prompt_identity",
            "protocol_id",
            "status",
            "primary_information",
            "instruction_text",
            "relevance_definitions",
            "boundary_definitions",
            "output_contract",
            "external_lookup",
            "reason_policy",
            "evidence_span_policy",
            "schema_repair_policy",
            "private_reasoning_policy",
        },
        "RCP prompt package",
    )
    if artifact["schema_version"] != RCP_SCHEMA_VERSION:
        raise ValueError("RCP prompt schema_version drift。")
    if artifact["artifact_type"] != "srtp_rcp_screening_prompt_package":
        raise ValueError("RCP prompt artifact_type drift。")
    if artifact["protocol_id"] != RCP_PROTOCOL_ID or artifact["status"] != "frozen":
        raise ValueError("RCP prompt protocol/status drift。")
    if artifact["primary_information"] != [
        "frozen_research_question",
        "frozen_topic_boundary",
        "opaque_candidate_id",
        "exact_title",
        "exact_abstract",
    ]:
        raise ValueError("RCP prompt primary information boundary drift。")
    _text(artifact["instruction_text"], "prompt instruction text")
    definitions = _mapping(
        artifact["relevance_definitions"], "prompt relevance definitions"
    )
    if set(definitions) != {"0", "1", "2", "abstain"}:
        raise ValueError("RCP relevance definitions drift。")
    if _mapping(artifact["boundary_definitions"], "boundary definitions") != {
        dimension: ["match", "mismatch", "unclear", "not_stated"]
        for dimension in BOUNDARY_DIMENSIONS
    }:
        raise ValueError("RCP boundary definitions drift。")
    output_contract = _mapping(artifact["output_contract"], "output contract")
    if output_contract.get("numeric_confidence") is not False:
        raise ValueError("RCP Primary 不允许 numerical confidence。")
    if output_contract.get("one_candidate_per_judgement") is not True:
        raise ValueError("RCP prompt 必须一条 judgement 对应一个 candidate。")
    _bool(artifact["external_lookup"], "prompt external_lookup", expected=False)
    if artifact["reason_policy"] != {
        "maximum_unicode_characters": 240,
        "short_auditable_summary_only": True,
    }:
        raise ValueError("RCP reason policy drift。")
    if artifact["evidence_span_policy"] != {
        "minimum": 1,
        "maximum": 2,
        "fields": ["title", "abstract"],
        "exact_offsets_required": True,
    }:
        raise ValueError("RCP evidence span policy drift。")
    if artifact["schema_repair_policy"] != {
        "maximum_attempts": 1,
        "schema_only": True,
        "rejudgement_forbidden": True,
        "second_failure_routes_human": True,
    }:
        raise ValueError("RCP schema repair policy drift。")
    if artifact["private_reasoning_policy"] != {
        "chain_of_thought_requested": False,
        "chain_of_thought_retained": False,
    }:
        raise ValueError("RCP private reasoning policy drift。")
    identity = compute_prompt_identity(artifact)
    if artifact["prompt_identity"] != identity:
        raise ValueError("RCP prompt identity drift。")
    if artifact["artifact_id"] != _artifact_id("srtp_rcp_prompt", identity):
        raise ValueError("RCP prompt artifact_id drift。")


def _validate_roster_template(template: Mapping[str, Any]) -> None:
    artifact = _mapping(dict(template), "RCP model roster template")
    _exact(
        artifact,
        {
            "schema_version",
            "artifact_type",
            "protocol_id",
            "status",
            "is_fixture",
            "instructions",
            "required_slots",
        },
        "RCP model roster template",
    )
    if (
        artifact["schema_version"] != RCP_SCHEMA_VERSION
        or artifact["artifact_type"] != "srtp_rcp_model_roster_template"
        or artifact["protocol_id"] != RCP_PROTOCOL_ID
        or artifact["status"] != "prepared_template_not_frozen"
    ):
        raise ValueError("RCP model roster template identity/status drift。")
    _bool(artifact["is_fixture"], "roster template is_fixture", expected=False)
    _text(artifact["instructions"], "roster template instructions")
    slots = _list(artifact["required_slots"], "required roster slots", nonempty=True)
    if [row.get("role") for row in slots if isinstance(row, dict)] != [
        "core",
        "core",
        "core",
        "sentinel",
        "sentinel",
    ]:
        raise ValueError("RCP roster template 必须声明 3 Core + 2 Sentinel。")
    if any(
        set(_mapping(row, "roster template slot"))
        != {"slot_id", "role", "fields_to_freeze"}
        for row in slots
    ):
        raise ValueError("RCP roster template slot fields drift。")


def _validate_rcp_config(config: Mapping[str, Any]) -> None:
    artifact = _mapping(dict(config), "RCP config")
    _exact(
        artifact,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "config_identity",
            "protocol_id",
            "protocol_version",
            "primary_method_id",
            "status",
            "is_fixture",
            "created_at",
            "inputs",
            "protocol",
            "panel",
            "model_identity_policy",
            "judgement_policy",
            "safe_zero_policy",
            "human_review_policy",
            "safe_zero_audit_policy",
            "final_selection_policy",
            "comparison_policy",
            "input_boundary",
        },
        "RCP config",
    )
    if artifact["schema_version"] != RCP_SCHEMA_VERSION:
        raise ValueError("RCP config schema_version drift。")
    if artifact["artifact_type"] != "srtp_reference_curation_config":
        raise ValueError("RCP config artifact_type drift。")
    if (
        artifact["protocol_id"] != RCP_PROTOCOL_ID
        or artifact["protocol_version"] != "RCP-v0.3"
        or artifact["primary_method_id"] != REFERENCE_METHOD_ID
        or artifact["status"] != "prepared_not_started"
    ):
        raise ValueError("RCP protocol/method/status drift。")
    _bool(artifact["is_fixture"], "RCP config is_fixture", expected=False)
    _datetime(artifact["created_at"], "RCP config created_at")
    identity = compute_rcp_config_identity(artifact)
    if artifact["config_identity"] != identity:
        raise ValueError("RCP config identity drift。")
    if artifact["artifact_id"] != _artifact_id("srtp_rcp_config", identity):
        raise ValueError("RCP config artifact_id drift。")

    protocol = _mapping(artifact["protocol"], "RCP protocol")
    required_protocol = {
        "selection_k": SELECTION_K,
        "primary_information": [
            "frozen_research_question",
            "frozen_topic_boundary",
            "opaque_candidate_id",
            "title",
            "abstract",
        ],
        "external_lookup": False,
        "fulltext_primary": False,
        "automatic_inclusion": "forbidden",
        "automatic_exclusion": "strict_safe_zero_only",
        "human_review_blind_first": True,
        "all_top8_human_review_required": True,
        "reference_claim": "auditable_internal_reference_selection",
    }
    if protocol != required_protocol:
        raise ValueError("RCP frozen protocol semantics drift。")
    panel = _mapping(artifact["panel"], "RCP panel")
    if panel != {
        "core_count": CORE_COUNT,
        "sentinel_count": SENTINEL_COUNT,
        "distinct_independence_groups": PANEL_COUNT,
        "distinct_model_families": PANEL_COUNT,
        "one_primary_instance_per_family": True,
        "same_family_versions_vote": False,
        "sentinels_vote_or_rank": False,
    }:
        raise ValueError("RCP panel policy drift。")
    identity_policy = _mapping(
        artifact["model_identity_policy"], "model identity policy"
    )
    if identity_policy != {
        "resolved_identity_required": True,
        "rolling_alias_may_be_requested": True,
        "rolling_alias_may_masquerade_as_snapshot": False,
        "snapshot_unavailable_requires_explicit_exception": True,
        "default_allow_snapshot_unavailable_exception": False,
        "downstream_generator_family_separation": True,
    }:
        raise ValueError("RCP model identity policy drift。")
    judgement = _mapping(artifact["judgement_policy"], "judgement policy")
    if judgement != {
        "relevance_values": [0, 1, 2],
        "abstain_uses_null_relevance": True,
        "uncertain_is_not_relevance_one": True,
        "boundary_dimensions": list(BOUNDARY_DIMENSIONS),
        "boundary_values": ["match", "mismatch", "unclear", "not_stated"],
        "evidence_span_minimum": 1,
        "evidence_span_maximum": 2,
        "reason_summary_maximum_unicode_characters": 240,
        "numeric_confidence_decision_bearing": False,
        "maximum_schema_repair_attempts": 1,
    }:
        raise ValueError("RCP judgement policy drift。")
    safe_zero = _mapping(artifact["safe_zero_policy"], "safe-zero policy")
    if safe_zero != {
        "all_core_zero": True,
        "all_sentinel_zero": True,
        "no_abstain": True,
        "no_unclear_or_not_stated": True,
        "sufficient_evidence_required": True,
        "valid_spans_required": True,
        "shared_hard_mismatch_dimension_required": True,
        "status": "provisional_exclusion_only",
    }:
        raise ValueError("RCP strict safe-zero policy drift。")
    human = _mapping(artifact["human_review_policy"], "human review policy")
    if human != {
        "reviewer_slots": ["r1", "r2", "r3"],
        "h1_reviewers": ["r1", "r2"],
        "h1_scope": "non_safe_zero_plus_audit_cases",
        "h1_blind": True,
        "h2_anonymized_evidence_only": True,
        "r3_blind_h1_before_h2": True,
        "final_numeric_rule": "r1_r2_agreement_else_three_label_median",
        "persistent_defer_at_frontier": "reference_not_freezable",
    }:
        raise ValueError("RCP human review policy drift。")
    audit = _mapping(artifact["safe_zero_audit_policy"], "audit policy")
    if audit != {
        "assumed_error_fraction": 0.1,
        "miss_probability_maximum": 0.05,
        "sampling_algorithm": "sha256_protocol_topic_candidate_seed_v1",
        "audit_seed": "srtp-rcp-v0.3-safe-zero-audit-v1",
        "confirmed_discrepancy_action": "review_all_remaining_safe_zero",
    }:
        raise ValueError("RCP safe-zero audit policy drift。")
    final = _mapping(artifact["final_selection_policy"], "final selection policy")
    if final != {
        "k": SELECTION_K,
        "cutoff_blind_reviewers": ["r1", "r2"],
        "cutoff_intersection_priority": True,
        "cutoff_r3_full_tie_group_priority": True,
        "eligible_human_relevance": [1, 2],
        "primary_ordering": [
            "final_human_relevance_desc",
            "n_core_label_2_desc",
            "n_core_label_ge_1_desc",
        ],
        "sentinel_rank_signal": False,
        "cutoff_hash_tiebreak": "mechanical_last_resort_only",
        "one_swap_frontier_ranks": [8, 9, 10],
    }:
        raise ValueError("RCP final selection policy drift。")
    comparison = _mapping(artifact["comparison_policy"], "comparison policy")
    if comparison != {
        "bm25_method_id": BM25_METHOD_ID,
        "reference_method_id": REFERENCE_METHOD_ID,
        "bm25_execution_policy": "after_reference_selection_freeze",
        "same_context_policy_required": True,
        "downstream_generator_family": None,
        "sensitivity_only_family_overlap_allowed": False,
    }:
        raise ValueError("RCP comparison policy drift。")
    boundary = _mapping(artifact["input_boundary"], "RCP input boundary")
    expected_false = {
        "live_api_allowed",
        "real_model_judgements_started",
        "real_human_review_started",
        "formal_reference_generated",
        "formal_bm25_generated",
        "matched_experimental_context_generated",
        "fulltext_primary_allowed",
        "hidden_topics_allowed",
        "hidden_labels_allowed",
    }
    _exact(boundary, expected_false, "RCP input boundary")
    for field in expected_false:
        _bool(boundary[field], f"RCP input boundary {field}", expected=False)


def load_reference_curation_inputs(
    config_path: str | Path,
    *,
    project_root: str | Path,
) -> ReferenceCurationInputs:
    root = Path(project_root).resolve()
    resolved_config = Path(config_path)
    if not resolved_config.is_absolute():
        resolved_config = (root / resolved_config).resolve()
    config = load_json_object(resolved_config, label="RCP config")
    _validate_rcp_config(config)
    inputs = _mapping(config["inputs"], "RCP inputs")
    _exact(
        inputs,
        {"selection_context_config", "prompt_package", "roster_template"},
        "RCP inputs",
    )

    selection_ref = _mapping(
        inputs["selection_context_config"], "selection context config reference"
    )
    _exact(
        selection_ref,
        {"path", "artifact_id", "config_identity", "sha256"},
        "selection context config reference",
    )
    selection_path = _resolve_repo_path(root, selection_ref["path"], "selection config")
    if sha256_file(selection_path) != selection_ref["sha256"]:
        raise ValueError("RCP selection-context config hash drift。")
    pilot_inputs = load_pilot_selection_inputs(selection_path, project_root=root)
    if (
        pilot_inputs.config["artifact_id"] != selection_ref["artifact_id"]
        or pilot_inputs.config["config_identity"] != selection_ref["config_identity"]
    ):
        raise ValueError("RCP selection-context config identity drift。")

    prompt_ref = _mapping(inputs["prompt_package"], "prompt package reference")
    _exact(
        prompt_ref,
        {"path", "artifact_id", "prompt_identity", "sha256"},
        "prompt package reference",
    )
    prompt_path = _resolve_repo_path(root, prompt_ref["path"], "prompt package path")
    prompt = load_json_object(prompt_path, label="RCP prompt package")
    _validate_prompt_package(prompt)
    if (
        sha256_file(prompt_path) != prompt_ref["sha256"]
        or prompt["artifact_id"] != prompt_ref["artifact_id"]
        or prompt["prompt_identity"] != prompt_ref["prompt_identity"]
    ):
        raise ValueError("RCP prompt package reference drift。")

    template_ref = _mapping(inputs["roster_template"], "roster template reference")
    _exact(template_ref, {"path", "sha256"}, "roster template reference")
    template_path = _resolve_repo_path(
        root, template_ref["path"], "roster template path"
    )
    template = load_json_object(template_path, label="RCP roster template")
    _validate_roster_template(template)
    if sha256_file(template_path) != template_ref["sha256"]:
        raise ValueError("RCP roster template hash drift。")
    return ReferenceCurationInputs(
        project_root=root,
        config_path=resolved_config,
        config=config,
        pilot_inputs=pilot_inputs,
        prompt_path=prompt_path,
        prompt_package=prompt,
        roster_template_path=template_path,
        roster_template=template,
    )


def validate_reference_preparation_package(
    package_dir: str | Path,
    *,
    config_path: str | Path,
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    package = Path(package_dir)
    if not package.is_absolute():
        package = (root / package).resolve()
    manifest_path = package / "manifest.json"
    manifest = load_json_object(manifest_path, label="RCP preparation manifest")
    _exact(
        manifest,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "package_identity",
            "protocol_id",
            "pilot_version",
            "primary_method_id",
            "status",
            "is_fixture",
            "created_at",
            "config",
            "u80",
            "files",
            "legacy_dual_curator_preparation",
            "model_roster_status",
            "real_execution_status",
        },
        "RCP preparation manifest",
    )
    if (
        manifest["schema_version"] != RCP_SCHEMA_VERSION
        or manifest["artifact_type"] != "srtp_rcp_preparation_manifest"
        or manifest["protocol_id"] != RCP_PROTOCOL_ID
        or manifest["pilot_version"] != PILOT_VERSION
        or manifest["primary_method_id"] != REFERENCE_METHOD_ID
        or manifest["status"] != "prepared_not_started"
        or manifest["model_roster_status"] != "template_only_real_roster_not_frozen"
    ):
        raise ValueError("RCP preparation protocol/status drift。")
    _bool(manifest["is_fixture"], "RCP preparation is_fixture", expected=False)
    _datetime(manifest["created_at"], "RCP preparation created_at")
    rcp_inputs = load_reference_curation_inputs(config_path, project_root=root)
    config_ref = _mapping(manifest["config"], "preparation config reference")
    expected_config_ref = {
        "path": rcp_inputs.config_path.relative_to(root).as_posix(),
        "artifact_id": rcp_inputs.config["artifact_id"],
        "config_identity": rcp_inputs.config["config_identity"],
        "sha256": sha256_file(rcp_inputs.config_path),
    }
    if config_ref != expected_config_ref:
        raise ValueError("RCP preparation config reference drift。")
    if manifest["u80"] != _u80_reference(rcp_inputs.pilot_inputs):
        raise ValueError("RCP preparation U80 identity/hash drift。")
    files = _mapping(manifest["files"], "RCP preparation files")
    actual_files = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual_files != set(files):
        raise ValueError("RCP preparation package file closure drift。")
    for relative, expected_hash in files.items():
        if sha256_file(package / relative) != expected_hash:
            raise ValueError(f"RCP preparation file hash drift：{relative}。")
    legacy = _mapping(
        manifest["legacy_dual_curator_preparation"], "legacy curator reference"
    )
    legacy_path = _resolve_repo_path(root, legacy["path"], "legacy curator path")
    if (
        sha256_file(legacy_path) != legacy["sha256"]
        or legacy["status"] != "preserved_historical_prepared_artifact"
    ):
        raise ValueError("Dual-Curator v0.2 historical package binding drift。")
    if set(manifest["real_execution_status"].values()) != {"not_started"}:
        raise ValueError("RCP preparation package 不得冒充真实 execution 已开始。")
    identity = _identity_without(
        manifest,
        prefix="srtp-rcp-preparation",
        omitted={"artifact_id", "package_identity"},
    )
    if manifest["package_identity"] != identity or manifest[
        "artifact_id"
    ] != _artifact_id("srtp_rcp_preparation", identity):
        raise ValueError("RCP preparation package identity drift。")
    return {
        "artifact_id": manifest["artifact_id"],
        "package_identity": identity,
        "manifest_sha256": sha256_file(manifest_path),
        "status": manifest["status"],
        "real_model_judgements_started": False,
    }


def compute_model_roster_identity(roster: Mapping[str, Any]) -> str:
    return _identity_without(
        roster,
        prefix=ROSTER_IDENTITY_PREFIX,
        omitted={"artifact_id", "roster_identity"},
    )


def validate_model_roster(
    roster: Mapping[str, Any],
    *,
    inputs: ReferenceCurationInputs,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    artifact = _mapping(dict(roster), "RCP model roster")
    _exact(
        artifact,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "roster_identity",
            "protocol_id",
            "protocol_config_identity",
            "status",
            "frozen_at",
            "downstream_generator_family",
            "run_scope",
            "allow_snapshot_unavailable_exception",
            "entries",
            "is_fixture",
            "provenance",
        },
        "RCP model roster",
    )
    if (
        artifact["schema_version"] != RCP_SCHEMA_VERSION
        or artifact["artifact_type"] != "srtp_rcp_model_roster"
        or artifact["protocol_id"] != RCP_PROTOCOL_ID
        or artifact["protocol_config_identity"] != inputs.config["config_identity"]
        or artifact["status"] != "frozen"
    ):
        raise ValueError("RCP model roster protocol/status drift。")
    is_fixture = _bool(artifact["is_fixture"], "model roster is_fixture")
    if is_fixture and not allow_fixture:
        raise ValueError("正式 RCP execution 不接受 fixture model roster。")
    _datetime(artifact["frozen_at"], "model roster frozen_at")
    run_scope = _text(artifact["run_scope"], "model roster run_scope")
    if run_scope not in {"primary", "sensitivity_only", "plumbing_only"}:
        raise ValueError("RCP model roster run_scope 非法。")
    if is_fixture != (run_scope == "plumbing_only"):
        raise ValueError("fixture roster 必须且只能使用 plumbing_only scope。")
    allow_unavailable = _bool(
        artifact["allow_snapshot_unavailable_exception"],
        "snapshot unavailable exception",
    )
    if allow_unavailable and run_scope == "primary":
        raise ValueError("Primary roster 不得静默允许 snapshot unavailable。")
    downstream = artifact["downstream_generator_family"]
    if downstream is not None:
        downstream = _text(downstream, "downstream generator family")

    provenance = _mapping(artifact["provenance"], "model roster provenance")
    _exact(
        provenance,
        {"created_by", "created_at", "git_revision"},
        "model roster provenance",
    )
    _text(provenance["created_by"], "model roster created_by")
    _datetime(provenance["created_at"], "model roster created_at")
    _git_revision(provenance["git_revision"], "model roster git_revision")

    entries = _list(artifact["entries"], "model roster entries", nonempty=True)
    if len(entries) != PANEL_COUNT:
        raise ValueError("RCP model roster 必须精确包含 3 Core + 2 Sentinel。")
    entry_ids: set[str] = set()
    families: set[str] = set()
    groups: set[str] = set()
    actual_model_identities: set[tuple[str, str, str]] = set()
    roles: Counter[str] = Counter()
    validated_entries: dict[str, dict[str, Any]] = {}
    for raw in entries:
        entry = _mapping(raw, "model roster entry")
        _exact(
            entry,
            {
                "roster_entry_id",
                "role",
                "provider",
                "model_family",
                "independence_group",
                "requested_model_id",
                "requested_model_id_type",
                "provider_reported_model_id",
                "resolved_model_id",
                "resolved_identity_confirmed",
                "snapshot_version",
                "snapshot_guarantee",
                "execution_config",
                "execution_config_sha256",
                "status",
            },
            "model roster entry",
        )
        entry_id = _text(entry["roster_entry_id"], "roster_entry_id")
        if entry_id in entry_ids:
            raise ValueError("RCP roster_entry_id 重复。")
        entry_ids.add(entry_id)
        role = _text(entry["role"], "model role")
        if role not in MODEL_ROLES:
            raise ValueError("RCP model role 必须是 core/sentinel。")
        roles[role] += 1
        provider = _text(entry["provider"], "model provider")
        family = _text(entry["model_family"], "model family")
        group = _text(entry["independence_group"], "independence group")
        if family in families or group in groups:
            raise ValueError(
                "RCP 五个 voter 必须来自 distinct family/independence_group。"
            )
        families.add(family)
        groups.add(group)
        requested = _text(entry["requested_model_id"], "requested model id")
        requested_type = _text(
            entry["requested_model_id_type"], "requested model id type"
        )
        if requested_type not in {"exact_version", "rolling_alias"}:
            raise ValueError("requested_model_id_type 非法。")
        reported = _text(
            entry["provider_reported_model_id"], "provider reported model id"
        )
        resolved = _text(entry["resolved_model_id"], "resolved model id")
        if reported != resolved:
            raise ValueError(
                "provider-reported model identity 与 frozen resolved identity 不一致。"
            )
        if requested_type == "exact_version" and requested != resolved:
            raise ValueError(
                "requested exact model identity 与 resolved identity 不一致。"
            )
        _bool(
            entry["resolved_identity_confirmed"],
            "resolved identity confirmed",
            expected=True,
        )
        guarantee = _text(entry["snapshot_guarantee"], "snapshot guarantee")
        if guarantee not in {"immutable", "provider_versioned", "unavailable"}:
            raise ValueError("snapshot_guarantee 非法。")
        snapshot = entry["snapshot_version"]
        if guarantee == "unavailable":
            if snapshot is not None:
                raise ValueError("snapshot unavailable 时不得伪造 snapshot_version。")
            if not allow_unavailable:
                raise ValueError("snapshot unavailable 缺少显式 protocol exception。")
        else:
            snapshot = _text(snapshot, "snapshot version")
        actual_identity = (
            provider.strip().casefold(),
            resolved.strip().casefold(),
            "" if snapshot is None else snapshot.strip().casefold(),
        )
        if actual_identity in actual_model_identities:
            raise ValueError(
                "RCP formal model roster 包含重复 actual model identity "
                "(provider + resolved model + snapshot/version)。"
            )
        actual_model_identities.add(actual_identity)
        if requested_type == "rolling_alias" and resolved == requested:
            raise ValueError(
                "rolling alias 未解析成可确认 identity；不得冒充 exact snapshot。"
            )
        if not is_fixture and any(
            value.casefold().startswith("fixture")
            for value in (
                requested,
                reported,
                resolved,
            )
        ):
            raise ValueError("正式 roster 不得使用 fixture model identity。")
        execution = _mapping(entry["execution_config"], "execution config")
        if canonical_json_sha256(execution) != entry["execution_config_sha256"]:
            raise ValueError("model execution_config hash drift。")
        if entry["status"] != "frozen":
            raise ValueError("正式 roster entry 必须 frozen。")
        if downstream == family:
            allowed_overlap = (
                run_scope == "sensitivity_only"
                and inputs.config["comparison_policy"][
                    "sensitivity_only_family_overlap_allowed"
                ]
            )
            if not allowed_overlap:
                raise ValueError(
                    "Reference panel 与 downstream generator family 重叠。"
                )
        validated_entries[entry_id] = entry
    if roles != Counter({"core": CORE_COUNT, "sentinel": SENTINEL_COUNT}):
        raise ValueError("RCP model roster 必须精确为 3 Core + 2 Sentinel。")
    identity = compute_model_roster_identity(artifact)
    if artifact["roster_identity"] != identity:
        raise ValueError("RCP model roster identity drift。")
    if artifact["artifact_id"] != _artifact_id("srtp_rcp_roster", identity):
        raise ValueError("RCP model roster artifact_id drift。")
    return {
        "artifact_id": artifact["artifact_id"],
        "roster_identity": identity,
        "sha256": payload_sha256(artifact),
        "entries": validated_entries,
        "is_fixture": is_fixture,
        "run_scope": run_scope,
    }


def build_model_roster(
    *,
    inputs: ReferenceCurationInputs,
    entries: Sequence[Mapping[str, Any]],
    frozen_at: str,
    git_revision: str,
    created_by: str,
    downstream_generator_family: str | None = None,
    run_scope: str = "primary",
    allow_snapshot_unavailable_exception: bool = False,
    is_fixture: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_model_roster",
        "artifact_id": "pending",
        "roster_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "protocol_config_identity": inputs.config["config_identity"],
        "status": "frozen",
        "frozen_at": _datetime(frozen_at, "roster frozen_at"),
        "downstream_generator_family": downstream_generator_family,
        "run_scope": run_scope,
        "allow_snapshot_unavailable_exception": allow_snapshot_unavailable_exception,
        "entries": [copy.deepcopy(dict(entry)) for entry in entries],
        "is_fixture": is_fixture,
        "provenance": {
            "created_by": _text(created_by, "roster created_by"),
            "created_at": frozen_at,
            "git_revision": _git_revision(git_revision, "roster git revision"),
        },
    }
    identity = compute_model_roster_identity(payload)
    payload["roster_identity"] = identity
    payload["artifact_id"] = _artifact_id("srtp_rcp_roster", identity)
    validate_model_roster(payload, inputs=inputs, allow_fixture=is_fixture)
    return payload


def _topic_boundary(
    pilot_inputs: PilotSelectionInputs, topic_id: str
) -> dict[str, Any]:
    topic = pilot_inputs.topics[topic_id]
    return {
        "scientific_object": topic["scientific_object"],
        "data_modality": topic["data_modality"],
        "target_task": topic["target_task"],
        "method_role": topic["method_role"],
        "scope_in": copy.deepcopy(topic["scope_in"]),
        "scope_out": copy.deepcopy(topic["scope_out"]),
        "boundary_cases": copy.deepcopy(topic["boundary_cases"]),
    }


def _visible_topic(pilot_inputs: PilotSelectionInputs, topic_id: str) -> dict[str, Any]:
    topic = topic_config(pilot_inputs, topic_id)
    return {
        "topic_id": topic_id,
        "question_id": topic["question_id"],
        "research_question": topic["research_question"],
        "research_question_identity": topic["research_question_identity"],
        "boundary": _topic_boundary(pilot_inputs, topic_id),
    }


def _u80_reference(pilot_inputs: PilotSelectionInputs) -> dict[str, str]:
    ref = pilot_inputs.config["inputs"]["u80"]
    return {
        "artifact_id": ref["artifact_id"],
        "u80_identity": ref["u80_identity"],
        "sha256": ref["sha256"],
    }


def _prompt_reference(inputs: ReferenceCurationInputs) -> dict[str, str]:
    return {
        "artifact_id": inputs.prompt_package["artifact_id"],
        "prompt_identity": inputs.prompt_package["prompt_identity"],
        "sha256": sha256_file(inputs.prompt_path),
    }


def _source_snapshot(
    pilot_inputs: PilotSelectionInputs,
    topic_id: str,
    canonical_entity_id: str,
) -> dict[str, str]:
    item = pilot_inputs.view_by_topic_entity[(topic_id, canonical_entity_id)]
    snapshot = {
        "selection_item_id": _text(item.get("selection_item_id"), "selection_item_id"),
        "title": _text(item.get("title"), "candidate title"),
        "abstract": _text(item.get("abstract"), "candidate abstract"),
    }
    return {**snapshot, "source_snapshot_sha256": payload_sha256(snapshot)}


def _model_run_id(
    *,
    roster_identity: str,
    roster_entry_id: str,
    topic_id: str,
    is_fixture: bool,
) -> str:
    identity = deterministic_identity(
        "srtp-rcp-model-run",
        {
            "protocol_id": RCP_PROTOCOL_ID,
            "roster_identity": roster_identity,
            "roster_entry_id": roster_entry_id,
            "topic_id": topic_id,
            "is_fixture": is_fixture,
        },
    )
    return f"rcp_run_{identity.rsplit(':', 1)[-1][:24]}"


def _opaque_candidate_id(
    *,
    model_run_id: str,
    canonical_entity_id: str,
    seed: str,
) -> str:
    digest = hashlib.sha256(
        f"{seed}|{model_run_id}|{canonical_entity_id}".encode("utf-8")
    ).hexdigest()
    return f"candidate_{digest[:20]}"


def _task_input_payload(task: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "protocol_id": task["protocol_id"],
        "model_run_id": task["model_run_id"],
        "topic": copy.deepcopy(task["topic"]),
        "candidate": copy.deepcopy(task["candidate"]),
        "prompt_package": copy.deepcopy(task["prompt_package"]),
        "external_lookup": task["external_lookup"],
    }


def _task_identity_payload(task: Mapping[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dict(task))
    body.pop("artifact_id", None)
    body.pop("task_identity", None)
    return body


def build_ai_task_package(
    *,
    inputs: ReferenceCurationInputs,
    roster: Mapping[str, Any],
    roster_entry_id: str,
    topic_id: str,
    created_at: str,
    git_revision: str,
    allow_fixture: bool = False,
    _skip_validation: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validated_roster = validate_model_roster(
        roster, inputs=inputs, allow_fixture=allow_fixture
    )
    entry = validated_roster["entries"].get(roster_entry_id)
    if entry is None:
        raise ValueError("RCP task export 使用了 roster 外 model entry。")
    pilot_inputs = inputs.pilot_inputs
    if topic_id not in pilot_inputs.u80_by_topic:
        raise ValueError("RCP task export Topic 不属于 frozen Pilot U80。")
    is_fixture = validated_roster["is_fixture"]
    run_id = _model_run_id(
        roster_identity=validated_roster["roster_identity"],
        roster_entry_id=roster_entry_id,
        topic_id=topic_id,
        is_fixture=is_fixture,
    )
    topic = _visible_topic(pilot_inputs, topic_id)
    prompt_ref = _prompt_reference(inputs)
    task_seed = inputs.config["judgement_policy"].get(
        "opaque_candidate_seed", "srtp-rcp-v0.3-model-opaque-v1"
    )
    order_seed = "srtp-rcp-v0.3-model-task-order-v1"
    rows: list[tuple[str, str, dict[str, str]]] = []
    for canonical_id in pilot_inputs.u80_by_topic[topic_id]:
        candidate_id = _opaque_candidate_id(
            model_run_id=run_id,
            canonical_entity_id=canonical_id,
            seed=task_seed,
        )
        snapshot = _source_snapshot(pilot_inputs, topic_id, canonical_id)
        order_key = hashlib.sha256(
            f"{order_seed}|{run_id}|{canonical_id}".encode("utf-8")
        ).hexdigest()
        rows.append(
            (order_key, canonical_id, {"candidate_id": candidate_id, **snapshot})
        )
    rows.sort(key=lambda row: (row[0], row[1]))

    tasks: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    for position, (order_key, canonical_id, source) in enumerate(rows, start=1):
        task: dict[str, Any] = {
            "schema_version": RCP_SCHEMA_VERSION,
            "artifact_type": "srtp_rcp_ai_screening_task",
            "artifact_id": "pending",
            "task_identity": "pending",
            "protocol_id": RCP_PROTOCOL_ID,
            "model_run_id": run_id,
            "topic": copy.deepcopy(topic),
            "candidate": {
                "candidate_id": source["candidate_id"],
                "title": source["title"],
                "abstract": source["abstract"],
            },
            "prompt_package": copy.deepcopy(prompt_ref),
            "input_sha256": "pending",
            "external_lookup": False,
            "is_fixture": is_fixture,
        }
        task["input_sha256"] = canonical_json_sha256(_task_input_payload(task))
        identity = deterministic_identity(
            TASK_IDENTITY_PREFIX, _task_identity_payload(task)
        )
        task["task_identity"] = identity
        task["artifact_id"] = _artifact_id("srtp_rcp_ai_task", identity)
        tasks.append(task)
        mapping_rows.append(
            {
                "position": position,
                "order_key_sha256": order_key,
                "candidate_id": source["candidate_id"],
                "canonical_entity_id": canonical_id,
                "selection_item_id": source["selection_item_id"],
                "source_snapshot_sha256": source["source_snapshot_sha256"],
                "task_artifact_id": task["artifact_id"],
                "task_identity": task["task_identity"],
                "input_sha256": task["input_sha256"],
            }
        )

    created = _datetime(created_at, "AI task package created_at")
    revision = _git_revision(git_revision, "AI task package git_revision")
    package: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_ai_task_package",
        "artifact_id": "pending",
        "package_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "model_run_id": run_id,
        "roster": {
            "artifact_id": validated_roster["artifact_id"],
            "roster_identity": validated_roster["roster_identity"],
            "sha256": validated_roster["sha256"],
        },
        "topic": {
            "topic_id": topic_id,
            "question_id": topic["question_id"],
            "research_question_identity": topic["research_question_identity"],
        },
        "u80": _u80_reference(pilot_inputs),
        "prompt_package": prompt_ref,
        "candidate_count": U80_COUNT,
        "tasks": tasks,
        "status": "prepared_not_started",
        "created_at": created,
        "provenance": {
            "created_by": "src.pilot_reference_curation",
            "created_at": created,
            "git_revision": revision,
        },
        "is_fixture": is_fixture,
        "purpose": "plumbing_only"
        if is_fixture
        else "external_independent_model_screening",
    }
    package_identity = _identity_without(
        package,
        prefix=TASK_PACKAGE_IDENTITY_PREFIX,
        omitted={"artifact_id", "package_identity"},
    )
    package["package_identity"] = package_identity
    package["artifact_id"] = _artifact_id("srtp_rcp_ai_tasks", package_identity)

    mapping: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_ai_task_map",
        "artifact_id": "pending",
        "map_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "model_run_id": run_id,
        "task_package": _artifact_reference(package),
        "roster_entry_id": roster_entry_id,
        "topic_id": topic_id,
        "u80": _u80_reference(pilot_inputs),
        "candidate_map": mapping_rows,
        "is_fixture": is_fixture,
        "visibility": "private_coordinator_only",
    }
    map_identity = _identity_without(
        mapping,
        prefix=TASK_MAP_IDENTITY_PREFIX,
        omitted={"artifact_id", "map_identity"},
    )
    mapping["map_identity"] = map_identity
    mapping["artifact_id"] = _artifact_id("srtp_rcp_ai_map", map_identity)
    if not _skip_validation:
        validate_ai_task_package(
            package,
            mapping=mapping,
            roster=roster,
            inputs=inputs,
            allow_fixture=allow_fixture,
        )
    return package, mapping


def validate_ai_task_package(
    package: Mapping[str, Any],
    *,
    mapping: Mapping[str, Any],
    roster: Mapping[str, Any],
    inputs: ReferenceCurationInputs,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    artifact = _mapping(dict(package), "AI task package")
    private_map = _mapping(dict(mapping), "AI task map")
    validated_roster = validate_model_roster(
        roster, inputs=inputs, allow_fixture=allow_fixture
    )
    if artifact.get("protocol_id") != RCP_PROTOCOL_ID:
        raise ValueError("AI task package wrong protocol。")
    topic_id = _mapping(artifact.get("topic"), "AI task package topic").get("topic_id")
    roster_summary = _mapping(artifact.get("roster"), "AI task package roster")
    if roster_summary != {
        "artifact_id": validated_roster["artifact_id"],
        "roster_identity": validated_roster["roster_identity"],
        "sha256": validated_roster["sha256"],
    }:
        raise ValueError("AI task package roster binding drift。")
    entry_id = private_map.get("roster_entry_id")
    if entry_id not in validated_roster["entries"]:
        raise ValueError("AI task package unexpected model。")
    expected_package, expected_map = build_ai_task_package(
        inputs=inputs,
        roster=roster,
        roster_entry_id=entry_id,
        topic_id=topic_id,
        created_at=artifact.get("created_at"),
        git_revision=_mapping(artifact.get("provenance"), "task provenance").get(
            "git_revision"
        ),
        allow_fixture=allow_fixture,
        _skip_validation=True,
    )
    if artifact != expected_package or private_map != expected_map:
        raise ValueError(
            "AI task package/map 与 frozen U80 deterministic reconstruction drift。"
        )
    forbidden = _all_keys(artifact) & AI_TASK_FORBIDDEN_KEYS
    if forbidden:
        raise ValueError(
            "AI task package 泄露 forbidden fields：" + ", ".join(sorted(forbidden))
        )
    tasks = _list(artifact["tasks"], "AI tasks", nonempty=True)
    if len(tasks) != U80_COUNT:
        raise ValueError("AI task package 必须精确覆盖 80 candidates。")
    if any(
        set(_mapping(task, "AI task")["candidate"])
        != {"candidate_id", "title", "abstract"}
        for task in tasks
    ):
        raise ValueError("AI model-facing candidate fields drift。")
    return {
        "artifact_id": artifact["artifact_id"],
        "package_identity": artifact["package_identity"],
        "sha256": payload_sha256(artifact),
        "map_sha256": payload_sha256(private_map),
        "model_run_id": artifact["model_run_id"],
        "roster_entry_id": entry_id,
        "topic_id": topic_id,
        "is_fixture": artifact["is_fixture"],
    }


def render_ai_execution_instructions() -> str:
    return """# RCP-v0.3 External Model Screening

This bundle contains independent, one-candidate Title+Abstract tasks. Process
each task separately with the frozen prompt package. Do not use web search,
full text, DOI/title lookup, another model's answer, BM25 output, or human
judgements. Return only the structured response contract; do not provide or
retain private chain-of-thought. Keep provider raw responses outside the Git
repository and retain their SHA-256 values for import.

The task bundle is not a ranking exercise. Do not compare candidates or choose
a Top-8. Every candidate receives an independent 0/1/2 or abstain judgement.
"""


def build_model_response_template(task: Mapping[str, Any]) -> dict[str, Any]:
    candidate = _mapping(task.get("candidate"), "AI task candidate")
    return {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_model_judgement_response",
        "protocol_id": RCP_PROTOCOL_ID,
        "model_run_id": task["model_run_id"],
        "topic_id": task["topic"]["topic_id"],
        "candidate_id": candidate["candidate_id"],
        "task_identity": task["task_identity"],
        "input_sha256": task["input_sha256"],
        "judgement": {
            "relevance": None,
            "abstain": True,
            "boundary": {dimension: "not_stated" for dimension in BOUNDARY_DIMENSIONS},
            "evidence_sufficiency": "insufficient",
            "uncertainty_codes": ["replace_with_short_machine_code"],
            "exclusion_or_boundary_codes": [],
            "evidence_spans": [],
            "reason_summary": "Replace with a short auditable summary (maximum 240 characters).",
        },
        "external_lookup": False,
    }


def export_ai_task_package(
    *,
    package: Mapping[str, Any],
    mapping: Mapping[str, Any],
    roster: Mapping[str, Any],
    inputs: ReferenceCurationInputs,
    model_output_dir: str | Path,
    coordinator_map_output: str | Path,
    allow_fixture: bool = False,
) -> dict[str, str]:
    validate_ai_task_package(
        package,
        mapping=mapping,
        roster=roster,
        inputs=inputs,
        allow_fixture=allow_fixture,
    )
    output = validate_external_output_path(
        model_output_dir,
        project_root=inputs.project_root,
        label="RCP model-facing task output",
    )
    coordinator = validate_external_output_path(
        coordinator_map_output,
        project_root=inputs.project_root,
        label="RCP private coordinator map output",
    )
    validate_visible_private_output_isolation(output, coordinator)
    if output.exists() and any(output.iterdir()):
        raise ValueError("RCP model-facing output directory 必须不存在或为空。")
    if coordinator.exists():
        raise ValueError("RCP coordinator map output 已存在；禁止覆盖。")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "task_package.json", package)
    write_json(output / "prompt_package.json", inputs.prompt_package)
    write_json(
        output / "response_template.json",
        build_model_response_template(package["tasks"][0]),
    )
    (output / "AI_EXECUTION_INSTRUCTIONS.md").write_text(
        render_ai_execution_instructions(), encoding="utf-8", newline="\n"
    )
    write_json(coordinator, mapping)
    return {
        "model_output_dir": str(output),
        "task_package": str(output / "task_package.json"),
        "coordinator_map": str(coordinator),
    }


def validate_visible_private_output_isolation(
    visible_output_dir: str | Path,
    private_map_output: str | Path,
) -> tuple[Path, Path]:
    """Keep a reviewer/model-visible bundle outside the private mapping tree."""

    visible = Path(visible_output_dir).resolve()
    private_map = Path(private_map_output).resolve()
    private_root = private_map.parent

    def _is_within(path: Path, directory: Path) -> bool:
        try:
            path.relative_to(directory)
        except ValueError:
            return False
        return True

    if _is_within(private_map, visible) or _is_within(visible, private_root):
        raise ValueError(
            "RCP visible bundle 与 private coordinator mapping 必须位于隔离目录；"
            "不得互相包含。"
        )
    return visible, private_map


def build_evidence_span(
    task: Mapping[str, Any],
    *,
    field: str,
    start_char: int,
    end_char: int,
) -> dict[str, Any]:
    if field not in {"title", "abstract"}:
        raise ValueError("evidence span field 必须是 title/abstract。")
    source = _text(_mapping(task["candidate"], "task candidate")[field], field)
    start = _integer(start_char, "span start_char")
    end = _integer(end_char, "span end_char")
    if end <= start or end > len(source):
        raise ValueError("evidence span offset 越界。")
    text = source[start:end]
    return {
        "field": field,
        "start_char": start,
        "end_char": end,
        "text": text,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _validate_evidence_spans(
    spans: Any,
    *,
    task: Mapping[str, Any],
    minimum: int,
    maximum: int = 2,
) -> list[dict[str, Any]]:
    rows = _list(spans, "evidence spans")
    if not minimum <= len(rows) <= maximum:
        raise ValueError(f"evidence spans 必须包含 {minimum}–{maximum} 项。")
    validated: list[dict[str, Any]] = []
    for raw in rows:
        span = _mapping(raw, "evidence span")
        _exact(
            span,
            {"field", "start_char", "end_char", "text", "content_sha256"},
            "evidence span",
        )
        field = _text(span["field"], "evidence span field")
        expected = build_evidence_span(
            task,
            field=field,
            start_char=_integer(span["start_char"], "span start_char"),
            end_char=_integer(span["end_char"], "span end_char"),
        )
        if span != expected:
            raise ValueError("evidence span 未精确对应 frozen Title/Abstract。")
        validated.append(span)
    return validated


def validate_model_judgement_response(
    response: Mapping[str, Any],
    *,
    task: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = _mapping(dict(response), "model judgement response")
    _exact(
        artifact,
        {
            "schema_version",
            "artifact_type",
            "protocol_id",
            "model_run_id",
            "topic_id",
            "candidate_id",
            "task_identity",
            "input_sha256",
            "judgement",
            "external_lookup",
        },
        "model judgement response",
    )
    if (
        artifact["schema_version"] != RCP_SCHEMA_VERSION
        or artifact["artifact_type"] != "srtp_rcp_model_judgement_response"
        or artifact["protocol_id"] != RCP_PROTOCOL_ID
    ):
        raise ValueError("model judgement wrong protocol/schema。")
    candidate = _mapping(task["candidate"], "AI task candidate")
    expected_bindings = {
        "model_run_id": task["model_run_id"],
        "topic_id": task["topic"]["topic_id"],
        "candidate_id": candidate["candidate_id"],
        "task_identity": task["task_identity"],
        "input_sha256": task["input_sha256"],
    }
    if any(
        artifact[field] != expected for field, expected in expected_bindings.items()
    ):
        raise ValueError("model judgement task/candidate/input binding drift。")
    _bool(artifact["external_lookup"], "model external_lookup", expected=False)
    forbidden_reasoning = _all_keys(artifact) & PRIVATE_REASONING_KEYS
    if forbidden_reasoning:
        raise ValueError("model judgement 不得保存 private chain-of-thought。")
    judgement = _mapping(artifact["judgement"], "model judgement")
    _exact(
        judgement,
        {
            "relevance",
            "abstain",
            "boundary",
            "evidence_sufficiency",
            "uncertainty_codes",
            "exclusion_or_boundary_codes",
            "evidence_spans",
            "reason_summary",
        },
        "model judgement",
    )
    abstain = _bool(judgement["abstain"], "model abstain")
    relevance = judgement["relevance"]
    if abstain:
        if relevance is not None:
            raise ValueError("abstain=true 时 relevance 必须是 null。")
    elif isinstance(relevance, bool) or relevance not in {0, 1, 2}:
        raise ValueError("非 abstain relevance 必须是 0/1/2。")
    boundary = _mapping(judgement["boundary"], "boundary judgement")
    _exact(boundary, set(BOUNDARY_DIMENSIONS), "boundary judgement")
    if any(value not in BOUNDARY_VALUES for value in boundary.values()):
        raise ValueError("boundary value 非法。")
    sufficiency = _text(judgement["evidence_sufficiency"], "evidence sufficiency")
    if sufficiency not in EVIDENCE_SUFFICIENCY_VALUES:
        raise ValueError("evidence_sufficiency 非法。")
    uncertainty = _strings(judgement["uncertainty_codes"], "uncertainty codes")
    exclusion = _strings(
        judgement["exclusion_or_boundary_codes"], "exclusion/boundary codes"
    )
    if any(
        not re.fullmatch(r"[a-z0-9][a-z0-9_:-]*", code)
        for code in uncertainty + exclusion
    ):
        raise ValueError("judgement codes 必须是稳定 machine-readable IDs。")
    _validate_evidence_spans(
        judgement["evidence_spans"], task=task, minimum=1, maximum=2
    )
    reason = _text(judgement["reason_summary"], "reason summary")
    if len(reason) > 240:
        raise ValueError("reason_summary 超过 240 Unicode characters。")
    uncertain_boundary = any(
        value in {"unclear", "not_stated"} for value in boundary.values()
    )
    if abstain:
        if not uncertainty or sufficiency != "insufficient":
            raise ValueError("abstain 必须记录 uncertainty 且 evidence insufficient。")
    elif uncertain_boundary or sufficiency != "sufficient":
        raise ValueError("无法可靠判断时必须 abstain；uncertain != relevance 1。")
    if relevance == 2 and any(value != "match" for value in boundary.values()):
        raise ValueError("relevance=2 要求四个必要维度全部 match。")
    if relevance == 0:
        mismatch_dimensions = {
            dimension for dimension, value in boundary.items() if value == "mismatch"
        }
        coded_dimensions = {
            HARD_MISMATCH_CODES[code]
            for code in exclusion
            if code in HARD_MISMATCH_CODES
        }
        if not mismatch_dimensions or not (mismatch_dimensions & coded_dimensions):
            raise ValueError(
                "relevance=0 必须有 hard mismatch code、dimension 与 supporting span。"
            )
    return {
        "candidate_id": artifact["candidate_id"],
        "relevance": relevance,
        "abstain": abstain,
        "boundary": copy.deepcopy(boundary),
        "evidence_sufficiency": sufficiency,
        "evidence_spans": copy.deepcopy(judgement["evidence_spans"]),
        "uncertainty_codes": tuple(uncertainty),
        "exclusion_or_boundary_codes": tuple(exclusion),
    }


def build_valid_response_envelope(
    response: Mapping[str, Any],
    *,
    raw_response_sha256: str,
    external_retention_reference: str,
    schema_repair_attempted: bool = False,
) -> dict[str, Any]:
    return {
        "status": "valid",
        "candidate_id": response["candidate_id"],
        "task_identity": response["task_identity"],
        "input_sha256": response["input_sha256"],
        "raw_response_sha256": _sha256(raw_response_sha256, "raw response SHA-256"),
        "external_retention_reference": _text(
            external_retention_reference, "external retention reference"
        ),
        "repair_provenance": {
            "attempted": schema_repair_attempted,
            "attempt_count": 1 if schema_repair_attempted else 0,
            "schema_only": schema_repair_attempted,
            "rejudgement_performed": False,
        },
        "response": copy.deepcopy(dict(response)),
        "validation_errors": [],
    }


def build_invalid_after_repair_envelope(
    task: Mapping[str, Any],
    *,
    raw_response_sha256: str,
    repaired_response_sha256: str,
    external_retention_reference: str,
    validation_errors: Sequence[str],
) -> dict[str, Any]:
    errors = [_text(error, "schema validation error") for error in validation_errors]
    if not errors:
        raise ValueError("invalid-after-repair outcome 必须记录 validation errors。")
    return {
        "status": "invalid_after_schema_repair",
        "candidate_id": task["candidate"]["candidate_id"],
        "task_identity": task["task_identity"],
        "input_sha256": task["input_sha256"],
        "raw_response_sha256": _sha256(raw_response_sha256, "raw response SHA-256"),
        "repaired_response_sha256": _sha256(
            repaired_response_sha256, "repaired response SHA-256"
        ),
        "external_retention_reference": _text(
            external_retention_reference, "external retention reference"
        ),
        "repair_provenance": {
            "attempted": True,
            "attempt_count": 1,
            "schema_only": True,
            "rejudgement_performed": False,
        },
        "response": None,
        "validation_errors": errors,
        "external_lookup": False,
    }


def build_response_envelopes_from_import_records(
    records: Sequence[Mapping[str, Any]],
    *,
    task_package: Mapping[str, Any],
) -> list[dict[str, Any]]:
    tasks = {
        task["candidate"]["candidate_id"]: task
        for task in _list(task_package.get("tasks"), "AI task package tasks")
    }
    envelopes: list[dict[str, Any]] = []
    for raw in records:
        record = _mapping(raw, "model import record")
        status = record.get("status")
        if status == "valid":
            _exact(
                record,
                {
                    "status",
                    "response",
                    "raw_response_sha256",
                    "external_retention_reference",
                    "schema_repair_attempted",
                },
                "valid model import record",
            )
            response = _mapping(record["response"], "structured model response")
            candidate_id = _text(
                response.get("candidate_id"), "model import candidate_id"
            )
            if candidate_id not in tasks:
                raise ValueError(
                    "model import record contains unknown opaque candidate ID。"
                )
            envelope = build_valid_response_envelope(
                response,
                raw_response_sha256=record["raw_response_sha256"],
                external_retention_reference=record["external_retention_reference"],
                schema_repair_attempted=_bool(
                    record["schema_repair_attempted"],
                    "schema repair attempted",
                ),
            )
        elif status == "invalid_after_schema_repair":
            _exact(
                record,
                {
                    "status",
                    "candidate_id",
                    "raw_response_sha256",
                    "repaired_response_sha256",
                    "external_retention_reference",
                    "validation_errors",
                },
                "invalid model import record",
            )
            candidate_id = _text(record["candidate_id"], "invalid import candidate_id")
            if candidate_id not in tasks:
                raise ValueError(
                    "invalid import record contains unknown opaque candidate ID。"
                )
            envelope = build_invalid_after_repair_envelope(
                tasks[candidate_id],
                raw_response_sha256=record["raw_response_sha256"],
                repaired_response_sha256=record["repaired_response_sha256"],
                external_retention_reference=record["external_retention_reference"],
                validation_errors=record["validation_errors"],
            )
        else:
            raise ValueError("model import record status 非法。")
        validate_response_envelope(envelope, task=tasks[candidate_id])
        envelopes.append(envelope)
    return envelopes


def validate_response_envelope(
    envelope: Mapping[str, Any],
    *,
    task: Mapping[str, Any],
) -> dict[str, Any]:
    item = _mapping(dict(envelope), "model response envelope")
    status = item.get("status")
    common = {
        "status",
        "candidate_id",
        "task_identity",
        "input_sha256",
        "raw_response_sha256",
        "external_retention_reference",
        "repair_provenance",
        "response",
        "validation_errors",
    }
    if status == "valid":
        _exact(item, common, "valid model response envelope")
    elif status == "invalid_after_schema_repair":
        _exact(
            item,
            common | {"repaired_response_sha256", "external_lookup"},
            "invalid model response envelope",
        )
    else:
        raise ValueError("model response envelope status 非法。")
    for field in ("candidate_id", "task_identity", "input_sha256"):
        expected = (
            task["candidate"]["candidate_id"]
            if field == "candidate_id"
            else task[field]
        )
        if item[field] != expected:
            raise ValueError("model response envelope task binding drift。")
    _sha256(item["raw_response_sha256"], "raw response SHA-256")
    _text(item["external_retention_reference"], "external retention reference")
    repair = _mapping(item["repair_provenance"], "repair provenance")
    _exact(
        repair,
        {"attempted", "attempt_count", "schema_only", "rejudgement_performed"},
        "repair provenance",
    )
    _bool(repair["rejudgement_performed"], "repair rejudgement", expected=False)
    if status == "valid":
        attempted = _bool(repair["attempted"], "repair attempted")
        if repair["attempt_count"] != (1 if attempted else 0):
            raise ValueError("schema repair attempt count drift。")
        if repair["schema_only"] is not attempted:
            raise ValueError("schema repair 必须且只能是 schema-only。")
        if item["validation_errors"] != []:
            raise ValueError("valid envelope 不得保留 validation errors。")
        validated = validate_model_judgement_response(item["response"], task=task)
        return {"status": status, **validated}
    _sha256(item["repaired_response_sha256"], "repaired response SHA-256")
    _bool(item["external_lookup"], "invalid outcome external_lookup", expected=False)
    if item["response"] is not None:
        raise ValueError("第二次 schema failure 不得冒充合法 judgement。")
    if repair != {
        "attempted": True,
        "attempt_count": 1,
        "schema_only": True,
        "rejudgement_performed": False,
    }:
        raise ValueError("invalid outcome schema-only repair provenance drift。")
    errors = _strings(item["validation_errors"], "validation errors")
    if not errors:
        raise ValueError("invalid outcome 缺少 validation errors。")
    return {
        "status": status,
        "candidate_id": item["candidate_id"],
        "relevance": None,
        "abstain": True,
        "boundary": None,
        "evidence_sufficiency": "invalid",
        "evidence_spans": [],
        "uncertainty_codes": ("schema_invalid_after_one_repair",),
        "exclusion_or_boundary_codes": (),
    }


def _batch_identity_payload(batch: Mapping[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dict(batch))
    body.pop("artifact_id", None)
    body.pop("batch_identity", None)
    return body


def build_model_judgement_batch(
    *,
    inputs: ReferenceCurationInputs,
    roster: Mapping[str, Any],
    task_package: Mapping[str, Any],
    mapping: Mapping[str, Any],
    envelopes: Sequence[Mapping[str, Any]],
    started_at: str,
    completed_at: str,
    git_revision: str,
    allow_fixture: bool = False,
    _skip_validation: bool = False,
) -> dict[str, Any]:
    task_validation = validate_ai_task_package(
        task_package,
        mapping=mapping,
        roster=roster,
        inputs=inputs,
        allow_fixture=allow_fixture,
    )
    roster_validation = validate_model_roster(
        roster, inputs=inputs, allow_fixture=allow_fixture
    )
    entry = roster_validation["entries"][task_validation["roster_entry_id"]]
    tasks_by_id = {
        task["candidate"]["candidate_id"]: task for task in task_package["tasks"]
    }
    if len(envelopes) != U80_COUNT:
        raise ValueError("model × Topic batch 必须精确包含 80 outcomes。")
    envelope_by_id: dict[str, Mapping[str, Any]] = {}
    for raw in envelopes:
        envelope = _mapping(raw, "model response envelope")
        candidate_id = _text(envelope.get("candidate_id"), "envelope candidate_id")
        if candidate_id in envelope_by_id:
            raise ValueError("model batch candidate duplicate。")
        if candidate_id not in tasks_by_id:
            raise ValueError("model batch wrong opaque candidate ID。")
        envelope_by_id[candidate_id] = envelope
    if set(envelope_by_id) != set(tasks_by_id):
        raise ValueError("model batch candidate coverage <80 或 missing。")

    outcomes: list[dict[str, Any]] = []
    for task in task_package["tasks"]:
        candidate_id = task["candidate"]["candidate_id"]
        envelope = copy.deepcopy(dict(envelope_by_id[candidate_id]))
        validate_response_envelope(envelope, task=task)
        outcomes.append(envelope)
    started = _datetime(started_at, "model batch started_at")
    completed = _datetime(completed_at, "model batch completed_at")
    if datetime.fromisoformat(
        completed.replace("Z", "+00:00")
    ) < datetime.fromisoformat(started.replace("Z", "+00:00")):
        raise ValueError("model batch completed_at 早于 started_at。")
    invalid_count = sum(
        outcome["status"] == "invalid_after_schema_repair" for outcome in outcomes
    )
    batch: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_model_judgement_batch",
        "artifact_id": "pending",
        "batch_identity": "pending",
        "protocol": {
            "protocol_id": RCP_PROTOCOL_ID,
            "config_identity": inputs.config["config_identity"],
            "config_sha256": sha256_file(inputs.config_path),
        },
        "model_run_id": task_validation["model_run_id"],
        "model_roster": {
            "artifact_id": roster_validation["artifact_id"],
            "roster_identity": roster_validation["roster_identity"],
            "sha256": roster_validation["sha256"],
            "roster_entry": copy.deepcopy(entry),
        },
        "topic": copy.deepcopy(task_package["topic"]),
        "u80": copy.deepcopy(task_package["u80"]),
        "prompt_package": copy.deepcopy(task_package["prompt_package"]),
        "task_package": {
            "artifact_id": task_package["artifact_id"],
            "package_identity": task_package["package_identity"],
            "sha256": payload_sha256(task_package),
            "private_map_sha256": payload_sha256(mapping),
        },
        "execution_config": copy.deepcopy(entry["execution_config"]),
        "execution_config_sha256": entry["execution_config_sha256"],
        "started_at": started,
        "completed_at": completed,
        "candidate_count": U80_COUNT,
        "valid_judgement_count": U80_COUNT - invalid_count,
        "invalid_after_repair_count": invalid_count,
        "outcomes": outcomes,
        "raw_structured_response_hashes": [
            outcome["raw_response_sha256"] for outcome in outcomes
        ],
        "raw_response_retention": "external_content_addressed_workspace",
        "status": (
            "completed_with_routed_invalid" if invalid_count else "completed_validated"
        ),
        "is_fixture": task_validation["is_fixture"],
        "provenance": {
            "created_by": "src.pilot_reference_curation",
            "git_revision": _git_revision(git_revision, "model batch git_revision"),
        },
    }
    identity = deterministic_identity(
        MODEL_BATCH_IDENTITY_PREFIX, _batch_identity_payload(batch)
    )
    batch["batch_identity"] = identity
    batch["artifact_id"] = _artifact_id("srtp_rcp_model_batch", identity)
    if not _skip_validation:
        validate_model_judgement_batch(
            batch,
            inputs=inputs,
            roster=roster,
            task_package=task_package,
            mapping=mapping,
            allow_fixture=allow_fixture,
        )
    return batch


def validate_model_judgement_batch(
    batch: Mapping[str, Any],
    *,
    inputs: ReferenceCurationInputs,
    roster: Mapping[str, Any],
    task_package: Mapping[str, Any],
    mapping: Mapping[str, Any],
    allow_fixture: bool = False,
) -> dict[str, Any]:
    artifact = _mapping(dict(batch), "model judgement batch")
    provenance = _mapping(artifact.get("provenance"), "model batch provenance")
    reconstructed = build_model_judgement_batch(
        inputs=inputs,
        roster=roster,
        task_package=task_package,
        mapping=mapping,
        envelopes=artifact.get("outcomes"),
        started_at=artifact.get("started_at"),
        completed_at=artifact.get("completed_at"),
        git_revision=provenance.get("git_revision"),
        allow_fixture=allow_fixture,
        _skip_validation=True,
    )
    if artifact != reconstructed:
        raise ValueError(
            "model judgement batch deterministic reconstruction/hash drift。"
        )
    entry = artifact["model_roster"]["roster_entry"]
    return {
        "artifact_id": artifact["artifact_id"],
        "batch_identity": artifact["batch_identity"],
        "sha256": payload_sha256(artifact),
        "model_run_id": artifact["model_run_id"],
        "roster_entry_id": entry["roster_entry_id"],
        "role": entry["role"],
        "topic_id": artifact["topic"]["topic_id"],
        "u80": copy.deepcopy(artifact["u80"]),
        "is_fixture": artifact["is_fixture"],
    }


def build_fake_model_judgement_response(
    task: Mapping[str, Any],
    *,
    scenario: str,
    role: str,
    panel_index: int = 0,
) -> dict[str, Any]:
    """Deterministic plumbing-only backend; it refuses non-fixture tasks."""

    if task.get("is_fixture") is not True:
        raise ValueError("deterministic fake backend 只能处理 is_fixture=true tasks。")
    if role not in MODEL_ROLES:
        raise ValueError("fake model role 非法。")
    title = _text(task["candidate"]["title"], "fixture candidate title")
    span = build_evidence_span(
        task,
        field="title",
        start_char=0,
        end_char=min(len(title), max(1, min(24, len(title)))),
    )
    relevance: int | None
    abstain = False
    boundary = {dimension: "match" for dimension in BOUNDARY_DIMENSIONS}
    sufficiency = "sufficient"
    uncertainty: list[str] = []
    exclusion: list[str] = []
    if scenario == "safe_zero":
        relevance = 0
        boundary["scientific_object"] = "mismatch"
        exclusion = ["hard_mismatch_scientific_object"]
    elif scenario == "core_disagreement":
        relevance = 2 if role == "core" and panel_index % 2 == 0 else 1
    elif scenario == "sentinel_challenge":
        if role == "sentinel":
            relevance = 1
        else:
            relevance = 0
            boundary["scientific_object"] = "mismatch"
            exclusion = ["hard_mismatch_scientific_object"]
    elif scenario == "abstain":
        relevance = None
        abstain = True
        boundary["data_modality"] = "unclear"
        sufficiency = "insufficient"
        uncertainty = ["title_abstract_insufficient"]
    elif scenario == "boundary_conflict":
        if panel_index % 2:
            relevance = 0
            boundary["method_role"] = "mismatch"
            exclusion = ["hard_mismatch_method_role"]
        else:
            relevance = 2
    elif scenario == "label_one":
        relevance = 1
    elif scenario == "label_two":
        relevance = 2
    else:
        raise ValueError(f"unknown fake judgement scenario：{scenario}。")
    response = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_model_judgement_response",
        "protocol_id": RCP_PROTOCOL_ID,
        "model_run_id": task["model_run_id"],
        "topic_id": task["topic"]["topic_id"],
        "candidate_id": task["candidate"]["candidate_id"],
        "task_identity": task["task_identity"],
        "input_sha256": task["input_sha256"],
        "judgement": {
            "relevance": relevance,
            "abstain": abstain,
            "boundary": boundary,
            "evidence_sufficiency": sufficiency,
            "uncertainty_codes": uncertainty,
            "exclusion_or_boundary_codes": exclusion,
            "evidence_spans": [span],
            "reason_summary": f"Deterministic {scenario} plumbing-only fixture outcome.",
        },
        "external_lookup": False,
    }
    validate_model_judgement_response(response, task=task)
    return response


def _validate_run_bundle(
    bundle: Mapping[str, Any],
    *,
    inputs: ReferenceCurationInputs,
    roster: Mapping[str, Any],
    allow_fixture: bool,
) -> dict[str, Any]:
    item = _mapping(dict(bundle), "RCP run bundle")
    _exact(item, {"batch", "task_package", "mapping"}, "RCP run bundle")
    validation = validate_model_judgement_batch(
        item["batch"],
        inputs=inputs,
        roster=roster,
        task_package=item["task_package"],
        mapping=item["mapping"],
        allow_fixture=allow_fixture,
    )
    return {**item, "validation": validation}


def _model_outcome_by_canonical(
    bundle: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    task_by_candidate = {
        task["candidate"]["candidate_id"]: task
        for task in bundle["task_package"]["tasks"]
    }
    map_by_candidate = {
        row["candidate_id"]: row["canonical_entity_id"]
        for row in bundle["mapping"]["candidate_map"]
    }
    result: dict[str, dict[str, Any]] = {}
    for envelope in bundle["batch"]["outcomes"]:
        candidate_id = envelope["candidate_id"]
        canonical_id = map_by_candidate[candidate_id]
        validated = validate_response_envelope(
            envelope, task=task_by_candidate[candidate_id]
        )
        result[canonical_id] = {
            "candidate_id": candidate_id,
            **validated,
        }
    return result


def _aggregation_identity_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dict(payload))
    body.pop("artifact_id", None)
    body.pop("aggregation_identity", None)
    return body


def build_judgement_aggregation(
    *,
    inputs: ReferenceCurationInputs,
    roster: Mapping[str, Any],
    run_bundles: Sequence[Mapping[str, Any]],
    created_at: str,
    git_revision: str,
    allow_fixture: bool = False,
    _skip_validation: bool = False,
) -> dict[str, Any]:
    roster_validation = validate_model_roster(
        roster, inputs=inputs, allow_fixture=allow_fixture
    )
    if len(run_bundles) != PANEL_COUNT:
        raise ValueError("RCP aggregation 必须精确输入 3 Core + 2 Sentinel batches。")
    validated_bundles = [
        _validate_run_bundle(
            bundle,
            inputs=inputs,
            roster=roster,
            allow_fixture=allow_fixture,
        )
        for bundle in run_bundles
    ]
    by_entry: dict[str, dict[str, Any]] = {}
    topic_ids: set[str] = set()
    for bundle in validated_bundles:
        validation = bundle["validation"]
        entry_id = validation["roster_entry_id"]
        if entry_id in by_entry:
            raise ValueError("RCP aggregation model batch duplicate。")
        by_entry[entry_id] = bundle
        topic_ids.add(validation["topic_id"])
    if set(by_entry) != set(roster_validation["entries"]):
        raise ValueError("RCP aggregation missing/unexpected model batch。")
    if len(topic_ids) != 1:
        raise ValueError("RCP aggregation 不得混合 Topics。")
    topic_id = next(iter(topic_ids))
    outcomes_by_entry = {
        entry_id: _model_outcome_by_canonical(bundle)
        for entry_id, bundle in by_entry.items()
    }
    expected_ids = list(inputs.pilot_inputs.u80_by_topic[topic_id])
    for entry_id, outcomes in outcomes_by_entry.items():
        if set(outcomes) != set(expected_ids):
            raise ValueError(f"RCP batch {entry_id} canonical U80 coverage drift。")

    core_ids = sorted(
        entry_id
        for entry_id, entry in roster_validation["entries"].items()
        if entry["role"] == "core"
    )
    sentinel_ids = sorted(
        entry_id
        for entry_id, entry in roster_validation["entries"].items()
        if entry["role"] == "sentinel"
    )
    matrix: list[dict[str, Any]] = []
    for canonical_id in expected_ids:
        core = [outcomes_by_entry[entry_id][canonical_id] for entry_id in core_ids]
        sentinels = [
            outcomes_by_entry[entry_id][canonical_id] for entry_id in sentinel_ids
        ]
        all_outcomes = core + sentinels
        all_valid = all(outcome["status"] == "valid" for outcome in all_outcomes)
        labels = [outcome["relevance"] for outcome in all_outcomes]
        all_zero = all(label == 0 for label in labels)
        no_abstain = all(not outcome["abstain"] for outcome in all_outcomes)
        no_unclear = all(
            outcome["boundary"] is not None
            and all(
                value not in {"unclear", "not_stated"}
                for value in outcome["boundary"].values()
            )
            for outcome in all_outcomes
        )
        sufficient = all(
            outcome["evidence_sufficiency"] == "sufficient" for outcome in all_outcomes
        )
        mismatch_sets = [
            {
                dimension
                for dimension, value in outcome["boundary"].items()
                if value == "mismatch"
            }
            if outcome["boundary"] is not None
            else set()
            for outcome in all_outcomes
        ]
        shared_mismatch = set.intersection(*mismatch_sets) if mismatch_sets else set()
        safe_zero = (
            all_valid
            and all_zero
            and no_abstain
            and no_unclear
            and sufficient
            and bool(shared_mismatch)
        )
        reasons: list[str] = []
        if not all_valid:
            reasons.append("invalid_schema_after_one_repair")
        if any(outcome["abstain"] for outcome in all_outcomes):
            reasons.append("abstain")
        if not no_unclear:
            reasons.append("unclear_or_not_stated_boundary")
        if not sufficient:
            reasons.append("insufficient_evidence")
        core_labels = [outcome["relevance"] for outcome in core]
        sentinel_labels = [outcome["relevance"] for outcome in sentinels]
        if len(set(core_labels)) != 1:
            reasons.append("core_disagreement")
        if any(label in {1, 2} for label in core_labels):
            reasons.append("core_nonzero")
        if core_labels == [0, 0, 0] and sentinel_labels != [0, 0]:
            reasons.append("sentinel_challenge")
        if all_zero and not shared_mismatch:
            reasons.append("no_shared_hard_mismatch_dimension")
        boundary_vectors = [outcome["boundary"] for outcome in all_outcomes]
        if any(
            {vector[dimension] for vector in boundary_vectors if vector is not None}
            & {"match"}
            and {vector[dimension] for vector in boundary_vectors if vector is not None}
            & {"mismatch"}
            for dimension in BOUNDARY_DIMENSIONS
        ):
            reasons.append("boundary_conflict")
        if safe_zero:
            reasons = ["strict_safe_zero"]
        core_unanimous = (
            core_labels[0]
            if len(set(core_labels)) == 1 and core_labels[0] in {0, 1, 2}
            else None
        )
        matrix.append(
            {
                "canonical_entity_id": canonical_id,
                "core": [
                    {
                        "roster_entry_id": entry_id,
                        **copy.deepcopy(outcomes_by_entry[entry_id][canonical_id]),
                    }
                    for entry_id in core_ids
                ],
                "sentinels": [
                    {
                        "roster_entry_id": entry_id,
                        **copy.deepcopy(outcomes_by_entry[entry_id][canonical_id]),
                    }
                    for entry_id in sentinel_ids
                ],
                "core_labels": core_labels,
                "sentinel_labels": sentinel_labels,
                "core_unanimous_label": core_unanimous,
                "shared_hard_mismatch_dimensions": sorted(shared_mismatch),
                "safe_zero": safe_zero,
                "human_route": not safe_zero,
                "routing_reasons": sorted(set(reasons)),
                "n_core_label_2": sum(label == 2 for label in core_labels),
                "n_core_label_ge_1": sum(
                    isinstance(label, int) and label >= 1 for label in core_labels
                ),
            }
        )
    created = _datetime(created_at, "aggregation created_at")
    batch_refs = [
        {
            "roster_entry_id": entry_id,
            "role": roster_validation["entries"][entry_id]["role"],
            "artifact_id": by_entry[entry_id]["validation"]["artifact_id"],
            "batch_identity": by_entry[entry_id]["validation"]["batch_identity"],
            "sha256": by_entry[entry_id]["validation"]["sha256"],
        }
        for entry_id in sorted(by_entry)
    ]
    payload: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_judgement_aggregation",
        "artifact_id": "pending",
        "aggregation_identity": "pending",
        "protocol": {
            "protocol_id": RCP_PROTOCOL_ID,
            "config_identity": inputs.config["config_identity"],
            "config_sha256": sha256_file(inputs.config_path),
        },
        "model_roster": {
            "artifact_id": roster_validation["artifact_id"],
            "roster_identity": roster_validation["roster_identity"],
            "sha256": roster_validation["sha256"],
        },
        "topic": {
            "topic_id": topic_id,
            "question_id": topic_config(inputs.pilot_inputs, topic_id)["question_id"],
            "research_question_identity": topic_config(inputs.pilot_inputs, topic_id)[
                "research_question_identity"
            ],
        },
        "u80": _u80_reference(inputs.pilot_inputs),
        "input_model_batches": batch_refs,
        "candidate_count": U80_COUNT,
        "safe_zero_count": sum(row["safe_zero"] for row in matrix),
        "human_route_count": sum(row["human_route"] for row in matrix),
        "judgement_matrix": matrix,
        "sentinel_decision_role": "challenge_core_unanimous_zero_only_not_vote_or_rank",
        "created_at": created,
        "is_fixture": roster_validation["is_fixture"],
        "provenance": {
            "created_by": "src.pilot_reference_curation",
            "git_revision": _git_revision(git_revision, "aggregation git_revision"),
        },
    }
    identity = deterministic_identity(
        AGGREGATION_IDENTITY_PREFIX, _aggregation_identity_payload(payload)
    )
    payload["aggregation_identity"] = identity
    payload["artifact_id"] = _artifact_id("srtp_rcp_aggregation", identity)
    if not _skip_validation:
        validate_judgement_aggregation(
            payload,
            inputs=inputs,
            roster=roster,
            run_bundles=run_bundles,
            allow_fixture=allow_fixture,
        )
    return payload


def validate_judgement_aggregation(
    aggregation: Mapping[str, Any],
    *,
    inputs: ReferenceCurationInputs,
    roster: Mapping[str, Any],
    run_bundles: Sequence[Mapping[str, Any]],
    allow_fixture: bool = False,
) -> dict[str, Any]:
    artifact = _mapping(dict(aggregation), "RCP aggregation")
    reconstructed = build_judgement_aggregation(
        inputs=inputs,
        roster=roster,
        run_bundles=run_bundles,
        created_at=artifact.get("created_at"),
        git_revision=_mapping(artifact.get("provenance"), "aggregation provenance").get(
            "git_revision"
        ),
        allow_fixture=allow_fixture,
        _skip_validation=True,
    )
    if artifact != reconstructed:
        raise ValueError("RCP aggregation deterministic reconstruction drift。")
    return {
        "artifact_id": artifact["artifact_id"],
        "aggregation_identity": artifact["aggregation_identity"],
        "sha256": payload_sha256(artifact),
        "topic_id": artifact["topic"]["topic_id"],
        "safe_zero_count": artifact["safe_zero_count"],
        "human_route_count": artifact["human_route_count"],
        "is_fixture": artifact["is_fixture"],
    }


def build_reference_execution_manifest(
    *,
    inputs: ReferenceCurationInputs,
    roster: Mapping[str, Any],
    run_bundles: Sequence[Mapping[str, Any]],
    frozen_at: str,
    git_revision: str,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    roster_validation = validate_model_roster(
        roster, inputs=inputs, allow_fixture=allow_fixture
    )
    expected_topics = sorted(inputs.pilot_inputs.u80_by_topic)
    expected_count = len(expected_topics) * PANEL_COUNT
    if len(run_bundles) != expected_count:
        raise ValueError(
            f"RCP execution manifest 必须精确绑定 {expected_count} batches。"
        )
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in run_bundles:
        bundle = _validate_run_bundle(
            raw,
            inputs=inputs,
            roster=roster,
            allow_fixture=allow_fixture,
        )
        validation = bundle["validation"]
        key = (validation["topic_id"], validation["roster_entry_id"])
        if key in seen:
            raise ValueError("RCP execution manifest duplicate model × Topic batch。")
        seen.add(key)
        rows.append(
            {
                "topic_id": key[0],
                "roster_entry_id": key[1],
                "role": validation["role"],
                "artifact_id": validation["artifact_id"],
                "batch_identity": validation["batch_identity"],
                "sha256": validation["sha256"],
                "task_package_sha256": payload_sha256(bundle["task_package"]),
                "private_map_sha256": payload_sha256(bundle["mapping"]),
            }
        )
    expected = {
        (topic_id, entry_id)
        for topic_id in expected_topics
        for entry_id in roster_validation["entries"]
    }
    if seen != expected:
        raise ValueError("RCP execution manifest 10-batch roster coverage drift。")
    rows.sort(key=lambda row: (row["topic_id"], row["roster_entry_id"]))
    payload: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_reference_execution_manifest",
        "artifact_id": "pending",
        "execution_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "protocol_config_identity": inputs.config["config_identity"],
        "model_roster": {
            "artifact_id": roster_validation["artifact_id"],
            "roster_identity": roster_validation["roster_identity"],
            "sha256": roster_validation["sha256"],
        },
        "topic_ids": expected_topics,
        "batch_count": expected_count,
        "model_batches": rows,
        "frozen_at": _datetime(frozen_at, "execution manifest frozen_at"),
        "status": "fixture_complete"
        if roster_validation["is_fixture"]
        else "completed_validated",
        "is_fixture": roster_validation["is_fixture"],
        "provenance": {
            "created_by": "src.pilot_reference_curation",
            "git_revision": _git_revision(git_revision, "execution git_revision"),
        },
    }
    identity = _identity_without(
        payload,
        prefix=EXECUTION_IDENTITY_PREFIX,
        omitted={"artifact_id", "execution_identity"},
    )
    payload["execution_identity"] = identity
    payload["artifact_id"] = _artifact_id("srtp_rcp_execution", identity)
    return payload


def validate_reference_execution_manifest(
    manifest: Mapping[str, Any],
    *,
    inputs: ReferenceCurationInputs,
    roster: Mapping[str, Any],
    run_bundles: Sequence[Mapping[str, Any]] | None = None,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    artifact = _mapping(dict(manifest), "RCP execution manifest")
    roster_validation = validate_model_roster(
        roster, inputs=inputs, allow_fixture=allow_fixture
    )
    _exact(
        artifact,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "execution_identity",
            "protocol_id",
            "protocol_config_identity",
            "model_roster",
            "topic_ids",
            "batch_count",
            "model_batches",
            "frozen_at",
            "status",
            "is_fixture",
            "provenance",
        },
        "RCP execution manifest",
    )
    expected_topics = sorted(inputs.pilot_inputs.u80_by_topic)
    if (
        artifact["schema_version"] != RCP_SCHEMA_VERSION
        or artifact["artifact_type"] != "srtp_rcp_reference_execution_manifest"
        or artifact["protocol_id"] != RCP_PROTOCOL_ID
        or artifact["protocol_config_identity"] != inputs.config["config_identity"]
        or artifact["topic_ids"] != expected_topics
        or artifact["batch_count"] != len(expected_topics) * PANEL_COUNT
        or artifact["is_fixture"] != roster_validation["is_fixture"]
    ):
        raise ValueError("RCP execution manifest protocol/count/fixture drift。")
    if artifact["model_roster"] != {
        "artifact_id": roster_validation["artifact_id"],
        "roster_identity": roster_validation["roster_identity"],
        "sha256": roster_validation["sha256"],
    }:
        raise ValueError("RCP execution manifest roster binding drift。")
    rows = _list(artifact["model_batches"], "execution model batches")
    keys = [(row.get("topic_id"), row.get("roster_entry_id")) for row in rows]
    expected_keys = sorted(
        (topic_id, entry_id)
        for topic_id in expected_topics
        for entry_id in roster_validation["entries"]
    )
    if keys != expected_keys or len(keys) != len(set(keys)):
        raise ValueError("RCP execution manifest exact 10-batch roster drift。")
    if any(
        row.get("role") != roster_validation["entries"][row["roster_entry_id"]]["role"]
        for row in rows
    ):
        raise ValueError("RCP execution manifest model role drift。")
    identity = _identity_without(
        artifact,
        prefix=EXECUTION_IDENTITY_PREFIX,
        omitted={"artifact_id", "execution_identity"},
    )
    if artifact["execution_identity"] != identity or artifact[
        "artifact_id"
    ] != _artifact_id("srtp_rcp_execution", identity):
        raise ValueError("RCP execution manifest identity drift。")
    if run_bundles is not None:
        reconstructed = build_reference_execution_manifest(
            inputs=inputs,
            roster=roster,
            run_bundles=run_bundles,
            frozen_at=artifact["frozen_at"],
            git_revision=_mapping(artifact["provenance"], "execution provenance")[
                "git_revision"
            ],
            allow_fixture=allow_fixture,
        )
        if artifact != reconstructed:
            raise ValueError(
                "RCP execution manifest/batch deterministic closure drift。"
            )
    return {
        "artifact_id": artifact["artifact_id"],
        "execution_identity": identity,
        "sha256": payload_sha256(artifact),
        "batch_count": artifact["batch_count"],
        "is_fixture": artifact["is_fixture"],
    }


def _combination_miss_probability(
    *, population: int, errors: int, sample: int
) -> float:
    if sample < 0 or sample > population:
        raise ValueError("audit sample size 越界。")
    if population == 0:
        return 0.0
    if sample > population - errors:
        return 0.0
    return math.comb(population - errors, sample) / math.comb(population, sample)


def minimum_safe_zero_audit_size(population: int) -> dict[str, Any]:
    size = _integer(population, "safe-zero population")
    if size == 0:
        return {
            "population": 0,
            "assumed_error_count": 0,
            "sample_size": 0,
            "miss_probability": 0.0,
        }
    errors = math.ceil(0.10 * size)
    sample = next(
        n
        for n in range(size + 1)
        if _combination_miss_probability(
            population=size,
            errors=errors,
            sample=n,
        )
        <= 0.05
    )
    return {
        "population": size,
        "assumed_error_count": errors,
        "sample_size": sample,
        "miss_probability": _combination_miss_probability(
            population=size,
            errors=errors,
            sample=sample,
        ),
    }


def build_safe_zero_audit_plan(
    aggregation: Mapping[str, Any],
    *,
    inputs: ReferenceCurationInputs,
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    if (
        aggregation.get("protocol", {}).get("config_identity")
        != inputs.config["config_identity"]
    ):
        raise ValueError("safe-zero audit wrong protocol config。")
    topic_id = aggregation["topic"]["topic_id"]
    safe_ids = [
        row["canonical_entity_id"]
        for row in aggregation["judgement_matrix"]
        if row["safe_zero"]
    ]
    statistics_payload = minimum_safe_zero_audit_size(len(safe_ids))
    seed = inputs.config["safe_zero_audit_policy"]["audit_seed"]
    ranked = sorted(
        safe_ids,
        key=lambda candidate_id: (
            hashlib.sha256(
                "|".join(
                    [
                        inputs.config["config_identity"],
                        topic_id,
                        candidate_id,
                        seed,
                    ]
                ).encode("utf-8")
            ).hexdigest(),
            candidate_id,
        ),
    )
    selected = ranked[: statistics_payload["sample_size"]]
    payload: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_safe_zero_audit_plan",
        "artifact_id": "pending",
        "audit_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "protocol_config_identity": inputs.config["config_identity"],
        "topic": copy.deepcopy(aggregation["topic"]),
        "aggregation": _artifact_reference(aggregation),
        "sampling": {
            "algorithm": "sha256_protocol_topic_candidate_seed_v1",
            "seed": seed,
            **statistics_payload,
        },
        "safe_zero_canonical_entity_ids": safe_ids,
        "audit_sample_canonical_entity_ids": selected,
        "status": "planned_not_started",
        "confirmed_discrepancy_action": "review_all_remaining_safe_zero",
        "created_at": _datetime(created_at, "audit plan created_at"),
        "is_fixture": aggregation["is_fixture"],
        "provenance": {
            "created_by": "src.pilot_reference_curation",
            "git_revision": _git_revision(git_revision, "audit plan git_revision"),
        },
    }
    identity = _identity_without(
        payload,
        prefix=AUDIT_IDENTITY_PREFIX,
        omitted={"artifact_id", "audit_identity"},
    )
    payload["audit_identity"] = identity
    payload["artifact_id"] = _artifact_id("srtp_rcp_audit", identity)
    return payload


def validate_safe_zero_audit_plan(
    audit_plan: Mapping[str, Any],
    *,
    aggregation: Mapping[str, Any],
    inputs: ReferenceCurationInputs,
) -> dict[str, Any]:
    artifact = _mapping(dict(audit_plan), "safe-zero audit plan")
    provenance = _mapping(artifact.get("provenance"), "audit plan provenance")
    reconstructed = build_safe_zero_audit_plan(
        aggregation,
        inputs=inputs,
        created_at=artifact.get("created_at"),
        git_revision=provenance.get("git_revision"),
    )
    if artifact != reconstructed:
        raise ValueError("safe-zero audit plan deterministic reconstruction drift。")
    return {
        "artifact_id": artifact["artifact_id"],
        "audit_identity": artifact["audit_identity"],
        "sha256": payload_sha256(artifact),
        "sample_size": artifact["sampling"]["sample_size"],
        "is_fixture": artifact["is_fixture"],
    }


def build_safe_zero_audit_outcome(
    audit_plan: Mapping[str, Any],
    *,
    inputs: ReferenceCurationInputs,
    aggregation: Mapping[str, Any],
    final_human_labels: Mapping[str, Any],
    completed_at: str,
    git_revision: str,
) -> dict[str, Any]:
    validate_safe_zero_audit_plan(
        audit_plan,
        aggregation=aggregation,
        inputs=inputs,
    )
    # Local import avoids a module-initialization cycle while keeping the audit
    # outcome dependent on the validated, raw-response-derived Human closure.
    from src.pilot_reference_review import validate_final_human_labels_identity

    validate_final_human_labels_identity(
        final_human_labels,
        aggregation=aggregation,
    )
    selected = _strings(
        audit_plan.get("audit_sample_canonical_entity_ids"), "audit sample IDs"
    )
    labels = {
        row["canonical_entity_id"]: row["final_human_relevance"]
        for row in _list(final_human_labels.get("labels"), "final human labels")
    }
    if not set(selected).issubset(labels):
        raise ValueError("validated Human labels 未覆盖完整 safe-zero audit sample。")
    discrepancies = [
        candidate_id for candidate_id in selected if labels[candidate_id] != 0
    ]
    all_safe = _strings(
        audit_plan.get("safe_zero_canonical_entity_ids"), "safe-zero IDs"
    )
    escalation = bool(discrepancies)
    payload: dict[str, Any] = {
        "schema_version": RCP_SCHEMA_VERSION,
        "artifact_type": "srtp_rcp_safe_zero_audit_outcome",
        "artifact_id": "pending",
        "audit_outcome_identity": "pending",
        "protocol_id": RCP_PROTOCOL_ID,
        "audit_plan": _artifact_reference(audit_plan),
        "human_audit_labels": _artifact_reference(final_human_labels),
        "reviewed_canonical_entity_ids": selected,
        "confirmed_discrepancy_ids": discrepancies,
        "escalation_required": escalation,
        "escalated_review_canonical_entity_ids": (
            [candidate_id for candidate_id in all_safe if candidate_id not in selected]
            if escalation
            else []
        ),
        "completed_at": _datetime(completed_at, "audit outcome completed_at"),
        "provenance": {
            "created_by": "src.pilot_reference_curation",
            "git_revision": _git_revision(git_revision, "audit outcome git_revision"),
        },
        "is_fixture": audit_plan["is_fixture"],
    }
    identity = _identity_without(
        payload,
        prefix=AUDIT_OUTCOME_IDENTITY_PREFIX,
        omitted={"artifact_id", "audit_outcome_identity"},
    )
    payload["audit_outcome_identity"] = identity
    payload["artifact_id"] = _artifact_id("srtp_rcp_audit_outcome", identity)
    return payload


def validate_safe_zero_audit_outcome(
    audit_outcome: Mapping[str, Any],
    *,
    audit_plan: Mapping[str, Any],
    inputs: ReferenceCurationInputs,
    aggregation: Mapping[str, Any],
    final_human_labels: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = _mapping(dict(audit_outcome), "safe-zero audit outcome")
    provenance = _mapping(
        artifact.get("provenance"), "safe-zero audit outcome provenance"
    )
    reconstructed = build_safe_zero_audit_outcome(
        audit_plan,
        inputs=inputs,
        aggregation=aggregation,
        final_human_labels=final_human_labels,
        completed_at=artifact.get("completed_at"),
        git_revision=provenance.get("git_revision"),
    )
    if artifact != reconstructed:
        raise ValueError("safe-zero audit outcome deterministic reconstruction drift。")
    return {
        "artifact_id": artifact["artifact_id"],
        "audit_outcome_identity": artifact["audit_outcome_identity"],
        "sha256": payload_sha256(artifact),
        "escalation_required": artifact["escalation_required"],
        "is_fixture": artifact["is_fixture"],
    }
