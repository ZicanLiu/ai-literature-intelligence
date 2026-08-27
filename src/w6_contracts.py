"""W6 research-artifact contracts and fail-closed validation.

The module intentionally validates small JSON artifacts instead of introducing a
JSON-Schema dependency.  It defines identity and no-leakage boundaries shared by
the six W6 branches; it does not implement retrieval, canonicalization, annotation,
ranking, or benchmark construction algorithms.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.annotation_tasks import sha256_file


W6_SCHEMA_VERSION = "0.2-alpha"
W6_CONTRACT_NAME = "w6_research_contract_bootstrap"
W6_CONTRACT_VERSION = "0.2-alpha"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
ALLOWED_RELEVANCE_LABELS = frozenset({0, 1, 2})
BLIND_VIEW_POLICY = "blind_to_retrieval_and_ranking_v2"
BLIND_ID_POLICY = "sha256(topic_id|public_identity|view_policy)"

BLIND_TASK_FORBIDDEN_KEYS = frozenset(
    {
        "acquisition_provenance_refs",
        "acquisition_system",
        "retrieval_hit_ids",
        "retrieval_run_id",
        "retriever",
        "source_rank",
        "source_score",
        "source_system_membership",
        "method_id",
        "score",
        "rank",
        "rrf",
        "selection_bucket",
        "selection_reasons",
        "relevance_label",
        "final_label",
        "other_annotator_label",
        "pool_item_id",
        "record_id",
        "canonical_entity_id",
    }
)
PRIVATE_REASONING_KEYS = frozenset(
    {"chain_of_thought", "private_reasoning", "reasoning_trace", "hidden_reasoning"}
)

PARALLEL_MODULE_FIXTURE_REQUIREMENTS = {
    "leader": {
        "topic_set",
        "retrieval_provenance",
        "source_records",
        "canonical_entities",
        "candidate_pool",
        "annotation_task_map",
        "annotation_tasks",
        "annotation_results",
        "annotation_reviews",
        "split_manifest",
        "hidden_label_anchor",
        "benchmark_manifest",
        "method_sparse_manifest",
    },
    "synthesis_and_fusion": {
        "topic_set",
        "retrieval_provenance",
        "source_records",
        "canonical_entities",
        "candidate_pool",
        "method_sparse_manifest",
        "method_dense_manifest",
        "method_fusion_manifest",
        "synthesis_input",
        "evidence_units",
        "structured_synthesis",
    },
    "multi_retriever_pool": {
        "topic_set",
        "retrieval_provenance",
        "source_records",
        "precanonical_candidate_pool",
    },
    "canonicalization_audit": {
        "topic_set",
        "retrieval_provenance",
        "source_records",
        "precanonical_candidate_pool",
        "canonical_entities",
        "candidate_pool",
    },
    "metadata_diagnostics": {
        "topic_set",
        "retrieval_provenance",
        "source_records",
        "precanonical_candidate_pool",
    },
    "quality_gate": {
        "topic_set",
        "retrieval_provenance",
        "source_records",
        "canonical_entities",
        "precanonical_candidate_pool",
        "candidate_pool",
        "annotation_task_map",
        "annotation_tasks",
        "annotation_results",
        "annotation_reviews",
        "split_manifest",
        "hidden_label_anchor",
        "benchmark_manifest",
        "method_sparse_manifest",
        "method_dense_manifest",
        "method_fusion_manifest",
        "synthesis_input",
        "evidence_units",
        "structured_synthesis",
    },
}


def load_json_object(path: str | Path, *, label: str = "JSON artifact") -> dict[str, Any]:
    artifact_path = Path(path)
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} 不是合法 JSON：{error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} 顶层必须是 JSON object。")
    return payload


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def deterministic_identity(prefix: str, value: Any) -> str:
    return f"{prefix}:sha256:{canonical_json_sha256(value)}"


def compute_pool_identity(pool: Mapping[str, Any]) -> str:
    payload = {
        "identity_stage": pool.get("identity_stage"),
        "policy": pool.get("policy"),
        "inputs": pool.get("inputs"),
        "topic_counts": pool.get("topic_counts"),
        "members": sorted(
            pool.get("members", []), key=lambda row: str(row.get("pool_item_id", ""))
        ),
    }
    return deterministic_identity("w6-pool", payload)


def compute_split_identity(split: Mapping[str, Any]) -> str:
    payload = {
        "topic_set": split.get("topic_set"),
        "frozen_at": split.get("frozen_at"),
        "freeze_policy": split.get("freeze_policy"),
        "dev_topic_ids": sorted(split.get("dev_topic_ids", [])),
        "hidden_test_topic_ids": sorted(split.get("hidden_test_topic_ids", [])),
    }
    return deterministic_identity("w6-topic-split", payload)


def compute_benchmark_identity(manifest: Mapping[str, Any]) -> str:
    payload = {
        "benchmark_name": manifest.get("benchmark_name"),
        "benchmark_version": manifest.get("benchmark_version"),
        "status": manifest.get("status"),
        "evaluation_target": manifest.get("evaluation_target"),
        "label_scheme": manifest.get("label_scheme"),
        "record_unit": manifest.get("record_unit"),
        "entity_policy": manifest.get("entity_policy"),
        "reference_year": manifest.get("reference_year"),
        "topic_set": manifest.get("topic_set"),
        "split": manifest.get("split"),
        "candidate_pool": manifest.get("candidate_pool"),
        "canonical_entities": manifest.get("canonical_entities"),
        "annotations": manifest.get("annotations"),
        "reviews": manifest.get("reviews"),
        "hidden_label_anchor": manifest.get("hidden_label_anchor"),
        "counts": manifest.get("counts"),
    }
    return deterministic_identity("w6-benchmark", payload)


def validate_topic_set(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "status",
            "is_fixture",
            "version",
            "created_at",
            "provenance",
            "topics",
        },
        "topic set",
    )
    _require_w6_header(payload, "w6_topic_set")
    if payload["status"] not in {"candidate", "frozen"}:
        raise ValueError("topic set status 必须是 candidate 或 frozen。")
    _require_datetime(payload["created_at"], "topic set created_at")
    _validate_provenance(payload["provenance"], "topic set provenance")
    topics = _require_nonempty_list(payload["topics"], "topics")
    result: dict[str, dict[str, Any]] = {}
    for index, topic in enumerate(topics, start=1):
        label = f"topic #{index}"
        mapping = _require_mapping_value(topic, label)
        _require_exact_fields(
            mapping,
            {
                "topic_id",
                "research_question",
                "scientific_object",
                "data_modality",
                "target_task",
                "method_role",
                "scientific_role",
                "scope_in",
                "scope_out",
                "boundary_cases",
                "acquisition_query_variants",
                "version",
                "lifecycle_status",
                "provenance",
            },
            label,
        )
        topic_id = _require_id(mapping["topic_id"], f"{label}.topic_id")
        if topic_id in result:
            raise ValueError(f"duplicate topic_id：{topic_id}。")
        for field in (
            "research_question",
            "scientific_object",
            "data_modality",
            "target_task",
            "method_role",
            "scientific_role",
            "version",
        ):
            _require_nonempty_string(mapping[field], f"{topic_id}.{field}")
        if mapping["lifecycle_status"] not in {"candidate", "frozen", "retired"}:
            raise ValueError(f"{topic_id}.lifecycle_status 非法。")
        for field in ("scope_in", "scope_out", "boundary_cases"):
            _require_string_list(mapping[field], f"{topic_id}.{field}", nonempty=True)
        variants = _require_nonempty_list(
            mapping["acquisition_query_variants"],
            f"{topic_id}.acquisition_query_variants",
        )
        variant_ids: set[str] = set()
        for variant in variants:
            variant_mapping = _require_mapping_value(variant, "query variant")
            _require_exact_fields(
                variant_mapping,
                {"query_variant_id", "query_text", "version", "status"},
                f"{topic_id} query variant",
            )
            variant_id = _require_id(
                variant_mapping["query_variant_id"], "query_variant_id"
            )
            if variant_id in variant_ids:
                raise ValueError(f"{topic_id} duplicate query_variant_id：{variant_id}。")
            variant_ids.add(variant_id)
            _require_nonempty_string(variant_mapping["query_text"], "query_text")
            _require_nonempty_string(variant_mapping["version"], "query version")
            if variant_mapping["status"] not in {"candidate", "frozen", "retired"}:
                raise ValueError(f"query variant {variant_id} status 非法。")
        _validate_provenance(mapping["provenance"], f"{topic_id}.provenance")
        result[topic_id] = mapping
    return result


def validate_retrieval_provenance(
    payload: dict[str, Any], *, topics: Mapping[str, dict[str, Any]]
) -> dict[str, Any]:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "created_at",
            "provenance",
            "runs",
            "hits",
        },
        "retrieval provenance",
    )
    _require_w6_header(payload, "w6_retrieval_provenance")
    _require_datetime(payload["created_at"], "retrieval provenance created_at")
    _validate_provenance(payload["provenance"], "retrieval provenance")
    runs: dict[str, dict[str, Any]] = {}
    for raw_run in _require_nonempty_list(payload["runs"], "retrieval runs"):
        run = _require_mapping_value(raw_run, "retrieval run")
        _require_exact_fields(
            run,
            {
                "retrieval_run_id",
                "topic_id",
                "acquisition_system",
                "query_variant_id",
                "method",
                "frozen_configuration",
                "configuration_sha256",
                "deterministic_seed",
                "started_at",
                "completed_at",
                "git_revision",
                "run_output_sha256",
            },
            "retrieval run",
        )
        run_id = _require_id(run["retrieval_run_id"], "retrieval_run_id")
        if run_id in runs:
            raise ValueError(f"duplicate retrieval_run_id：{run_id}。")
        topic_id = run["topic_id"]
        if topic_id not in topics:
            raise ValueError(f"retrieval run {run_id} 引用 unknown topic：{topic_id}。")
        variant_ids = {
            item["query_variant_id"]
            for item in topics[topic_id]["acquisition_query_variants"]
        }
        if run["query_variant_id"] not in variant_ids:
            raise ValueError(f"retrieval run {run_id} 引用 unknown query variant。")
        _require_nonempty_string(run["acquisition_system"], "acquisition_system")
        method = _require_mapping_value(run["method"], "retrieval method")
        _require_exact_fields(method, {"method_id", "family", "model"}, "retrieval method")
        _require_id(method["method_id"], "retrieval method_id")
        _require_nonempty_string(method["family"], "retrieval method family")
        if method["model"] is not None and not isinstance(method["model"], dict):
            raise ValueError("retrieval method.model 必须是 null 或 object。")
        config = _require_mapping_value(run["frozen_configuration"], "frozen_configuration")
        if run["configuration_sha256"] != canonical_json_sha256(config):
            raise ValueError(f"retrieval run {run_id} configuration hash mismatch。")
        seed = run["deterministic_seed"]
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise ValueError(f"retrieval run {run_id} deterministic_seed 必须是 integer/null。")
        _require_datetime(run["started_at"], f"{run_id}.started_at")
        _require_datetime(run["completed_at"], f"{run_id}.completed_at")
        _require_git_revision(run["git_revision"], f"{run_id}.git_revision")
        _require_sha256(run["run_output_sha256"], f"{run_id}.run_output_sha256")
        runs[run_id] = run

    hits: dict[str, dict[str, Any]] = {}
    ranks_by_run: dict[str, set[int]] = defaultdict(set)
    for raw_hit in _require_nonempty_list(payload["hits"], "retrieval hits"):
        hit = _require_mapping_value(raw_hit, "retrieval hit")
        _require_exact_fields(
            hit,
            {
                "retrieval_hit_id",
                "retrieval_run_id",
                "record_id",
                "source_rank",
                "source_score",
                "score_direction",
                "retrieved_at",
            },
            "retrieval hit",
        )
        hit_id = _require_id(hit["retrieval_hit_id"], "retrieval_hit_id")
        if hit_id in hits:
            raise ValueError(f"duplicate retrieval_hit_id：{hit_id}。")
        run_id = hit["retrieval_run_id"]
        if run_id not in runs:
            raise ValueError(f"retrieval hit {hit_id} 引用 unknown run：{run_id}。")
        _require_id(hit["record_id"], f"{hit_id}.record_id")
        rank = hit["source_rank"]
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            raise ValueError(f"retrieval hit {hit_id} source_rank 必须是正整数。")
        if rank in ranks_by_run[run_id]:
            raise ValueError(f"retrieval run {run_id} duplicate source_rank：{rank}。")
        ranks_by_run[run_id].add(rank)
        score = hit["source_score"]
        if score is not None and (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            raise ValueError(f"retrieval hit {hit_id} source_score 必须有限或 null。")
        expected_direction = "not_applicable" if score is None else "higher_is_better"
        if hit["score_direction"] != expected_direction:
            raise ValueError(f"retrieval hit {hit_id} score_direction 与 score 不一致。")
        _require_datetime(hit["retrieved_at"], f"{hit_id}.retrieved_at")
        hits[hit_id] = hit
    return {"runs": runs, "hits": hits}


def validate_source_records(
    payload: dict[str, Any], *, topics: Mapping[str, Any], retrieval: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "created_at",
            "provenance",
            "records",
        },
        "source records",
    )
    _require_w6_header(payload, "w6_source_records")
    _require_datetime(payload["created_at"], "source records created_at")
    _validate_provenance(payload["provenance"], "source records provenance")
    records: dict[str, dict[str, Any]] = {}
    hits = retrieval["hits"]
    runs = retrieval["runs"]
    referenced_hits: set[str] = set()
    source_identities: set[tuple[str, str]] = set()
    for raw_record in _require_nonempty_list(payload["records"], "source records"):
        record = _require_mapping_value(raw_record, "source record")
        _require_exact_fields(
            record,
            {
                "record_id",
                "topic_ids",
                "openalex_id",
                "doi",
                "title",
                "abstract",
                "publication_year",
                "authors",
                "venue",
                "landing_page_url",
                "metadata_completeness",
                "acquisition_provenance_refs",
                "record_provenance",
            },
            "source record",
        )
        record_id = _require_id(record["record_id"], "record_id")
        if record_id in records:
            raise ValueError(f"duplicate record_id：{record_id}。")
        topic_ids = _require_string_list(record["topic_ids"], f"{record_id}.topic_ids", nonempty=True)
        if len(topic_ids) != len(set(topic_ids)) or not set(topic_ids) <= set(topics):
            raise ValueError(f"source record {record_id} 包含 duplicate/unknown topic。")
        _require_nonempty_string(record["title"], f"{record_id}.title")
        if record["abstract"] is not None:
            _require_nonempty_string(record["abstract"], f"{record_id}.abstract")
        if record["openalex_id"] is not None:
            _require_nonempty_string(record["openalex_id"], f"{record_id}.openalex_id")
            if not re.fullmatch(r"W[0-9]+", normalize_openalex_id(record["openalex_id"])):
                raise ValueError(f"{record_id}.openalex_id 不是合法 OpenAlex work identity。")
        if record["doi"] is not None:
            _require_nonempty_string(record["doi"], f"{record_id}.doi")
            if not re.fullmatch(r"10\.[0-9]{4,9}/\S+", normalize_doi(record["doi"])):
                raise ValueError(f"{record_id}.doi 不是合法 DOI identity。")
        year = record["publication_year"]
        if isinstance(year, bool) or not isinstance(year, int) or not 1800 <= year <= 2200:
            raise ValueError(f"{record_id}.publication_year 非法。")
        _require_string_list(record["authors"], f"{record_id}.authors", nonempty=True)
        _require_nonempty_string(record["venue"], f"{record_id}.venue")
        _require_nonempty_string(record["landing_page_url"], f"{record_id}.landing_page_url")
        completeness = _require_mapping_value(
            record["metadata_completeness"], f"{record_id}.metadata_completeness"
        )
        _require_exact_fields(
            completeness,
            {"status", "missing_fields", "completeness_score"},
            f"{record_id}.metadata_completeness",
        )
        if completeness["status"] not in {"complete", "partial"}:
            raise ValueError(f"{record_id} metadata completeness status 非法。")
        missing = _require_string_list(
            completeness["missing_fields"], f"{record_id}.missing_fields", nonempty=False
        )
        score = completeness["completeness_score"]
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not 0 <= float(score) <= 1
        ):
            raise ValueError(f"{record_id}.completeness_score 必须在 0..1。")
        expected_missing = {
            field
            for field in ("abstract", "openalex_id", "doi")
            if record[field] is None
        }
        if len(missing) != len(set(missing)) or set(missing) != expected_missing:
            raise ValueError(
                f"{record_id} metadata missing_fields 与 abstract/OpenAlex/DOI 实值不一致。"
            )
        if bool(missing) != (completeness["status"] == "partial"):
            raise ValueError(f"{record_id} completeness status 与 missing_fields 不一致。")
        if (
            completeness["status"] == "complete" and float(score) != 1.0
        ) or (
            completeness["status"] == "partial" and float(score) >= 1.0
        ):
            raise ValueError(f"{record_id} completeness_score 与 complete/partial 状态不一致。")
        hit_ids = _require_string_list(
            record["acquisition_provenance_refs"],
            f"{record_id}.acquisition_provenance_refs",
            nonempty=True,
        )
        if len(hit_ids) != len(set(hit_ids)):
            raise ValueError(f"{record_id} acquisition provenance 重复。")
        hit_topics = set()
        for hit_id in hit_ids:
            hit = hits.get(hit_id)
            if hit is None or hit["record_id"] != record_id:
                raise ValueError(f"{record_id} acquisition provenance dangling/mismatch：{hit_id}。")
            referenced_hits.add(hit_id)
            hit_topics.add(runs[hit["retrieval_run_id"]]["topic_id"])
        if hit_topics != set(topic_ids):
            raise ValueError(f"{record_id}.topic_ids 与 retrieval provenance 不一致。")
        provenance = _require_mapping_value(
            record["record_provenance"], f"{record_id}.record_provenance"
        )
        _require_exact_fields(
            provenance,
            {"provider", "source_record_id", "retrieved_at"},
            f"{record_id}.record_provenance",
        )
        _require_nonempty_string(provenance["provider"], "record provider")
        _require_nonempty_string(provenance["source_record_id"], "source_record_id")
        source_identity = (
            provenance["provider"].casefold(),
            provenance["source_record_id"].casefold(),
        )
        if source_identity in source_identities:
            raise ValueError(
                f"duplicate provider/source_record_id identity：{source_identity}。"
            )
        source_identities.add(source_identity)
        _require_datetime(provenance["retrieved_at"], "record retrieved_at")
        records[record_id] = record
    if referenced_hits != set(hits):
        missing_hits = sorted(set(hits).difference(referenced_hits))
        raise ValueError("source records 未闭合 retrieval hits：" + ", ".join(missing_hits) + "。")
    return records


def validate_canonical_entities(
    payload: dict[str, Any], *, records: Mapping[str, Any], retrieval: Mapping[str, Any]
) -> dict[str, Any]:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "created_at",
            "provenance",
            "entities",
            "suspected_relationships",
        },
        "canonical entities",
    )
    _require_w6_header(payload, "w6_canonical_entities")
    _require_datetime(payload["created_at"], "canonical entities created_at")
    _validate_provenance(payload["provenance"], "canonical entities provenance")
    entities: dict[str, dict[str, Any]] = {}
    entity_by_record: dict[str, str] = {}
    for raw_entity in _require_nonempty_list(payload["entities"], "canonical entities"):
        entity = _require_mapping_value(raw_entity, "canonical entity")
        _require_exact_fields(
            entity,
            {
                "canonical_entity_id",
                "preferred_record_id",
                "normalized_openalex_ids",
                "normalized_dois",
                "normalized_title",
                "alias_record_ids",
                "identity_evidence",
                "identity_confidence",
                "review_state",
                "canonicalization_provenance",
                "source_retrieval_provenance_union",
            },
            "canonical entity",
        )
        entity_id = _require_id(entity["canonical_entity_id"], "canonical_entity_id")
        if entity_id in entities:
            raise ValueError(f"duplicate canonical_entity_id：{entity_id}。")
        aliases = _require_string_list(
            entity["alias_record_ids"], f"{entity_id}.alias_record_ids", nonempty=True
        )
        if len(aliases) != len(set(aliases)):
            raise ValueError(f"{entity_id} alias_record_ids 重复。")
        for record_id in aliases:
            if record_id not in records:
                raise ValueError(f"canonical entity {entity_id} dangling alias：{record_id}。")
            if record_id in entity_by_record:
                raise ValueError(f"record {record_id} 被多个 canonical entity 引用。")
            entity_by_record[record_id] = entity_id
        if entity["preferred_record_id"] not in aliases:
            raise ValueError(f"{entity_id}.preferred_record_id 必须属于 alias_record_ids。")
        if entity["identity_confidence"] not in {"high", "medium", "low"}:
            raise ValueError(f"{entity_id}.identity_confidence 非法。")
        if entity["review_state"] not in {"confirmed", "pending_review"}:
            raise ValueError(f"{entity_id}.review_state 非法。")
        if len(aliases) > 1 and not (
            entity["identity_confidence"] == "high"
            and entity["review_state"] == "confirmed"
        ):
            raise ValueError(
                f"{entity_id} 多 alias 自动合并只允许 high-confidence confirmed identity。"
            )
        openalex_ids = _require_string_list(
            entity["normalized_openalex_ids"],
            f"{entity_id}.normalized_openalex_ids",
            nonempty=False,
        )
        dois = _require_string_list(
            entity["normalized_dois"], f"{entity_id}.normalized_dois", nonempty=False
        )
        if any(value != normalize_openalex_id(value) for value in openalex_ids):
            raise ValueError(f"{entity_id} OpenAlex ID 未规范化。")
        if any(value != normalize_doi(value) for value in dois):
            raise ValueError(f"{entity_id} DOI 未规范化。")
        expected_openalex = sorted(
            {
                normalize_openalex_id(records[record_id]["openalex_id"])
                for record_id in aliases
                if records[record_id]["openalex_id"]
            }
        )
        expected_dois = sorted(
            {
                normalize_doi(records[record_id]["doi"])
                for record_id in aliases
                if records[record_id]["doi"]
            }
        )
        if sorted(openalex_ids) != expected_openalex or sorted(dois) != expected_dois:
            raise ValueError(f"{entity_id} normalized identifiers 与 source records 不一致。")
        preferred_title = records[entity["preferred_record_id"]]["title"]
        if entity["normalized_title"] != normalize_title(preferred_title):
            raise ValueError(f"{entity_id}.normalized_title 与 preferred record 不一致。")
        evidence = _require_nonempty_list(
            entity["identity_evidence"], f"{entity_id}.identity_evidence"
        )
        for item in evidence:
            item_map = _require_mapping_value(item, "identity evidence")
            _require_exact_fields(
                item_map, {"evidence_type", "value", "record_ids"}, "identity evidence"
            )
            _require_nonempty_string(item_map["evidence_type"], "identity evidence_type")
            _require_nonempty_string(item_map["value"], "identity evidence value")
            evidence_records = _require_string_list(
                item_map["record_ids"], "identity evidence record_ids", nonempty=True
            )
            if not set(evidence_records) <= set(aliases):
                raise ValueError(f"{entity_id} identity evidence 引用 entity 外 record。")
        union = _require_string_list(
            entity["source_retrieval_provenance_union"],
            f"{entity_id}.source_retrieval_provenance_union",
            nonempty=True,
        )
        expected_union = sorted(
            {
                hit_id
                for record_id in aliases
                for hit_id in records[record_id]["acquisition_provenance_refs"]
            }
        )
        if sorted(union) != expected_union:
            raise ValueError(f"{entity_id} retrieval provenance union 不完整。")
        _validate_canonicalization_provenance(
            entity["canonicalization_provenance"], entity_id
        )
        entities[entity_id] = entity
    if set(entity_by_record) != set(records):
        missing = sorted(set(records).difference(entity_by_record))
        raise ValueError("canonical mapping 未覆盖 source records：" + ", ".join(missing) + "。")

    relationships: dict[str, dict[str, Any]] = {}
    for raw_relationship in _require_list(
        payload["suspected_relationships"], "suspected relationships"
    ):
        relationship = _require_mapping_value(raw_relationship, "suspected relationship")
        _require_exact_fields(
            relationship,
            {
                "relationship_id",
                "entity_ids",
                "relationship_type",
                "review_state",
                "confidence",
                "evidence",
                "provenance",
            },
            "suspected relationship",
        )
        relationship_id = _require_id(
            relationship["relationship_id"], "relationship_id"
        )
        if relationship_id in relationships:
            raise ValueError(f"duplicate relationship_id：{relationship_id}。")
        entity_ids = _require_string_list(
            relationship["entity_ids"], "relationship.entity_ids", nonempty=True
        )
        if len(entity_ids) != 2 or len(set(entity_ids)) != 2:
            raise ValueError(f"{relationship_id} 必须连接两个不同 canonical entities。")
        if not set(entity_ids) <= set(entities):
            raise ValueError(f"{relationship_id} 引用 unknown canonical entity。")
        if relationship["relationship_type"] != "suspected_duplicate":
            raise ValueError(f"{relationship_id}.relationship_type 非法。")
        if relationship["review_state"] not in {"pending_review", "confirmed_distinct"}:
            raise ValueError(f"{relationship_id}.review_state 非法。")
        if relationship["confidence"] not in {"low", "medium"}:
            raise ValueError(f"suspected duplicate {relationship_id} 不得声明 high confidence。")
        _require_string_list(relationship["evidence"], "relationship.evidence", nonempty=True)
        _validate_provenance(relationship["provenance"], "relationship provenance")
        relationships[relationship_id] = relationship
    return {
        "entities": entities,
        "entity_by_record": entity_by_record,
        "relationships": relationships,
    }


def validate_candidate_pool(
    payload: dict[str, Any],
    *,
    topics: Mapping[str, Any],
    records: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    registry: Mapping[str, dict[str, str]],
    canonical: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "status",
            "identity_stage",
            "pool_identity",
            "policy",
            "inputs",
            "topic_counts",
            "members",
            "created_at",
            "provenance",
        },
        "candidate pool",
    )
    _require_w6_header(payload, "w6_candidate_pool")
    if payload["status"] not in {"candidate", "frozen"}:
        raise ValueError("candidate pool status 必须是 candidate/frozen。")
    if payload["identity_stage"] not in {
        "pre_canonicalization",
        "post_canonicalization",
    }:
        raise ValueError("candidate pool identity_stage 非法。")
    policy = _require_mapping_value(payload["policy"], "pool policy")
    _require_exact_fields(
        policy,
        {"name", "version", "parameters", "included_retrieval_run_ids"},
        "pool policy",
    )
    _require_nonempty_string(policy["name"], "pool policy name")
    _require_nonempty_string(policy["version"], "pool policy version")
    _require_mapping_value(policy["parameters"], "pool policy parameters")
    included_run_ids = _require_string_list(
        policy["included_retrieval_run_ids"],
        "pool policy included_retrieval_run_ids",
        nonempty=True,
    )
    if len(included_run_ids) != len(set(included_run_ids)):
        raise ValueError("pool policy included_retrieval_run_ids 重复。")
    included_run_id_set = set(included_run_ids)
    unknown_runs = sorted(included_run_id_set.difference(retrieval["runs"]))
    if unknown_runs:
        raise ValueError("pool policy 引用 unknown retrieval run：" + ", ".join(unknown_runs) + "。")
    inputs = _require_mapping_value(payload["inputs"], "pool inputs")
    expected_inputs = {"topic_set", "retrieval_provenance", "source_records"}
    if payload["identity_stage"] == "post_canonicalization":
        expected_inputs.add("canonical_entities")
        if canonical is None:
            raise ValueError("post-canonicalization pool 必须提供 canonical mapping。")
    elif canonical is not None:
        raise ValueError("pre-canonicalization pool validator 不得依赖 canonical mapping。")
    _require_exact_fields(inputs, expected_inputs, "pool inputs")
    for name, reference in inputs.items():
        _validate_registry_reference(reference, registry, f"pool inputs.{name}")
    members: dict[str, dict[str, Any]] = {}
    seen_topic_records: set[tuple[str, str]] = set()
    counts: Counter[str] = Counter()
    for raw_member in _require_nonempty_list(payload["members"], "pool members"):
        member = _require_mapping_value(raw_member, "pool member")
        _require_exact_fields(
            member,
            {
                "pool_item_id",
                "topic_id",
                "record_id",
                "canonical_entity_id",
                "retrieval_hit_ids",
                "source_system_membership",
                "selection_reasons",
            },
            "pool member",
        )
        item_id = _require_id(member["pool_item_id"], "pool_item_id")
        if item_id in members:
            raise ValueError(f"duplicate pool_item_id：{item_id}。")
        topic_id = member["topic_id"]
        record_id = member["record_id"]
        if topic_id not in topics:
            raise ValueError(f"pool item {item_id} 引用 unknown topic。")
        if record_id not in records or topic_id not in records[record_id]["topic_ids"]:
            raise ValueError(f"pool item {item_id} candidate identity mismatch。")
        topic_record = (topic_id, record_id)
        if topic_record in seen_topic_records:
            raise ValueError(f"candidate pool duplicate topic-record：{topic_record}。")
        seen_topic_records.add(topic_record)
        entity_id = member["canonical_entity_id"]
        expected_entity = (
            canonical["entity_by_record"].get(record_id) if canonical is not None else None
        )
        if payload["identity_stage"] == "post_canonicalization":
            if entity_id != expected_entity:
                raise ValueError(f"pool item {item_id} canonical identity mismatch。")
        elif entity_id is not None:
            raise ValueError("pre-canonicalization pool 不得预填 canonical_entity_id。")
        hit_ids = _require_string_list(
            member["retrieval_hit_ids"], f"{item_id}.retrieval_hit_ids", nonempty=True
        )
        if len(hit_ids) != len(set(hit_ids)):
            raise ValueError(f"pool item {item_id} retrieval_hit_ids 重复。")
        expected_hit_ids = {
            hit_id
            for hit_id, hit in retrieval["hits"].items()
            if hit["record_id"] == record_id
            and hit["retrieval_run_id"] in included_run_id_set
            and retrieval["runs"][hit["retrieval_run_id"]]["topic_id"] == topic_id
        }
        if set(hit_ids) != expected_hit_ids:
            raise ValueError(
                f"pool item {item_id} retrieval provenance union 与冻结 included runs 不一致。"
            )
        expected_systems = set()
        for hit_id in hit_ids:
            hit = retrieval["hits"].get(hit_id)
            if hit is None or hit["record_id"] != record_id:
                raise ValueError(f"pool item {item_id} dangling/mismatched retrieval hit。")
            run = retrieval["runs"][hit["retrieval_run_id"]]
            if run["topic_id"] != topic_id:
                raise ValueError(f"pool item {item_id} retrieval topic mismatch。")
            expected_systems.add(run["acquisition_system"])
        systems = _require_string_list(
            member["source_system_membership"],
            f"{item_id}.source_system_membership",
            nonempty=True,
        )
        if set(systems) != expected_systems or len(systems) != len(set(systems)):
            raise ValueError(f"pool item {item_id} source-system union 不一致。")
        _require_string_list(
            member["selection_reasons"], f"{item_id}.selection_reasons", nonempty=True
        )
        counts[topic_id] += 1
        members[item_id] = member
    topic_counts = _require_mapping_value(payload["topic_counts"], "topic_counts")
    if set(topic_counts) != set(topics):
        raise ValueError("candidate pool topic_counts 必须覆盖全部 topic。")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in topic_counts.values()):
        raise ValueError("candidate pool topic_counts 必须是非负整数。")
    if dict(counts) != topic_counts:
        raise ValueError("candidate pool topic_counts 与 members 不一致。")
    if payload["pool_identity"] != compute_pool_identity(payload):
        raise ValueError("candidate pool deterministic pool_identity mismatch。")
    _require_datetime(payload["created_at"], "candidate pool created_at")
    _validate_provenance(payload["provenance"], "candidate pool provenance")
    return members


def compute_blind_annotation_item_id(
    *, topic_id: str, record: Mapping[str, Any]
) -> str:
    """Return an opaque annotation ID independent of pool/retriever/rank identity."""
    identity = {
        "topic_id": topic_id,
        "public_identity": {
            "openalex_id": record["openalex_id"],
            "doi": record["doi"],
            "landing_page_url": record["landing_page_url"],
        },
        "view_policy": BLIND_VIEW_POLICY,
    }
    return "blind_" + canonical_json_sha256(identity)[:24]


def build_annotation_task_map(
    *, records: Mapping[str, dict[str, Any]], pool_members: Mapping[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build the private mapping kept outside the annotation-safe projection."""
    mappings: list[dict[str, Any]] = []
    seen_items: set[str] = set()
    for pool_item_id in sorted(pool_members):
        member = pool_members[pool_item_id]
        item_id = compute_blind_annotation_item_id(
            topic_id=member["topic_id"], record=records[member["record_id"]]
        )
        if item_id in seen_items:
            raise ValueError("opaque annotation_item_id collision。")
        seen_items.add(item_id)
        mappings.append(
            {
                "annotation_item_id": item_id,
                "annotation_task_id": f"annot:{item_id}",
                "topic_id": member["topic_id"],
                "pool_item_id": pool_item_id,
                "record_id": member["record_id"],
                "canonical_entity_id": member["canonical_entity_id"],
            }
        )
    return mappings


def validate_annotation_task_map(
    payload: dict[str, Any],
    *,
    records: Mapping[str, dict[str, Any]],
    pool_members: Mapping[str, dict[str, Any]],
    registry: Mapping[str, dict[str, str]],
) -> dict[str, dict[str, Any]]:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "view_policy",
            "id_policy",
            "candidate_pool",
            "created_at",
            "provenance",
            "mappings",
        },
        "annotation task map",
    )
    _require_w6_header(payload, "w6_annotation_task_map")
    if payload["view_policy"] != BLIND_VIEW_POLICY or payload["id_policy"] != BLIND_ID_POLICY:
        raise ValueError("annotation task map policy 非法。")
    _validate_registry_reference(
        payload["candidate_pool"], registry, "task map candidate_pool"
    )
    expected = build_annotation_task_map(records=records, pool_members=pool_members)
    mappings = _require_list(payload["mappings"], "annotation task mappings")
    if mappings != expected:
        raise ValueError("annotation task map 未精确绑定 opaque ID 与冻结 pool identity。")
    _require_datetime(payload["created_at"], "annotation task map created_at")
    _validate_provenance(payload["provenance"], "annotation task map provenance")
    return {row["annotation_task_id"]: row for row in mappings}


def build_blind_annotation_tasks(
    *,
    topics: Mapping[str, dict[str, Any]],
    records: Mapping[str, dict[str, Any]],
    task_mappings: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project mapped pool records onto the strict annotation-safe view."""
    tasks: list[dict[str, Any]] = []
    for mapping in sorted(task_mappings.values(), key=lambda row: row["pool_item_id"]):
        task_id = mapping["annotation_task_id"]
        topic = topics[mapping["topic_id"]]
        record = records[mapping["record_id"]]
        tasks.append(
            {
                "annotation_task_id": task_id,
                "annotation_item_id": mapping["annotation_item_id"],
                "annotation_round": "independent_primary",
                "topic": {
                    "topic_id": topic["topic_id"],
                    "research_question": topic["research_question"],
                    "scientific_object": topic["scientific_object"],
                    "data_modality": topic["data_modality"],
                    "target_task": topic["target_task"],
                    "method_role": topic["method_role"],
                    "scope_in": topic["scope_in"],
                    "scope_out": topic["scope_out"],
                    "boundary_cases": topic["boundary_cases"],
                },
                "candidate": {
                    "title": record["title"],
                    "abstract": record["abstract"],
                    "publication_year": record["publication_year"],
                    "authors": record["authors"],
                    "venue": record["venue"],
                    "public_identity": {
                        "openalex_id": record["openalex_id"],
                        "doi": record["doi"],
                        "landing_page_url": record["landing_page_url"],
                    },
                },
            }
        )
    return tasks


def validate_blind_annotation_tasks(
    payload: dict[str, Any],
    *,
    topics: Mapping[str, dict[str, Any]],
    records: Mapping[str, dict[str, Any]],
    task_mappings: Mapping[str, dict[str, Any]],
    registry: Mapping[str, dict[str, str]],
) -> dict[str, dict[str, Any]]:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "view_policy",
            "task_map",
            "created_at",
            "provenance",
            "tasks",
        },
        "blind annotation tasks",
    )
    _require_w6_header(payload, "w6_blind_annotation_tasks")
    if payload["view_policy"] != BLIND_VIEW_POLICY:
        raise ValueError("blind annotation view_policy 非法。")
    _validate_registry_reference(payload["task_map"], registry, "blind tasks task_map")
    leaked = sorted(_find_forbidden_keys(payload["tasks"], BLIND_TASK_FORBIDDEN_KEYS))
    if leaked:
        raise ValueError("blind annotation task 泄漏 retrieval/ranking 字段：" + ", ".join(leaked) + "。")
    expected = build_blind_annotation_tasks(
        topics=topics, records=records, task_mappings=task_mappings
    )
    tasks = _require_list(payload["tasks"], "annotation tasks")
    if tasks != expected:
        raise ValueError("blind annotation tasks 未精确匹配 full-record → blind-view 投影。")
    _require_datetime(payload["created_at"], "annotation tasks created_at")
    _validate_provenance(payload["provenance"], "annotation tasks provenance")
    return {task["annotation_task_id"]: task for task in tasks}


def validate_annotation_results(
    payload: dict[str, Any],
    *,
    tasks: Mapping[str, dict[str, Any]],
    task_mappings: Mapping[str, dict[str, Any]],
    split: Mapping[str, Any],
    split_sets: Mapping[str, set[str]],
    registry: Mapping[str, dict[str, str]],
) -> dict[str, dict[str, Any]]:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "label_scheme_version",
            "split",
            "annotation_started_at",
            "created_at",
            "provenance",
            "annotations",
        },
        "annotation results",
    )
    _require_w6_header(payload, "w6_ai_assisted_annotations")
    if payload["label_scheme_version"] != "query_relevance_0_1_2_v1":
        raise ValueError("annotation label scheme version 非法。")
    split_ref = _validate_registry_reference(payload["split"], registry, "annotations.split")
    if split_ref["artifact_id"] != split["artifact_id"] or split["reveal_state"] != "sealed":
        raise ValueError("annotations 必须绑定仍处于 sealed 状态的实际 split artifact。")
    _require_datetime(payload["annotation_started_at"], "annotation_started_at")
    split_frozen_at = datetime.fromisoformat(str(split["frozen_at"]))
    annotation_started_at = datetime.fromisoformat(str(payload["annotation_started_at"]))
    if annotation_started_at <= split_frozen_at:
        raise ValueError("annotation_started_at 必须晚于实际 split frozen_at。")
    private_keys = sorted(_find_forbidden_keys(payload, PRIVATE_REASONING_KEYS))
    if private_keys:
        raise ValueError("annotation artifact 不得存储 private chain-of-thought：" + ", ".join(private_keys) + "。")
    annotations: dict[str, dict[str, Any]] = {}
    seen_tasks: set[str] = set()
    for raw_annotation in _require_nonempty_list(payload["annotations"], "annotations"):
        annotation = _require_mapping_value(raw_annotation, "annotation")
        _require_exact_fields(
            annotation,
            {
                "annotation_id",
                "annotation_task_id",
                "topic_id",
                "pool_item_id",
                "record_id",
                "relevance_label",
                "confidence",
                "evidence_sources",
                "justification_summary",
                "uncertainty",
                "review_status",
                "annotation_provenance",
            },
            "annotation",
        )
        annotation_id = _require_id(annotation["annotation_id"], "annotation_id")
        if annotation_id in annotations:
            raise ValueError(f"duplicate annotation_id：{annotation_id}。")
        task_id = annotation["annotation_task_id"]
        task = tasks.get(task_id)
        mapping = task_mappings.get(task_id)
        if task is None or mapping is None:
            raise ValueError(f"annotation {annotation_id} 引用不存在 candidate/task。")
        if task_id in seen_tasks:
            raise ValueError(f"独立 annotation artifact duplicate task：{task_id}。")
        seen_tasks.add(task_id)
        expected = (
            mapping["topic_id"],
            mapping["pool_item_id"],
            mapping["record_id"],
        )
        actual = (
            annotation["topic_id"],
            annotation["pool_item_id"],
            annotation["record_id"],
        )
        if actual != expected:
            raise ValueError(f"annotation {annotation_id} candidate identity mismatch。")
        if annotation["topic_id"] not in split_sets["dev"]:
            raise ValueError(f"annotation {annotation_id} 不得公开 hidden-test topic label。")
        if type(annotation["relevance_label"]) is not int or annotation["relevance_label"] not in ALLOWED_RELEVANCE_LABELS:
            raise ValueError(f"annotation {annotation_id} illegal relevance label。")
        if annotation["confidence"] not in {"high", "medium", "low"}:
            raise ValueError(f"annotation {annotation_id} confidence 非法。")
        evidence = _require_nonempty_list(
            annotation["evidence_sources"], f"{annotation_id}.evidence_sources"
        )
        for source in evidence:
            source_map = _require_mapping_value(source, "annotation evidence source")
            _require_exact_fields(
                source_map,
                {"source_type", "source_reference", "checked_at"},
                "annotation evidence source",
            )
            _require_nonempty_string(source_map["source_type"], "evidence source_type")
            _require_nonempty_string(source_map["source_reference"], "evidence source_reference")
            _require_datetime(source_map["checked_at"], "evidence checked_at")
        _require_nonempty_string(annotation["justification_summary"], "justification_summary")
        if not isinstance(annotation["uncertainty"], str):
            raise ValueError("annotation uncertainty 必须是 string（可为空）。")
        if annotation["review_status"] not in {
            "ai_proposed",
            "pending_human_review",
            "human_reviewed",
            "adjudicated",
        }:
            raise ValueError(f"annotation {annotation_id} review_status 非法。")
        provenance = _validate_annotation_provenance(
            annotation["annotation_provenance"], annotation_id
        )
        if datetime.fromisoformat(str(provenance["created_at"])) < annotation_started_at:
            raise ValueError(
                f"annotation {annotation_id} provenance 时间早于 split-bound annotation start。"
            )
        if provenance["actor_type"] == "ai_assistant" and annotation["review_status"] in {
            "human_reviewed",
            "adjudicated",
        }:
            raise ValueError(f"AI annotation {annotation_id} 不得伪装为 pure-human final judgement。")
        annotations[annotation_id] = annotation
    _require_datetime(payload["created_at"], "annotation results created_at")
    if datetime.fromisoformat(str(payload["created_at"])) < annotation_started_at:
        raise ValueError("annotation results created_at 早于 annotation_started_at。")
    _validate_provenance(payload["provenance"], "annotation results provenance")
    return annotations


def validate_annotation_reviews(
    payload: dict[str, Any], *, annotations: Mapping[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Validate the review/adjudication layer separately from raw annotations."""
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "created_at",
            "provenance",
            "reviews",
        },
        "annotation reviews",
    )
    _require_w6_header(payload, "w6_annotation_reviews")
    reviews: dict[str, dict[str, Any]] = {}
    reviewed_annotations: set[str] = set()
    for raw_review in _require_list(payload["reviews"], "annotation reviews"):
        review = _require_mapping_value(raw_review, "annotation review")
        _require_exact_fields(
            review,
            {
                "review_id",
                "annotation_id",
                "topic_id",
                "pool_item_id",
                "reviewer_type",
                "reviewer_id",
                "decision",
                "final_label",
                "reviewed_at",
                "review_note",
                "provenance",
            },
            "annotation review",
        )
        review_id = _require_id(review["review_id"], "review_id")
        if review_id in reviews:
            raise ValueError(f"duplicate review_id：{review_id}。")
        annotation_id = review["annotation_id"]
        annotation = annotations.get(annotation_id)
        if annotation is None or annotation_id in reviewed_annotations:
            raise ValueError(f"review {review_id} 引用 unknown/duplicate annotation。")
        reviewed_annotations.add(annotation_id)
        if (
            review["topic_id"] != annotation["topic_id"]
            or review["pool_item_id"] != annotation["pool_item_id"]
        ):
            raise ValueError(f"review {review_id} annotation identity mismatch。")
        if review["reviewer_type"] not in {"human", "ai_assisted_human"}:
            raise ValueError("annotation review 必须由 human/ai_assisted_human 完成。")
        _require_nonempty_string(review["reviewer_id"], "reviewer_id")
        if review["decision"] not in {"approve", "modify"}:
            raise ValueError("annotation review decision 必须是 approve/modify。")
        if type(review["final_label"]) is not int or review["final_label"] not in ALLOWED_RELEVANCE_LABELS:
            raise ValueError("annotation review final_label 非法。")
        if (
            review["decision"] == "approve"
            and review["final_label"] != annotation["relevance_label"]
        ):
            raise ValueError("approve review 不得改变原 annotation label。")
        _require_datetime(review["reviewed_at"], "annotation review reviewed_at")
        _require_nonempty_string(review["review_note"], "annotation review note")
        _validate_provenance(review["provenance"], "annotation review provenance")
        reviews[review_id] = review
    _require_datetime(payload["created_at"], "annotation reviews created_at")
    _validate_provenance(payload["provenance"], "annotation reviews provenance")
    return reviews


def validate_topic_split(
    payload: dict[str, Any], *, topics: Mapping[str, Any]
) -> dict[str, set[str]]:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "split_id",
            "topic_set",
            "split_identity",
            "status",
            "frozen_at",
            "frozen_by",
            "freeze_policy",
            "dev_topic_ids",
            "hidden_test_topic_ids",
            "reveal_state",
            "provenance",
        },
        "topic split",
    )
    _require_w6_header(payload, "w6_topic_split")
    _require_id(payload["split_id"], "split_id")
    validate_artifact_identity_reference(payload["topic_set"], "split.topic_set")
    if payload["status"] != "frozen":
        raise ValueError("topic split 必须 frozen。")
    _require_datetime(payload["frozen_at"], "split frozen_at")
    _require_nonempty_string(payload["frozen_by"], "split frozen_by")
    policy = _require_mapping_value(payload["freeze_policy"], "split freeze_policy")
    _require_exact_fields(
        policy,
        {"unit", "frozen_before_labels", "frozen_before_label_aware_method_selection"},
        "split freeze_policy",
    )
    if policy != {
        "unit": "topic",
        "frozen_before_labels": True,
        "frozen_before_label_aware_method_selection": True,
    }:
        raise ValueError("Dev/Hidden split 必须按 topic 且在 labels/method selection 前冻结。")
    dev = set(_require_string_list(payload["dev_topic_ids"], "dev_topic_ids", nonempty=True))
    hidden = set(
        _require_string_list(payload["hidden_test_topic_ids"], "hidden_test_topic_ids", nonempty=True)
    )
    if dev & hidden:
        raise ValueError("topic dev/test overlap。")
    if dev | hidden != set(topics):
        raise ValueError("topic split 必须恰好覆盖冻结 topic set。")
    if payload["reveal_state"] != "sealed":
        raise ValueError("Bootstrap split 只允许 sealed；reveal 属于独立 evaluator 边界。")
    if payload["split_identity"] != compute_split_identity(payload):
        raise ValueError("topic split identity/hash mismatch。")
    _validate_provenance(payload["provenance"], "split provenance")
    return {"dev": dev, "hidden": hidden}


def validate_hidden_label_anchor(
    payload: dict[str, Any],
    *,
    split: Mapping[str, Any],
    split_sets: Mapping[str, set[str]],
    registry: Mapping[str, dict[str, str]],
) -> None:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "seal_id",
            "split",
            "hidden_topic_ids",
            "label_artifact",
            "storage",
            "sealed_at",
            "reveal_policy",
            "access_policy",
            "provenance",
        },
        "hidden label anchor",
    )
    _require_w6_header(payload, "w6_hidden_label_anchor")
    _require_id(payload["seal_id"], "seal_id")
    split_ref = _validate_registry_reference(payload["split"], registry, "hidden anchor split")
    if split_ref["artifact_id"] != split["artifact_id"]:
        raise ValueError("hidden label anchor split identity mismatch。")
    hidden = set(
        _require_string_list(payload["hidden_topic_ids"], "hidden_topic_ids", nonempty=True)
    )
    if hidden != split_sets["hidden"]:
        raise ValueError("hidden label anchor topics 与 split 不一致。")
    label_ref = _require_mapping_value(payload["label_artifact"], "hidden label artifact")
    _require_exact_fields(label_ref, {"artifact_id", "sha256"}, "hidden label artifact")
    _require_id(label_ref["artifact_id"], "hidden label artifact_id")
    _require_sha256(label_ref["sha256"], "hidden label sha256")
    storage = _require_mapping_value(payload["storage"], "hidden label storage")
    _require_exact_fields(storage, {"location", "repository_path"}, "hidden label storage")
    if storage != {"location": "external", "repository_path": None}:
        raise ValueError("真实 hidden labels 必须在普通仓库之外，公开 anchor 不得含路径。")
    _require_datetime(payload["sealed_at"], "hidden labels sealed_at")
    if datetime.fromisoformat(str(payload["sealed_at"])) < datetime.fromisoformat(
        str(split["frozen_at"])
    ):
        raise ValueError("hidden label seal 不得早于实际 topic split freeze。")
    reveal = _require_mapping_value(payload["reveal_policy"], "hidden reveal policy")
    _require_exact_fields(
        reveal,
        {
            "method_freeze_required",
            "one_time_evaluation",
            "reveal_count",
            "revealed_at",
        },
        "hidden reveal policy",
    )
    if reveal != {
        "method_freeze_required": True,
        "one_time_evaluation": True,
        "reveal_count": 0,
        "revealed_at": None,
    }:
        raise ValueError("sealed hidden fixture 必须要求 method freeze 与一次性 reveal。")
    access = _require_mapping_value(payload["access_policy"], "hidden access policy")
    _require_exact_fields(
        access,
        {"generation_can_read", "allowed_consumer"},
        "hidden access policy",
    )
    if access != {"generation_can_read": False, "allowed_consumer": "sealed_evaluator"}:
        raise ValueError("hidden labels 不得进入 method generation。")
    _validate_provenance(payload["provenance"], "hidden anchor provenance")
def validate_benchmark_manifest(
    payload: dict[str, Any],
    *,
    registry: Mapping[str, dict[str, str]],
    topics: Mapping[str, Any],
    pool_members: Mapping[str, Any],
    canonical: Mapping[str, Any],
    annotations: Mapping[str, Any],
    reviews: Mapping[str, Any],
    split_sets: Mapping[str, set[str]],
) -> None:
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "benchmark_name",
            "benchmark_version",
            "status",
            "evaluation_target",
            "label_scheme",
            "record_unit",
            "entity_policy",
            "reference_year",
            "topic_set",
            "split",
            "candidate_pool",
            "canonical_entities",
            "annotations",
            "reviews",
            "hidden_label_anchor",
            "counts",
            "benchmark_identity",
            "generation_provenance",
            "review_provenance",
        },
        "benchmark manifest",
    )
    _require_w6_header(payload, "w6_benchmark_manifest")
    if payload["status"] == "approved":
        raise ValueError(
            "W6 formal approval/promotion gate 尚未由 Bootstrap 实现；approved 必须留给具备完整"
            " coverage/review/adjudication/roster/hash provenance 的后续 Benchmark contract。"
        )
    if payload["status"] not in {
        "bootstrap_fixture",
        "draft",
        "proposed",
        "sealed_candidate",
    }:
        raise ValueError("benchmark status 非法。")
    if payload["status"] == "bootstrap_fixture" and payload["is_fixture"] is not True:
        raise ValueError("bootstrap_fixture benchmark 必须显式 is_fixture=true。")
    _require_nonempty_string(payload["benchmark_name"], "benchmark_name")
    _require_nonempty_string(payload["benchmark_version"], "benchmark_version")
    if payload["evaluation_target"] != "query_relevance":
        raise ValueError("W6 Bootstrap benchmark 只定义 query_relevance。")
    label_scheme = _require_mapping_value(payload["label_scheme"], "benchmark label_scheme")
    if label_scheme != {
        "type": "graded_relevance",
        "allowed_values": [0, 1, 2],
        "version": "query_relevance_0_1_2_v1",
    }:
        raise ValueError("benchmark label_scheme 必须显式 version 的 0/1/2 graded relevance。")
    if payload["record_unit"] != "topic_id + pool_item_id":
        raise ValueError("benchmark record_unit 非法。")
    _require_nonempty_string(payload["entity_policy"], "benchmark entity_policy")
    reference_year = payload["reference_year"]
    if isinstance(reference_year, bool) or not isinstance(reference_year, int):
        raise ValueError("benchmark reference_year 必须是 integer。")
    ref_names = (
        "topic_set",
        "split",
        "candidate_pool",
        "canonical_entities",
        "annotations",
        "reviews",
        "hidden_label_anchor",
    )
    for name in ref_names:
        _validate_registry_reference(payload[name], registry, f"benchmark.{name}")
    counts = _require_mapping_value(payload["counts"], "benchmark counts")
    expected_counts = {
        "topic_count": len(topics),
        "dev_topic_count": len(split_sets["dev"]),
        "hidden_test_topic_count": len(split_sets["hidden"]),
        "pool_item_count": len(pool_members),
        "canonical_entity_count": len(canonical["entities"]),
        "public_annotation_count": len(annotations),
        "public_review_count": len(reviews),
    }
    if counts != expected_counts:
        raise ValueError("benchmark counts 与绑定 artifacts 不一致。")
    hidden_annotations = sorted(
        annotation["annotation_id"]
        for annotation in annotations.values()
        if annotation["topic_id"] not in split_sets["dev"]
    )
    if hidden_annotations:
        raise ValueError(
            "公开 benchmark annotations 不得暴露 hidden-test labels："
            + ", ".join(hidden_annotations)
            + "。"
        )
    if payload["benchmark_identity"] != compute_benchmark_identity(payload):
        raise ValueError("benchmark identity/hash mismatch。")
    _validate_provenance(payload["generation_provenance"], "benchmark generation provenance")
    review = _require_mapping_value(payload["review_provenance"], "benchmark review provenance")
    _require_exact_fields(review, {"status", "reviewers", "note"}, "benchmark review provenance")
    if review["status"] not in {"not_started", "in_review", "approved"}:
        raise ValueError("benchmark review status 非法。")
    if review["status"] == "approved":
        raise ValueError("Bootstrap review provenance 不得自报 formal approved status。")
    _require_string_list(review["reviewers"], "benchmark reviewers", nonempty=False)
    if not isinstance(review["note"], str):
        raise ValueError("benchmark review note 必须是 string。")


def validate_artifact_identity_reference(value: Any, label: str) -> dict[str, str]:
    reference = _require_mapping_value(value, label)
    _require_exact_fields(reference, {"artifact_id", "sha256"}, label)
    _require_id(reference["artifact_id"], f"{label}.artifact_id")
    _require_sha256(reference["sha256"], f"{label}.sha256")
    return reference


def load_w6_bootstrap_bundle_inventory(
    manifest_path: str | Path,
) -> dict[str, Any]:
    """Validate and load the public W6 manifest, artifact roster, and hashes."""
    bundle_path = Path(manifest_path).resolve()
    bundle_dir = bundle_path.parent
    manifest = load_json_object(bundle_path, label="W6 bundle manifest")
    _require_exact_fields(
        manifest,
        {
            "schema_version",
            "contract_name",
            "contract_version",
            "bundle_id",
            "is_fixture",
            "created_at",
            "artifacts",
            "parallel_development",
        },
        "W6 bundle manifest",
    )
    if manifest["schema_version"] != W6_SCHEMA_VERSION:
        raise ValueError("W6 bundle schema_version 非法。")
    if manifest["contract_name"] != W6_CONTRACT_NAME or manifest["contract_version"] != W6_CONTRACT_VERSION:
        raise ValueError("W6 bundle contract name/version 非法。")
    _require_id(manifest["bundle_id"], "bundle_id")
    if manifest["is_fixture"] is not True:
        raise ValueError("Bootstrap bundle 必须明确标记 synthetic fixture。")
    _require_datetime(manifest["created_at"], "bundle created_at")
    artifact_refs = _require_mapping_value(manifest["artifacts"], "bundle artifacts")
    required_artifacts = set().union(*PARALLEL_MODULE_FIXTURE_REQUIREMENTS.values())
    if set(artifact_refs) != required_artifacts:
        missing = sorted(required_artifacts.difference(artifact_refs))
        extra = sorted(set(artifact_refs).difference(required_artifacts))
        raise ValueError(f"W6 bundle artifacts 不完整：missing={missing}, extra={extra}。")

    registry: dict[str, dict[str, str]] = {}
    payloads: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    for name, raw_reference in artifact_refs.items():
        reference = _require_mapping_value(raw_reference, f"bundle artifact {name}")
        _require_exact_fields(reference, {"artifact_id", "path", "sha256"}, f"bundle artifact {name}")
        artifact_id = _require_id(reference["artifact_id"], f"bundle {name}.artifact_id")
        _require_sha256(reference["sha256"], f"bundle {name}.sha256")
        artifact_path = _resolve_within(reference["path"], base=bundle_dir, root=bundle_dir)
        if sha256_file(artifact_path) != reference["sha256"]:
            raise ValueError(f"bundle artifact {name} manifest hash mismatch。")
        if artifact_id in registry:
            raise ValueError(f"bundle duplicate artifact_id：{artifact_id}。")
        registry[artifact_id] = {"artifact_id": artifact_id, "sha256": reference["sha256"]}
        paths[name] = artifact_path
        if artifact_path.suffix.lower() == ".json":
            payload = load_json_object(artifact_path, label=f"bundle artifact {name}")
            if payload.get("artifact_id") != artifact_id:
                raise ValueError(f"bundle artifact {name} identity mismatch。")
            payloads[name] = payload

    return {
        "manifest_path": bundle_path,
        "bundle_dir": bundle_dir,
        "manifest": manifest,
        "registry": registry,
        "payloads": payloads,
        "paths": paths,
    }


def validate_w6_bootstrap_bundle(
    manifest_path: str | Path,
) -> dict[str, Any]:
    """Validate the complete public W6 Bootstrap fixture bundle."""
    inventory = load_w6_bootstrap_bundle_inventory(manifest_path)
    manifest = inventory["manifest"]
    registry = inventory["registry"]
    payloads = inventory["payloads"]
    paths = inventory["paths"]
    artifact_refs = manifest["artifacts"]

    parallel = _require_mapping_value(manifest["parallel_development"], "parallel_development")
    if set(parallel) != set(PARALLEL_MODULE_FIXTURE_REQUIREMENTS):
        raise ValueError("parallel_development 必须覆盖六个公共任务槽位。")
    for module_name, requirements in PARALLEL_MODULE_FIXTURE_REQUIREMENTS.items():
        entry = _require_mapping_value(parallel[module_name], f"parallel module {module_name}")
        _require_exact_fields(entry, {"depends_on", "artifacts"}, f"parallel module {module_name}")
        if entry["depends_on"] != ["w6_bootstrap"]:
            raise ValueError(f"{module_name} 不得依赖其他成员尚未合并的 PR/artifact。")
        declared_names = set(
            _require_string_list(entry["artifacts"], f"{module_name}.artifacts", nonempty=True)
        )
        if declared_names != requirements:
            raise ValueError(f"{module_name} fixture dependency matrix 漂移。")
        if not declared_names <= set(artifact_refs):
            raise ValueError(f"{module_name} 引用不存在的 Bootstrap artifact。")

    topics = validate_topic_set(payloads["topic_set"])
    retrieval = validate_retrieval_provenance(
        payloads["retrieval_provenance"], topics=topics
    )
    records = validate_source_records(
        payloads["source_records"], topics=topics, retrieval=retrieval
    )
    canonical = validate_canonical_entities(
        payloads["canonical_entities"], records=records, retrieval=retrieval
    )
    precanonical_pool_members = validate_candidate_pool(
        payloads["precanonical_candidate_pool"],
        topics=topics,
        records=records,
        retrieval=retrieval,
        registry=registry,
    )
    pool_members = validate_candidate_pool(
        payloads["candidate_pool"],
        topics=topics,
        records=records,
        retrieval=retrieval,
        registry=registry,
        canonical=canonical,
    )
    task_mappings = validate_annotation_task_map(
        payloads["annotation_task_map"],
        records=records,
        pool_members=pool_members,
        registry=registry,
    )
    tasks = validate_blind_annotation_tasks(
        payloads["annotation_tasks"],
        topics=topics,
        records=records,
        task_mappings=task_mappings,
        registry=registry,
    )
    split_sets = validate_topic_split(payloads["split_manifest"], topics=topics)
    _validate_registry_reference(payloads["split_manifest"]["topic_set"], registry, "split.topic_set")
    annotations = validate_annotation_results(
        payloads["annotation_results"],
        tasks=tasks,
        task_mappings=task_mappings,
        split=payloads["split_manifest"],
        split_sets=split_sets,
        registry=registry,
    )
    reviews = validate_annotation_reviews(
        payloads["annotation_reviews"], annotations=annotations
    )
    validate_hidden_label_anchor(
        payloads["hidden_label_anchor"],
        split=payloads["split_manifest"],
        split_sets=split_sets,
        registry=registry,
    )

    # Local imports avoid a circular dependency: method/synthesis validators reuse
    # the generic reference and identity helpers defined above.
    from src.w6_method_contract import validate_w6_method_package
    from src.w6_synthesis_contract import (
        validate_evidence_units,
        validate_structured_synthesis,
        validate_synthesis_input,
    )

    method_packages: dict[str, dict[str, Any]] = {}
    for name in ("method_sparse_manifest", "method_dense_manifest"):
        validated = validate_w6_method_package(
            paths[name],
            artifact_registry=registry,
            pool_members=pool_members,
            known_method_packages=method_packages,
        )
        method_packages[validated["artifact_id"]] = validated
    fusion = validate_w6_method_package(
        paths["method_fusion_manifest"],
        artifact_registry=registry,
        pool_members=pool_members,
        known_method_packages=method_packages,
    )
    method_packages[fusion["artifact_id"]] = fusion
    evidence = validate_evidence_units(
        payloads["evidence_units"], records=records, canonical=canonical
    )
    synthesis_input = validate_synthesis_input(
        payloads["synthesis_input"],
        registry=registry,
        topics=topics,
        pool_members=pool_members,
        method_packages=method_packages,
        records=records,
        canonical=canonical,
        evidence=evidence,
        expected_artifact_ids={
            "topic_set": payloads["topic_set"]["artifact_id"],
            "source_records": payloads["source_records"]["artifact_id"],
            "retrieval_provenance": payloads["retrieval_provenance"]["artifact_id"],
            "evidence_units": payloads["evidence_units"]["artifact_id"],
        },
    )
    validate_structured_synthesis(
        payloads["structured_synthesis"],
        synthesis_input=synthesis_input,
        evidence=evidence,
        canonical=canonical,
    )
    validate_benchmark_manifest(
        payloads["benchmark_manifest"],
        registry=registry,
        topics=topics,
        pool_members=pool_members,
        canonical=canonical,
        annotations=annotations,
        reviews=reviews,
        split_sets=split_sets,
    )
    return {
        "manifest": manifest,
        "registry": registry,
        "paths": paths,
        "payloads": payloads,
        "topics": topics,
        "retrieval": retrieval,
        "records": records,
        "canonical": canonical,
        "precanonical_pool_members": precanonical_pool_members,
        "pool_members": pool_members,
        "annotation_task_mappings": task_mappings,
        "annotation_tasks": tasks,
        "annotations": annotations,
        "reviews": reviews,
        "split_sets": split_sets,
        "method_packages": method_packages,
        "evidence_units": evidence,
        "synthesis_input": synthesis_input,
    }


def normalize_doi(value: Any) -> str:
    text = str(value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text


def normalize_openalex_id(value: Any) -> str:
    text = str(value or "").strip()
    return text.rstrip("/").rsplit("/", 1)[-1].upper()


def normalize_title(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _validate_registry_reference(
    value: Any, registry: Mapping[str, dict[str, str]], label: str
) -> dict[str, str]:
    reference = validate_artifact_identity_reference(value, label)
    trusted = registry.get(reference["artifact_id"])
    if trusted is None or trusted["sha256"] != reference["sha256"]:
        raise ValueError(f"{label} artifact identity/hash drift。")
    return reference


def _validate_annotation_provenance(value: Any, annotation_id: str) -> dict[str, Any]:
    provenance = _require_mapping_value(value, f"{annotation_id}.annotation_provenance")
    _require_exact_fields(
        provenance,
        {
            "actor_type",
            "actor_id",
            "model_or_tool",
            "prompt_or_protocol_version",
            "created_at",
            "evidence_lookup_performed",
        },
        "annotation provenance",
    )
    if provenance["actor_type"] not in {"ai_assistant", "human", "ai_assisted_human"}:
        raise ValueError(f"annotation {annotation_id} actor_type 非法。")
    _require_nonempty_string(provenance["actor_id"], "annotation actor_id")
    tool = provenance["model_or_tool"]
    if provenance["actor_type"] in {"ai_assistant", "ai_assisted_human"}:
        tool_mapping = _require_mapping_value(tool, "annotation model_or_tool")
        _require_exact_fields(tool_mapping, {"name", "version"}, "annotation model_or_tool")
        _require_nonempty_string(tool_mapping["name"], "annotation tool name")
        _require_nonempty_string(tool_mapping["version"], "annotation tool version")
    elif tool is not None:
        raise ValueError("pure human annotation 的 model_or_tool 必须是 null。")
    _require_nonempty_string(
        provenance["prompt_or_protocol_version"], "annotation prompt/protocol version"
    )
    _require_datetime(provenance["created_at"], "annotation created_at")
    if not isinstance(provenance["evidence_lookup_performed"], bool):
        raise ValueError("evidence_lookup_performed 必须是 boolean。")
    return provenance


def _validate_canonicalization_provenance(value: Any, entity_id: str) -> None:
    provenance = _require_mapping_value(value, f"{entity_id}.canonicalization_provenance")
    _require_exact_fields(
        provenance,
        {"tool", "version", "created_at", "git_revision", "reviewer"},
        "canonicalization provenance",
    )
    _require_nonempty_string(provenance["tool"], "canonicalization tool")
    _require_nonempty_string(provenance["version"], "canonicalization version")
    _require_datetime(provenance["created_at"], "canonicalization created_at")
    _require_git_revision(provenance["git_revision"], "canonicalization git_revision")
    if provenance["reviewer"] is not None:
        _require_nonempty_string(provenance["reviewer"], "canonicalization reviewer")


def _validate_provenance(value: Any, label: str) -> None:
    provenance = _require_mapping_value(value, label)
    _require_exact_fields(
        provenance, {"kind", "created_by", "created_at", "git_revision"}, label
    )
    _require_nonempty_string(provenance["kind"], f"{label}.kind")
    _require_nonempty_string(provenance["created_by"], f"{label}.created_by")
    _require_datetime(provenance["created_at"], f"{label}.created_at")
    _require_git_revision(provenance["git_revision"], f"{label}.git_revision")


def _require_w6_header(payload: Mapping[str, Any], artifact_type: str) -> None:
    if payload.get("schema_version") != W6_SCHEMA_VERSION:
        raise ValueError(f"{artifact_type} schema_version 必须是 {W6_SCHEMA_VERSION}。")
    if payload.get("artifact_type") != artifact_type:
        raise ValueError(f"artifact_type 必须是 {artifact_type}。")
    _require_id(payload.get("artifact_id"), f"{artifact_type}.artifact_id")
    if not isinstance(payload.get("is_fixture"), bool):
        raise ValueError(f"{artifact_type}.is_fixture 必须是 boolean。")


def _resolve_within(value: Any, *, base: Path, root: Path) -> Path:
    text = str(value or "").strip()
    if not text or Path(text).is_absolute():
        raise ValueError("artifact path 必须是 bundle 内相对路径。")
    resolved = (base / text).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("artifact path 不得离开 bundle。") from error
    if not resolved.is_file():
        raise ValueError(f"artifact file 不存在：{resolved}")
    return resolved


def _find_forbidden_keys(value: Any, forbidden: Iterable[str]) -> set[str]:
    forbidden_set = set(forbidden)
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in forbidden_set:
                found.add(key)
            found.update(_find_forbidden_keys(child, forbidden_set))
    elif isinstance(value, list):
        for child in value:
            found.update(_find_forbidden_keys(child, forbidden_set))
    return found


def _require_exact_fields(payload: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected.difference(actual))
        extra = sorted(actual.difference(expected))
        raise ValueError(f"{label} 字段不符合 contract：missing={missing}, extra={extra}。")


def _require_mapping_value(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON object。")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是 JSON array。")
    return value


def _require_nonempty_list(value: Any, label: str) -> list[Any]:
    items = _require_list(value, label)
    if not items:
        raise ValueError(f"{label} 不能为空。")
    return items


def _require_string_list(value: Any, label: str, *, nonempty: bool) -> list[str]:
    items = _require_list(value, label)
    if nonempty and not items:
        raise ValueError(f"{label} 不能为空。")
    if any(not isinstance(item, str) or not item.strip() or item != item.strip() for item in items):
        raise ValueError(f"{label} 必须只包含无首尾空白的非空字符串。")
    return items


def _require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} 必须是无首尾空白的非空字符串。")
    return value


def _require_id(value: Any, label: str) -> str:
    text = _require_nonempty_string(value, label)
    if not ID_PATTERN.fullmatch(text):
        raise ValueError(f"{label} 必须是稳定的小写机器标识。")
    return text


def _require_sha256(value: Any, label: str) -> str:
    text = str(value or "")
    if not SHA256_PATTERN.fullmatch(text):
        raise ValueError(f"{label} 必须是 64 位小写 SHA-256。")
    return text


def _require_git_revision(value: Any, label: str) -> str:
    text = str(value or "")
    if not GIT_REVISION_PATTERN.fullmatch(text):
        raise ValueError(f"{label} 必须是 40 位小写 Git SHA。")
    return text


def _require_datetime(value: Any, label: str) -> None:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{label} 必须是 ISO-8601 时间。") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} 必须包含时区。")
