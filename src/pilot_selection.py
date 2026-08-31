"""Pilot v0.2 selection contracts and dual-curator workflow.

This module stops before real human selection.  It provides a thin generic
selection artifact shared by BM25 and human curation, blind curator task
preparation, response import, overlap/adjudication tooling, and strict offline
validation.  It never calls OpenAlex or an LLM.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.annotation_tasks import sha256_file
from src.bm25_ranking import (
    BM25_B,
    BM25_K1,
    bm25_score,
    build_document_tokens,
    compute_corpus_stats,
)
from src.text_relevance import tokenize_text
from src.w6_contracts import deterministic_identity, load_json_object


SCHEMA_VERSION = "1.0"
PILOT_VERSION = "srtp-pilot-v0.2"
SELECTION_K = 8
U80_COUNT = 80
BM25_METHOD_ID = "pilot_bm25_lexical_v1"
HUMAN_METHOD_ID = "pilot_dual_curator_v1"
REFERENCE_METHOD_ID = "pilot_ai_assisted_reference_abstract_v1"
FIXTURE_METHOD_ID = "pilot_mock_selection_plumbing_v1"
CURATOR_SLOTS = ("curator_a", "curator_b")
MINIMUM_CURATOR_OVERLAP = 4

CONFIG_IDENTITY_PREFIX = "srtp-pilot-selection-context-config"
QUESTION_IDENTITY_PREFIX = "srtp-pilot-question"
BM25_CONFIG_IDENTITY_PREFIX = "srtp-pilot-bm25-config"
HUMAN_CONFIG_IDENTITY_PREFIX = "srtp-pilot-dual-curator-config"
CONTEXT_POLICY_IDENTITY_PREFIX = "srtp-pilot-context-policy"
SELECTION_IDENTITY_PREFIX = "srtp-pilot-selection"
CURATOR_TASK_IDENTITY_PREFIX = "srtp-pilot-curator-task"
CURATOR_ROSTER_IDENTITY_PREFIX = "srtp-pilot-curator-roster"
CURATOR_MAP_IDENTITY_PREFIX = "srtp-pilot-curator-map"
CURATOR_SUBMISSION_IDENTITY_PREFIX = "srtp-pilot-curator-submission"
CURATOR_COMPARISON_IDENTITY_PREFIX = "srtp-pilot-curator-comparison"
ADJUDICATION_TASK_IDENTITY_PREFIX = "srtp-pilot-adjudication-task"
ADJUDICATION_SUBMISSION_IDENTITY_PREFIX = "srtp-pilot-adjudication-submission"
CURATOR_PACKAGE_IDENTITY_PREFIX = "srtp-pilot-curator-preparation"
CURATOR_EXPORT_IDENTITY_PREFIX = "srtp-pilot-curator-export"

CURATOR_VISIBLE_CANDIDATE_FIELDS = {"candidate_id", "title", "abstract"}
CURATOR_FORBIDDEN_KEYS = {
    "authors",
    "venue",
    "canonical_entity_id",
    "openalex_id",
    "doi",
    "citation_count",
    "cited_by_count",
    "source_rank",
    "source_score",
    "query_support",
    "query_support_count",
    "bm25_score",
    "bm25_rank",
    "selection_score",
    "selection_rank",
    "other_curator_selection",
    "hidden_label",
    "relevance_label",
}


@dataclass(frozen=True)
class PilotSelectionInputs:
    project_root: Path
    config_path: Path
    config: dict[str, Any]
    manifest: dict[str, Any]
    u80: dict[str, Any]
    selection_view: dict[str, Any]
    topics_payload: dict[str, Any]
    topics: dict[str, dict[str, Any]]
    u80_by_topic: dict[str, tuple[str, ...]]
    view_by_topic_entity: dict[tuple[str, str], dict[str, Any]]


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def write_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_json_bytes(payload))
    return output


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON object。")
    return value


def _require_list(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = "非空数组" if nonempty else "数组"
        raise ValueError(f"{label} 必须是{suffix}。")
    return value


def _require_exact_fields(
    value: Mapping[str, Any], expected: set[str], label: str
) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{label} 字段漂移：missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}。"
        )


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空字符串。")
    return value.strip()


def _require_bool(value: Any, expected: bool | None, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} 必须是布尔值。")
    if expected is not None and value is not expected:
        raise ValueError(f"{label} 必须是 {expected}。")
    return value


def _require_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} 必须是 >= {minimum} 的整数。")
    return value


def _require_number(value: Any, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} 必须是数值。")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{label} 必须是 >= {minimum} 的有限数值。")
    return result


def _require_datetime(value: Any, label: str) -> str:
    text = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} 必须是 ISO-8601 时间。") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} 必须包含时区。")
    return text


def _require_git_revision(value: Any, label: str) -> str:
    revision = _require_text(value, label)
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError(f"{label} 必须是 40 位 lowercase Git SHA。")
    return revision


def _require_sha256(value: Any, label: str) -> str:
    digest = _require_text(value, label)
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"{label} 必须是 64 位 lowercase SHA-256。")
    return digest


def _require_string_list(
    value: Any, label: str, *, count: int | None = None, unique: bool = True
) -> list[str]:
    values = _require_list(value, label)
    result = [_require_text(item, f"{label} item") for item in values]
    if count is not None and len(result) != count:
        raise ValueError(f"{label} 必须精确包含 {count} 项。")
    if unique and len(result) != len(set(result)):
        raise ValueError(f"{label} 不得重复。")
    return result


def _resolve_repo_path(project_root: Path, relative_path: Any, label: str) -> Path:
    relative = Path(_require_text(relative_path, label))
    if relative.is_absolute():
        raise ValueError(f"{label} 必须是仓库相对路径。")
    root = project_root.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} 逃逸仓库根目录。") from error
    return resolved


def _reference(path: Path, payload: Mapping[str, Any]) -> dict[str, str]:
    return {
        "artifact_id": _require_text(payload.get("artifact_id"), "artifact_id"),
        "sha256": sha256_file(path),
    }


def compute_question_identity(topic_id: str, research_question: str) -> str:
    return deterministic_identity(
        QUESTION_IDENTITY_PREFIX,
        {"topic_id": topic_id, "research_question": research_question},
    )


def _identity_without(payload: Mapping[str, Any], field: str, prefix: str) -> str:
    body = copy.deepcopy(dict(payload))
    body.pop(field, None)
    return deterministic_identity(prefix, body)


def compute_selection_context_config_identity(config: Mapping[str, Any]) -> str:
    return _identity_without(config, "config_identity", CONFIG_IDENTITY_PREFIX)


def compute_bm25_config_identity(config: Mapping[str, Any]) -> str:
    return _identity_without(config, "config_identity", BM25_CONFIG_IDENTITY_PREFIX)


def compute_human_config_identity(config: Mapping[str, Any]) -> str:
    return _identity_without(config, "config_identity", HUMAN_CONFIG_IDENTITY_PREFIX)


def compute_context_policy_identity(config: Mapping[str, Any]) -> str:
    return _identity_without(config, "config_identity", CONTEXT_POLICY_IDENTITY_PREFIX)


def _validate_config(config: dict[str, Any]) -> None:
    _require_exact_fields(
        config,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "config_identity",
            "pilot_version",
            "status",
            "is_fixture",
            "created_at",
            "inputs",
            "topics",
            "selection_policy",
            "bm25",
            "dual_curator",
            "context_policy",
            "input_boundary",
        },
        "Pilot selection/context config",
    )
    if config["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Pilot selection config schema_version drift。")
    if config["artifact_type"] != "srtp_pilot_selection_context_config":
        raise ValueError("Pilot selection config artifact_type drift。")
    if config["pilot_version"] != PILOT_VERSION or config["status"] != "frozen":
        raise ValueError("Pilot selection config version/status drift。")
    _require_bool(config["is_fixture"], False, "config is_fixture")
    _require_datetime(config["created_at"], "config created_at")
    if config["config_identity"] != compute_selection_context_config_identity(config):
        raise ValueError("Pilot selection config identity/hash drift。")

    selection_policy = _require_mapping(config["selection_policy"], "selection_policy")
    _require_exact_fields(
        selection_policy,
        {
            "k_per_topic",
            "canonical_entity_one_slot",
            "shared_u80_required",
            "shared_paper_representation",
        },
        "selection_policy",
    )
    if (
        _require_int(selection_policy["k_per_topic"], "k_per_topic", minimum=1)
        != SELECTION_K
    ):
        raise ValueError("Pilot selection K 必须冻结为 8。")
    _require_bool(
        selection_policy["canonical_entity_one_slot"],
        True,
        "canonical_entity_one_slot",
    )
    _require_bool(selection_policy["shared_u80_required"], True, "shared_u80_required")
    if selection_policy["shared_paper_representation"] != ["title", "abstract"]:
        raise ValueError("selection paper representation 必须是 title + abstract。")

    bm25 = _require_mapping(config["bm25"], "bm25 config")
    _require_exact_fields(
        bm25,
        {
            "method_id",
            "config_identity",
            "query_field",
            "paper_representation",
            "tokenizer",
            "k1",
            "b",
            "ranking",
            "k",
            "formal_execution_policy",
        },
        "bm25 config",
    )
    if bm25["method_id"] != BM25_METHOD_ID:
        raise ValueError("Pilot BM25 method_id drift。")
    if bm25["config_identity"] != compute_bm25_config_identity(bm25):
        raise ValueError("Pilot BM25 config identity drift。")
    if bm25["query_field"] != "frozen_topic_research_question":
        raise ValueError("Pilot BM25 query 必须使用 frozen research_question。")
    if bm25["paper_representation"] != ["title", "abstract"]:
        raise ValueError("Pilot BM25 representation drift。")
    if bm25["tokenizer"] != "src.text_relevance.tokenize_text:v1":
        raise ValueError("Pilot BM25 tokenizer drift。")
    if float(bm25["k1"]) != BM25_K1 or float(bm25["b"]) != BM25_B:
        raise ValueError("Pilot BM25 k1/b drift。")
    if bm25["ranking"] != ["score_desc", "canonical_entity_id_asc"]:
        raise ValueError("Pilot BM25 ranking/tie-break drift。")
    if bm25["k"] != SELECTION_K:
        raise ValueError("Pilot BM25 K drift。")
    if bm25["formal_execution_policy"] != "after_dual_curator_final_selection_freeze":
        raise ValueError("Pilot BM25 formal execution policy drift。")

    human = _require_mapping(config["dual_curator"], "dual_curator config")
    _require_exact_fields(
        human,
        {
            "method_id",
            "config_identity",
            "curator_slots",
            "selection_count",
            "minimum_overlap_count",
            "external_lookup",
            "independent_submission_required",
            "adjudicator_candidate_scope",
            "preserve_original_submissions",
            "opaque_candidate_seed",
            "candidate_order_seed",
        },
        "dual_curator config",
    )
    if human["method_id"] != HUMAN_METHOD_ID:
        raise ValueError("Dual-Curator method_id drift。")
    if human["config_identity"] != compute_human_config_identity(human):
        raise ValueError("Dual-Curator config identity drift。")
    if human["curator_slots"] != list(CURATOR_SLOTS):
        raise ValueError("Dual-Curator roster 必须是 curator_a/curator_b。")
    if human["selection_count"] != SELECTION_K:
        raise ValueError("Dual-Curator selection count 必须是 8。")
    if human["minimum_overlap_count"] != MINIMUM_CURATOR_OVERLAP:
        raise ValueError("Dual-Curator minimum overlap 必须是 4。")
    _require_bool(human["external_lookup"], False, "dual curator external_lookup")
    _require_bool(
        human["independent_submission_required"],
        True,
        "independent submission",
    )
    if human["adjudicator_candidate_scope"] != "symmetric_difference_only":
        raise ValueError("第三人只能从 symmetric difference 补足。")
    _require_bool(
        human["preserve_original_submissions"],
        True,
        "preserve original submissions",
    )
    _require_text(human["opaque_candidate_seed"], "opaque candidate seed")
    _require_text(human["candidate_order_seed"], "candidate order seed")

    context = _require_mapping(config["context_policy"], "context_policy")
    _require_exact_fields(
        context,
        {
            "policy_id",
            "config_identity",
            "representation",
            "tokenizer",
            "per_paper_token_cap",
            "maximum_context_tokens",
            "field_template",
            "separator",
            "truncation_marker",
            "truncation_allocation",
            "global_tail_truncation",
            "padding",
            "ordering",
            "generator_compatibility_requirement",
        },
        "context_policy",
    )
    if context["policy_id"] != "pilot_title_abstract_context_v1":
        raise ValueError("Pilot context policy_id drift。")
    if context["config_identity"] != compute_context_policy_identity(context):
        raise ValueError("Pilot context policy identity drift。")
    if context["representation"] != ["title", "abstract"]:
        raise ValueError("Pilot context representation 必须是 title + abstract。")
    tokenizer = _require_mapping(context["tokenizer"], "context tokenizer")
    _require_exact_fields(
        tokenizer,
        {"tokenizer_id", "implementation", "pattern", "normalization"},
        "context tokenizer",
    )
    if tokenizer != {
        "tokenizer_id": "pilot_unicode_word_v1",
        "implementation": "python_re_unicode_finditer",
        "pattern": r"[^\W_]+(?:[-'’][^\W_]+)*",
        "normalization": "none_counting_only_exact_text_preserved",
    }:
        raise ValueError("Pilot context tokenizer convention drift。")
    per_paper_cap = _require_int(
        context["per_paper_token_cap"], "per-paper token cap", minimum=1
    )
    maximum = _require_int(
        context["maximum_context_tokens"], "maximum context tokens", minimum=1
    )
    if per_paper_cap != 256 or maximum != 2400:
        raise ValueError("Pilot context token caps drift。")
    if context["field_template"] != "Title: {title}\nAbstract: {abstract}":
        raise ValueError("Pilot context field template drift。")
    if context["separator"] != "\n\n---\n\n":
        raise ValueError("Pilot context separator drift。")
    if context["truncation_marker"] != " …":
        raise ValueError("Pilot context truncation marker drift。")
    if context["truncation_allocation"] != "title_first_then_abstract":
        raise ValueError("Pilot context truncation allocation drift。")
    _require_bool(context["global_tail_truncation"], False, "global tail truncation")
    _require_bool(context["padding"], False, "context padding")
    ordering = _require_mapping(context["ordering"], "context ordering")
    _require_exact_fields(
        ordering,
        {
            "algorithm",
            "seed",
            "hash_input_format",
            "condition_name_included",
            "selection_rank_included",
            "repeat_number_included",
        },
        "context ordering",
    )
    if ordering["algorithm"] != "sha256_seed_question_canonical_v1":
        raise ValueError("Pilot context ordering algorithm drift。")
    _require_text(ordering["seed"], "context ordering seed")
    if ordering["hash_input_format"] != "seed|question_id|canonical_entity_id":
        raise ValueError("Pilot context ordering hash input drift。")
    for key in (
        "condition_name_included",
        "selection_rank_included",
        "repeat_number_included",
    ):
        _require_bool(ordering[key], False, f"context ordering {key}")
    if context["generator_compatibility_requirement"] != (
        "consume_exact_rendered_utf8_context_unchanged_and_record_provider_token_counts_separately"
    ):
        raise ValueError("Pilot context generator compatibility statement drift。")

    topics = _require_list(config["topics"], "config topics", nonempty=True)
    if len(topics) != 2:
        raise ValueError("Pilot selection config 必须精确包含两个 Dev Topics。")
    topic_ids: set[str] = set()
    for raw in topics:
        topic = _require_mapping(raw, "config topic")
        _require_exact_fields(
            topic,
            {
                "topic_id",
                "question_id",
                "research_question",
                "research_question_identity",
            },
            "config topic",
        )
        topic_id = _require_text(topic["topic_id"], "topic_id")
        if topic_id in topic_ids:
            raise ValueError("config topic_id 重复。")
        topic_ids.add(topic_id)
        question_id = _require_text(topic["question_id"], "question_id")
        question = _require_text(topic["research_question"], "research_question")
        expected_identity = compute_question_identity(topic_id, question)
        if topic["research_question_identity"] != expected_identity:
            raise ValueError(f"{question_id} research question identity drift。")
    if any("hidden" in topic_id.casefold() for topic_id in topic_ids):
        raise ValueError("Pilot selection config 不得包含 Hidden Topic。")

    boundary = _require_mapping(config["input_boundary"], "input_boundary")
    required_false = {
        "hidden_topics_allowed",
        "hidden_labels_allowed",
        "relevance_labels_allowed",
        "bm25_results_visible_to_curators",
        "other_curator_selection_visible",
        "live_api_allowed",
        "llm_allowed",
    }
    _require_exact_fields(boundary, required_false, "input_boundary")
    for key in required_false:
        _require_bool(boundary.get(key), False, f"input_boundary.{key}")


def load_pilot_selection_inputs(
    config_path: str | Path, *, project_root: str | Path
) -> PilotSelectionInputs:
    root = Path(project_root).resolve()
    resolved_config = Path(config_path)
    if not resolved_config.is_absolute():
        resolved_config = (root / resolved_config).resolve()
    config = load_json_object(resolved_config, label="Pilot selection/context config")
    _validate_config(config)
    inputs = _require_mapping(config["inputs"], "config inputs")
    _require_exact_fields(
        inputs,
        {"foundation_package", "u80", "canonical_selection_view", "topic_set"},
        "config inputs",
    )

    foundation = _require_mapping(inputs["foundation_package"], "foundation_package")
    _require_exact_fields(
        foundation,
        {"path", "package_identity", "manifest_sha256"},
        "foundation_package",
    )
    package_dir = _resolve_repo_path(
        root, foundation["path"], "foundation package path"
    )
    manifest_path = package_dir / "manifest.json"
    manifest = load_json_object(manifest_path, label="Pilot foundation manifest")
    if sha256_file(manifest_path) != foundation["manifest_sha256"]:
        raise ValueError("Pilot foundation manifest SHA-256 drift。")
    if manifest.get("package_identity") != foundation["package_identity"]:
        raise ValueError("Pilot foundation package identity drift。")

    def load_bound(name: str, label: str) -> tuple[Path, dict[str, Any]]:
        reference = _require_mapping(inputs[name], label)
        _require_exact_fields(
            reference,
            {"path", "artifact_id", "sha256"}
            | ({"u80_identity"} if name == "u80" else set())
            | ({"view_identity"} if name == "canonical_selection_view" else set()),
            label,
        )
        path = _resolve_repo_path(root, reference["path"], f"{label} path")
        payload = load_json_object(path, label=label)
        if sha256_file(path) != reference["sha256"]:
            raise ValueError(f"{label} SHA-256 drift。")
        if payload.get("artifact_id") != reference["artifact_id"]:
            raise ValueError(f"{label} artifact identity drift。")
        return path, payload

    u80_path, u80 = load_bound("u80", "Pilot U80")
    view_path, selection_view = load_bound(
        "canonical_selection_view", "Pilot canonical selection view"
    )
    topics_path, topics_payload = load_bound("topic_set", "W6 frozen Topic set")
    if u80.get("u80_identity") != inputs["u80"]["u80_identity"]:
        raise ValueError("Pilot U80 identity drift。")
    if (
        selection_view.get("view_identity")
        != inputs["canonical_selection_view"]["view_identity"]
    ):
        raise ValueError("Pilot canonical selection view identity drift。")
    manifest_files = _require_mapping(
        manifest.get("files"), "foundation manifest files"
    )
    if manifest_files.get(u80_path.name) != sha256_file(u80_path):
        raise ValueError("foundation manifest/U80 hash binding drift。")
    if manifest_files.get(view_path.name) != sha256_file(view_path):
        raise ValueError("foundation manifest/selection-view hash binding drift。")
    if topics_path.name != "topics.json":
        raise ValueError("Pilot topic_set 必须绑定 frozen topics.json。")

    topic_rows = _require_list(
        topics_payload.get("topics"), "frozen topics", nonempty=True
    )
    topics = {
        _require_text(row.get("topic_id"), "frozen topic_id"): row
        for row in topic_rows
        if isinstance(row, dict)
    }
    configured_topics = {row["topic_id"]: row for row in config["topics"]}
    if set(configured_topics) != set(u80.get("topic_counts", {})):
        raise ValueError("config/U80 Topic roster drift。")
    for topic_id, configured in configured_topics.items():
        frozen = topics.get(topic_id)
        if frozen is None or frozen.get("lifecycle_status") != "frozen":
            raise ValueError(f"Pilot topic 未冻结或不存在：{topic_id}。")
        if frozen.get("research_question") != configured["research_question"]:
            raise ValueError(f"Pilot frozen research question drift：{topic_id}。")

    u80_by_topic: dict[str, tuple[str, ...]] = {}
    for raw_topic in _require_list(u80.get("topics"), "U80 topics", nonempty=True):
        topic = _require_mapping(raw_topic, "U80 topic")
        topic_id = _require_text(topic.get("topic_id"), "U80 topic_id")
        entity_ids = _require_string_list(
            topic.get("ordered_canonical_entity_ids"),
            f"{topic_id} U80 entity ids",
            count=U80_COUNT,
        )
        if topic.get("requested_n") != U80_COUNT:
            raise ValueError(f"{topic_id} U80 requested_n drift。")
        u80_by_topic[topic_id] = tuple(entity_ids)
    if set(u80_by_topic) != set(configured_topics):
        raise ValueError("U80/config Topic roster drift。")

    view_by_topic_entity: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_item in _require_list(selection_view.get("items"), "selection view items"):
        item = _require_mapping(raw_item, "selection view item")
        key = (
            _require_text(item.get("topic_id"), "selection item topic_id"),
            _require_text(item.get("canonical_entity_id"), "canonical_entity_id"),
        )
        if key in view_by_topic_entity:
            raise ValueError(f"canonical selection item 重复：{key}。")
        view_by_topic_entity[key] = item
    for topic_id, entity_ids in u80_by_topic.items():
        for entity_id in entity_ids:
            item = view_by_topic_entity.get((topic_id, entity_id))
            if item is None:
                raise ValueError(
                    f"U80 entity 缺少 canonical selection snapshot：{entity_id}。"
                )
            _require_text(item.get("title"), f"{entity_id} title")
            _require_text(item.get("abstract"), f"{entity_id} abstract")

    return PilotSelectionInputs(
        project_root=root,
        config_path=resolved_config,
        config=config,
        manifest=manifest,
        u80=u80,
        selection_view=selection_view,
        topics_payload=topics_payload,
        topics=topics,
        u80_by_topic=u80_by_topic,
        view_by_topic_entity=view_by_topic_entity,
    )


def topic_config(inputs: PilotSelectionInputs, topic_id: str) -> dict[str, Any]:
    for topic in inputs.config["topics"]:
        if topic["topic_id"] == topic_id:
            return topic
    raise ValueError(f"未知 Pilot Topic：{topic_id}。")


def _u80_reference(inputs: PilotSelectionInputs) -> dict[str, str]:
    reference = inputs.config["inputs"]["u80"]
    return {
        "artifact_id": reference["artifact_id"],
        "u80_identity": reference["u80_identity"],
        "sha256": reference["sha256"],
    }


def rank_pilot_bm25_candidates(
    *,
    research_question: str,
    candidates: Mapping[str, Mapping[str, Any]],
    k: int = SELECTION_K,
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> list[dict[str, Any]]:
    """Rank a frozen canonical candidate universe with the existing BM25 core."""

    if not candidates or len(candidates) < k:
        raise ValueError("BM25 candidate universe 小于 K，fail closed。")
    query_tokens = tokenize_text(_require_text(research_question, "research_question"))
    documents = {
        entity_id: build_document_tokens(item.get("title"), item.get("abstract"))
        for entity_id, item in candidates.items()
    }
    corpus_stats = compute_corpus_stats(documents)
    scored = [
        (
            entity_id,
            bm25_score(query_tokens, tokens, corpus_stats, k1=k1, b=b),
        )
        for entity_id, tokens in documents.items()
    ]
    scored.sort(key=lambda row: (-row[1], row[0]))
    return [
        {"canonical_entity_id": entity_id, "score": score, "rank": rank}
        for rank, (entity_id, score) in enumerate(scored[:k], start=1)
    ]


def _selection_identity_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dict(payload))
    body.pop("artifact_id", None)
    body.pop("selection_identity", None)
    return body


def build_selection_artifact(
    *,
    inputs: PilotSelectionInputs,
    topic_id: str,
    selection_method: Mapping[str, Any],
    selected_canonical_entity_ids: list[str],
    method_specific_provenance: Mapping[str, Any],
    created_at: str,
    git_revision: str,
    is_fixture: bool,
    purpose: str,
    human_selection_freeze: Mapping[str, Any] | None = None,
    reference_selection_freeze: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    topic = topic_config(inputs, topic_id)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_selection",
        "artifact_id": "pending",
        "selection_identity": "pending",
        "pilot_version": PILOT_VERSION,
        "topic": {
            "topic_id": topic_id,
            "question_id": topic["question_id"],
            "research_question_identity": topic["research_question_identity"],
        },
        "u80": _u80_reference(inputs),
        "selection_method": copy.deepcopy(dict(selection_method)),
        "selected_canonical_entity_ids": list(selected_canonical_entity_ids),
        "k": SELECTION_K,
        "method_specific_provenance": copy.deepcopy(dict(method_specific_provenance)),
        "created_at": _require_datetime(created_at, "selection created_at"),
        "provenance": {
            "kind": "pilot_generic_selection_import",
            "created_by": "src.pilot_selection",
            "created_at": created_at,
            "git_revision": _require_git_revision(
                git_revision, "selection git_revision"
            ),
        },
        "is_fixture": is_fixture,
        "purpose": purpose,
    }
    identity = deterministic_identity(
        SELECTION_IDENTITY_PREFIX, _selection_identity_payload(payload)
    )
    payload["selection_identity"] = identity
    payload["artifact_id"] = f"srtp_pilot_selection_{identity.rsplit(':', 1)[-1][:24]}"
    validate_selection_artifact(
        payload,
        inputs=inputs,
        human_selection_freeze=human_selection_freeze,
        reference_selection_freeze=reference_selection_freeze,
    )
    return payload


def build_human_selection_freeze_reference(
    human_selection: Mapping[str, Any],
) -> dict[str, str]:
    """Build the explicit content-addressed dependency stored by formal BM25."""

    selection = _require_mapping(dict(human_selection), "Human selection freeze")
    return {
        "human_selection_artifact_id": _require_text(
            selection.get("artifact_id"), "Human selection artifact_id"
        ),
        "human_selection_identity": _require_text(
            selection.get("selection_identity"), "Human selection identity"
        ),
        "human_selection_sha256": payload_sha256(selection),
        "human_selection_frozen_at": _require_datetime(
            selection.get("created_at"), "Human selection frozen_at"
        ),
    }


def validate_human_selection_freeze_reference(
    reference: Mapping[str, Any], human_selection: Mapping[str, Any]
) -> dict[str, str]:
    """Reject a formal BM25 dependency that does not bind the exact Human artifact."""

    supplied = _require_mapping(dict(reference), "BM25 Human-freeze reference")
    _require_exact_fields(
        supplied,
        {
            "human_selection_artifact_id",
            "human_selection_identity",
            "human_selection_sha256",
            "human_selection_frozen_at",
        },
        "BM25 Human-freeze reference",
    )
    expected = build_human_selection_freeze_reference(human_selection)
    if supplied != expected:
        raise ValueError("BM25/Human selection freeze hash binding drift。")
    return expected


def build_bm25_selection(
    inputs: PilotSelectionInputs,
    *,
    topic_id: str,
    human_selection_freeze: Mapping[str, Any],
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    topic = topic_config(inputs, topic_id)
    validated_human = validate_selection_artifact(human_selection_freeze, inputs=inputs)
    if (
        validated_human["method_id"] != HUMAN_METHOD_ID
        or validated_human["is_fixture"]
        or validated_human["topic_id"] != topic_id
    ):
        raise ValueError(
            "formal BM25 requires same-Topic frozen non-fixture Dual-Curator selection。"
        )
    freeze_reference = build_human_selection_freeze_reference(human_selection_freeze)
    human_frozen_at = freeze_reference["human_selection_frozen_at"]
    bm25_created_at = _require_datetime(created_at, "BM25 created_at")
    if datetime.fromisoformat(
        bm25_created_at.replace("Z", "+00:00")
    ) < datetime.fromisoformat(human_frozen_at.replace("Z", "+00:00")):
        raise ValueError("BM25 created_at 不得早于 Human selection freeze。")
    candidates = {
        entity_id: inputs.view_by_topic_entity[(topic_id, entity_id)]
        for entity_id in inputs.u80_by_topic[topic_id]
    }
    bm25 = inputs.config["bm25"]
    ranked = rank_pilot_bm25_candidates(
        research_question=topic["research_question"],
        candidates=candidates,
        k=SELECTION_K,
        k1=float(bm25["k1"]),
        b=float(bm25["b"]),
    )
    return build_selection_artifact(
        inputs=inputs,
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
            "human_selection_freeze": freeze_reference,
        },
        created_at=created_at,
        git_revision=git_revision,
        is_fixture=False,
        purpose="formal_bm25_condition_after_human_selection_freeze",
        human_selection_freeze=human_selection_freeze,
    )


def validate_selection_artifact(
    payload: Mapping[str, Any],
    *,
    inputs: PilotSelectionInputs,
    human_selection_freeze: Mapping[str, Any] | None = None,
    reference_selection_freeze: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selection = _require_mapping(dict(payload), "selection artifact")
    _require_exact_fields(
        selection,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "selection_identity",
            "pilot_version",
            "topic",
            "u80",
            "selection_method",
            "selected_canonical_entity_ids",
            "k",
            "method_specific_provenance",
            "created_at",
            "provenance",
            "is_fixture",
            "purpose",
        },
        "selection artifact",
    )
    if selection["schema_version"] != SCHEMA_VERSION:
        raise ValueError("selection schema_version drift。")
    if selection["artifact_type"] != "srtp_pilot_selection":
        raise ValueError("selection artifact_type drift。")
    if selection["pilot_version"] != PILOT_VERSION:
        raise ValueError("selection pilot_version drift。")
    topic = _require_mapping(selection["topic"], "selection topic")
    _require_exact_fields(
        topic,
        {"topic_id", "question_id", "research_question_identity"},
        "selection topic",
    )
    expected_topic = topic_config(inputs, _require_text(topic["topic_id"], "topic_id"))
    if topic != {
        "topic_id": expected_topic["topic_id"],
        "question_id": expected_topic["question_id"],
        "research_question_identity": expected_topic["research_question_identity"],
    }:
        raise ValueError("selection Topic/Question identity drift。")
    if selection["u80"] != _u80_reference(inputs):
        raise ValueError("selection U80 identity/hash binding drift。")
    if selection["k"] != SELECTION_K:
        raise ValueError("selection K 必须精确为 8。")
    selected = _require_string_list(
        selection["selected_canonical_entity_ids"],
        "selected_canonical_entity_ids",
        count=SELECTION_K,
    )
    allowed = set(inputs.u80_by_topic[topic["topic_id"]])
    unknown = sorted(set(selected) - allowed)
    if unknown:
        raise ValueError(
            "selection 含 U80 外 canonical ID：" + ", ".join(unknown) + "。"
        )
    _require_datetime(selection["created_at"], "selection created_at")
    provenance = _require_mapping(selection["provenance"], "selection provenance")
    _require_exact_fields(
        provenance,
        {"kind", "created_by", "created_at", "git_revision"},
        "selection provenance",
    )
    _require_text(provenance["kind"], "selection provenance kind")
    _require_text(provenance["created_by"], "selection provenance created_by")
    if provenance["created_at"] != selection["created_at"]:
        raise ValueError("selection provenance time drift。")
    _require_git_revision(provenance["git_revision"], "selection git revision")
    is_fixture = _require_bool(selection["is_fixture"], None, "selection is_fixture")
    purpose = _require_text(selection["purpose"], "selection purpose")

    method = _require_mapping(selection["selection_method"], "selection_method")
    _require_exact_fields(
        method, {"method_id", "family", "config_identity"}, "selection_method"
    )
    method_id = _require_text(method["method_id"], "selection method_id")
    details = _require_mapping(
        selection["method_specific_provenance"], "method_specific_provenance"
    )
    if method_id == BM25_METHOD_ID:
        if is_fixture:
            raise ValueError("正式 BM25 selection 不得标为 fixture。")
        bm25 = inputs.config["bm25"]
        if method != {
            "method_id": BM25_METHOD_ID,
            "family": "lexical",
            "config_identity": bm25["config_identity"],
        }:
            raise ValueError("BM25 selection method/config identity drift。")
        _validate_bm25_provenance(
            details,
            selected,
            expected_topic,
            bm25,
            inputs=inputs,
            topic_id=topic["topic_id"],
            bm25_created_at=selection["created_at"],
            human_selection_freeze=human_selection_freeze,
            reference_selection_freeze=reference_selection_freeze,
        )
    elif method_id == HUMAN_METHOD_ID:
        if is_fixture:
            raise ValueError("正式 Dual-Curator selection 不得标为 fixture。")
        human = inputs.config["dual_curator"]
        if method != {
            "method_id": HUMAN_METHOD_ID,
            "family": "human_dual_curator",
            "config_identity": human["config_identity"],
        }:
            raise ValueError("Human selection method/config identity drift。")
        _validate_human_selection_provenance(details, selected)
    elif method_id == REFERENCE_METHOD_ID:
        from src.pilot_reference_selection import (
            validate_reference_selection_method_provenance,
        )

        if method != {
            "method_id": REFERENCE_METHOD_ID,
            "family": "ai_assisted_human_reference",
            "config_identity": details.get("protocol_config_identity"),
        }:
            raise ValueError("Reference selection method/config identity drift。")
        validate_reference_selection_method_provenance(
            details,
            selected,
            inputs=inputs,
            is_fixture=is_fixture,
            purpose=purpose,
        )
    elif method_id == FIXTURE_METHOD_ID:
        if not is_fixture or purpose != "plumbing_only":
            raise ValueError(
                "mock selection 只能用于 is_fixture=true / plumbing_only。"
            )
        if method["family"] != "testing_only" or method["config_identity"] != "fixture":
            raise ValueError("mock selection method fields drift。")
        if set(details) != {"fixture_strategy"}:
            raise ValueError("mock selection provenance 只能声明 fixture_strategy。")
        _require_text(details["fixture_strategy"], "fixture_strategy")
    else:
        raise ValueError(f"unknown Pilot selection method：{method_id}。")

    expected_identity = deterministic_identity(
        SELECTION_IDENTITY_PREFIX, _selection_identity_payload(selection)
    )
    if selection["selection_identity"] != expected_identity:
        raise ValueError("selection identity drift。")
    expected_artifact_id = (
        f"srtp_pilot_selection_{expected_identity.rsplit(':', 1)[-1][:24]}"
    )
    if selection["artifact_id"] != expected_artifact_id:
        raise ValueError("selection artifact_id drift。")
    return {
        "topic_id": topic["topic_id"],
        "question_id": topic["question_id"],
        "research_question_identity": topic["research_question_identity"],
        "u80": copy.deepcopy(selection["u80"]),
        "k": SELECTION_K,
        "selected_canonical_entity_ids": tuple(selected),
        "method_id": method_id,
        "selection_identity": expected_identity,
        "artifact_id": expected_artifact_id,
        "is_fixture": is_fixture,
        "purpose": purpose,
    }


def _validate_bm25_provenance(
    details: Mapping[str, Any],
    selected: list[str],
    topic: Mapping[str, Any],
    bm25: Mapping[str, Any],
    *,
    inputs: PilotSelectionInputs,
    topic_id: str,
    bm25_created_at: str,
    human_selection_freeze: Mapping[str, Any] | None,
    reference_selection_freeze: Mapping[str, Any] | None,
) -> None:
    legacy_fields = {
        "query",
        "query_field",
        "paper_representation",
        "tokenizer",
        "k1",
        "b",
        "corpus_document_count",
        "ranking",
        "bm25_config_identity",
        "human_selection_freeze",
    }
    reference_fields = (legacy_fields - {"human_selection_freeze"}) | {
        "formal_execution_policy",
        "reference_selection_freeze",
    }
    actual_fields = set(details)
    if frozenset(actual_fields) not in {
        frozenset(legacy_fields),
        frozenset(reference_fields),
    }:
        raise ValueError("BM25 provenance fields drift。")
    if details["query"] != topic["research_question"]:
        raise ValueError("BM25 query 不是 frozen research_question。")
    for key in ("query_field", "paper_representation", "tokenizer", "k1", "b"):
        if details[key] != bm25[key]:
            raise ValueError(f"BM25 provenance {key} drift。")
    if details["corpus_document_count"] != U80_COUNT:
        raise ValueError("BM25 corpus 必须是完整 U80。")
    if details["bm25_config_identity"] != bm25["config_identity"]:
        raise ValueError("BM25 config identity drift。")
    if actual_fields == legacy_fields:
        if reference_selection_freeze is not None:
            raise ValueError("legacy BM25 provenance 不得混入 Reference freeze。")
        if human_selection_freeze is None:
            raise ValueError("BM25 validation 缺少 frozen Human selection artifact。")
        validated_dependency = validate_selection_artifact(
            human_selection_freeze, inputs=inputs
        )
        if (
            validated_dependency["method_id"] != HUMAN_METHOD_ID
            or validated_dependency["is_fixture"]
            or validated_dependency["topic_id"] != topic_id
        ):
            raise ValueError("BM25 Human-freeze artifact method/topic/fixture drift。")
        expected_freeze = validate_human_selection_freeze_reference(
            details["human_selection_freeze"], human_selection_freeze
        )
        dependency_frozen_at = expected_freeze["human_selection_frozen_at"]
    else:
        if human_selection_freeze is not None:
            raise ValueError("Reference-bound BM25 provenance 不得混入 Human freeze。")
        if reference_selection_freeze is None:
            raise ValueError(
                "BM25 validation 缺少 frozen Reference selection artifact。"
            )
        if details["formal_execution_policy"] != "after_reference_selection_freeze":
            raise ValueError("BM25 Reference execution policy drift。")
        from src.pilot_reference_selection import (
            validate_reference_selection_freeze_reference,
        )

        validated_dependency = validate_selection_artifact(
            reference_selection_freeze, inputs=inputs
        )
        if (
            validated_dependency["method_id"] != REFERENCE_METHOD_ID
            or validated_dependency["is_fixture"]
            or validated_dependency["topic_id"] != topic_id
        ):
            raise ValueError(
                "BM25 Reference-freeze artifact method/topic/fixture drift。"
            )
        expected_freeze = validate_reference_selection_freeze_reference(
            details["reference_selection_freeze"],
            reference_selection_freeze,
            inputs=inputs,
            require_formal=True,
        )
        dependency_frozen_at = expected_freeze["reference_selection_frozen_at"]
    if datetime.fromisoformat(
        _require_datetime(bm25_created_at, "BM25 created_at").replace("Z", "+00:00")
    ) < datetime.fromisoformat(
        _require_datetime(dependency_frozen_at, "selection frozen_at").replace(
            "Z", "+00:00"
        )
    ):
        raise ValueError("BM25 artifact 早于 required selection freeze。")
    ranking = _require_list(details["ranking"], "BM25 ranking", nonempty=True)
    if len(ranking) != SELECTION_K:
        raise ValueError("BM25 selection ranking 必须精确为 Top-8。")
    ranked_ids = []
    previous: tuple[float, str] | None = None
    for expected_rank, raw in enumerate(ranking, start=1):
        row = _require_mapping(raw, "BM25 ranking row")
        _require_exact_fields(row, {"canonical_entity_id", "score", "rank"}, "BM25 row")
        entity_id = _require_text(row["canonical_entity_id"], "BM25 canonical ID")
        score = _require_number(row["score"], "BM25 score")
        if row["rank"] != expected_rank:
            raise ValueError("BM25 ranks 必须从 1 连续到 8。")
        key = (-score, entity_id)
        if previous is not None and key < previous:
            raise ValueError("BM25 ranking 不是 score desc / canonical ID asc。")
        previous = key
        ranked_ids.append(entity_id)
    if ranked_ids != selected:
        raise ValueError("BM25 selected IDs 必须与 ranking Top-8 顺序一致。")
    expected_ranking = rank_pilot_bm25_candidates(
        research_question=topic["research_question"],
        candidates={
            entity_id: inputs.view_by_topic_entity[(topic_id, entity_id)]
            for entity_id in inputs.u80_by_topic[topic_id]
        },
        k=SELECTION_K,
        k1=float(bm25["k1"]),
        b=float(bm25["b"]),
    )
    if ranking != expected_ranking:
        raise ValueError(
            "BM25 ranking 与 frozen U80 deterministic reconstruction 不一致。"
        )


def _validate_human_selection_provenance(
    details: Mapping[str, Any], selected: list[str]
) -> None:
    _require_exact_fields(
        details,
        {
            "comparison_artifact_id",
            "comparison_sha256",
            "curator_submission_artifact_ids",
            "curator_submission_sha256s",
            "intersection_canonical_entity_ids",
            "symmetric_difference_canonical_entity_ids",
            "overlap_count",
            "jaccard",
            "adjudication",
            "external_lookup",
            "independent_submissions",
        },
        "human selection provenance",
    )
    _require_text(details["comparison_artifact_id"], "comparison artifact_id")
    if not re.fullmatch(r"[0-9a-f]{64}", str(details["comparison_sha256"])):
        raise ValueError("comparison SHA-256 非法。")
    _require_string_list(
        details["curator_submission_artifact_ids"], "curator submission ids", count=2
    )
    hashes = _require_string_list(
        details["curator_submission_sha256s"], "curator submission hashes", count=2
    )
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes):
        raise ValueError("curator submission SHA-256 非法。")
    intersection = _require_string_list(
        details["intersection_canonical_entity_ids"], "human intersection"
    )
    symmetric = _require_string_list(
        details["symmetric_difference_canonical_entity_ids"],
        "human symmetric difference",
    )
    if details["overlap_count"] != len(intersection) or len(intersection) < 4:
        raise ValueError("final human selection 要求 curator overlap >= 4。")
    union_count = len(intersection) + len(symmetric)
    expected_jaccard = len(intersection) / union_count
    if not math.isclose(float(details["jaccard"]), expected_jaccard, abs_tol=1e-12):
        raise ValueError("human selection Jaccard drift。")
    _require_bool(details["external_lookup"], False, "human external_lookup")
    _require_bool(details["independent_submissions"], True, "independent submissions")
    adjudication = _require_mapping(details["adjudication"], "adjudication provenance")
    _require_exact_fields(
        adjudication,
        {
            "required",
            "artifact_id",
            "sha256",
            "adjudicator_id",
            "selected_from_symmetric_difference_canonical_entity_ids",
        },
        "adjudication provenance",
    )
    required = len(intersection) < SELECTION_K
    _require_bool(adjudication["required"], required, "adjudication required")
    additions = _require_string_list(
        adjudication["selected_from_symmetric_difference_canonical_entity_ids"],
        "adjudication additions",
        count=SELECTION_K - len(intersection),
    )
    if not set(additions) <= set(symmetric):
        raise ValueError("adjudicator 选择超出 symmetric difference。")
    if required:
        _require_text(adjudication["artifact_id"], "adjudication artifact_id")
        if not re.fullmatch(r"[0-9a-f]{64}", str(adjudication["sha256"])):
            raise ValueError("adjudication SHA-256 非法。")
        _require_text(adjudication["adjudicator_id"], "adjudicator_id")
    elif any(
        adjudication[key] is not None
        for key in ("artifact_id", "sha256", "adjudicator_id")
    ):
        raise ValueError("full intersection 不应伪造 adjudication。")
    if set(selected) != set(intersection) | set(additions):
        raise ValueError(
            "final human selection 不等于 intersection + adjudicated additions。"
        )


def _opaque_candidate_id(
    inputs: PilotSelectionInputs,
    topic_id: str,
    curator_slot: str,
    entity_id: str,
) -> str:
    human = inputs.config["dual_curator"]
    digest = hashlib.sha256(
        "|".join(
            [human["opaque_candidate_seed"], curator_slot, topic_id, entity_id]
        ).encode("utf-8")
    ).hexdigest()
    return f"candidate_{digest[:16]}"


def _candidate_order_key(
    inputs: PilotSelectionInputs,
    topic_id: str,
    curator_slot: str,
    entity_id: str,
) -> tuple[str, str]:
    seed = inputs.config["dual_curator"]["candidate_order_seed"]
    return (
        hashlib.sha256(
            f"{seed}|{curator_slot}|{topic_id}|{entity_id}".encode("utf-8")
        ).hexdigest(),
        entity_id,
    )


def _source_snapshot_payload(item: Mapping[str, Any], entity_id: str) -> dict[str, str]:
    return {
        "canonical_entity_id": entity_id,
        "source_selection_item_id": _require_text(
            item.get("selection_item_id"), "source selection_item_id"
        ),
        "title": _require_text(item.get("title"), "source title"),
        "abstract": _require_text(item.get("abstract"), "source abstract"),
    }


def _expected_curator_roster(
    inputs: PilotSelectionInputs, *, topic_id: str, curator_slot: str
) -> tuple[list[dict[str, str]], list[dict[str, str]], str]:
    ordered_entities = sorted(
        inputs.u80_by_topic[topic_id],
        key=lambda entity_id: _candidate_order_key(
            inputs, topic_id, curator_slot, entity_id
        ),
    )
    candidates: list[dict[str, str]] = []
    mapping_rows: list[dict[str, str]] = []
    for entity_id in ordered_entities:
        item = inputs.view_by_topic_entity[(topic_id, entity_id)]
        candidate_id = _opaque_candidate_id(inputs, topic_id, curator_slot, entity_id)
        snapshot = _source_snapshot_payload(item, entity_id)
        candidates.append(
            {
                "candidate_id": candidate_id,
                "title": snapshot["title"],
                "abstract": snapshot["abstract"],
            }
        )
        mapping_rows.append(
            {
                "candidate_id": candidate_id,
                "canonical_entity_id": entity_id,
                "source_selection_item_id": snapshot["source_selection_item_id"],
                "source_snapshot_sha256": payload_sha256(snapshot),
            }
        )
    roster_identity = deterministic_identity(
        CURATOR_ROSTER_IDENTITY_PREFIX,
        {
            "pilot_version": PILOT_VERSION,
            "topic_id": topic_id,
            "curator_slot": curator_slot,
            "u80": _u80_reference(inputs),
            "candidates": candidates,
        },
    )
    return candidates, mapping_rows, roster_identity


def _topic_guidance(inputs: PilotSelectionInputs, topic_id: str) -> dict[str, Any]:
    topic = inputs.topics[topic_id]
    return {
        "scientific_object": topic["scientific_object"],
        "data_modality": topic["data_modality"],
        "target_task": topic["target_task"],
        "method_role": topic["method_role"],
        "scope_in": copy.deepcopy(topic["scope_in"]),
        "scope_out": copy.deepcopy(topic["scope_out"]),
        "boundary_cases": copy.deepcopy(topic["boundary_cases"]),
    }


def _task_identity_payload(
    payload: Mapping[str, Any], identity_field: str
) -> dict[str, Any]:
    body = copy.deepcopy(dict(payload))
    body.pop("artifact_id", None)
    body.pop(identity_field, None)
    return body


def build_curator_task_and_map(
    inputs: PilotSelectionInputs,
    *,
    topic_id: str,
    curator_slot: str,
    created_at: str,
    git_revision: str,
    is_fixture: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if curator_slot not in CURATOR_SLOTS:
        raise ValueError("curator_slot 必须是 curator_a 或 curator_b。")
    topic = topic_config(inputs, topic_id)
    candidates, mapping_rows, roster_identity = _expected_curator_roster(
        inputs, topic_id=topic_id, curator_slot=curator_slot
    )
    task: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_curator_task",
        "artifact_id": "pending",
        "task_identity": "pending",
        "pilot_version": PILOT_VERSION,
        "task_id": f"pilot_{curator_slot}_{topic['question_id']}",
        "curator_slot": curator_slot,
        "candidate_roster_identity": roster_identity,
        "topic": {
            "topic_id": topic_id,
            "question_id": topic["question_id"],
            "research_question": topic["research_question"],
            "research_question_identity": topic["research_question_identity"],
            "guidance": _topic_guidance(inputs, topic_id),
        },
        "u80": _u80_reference(inputs),
        "selection_policy": {
            "candidate_count": U80_COUNT,
            "required_selection_count": SELECTION_K,
            "external_lookup": False,
            "independent_submission_required": True,
            "reason_requirement": "one_short_reason_per_selected_candidate",
        },
        "blindness": {
            "visible_candidate_fields": sorted(CURATOR_VISIBLE_CANDIDATE_FIELDS),
            "hidden_candidate_fields": sorted(CURATOR_FORBIDDEN_KEYS),
            "authors_hidden": True,
            "venue_hidden": True,
            "bm25_output_generated": False,
            "other_curator_submission_visible": False,
        },
        "candidates": candidates,
        "created_at": _require_datetime(created_at, "curator task created_at"),
        "provenance": {
            "kind": "pilot_blind_curator_task_preparation",
            "created_by": "src.pilot_selection",
            "created_at": created_at,
            "git_revision": _require_git_revision(git_revision, "task git revision"),
        },
        "is_fixture": is_fixture,
        "purpose": (
            "plumbing_only" if is_fixture else "future_independent_human_selection"
        ),
    }
    task_identity = deterministic_identity(
        CURATOR_TASK_IDENTITY_PREFIX, _task_identity_payload(task, "task_identity")
    )
    task["task_identity"] = task_identity
    task["artifact_id"] = (
        f"srtp_pilot_curator_task_{task_identity.rsplit(':', 1)[-1][:24]}"
    )

    mapping: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_curator_candidate_map",
        "artifact_id": "pending",
        "map_identity": "pending",
        "pilot_version": PILOT_VERSION,
        "task": {
            "task_id": task["task_id"],
            "artifact_id": task["artifact_id"],
            "task_identity": task_identity,
            "sha256": payload_sha256(task),
        },
        "topic_id": topic_id,
        "u80": _u80_reference(inputs),
        "candidate_roster_identity": roster_identity,
        "candidate_map": mapping_rows,
        "access_policy": "coordinator_private_do_not_share_with_curators",
        "created_at": created_at,
        "provenance": copy.deepcopy(task["provenance"]),
        "is_fixture": is_fixture,
    }
    map_identity = deterministic_identity(
        CURATOR_MAP_IDENTITY_PREFIX, _task_identity_payload(mapping, "map_identity")
    )
    mapping["map_identity"] = map_identity
    mapping["artifact_id"] = (
        f"srtp_pilot_curator_map_{map_identity.rsplit(':', 1)[-1][:24]}"
    )
    validate_curator_task(task, mapping=mapping, inputs=inputs)
    return task, mapping


def _find_forbidden_task_keys(value: Any) -> list[str]:
    hits: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                if str(key).casefold() in CURATOR_FORBIDDEN_KEYS:
                    hits.append(child_path)
                walk(child, child_path)
        elif isinstance(node, list):
            for child in node:
                walk(child, path)

    walk(value, "")
    return sorted(hits)


def validate_curator_task(
    task: Mapping[str, Any], *, mapping: Mapping[str, Any], inputs: PilotSelectionInputs
) -> None:
    task = _require_mapping(dict(task), "curator task")
    mapping = _require_mapping(dict(mapping), "curator candidate map")
    _require_exact_fields(
        task,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "task_identity",
            "pilot_version",
            "task_id",
            "curator_slot",
            "candidate_roster_identity",
            "topic",
            "u80",
            "selection_policy",
            "blindness",
            "candidates",
            "created_at",
            "provenance",
            "is_fixture",
            "purpose",
        },
        "curator task",
    )
    if task.get("artifact_type") != "srtp_pilot_curator_task" or not isinstance(
        task.get("is_fixture"), bool
    ):
        raise ValueError("curator task header/fixture status drift。")
    if task.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("curator task schema drift。")
    if task.get("curator_slot") not in CURATOR_SLOTS:
        raise ValueError("curator task slot drift。")
    expected_purpose = (
        "plumbing_only" if task["is_fixture"] else "future_independent_human_selection"
    )
    if task.get("purpose") != expected_purpose:
        raise ValueError("curator task purpose/fixture separation drift。")
    if task.get("pilot_version") != PILOT_VERSION:
        raise ValueError("curator task pilot version drift。")
    topic = _require_mapping(task.get("topic"), "curator task topic")
    _require_exact_fields(
        topic,
        {
            "topic_id",
            "question_id",
            "research_question",
            "research_question_identity",
            "guidance",
        },
        "curator task topic",
    )
    expected_topic = topic_config(inputs, topic.get("topic_id"))
    if topic.get("question_id") != expected_topic["question_id"]:
        raise ValueError("curator task question identity drift。")
    if topic.get("research_question") != expected_topic["research_question"]:
        raise ValueError("curator task research question drift。")
    if (
        topic.get("research_question_identity")
        != expected_topic["research_question_identity"]
    ):
        raise ValueError("curator task research question hash drift。")
    if topic.get("guidance") != _topic_guidance(inputs, expected_topic["topic_id"]):
        raise ValueError("curator task frozen guidance drift。")
    if task.get("u80") != _u80_reference(inputs):
        raise ValueError("curator task U80 binding drift。")
    expected_candidates, expected_rows, expected_roster_identity = (
        _expected_curator_roster(
            inputs,
            topic_id=topic["topic_id"],
            curator_slot=task["curator_slot"],
        )
    )
    if task.get("candidate_roster_identity") != expected_roster_identity:
        raise ValueError("curator candidate roster identity drift。")
    selection_policy = _require_mapping(
        task.get("selection_policy"), "curator selection policy"
    )
    if selection_policy != {
        "candidate_count": U80_COUNT,
        "required_selection_count": SELECTION_K,
        "external_lookup": False,
        "independent_submission_required": True,
        "reason_requirement": "one_short_reason_per_selected_candidate",
    }:
        raise ValueError("curator task selection policy drift。")
    candidates = _require_list(
        task.get("candidates"), "curator candidates", nonempty=True
    )
    if len(candidates) != U80_COUNT:
        raise ValueError("curator task 必须包含完整 80 candidates。")
    if candidates != expected_candidates:
        raise ValueError(
            "curator-visible candidate roster/order/content 与 frozen source drift。"
        )
    candidate_ids = []
    for raw in candidates:
        candidate = _require_mapping(raw, "curator candidate")
        if set(candidate) != CURATOR_VISIBLE_CANDIDATE_FIELDS:
            raise ValueError(
                "curator candidate 暴露字段超出 candidate_id/title/abstract。"
            )
        candidate_ids.append(
            _require_text(candidate["candidate_id"], "opaque candidate_id")
        )
        _require_text(candidate["title"], "curator candidate title")
        _require_text(candidate["abstract"], "curator candidate abstract")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("curator opaque candidate IDs 重复。")
    forbidden = _find_forbidden_task_keys({"candidates": candidates})
    if forbidden:
        raise ValueError(
            "curator task 泄漏 forbidden candidate fields：" + ", ".join(forbidden)
        )
    blindness = _require_mapping(task.get("blindness"), "task blindness")
    _require_exact_fields(
        blindness,
        {
            "visible_candidate_fields",
            "hidden_candidate_fields",
            "authors_hidden",
            "venue_hidden",
            "bm25_output_generated",
            "other_curator_submission_visible",
        },
        "task blindness",
    )
    if blindness.get("visible_candidate_fields") != sorted(
        CURATOR_VISIBLE_CANDIDATE_FIELDS
    ) or blindness.get("hidden_candidate_fields") != sorted(CURATOR_FORBIDDEN_KEYS):
        raise ValueError("curator task blindness field registry drift。")
    if blindness.get("bm25_output_generated") is not False:
        raise ValueError("curator task 不得声明已生成 BM25 output。")
    if blindness.get("other_curator_submission_visible") is not False:
        raise ValueError("curator task 不得暴露另一 curator submission。")
    if (
        blindness.get("authors_hidden") is not True
        or blindness.get("venue_hidden") is not True
    ):
        raise ValueError("curator task 必须隐藏 authors/venue。")
    expected_task_identity = deterministic_identity(
        CURATOR_TASK_IDENTITY_PREFIX, _task_identity_payload(task, "task_identity")
    )
    if task.get("task_identity") != expected_task_identity:
        raise ValueError("curator task identity drift。")
    if task.get("artifact_id") != (
        f"srtp_pilot_curator_task_{expected_task_identity.rsplit(':', 1)[-1][:24]}"
    ):
        raise ValueError("curator task artifact_id drift。")
    _require_datetime(task.get("created_at"), "curator task created_at")
    task_provenance = _require_mapping(task.get("provenance"), "task provenance")
    if task_provenance.get("created_at") != task["created_at"]:
        raise ValueError("curator task provenance time drift。")
    _require_git_revision(task_provenance.get("git_revision"), "task git revision")

    _require_exact_fields(
        mapping,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "map_identity",
            "pilot_version",
            "task",
            "topic_id",
            "u80",
            "candidate_roster_identity",
            "candidate_map",
            "access_policy",
            "created_at",
            "provenance",
            "is_fixture",
        },
        "candidate map",
    )
    if mapping.get("artifact_type") != "srtp_pilot_curator_candidate_map":
        raise ValueError("candidate map artifact_type drift。")
    if mapping.get("is_fixture") != task["is_fixture"]:
        raise ValueError("candidate map/task fixture status drift。")
    if mapping.get("access_policy") != "coordinator_private_do_not_share_with_curators":
        raise ValueError("candidate map access policy drift。")
    if (
        mapping.get("u80") != _u80_reference(inputs)
        or mapping.get("topic_id") != topic["topic_id"]
    ):
        raise ValueError("candidate map Topic/U80 binding drift。")
    if mapping.get("candidate_roster_identity") != expected_roster_identity:
        raise ValueError("candidate map/visible roster identity drift。")
    if mapping.get("task") != {
        "task_id": task["task_id"],
        "artifact_id": task["artifact_id"],
        "task_identity": task["task_identity"],
        "sha256": payload_sha256(task),
    }:
        raise ValueError("candidate map/task binding drift。")
    rows = _require_list(
        mapping.get("candidate_map"), "candidate map rows", nonempty=True
    )
    for raw in rows:
        row = _require_mapping(raw, "candidate map row")
        _require_exact_fields(
            row,
            {
                "candidate_id",
                "canonical_entity_id",
                "source_selection_item_id",
                "source_snapshot_sha256",
            },
            "candidate map row",
        )
    if rows != expected_rows:
        raise ValueError(
            "candidate map opaque→canonical/source snapshot reconstruction drift。"
        )
    mapped_ids = _require_string_list(
        [row.get("candidate_id") for row in rows if isinstance(row, dict)],
        "mapped candidate IDs",
        count=U80_COUNT,
    )
    if set(mapped_ids) != set(candidate_ids):
        raise ValueError("candidate map/task candidate roster drift。")
    mapped_entities = _require_string_list(
        [row.get("canonical_entity_id") for row in rows if isinstance(row, dict)],
        "mapped canonical IDs",
        count=U80_COUNT,
    )
    if set(mapped_entities) != set(inputs.u80_by_topic[topic["topic_id"]]):
        raise ValueError("candidate map/U80 canonical roster drift。")
    expected_map_identity = deterministic_identity(
        CURATOR_MAP_IDENTITY_PREFIX, _task_identity_payload(mapping, "map_identity")
    )
    if mapping.get("map_identity") != expected_map_identity:
        raise ValueError("candidate map identity drift。")
    if (
        mapping.get("created_at") != task["created_at"]
        or mapping.get("provenance") != task["provenance"]
    ):
        raise ValueError("candidate map/task provenance drift。")


def build_blank_curator_response(task: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_curator_response_form",
        "status": "blank_template",
        "task_id": task["task_id"],
        "task_identity": task["task_identity"],
        "curator_slot": task["curator_slot"],
        "curator_id": "",
        "selected_candidates": [
            {"candidate_id": "", "selection_reason": ""} for _ in range(SELECTION_K)
        ],
        "timing": {"started_at": "", "completed_at": "", "elapsed_minutes": None},
        "external_lookup": False,
        "independent_submission_acknowledged": False,
        "submitted_at": "",
        "notes": "",
        "is_fixture": task["is_fixture"],
    }


def render_curator_task_markdown(task: Mapping[str, Any]) -> str:
    """Render only the already validated curator-visible task fields."""

    topic = _require_mapping(task.get("topic"), "curator task topic")
    guidance = _require_mapping(topic.get("guidance"), "curator task guidance")
    lines = [
        f"# {task['curator_slot']} · {topic['question_id']}",
        "",
        "## Frozen Research Question",
        "",
        topic["research_question"],
        "",
        "## Frozen Topic Guidance",
        "",
        f"- Scientific object: {guidance['scientific_object']}",
        f"- Data modality: {guidance['data_modality']}",
        f"- Target task: {guidance['target_task']}",
        f"- Method role: {guidance['method_role']}",
        "- Scope in:",
    ]
    lines.extend(f"  - {value}" for value in guidance["scope_in"])
    lines.append("- Scope out:")
    lines.extend(f"  - {value}" for value in guidance["scope_out"])
    lines.append("- Boundary cases:")
    for value in guidance["boundary_cases"]:
        if isinstance(value, dict):
            lines.append(
                "  - "
                + "; ".join(f"{key}: {item}" for key, item in sorted(value.items()))
            )
        else:
            lines.append(f"  - {value}")
    lines.extend(
        [
            "",
            "## Selection Rule",
            "",
            "Independently select exactly 8 of the 80 candidates. Use only the "
            "information in this file; do not perform external lookup.",
            "",
            "## Candidates",
            "",
        ]
    )
    for candidate in task["candidates"]:
        lines.extend(
            [
                f"### {candidate['candidate_id']}",
                "",
                f"Title: {candidate['title']}",
                "",
                f"Abstract: {candidate['abstract']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_curator_instructions_markdown() -> str:
    return """# SRTP Pilot v0.2 · Independent Curator Instructions

The committed preparation package is immutable and read-only. Curators work only
inside a repository-external exported bundle; this package contains no human
selection result.

## Coordinator

1. Assign `curator_a` and `curator_b` to two different people.
2. Use `python -m app.export_pilot_curator_bundle` to create one repository-
   external bundle for each slot. Give each person only their own exported
   bundle.
3. Never share the `coordinator/` directory with a curator.
4. Do not show either curator BM25 output, the other curator's response, OpenAlex
   source rank, query support, citation counts, authors, or venue.

## Each curator

For each of the two Topic Markdown files:

1. Read the frozen Research Question and Topic guidance.
2. Review all 80 opaque candidates using only title and abstract.
   If an abstract contains a URL, do not click or open it. Do not search a DOI,
   title, author, or paper page. Use only the Question, Topic guidance, Title,
   and Abstract text already present in the exported bundle.
3. Independently select exactly 8 candidates.
4. In the matching response JSON, set `status` to `completed`, fill a stable
   `curator_id`, enter the 8 candidate IDs and one short reason for each, and
   record either start/end times or elapsed minutes.
5. Keep `external_lookup` false, set
   `independent_submission_acknowledged` true, and record `submitted_at` with a
   timezone.
6. Return only the two completed response JSON files from the external bundle to
   the coordinator.

Do not edit the committed preparation package, Python, task Markdown, bundle
manifest, or coordinator mappings. A planning estimate is 2–3 hours per Topic
(4–6 hours per curator); actual elapsed time must be recorded.
"""


def _candidate_map_index(mapping: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = _require_list(
        mapping.get("candidate_map"), "candidate map rows", nonempty=True
    )
    index: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = _require_mapping(raw, "candidate map row")
        candidate_id = _require_text(row.get("candidate_id"), "mapped candidate_id")
        if candidate_id in index:
            raise ValueError("candidate map candidate_id 重复。")
        index[candidate_id] = row
    return index


def _validate_task_map_binding(
    task: Mapping[str, Any], mapping: Mapping[str, Any]
) -> None:
    expected = {
        "task_id": task.get("task_id"),
        "artifact_id": task.get("artifact_id"),
        "task_identity": task.get("task_identity"),
        "sha256": payload_sha256(task),
    }
    if mapping.get("task") != expected:
        raise ValueError("candidate map/task hash binding drift。")
    if mapping.get("is_fixture") != task.get("is_fixture"):
        raise ValueError("candidate map/task fixture status drift。")


def _validate_human_timing(value: Any, label: str) -> dict[str, Any]:
    timing = _require_mapping(value, label)
    _require_exact_fields(
        timing, {"started_at", "completed_at", "elapsed_minutes"}, label
    )
    started = str(timing["started_at"] or "").strip()
    completed = str(timing["completed_at"] or "").strip()
    elapsed = timing["elapsed_minutes"]
    if started or completed:
        if not started or not completed:
            raise ValueError(f"{label} start/end 必须成对填写。")
        start_dt = datetime.fromisoformat(
            _require_datetime(started, f"{label} started_at").replace("Z", "+00:00")
        )
        end_dt = datetime.fromisoformat(
            _require_datetime(completed, f"{label} completed_at").replace("Z", "+00:00")
        )
        if end_dt <= start_dt:
            raise ValueError(f"{label} completed_at 必须晚于 started_at。")
    elif elapsed is None:
        raise ValueError(f"{label} 必须填写 start/end 或 elapsed_minutes。")
    if elapsed is not None:
        _require_number(elapsed, f"{label} elapsed_minutes", minimum=0.01)
    return copy.deepcopy(timing)


def validate_completed_curator_response(
    form: Mapping[str, Any], *, task: Mapping[str, Any], mapping: Mapping[str, Any]
) -> dict[str, Any]:
    _validate_task_map_binding(task, mapping)
    response = _require_mapping(dict(form), "curator response")
    _require_exact_fields(
        response,
        {
            "schema_version",
            "artifact_type",
            "status",
            "task_id",
            "task_identity",
            "curator_slot",
            "curator_id",
            "selected_candidates",
            "timing",
            "external_lookup",
            "independent_submission_acknowledged",
            "submitted_at",
            "notes",
            "is_fixture",
        },
        "curator response",
    )
    if response["schema_version"] != SCHEMA_VERSION:
        raise ValueError("curator response schema drift。")
    if response["artifact_type"] != "srtp_pilot_curator_response_form":
        raise ValueError("curator response artifact_type drift。")
    if response["status"] != "completed":
        raise ValueError("curator response 必须标为 completed。")
    for key in ("task_id", "task_identity", "curator_slot", "is_fixture"):
        if response[key] != task[key]:
            raise ValueError(f"curator response {key} 与 task 不一致。")
    curator_id = _require_text(response["curator_id"], "curator_id")
    selected_rows = _require_list(
        response["selected_candidates"], "selected candidates", nonempty=True
    )
    if len(selected_rows) != SELECTION_K:
        raise ValueError("每位 curator 必须精确选择 8 篇。")
    mapping_index = _candidate_map_index(mapping)
    candidate_ids: list[str] = []
    reasons: dict[str, str] = {}
    for raw in selected_rows:
        row = _require_mapping(raw, "selected candidate")
        _require_exact_fields(
            row, {"candidate_id", "selection_reason"}, "selected candidate"
        )
        candidate_id = _require_text(row["candidate_id"], "selected candidate_id")
        reason = _require_text(row["selection_reason"], "selection reason")
        if len(reason) > 500:
            raise ValueError("selection reason 应保持简短（<=500 chars）。")
        if candidate_id not in mapping_index:
            raise ValueError(f"curator response 含 unknown candidate：{candidate_id}。")
        candidate_ids.append(candidate_id)
        reasons[candidate_id] = reason
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("curator response 不得重复 candidate。")
    _require_bool(response["external_lookup"], False, "curator external_lookup")
    _require_bool(
        response["independent_submission_acknowledged"],
        True,
        "independent submission acknowledgement",
    )
    submitted_at = _require_datetime(response["submitted_at"], "submitted_at")
    timing = _validate_human_timing(response["timing"], "curator timing")
    canonical_ids = [
        mapping_index[candidate_id]["canonical_entity_id"]
        for candidate_id in candidate_ids
    ]
    return {
        "curator_id": curator_id,
        "curator_slot": response["curator_slot"],
        "candidate_ids": candidate_ids,
        "canonical_entity_ids": canonical_ids,
        "reasons": reasons,
        "timing": copy.deepcopy(timing),
        "submitted_at": submitted_at,
        "notes": str(response["notes"] or ""),
        "external_lookup": False,
        "independent_submission_acknowledged": True,
    }


def _preparation_package_reference(
    manifest: Mapping[str, Any], manifest_sha256: str
) -> dict[str, str]:
    return {
        "artifact_id": _require_text(
            manifest.get("artifact_id"), "preparation artifact_id"
        ),
        "package_identity": _require_text(
            manifest.get("package_identity"), "preparation package_identity"
        ),
        "manifest_sha256": _require_sha256(
            manifest_sha256, "preparation manifest SHA-256"
        ),
    }


def _manifest_task_summary(
    manifest: Mapping[str, Any], *, curator_slot: str, task_id: str
) -> dict[str, Any]:
    matches = [
        _require_mapping(row, "preparation task summary")
        for row in _require_list(manifest.get("tasks"), "preparation manifest tasks")
        if isinstance(row, dict)
        and row.get("curator_slot") == curator_slot
        and row.get("task_artifact_id") is not None
    ]
    for row in matches:
        if row.get("task_artifact_id") and row.get("task_identity"):
            expected_task_id = f"pilot_{curator_slot}_{row.get('question_id')}"
            if expected_task_id == task_id:
                return row
    raise ValueError("response task/slot 不属于 trusted preparation manifest。")


def validate_curator_import_chain(
    *,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    task: Mapping[str, Any],
    mapping: Mapping[str, Any],
    inputs: PilotSelectionInputs,
    expected_curator_slot: str,
) -> dict[str, Any]:
    """Close manifest → task → visible roster → map → U80/source snapshot."""

    if payload_sha256(manifest) != _require_sha256(
        manifest_sha256, "preparation manifest SHA-256"
    ):
        raise ValueError("preparation manifest content/SHA-256 drift。")
    manifest_provenance = _require_mapping(
        manifest.get("provenance"), "preparation manifest provenance"
    )
    is_fixture = _require_bool(
        manifest.get("is_fixture"), None, "preparation manifest is_fixture"
    )
    _, expected_manifest = assemble_curator_preparation_payloads(
        inputs,
        created_at=manifest.get("created_at"),
        git_revision=manifest_provenance.get("git_revision"),
        is_fixture=is_fixture,
    )
    if dict(manifest) != expected_manifest:
        raise ValueError("preparation manifest deterministic reconstruction drift。")
    if manifest.get("pilot_version") != PILOT_VERSION:
        raise ValueError("preparation manifest Pilot version drift。")
    if manifest.get("u80") != _u80_reference(inputs):
        raise ValueError("preparation manifest U80 identity/hash drift。")
    if expected_curator_slot not in CURATOR_SLOTS:
        raise ValueError("expected curator slot 非法。")
    if task.get("curator_slot") != expected_curator_slot:
        raise ValueError("cross-slot response/task import 被拒绝。")
    validate_curator_task(task, mapping=mapping, inputs=inputs)
    summary = _manifest_task_summary(
        manifest,
        curator_slot=expected_curator_slot,
        task_id=_require_text(task.get("task_id"), "curator task_id"),
    )
    expected_summary_fields = {
        "curator_slot": expected_curator_slot,
        "topic_id": task["topic"]["topic_id"],
        "question_id": task["topic"]["question_id"],
        "task_artifact_id": task["artifact_id"],
        "task_identity": task["task_identity"],
        "task_sha256": payload_sha256(task),
        "candidate_roster_identity": task["candidate_roster_identity"],
        "map_artifact_id": mapping["artifact_id"],
        "map_identity": mapping["map_identity"],
        "map_sha256": payload_sha256(mapping),
    }
    for key, expected in expected_summary_fields.items():
        if summary.get(key) != expected:
            raise ValueError(f"preparation manifest task closure drift：{key}。")
    package_reference = _preparation_package_reference(manifest, manifest_sha256)
    return {
        "preparation_package": package_reference,
        "topic_id": task["topic"]["topic_id"],
        "question_id": task["topic"]["question_id"],
        "candidate_roster_identity": task["candidate_roster_identity"],
        "task_sha256": payload_sha256(task),
        "map_sha256": payload_sha256(mapping),
    }


def import_curator_submission(
    form: Mapping[str, Any],
    *,
    task: Mapping[str, Any],
    mapping: Mapping[str, Any],
    preparation_manifest: Mapping[str, Any],
    preparation_manifest_sha256: str,
    inputs: PilotSelectionInputs,
    expected_curator_slot: str,
    imported_at: str,
    git_revision: str,
) -> dict[str, Any]:
    closure = validate_curator_import_chain(
        manifest=preparation_manifest,
        manifest_sha256=preparation_manifest_sha256,
        task=task,
        mapping=mapping,
        inputs=inputs,
        expected_curator_slot=expected_curator_slot,
    )
    validated = validate_completed_curator_response(form, task=task, mapping=mapping)
    if validated["curator_slot"] != expected_curator_slot:
        raise ValueError("cross-slot curator response import 被拒绝。")
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_curator_submission",
        "artifact_id": "pending",
        "submission_identity": "pending",
        "pilot_version": PILOT_VERSION,
        "preparation_package": closure["preparation_package"],
        "task": {
            "task_id": task["task_id"],
            "artifact_id": task["artifact_id"],
            "task_identity": task["task_identity"],
            "sha256": payload_sha256(task),
            "candidate_roster_identity": task["candidate_roster_identity"],
        },
        "candidate_map": {
            "artifact_id": mapping["artifact_id"],
            "map_identity": mapping["map_identity"],
            "sha256": payload_sha256(mapping),
        },
        "topic_id": task["topic"]["topic_id"],
        "u80": copy.deepcopy(task["u80"]),
        "curator_id": validated["curator_id"],
        "curator_slot": validated["curator_slot"],
        "selected_candidates": [
            {
                "candidate_id": candidate_id,
                "canonical_entity_id": canonical_id,
                "selection_reason": validated["reasons"][candidate_id],
            }
            for candidate_id, canonical_id in zip(
                validated["candidate_ids"],
                validated["canonical_entity_ids"],
                strict=True,
            )
        ],
        "timing": validated["timing"],
        "external_lookup": False,
        "independent_submission_acknowledged": True,
        "submitted_at": validated["submitted_at"],
        "notes": validated["notes"],
        "original_response": copy.deepcopy(dict(form)),
        "imported_at": _require_datetime(imported_at, "submission imported_at"),
        "provenance": {
            "kind": "immutable_human_curator_submission_import",
            "created_by": "src.pilot_selection",
            "created_at": imported_at,
            "git_revision": _require_git_revision(
                git_revision, "submission git revision"
            ),
        },
        "is_fixture": bool(form["is_fixture"]),
    }
    identity = deterministic_identity(
        CURATOR_SUBMISSION_IDENTITY_PREFIX,
        _task_identity_payload(payload, "submission_identity"),
    )
    payload["submission_identity"] = identity
    payload["artifact_id"] = (
        f"srtp_pilot_curator_submission_{identity.rsplit(':', 1)[-1][:24]}"
    )
    validate_curator_submission(
        payload,
        inputs=inputs,
        preparation_manifest=preparation_manifest,
        preparation_manifest_sha256=preparation_manifest_sha256,
    )
    return payload


def validate_curator_submission(
    payload: Mapping[str, Any],
    *,
    inputs: PilotSelectionInputs | None = None,
    preparation_manifest: Mapping[str, Any] | None = None,
    preparation_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    submission = _require_mapping(dict(payload), "curator submission")
    _require_exact_fields(
        submission,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "submission_identity",
            "pilot_version",
            "preparation_package",
            "task",
            "candidate_map",
            "topic_id",
            "u80",
            "curator_id",
            "curator_slot",
            "selected_candidates",
            "timing",
            "external_lookup",
            "independent_submission_acknowledged",
            "submitted_at",
            "notes",
            "original_response",
            "imported_at",
            "provenance",
            "is_fixture",
        },
        "curator submission",
    )
    if submission["schema_version"] != SCHEMA_VERSION:
        raise ValueError("curator submission schema drift。")
    if submission["artifact_type"] != "srtp_pilot_curator_submission":
        raise ValueError("curator submission artifact_type drift。")
    if submission["pilot_version"] != PILOT_VERSION:
        raise ValueError("curator submission Pilot version drift。")
    preparation = _require_mapping(
        submission["preparation_package"], "submission preparation package"
    )
    _require_exact_fields(
        preparation,
        {"artifact_id", "package_identity", "manifest_sha256"},
        "submission preparation package",
    )
    _require_sha256(preparation["manifest_sha256"], "preparation manifest SHA-256")
    task = _require_mapping(submission["task"], "submission task reference")
    _require_exact_fields(
        task,
        {
            "task_id",
            "artifact_id",
            "task_identity",
            "sha256",
            "candidate_roster_identity",
        },
        "task reference",
    )
    candidate_map = _require_mapping(
        submission["candidate_map"], "submission candidate map reference"
    )
    _require_exact_fields(
        candidate_map,
        {"artifact_id", "map_identity", "sha256"},
        "candidate map reference",
    )
    for label, value in (
        ("task SHA-256", task["sha256"]),
        ("candidate map SHA-256", candidate_map["sha256"]),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(value)):
            raise ValueError(f"{label} 非法。")
    _require_text(submission["topic_id"], "submission topic_id")
    submission_u80 = _require_mapping(submission["u80"], "submission U80")
    curator_id = _require_text(submission["curator_id"], "submission curator_id")
    if submission["curator_slot"] not in CURATOR_SLOTS:
        raise ValueError("submission curator_slot 非法。")
    rows = _require_list(
        submission["selected_candidates"], "submission selected candidates"
    )
    if len(rows) != SELECTION_K:
        raise ValueError("curator submission 必须精确包含 8 selections。")
    candidate_ids: list[str] = []
    canonical_ids: list[str] = []
    reasons: dict[str, str] = {}
    for raw in rows:
        row = _require_mapping(raw, "submission selected candidate")
        _require_exact_fields(
            row,
            {"candidate_id", "canonical_entity_id", "selection_reason"},
            "submission selected candidate",
        )
        candidate_id = _require_text(row["candidate_id"], "submission candidate_id")
        canonical_id = _require_text(
            row["canonical_entity_id"], "submission canonical_entity_id"
        )
        reason = _require_text(row["selection_reason"], "submission reason")
        candidate_ids.append(candidate_id)
        canonical_ids.append(canonical_id)
        reasons[candidate_id] = reason
    if len(set(candidate_ids)) != SELECTION_K or len(set(canonical_ids)) != SELECTION_K:
        raise ValueError("curator submission candidate/canonical IDs 不得重复。")
    timing = _validate_human_timing(submission["timing"], "submission timing")
    _require_bool(submission["external_lookup"], False, "submission external_lookup")
    _require_bool(
        submission["independent_submission_acknowledged"],
        True,
        "submission independent acknowledgement",
    )
    submitted_at = _require_datetime(
        submission["submitted_at"], "submission submitted_at"
    )
    imported_at = _require_datetime(submission["imported_at"], "submission imported_at")
    is_fixture = _require_bool(submission["is_fixture"], None, "submission is_fixture")
    original = _require_mapping(submission["original_response"], "original response")
    if (
        original.get("task_id") != task["task_id"]
        or original.get("task_identity") != task["task_identity"]
        or original.get("curator_id") != curator_id
        or original.get("curator_slot") != submission["curator_slot"]
        or original.get("timing") != timing
        or original.get("submitted_at") != submitted_at
        or original.get("is_fixture") != is_fixture
        or original.get("external_lookup") is not False
        or original.get("independent_submission_acknowledged") is not True
    ):
        raise ValueError("curator submission/original response provenance drift。")
    original_rows = _require_list(
        original.get("selected_candidates"), "original selected candidates"
    )
    if original_rows != [
        {"candidate_id": candidate_id, "selection_reason": reasons[candidate_id]}
        for candidate_id in candidate_ids
    ]:
        raise ValueError("curator submission 改写了 original response selections。")
    provenance = _require_mapping(submission["provenance"], "submission provenance")
    _require_exact_fields(
        provenance,
        {"kind", "created_by", "created_at", "git_revision"},
        "submission provenance",
    )
    if provenance["created_at"] != imported_at:
        raise ValueError("submission provenance time drift。")
    _require_git_revision(provenance["git_revision"], "submission git revision")
    expected_identity = deterministic_identity(
        CURATOR_SUBMISSION_IDENTITY_PREFIX,
        _task_identity_payload(submission, "submission_identity"),
    )
    if submission["submission_identity"] != expected_identity:
        raise ValueError("curator submission identity drift。")
    if submission["artifact_id"] != (
        f"srtp_pilot_curator_submission_{expected_identity.rsplit(':', 1)[-1][:24]}"
    ):
        raise ValueError("curator submission artifact_id drift。")
    if inputs is not None:
        topic = topic_config(inputs, submission["topic_id"])
        if submission_u80 != _u80_reference(inputs):
            raise ValueError("curator submission U80 binding drift。")
        allowed = set(inputs.u80_by_topic[submission["topic_id"]])
        if not set(canonical_ids) <= allowed:
            raise ValueError("curator submission 含 U80 外 canonical ID。")
        if (
            task["task_id"]
            != f"pilot_{submission['curator_slot']}_{topic['question_id']}"
        ):
            raise ValueError("curator submission task/topic/question binding drift。")
    if (preparation_manifest is None) != (preparation_manifest_sha256 is None):
        raise ValueError("preparation manifest 与 SHA-256 必须同时提供。")
    if preparation_manifest is not None and preparation_manifest_sha256 is not None:
        expected_preparation = _preparation_package_reference(
            preparation_manifest, preparation_manifest_sha256
        )
        if preparation != expected_preparation:
            raise ValueError("curator submission preparation package binding drift。")
        summary = _manifest_task_summary(
            preparation_manifest,
            curator_slot=submission["curator_slot"],
            task_id=task["task_id"],
        )
        for key, expected in {
            "task_artifact_id": task["artifact_id"],
            "task_identity": task["task_identity"],
            "task_sha256": task["sha256"],
            "candidate_roster_identity": task["candidate_roster_identity"],
            "map_artifact_id": candidate_map["artifact_id"],
            "map_identity": candidate_map["map_identity"],
            "map_sha256": candidate_map["sha256"],
        }.items():
            if summary.get(key) != expected:
                raise ValueError(f"curator submission/manifest closure drift：{key}。")
    return {
        "topic_id": submission["topic_id"],
        "u80": copy.deepcopy(submission["u80"]),
        "curator_id": curator_id,
        "curator_slot": submission["curator_slot"],
        "preparation_package": copy.deepcopy(preparation),
        "canonical_entity_ids": tuple(canonical_ids),
        "is_fixture": is_fixture,
    }


def _submission_selected(submission: Mapping[str, Any]) -> list[str]:
    return [row["canonical_entity_id"] for row in submission["selected_candidates"]]


def build_curator_comparison(
    submission_a: Mapping[str, Any],
    submission_b: Mapping[str, Any],
    *,
    inputs: PilotSelectionInputs,
    preparation_manifest: Mapping[str, Any],
    preparation_manifest_sha256: str,
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    validate_curator_submission(
        submission_a,
        inputs=inputs,
        preparation_manifest=preparation_manifest,
        preparation_manifest_sha256=preparation_manifest_sha256,
    )
    validate_curator_submission(
        submission_b,
        inputs=inputs,
        preparation_manifest=preparation_manifest,
        preparation_manifest_sha256=preparation_manifest_sha256,
    )
    if submission_a["curator_slot"] == submission_b["curator_slot"]:
        raise ValueError("comparison 要求 curator_a 与 curator_b 两个独立 slot。")
    if submission_a["curator_id"] == submission_b["curator_id"]:
        raise ValueError("Dual-Curator 必须由两个不同 curator 完成。")
    if submission_a["is_fixture"] != submission_b["is_fixture"]:
        raise ValueError("禁止混用 fixture 与 real curator submissions。")
    for key in ("topic_id", "u80"):
        if submission_a[key] != submission_b[key]:
            raise ValueError(f"curator submissions {key} 不一致。")
    if submission_a["preparation_package"] != submission_b["preparation_package"]:
        raise ValueError("curator submissions 来自不同 preparation package。")
    selected_a = set(_submission_selected(submission_a))
    selected_b = set(_submission_selected(submission_b))
    if len(selected_a) != SELECTION_K or len(selected_b) != SELECTION_K:
        raise ValueError("每份 curator submission 必须精确包含 8 canonical IDs。")
    intersection = sorted(selected_a & selected_b)
    symmetric = sorted(selected_a ^ selected_b)
    union = selected_a | selected_b
    overlap = len(intersection)
    status = (
        "ready_for_adjudication"
        if overlap >= MINIMUM_CURATOR_OVERLAP
        else "curation_stability_failure"
    )
    if overlap == SELECTION_K:
        status = "ready_without_adjudication"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_curator_comparison",
        "artifact_id": "pending",
        "comparison_identity": "pending",
        "pilot_version": PILOT_VERSION,
        "preparation_package": copy.deepcopy(submission_a["preparation_package"]),
        "topic_id": submission_a["topic_id"],
        "u80": copy.deepcopy(submission_a["u80"]),
        "original_submissions": [
            {
                "curator_slot": submission["curator_slot"],
                "curator_id": submission["curator_id"],
                "artifact_id": submission["artifact_id"],
                "submission_identity": submission["submission_identity"],
                "sha256": payload_sha256(submission),
                "selected_canonical_entity_ids": _submission_selected(submission),
            }
            for submission in sorted(
                (submission_a, submission_b), key=lambda item: item["curator_slot"]
            )
        ],
        "intersection_canonical_entity_ids": intersection,
        "symmetric_difference_canonical_entity_ids": symmetric,
        "overlap_count": overlap,
        "jaccard": overlap / len(union),
        "minimum_overlap_count": MINIMUM_CURATOR_OVERLAP,
        "status": status,
        "failure_action": "fail_closed_do_not_auto_replace_topic"
        if overlap < 4
        else None,
        "created_at": _require_datetime(created_at, "comparison created_at"),
        "provenance": {
            "kind": "deterministic_dual_curator_comparison",
            "created_by": "src.pilot_selection",
            "created_at": created_at,
            "git_revision": _require_git_revision(
                git_revision, "comparison git revision"
            ),
        },
        "is_fixture": bool(submission_a["is_fixture"]),
    }
    identity = deterministic_identity(
        CURATOR_COMPARISON_IDENTITY_PREFIX,
        _task_identity_payload(payload, "comparison_identity"),
    )
    payload["comparison_identity"] = identity
    payload["artifact_id"] = (
        f"srtp_pilot_curator_comparison_{identity.rsplit(':', 1)[-1][:24]}"
    )
    validate_curator_comparison(
        payload,
        inputs=inputs,
        submission_a=submission_a,
        submission_b=submission_b,
        preparation_manifest=preparation_manifest,
        preparation_manifest_sha256=preparation_manifest_sha256,
    )
    return payload


def validate_curator_comparison(
    payload: Mapping[str, Any],
    *,
    inputs: PilotSelectionInputs | None = None,
    submission_a: Mapping[str, Any] | None = None,
    submission_b: Mapping[str, Any] | None = None,
    preparation_manifest: Mapping[str, Any] | None = None,
    preparation_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    comparison = _require_mapping(dict(payload), "curator comparison")
    _require_exact_fields(
        comparison,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "comparison_identity",
            "pilot_version",
            "preparation_package",
            "topic_id",
            "u80",
            "original_submissions",
            "intersection_canonical_entity_ids",
            "symmetric_difference_canonical_entity_ids",
            "overlap_count",
            "jaccard",
            "minimum_overlap_count",
            "status",
            "failure_action",
            "created_at",
            "provenance",
            "is_fixture",
        },
        "curator comparison",
    )
    if comparison["schema_version"] != SCHEMA_VERSION:
        raise ValueError("curator comparison schema drift。")
    if comparison["artifact_type"] != "srtp_pilot_curator_comparison":
        raise ValueError("curator comparison artifact_type drift。")
    if comparison["pilot_version"] != PILOT_VERSION:
        raise ValueError("curator comparison Pilot version drift。")
    preparation = _require_mapping(
        comparison["preparation_package"], "comparison preparation package"
    )
    topic_id = _require_text(comparison["topic_id"], "comparison topic_id")
    originals = _require_list(
        comparison["original_submissions"], "comparison original submissions"
    )
    if len(originals) != 2:
        raise ValueError("comparison 必须保留两份 original submissions。")
    selected_sets = []
    slots = set()
    curator_ids = set()
    for raw in originals:
        row = _require_mapping(raw, "comparison original submission")
        _require_exact_fields(
            row,
            {
                "curator_slot",
                "curator_id",
                "artifact_id",
                "submission_identity",
                "sha256",
                "selected_canonical_entity_ids",
            },
            "comparison original submission",
        )
        slots.add(_require_text(row["curator_slot"], "original curator_slot"))
        curator_ids.add(_require_text(row["curator_id"], "original curator_id"))
        if not re.fullmatch(r"[0-9a-f]{64}", str(row["sha256"])):
            raise ValueError("original submission SHA-256 非法。")
        selected_sets.append(
            set(
                _require_string_list(
                    row["selected_canonical_entity_ids"],
                    "original selected canonical IDs",
                    count=SELECTION_K,
                )
            )
        )
    if slots != set(CURATOR_SLOTS) or len(curator_ids) != 2:
        raise ValueError("comparison 要求两个不同 curator/slot。")
    expected_intersection = sorted(selected_sets[0] & selected_sets[1])
    expected_symmetric = sorted(selected_sets[0] ^ selected_sets[1])
    intersection = _require_string_list(
        comparison["intersection_canonical_entity_ids"], "comparison intersection"
    )
    symmetric = _require_string_list(
        comparison["symmetric_difference_canonical_entity_ids"],
        "comparison symmetric difference",
    )
    if intersection != expected_intersection or symmetric != expected_symmetric:
        raise ValueError("comparison set reconstruction drift。")
    overlap = len(intersection)
    if comparison["overlap_count"] != overlap:
        raise ValueError("comparison overlap count drift。")
    union_count = len(selected_sets[0] | selected_sets[1])
    if not math.isclose(
        float(comparison["jaccard"]), overlap / union_count, abs_tol=1e-12
    ):
        raise ValueError("comparison Jaccard drift。")
    if comparison["minimum_overlap_count"] != MINIMUM_CURATOR_OVERLAP:
        raise ValueError("comparison minimum overlap drift。")
    expected_status = (
        "curation_stability_failure"
        if overlap < MINIMUM_CURATOR_OVERLAP
        else "ready_without_adjudication"
        if overlap == SELECTION_K
        else "ready_for_adjudication"
    )
    if comparison["status"] != expected_status:
        raise ValueError("comparison status drift。")
    expected_action = (
        "fail_closed_do_not_auto_replace_topic"
        if overlap < MINIMUM_CURATOR_OVERLAP
        else None
    )
    if comparison["failure_action"] != expected_action:
        raise ValueError("comparison failure action drift。")
    _require_bool(comparison["is_fixture"], None, "comparison is_fixture")
    created_at = _require_datetime(comparison["created_at"], "comparison created_at")
    provenance = _require_mapping(comparison["provenance"], "comparison provenance")
    if provenance.get("created_at") != created_at:
        raise ValueError("comparison provenance time drift。")
    _require_git_revision(provenance.get("git_revision"), "comparison git revision")
    if inputs is not None:
        topic_config(inputs, topic_id)
        if comparison["u80"] != _u80_reference(inputs):
            raise ValueError("comparison U80 binding drift。")
        allowed = set(inputs.u80_by_topic[topic_id])
        if any(not selected <= allowed for selected in selected_sets):
            raise ValueError("comparison 含 U80 外 canonical ID。")
    if (submission_a is None) != (submission_b is None):
        raise ValueError("comparison validation 必须同时提供 A/B submissions。")
    if submission_a is not None and submission_b is not None:
        supplied = sorted(
            (submission_a, submission_b), key=lambda item: item["curator_slot"]
        )
        expected_originals = [
            {
                "curator_slot": submission["curator_slot"],
                "curator_id": submission["curator_id"],
                "artifact_id": submission["artifact_id"],
                "submission_identity": submission["submission_identity"],
                "sha256": payload_sha256(submission),
                "selected_canonical_entity_ids": _submission_selected(submission),
            }
            for submission in supplied
        ]
        if originals != expected_originals:
            raise ValueError("comparison/A+B frozen submission hash closure drift。")
        if any(
            submission["preparation_package"] != preparation for submission in supplied
        ):
            raise ValueError("comparison/A+B preparation package closure drift。")
        if inputs is not None:
            for submission in supplied:
                validate_curator_submission(
                    submission,
                    inputs=inputs,
                    preparation_manifest=preparation_manifest,
                    preparation_manifest_sha256=preparation_manifest_sha256,
                )
    if (preparation_manifest is None) != (preparation_manifest_sha256 is None):
        raise ValueError("comparison preparation manifest/SHA 必须同时提供。")
    if preparation_manifest is not None and preparation_manifest_sha256 is not None:
        if preparation != _preparation_package_reference(
            preparation_manifest, preparation_manifest_sha256
        ):
            raise ValueError("comparison preparation package identity/hash drift。")
    expected_identity = deterministic_identity(
        CURATOR_COMPARISON_IDENTITY_PREFIX,
        _task_identity_payload(comparison, "comparison_identity"),
    )
    if comparison["comparison_identity"] != expected_identity:
        raise ValueError("curator comparison identity drift。")
    if comparison["artifact_id"] != (
        f"srtp_pilot_curator_comparison_{expected_identity.rsplit(':', 1)[-1][:24]}"
    ):
        raise ValueError("curator comparison artifact_id drift。")
    return {
        "topic_id": topic_id,
        "overlap_count": overlap,
        "status": expected_status,
        "is_fixture": comparison["is_fixture"],
    }


def _canonical_to_opaque(mapping: Mapping[str, Any]) -> dict[str, str]:
    return {
        row["canonical_entity_id"]: row["candidate_id"]
        for row in mapping["candidate_map"]
    }


def build_adjudication_task(
    comparison: Mapping[str, Any],
    *,
    submission_a: Mapping[str, Any],
    submission_b: Mapping[str, Any],
    source_task: Mapping[str, Any],
    mapping: Mapping[str, Any],
    inputs: PilotSelectionInputs,
    preparation_manifest: Mapping[str, Any],
    preparation_manifest_sha256: str,
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    validate_curator_comparison(
        comparison,
        inputs=inputs,
        submission_a=submission_a,
        submission_b=submission_b,
        preparation_manifest=preparation_manifest,
        preparation_manifest_sha256=preparation_manifest_sha256,
    )
    if comparison.get("status") == "curation_stability_failure":
        raise ValueError(
            "curator overlap < 4/8；curation stability failure，fail closed。"
        )
    if comparison.get("status") != "ready_for_adjudication":
        raise ValueError("当前 comparison 不需要或不能生成 adjudication task。")
    topic_id = comparison["topic_id"]
    if source_task.get("topic", {}).get("topic_id") != topic_id:
        raise ValueError("adjudication source task Topic drift。")
    validate_curator_import_chain(
        manifest=preparation_manifest,
        manifest_sha256=preparation_manifest_sha256,
        task=source_task,
        mapping=mapping,
        inputs=inputs,
        expected_curator_slot=source_task.get("curator_slot"),
    )
    canonical_to_opaque = _canonical_to_opaque(mapping)
    symmetric = comparison["symmetric_difference_canonical_entity_ids"]
    candidates = []
    for entity_id in symmetric:
        candidate_id = canonical_to_opaque.get(entity_id)
        if candidate_id is None:
            raise ValueError("adjudication symmetric difference 缺少 opaque mapping。")
        item = inputs.view_by_topic_entity[(topic_id, entity_id)]
        candidates.append(
            {
                "candidate_id": candidate_id,
                "title": item["title"],
                "abstract": item["abstract"],
            }
        )
    candidates.sort(key=lambda row: row["candidate_id"])
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_adjudication_task",
        "artifact_id": "pending",
        "task_identity": "pending",
        "pilot_version": PILOT_VERSION,
        "topic_id": topic_id,
        "u80": copy.deepcopy(comparison["u80"]),
        "preparation_package": copy.deepcopy(comparison["preparation_package"]),
        "comparison": {
            "artifact_id": comparison["artifact_id"],
            "comparison_identity": comparison["comparison_identity"],
            "sha256": payload_sha256(comparison),
        },
        "locked_intersection_count": comparison["overlap_count"],
        "adjudication_roster_identity": deterministic_identity(
            "srtp-pilot-adjudication-roster",
            {
                "comparison_identity": comparison["comparison_identity"],
                "candidate_scope": "symmetric_difference_only",
                "candidates": candidates,
            },
        ),
        "candidate_scope": "symmetric_difference_only",
        "required_additional_count": SELECTION_K - comparison["overlap_count"],
        "candidates": candidates,
        "instructions": "Select only the required additions from this symmetric-difference roster; do not reopen the full U80.",
        "blindness": {
            "curator_side_membership_hidden": True,
            "bm25_output_hidden": True,
            "authors_hidden": True,
            "venue_hidden": True,
        },
        "created_at": _require_datetime(created_at, "adjudication task created_at"),
        "provenance": {
            "kind": "restricted_symmetric_difference_adjudication_task",
            "created_by": "src.pilot_selection",
            "created_at": created_at,
            "git_revision": _require_git_revision(
                git_revision, "adjudication task git revision"
            ),
        },
        "is_fixture": comparison["is_fixture"],
    }
    identity = deterministic_identity(
        ADJUDICATION_TASK_IDENTITY_PREFIX,
        _task_identity_payload(payload, "task_identity"),
    )
    payload["task_identity"] = identity
    payload["artifact_id"] = (
        f"srtp_pilot_adjudication_task_{identity.rsplit(':', 1)[-1][:24]}"
    )
    return payload


def build_blank_adjudication_response(task: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_adjudication_response_form",
        "status": "blank_template",
        "task_identity": task["task_identity"],
        "adjudicator_id": "",
        "selected_candidates": [
            {"candidate_id": "", "selection_reason": ""}
            for _ in range(task["required_additional_count"])
        ],
        "timing": {"started_at": "", "completed_at": "", "elapsed_minutes": None},
        "external_lookup": False,
        "submitted_at": "",
        "notes": "",
        "is_fixture": task["is_fixture"],
    }


def validate_adjudication_task(
    task: Mapping[str, Any],
    *,
    comparison: Mapping[str, Any],
    submission_a: Mapping[str, Any],
    submission_b: Mapping[str, Any],
    source_task: Mapping[str, Any],
    mapping: Mapping[str, Any],
    inputs: PilotSelectionInputs,
    preparation_manifest: Mapping[str, Any],
    preparation_manifest_sha256: str,
) -> dict[str, Any]:
    artifact = _require_mapping(dict(task), "adjudication task")
    provenance = _require_mapping(
        artifact.get("provenance"), "adjudication task provenance"
    )
    expected = build_adjudication_task(
        comparison,
        submission_a=submission_a,
        submission_b=submission_b,
        source_task=source_task,
        mapping=mapping,
        inputs=inputs,
        preparation_manifest=preparation_manifest,
        preparation_manifest_sha256=preparation_manifest_sha256,
        created_at=artifact.get("created_at"),
        git_revision=provenance.get("git_revision"),
    )
    if artifact != expected:
        raise ValueError(
            "adjudication task/comparison/symmetric-difference reconstruction drift。"
        )
    return {
        "topic_id": artifact["topic_id"],
        "required_additional_count": artifact["required_additional_count"],
        "adjudication_roster_identity": artifact["adjudication_roster_identity"],
        "is_fixture": artifact["is_fixture"],
    }


def import_adjudication_submission(
    form: Mapping[str, Any],
    *,
    task: Mapping[str, Any],
    comparison: Mapping[str, Any],
    submission_a: Mapping[str, Any],
    submission_b: Mapping[str, Any],
    source_task: Mapping[str, Any],
    mapping: Mapping[str, Any],
    inputs: PilotSelectionInputs,
    preparation_manifest: Mapping[str, Any],
    preparation_manifest_sha256: str,
    imported_at: str,
    git_revision: str,
) -> dict[str, Any]:
    validate_adjudication_task(
        task,
        comparison=comparison,
        submission_a=submission_a,
        submission_b=submission_b,
        source_task=source_task,
        mapping=mapping,
        inputs=inputs,
        preparation_manifest=preparation_manifest,
        preparation_manifest_sha256=preparation_manifest_sha256,
    )
    response = _require_mapping(dict(form), "adjudication response")
    _require_exact_fields(
        response,
        {
            "schema_version",
            "artifact_type",
            "status",
            "task_identity",
            "adjudicator_id",
            "selected_candidates",
            "timing",
            "external_lookup",
            "submitted_at",
            "notes",
            "is_fixture",
        },
        "adjudication response",
    )
    if response["schema_version"] != SCHEMA_VERSION:
        raise ValueError("adjudication response schema drift。")
    if response.get("artifact_type") != "srtp_pilot_adjudication_response_form":
        raise ValueError("adjudication response artifact_type drift。")
    if (
        response.get("status") != "completed"
        or response.get("task_identity") != task["task_identity"]
    ):
        raise ValueError("adjudication response status/task binding drift。")
    if response["is_fixture"] != task["is_fixture"]:
        raise ValueError("adjudication response fixture status drift。")
    adjudicator_id = _require_text(response.get("adjudicator_id"), "adjudicator_id")
    _require_bool(response.get("external_lookup"), False, "adjudicator external_lookup")
    submitted_at = _require_datetime(
        response.get("submitted_at"), "adjudication submitted_at"
    )
    timing = _validate_human_timing(response.get("timing"), "adjudication timing")
    rows = _require_list(response.get("selected_candidates"), "adjudication selections")
    required = task["required_additional_count"]
    if len(rows) != required:
        raise ValueError(f"adjudicator 必须精确补足 {required} 篇。")
    allowed = {row["candidate_id"] for row in task["candidates"]}
    map_index = _candidate_map_index(mapping)
    candidate_ids = []
    normalized = []
    for raw in rows:
        row = _require_mapping(raw, "adjudication selected candidate")
        _require_exact_fields(
            row, {"candidate_id", "selection_reason"}, "adjudication selection"
        )
        candidate_id = _require_text(row["candidate_id"], "adjudication candidate_id")
        if candidate_id not in allowed:
            raise ValueError("adjudicator 只能从 symmetric difference task 选择。")
        reason = _require_text(row["selection_reason"], "adjudication reason")
        if len(reason) > 500:
            raise ValueError("adjudication reason 应保持简短（<=500 chars）。")
        candidate_ids.append(candidate_id)
        normalized.append(
            {
                "candidate_id": candidate_id,
                "canonical_entity_id": map_index[candidate_id]["canonical_entity_id"],
                "selection_reason": reason,
            }
        )
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("adjudication selections 不得重复。")
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_adjudication_submission",
        "artifact_id": "pending",
        "submission_identity": "pending",
        "pilot_version": PILOT_VERSION,
        "preparation_package": copy.deepcopy(comparison["preparation_package"]),
        "comparison": {
            "artifact_id": comparison["artifact_id"],
            "comparison_identity": comparison["comparison_identity"],
            "sha256": payload_sha256(comparison),
        },
        "original_submissions": copy.deepcopy(comparison["original_submissions"]),
        "task": {
            "artifact_id": task["artifact_id"],
            "task_identity": task["task_identity"],
            "sha256": payload_sha256(task),
            "adjudication_roster_identity": task["adjudication_roster_identity"],
        },
        "candidate_map": {
            "artifact_id": mapping["artifact_id"],
            "map_identity": mapping["map_identity"],
            "sha256": payload_sha256(mapping),
        },
        "adjudicator_id": adjudicator_id,
        "selected_candidates": normalized,
        "timing": timing,
        "external_lookup": False,
        "submitted_at": submitted_at,
        "notes": str(response.get("notes") or ""),
        "original_response": copy.deepcopy(response),
        "imported_at": _require_datetime(imported_at, "adjudication imported_at"),
        "provenance": {
            "kind": "immutable_restricted_adjudication_import",
            "created_by": "src.pilot_selection",
            "created_at": imported_at,
            "git_revision": _require_git_revision(
                git_revision, "adjudication git revision"
            ),
        },
        "is_fixture": task["is_fixture"],
    }
    identity = deterministic_identity(
        ADJUDICATION_SUBMISSION_IDENTITY_PREFIX,
        _task_identity_payload(payload, "submission_identity"),
    )
    payload["submission_identity"] = identity
    payload["artifact_id"] = (
        f"srtp_pilot_adjudication_submission_{identity.rsplit(':', 1)[-1][:24]}"
    )
    validate_adjudication_submission(
        payload,
        task=task,
        comparison=comparison,
        submission_a=submission_a,
        submission_b=submission_b,
        source_task=source_task,
        mapping=mapping,
        inputs=inputs,
        preparation_manifest=preparation_manifest,
        preparation_manifest_sha256=preparation_manifest_sha256,
    )
    return payload


def validate_adjudication_submission(
    payload: Mapping[str, Any],
    *,
    task: Mapping[str, Any],
    comparison: Mapping[str, Any],
    submission_a: Mapping[str, Any],
    submission_b: Mapping[str, Any],
    source_task: Mapping[str, Any],
    mapping: Mapping[str, Any],
    inputs: PilotSelectionInputs,
    preparation_manifest: Mapping[str, Any],
    preparation_manifest_sha256: str,
) -> dict[str, Any]:
    validate_adjudication_task(
        task,
        comparison=comparison,
        submission_a=submission_a,
        submission_b=submission_b,
        source_task=source_task,
        mapping=mapping,
        inputs=inputs,
        preparation_manifest=preparation_manifest,
        preparation_manifest_sha256=preparation_manifest_sha256,
    )
    submission = _require_mapping(dict(payload), "adjudication submission")
    _require_exact_fields(
        submission,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "submission_identity",
            "pilot_version",
            "preparation_package",
            "comparison",
            "original_submissions",
            "task",
            "candidate_map",
            "adjudicator_id",
            "selected_candidates",
            "timing",
            "external_lookup",
            "submitted_at",
            "notes",
            "original_response",
            "imported_at",
            "provenance",
            "is_fixture",
        },
        "adjudication submission",
    )
    if (
        submission["schema_version"] != SCHEMA_VERSION
        or submission["artifact_type"] != "srtp_pilot_adjudication_submission"
    ):
        raise ValueError("adjudication submission header drift。")
    if submission["pilot_version"] != PILOT_VERSION:
        raise ValueError("adjudication submission Pilot version drift。")
    if submission["preparation_package"] != comparison["preparation_package"]:
        raise ValueError("adjudication/preparation package closure drift。")
    if submission["comparison"] != {
        "artifact_id": comparison["artifact_id"],
        "comparison_identity": comparison["comparison_identity"],
        "sha256": payload_sha256(comparison),
    }:
        raise ValueError("adjudication/comparison hash closure drift。")
    if submission["original_submissions"] != comparison["original_submissions"]:
        raise ValueError("adjudication/A+B original submission closure drift。")
    if submission["task"] != {
        "artifact_id": task["artifact_id"],
        "task_identity": task["task_identity"],
        "sha256": payload_sha256(task),
        "adjudication_roster_identity": task["adjudication_roster_identity"],
    }:
        raise ValueError("adjudication submission/task roster closure drift。")
    if submission["candidate_map"] != {
        "artifact_id": mapping["artifact_id"],
        "map_identity": mapping["map_identity"],
        "sha256": payload_sha256(mapping),
    }:
        raise ValueError("adjudication submission/mapping closure drift。")
    rows = _require_list(
        submission["selected_candidates"], "adjudication selected candidates"
    )
    if len(rows) != task["required_additional_count"]:
        raise ValueError("adjudication selected count drift。")
    allowed = {row["candidate_id"] for row in task["candidates"]}
    map_index = _candidate_map_index(mapping)
    candidate_ids: list[str] = []
    canonical_ids: list[str] = []
    for raw in rows:
        row = _require_mapping(raw, "adjudication selected row")
        _require_exact_fields(
            row,
            {"candidate_id", "canonical_entity_id", "selection_reason"},
            "adjudication selected row",
        )
        candidate_id = _require_text(
            row.get("candidate_id"), "adjudication candidate_id"
        )
        canonical_id = _require_text(
            row.get("canonical_entity_id"), "adjudication canonical_entity_id"
        )
        _require_text(row.get("selection_reason"), "adjudication selection reason")
        if (
            candidate_id not in allowed
            or map_index.get(candidate_id, {}).get("canonical_entity_id")
            != canonical_id
        ):
            raise ValueError("adjudication opaque→canonical mapping drift。")
        candidate_ids.append(candidate_id)
        canonical_ids.append(canonical_id)
    if len(candidate_ids) != len(set(candidate_ids)) or len(canonical_ids) != len(
        set(canonical_ids)
    ):
        raise ValueError("adjudication selected candidate/canonical IDs 重复。")
    if not set(canonical_ids) <= set(
        comparison["symmetric_difference_canonical_entity_ids"]
    ):
        raise ValueError("adjudication selection 超出 symmetric difference。")
    _require_bool(submission["external_lookup"], False, "adjudication external_lookup")
    _validate_human_timing(submission["timing"], "adjudication timing")
    _require_datetime(submission["submitted_at"], "adjudication submitted_at")
    _require_datetime(submission["imported_at"], "adjudication imported_at")
    if submission["is_fixture"] != task["is_fixture"]:
        raise ValueError("adjudication fixture status drift。")
    original = _require_mapping(
        submission["original_response"], "original adjudication response"
    )
    _require_exact_fields(
        original,
        {
            "schema_version",
            "artifact_type",
            "status",
            "task_identity",
            "adjudicator_id",
            "selected_candidates",
            "timing",
            "external_lookup",
            "submitted_at",
            "notes",
            "is_fixture",
        },
        "original adjudication response",
    )
    expected_original_rows = [
        {
            "candidate_id": row["candidate_id"],
            "selection_reason": row["selection_reason"],
        }
        for row in rows
    ]
    if (
        original["schema_version"] != SCHEMA_VERSION
        or original["artifact_type"] != "srtp_pilot_adjudication_response_form"
        or original["status"] != "completed"
        or original["task_identity"] != task["task_identity"]
        or original["adjudicator_id"] != submission["adjudicator_id"]
        or original["selected_candidates"] != expected_original_rows
        or original["timing"] != submission["timing"]
        or original["external_lookup"] is not False
        or original["submitted_at"] != submission["submitted_at"]
        or str(original["notes"] or "") != submission["notes"]
        or original["is_fixture"] != submission["is_fixture"]
    ):
        raise ValueError("adjudication submission/original response closure drift。")
    provenance = _require_mapping(
        submission["provenance"], "adjudication submission provenance"
    )
    _require_exact_fields(
        provenance,
        {"kind", "created_by", "created_at", "git_revision"},
        "adjudication submission provenance",
    )
    if (
        provenance["kind"] != "immutable_restricted_adjudication_import"
        or provenance["created_by"] != "src.pilot_selection"
        or provenance["created_at"] != submission["imported_at"]
    ):
        raise ValueError("adjudication submission provenance drift。")
    _require_git_revision(
        provenance["git_revision"], "adjudication submission git revision"
    )
    expected_identity = deterministic_identity(
        ADJUDICATION_SUBMISSION_IDENTITY_PREFIX,
        _task_identity_payload(submission, "submission_identity"),
    )
    if submission["submission_identity"] != expected_identity:
        raise ValueError("adjudication submission identity drift。")
    if submission["artifact_id"] != (
        f"srtp_pilot_adjudication_submission_{expected_identity.rsplit(':', 1)[-1][:24]}"
    ):
        raise ValueError("adjudication submission artifact_id drift。")
    return {
        "canonical_entity_ids": tuple(canonical_ids),
        "is_fixture": submission["is_fixture"],
    }


def build_final_human_selection(
    comparison: Mapping[str, Any],
    *,
    inputs: PilotSelectionInputs,
    submission_a: Mapping[str, Any],
    submission_b: Mapping[str, Any],
    preparation_manifest: Mapping[str, Any],
    preparation_manifest_sha256: str,
    adjudication_task: Mapping[str, Any] | None,
    adjudication_source_task: Mapping[str, Any] | None,
    adjudication_mapping: Mapping[str, Any] | None,
    adjudication: Mapping[str, Any] | None,
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    validate_curator_comparison(
        comparison,
        inputs=inputs,
        submission_a=submission_a,
        submission_b=submission_b,
        preparation_manifest=preparation_manifest,
        preparation_manifest_sha256=preparation_manifest_sha256,
    )
    if comparison.get("status") == "curation_stability_failure":
        raise ValueError("curator overlap < 4/8；不得生成 final human selection。")
    intersection = list(comparison["intersection_canonical_entity_ids"])
    symmetric = list(comparison["symmetric_difference_canonical_entity_ids"])
    required = SELECTION_K - len(intersection)
    if required:
        if any(
            value is None
            for value in (
                adjudication_task,
                adjudication_source_task,
                adjudication_mapping,
                adjudication,
            )
        ):
            raise ValueError("final human selection 缺少 required adjudication。")
        assert adjudication_task is not None
        assert adjudication_source_task is not None
        assert adjudication_mapping is not None
        assert adjudication is not None
        validate_adjudication_submission(
            adjudication,
            task=adjudication_task,
            comparison=comparison,
            submission_a=submission_a,
            submission_b=submission_b,
            source_task=adjudication_source_task,
            mapping=adjudication_mapping,
            inputs=inputs,
            preparation_manifest=preparation_manifest,
            preparation_manifest_sha256=preparation_manifest_sha256,
        )
        additions = [
            row["canonical_entity_id"] for row in adjudication["selected_candidates"]
        ]
        if len(additions) != required or not set(additions) <= set(symmetric):
            raise ValueError("final adjudication additions 非法。")
        adjudication_details = {
            "required": True,
            "artifact_id": adjudication["artifact_id"],
            "sha256": payload_sha256(adjudication),
            "adjudicator_id": adjudication["adjudicator_id"],
            "selected_from_symmetric_difference_canonical_entity_ids": additions,
        }
    else:
        if any(
            value is not None
            for value in (
                adjudication_task,
                adjudication_source_task,
                adjudication_mapping,
                adjudication,
            )
        ):
            raise ValueError("8/8 intersection 不得附加 adjudication。")
        additions = []
        adjudication_details = {
            "required": False,
            "artifact_id": None,
            "sha256": None,
            "adjudicator_id": None,
            "selected_from_symmetric_difference_canonical_entity_ids": [],
        }
    selected = sorted(intersection + additions)
    if comparison.get("is_fixture"):
        return build_selection_artifact(
            inputs=inputs,
            topic_id=comparison["topic_id"],
            selection_method={
                "method_id": FIXTURE_METHOD_ID,
                "family": "testing_only",
                "config_identity": "fixture",
            },
            selected_canonical_entity_ids=selected,
            method_specific_provenance={
                "fixture_strategy": "mock_dual_curator_plumbing_workflow"
            },
            created_at=created_at,
            git_revision=git_revision,
            is_fixture=True,
            purpose="plumbing_only",
        )
    originals = comparison["original_submissions"]
    return build_selection_artifact(
        inputs=inputs,
        topic_id=comparison["topic_id"],
        selection_method={
            "method_id": HUMAN_METHOD_ID,
            "family": "human_dual_curator",
            "config_identity": inputs.config["dual_curator"]["config_identity"],
        },
        selected_canonical_entity_ids=selected,
        method_specific_provenance={
            "comparison_artifact_id": comparison["artifact_id"],
            "comparison_sha256": payload_sha256(comparison),
            "curator_submission_artifact_ids": [
                row["artifact_id"] for row in originals
            ],
            "curator_submission_sha256s": [row["sha256"] for row in originals],
            "intersection_canonical_entity_ids": intersection,
            "symmetric_difference_canonical_entity_ids": symmetric,
            "overlap_count": comparison["overlap_count"],
            "jaccard": comparison["jaccard"],
            "adjudication": adjudication_details,
            "external_lookup": False,
            "independent_submissions": True,
        },
        created_at=created_at,
        git_revision=git_revision,
        is_fixture=False,
        purpose="formal_dual_curator_condition",
    )


def capture_git_state(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {
        "git_revision": _require_git_revision(revision, "Git revision"),
        "git_worktree_clean": not bool(status.strip()),
    }


def validate_external_output_path(
    output_path: str | Path,
    *,
    project_root: str | Path,
    label: str = "human workflow output",
) -> Path:
    """Require Human-workflow outputs to live outside the trusted repository."""

    root = Path(project_root).resolve()
    output = Path(output_path).resolve()
    try:
        output.relative_to(root)
    except ValueError:
        return output
    raise ValueError(f"{label} 必须位于 repository root 之外。")


def assemble_curator_preparation_payloads(
    inputs: PilotSelectionInputs,
    *,
    created_at: str,
    git_revision: str,
    is_fixture: bool = False,
) -> tuple[dict[str, dict[str, Any] | str], dict[str, Any]]:
    payloads: dict[str, dict[str, Any] | str] = {
        "CURATOR_INSTRUCTIONS.md": render_curator_instructions_markdown()
    }
    task_summaries = []
    for curator_slot in CURATOR_SLOTS:
        for topic_id in sorted(inputs.u80_by_topic):
            task, mapping = build_curator_task_and_map(
                inputs,
                topic_id=topic_id,
                curator_slot=curator_slot,
                created_at=created_at,
                git_revision=git_revision,
                is_fixture=is_fixture,
            )
            task_name = f"curator_tasks/{curator_slot}/{topic_id}.json"
            readable_name = f"curator_tasks/{curator_slot}/{topic_id}.md"
            map_name = f"coordinator/{curator_slot}/{topic_id}_candidate_map.json"
            response_name = f"responses/{curator_slot}/{topic_id}_response.json"
            payloads[task_name] = task
            payloads[readable_name] = render_curator_task_markdown(task)
            payloads[map_name] = mapping
            payloads[response_name] = build_blank_curator_response(task)
            task_summaries.append(
                {
                    "curator_slot": curator_slot,
                    "topic_id": topic_id,
                    "question_id": task["topic"]["question_id"],
                    "task_path": task_name,
                    "readable_task_path": readable_name,
                    "response_template_path": response_name,
                    "coordinator_map_path": map_name,
                    "task_artifact_id": task["artifact_id"],
                    "task_identity": task["task_identity"],
                    "task_sha256": payload_sha256(task),
                    "candidate_roster_identity": task["candidate_roster_identity"],
                    "map_artifact_id": mapping["artifact_id"],
                    "map_identity": mapping["map_identity"],
                    "map_sha256": payload_sha256(mapping),
                }
            )
    file_hashes = {
        name: (
            payload_sha256(payload)
            if isinstance(payload, dict)
            else hashlib.sha256(payload.encode("utf-8")).hexdigest()
        )
        for name, payload in payloads.items()
    }
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_curator_preparation_manifest",
        "artifact_id": "pending",
        "package_identity": "pending",
        "pilot_version": PILOT_VERSION,
        "status": "fixture_plumbing" if is_fixture else "prepared_not_started",
        "is_fixture": is_fixture,
        "purpose": (
            "plumbing_only"
            if is_fixture
            else "prepare_real_independent_human_selection_without_prefilling_answers"
        ),
        "config": {
            "artifact_id": inputs.config["artifact_id"],
            "config_identity": inputs.config["config_identity"],
            "sha256": sha256_file(inputs.config_path),
        },
        "u80": _u80_reference(inputs),
        "task_count": len(task_summaries),
        "curator_count": len(CURATOR_SLOTS),
        "topic_count": len(inputs.u80_by_topic),
        "tasks": task_summaries,
        "files": file_hashes,
        "bm25_execution_status": "deferred_until_dual_curator_final_selection_freeze",
        "human_selection_status": "not_started",
        "created_at": _require_datetime(created_at, "package created_at"),
        "provenance": {
            "kind": "deterministic_curator_task_preparation",
            "created_by": "src.pilot_selection",
            "created_at": created_at,
            "git_revision": _require_git_revision(git_revision, "package git revision"),
        },
    }
    identity = deterministic_identity(
        CURATOR_PACKAGE_IDENTITY_PREFIX,
        _task_identity_payload(manifest, "package_identity"),
    )
    manifest["package_identity"] = identity
    manifest["artifact_id"] = (
        f"srtp_pilot_curator_preparation_{identity.rsplit(':', 1)[-1][:24]}"
    )
    return payloads, manifest


def _validate_replaceable_not_started_package(output: Path) -> None:
    manifest_path = output / "manifest.json"
    manifest = load_json_object(
        manifest_path, label="existing curator package manifest"
    )
    if (
        manifest.get("artifact_type") != "srtp_pilot_curator_preparation_manifest"
        or manifest.get("status") != "prepared_not_started"
        or manifest.get("human_selection_status") != "not_started"
        or manifest.get("is_fixture") is not False
    ):
        raise ValueError("existing package 不是可安全替换的 not-started preparation。")
    files = _require_mapping(manifest.get("files"), "existing package files")
    actual = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    if actual != set(files) | {"manifest.json"}:
        raise ValueError("existing not-started package file closure drift；拒绝替换。")
    for relative, expected_hash in files.items():
        if sha256_file(output / relative) != expected_hash:
            raise ValueError(f"existing package hash drift；拒绝替换：{relative}。")
        if relative.startswith("responses/"):
            response = load_json_object(output / relative, label=relative)
            if response.get("status") != "blank_template":
                raise ValueError("existing package 已含非空 human response；拒绝替换。")


def build_curator_preparation_package(
    *,
    config_path: str | Path,
    output_dir: str | Path,
    project_root: str | Path,
    replace_not_started: bool = False,
) -> Path:
    root = Path(project_root).resolve()
    git_state = capture_git_state(root)
    if not git_state["git_worktree_clean"]:
        raise ValueError("curator preparation package 必须从 clean worktree 生成。")
    inputs = load_pilot_selection_inputs(config_path, project_root=root)
    output = Path(output_dir)
    if not output.is_absolute():
        output = (root / output).resolve()
    replacing = output.exists() and output.is_dir() and any(output.iterdir())
    if replacing:
        if not replace_not_started:
            raise ValueError("curator preparation output 必须不存在或为空。")
        try:
            relative_output = output.relative_to(root)
        except ValueError as error:
            raise ValueError(
                "replace-not-started 只允许仓库内明确 package path。"
            ) from error
        if not relative_output.parts or relative_output == Path("."):
            raise ValueError("replace-not-started 禁止以 repository root 为目标。")
        _validate_replaceable_not_started_package(output)
    elif output.exists() and not output.is_dir():
        raise ValueError("curator preparation output 必须是目录。")
    payloads, manifest = assemble_curator_preparation_payloads(
        inputs,
        created_at=inputs.config["created_at"],
        git_revision=git_state["git_revision"],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.publish_", dir=output.parent)
    )
    try:
        for relative, payload in payloads.items():
            if isinstance(payload, dict):
                write_json(staging / relative, payload)
            else:
                path = staging / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(payload, encoding="utf-8", newline="\n")
        write_json(staging / "manifest.json", manifest)
        validate_curator_preparation_package(
            staging, config_path=inputs.config_path, project_root=root
        )
        if replacing:
            backup = output.parent / f".{output.name}.previous_not_started"
            if backup.exists():
                raise ValueError("stale preparation replacement backup 已存在。")
            output.replace(backup)
            try:
                staging.replace(output)
            except Exception:
                if not output.exists() and backup.exists():
                    backup.replace(output)
                raise
            else:
                shutil.rmtree(backup)
        else:
            if output.exists():
                output.rmdir()
            staging.replace(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return output / "manifest.json"


def validate_curator_preparation_package(
    package_dir: str | Path, *, config_path: str | Path, project_root: str | Path
) -> dict[str, Any]:
    package = Path(package_dir).resolve()
    if not package.is_dir():
        raise ValueError("curator preparation package 不存在。")
    inputs = load_pilot_selection_inputs(config_path, project_root=project_root)
    manifest = load_json_object(
        package / "manifest.json", label="curator package manifest"
    )
    is_fixture = _require_bool(
        manifest.get("is_fixture"), None, "curator package is_fixture"
    )
    expected_status = "fixture_plumbing" if is_fixture else "prepared_not_started"
    if manifest.get("status") != expected_status:
        raise ValueError(f"curator package status 必须是 {expected_status}。")
    provenance = _require_mapping(
        manifest.get("provenance"), "curator package provenance"
    )
    expected_payloads, expected_manifest = assemble_curator_preparation_payloads(
        inputs,
        created_at=manifest.get("created_at"),
        git_revision=provenance.get("git_revision"),
        is_fixture=is_fixture,
    )
    manifest_files = _require_mapping(manifest.get("files"), "curator manifest files")
    expected_files = set(expected_payloads) | {"manifest.json"}
    actual_files = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        raise ValueError(
            f"curator package file closure drift：missing={sorted(expected_files - actual_files)}, "
            f"extra={sorted(actual_files - expected_files)}。"
        )
    for relative, expected in expected_payloads.items():
        path = package / relative
        if sha256_file(path) != manifest_files.get(relative):
            raise ValueError(f"curator package hash drift：{relative}。")
        actual = (
            load_json_object(path, label=relative)
            if isinstance(expected, dict)
            else path.read_text(encoding="utf-8")
        )
        if actual != expected:
            raise ValueError(
                f"curator package semantic reconstruction drift：{relative}。"
            )
    if manifest != expected_manifest:
        raise ValueError("curator package manifest reconstruction drift。")
    return manifest


def _require_trusted_committed_package(package: Path, *, project_root: Path) -> None:
    root = project_root.resolve()
    try:
        relative = package.resolve().relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("trusted preparation package 必须位于当前仓库内。") from error
    status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            relative,
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        raise ValueError("preparation package 必须是 committed 且相对 HEAD 未修改。")
    tracked_output = subprocess.run(
        ["git", "ls-files", "--", relative],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    tracked = {line.strip() for line in tracked_output.splitlines() if line.strip()}
    actual = {
        path.relative_to(root).as_posix()
        for path in package.rglob("*")
        if path.is_file()
    }
    if tracked != actual:
        raise ValueError("preparation package file closure 未全部 Git tracked。")


def _package_member(package: Path, relative: Any, label: str) -> Path:
    member = (package / _require_text(relative, label)).resolve()
    try:
        member.relative_to(package.resolve())
    except ValueError as error:
        raise ValueError(f"{label} 逃逸 preparation package。") from error
    if not member.is_file():
        raise ValueError(f"{label} 不存在。")
    return member


def load_curator_import_chain_from_package(
    *,
    package_dir: str | Path,
    response: Mapping[str, Any],
    inputs: PilotSelectionInputs,
    expected_curator_slot: str,
    require_committed: bool = True,
) -> dict[str, Any]:
    package = Path(package_dir).resolve()
    manifest = validate_curator_preparation_package(
        package,
        config_path=inputs.config_path,
        project_root=inputs.project_root,
    )
    if require_committed:
        _require_trusted_committed_package(package, project_root=inputs.project_root)
    manifest_path = package / "manifest.json"
    manifest_sha256 = sha256_file(manifest_path)
    task_id = _require_text(response.get("task_id"), "external response task_id")
    if response.get("curator_slot") != expected_curator_slot:
        raise ValueError("cross-slot external curator response 被拒绝。")
    summary = _manifest_task_summary(
        manifest, curator_slot=expected_curator_slot, task_id=task_id
    )
    task_path = _package_member(package, summary.get("task_path"), "task path")
    map_path = _package_member(
        package, summary.get("coordinator_map_path"), "coordinator map path"
    )
    task = load_json_object(task_path, label="trusted curator task")
    mapping = load_json_object(map_path, label="trusted coordinator map")
    closure = validate_curator_import_chain(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        task=task,
        mapping=mapping,
        inputs=inputs,
        expected_curator_slot=expected_curator_slot,
    )
    return {
        "manifest": manifest,
        "manifest_sha256": manifest_sha256,
        "task": task,
        "mapping": mapping,
        "closure": closure,
    }


def validate_curator_submission_against_package(
    submission: Mapping[str, Any],
    *,
    package_dir: str | Path,
    inputs: PilotSelectionInputs,
    require_committed: bool = True,
) -> dict[str, Any]:
    chain = load_curator_import_chain_from_package(
        package_dir=package_dir,
        response={
            "task_id": submission.get("task", {}).get("task_id"),
            "curator_slot": submission.get("curator_slot"),
        },
        inputs=inputs,
        expected_curator_slot=submission.get("curator_slot"),
        require_committed=require_committed,
    )
    validated = validate_curator_submission(
        submission,
        inputs=inputs,
        preparation_manifest=chain["manifest"],
        preparation_manifest_sha256=chain["manifest_sha256"],
    )
    if submission["task"]["sha256"] != payload_sha256(chain["task"]):
        raise ValueError("submission/trusted task content hash drift。")
    if submission["candidate_map"]["sha256"] != payload_sha256(chain["mapping"]):
        raise ValueError("submission/trusted mapping content hash drift。")
    return {**chain, "validated_submission": validated}


def _curator_export_identity_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dict(payload))
    body.pop("artifact_id", None)
    body.pop("bundle_identity", None)
    return body


def export_curator_bundle(
    *,
    package_dir: str | Path,
    curator_slot: str,
    output_dir: str | Path,
    config_path: str | Path,
    project_root: str | Path,
    exported_at: str,
    git_revision: str,
    require_committed: bool = True,
) -> Path:
    """Export one fillable bundle outside the repository without private maps."""

    root = Path(project_root).resolve()
    output = validate_external_output_path(
        output_dir, project_root=root, label="curator workspace"
    )
    if curator_slot not in CURATOR_SLOTS:
        raise ValueError("curator export slot 必须是 curator_a 或 curator_b。")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("curator export output 必须不存在或为空。")
    inputs = load_pilot_selection_inputs(config_path, project_root=root)
    package = Path(package_dir).resolve()
    manifest = validate_curator_preparation_package(
        package, config_path=inputs.config_path, project_root=root
    )
    if manifest.get("is_fixture"):
        purpose = "plumbing_only"
    else:
        purpose = "repository_external_independent_human_curation"
    if require_committed:
        _require_trusted_committed_package(package, project_root=root)
    package_reference = _preparation_package_reference(
        manifest, sha256_file(package / "manifest.json")
    )
    selected_summaries = sorted(
        [row for row in manifest["tasks"] if row["curator_slot"] == curator_slot],
        key=lambda row: row["topic_id"],
    )
    if len(selected_summaries) != 2:
        raise ValueError("curator export 必须精确包含两个 Topic tasks。")
    text_files: dict[str, str] = {
        "CURATOR_INSTRUCTIONS.md": (package / "CURATOR_INSTRUCTIONS.md").read_text(
            encoding="utf-8"
        )
    }
    json_files: dict[str, dict[str, Any]] = {}
    bundle_tasks = []
    for summary in selected_summaries:
        topic_id = summary["topic_id"]
        readable = _package_member(
            package, summary["readable_task_path"], "readable task path"
        )
        response_path = _package_member(
            package, summary["response_template_path"], "response template path"
        )
        task_name = f"tasks/{topic_id}.md"
        response_name = f"responses/{topic_id}_response.json"
        text_files[task_name] = readable.read_text(encoding="utf-8")
        response = load_json_object(response_path, label="blank response template")
        if (
            response.get("status") != "blank_template"
            or response.get("curator_slot") != curator_slot
        ):
            raise ValueError("curator export response template status/slot drift。")
        json_files[response_name] = response
        bundle_tasks.append(
            {
                "topic_id": topic_id,
                "question_id": summary["question_id"],
                "task_artifact_id": summary["task_artifact_id"],
                "task_identity": summary["task_identity"],
                "task_sha256": summary["task_sha256"],
                "candidate_roster_identity": summary["candidate_roster_identity"],
                "readable_task_path": task_name,
                "response_path": response_name,
                "u80": copy.deepcopy(manifest["u80"]),
            }
        )
    files = {
        **{
            name: hashlib.sha256(value.encode("utf-8")).hexdigest()
            for name, value in text_files.items()
        },
        **{name: payload_sha256(value) for name, value in json_files.items()},
    }
    bundle_manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_curator_export_bundle",
        "artifact_id": "pending",
        "bundle_identity": "pending",
        "pilot_version": PILOT_VERSION,
        "curator_slot": curator_slot,
        "source_preparation_package": package_reference,
        "tasks": bundle_tasks,
        "files": files,
        "contains_coordinator_mapping": False,
        "workspace_policy": "repository_external_fillable_copy",
        "exported_at": _require_datetime(exported_at, "curator export time"),
        "provenance": {
            "kind": "pilot_repository_external_curator_export",
            "created_by": "src.pilot_selection",
            "created_at": exported_at,
            "git_revision": _require_git_revision(
                git_revision, "curator export git revision"
            ),
        },
        "is_fixture": manifest["is_fixture"],
        "purpose": purpose,
    }
    identity = deterministic_identity(
        CURATOR_EXPORT_IDENTITY_PREFIX,
        _curator_export_identity_payload(bundle_manifest),
    )
    bundle_manifest["bundle_identity"] = identity
    bundle_manifest["artifact_id"] = (
        f"srtp_pilot_curator_export_{identity.rsplit(':', 1)[-1][:24]}"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.export_", dir=output.parent)
    )
    try:
        for relative, content in text_files.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        for relative, payload in json_files.items():
            write_json(staging / relative, payload)
        write_json(staging / "bundle_manifest.json", bundle_manifest)
        actual = {
            path.relative_to(staging).as_posix()
            for path in staging.rglob("*")
            if path.is_file()
        }
        if actual != set(files) | {"bundle_manifest.json"}:
            raise ValueError("curator export file closure drift。")
        if any("coordinator" in path.casefold() for path in actual):
            raise ValueError("curator export 不得包含 coordinator mapping。")
        if output.exists():
            output.rmdir()
        staging.replace(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return output / "bundle_manifest.json"


__all__ = [
    "BM25_METHOD_ID",
    "CURATOR_FORBIDDEN_KEYS",
    "CURATOR_SLOTS",
    "FIXTURE_METHOD_ID",
    "HUMAN_METHOD_ID",
    "REFERENCE_METHOD_ID",
    "MINIMUM_CURATOR_OVERLAP",
    "PILOT_VERSION",
    "PilotSelectionInputs",
    "SCHEMA_VERSION",
    "SELECTION_K",
    "assemble_curator_preparation_payloads",
    "build_adjudication_task",
    "build_blank_adjudication_response",
    "build_blank_curator_response",
    "build_bm25_selection",
    "build_curator_comparison",
    "build_curator_preparation_package",
    "build_curator_task_and_map",
    "build_final_human_selection",
    "build_human_selection_freeze_reference",
    "build_selection_artifact",
    "capture_git_state",
    "compute_bm25_config_identity",
    "compute_context_policy_identity",
    "compute_human_config_identity",
    "compute_question_identity",
    "compute_selection_context_config_identity",
    "export_curator_bundle",
    "import_adjudication_submission",
    "import_curator_submission",
    "load_curator_import_chain_from_package",
    "load_pilot_selection_inputs",
    "payload_sha256",
    "rank_pilot_bm25_candidates",
    "render_curator_instructions_markdown",
    "render_curator_task_markdown",
    "topic_config",
    "validate_adjudication_submission",
    "validate_adjudication_task",
    "validate_completed_curator_response",
    "validate_curator_import_chain",
    "validate_curator_preparation_package",
    "validate_curator_comparison",
    "validate_curator_submission",
    "validate_curator_submission_against_package",
    "validate_curator_task",
    "validate_external_output_path",
    "validate_human_selection_freeze_reference",
    "validate_selection_artifact",
    "write_json",
]
