"""Evidence-grounded synthesis input, evidence-unit, and claim contracts for W6.

This module verifies structured evidence and citations.  It deliberately contains
no LLM client, prompt execution, PDF downloader, or free-form review generator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from src.w6_contracts import (
    W6_SCHEMA_VERSION,
    load_json_object,
    validate_artifact_identity_reference,
)


EVIDENCE_TYPES = frozenset(
    {"abstract_snippet", "structured_metadata", "public_summary_snippet"}
)
EXTRACTION_STATUSES = frozenset({"extracted", "human_verified", "rejected"})
CONFIDENCE_VALUES = frozenset({"high", "medium", "low"})
SUPPORT_STATUSES = frozenset({"supported", "partially_supported", "unsupported"})
CITATION_STATUSES = frozenset({"verified", "incomplete", "missing"})
MAX_SNIPPET_CHARACTERS = 800


def validate_evidence_units(
    payload: dict[str, Any],
    *,
    records: Mapping[str, dict[str, Any]],
    canonical: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "copyright_policy",
            "created_at",
            "provenance",
            "evidence_units",
        },
        "evidence artifact",
    )
    _require_header(payload, "w6_evidence_units")
    if payload["copyright_policy"] != "short_public_snippets_or_structured_fields_only":
        raise ValueError("evidence contract 不得默认复制整篇论文正文。")
    _require_datetime(payload["created_at"], "evidence created_at")
    _validate_provenance(payload["provenance"], "evidence provenance")
    result: dict[str, dict[str, Any]] = {}
    for raw_unit in _require_nonempty_list(payload["evidence_units"], "evidence_units"):
        unit = _require_mapping(raw_unit, "evidence unit")
        _require_exact_fields(
            unit,
            {
                "evidence_id",
                "paper_identity",
                "evidence_type",
                "source_location",
                "content",
                "provenance",
                "extraction_status",
                "confidence",
            },
            "evidence unit",
        )
        evidence_id = _require_id(unit["evidence_id"], "evidence_id")
        if evidence_id in result:
            raise ValueError(f"duplicate evidence_id：{evidence_id}。")
        identity = _require_mapping(unit["paper_identity"], "evidence paper_identity")
        _require_exact_fields(
            identity, {"canonical_entity_id", "record_id"}, "evidence paper_identity"
        )
        entity_id = identity["canonical_entity_id"]
        record_id = identity["record_id"]
        entity = canonical["entities"].get(entity_id)
        if entity is None or record_id not in records or record_id not in entity["alias_record_ids"]:
            raise ValueError(f"evidence {evidence_id} paper identity mismatch。")
        if unit["evidence_type"] not in EVIDENCE_TYPES:
            raise ValueError(f"evidence {evidence_id} evidence_type 非法。")
        location = _require_mapping(unit["source_location"], "evidence source_location")
        _require_exact_fields(
            location,
            {"source_type", "source_reference", "locator"},
            "evidence source_location",
        )
        _require_nonempty_string(location["source_type"], "source_type")
        _require_nonempty_string(location["source_reference"], "source_reference")
        _require_nonempty_string(location["locator"], "source locator")
        content = _require_mapping(unit["content"], "evidence content")
        _require_exact_fields(content, {"snippet", "structured_field"}, "evidence content")
        snippet = content["snippet"]
        field = content["structured_field"]
        if (snippet is None) == (field is None):
            raise ValueError(f"evidence {evidence_id} 必须且只能提供 snippet/structured_field 之一。")
        if snippet is not None:
            _require_nonempty_string(snippet, "evidence snippet")
            if len(snippet) > MAX_SNIPPET_CHARACTERS:
                raise ValueError(f"evidence {evidence_id} snippet 超过版权安全上限。")
        if field is not None:
            field_mapping = _require_mapping(field, "structured_field")
            _require_exact_fields(field_mapping, {"name", "value"}, "structured_field")
            _require_nonempty_string(field_mapping["name"], "structured field name")
            if not isinstance(field_mapping["value"], (str, int, float, bool)):
                raise ValueError("structured field value 必须是 JSON scalar。")
        _validate_extraction_provenance(unit["provenance"], evidence_id)
        if unit["extraction_status"] not in EXTRACTION_STATUSES:
            raise ValueError(f"evidence {evidence_id} extraction_status 非法。")
        if unit["confidence"] not in CONFIDENCE_VALUES:
            raise ValueError(f"evidence {evidence_id} confidence 非法。")
        result[evidence_id] = unit
    return result


def validate_synthesis_input(
    payload: dict[str, Any],
    *,
    registry: Mapping[str, dict[str, str]],
    topics: Mapping[str, dict[str, Any]],
    pool_members: Mapping[str, dict[str, Any]],
    method_packages: Mapping[str, dict[str, Any]],
    records: Mapping[str, dict[str, Any]],
    canonical: Mapping[str, Any],
    evidence: Mapping[str, dict[str, Any]],
    expected_artifact_ids: Mapping[str, str],
) -> dict[str, Any]:
    if set(expected_artifact_ids) != {
        "topic_set",
        "source_records",
        "retrieval_provenance",
        "evidence_units",
    }:
        raise ValueError("synthesis expected artifact roster 不完整。")
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "synthesis_input_id",
            "topic",
            "ranked_papers",
            "selected_pool_item_ids",
            "paper_metadata",
            "source_provenance",
            "evidence_units",
            "created_at",
            "provenance",
        },
        "synthesis input",
    )
    _require_header(payload, "w6_synthesis_input")
    _require_id(payload["synthesis_input_id"], "synthesis_input_id")
    topic = _require_mapping(payload["topic"], "synthesis topic")
    _require_exact_fields(
        topic, {"topic_id", "research_question", "topic_artifact"}, "synthesis topic"
    )
    topic_id = topic["topic_id"]
    if topic_id not in topics or topic["research_question"] != topics[topic_id]["research_question"]:
        raise ValueError("synthesis topic identity/question mismatch。")
    topic_ref = _validate_registry_reference(
        topic["topic_artifact"], registry, "synthesis topic artifact"
    )
    if topic_ref["artifact_id"] != expected_artifact_ids["topic_set"]:
        raise ValueError("synthesis topic_artifact 必须绑定冻结 topic_set。")
    ranked = _require_mapping(payload["ranked_papers"], "ranked_papers")
    _require_exact_fields(
        ranked,
        {
            "method_manifest_artifact_id",
            "manifest_sha256",
            "ranking_sha256",
            "method_id",
            "status",
        },
        "ranked_papers",
    )
    artifact_id = ranked["method_manifest_artifact_id"]
    package = method_packages.get(artifact_id)
    if package is None:
        raise ValueError("synthesis ranked list 必须来自已验证 frozen method package。")
    if (
        package["manifest_sha256"] != ranked["manifest_sha256"]
        or package["ranking_sha256"] != ranked["ranking_sha256"]
        or package["method_id"] != ranked["method_id"]
        or ranked["status"] != "frozen"
    ):
        raise ValueError("synthesis ranked list identity/hash drift。")
    selected = _require_string_list(
        payload["selected_pool_item_ids"], "selected_pool_item_ids", nonempty=True
    )
    if len(selected) != len(set(selected)):
        raise ValueError("synthesis selected_pool_item_ids 重复。")
    ranks_by_item = {row["pair_id"]: row for row in package["ranking_rows"]}
    for item_id in selected:
        if item_id not in pool_members or pool_members[item_id]["topic_id"] != topic_id:
            raise ValueError(f"synthesis selected candidate identity mismatch：{item_id}。")
        if item_id not in ranks_by_item:
            raise ValueError(f"synthesis ranked list 缺少 selected item：{item_id}。")
    if selected != sorted(selected, key=lambda item_id: ranks_by_item[item_id]["rank"]):
        raise ValueError("synthesis selected_pool_item_ids 必须保持冻结 ranking 顺序。")
    metadata_ref = _validate_registry_reference(
        payload["paper_metadata"], registry, "synthesis paper_metadata"
    )
    provenance_ref = _validate_registry_reference(
        payload["source_provenance"], registry, "synthesis source_provenance"
    )
    evidence_ref = _validate_registry_reference(
        payload["evidence_units"], registry, "synthesis evidence_units"
    )
    expected_refs = {
        "paper_metadata": expected_artifact_ids["source_records"],
        "source_provenance": expected_artifact_ids["retrieval_provenance"],
        "evidence_units": expected_artifact_ids["evidence_units"],
    }
    actual_refs = {
        "paper_metadata": metadata_ref["artifact_id"],
        "source_provenance": provenance_ref["artifact_id"],
        "evidence_units": evidence_ref["artifact_id"],
    }
    if actual_refs != expected_refs:
        raise ValueError("synthesis metadata/provenance/evidence artifact type binding 漂移。")
    if not evidence:
        raise ValueError("synthesis evidence artifact 不能为空。")
    selected_record_ids = {pool_members[item_id]["record_id"] for item_id in selected}
    if not selected_record_ids <= set(records):
        raise ValueError("synthesis selected pool 含 unknown source record。")
    selected_entity_ids = {
        canonical["entity_by_record"][record_id] for record_id in selected_record_ids
    }
    synthesis_artifact_id = payload["artifact_id"]
    trusted_input = registry.get(synthesis_artifact_id)
    if trusted_input is None:
        raise ValueError("synthesis input 自身必须注册在 artifact registry。")
    _require_datetime(payload["created_at"], "synthesis input created_at")
    _validate_provenance(payload["provenance"], "synthesis input provenance")
    return {
        "payload": payload,
        "topic_id": topic_id,
        "selected_pool_item_ids": selected,
        "selected_record_ids": selected_record_ids,
        "selected_entity_ids": selected_entity_ids,
        "artifact_id": synthesis_artifact_id,
        "artifact_sha256": trusted_input["sha256"],
        "method_package": package,
    }


def validate_structured_synthesis(
    payload: dict[str, Any],
    *,
    synthesis_input: Mapping[str, Any],
    evidence: Mapping[str, dict[str, Any]],
    canonical: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "synthesis_id",
            "synthesis_input_id",
            "synthesis_input",
            "claims",
            "rendered_review",
            "generation_provenance",
        },
        "structured synthesis",
    )
    _require_header(payload, "w6_structured_synthesis")
    _require_id(payload["synthesis_id"], "synthesis_id")
    if payload["synthesis_input_id"] != synthesis_input["payload"]["synthesis_input_id"]:
        raise ValueError("structured synthesis input identity mismatch。")
    input_ref = validate_artifact_identity_reference(
        payload["synthesis_input"], "structured synthesis input"
    )
    if input_ref != {
        "artifact_id": synthesis_input["artifact_id"],
        "sha256": synthesis_input["artifact_sha256"],
    }:
        raise ValueError("structured synthesis 未绑定实际 synthesis input hash。")
    claims: dict[str, dict[str, Any]] = {}
    for raw_claim in _require_nonempty_list(payload["claims"], "synthesis claims"):
        claim = _require_mapping(raw_claim, "synthesis claim")
        _require_exact_fields(
            claim,
            {
                "claim_id",
                "claim_text",
                "supporting_canonical_entity_ids",
                "evidence_refs",
                "confidence",
                "support_status",
                "citation_status",
            },
            "synthesis claim",
        )
        claim_id = _require_id(claim["claim_id"], "claim_id")
        if claim_id in claims:
            raise ValueError(f"duplicate claim_id：{claim_id}。")
        _require_nonempty_string(claim["claim_text"], f"{claim_id}.claim_text")
        entity_ids = _require_string_list(
            claim["supporting_canonical_entity_ids"],
            f"{claim_id}.supporting_canonical_entity_ids",
            nonempty=False,
        )
        evidence_refs = _require_string_list(
            claim["evidence_refs"], f"{claim_id}.evidence_refs", nonempty=False
        )
        if len(entity_ids) != len(set(entity_ids)) or len(evidence_refs) != len(set(evidence_refs)):
            raise ValueError(f"claim {claim_id} entity/evidence refs 不得重复。")
        if not set(entity_ids) <= set(canonical["entities"]):
            raise ValueError(f"claim {claim_id} dangling paper reference。")
        if not set(entity_ids) <= synthesis_input["selected_entity_ids"]:
            raise ValueError(f"claim {claim_id} 引用 ranked selection 之外的 paper。")
        dangling = sorted(set(evidence_refs).difference(evidence))
        if dangling:
            raise ValueError(f"claim {claim_id} dangling evidence ref：{dangling}。")
        evidence_entities = {
            evidence[evidence_id]["paper_identity"]["canonical_entity_id"]
            for evidence_id in evidence_refs
        }
        evidence_records = {
            evidence[evidence_id]["paper_identity"]["record_id"]
            for evidence_id in evidence_refs
        }
        if evidence_refs and evidence_entities != set(entity_ids):
            raise ValueError(f"claim {claim_id} evidence 与 supporting paper identity 不一致。")
        if not evidence_records <= synthesis_input["selected_record_ids"]:
            raise ValueError(f"claim {claim_id} evidence 引用 ranked selection 外 source record。")
        if claim["confidence"] not in CONFIDENCE_VALUES:
            raise ValueError(f"claim {claim_id} confidence 非法。")
        if claim["support_status"] not in SUPPORT_STATUSES:
            raise ValueError(f"claim {claim_id} support_status 非法。")
        if claim["citation_status"] not in CITATION_STATUSES:
            raise ValueError(f"claim {claim_id} citation_status 非法。")
        if claim["support_status"] in {"supported", "partially_supported"}:
            if not entity_ids or not evidence_refs:
                raise ValueError(f"claim {claim_id} supported/partial 但没有 paper/evidence。")
            expected_citation = (
                "verified" if claim["support_status"] == "supported" else "incomplete"
            )
            if claim["citation_status"] != expected_citation:
                raise ValueError(f"claim {claim_id} citation status 与 support status 不一致。")
            extraction_statuses = {
                evidence[evidence_id]["extraction_status"] for evidence_id in evidence_refs
            }
            if "rejected" in extraction_statuses:
                raise ValueError(f"claim {claim_id} 不得使用 rejected evidence 声明支持。")
            if claim["support_status"] == "supported" and extraction_statuses != {
                "human_verified"
            }:
                raise ValueError(
                    f"claim {claim_id} verified citation 只能由 human_verified evidence 支撑。"
                )
        else:
            if entity_ids or evidence_refs or claim["citation_status"] != "missing":
                raise ValueError(f"unsupported claim {claim_id} 必须显式无 citation/evidence。")
        claims[claim_id] = claim
    rendered = _require_mapping(payload["rendered_review"], "rendered_review")
    _require_exact_fields(
        rendered,
        {"format", "text", "generated_from_claim_ids"},
        "rendered_review",
    )
    if rendered["format"] != "markdown":
        raise ValueError("rendered review format 必须是 markdown。")
    _require_nonempty_string(rendered["text"], "rendered review text")
    rendered_claim_ids = _require_string_list(
        rendered["generated_from_claim_ids"], "rendered claim ids", nonempty=True
    )
    if set(rendered_claim_ids) != set(claims) or len(rendered_claim_ids) != len(claims):
        raise ValueError("rendered review 必须由全部且仅结构化 claims 生成。")
    _validate_provenance(payload["generation_provenance"], "synthesis generation provenance")
    return claims


def load_and_validate_evidence_units(
    path: str | Path,
    *,
    records: Mapping[str, dict[str, Any]],
    canonical: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    return validate_evidence_units(
        load_json_object(Path(path), label="evidence units"),
        records=records,
        canonical=canonical,
    )


def _validate_registry_reference(
    value: Any, registry: Mapping[str, dict[str, str]], label: str
) -> dict[str, str]:
    reference = validate_artifact_identity_reference(value, label)
    trusted = registry.get(reference["artifact_id"])
    if trusted is None or trusted["sha256"] != reference["sha256"]:
        raise ValueError(f"{label} identity/hash drift。")
    return reference


def _validate_extraction_provenance(value: Any, evidence_id: str) -> None:
    provenance = _require_mapping(value, f"{evidence_id}.provenance")
    _require_exact_fields(
        provenance,
        {
            "extraction_method",
            "model_or_tool",
            "extracted_at",
            "source_license_note",
        },
        "evidence extraction provenance",
    )
    _require_nonempty_string(provenance["extraction_method"], "extraction method")
    if provenance["model_or_tool"] is not None:
        tool = _require_mapping(provenance["model_or_tool"], "evidence model_or_tool")
        _require_exact_fields(tool, {"name", "version"}, "evidence model_or_tool")
        _require_nonempty_string(tool["name"], "evidence tool name")
        _require_nonempty_string(tool["version"], "evidence tool version")
    _require_datetime(provenance["extracted_at"], "evidence extracted_at")
    _require_nonempty_string(provenance["source_license_note"], "source_license_note")


def _validate_provenance(value: Any, label: str) -> None:
    provenance = _require_mapping(value, label)
    _require_exact_fields(
        provenance, {"kind", "created_by", "created_at", "git_revision"}, label
    )
    _require_nonempty_string(provenance["kind"], f"{label}.kind")
    _require_nonempty_string(provenance["created_by"], f"{label}.created_by")
    _require_datetime(provenance["created_at"], f"{label}.created_at")
    revision = str(provenance["git_revision"])
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
        raise ValueError(f"{label}.git_revision 必须是完整 Git SHA。")


def _require_header(payload: Mapping[str, Any], artifact_type: str) -> None:
    if payload.get("schema_version") != W6_SCHEMA_VERSION:
        raise ValueError(f"{artifact_type} schema_version 非法。")
    if payload.get("artifact_type") != artifact_type:
        raise ValueError(f"artifact_type 必须是 {artifact_type}。")
    _require_id(payload.get("artifact_id"), f"{artifact_type}.artifact_id")
    if not isinstance(payload.get("is_fixture"), bool):
        raise ValueError(f"{artifact_type}.is_fixture 必须是 boolean。")


def _require_exact_fields(payload: Mapping[str, Any], expected: set[str], label: str) -> None:
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


def _require_nonempty_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} 必须是非空 JSON array。")
    return value


def _require_string_list(value: Any, label: str, *, nonempty: bool) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{label} 必须是{'非空' if nonempty else ''} JSON array。")
    if any(not isinstance(item, str) or not item.strip() or item != item.strip() for item in value):
        raise ValueError(f"{label} 必须只包含非空、无首尾空白字符串。")
    return value


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


def _require_datetime(value: Any, label: str) -> None:
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(str(value or "").strip())
    except ValueError as error:
        raise ValueError(f"{label} 必须是 ISO-8601 时间。") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} 必须包含时区。")
