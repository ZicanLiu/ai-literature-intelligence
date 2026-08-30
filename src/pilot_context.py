"""Selection-method-agnostic matched-context tooling for SRTP Pilot v0.2.

The builder consumes only the generic selection contract, the frozen U80
snapshot, and the frozen context policy.  BM25 ranks, curator priorities, and
other method-specific fields cannot influence rendering or ordering.
"""

from __future__ import annotations

import copy
import hashlib
import re
from datetime import datetime
from typing import Any, Mapping

from src.annotation_tasks import sha256_file
from src.pilot_selection import (
    BM25_METHOD_ID,
    HUMAN_METHOD_ID,
    PILOT_VERSION,
    SCHEMA_VERSION,
    SELECTION_K,
    PilotSelectionInputs,
    payload_sha256,
    topic_config,
    validate_human_selection_freeze_reference,
    validate_selection_artifact,
)
from src.w6_contracts import deterministic_identity


CONTEXT_IDENTITY_PREFIX = "srtp-pilot-matched-context"
CONTEXT_PAIR_IDENTITY_PREFIX = "srtp-pilot-matched-context-pair"


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON object。")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空字符串。")
    return value.strip()


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


def _token_pattern(policy: Mapping[str, Any]) -> re.Pattern[str]:
    tokenizer = _require_mapping(policy.get("tokenizer"), "context tokenizer")
    if tokenizer.get("implementation") != "python_re_unicode_finditer":
        raise ValueError("不支持的 Pilot context tokenizer implementation。")
    return re.compile(_require_text(tokenizer.get("pattern"), "tokenizer pattern"))


def tokenize_context_text(text: str, policy: Mapping[str, Any]) -> list[str]:
    """Return frozen provider-neutral counting tokens without changing text."""

    return [match.group(0) for match in _token_pattern(policy).finditer(str(text))]


def count_context_tokens(text: str, policy: Mapping[str, Any]) -> int:
    return sum(1 for _ in _token_pattern(policy).finditer(str(text)))


def _truncate_to_token_count(
    text: str, token_limit: int, *, policy: Mapping[str, Any]
) -> tuple[str, bool]:
    value = str(text).strip()
    matches = list(_token_pattern(policy).finditer(value))
    if len(matches) <= token_limit:
        return value, False
    if token_limit <= 0:
        return "", bool(value)
    marker = str(policy["truncation_marker"])
    return value[: matches[token_limit - 1].end()].rstrip() + marker, True


def truncate_paper_fields(
    title: str, abstract: str, *, policy: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply the same title-first per-paper cap, never a global tail cut."""

    cap = int(policy["per_paper_token_cap"])
    title_value = _require_text(title, "paper title")
    abstract_value = _require_text(abstract, "paper abstract")
    title_count = count_context_tokens(title_value, policy)
    if title_count >= cap:
        exposed_title, title_truncated = _truncate_to_token_count(
            title_value, cap, policy=policy
        )
        exposed_abstract = ""
        abstract_truncated = True
    else:
        exposed_title = title_value
        title_truncated = False
        exposed_abstract, abstract_truncated = _truncate_to_token_count(
            abstract_value, cap - title_count, policy=policy
        )
    token_count = count_context_tokens(f"{exposed_title}\n{exposed_abstract}", policy)
    if token_count > cap:
        raise ValueError("per-paper token cap 实现漂移。")
    return {
        "title": exposed_title,
        "abstract": exposed_abstract,
        "title_truncated": title_truncated,
        "abstract_truncated": abstract_truncated,
        "truncated": title_truncated or abstract_truncated,
        "token_count": token_count,
    }


def neutral_order_key(
    *, question_id: str, canonical_entity_id: str, policy: Mapping[str, Any]
) -> str:
    ordering = _require_mapping(policy.get("ordering"), "context ordering")
    if ordering.get("algorithm") != "sha256_seed_question_canonical_v1":
        raise ValueError("不支持的 Pilot context ordering algorithm。")
    value = "|".join(
        [
            _require_text(ordering.get("seed"), "context order seed"),
            _require_text(question_id, "question_id"),
            _require_text(canonical_entity_id, "canonical_entity_id"),
        ]
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _context_identity_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dict(payload))
    body.pop("artifact_id", None)
    body.pop("context_identity", None)
    return body


def _source_snapshot(item: Mapping[str, Any], entity_id: str) -> dict[str, str]:
    snapshot = {
        "selection_item_id": _require_text(
            item.get("selection_item_id"), "selection_item_id"
        ),
        "canonical_entity_id": entity_id,
        "title": _require_text(item.get("title"), f"{entity_id} title"),
        "abstract": _require_text(item.get("abstract"), f"{entity_id} abstract"),
    }
    return {**snapshot, "source_snapshot_sha256": payload_sha256(snapshot)}


def _build_matched_context_payload(
    *,
    inputs: PilotSelectionInputs,
    selection: Mapping[str, Any],
    human_selection_freeze: Mapping[str, Any] | None,
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    validated = validate_selection_artifact(
        selection,
        inputs=inputs,
        human_selection_freeze=human_selection_freeze,
    )
    topic = topic_config(inputs, validated["topic_id"])
    policy = copy.deepcopy(inputs.config["context_policy"])
    selected_ids = list(validated["selected_canonical_entity_ids"])
    ordered_ids = sorted(
        selected_ids,
        key=lambda entity_id: (
            neutral_order_key(
                question_id=topic["question_id"],
                canonical_entity_id=entity_id,
                policy=policy,
            ),
            entity_id,
        ),
    )
    snapshots: list[dict[str, Any]] = []
    blocks: list[str] = []
    for position, entity_id in enumerate(ordered_ids, start=1):
        source = _source_snapshot(
            inputs.view_by_topic_entity[(validated["topic_id"], entity_id)], entity_id
        )
        exposed = truncate_paper_fields(
            source["title"], source["abstract"], policy=policy
        )
        block = policy["field_template"].format(
            title=exposed["title"], abstract=exposed["abstract"]
        )
        blocks.append(block)
        snapshots.append(
            {
                "position": position,
                "canonical_entity_id": entity_id,
                "order_key_sha256": neutral_order_key(
                    question_id=topic["question_id"],
                    canonical_entity_id=entity_id,
                    policy=policy,
                ),
                "source_selection_item_id": source["selection_item_id"],
                "source_snapshot_sha256": source["source_snapshot_sha256"],
                "title": exposed["title"],
                "abstract": exposed["abstract"],
                "exact_exposed_text": (
                    f"Title: {exposed['title']}\nAbstract: {exposed['abstract']}"
                ),
                "title_truncated": exposed["title_truncated"],
                "abstract_truncated": exposed["abstract_truncated"],
                "truncated": exposed["truncated"],
                "token_count": exposed["token_count"],
            }
        )
    rendered = policy["separator"].join(blocks)
    total_tokens = count_context_tokens(rendered, policy)
    if total_tokens > int(policy["maximum_context_tokens"]):
        raise ValueError(
            "matched context 超过 frozen maximum_context_tokens；"
            "禁止 global tail truncation，fail closed。"
        )
    created = _require_datetime(created_at, "context created_at")
    revision = _require_git_revision(git_revision, "context git_revision")
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_matched_context",
        "artifact_id": "pending",
        "context_identity": "pending",
        "pilot_version": PILOT_VERSION,
        "topic": {
            "topic_id": topic["topic_id"],
            "question_id": topic["question_id"],
            "research_question_identity": topic["research_question_identity"],
        },
        "selection": {
            "artifact_id": selection["artifact_id"],
            "selection_identity": selection["selection_identity"],
            "sha256": payload_sha256(selection),
            "method_id": selection["selection_method"]["method_id"],
            "is_fixture": selection["is_fixture"],
            "purpose": selection["purpose"],
        },
        "u80": copy.deepcopy(selection["u80"]),
        "k": SELECTION_K,
        "ordered_canonical_entity_ids": ordered_ids,
        "paper_snapshots": snapshots,
        "config": {
            "artifact_id": inputs.config["artifact_id"],
            "config_identity": inputs.config["config_identity"],
            "sha256": sha256_file(inputs.config_path),
        },
        "context_policy": policy,
        "exact_rendered_context": rendered,
        "rendered_context_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "actual_total_token_count": total_tokens,
        "created_at": created,
        "provenance": {
            "kind": "selection_method_agnostic_matched_context_build",
            "created_by": "src.pilot_context",
            "created_at": created,
            "git_revision": revision,
        },
        "is_fixture": validated["is_fixture"],
        "purpose": (
            "plumbing_only"
            if validated["is_fixture"]
            else "formal_evidence_context_not_llm_prompt"
        ),
    }
    identity = deterministic_identity(
        CONTEXT_IDENTITY_PREFIX, _context_identity_payload(payload)
    )
    payload["context_identity"] = identity
    payload["artifact_id"] = f"srtp_pilot_context_{identity.rsplit(':', 1)[-1][:24]}"
    return payload


def build_matched_context(
    *,
    inputs: PilotSelectionInputs,
    selection: Mapping[str, Any],
    human_selection_freeze: Mapping[str, Any] | None = None,
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    """Build and self-validate one matched context from generic selection data."""

    payload = _build_matched_context_payload(
        inputs=inputs,
        selection=selection,
        human_selection_freeze=human_selection_freeze,
        created_at=created_at,
        git_revision=git_revision,
    )
    validate_matched_context(
        payload,
        selection=selection,
        inputs=inputs,
        human_selection_freeze=human_selection_freeze,
    )
    return payload


def validate_matched_context(
    context: Mapping[str, Any],
    *,
    selection: Mapping[str, Any],
    inputs: PilotSelectionInputs,
    human_selection_freeze: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconstruct and compare the complete context artifact fail-closed."""

    artifact = _require_mapping(dict(context), "matched context")
    expected_fields = {
        "schema_version",
        "artifact_type",
        "artifact_id",
        "context_identity",
        "pilot_version",
        "topic",
        "selection",
        "u80",
        "k",
        "ordered_canonical_entity_ids",
        "paper_snapshots",
        "config",
        "context_policy",
        "exact_rendered_context",
        "rendered_context_sha256",
        "actual_total_token_count",
        "created_at",
        "provenance",
        "is_fixture",
        "purpose",
    }
    if set(artifact) != expected_fields:
        raise ValueError("matched context schema fields drift。")
    if artifact.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("matched context schema_version drift。")
    if artifact.get("artifact_type") != "srtp_pilot_matched_context":
        raise ValueError("matched context artifact_type drift。")
    if artifact.get("pilot_version") != PILOT_VERSION:
        raise ValueError("matched context Pilot version drift。")
    provenance = _require_mapping(artifact.get("provenance"), "context provenance")
    reconstructed = _build_matched_context_payload(
        inputs=inputs,
        selection=selection,
        human_selection_freeze=human_selection_freeze,
        created_at=artifact.get("created_at"),
        git_revision=provenance.get("git_revision"),
    )
    if artifact != reconstructed:
        raise ValueError(
            "matched context deterministic reconstruction drift；"
            "selection/U80/policy/content/order/hash 不一致。"
        )
    return {
        "artifact_id": artifact["artifact_id"],
        "context_identity": artifact["context_identity"],
        "topic_id": artifact["topic"]["topic_id"],
        "question_id": artifact["topic"]["question_id"],
        "u80": copy.deepcopy(artifact["u80"]),
        "k": artifact["k"],
        "ordered_canonical_entity_ids": tuple(artifact["ordered_canonical_entity_ids"]),
        "context_policy_identity": artifact["context_policy"]["config_identity"],
        "actual_total_token_count": artifact["actual_total_token_count"],
        "is_fixture": artifact["is_fixture"],
    }


def validate_matched_context_pair(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    left_selection: Mapping[str, Any],
    right_selection: Mapping[str, Any],
    inputs: PilotSelectionInputs,
    left_human_selection_freeze: Mapping[str, Any] | None = None,
    right_human_selection_freeze: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate BM25/Human fairness while allowing natural content differences."""

    validate_matched_context(
        left,
        selection=left_selection,
        inputs=inputs,
        human_selection_freeze=left_human_selection_freeze,
    )
    validate_matched_context(
        right,
        selection=right_selection,
        inputs=inputs,
        human_selection_freeze=right_human_selection_freeze,
    )
    required_equal = {
        "pilot_version": (left["pilot_version"], right["pilot_version"]),
        "topic": (left["topic"], right["topic"]),
        "u80": (left["u80"], right["u80"]),
        "k": (left["k"], right["k"]),
        "context_policy": (left["context_policy"], right["context_policy"]),
        "config": (left["config"], right["config"]),
        "fixture_status": (left["is_fixture"], right["is_fixture"]),
    }
    mismatches = [
        name for name, values in required_equal.items() if values[0] != values[1]
    ]
    if mismatches:
        raise ValueError(
            "matched-context fairness mismatch：" + ", ".join(sorted(mismatches)) + "。"
        )
    left_count = int(left["actual_total_token_count"])
    right_count = int(right["actual_total_token_count"])
    overlap = len(
        set(left["ordered_canonical_entity_ids"])
        & set(right["ordered_canonical_entity_ids"])
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_matched_context_pair_validation",
        "validation_identity": "pending",
        "status": "pass",
        "pilot_version": left["pilot_version"],
        "topic": copy.deepcopy(left["topic"]),
        "u80": copy.deepcopy(left["u80"]),
        "k": left["k"],
        "context_policy_identity": left["context_policy"]["config_identity"],
        "tokenizer": copy.deepcopy(left["context_policy"]["tokenizer"]),
        "representation": copy.deepcopy(left["context_policy"]["representation"]),
        "ordering": copy.deepcopy(left["context_policy"]["ordering"]),
        "left": {
            "artifact_id": left["artifact_id"],
            "context_identity": left["context_identity"],
            "selection_method_id": left["selection"]["method_id"],
            "actual_total_token_count": left_count,
        },
        "right": {
            "artifact_id": right["artifact_id"],
            "context_identity": right["context_identity"],
            "selection_method_id": right["selection"]["method_id"],
            "actual_total_token_count": right_count,
        },
        "selected_set_overlap_count": overlap,
        "actual_token_delta_left_minus_right": left_count - right_count,
        "actual_token_delta_absolute": abs(left_count - right_count),
        "allowed_differences": [
            "selected_canonical_entity_ids",
            "natural_token_count",
            "content_caused_truncation",
        ],
        "padding_used": False,
    }
    report["validation_identity"] = deterministic_identity(
        CONTEXT_PAIR_IDENTITY_PREFIX,
        {key: value for key, value in report.items() if key != "validation_identity"},
    )
    return report


def validate_formal_pair_method_roster(
    left_method_id: str,
    right_method_id: str,
    *,
    left_is_fixture: bool,
    right_is_fixture: bool,
) -> None:
    if left_is_fixture or right_is_fixture:
        raise ValueError("formal Pilot pair 不得包含 fixture context。")
    if {left_method_id, right_method_id} != {BM25_METHOD_ID, HUMAN_METHOD_ID}:
        raise ValueError(
            "formal Pilot pair method roster 必须精确为 BM25 Lexical + Dual-Curator。"
        )


def validate_formal_pair_selection_binding(
    left_selection: Mapping[str, Any],
    right_selection: Mapping[str, Any],
    *,
    inputs: PilotSelectionInputs,
) -> dict[str, Any]:
    """Bind formal BM25 provenance to the Human artifact in this exact pair."""

    left_method = _require_mapping(
        left_selection.get("selection_method"), "left selection method"
    ).get("method_id")
    right_method = _require_mapping(
        right_selection.get("selection_method"), "right selection method"
    ).get("method_id")
    validate_formal_pair_method_roster(
        left_method,
        right_method,
        left_is_fixture=left_selection.get("is_fixture") is not False,
        right_is_fixture=right_selection.get("is_fixture") is not False,
    )
    if left_method == BM25_METHOD_ID:
        bm25_side = "left"
        human_side = "right"
        bm25_selection = left_selection
        human_selection = right_selection
    else:
        bm25_side = "right"
        human_side = "left"
        bm25_selection = right_selection
        human_selection = left_selection

    bm25_details = _require_mapping(
        bm25_selection.get("method_specific_provenance"),
        "formal BM25 provenance",
    )
    validate_human_selection_freeze_reference(
        _require_mapping(
            bm25_details.get("human_selection_freeze"),
            "formal BM25 Human-freeze reference",
        ),
        human_selection,
    )
    validated_human = validate_selection_artifact(human_selection, inputs=inputs)
    validated_bm25 = validate_selection_artifact(
        bm25_selection,
        inputs=inputs,
        human_selection_freeze=human_selection,
    )
    if (
        validated_human["method_id"] != HUMAN_METHOD_ID
        or validated_bm25["method_id"] != BM25_METHOD_ID
        or validated_human["is_fixture"]
        or validated_bm25["is_fixture"]
    ):
        raise ValueError("formal pair selection method/fixture validation drift。")
    for key in ("topic_id", "question_id", "u80", "k"):
        if validated_bm25[key] != validated_human[key]:
            raise ValueError(f"formal pair BM25/Human {key} binding drift。")
    return {
        "bm25_side": bm25_side,
        "human_side": human_side,
        "human_artifact_id": validated_human["artifact_id"],
        "human_selection_identity": validated_human["selection_identity"],
        "human_selection_sha256": payload_sha256(human_selection),
        "human_selection_frozen_at": human_selection["created_at"],
    }


def validate_formal_matched_context_pair(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    left_selection: Mapping[str, Any],
    right_selection: Mapping[str, Any],
    inputs: PilotSelectionInputs,
) -> dict[str, Any]:
    binding = validate_formal_pair_selection_binding(
        left_selection, right_selection, inputs=inputs
    )
    left_freeze = right_selection if binding["bm25_side"] == "left" else None
    right_freeze = left_selection if binding["bm25_side"] == "right" else None
    report = validate_matched_context_pair(
        left,
        right,
        left_selection=left_selection,
        right_selection=right_selection,
        inputs=inputs,
        left_human_selection_freeze=left_freeze,
        right_human_selection_freeze=right_freeze,
    )
    report["validation_mode"] = "formal_bm25_vs_dual_curator"
    report["human_freeze_binding"] = binding
    report["validation_identity"] = deterministic_identity(
        CONTEXT_PAIR_IDENTITY_PREFIX,
        {key: value for key, value in report.items() if key != "validation_identity"},
    )
    return report


__all__ = [
    "build_matched_context",
    "count_context_tokens",
    "neutral_order_key",
    "tokenize_context_text",
    "truncate_paper_fields",
    "validate_formal_matched_context_pair",
    "validate_formal_pair_method_roster",
    "validate_formal_pair_selection_binding",
    "validate_matched_context",
    "validate_matched_context_pair",
]
