"""W6 post-freeze OpenAlex multi-query acquisition and label-free audit.

This module deliberately sits outside the frozen Topic contract and the W6
benchmark/ranking paths.  It validates a separately frozen query design,
captures compact public OpenAlex metadata, deduplicates only by exact normalized
OpenAlex Work ID, preserves every query hit, and derives descriptive robustness
statistics without reading labels, judgements, rankings, or evaluation metrics.
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from src.annotation_tasks import sha256_file
from src.openalex_client_v2 import fetch_openalex_papers_v2
from src.utils import current_timestamp
from src.w6_artifact_safety import ensure_output_separate_from_inputs
from src.w6_contracts import (
    deterministic_identity,
    load_json_object,
    normalize_openalex_id,
)


QUERY_CONFIG_IDENTITY_PREFIX = "w6-openalex-query-audit-config"
ACQUISITION_IDENTITY_PREFIX = "w6-openalex-acquisition"
HIT_IDENTITY_PREFIX = "w6-openalex-hit"
EXPECTED_TOPIC_COUNT = 9
ALLOWED_QUERY_COUNT_RANGE = range(5, 9)
PACKAGE_FILES = (
    "works.jsonl",
    "query_hits.jsonl",
    "query_runs.json",
    "topic_audit.json",
    "topic_audit.md",
)
AUTHENTICATION_SOURCES = {
    "process_environment",
    "windows_user_environment",
    "windows_machine_environment",
}


def resolve_openalex_api_key(
    *,
    getenv: Callable[[str, str], str | None] | None = None,
    windows_reader: Callable[[str], str | None] | None = None,
) -> tuple[str, str]:
    """Resolve only OPENALEX_API_KEY without dotenv, logging, or broad secret scans."""

    environment_get = getenv or os.getenv
    process_value = environment_get("OPENALEX_API_KEY", "")
    if isinstance(process_value, str) and process_value.strip():
        return process_value.strip(), "process_environment"
    if os.name != "nt" and windows_reader is None:
        return "", "unavailable"
    reader = windows_reader or _read_windows_openalex_api_key
    for scope, source in (
        ("user", "windows_user_environment"),
        ("machine", "windows_machine_environment"),
    ):
        value = reader(scope)
        if isinstance(value, str) and value.strip():
            return value.strip(), source
    return "", "unavailable"


def compute_query_config_identity(config: Mapping[str, Any]) -> str:
    """Compute the stable identity while excluding the identity field itself."""

    payload = {key: value for key, value in config.items() if key != "config_identity"}
    return deterministic_identity(QUERY_CONFIG_IDENTITY_PREFIX, payload)


def load_and_validate_query_config(
    config_path: str | Path,
    *,
    topic_set_path: str | Path,
    split_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load the three public artifacts and enforce their frozen bindings."""

    config_file = Path(config_path)
    topic_file = Path(topic_set_path)
    split_file = Path(split_path)
    config = load_json_object(config_file, label="OpenAlex query audit config")
    topic_set = load_json_object(topic_file, label="W6 Topic Set")
    split = load_json_object(split_file, label="W6 split manifest")
    validate_query_config(
        config,
        topic_set=topic_set,
        topic_set_sha256=sha256_file(topic_file),
        split=split,
        split_sha256=sha256_file(split_file),
    )
    return config, topic_set, split


def validate_query_config(
    config: Mapping[str, Any],
    *,
    topic_set: Mapping[str, Any],
    topic_set_sha256: str,
    split: Mapping[str, Any],
    split_sha256: str,
) -> None:
    """Reject drift, adaptive designs, label access, and malformed queries."""

    if config.get("artifact_type") != "w6_post_freeze_openalex_query_audit_config":
        raise ValueError("query audit config artifact_type 无效。")
    if config.get("status") != "frozen" or config.get("is_fixture") is not False:
        raise ValueError("query audit config 必须是真实 frozen artifact。")
    if config.get("post_freeze_audit") is not True:
        raise ValueError("query audit config 必须显式声明 post_freeze_audit=true。")
    if config.get("frozen_before_acquisition") is not True:
        raise ValueError("query audit config 必须在 acquisition 前冻结。")
    expected_identity = compute_query_config_identity(config)
    if config.get("config_identity") != expected_identity:
        raise ValueError("query audit config identity/hash drift。")

    topic_reference = _require_mapping(config.get("topic_set_reference"), "topic_set_reference")
    if topic_reference.get("artifact_id") != topic_set.get("artifact_id"):
        raise ValueError("query config 绑定的 Topic Set artifact_id 不匹配。")
    if str(topic_reference.get("sha256", "")).lower() != topic_set_sha256.lower():
        raise ValueError("query config 绑定的 Topic Set sha256 不匹配。")
    if topic_set.get("status") != "frozen" or topic_set.get("is_fixture") is not False:
        raise ValueError("Topic Set 必须是真实 frozen artifact。")

    split_reference = _require_mapping(config.get("split_reference"), "split_reference")
    if split_reference.get("artifact_id") != split.get("artifact_id"):
        raise ValueError("query config 绑定的 split artifact_id 不匹配。")
    if split_reference.get("split_identity") != split.get("split_identity"):
        raise ValueError("query config 绑定的 split identity 不匹配。")
    if str(split_reference.get("sha256", "")).lower() != split_sha256.lower():
        raise ValueError("query config 绑定的 split sha256 不匹配。")
    if split.get("status") != "frozen" or split.get("reveal_state") != "sealed":
        raise ValueError("W6 split 必须保持 frozen/sealed。")

    policy = _require_mapping(config.get("acquisition_policy"), "acquisition_policy")
    if policy.get("provider") != "OpenAlex" or policy.get("entity") != "works":
        raise ValueError("query audit 只允许 OpenAlex works。")
    if policy.get("operation") != "search":
        raise ValueError("query audit 必须使用 OpenAlex works search。")
    if policy.get("labels_allowed") is not False:
        raise ValueError("query audit 必须保持 label-free。")
    if policy.get("adaptive_query_tuning_after_results") is not False:
        raise ValueError("query audit 禁止按结果自适应调 query。")
    if policy.get("retrieval_evaluation") is not False:
        raise ValueError("query audit 不是 retrieval evaluation。")
    if policy.get("deduplication") != "exact normalized OpenAlex Work ID only":
        raise ValueError("query audit 只允许 exact OpenAlex Work ID dedup。")
    if policy.get("preserve_all_query_hits") is not True:
        raise ValueError("query audit 必须保留全部 query hit provenance。")
    max_results = _require_int(policy.get("max_results_per_query"), "max_results_per_query")
    if not 1 <= max_results <= 100:
        raise ValueError("max_results_per_query 必须在 1..100，保持单页 bounded query。")
    from_year = _require_int(policy.get("from_year"), "from_year")
    to_year = _require_int(policy.get("to_year"), "to_year")
    if from_year > to_year:
        raise ValueError("acquisition year range 无效。")
    configured_query_count = _require_int(
        policy.get("query_variants_per_topic"), "query_variants_per_topic"
    )
    if configured_query_count not in ALLOWED_QUERY_COUNT_RANGE:
        raise ValueError("每个 Topic 必须冻结 5–8 个 query variants。")
    targets = _require_mapping(
        policy.get("target_unique_works_per_topic"),
        "target_unique_works_per_topic",
    )
    minimum = _require_int(targets.get("minimum"), "target minimum")
    preferred_maximum = _require_int(
        targets.get("preferred_maximum"), "target preferred_maximum"
    )
    soft_cap = _require_int(targets.get("soft_cap"), "target soft_cap")
    if not (0 < minimum <= preferred_maximum <= soft_cap <= 500):
        raise ValueError("per-topic target/soft-cap contract 无效。")
    if max_results * configured_query_count > soft_cap:
        raise ValueError("固定 query 上限会超过 per-topic soft cap。")

    frozen_topics = topic_set.get("topics")
    configured_topics = config.get("topics")
    if not isinstance(frozen_topics, list) or len(frozen_topics) != EXPECTED_TOPIC_COUNT:
        raise ValueError("绑定的 Topic Set 必须包含 9 个 Topic。")
    if not isinstance(configured_topics, list) or len(configured_topics) != EXPECTED_TOPIC_COUNT:
        raise ValueError("query audit config 必须完整覆盖 9 个 Topic。")
    frozen_ids = [str(topic.get("topic_id", "")) for topic in frozen_topics]
    configured_ids = [str(topic.get("topic_id", "")) for topic in configured_topics]
    if configured_ids != frozen_ids:
        raise ValueError("query audit Topic 顺序/覆盖与 frozen Topic Set 不一致。")

    all_variant_ids: set[str] = set()
    for topic in configured_topics:
        topic_id = str(topic.get("topic_id", ""))
        expected_facets = _require_string_list(
            topic.get("expected_facets"), f"{topic_id}.expected_facets"
        )
        variants = topic.get("query_variants")
        if not isinstance(variants, list) or len(variants) != configured_query_count:
            raise ValueError(f"{topic_id} query variant 数量与 frozen policy 不一致。")
        topic_texts: set[str] = set()
        covered_facets: set[str] = set()
        for variant in variants:
            if not isinstance(variant, Mapping):
                raise ValueError(f"{topic_id} query variant 必须是 object。")
            variant_id = _require_text(variant.get("query_variant_id"), "query_variant_id")
            query_text = _require_text(variant.get("query_text"), "query_text")
            rationale = _require_text(variant.get("rationale"), "rationale")
            if len(rationale) < 20:
                raise ValueError(f"{variant_id} rationale 过短。")
            if variant_id in all_variant_ids:
                raise ValueError(f"重复 query_variant_id：{variant_id}")
            if query_text.casefold() in topic_texts:
                raise ValueError(f"{topic_id} 存在重复 query_text。")
            facets = _require_string_list(
                variant.get("coverage_facets"), f"{variant_id}.coverage_facets"
            )
            unknown = set(facets) - set(expected_facets)
            if unknown:
                raise ValueError(f"{variant_id} 引用了未声明 facet：{sorted(unknown)}")
            all_variant_ids.add(variant_id)
            topic_texts.add(query_text.casefold())
            covered_facets.update(facets)
        if covered_facets != set(expected_facets):
            raise ValueError(f"{topic_id} query variants 未覆盖全部 expected facets。")

    amendments = config.get("potential_topic_amendments")
    if amendments != []:
        raise ValueError("采集前 query config 不得预设 potential_topic_amendments。")
    provenance = _require_mapping(config.get("provenance"), "provenance")
    if provenance.get("selection_labels_used") is not False:
        raise ValueError("query design provenance 必须声明未使用 labels。")
    if provenance.get("ranking_metrics_used") is not False:
        raise ValueError("query design provenance 必须声明未使用 ranking metrics。")


def acquire_and_audit(
    *,
    config_path: str | Path,
    topic_set_path: str | Path,
    split_path: str | Path,
    output_dir: str | Path,
    api_key: str,
    authentication_source: str = "process_environment",
    fetcher: Callable[..., dict[str, Any]] = fetch_openalex_papers_v2,
    timestamp_fn: Callable[[], str] = current_timestamp,
) -> dict[str, Any]:
    """Run the frozen queries and atomically materialize a compact package."""

    config_file = Path(config_path).resolve()
    topic_file = Path(topic_set_path).resolve()
    split_file = Path(split_path).resolve()
    config, topic_set, split = load_and_validate_query_config(
        config_file,
        topic_set_path=topic_file,
        split_path=split_file,
    )
    output = ensure_output_separate_from_inputs(
        output_dir,
        input_paths=[config_file, topic_file, split_file],
    )
    if output.exists():
        raise ValueError("output_dir 已存在；为保护 research evidence，拒绝覆盖。")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("OpenAlex live acquisition 需要环境变量 OPENALEX_API_KEY。")
    if authentication_source not in AUTHENTICATION_SOURCES:
        raise ValueError("OpenAlex authentication_source 无效。")

    started_at = timestamp_fn()
    acquisition_run_id = deterministic_identity(
        "w6-openalex-live-run",
        {
            "config_identity": config["config_identity"],
            "acquisition_started_at": started_at,
        },
    )
    records_by_id: dict[str, dict[str, Any]] = {}
    hits: list[dict[str, Any]] = []
    query_runs: list[dict[str, Any]] = []
    policy = config["acquisition_policy"]

    for topic in config["topics"]:
        topic_id = topic["topic_id"]
        for variant in topic["query_variants"]:
            query_run_id = deterministic_identity(
                "w6-openalex-query-run",
                {
                    "acquisition_run_id": acquisition_run_id,
                    "topic_id": topic_id,
                    "query_variant_id": variant["query_variant_id"],
                },
            )
            query_started_at = timestamp_fn()
            result = fetcher(
                variant["query_text"],
                policy["max_results_per_query"],
                from_year=policy["from_year"],
                to_year=policy["to_year"],
                api_key=api_key.strip(),
            )
            query_completed_at = timestamp_fn()
            raw_results = result.get("raw_response", {}).get("results", [])
            papers = result.get("papers", [])
            stats = result.get("stats", {})
            if not isinstance(raw_results, list) or not isinstance(papers, list):
                raise ValueError("OpenAlex client 返回了无效 results/papers。")
            paper_by_id = {
                normalize_openalex_id(paper.get("openalex_id")): paper
                for paper in papers
                if normalize_openalex_id(paper.get("openalex_id"))
            }
            skipped_missing_id = 0
            query_seen: set[str] = set()
            for source_rank, work in enumerate(raw_results, start=1):
                if not isinstance(work, Mapping):
                    raise ValueError("OpenAlex results 包含非 object 记录。")
                normalized_id = normalize_openalex_id(work.get("id"))
                if not normalized_id:
                    skipped_missing_id += 1
                    continue
                if normalized_id in query_seen:
                    raise ValueError("OpenAlex client 输出仍含 query 内重复 Work ID。")
                query_seen.add(normalized_id)
                paper = paper_by_id.get(normalized_id, {})
                record_id = f"openalex:{normalized_id}"
                hit_id = deterministic_identity(
                    HIT_IDENTITY_PREFIX,
                    {
                        "acquisition_run_id": acquisition_run_id,
                        "topic_id": topic_id,
                        "query_variant_id": variant["query_variant_id"],
                        "openalex_id": normalized_id,
                    },
                )
                hit = {
                    "hit_id": hit_id,
                    "acquisition_run_id": acquisition_run_id,
                    "query_run_id": query_run_id,
                    "record_id": record_id,
                    "openalex_id": normalized_id,
                    "topic_id": topic_id,
                    "query_variant_id": variant["query_variant_id"],
                    "source_rank": source_rank,
                }
                hits.append(hit)
                if normalized_id not in records_by_id:
                    records_by_id[normalized_id] = _normalize_work(
                        work,
                        paper=paper,
                        record_id=record_id,
                        normalized_id=normalized_id,
                        retrieved_at=started_at,
                        acquisition_run_id=acquisition_run_id,
                    )
                record = records_by_id[normalized_id]
                record["hit_ids"].append(hit_id)
                record["topic_ids"].append(topic_id)
                record["query_variant_ids"].append(variant["query_variant_id"])

            page_meta = result.get("raw_response", {}).get("page_meta", [])
            api_hit_count = None
            if isinstance(page_meta, list) and page_meta:
                first_page = page_meta[0]
                if isinstance(first_page, Mapping):
                    count = first_page.get("count")
                    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                        api_hit_count = count
            safe_stats = _safe_client_stats(stats)
            query_runs.append(
                {
                    "query_run_id": query_run_id,
                    "acquisition_run_id": acquisition_run_id,
                    "topic_id": topic_id,
                    "query_variant_id": variant["query_variant_id"],
                    "query_text": variant["query_text"],
                    "query_started_at": query_started_at,
                    "query_completed_at": query_completed_at,
                    "api_hit_count": api_hit_count,
                    "retrieved_work_count": len(query_seen),
                    "missing_openalex_id_skipped": skipped_missing_id,
                    "client_stats": safe_stats,
                }
            )

    records = []
    for normalized_id in sorted(records_by_id):
        record = records_by_id[normalized_id]
        for field in ("hit_ids", "topic_ids", "query_variant_ids"):
            record[field] = sorted(set(record[field]))
        records.append(record)
    hits.sort(key=lambda row: (row["topic_id"], row["query_variant_id"], row["source_rank"], row["openalex_id"]))
    query_runs.sort(key=lambda row: (row["topic_id"], row["query_variant_id"]))
    completed_at = timestamp_fn()
    audit = build_topic_audit(
        config=config,
        records=records,
        hits=hits,
        query_runs=query_runs,
        generated_at=completed_at,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}-staging-", dir=output.parent
    ) as temporary_directory:
        staging = Path(temporary_directory) / output.name
        staging.mkdir()
        _write_jsonl(staging / "works.jsonl", records)
        _write_jsonl(staging / "query_hits.jsonl", hits)
        _write_json(
            staging / "query_runs.json",
            {
                "schema_version": "1.0",
                "artifact_type": "w6_openalex_query_runs",
                "config_identity": config["config_identity"],
                "acquisition_run_id": acquisition_run_id,
                "acquisition_started_at": started_at,
                "acquisition_completed_at": completed_at,
                "query_count": len(query_runs),
                "runs": query_runs,
            },
        )
        _write_json(staging / "topic_audit.json", audit)
        (staging / "topic_audit.md").write_text(
            render_topic_audit_markdown(audit), encoding="utf-8", newline="\n"
        )
        file_hashes = {name: sha256_file(staging / name) for name in PACKAGE_FILES}
        acquisition_identity = deterministic_identity(
            ACQUISITION_IDENTITY_PREFIX,
            {
                "config_identity": config["config_identity"],
                "topic_set_sha256": config["topic_set_reference"]["sha256"],
                "split_identity": split["split_identity"],
                "file_hashes": file_hashes,
            },
        )
        manifest = {
            "schema_version": "1.0",
            "artifact_type": "w6_post_freeze_openalex_audit_package",
            "artifact_id": "w6_openalex_topic_robustness_audit_v1",
            "acquisition_identity": acquisition_identity,
            "acquisition_run_id": acquisition_run_id,
            "status": "complete",
            "is_fixture": False,
            "post_freeze_audit": True,
            "label_free": True,
            "retrieval_evaluation": False,
            "config_reference": {
                "artifact_id": config["artifact_id"],
                "config_identity": config["config_identity"],
                "sha256": sha256_file(config_file),
            },
            "topic_set_reference": config["topic_set_reference"],
            "split_reference": config["split_reference"],
            "acquisition_started_at": started_at,
            "acquisition_completed_at": completed_at,
            "query_count": len(query_runs),
            "unique_work_count": len(records),
            "query_hit_count": len(hits),
            "potential_topic_amendments": config["potential_topic_amendments"],
            "files": file_hashes,
            "secret_handling": {
                "api_key_received_from_environment": True,
                "authentication_source": authentication_source,
                "api_key_persisted": False,
                "dotenv_read": False,
            },
        }
        _write_json(staging / "manifest.json", manifest)
        shutil.move(str(staging), str(output))
    validate_acquisition_package(
        package_dir=output,
        config_path=config_file,
        topic_set_path=topic_file,
        split_path=split_file,
    )
    return manifest


def validate_acquisition_package(
    *,
    package_dir: str | Path,
    config_path: str | Path,
    topic_set_path: str | Path,
    split_path: str | Path,
) -> dict[str, Any]:
    """Validate hashes, identities, exact-ID records, and hit closure."""

    package = Path(package_dir)
    config, _, split = load_and_validate_query_config(
        config_path,
        topic_set_path=topic_set_path,
        split_path=split_path,
    )
    manifest = load_json_object(package / "manifest.json", label="OpenAlex audit manifest")
    if manifest.get("artifact_type") != "w6_post_freeze_openalex_audit_package":
        raise ValueError("OpenAlex audit manifest artifact_type 无效。")
    if manifest.get("status") != "complete" or manifest.get("is_fixture") is not False:
        raise ValueError("OpenAlex audit package 必须是真实 complete artifact。")
    if manifest.get("label_free") is not True or manifest.get("retrieval_evaluation") is not False:
        raise ValueError("OpenAlex audit package label-free boundary 无效。")
    config_reference = _require_mapping(manifest.get("config_reference"), "config_reference")
    if config_reference.get("config_identity") != config["config_identity"]:
        raise ValueError("OpenAlex audit package config identity drift。")
    if str(config_reference.get("sha256", "")).lower() != sha256_file(Path(config_path)).lower():
        raise ValueError("OpenAlex audit package config hash drift。")
    if manifest.get("topic_set_reference") != config["topic_set_reference"]:
        raise ValueError("OpenAlex audit package Topic binding drift。")
    if manifest.get("split_reference") != config["split_reference"]:
        raise ValueError("OpenAlex audit package split binding drift。")
    secret_handling = _require_mapping(manifest.get("secret_handling"), "secret_handling")
    if secret_handling.get("api_key_received_from_environment") is not True:
        raise ValueError("OpenAlex audit package environment authentication drift。")
    if secret_handling.get("authentication_source") not in AUTHENTICATION_SOURCES:
        raise ValueError("OpenAlex audit package authentication source drift。")
    if secret_handling.get("api_key_persisted") is not False:
        raise ValueError("OpenAlex audit package secret persistence drift。")
    if secret_handling.get("dotenv_read") is not False or len(secret_handling) != 4:
        raise ValueError("OpenAlex audit package secret-handling declaration drift。")

    file_hashes = _require_mapping(manifest.get("files"), "files")
    if set(file_hashes) != set(PACKAGE_FILES):
        raise ValueError("OpenAlex audit package file closure 不完整。")
    for name in PACKAGE_FILES:
        if str(file_hashes[name]).lower() != sha256_file(package / name).lower():
            raise ValueError(f"OpenAlex audit package file hash drift：{name}")
    expected_identity = deterministic_identity(
        ACQUISITION_IDENTITY_PREFIX,
        {
            "config_identity": config["config_identity"],
            "topic_set_sha256": config["topic_set_reference"]["sha256"],
            "split_identity": split["split_identity"],
            "file_hashes": dict(file_hashes),
        },
    )
    if manifest.get("acquisition_identity") != expected_identity:
        raise ValueError("OpenAlex acquisition identity drift。")

    records = _read_jsonl(package / "works.jsonl")
    hits = _read_jsonl(package / "query_hits.jsonl")
    query_runs = load_json_object(package / "query_runs.json", label="query runs")
    audit = load_json_object(package / "topic_audit.json", label="topic audit")
    record_ids = [row.get("record_id") for row in records]
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("works.jsonl 包含重复 record_id。")
    normalized_ids = [row.get("openalex_id") for row in records]
    if any(not value or normalize_openalex_id(value) != value for value in normalized_ids):
        raise ValueError("works.jsonl 包含非规范 OpenAlex Work ID。")
    if len(normalized_ids) != len(set(normalized_ids)):
        raise ValueError("works.jsonl 包含重复 OpenAlex Work ID。")
    acquisition_run_id = manifest.get("acquisition_run_id")
    if not isinstance(acquisition_run_id, str) or not acquisition_run_id:
        raise ValueError("manifest 缺少 acquisition_run_id。")
    if any(row.get("acquisition_run_id") != acquisition_run_id for row in records):
        raise ValueError("works.jsonl acquisition_run_id drift。")
    required_record_fields = {
        "publication_date",
        "work_type",
        "openalex_url",
        "hit_ids",
        "topic_ids",
        "query_variant_ids",
    }
    if any(not required_record_fields.issubset(row) for row in records):
        raise ValueError("works.jsonl 缺少 compact metadata/provenance fields。")
    record_id_set = set(record_ids)
    hit_ids = [row.get("hit_id") for row in hits]
    if len(hit_ids) != len(set(hit_ids)):
        raise ValueError("query_hits.jsonl 包含重复 hit_id。")
    if any(row.get("record_id") not in record_id_set for row in hits):
        raise ValueError("query hit 引用了不存在的 record。")
    if any(row.get("acquisition_run_id") != acquisition_run_id for row in hits):
        raise ValueError("query_hits.jsonl acquisition_run_id drift。")
    if manifest.get("unique_work_count") != len(records):
        raise ValueError("manifest unique_work_count drift。")
    if manifest.get("query_hit_count") != len(hits):
        raise ValueError("manifest query_hit_count drift。")
    runs = query_runs.get("runs")
    if not isinstance(runs, list) or manifest.get("query_count") != len(runs):
        raise ValueError("manifest/query_runs query_count drift。")
    if query_runs.get("acquisition_run_id") != acquisition_run_id:
        raise ValueError("query_runs acquisition_run_id drift。")
    run_ids = {row.get("query_run_id") for row in runs}
    if len(run_ids) != len(runs) or None in run_ids:
        raise ValueError("query_runs query_run_id 不唯一或缺失。")
    if any(row.get("acquisition_run_id") != acquisition_run_id for row in runs):
        raise ValueError("query run acquisition_run_id drift。")
    if any(row.get("query_run_id") not in run_ids for row in hits):
        raise ValueError("query hit 引用了不存在的 query_run_id。")
    hits_by_record: dict[str, set[str]] = defaultdict(set)
    for hit in hits:
        hits_by_record[str(hit["record_id"])].add(str(hit["hit_id"]))
    for record in records:
        if set(record.get("hit_ids", [])) != hits_by_record[str(record["record_id"])]:
            raise ValueError("work record/query hit provenance closure drift。")
    if audit.get("config_identity") != config["config_identity"]:
        raise ValueError("topic audit config identity drift。")
    if audit.get("global_summary", {}).get("unique_work_count") != len(records):
        raise ValueError("topic audit unique_work_count drift。")
    return manifest


def refresh_acquisition_audit(
    *,
    package_dir: str | Path,
    config_path: str | Path,
    topic_set_path: str | Path,
    split_path: str | Path,
) -> dict[str, Any]:
    """Rebuild only derived audit files from a validated captured corpus."""

    package = Path(package_dir)
    manifest = validate_acquisition_package(
        package_dir=package,
        config_path=config_path,
        topic_set_path=topic_set_path,
        split_path=split_path,
    )
    config, _, split = load_and_validate_query_config(
        config_path,
        topic_set_path=topic_set_path,
        split_path=split_path,
    )
    records = _read_jsonl(package / "works.jsonl")
    hits = _read_jsonl(package / "query_hits.jsonl")
    query_runs_artifact = load_json_object(
        package / "query_runs.json", label="query runs"
    )
    audit = build_topic_audit(
        config=config,
        records=records,
        hits=hits,
        query_runs=query_runs_artifact["runs"],
        generated_at=query_runs_artifact["acquisition_completed_at"],
    )
    with tempfile.TemporaryDirectory(
        prefix=f".{package.name}-audit-refresh-", dir=package.parent
    ) as temporary_directory:
        staging = Path(temporary_directory)
        _write_json(staging / "topic_audit.json", audit)
        (staging / "topic_audit.md").write_text(
            render_topic_audit_markdown(audit), encoding="utf-8", newline="\n"
        )
        file_hashes = dict(manifest["files"])
        for name in ("topic_audit.json", "topic_audit.md"):
            file_hashes[name] = sha256_file(staging / name)
        refreshed_manifest = dict(manifest)
        refreshed_manifest["files"] = file_hashes
        refreshed_manifest["acquisition_identity"] = deterministic_identity(
            ACQUISITION_IDENTITY_PREFIX,
            {
                "config_identity": config["config_identity"],
                "topic_set_sha256": config["topic_set_reference"]["sha256"],
                "split_identity": split["split_identity"],
                "file_hashes": file_hashes,
            },
        )
        _write_json(staging / "manifest.json", refreshed_manifest)
        for name in ("topic_audit.json", "topic_audit.md", "manifest.json"):
            os.replace(staging / name, package / name)
    return validate_acquisition_package(
        package_dir=package,
        config_path=config_path,
        topic_set_path=topic_set_path,
        split_path=split_path,
    )


def build_topic_audit(
    *,
    config: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    hits: Sequence[Mapping[str, Any]],
    query_runs: Sequence[Mapping[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    """Derive deterministic descriptive statistics from label-free hit sets."""

    record_by_id = {str(row["record_id"]): row for row in records}
    hits_by_topic_query: dict[tuple[str, str], set[str]] = defaultdict(set)
    for hit in hits:
        hits_by_topic_query[(str(hit["topic_id"]), str(hit["query_variant_id"]))].add(
            str(hit["record_id"])
        )
    run_by_key = {
        (str(run["topic_id"]), str(run["query_variant_id"])): run
        for run in query_runs
    }
    topic_audits: list[dict[str, Any]] = []
    topic_sets: dict[str, set[str]] = {}
    targets = config["acquisition_policy"]["target_unique_works_per_topic"]

    for topic in config["topics"]:
        topic_id = topic["topic_id"]
        variants = topic["query_variants"]
        query_sets = {
            variant["query_variant_id"]: hits_by_topic_query[
                (topic_id, variant["query_variant_id"])
            ]
            for variant in variants
        }
        union = set().union(*query_sets.values()) if query_sets else set()
        topic_sets[topic_id] = union
        support_counts = Counter(
            record_id
            for members in query_sets.values()
            for record_id in members
        )
        query_rows = []
        for variant in variants:
            variant_id = variant["query_variant_id"]
            members = query_sets[variant_id]
            other_union = set().union(
                *(value for key, value in query_sets.items() if key != variant_id)
            )
            run = run_by_key[(topic_id, variant_id)]
            query_rows.append(
                {
                    "query_variant_id": variant_id,
                    "query_text": variant["query_text"],
                    "coverage_facets": variant["coverage_facets"],
                    "api_hit_count": run.get("api_hit_count"),
                    "retrieved_work_count": len(members),
                    "unique_contribution_count": len(members - other_union),
                    "unique_contribution_ratio": _ratio(
                        len(members - other_union), len(members)
                    ),
                    "union_coverage_ratio": _ratio(len(members), len(union)),
                }
            )
        pairwise = []
        for index, left in enumerate(variants):
            left_id = left["query_variant_id"]
            for right in variants[index + 1 :]:
                right_id = right["query_variant_id"]
                left_set = query_sets[left_id]
                right_set = query_sets[right_id]
                intersection = left_set & right_set
                pair_union = left_set | right_set
                pairwise.append(
                    {
                        "left_query_variant_id": left_id,
                        "right_query_variant_id": right_id,
                        "intersection_count": len(intersection),
                        "union_count": len(pair_union),
                        "jaccard": _ratio(len(intersection), len(pair_union)),
                        "left_overlap_ratio": _ratio(len(intersection), len(left_set)),
                        "right_overlap_ratio": _ratio(len(intersection), len(right_set)),
                    }
                )
        topic_records = [record_by_id[record_id] for record_id in sorted(union)]
        year_distribution = Counter(
            str(record.get("publication_year"))
            if isinstance(record.get("publication_year"), int)
            else "missing"
            for record in topic_records
        )
        metadata_fields = (
            "title",
            "abstract",
            "doi",
            "authors",
            "publication_year",
            "source_name",
            "landing_page_url",
            "publication_date",
            "work_type",
            "openalex_url",
        )
        metadata = {}
        for field in metadata_fields:
            present = sum(_metadata_present(record.get(field)) for record in topic_records)
            metadata[field] = {
                "present_count": present,
                "missing_count": len(topic_records) - present,
                "completeness_ratio": _ratio(present, len(topic_records)),
            }
        support_distribution = Counter(support_counts.values())
        known_years = sorted(
            int(record["publication_year"])
            for record in topic_records
            if isinstance(record.get("publication_year"), int)
        )
        year_bins = _publication_year_bins(
            known_years,
            from_year=config["acquisition_policy"]["from_year"],
            to_year=config["acquisition_policy"]["to_year"],
            missing_count=len(topic_records) - len(known_years),
        )
        representatives = sorted(
            topic_records,
            key=lambda record: (
                -support_counts[str(record["record_id"])],
                -_sortable_int(record.get("cited_by_count")),
                -_sortable_int(record.get("publication_year")),
                str(record["openalex_id"]),
            ),
        )[:5]
        risks: list[str] = []
        if len(union) < targets["minimum"]:
            risks.append("below_target_unique_work_count")
        if len(union) > targets["soft_cap"]:
            risks.append("above_soft_cap_unique_work_count")
        if any(row["retrieved_work_count"] == 0 for row in query_rows):
            risks.append("zero_result_query_variant")
        if topic_records and metadata["abstract"]["completeness_ratio"] < 0.5:
            risks.append("abstract_completeness_below_0.5")
        if any(row["jaccard"] >= 0.8 for row in pairwise):
            risks.append("high_query_redundancy_signal")
        facet_rows = []
        for facet in topic["expected_facets"]:
            facet_queries = [
                row["query_variant_id"]
                for row in query_rows
                if facet in row["coverage_facets"]
            ]
            facet_rows.append(
                {
                    "facet": facet,
                    "query_variant_ids": facet_queries,
                    "retrieved_work_count_sum": sum(
                        len(query_sets[query_id]) for query_id in facet_queries
                    ),
                    "coverage_kind": "query_design_only_not_relevance_judgement",
                }
            )
        topic_audits.append(
            {
                "topic_id": topic_id,
                "union_work_count": len(union),
                "api_hit_count_sum": sum(
                    row["api_hit_count"]
                    for row in query_rows
                    if isinstance(row["api_hit_count"], int)
                ),
                "retrieved_query_hit_count": sum(
                    row["retrieved_work_count"] for row in query_rows
                ),
                "within_topic_repeated_hit_count": sum(
                    row["retrieved_work_count"] for row in query_rows
                )
                - len(union),
                "target_status": _target_status(len(union), targets),
                "query_variants": query_rows,
                "pairwise_query_overlap": pairwise,
                "multi_query_support_distribution": {
                    str(key): support_distribution[key]
                    for key in sorted(support_distribution)
                },
                "publication_year_distribution": {
                    key: year_distribution[key]
                    for key in sorted(year_distribution, key=_year_sort_key)
                },
                "publication_year_summary": {
                    "minimum": min(known_years) if known_years else None,
                    "median": statistics.median(known_years) if known_years else None,
                    "maximum": max(known_years) if known_years else None,
                    "known_count": len(known_years),
                    "missing_count": len(topic_records) - len(known_years),
                    "recent_five_year_count": sum(
                        year >= config["acquisition_policy"]["to_year"] - 4
                        for year in known_years
                    ),
                    "bins": year_bins,
                },
                "metadata_completeness": metadata,
                "query_facet_coverage": facet_rows,
                "representative_works": [
                    {
                        "openalex_id": record["openalex_id"],
                        "title": record["title"],
                        "publication_year": record["publication_year"],
                        "doi": record["doi"],
                        "query_support_count": support_counts[str(record["record_id"])],
                    }
                    for record in representatives
                ],
                "audit_signals": risks,
                "potential_topic_amendments": [],
            }
        )

    cross_topic = []
    topic_ids = [topic["topic_id"] for topic in config["topics"]]
    for index, left_id in enumerate(topic_ids):
        for right_id in topic_ids[index + 1 :]:
            intersection = topic_sets[left_id] & topic_sets[right_id]
            union = topic_sets[left_id] | topic_sets[right_id]
            cross_topic.append(
                {
                    "left_topic_id": left_id,
                    "right_topic_id": right_id,
                    "intersection_count": len(intersection),
                    "union_count": len(union),
                    "jaccard": _ratio(len(intersection), len(union)),
                    "left_overlap_ratio": _ratio(
                        len(intersection), len(topic_sets[left_id])
                    ),
                    "right_overlap_ratio": _ratio(
                        len(intersection), len(topic_sets[right_id])
                    ),
                    "shared_openalex_ids": sorted(
                        str(record_by_id[record_id]["openalex_id"])
                        for record_id in intersection
                    ),
                }
            )
    return {
        "schema_version": "1.0",
        "artifact_type": "w6_openalex_topic_robustness_audit",
        "status": "descriptive_label_free",
        "generated_at": generated_at,
        "config_identity": config["config_identity"],
        "topic_set_reference": config["topic_set_reference"],
        "global_summary": {
            "topic_count": len(topic_ids),
            "query_count": len(query_runs),
            "unique_work_count": len(records),
            "query_hit_count": len(hits),
            "repeated_query_hit_count": len(hits) - len(records),
        },
        "topics": topic_audits,
        "cross_topic_overlap": cross_topic,
        "potential_topic_amendments": [],
        "interpretation_boundary": (
            "Counts, overlaps, metadata completeness, and query-design facets are descriptive "
            "OpenAlex evidence only; they are not relevance labels, ranking metrics, or Topic selection evidence."
        ),
    }


def render_topic_audit_markdown(audit: Mapping[str, Any]) -> str:
    """Render a compact human-readable companion to the JSON audit."""

    summary = audit["global_summary"]
    lines = [
        "# W6 Post-Freeze OpenAlex Multi-Query Topic Robustness Audit",
        "",
        f"- Config identity: `{audit['config_identity']}`",
        f"- Generated at: `{audit['generated_at']}`",
        f"- Topics / queries: {summary['topic_count']} / {summary['query_count']}",
        f"- Global unique works / query hits: {summary['unique_work_count']} / {summary['query_hit_count']}",
        "- Boundary: descriptive, label-free post-freeze evidence; not Topic selection or retrieval evaluation.",
        "",
        "## Topic summary",
        "",
        "| Topic | Union works | Target status | Multi-query works | Audit signals |",
        "|---|---:|---|---:|---|",
    ]
    for topic in audit["topics"]:
        multi_query = sum(
            count
            for support, count in topic["multi_query_support_distribution"].items()
            if int(support) >= 2
        )
        signals = ", ".join(topic["audit_signals"]) or "none"
        lines.append(
            f"| `{topic['topic_id']}` | {topic['union_work_count']} | "
            f"{topic['target_status']} | {multi_query} | {signals} |"
        )
    lines.extend(["", "## Query evidence", ""])
    for topic in audit["topics"]:
        lines.extend(
            [
                f"### `{topic['topic_id']}`",
                "",
                "| Query variant | API hits | Retrieved | Unique contribution | Unique ratio | Union coverage |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for query in topic["query_variants"]:
            lines.append(
                f"| `{query['query_variant_id']}` | {query['api_hit_count']} | "
                f"{query['retrieved_work_count']} | {query['unique_contribution_count']} | "
                f"{query['unique_contribution_ratio']:.4f} | "
                f"{query['union_coverage_ratio']:.4f} |"
            )
        year = topic["publication_year_summary"]
        metadata = topic["metadata_completeness"]
        lines.extend(
            [
                "",
                f"- API-hit sum / retrieved hits / union / repeated hits: "
                f"{topic['api_hit_count_sum']} / {topic['retrieved_query_hit_count']} / "
                f"{topic['union_work_count']} / {topic['within_topic_repeated_hit_count']}",
                f"- Publication years: {year['minimum']}–{year['maximum']}, "
                f"median={year['median']}, recent-five-year={year['recent_five_year_count']}",
                f"- Abstract / DOI completeness: "
                f"{metadata['abstract']['completeness_ratio']:.4f} / "
                f"{metadata['doi']['completeness_ratio']:.4f}",
            ]
        )
        lines.extend(["", "Representative public works (descriptive ordering only):", ""])
        for work in topic["representative_works"]:
            lines.append(
                f"- `{work['openalex_id']}` ({work['publication_year']}), "
                f"support={work['query_support_count']}: {work['title']}"
            )
        lines.append("")
    nonzero_cross = [
        row for row in audit["cross_topic_overlap"] if row["intersection_count"] > 0
    ]
    lines.extend(
        [
            "## Cross-topic overlap",
            "",
            "| Topic pair | Shared works | Jaccard | Left overlap | Right overlap |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    if nonzero_cross:
        for row in nonzero_cross:
            lines.append(
                f"| `{row['left_topic_id']}` / `{row['right_topic_id']}` | "
                f"{row['intersection_count']} | {row['jaccard']:.4f} | "
                f"{row['left_overlap_ratio']:.4f} | {row['right_overlap_ratio']:.4f} |"
            )
    else:
        lines.append("| none | 0 | 0.0000 | 0.0000 | 0.0000 |")
    lines.extend(
        [
            "",
            "## Topic amendment record",
            "",
            "No `potential_topic_amendment` was recorded automatically. Any amendment requires "
            "a separate scientific interpretation and must not mutate the frozen Topic Set or split.",
            "",
        ]
    )
    return "\n".join(lines)


def _normalize_work(
    work: Mapping[str, Any],
    *,
    paper: Mapping[str, Any],
    record_id: str,
    normalized_id: str,
    retrieved_at: str,
    acquisition_run_id: str,
) -> dict[str, Any]:
    authors_text = str(paper.get("authors") or "")
    authors = [name.strip() for name in authors_text.split(";") if name.strip()]
    return {
        "record_id": record_id,
        "acquisition_run_id": acquisition_run_id,
        "openalex_id": normalized_id,
        "openalex_url": f"https://openalex.org/{normalized_id}",
        "title": str(paper.get("title") or work.get("display_name") or ""),
        "abstract": str(paper.get("abstract") or ""),
        "authors": authors,
        "publication_year": work.get("publication_year")
        if isinstance(work.get("publication_year"), int)
        else None,
        "publication_date": str(work.get("publication_date") or ""),
        "work_type": str(work.get("type") or ""),
        "doi": str(work.get("doi") or ""),
        "cited_by_count": work.get("cited_by_count")
        if isinstance(work.get("cited_by_count"), int)
        else None,
        "source_name": str(paper.get("source_name") or ""),
        "landing_page_url": str(paper.get("landing_page_url") or ""),
        "retrieved_at": retrieved_at,
        "hit_ids": [],
        "topic_ids": [],
        "query_variant_ids": [],
    }


def _read_windows_openalex_api_key(scope: str) -> str | None:
    """Read one explicitly authorized Windows environment value from Registry."""

    import winreg

    if scope == "user":
        root = winreg.HKEY_CURRENT_USER
        subkey = "Environment"
    elif scope == "machine":
        root = winreg.HKEY_LOCAL_MACHINE
        subkey = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    else:
        raise ValueError("Windows environment scope 无效。")
    try:
        with winreg.OpenKey(root, subkey) as key:
            value, _ = winreg.QueryValueEx(key, "OPENALEX_API_KEY")
    except OSError:
        return None
    return value if isinstance(value, str) else None


def _safe_client_stats(value: Any) -> dict[str, Any]:
    stats = value if isinstance(value, Mapping) else {}
    allowed = (
        "requested_max_results",
        "actual_result_count",
        "page_count",
        "request_count",
        "retry_count",
        "applied_filters",
        "elapsed_seconds",
        "stopped_reason",
        "status",
        "duplicate_records_skipped",
        "output_duplicate_id_count",
    )
    return {key: stats.get(key) for key in allowed}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path.name}:{line_number} 不是合法 JSONL。") from error
        if not isinstance(row, dict):
            raise ValueError(f"{path.name}:{line_number} 必须是 JSON object。")
        rows.append(row)
    return rows


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} 必须是 object。")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空字符串。")
    return value.strip()


def _require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} 必须是非空 string list。")
    values = [_require_text(item, label) for item in value]
    if len(values) != len(set(values)):
        raise ValueError(f"{label} 不得包含重复值。")
    return values


def _require_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} 必须是整数。")
    return value


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _sortable_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def _metadata_present(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return int(bool(value.strip()))
    if isinstance(value, list):
        return int(bool(value))
    return 1


def _target_status(count: int, targets: Mapping[str, Any]) -> str:
    if count < targets["minimum"]:
        return "below_target"
    if count <= targets["preferred_maximum"]:
        return "within_preferred_range"
    if count <= targets["soft_cap"]:
        return "above_preferred_within_soft_cap"
    return "above_soft_cap"


def _year_sort_key(value: str) -> tuple[int, str]:
    return (1, value) if value == "missing" else (0, value)


def _publication_year_bins(
    years: Sequence[int],
    *,
    from_year: int,
    to_year: int,
    missing_count: int,
) -> dict[str, int]:
    boundaries = (
        (from_year, 2009),
        (2010, 2014),
        (2015, 2019),
        (2020, 2022),
        (2023, to_year),
    )
    bins = {
        f"{start}-{end}": sum(start <= year <= end for year in years)
        for start, end in boundaries
        if start <= end
    }
    bins["missing"] = missing_count
    return bins
