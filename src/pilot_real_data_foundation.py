"""Deterministic real-data foundation for the SRTP Pilot v0.2 calibration study.

This module is intentionally narrow.  It validates the committed W6 OpenAlex
audit package, adapts the two preregistered Dev Topics into existing W6
contracts, reuses the W6 candidate-pool builder and canonicalizer, and produces
an arm-neutral canonical U80 universe.  It never imports ranking, annotation,
benchmark-label, synthesis, or live-acquisition code paths.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.annotation_tasks import sha256_file
from src.w6_artifact_safety import ensure_output_separate_from_inputs
from src.w6_candidate_pool_builder import LoadedArtifact, build_pool_artifacts
from src.w6_canonicalization import (
    CANONICALIZATION_TOOL,
    CANONICALIZATION_VERSION,
    build_canonical_entities,
    build_post_canonical_pool,
)
from src.w6_contracts import (
    W6_SCHEMA_VERSION,
    canonical_json_sha256,
    deterministic_identity,
    load_json_object,
    normalize_doi,
    normalize_openalex_id,
    validate_candidate_pool,
    validate_canonical_entities,
    validate_retrieval_provenance,
    validate_source_records,
    validate_topic_set,
    validate_topic_split,
)
from src.w6_openalex_audit import validate_acquisition_package


PILOT_SCHEMA_VERSION = "1.0"
PILOT_PROTOCOL_VERSION = "srtp-pilot-v0.2"
CONFIG_IDENTITY_PREFIX = "srtp-pilot-real-data-config"
QUERY_REGISTRY_IDENTITY_PREFIX = "srtp-pilot-query-registry"
ADAPTER_IDENTITY_PREFIX = "srtp-pilot-openalex-w6-adapter"
ELIGIBILITY_IDENTITY_PREFIX = "srtp-pilot-eligibility"
SELECTION_VIEW_IDENTITY_PREFIX = "srtp-pilot-canonical-selection-view"
U80_IDENTITY_PREFIX = "srtp-pilot-u80"
PACKAGE_IDENTITY_PREFIX = "srtp-pilot-real-data-foundation"

EXPECTED_TOPIC_IDS = (
    "w6_topic_21cm_foreground_removal",
    "w6_topic_spectral_anomaly_detection",
)
EXPECTED_QUERY_SUFFIXES = tuple(f"aq{index:02d}" for index in range(1, 7))
OPENALEX_ID_PATTERN = re.compile(r"W[1-9][0-9]*\Z")
DOI_PATTERN = re.compile(r"10\.[0-9]{4,9}/\S+\Z")
GIT_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")

QUERY_REGISTRY_FILENAME = "query_registry.json"
TOPIC_ADAPTER_FILENAME = "topic_adapter.json"
RETRIEVAL_FILENAME = "retrieval_provenance.json"
SOURCE_RECORDS_FILENAME = "source_records.json"
POOLING_POLICY_FILENAME = "pooling_policy.json"
POOL_STATISTICS_FILENAME = "pool_statistics.json"
PRECANONICAL_POOL_FILENAME = "precanonical_candidate_pool.json"
CANONICAL_ENTITIES_FILENAME = "canonical_entities.json"
POSTCANONICAL_POOL_FILENAME = "postcanonical_candidate_pool.json"
SELECTION_VIEW_FILENAME = "canonical_selection_view.json"
ELIGIBILITY_REPORT_FILENAME = "eligibility_report.json"
U80_FILENAME = "u80_calibration_universe.json"
MANIFEST_FILENAME = "manifest.json"

OUTPUT_FILENAMES = (
    QUERY_REGISTRY_FILENAME,
    TOPIC_ADAPTER_FILENAME,
    RETRIEVAL_FILENAME,
    SOURCE_RECORDS_FILENAME,
    POOLING_POLICY_FILENAME,
    POOL_STATISTICS_FILENAME,
    PRECANONICAL_POOL_FILENAME,
    CANONICAL_ENTITIES_FILENAME,
    POSTCANONICAL_POOL_FILENAME,
    SELECTION_VIEW_FILENAME,
    ELIGIBILITY_REPORT_FILENAME,
    U80_FILENAME,
)


@dataclass(frozen=True)
class PilotInputs:
    project_root: Path
    config_path: Path
    config_sha256: str
    config: dict[str, Any]
    topic_set_path: Path
    topic_set_payload: dict[str, Any]
    topics: dict[str, dict[str, Any]]
    split_path: Path
    split_payload: dict[str, Any]
    split: dict[str, set[str]]
    acquisition_config_path: Path
    acquisition_config: dict[str, Any]
    package_dir: Path
    source_manifest: dict[str, Any]
    query_runs_payload: dict[str, Any]
    query_runs_by_id: dict[str, dict[str, Any]]
    source_hits: list[dict[str, Any]]
    source_works: list[dict[str, Any]]


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path.name}:{line_number} 不是合法 JSON。") from error
        if not isinstance(row, dict):
            raise ValueError(f"{path.name}:{line_number} 顶层必须是 object。")
        rows.append(row)
    return rows


def _require_exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{label} 字段不符合 contract："
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}。"
        )


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 object。")
    return value


def _require_list(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{label} 必须是{'非空' if nonempty else ''} array。")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} 必须是无首尾空白的非空字符串。")
    return value


def _require_bool(value: Any, expected: bool, label: str) -> None:
    if value is not expected:
        raise ValueError(f"{label} 必须是 {str(expected).lower()}。")


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


def _require_datetime(value: Any, label: str) -> str:
    text = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{label} 必须是 ISO-8601 datetime。") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} 必须包含时区。")
    return text


def _resolve_project_path(project_root: Path, value: Any, label: str) -> Path:
    text = _require_text(value, label)
    relative = Path(text)
    if relative.is_absolute():
        raise ValueError(f"{label} 不得是绝对路径。")
    resolved = (project_root / relative).resolve()
    if not resolved.is_relative_to(project_root.resolve()):
        raise ValueError(f"{label} 不得逃逸 project root。")
    if not resolved.exists():
        raise ValueError(f"{label} 不存在：{text}")
    return resolved


def compute_pilot_config_identity(config: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in config.items() if key != "config_identity"}
    return deterministic_identity(CONFIG_IDENTITY_PREFIX, payload)


def _validate_reference_file(
    reference: Mapping[str, Any],
    *,
    project_root: Path,
    hash_field: str = "sha256",
    label: str,
) -> Path:
    path = _resolve_project_path(project_root, reference.get("path"), f"{label}.path")
    expected_hash = _require_sha256(reference.get(hash_field), f"{label}.{hash_field}")
    target = path / MANIFEST_FILENAME if path.is_dir() else path
    if sha256_file(target) != expected_hash:
        raise ValueError(f"{label} file hash drift。")
    return path


def _validate_config_shape(config: dict[str, Any]) -> None:
    _require_exact_fields(
        config,
        {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "config_identity",
            "status",
            "is_fixture",
            "protocol_version",
            "artifact_created_at",
            "topic_ids",
            "topic_set_reference",
            "dev_split_reference",
            "source_openalex_package",
            "source_acquisition_config",
            "source_revision_provenance",
            "query_roster",
            "query_identity_policy",
            "metadata_eligibility_policy",
            "pooling_policy",
            "canonical_selection_policy",
            "sampling",
            "input_boundary",
            "provenance",
        },
        "Pilot config",
    )
    if config["schema_version"] != PILOT_SCHEMA_VERSION:
        raise ValueError("Pilot config schema_version drift。")
    if config["artifact_type"] != "srtp_pilot_real_data_foundation_config":
        raise ValueError("Pilot config artifact_type drift。")
    if config["status"] != "frozen" or config["is_fixture"] is not False:
        raise ValueError("Pilot config 必须是真实 frozen config。")
    if config["protocol_version"] != PILOT_PROTOCOL_VERSION:
        raise ValueError("Pilot protocol version drift。")
    _require_datetime(config["artifact_created_at"], "artifact_created_at")
    if config.get("config_identity") != compute_pilot_config_identity(config):
        raise ValueError("Pilot config deterministic identity drift。")
    topic_ids = _require_list(config["topic_ids"], "topic_ids", nonempty=True)
    if tuple(topic_ids) != EXPECTED_TOPIC_IDS:
        raise ValueError("Pilot config 必须精确冻结两个指定 Dev Topics。")

    identity_policy = _require_mapping(config["query_identity_policy"], "query identity policy")
    if identity_policy != {
        "name": "pilot_aq_registry_with_exact_text_historical_lineage",
        "version": "v1",
        "preserve_acquisition_query_ids": True,
        "historical_lineage_rule": "exact_topic_and_query_text_match_only",
        "unmatched_aq_behavior": "retain_as_independent_acquisition_identity",
        "mutate_frozen_topic_artifact": False,
    }:
        raise ValueError("query identity policy drift。")

    metadata_policy = _require_mapping(
        config["metadata_eligibility_policy"], "metadata eligibility policy"
    )
    required = {
        "name",
        "version",
        "w6_required_source_fields",
        "w6_partial_fields",
        "canonical_selection_required_preferred_fields",
        "source_exclusion_reason_codes",
        "enrichment_enabled",
        "unknown_placeholder_allowed",
        "relevance_based_filtering_allowed",
    }
    _require_exact_fields(metadata_policy, required, "metadata eligibility policy")
    if metadata_policy["w6_required_source_fields"] != [
        "title",
        "publication_year",
        "authors",
        "venue",
        "landing_page_url",
    ]:
        raise ValueError("W6 required metadata roster drift。")
    if metadata_policy["w6_partial_fields"] != ["abstract", "openalex_id", "doi"]:
        raise ValueError("W6 partial metadata roster drift。")
    if metadata_policy["canonical_selection_required_preferred_fields"] != [
        "title",
        "abstract",
    ]:
        raise ValueError("canonical selection metadata gate drift。")
    for field in (
        "enrichment_enabled",
        "unknown_placeholder_allowed",
        "relevance_based_filtering_allowed",
    ):
        _require_bool(metadata_policy[field], False, f"metadata policy.{field}")

    pooling = _require_mapping(config["pooling_policy"], "pooling policy")
    _require_exact_fields(
        pooling,
        {"name", "version", "parameters", "included_run_policy", "source_rank_semantics"},
        "pooling policy",
    )
    parameters = _require_mapping(pooling["parameters"], "pooling parameters")
    if parameters.get("depth_by_system") != {"openalex_native": 80}:
        raise ValueError("Pilot pooling depth 必须完整纳入 source capture cap=80。")
    if parameters.get("target_size_per_topic") != 80 or parameters.get(
        "minimum_size_per_topic"
    ) != 80:
        raise ValueError("Pilot pool minimum/target 必须是 80。")
    _require_bool(parameters.get("random_fill_enabled"), False, "random_fill_enabled")

    selection = _require_mapping(
        config["canonical_selection_policy"], "canonical selection policy"
    )
    if selection.get("selection_unit") != "canonical_paper":
        raise ValueError("Pilot selection unit 必须是 canonical paper。")
    if selection.get("confirmed_alias_handling") != "one_slot_keep_all_alias_provenance":
        raise ValueError("confirmed alias policy drift。")
    if selection.get("suspected_duplicate_handling") != (
        "retain_separate_entities_with_explicit_status"
    ):
        raise ValueError("suspected duplicate policy drift。")

    sampling = _require_mapping(config["sampling"], "sampling")
    if sampling != {
        "method": "query_balanced_deterministic_hash_round_robin",
        "version": "v1",
        "hash_algorithm": "sha256",
        "seed": "srtp-pilot-v0.2-u80",
        "n_per_topic": 80,
        "query_iteration_order": "seeded_hash_order",
        "within_query_order": "seed_topic_query_canonical_entity_hash_order",
        "duplicate_entity_handling": "first_admission_only_keep_all_query_support",
    }:
        raise ValueError("U80 sampling config drift。")

    boundary = _require_mapping(config["input_boundary"], "input boundary")
    expected_boundary = {
        "dev_topics_only": True,
        "hidden_topics_allowed": False,
        "hidden_labels_allowed": False,
        "relevance_labels_allowed": False,
        "bm25_allowed": False,
        "human_selection_allowed": False,
        "citation_count_allowed": False,
        "source_rank_allowed_for_u80": False,
        "downstream_synthesis_allowed": False,
        "live_api_allowed": False,
    }
    if boundary != expected_boundary:
        raise ValueError("Pilot input/no-leakage boundary drift。")

    revision = _require_mapping(config["source_revision_provenance"], "source revision")
    _require_exact_fields(
        revision,
        {
            "source_package_introduction_commit",
            "source_package_parent_commit",
            "w6_compatibility_git_revision",
            "w6_git_revision_semantics",
            "exact_acquisition_execution_revision_captured",
        },
        "source revision provenance",
    )
    for field in (
        "source_package_introduction_commit",
        "source_package_parent_commit",
        "w6_compatibility_git_revision",
    ):
        _require_git_revision(revision[field], f"source revision.{field}")
    _require_bool(
        revision["exact_acquisition_execution_revision_captured"],
        False,
        "exact acquisition execution revision captured",
    )
    if revision["w6_compatibility_git_revision"] != revision["source_package_parent_commit"]:
        raise ValueError("W6 compatibility revision 必须绑定 source package parent anchor。")


def load_and_validate_pilot_inputs(
    config_path: str | Path, *, project_root: str | Path
) -> PilotInputs:
    root = Path(project_root).resolve()
    path = Path(config_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Pilot config 必须位于 project root 内。")
    config = load_json_object(path, label="Pilot real-data config")
    _validate_config_shape(config)
    config_sha256 = sha256_file(path)

    topic_reference = _require_mapping(config["topic_set_reference"], "topic set reference")
    _require_exact_fields(topic_reference, {"path", "artifact_id", "sha256"}, "topic set reference")
    topic_path = _validate_reference_file(topic_reference, project_root=root, label="topic set")
    topic_payload = load_json_object(topic_path, label="frozen W6 topic set")
    topics = validate_topic_set(topic_payload)
    if topic_payload.get("artifact_id") != topic_reference["artifact_id"]:
        raise ValueError("Topic artifact identity drift。")

    split_reference = _require_mapping(config["dev_split_reference"], "split reference")
    _require_exact_fields(
        split_reference,
        {"path", "artifact_id", "split_identity", "sha256"},
        "split reference",
    )
    split_path = _validate_reference_file(split_reference, project_root=root, label="split")
    split_payload = load_json_object(split_path, label="frozen W6 split")
    split = validate_topic_split(split_payload, topics=topics)
    if split_payload.get("artifact_id") != split_reference["artifact_id"] or split_payload.get(
        "split_identity"
    ) != split_reference["split_identity"]:
        raise ValueError("Dev split identity drift。")
    selected_topics = set(config["topic_ids"])
    if not selected_topics <= split["dev"] or selected_topics & split["hidden"]:
        raise ValueError("Pilot Topic roster 必须只来自 frozen Dev split。")

    acquisition_reference = _require_mapping(
        config["source_acquisition_config"], "source acquisition config"
    )
    _require_exact_fields(
        acquisition_reference,
        {"path", "artifact_id", "config_identity", "sha256"},
        "source acquisition config",
    )
    acquisition_config_path = _validate_reference_file(
        acquisition_reference, project_root=root, label="source acquisition config"
    )
    acquisition_config = load_json_object(
        acquisition_config_path, label="source acquisition config"
    )
    if acquisition_config.get("artifact_id") != acquisition_reference["artifact_id"] or acquisition_config.get(
        "config_identity"
    ) != acquisition_reference["config_identity"]:
        raise ValueError("source acquisition config identity drift。")

    package_reference = _require_mapping(
        config["source_openalex_package"], "source OpenAlex package"
    )
    _require_exact_fields(
        package_reference,
        {"path", "artifact_id", "acquisition_identity", "manifest_sha256"},
        "source OpenAlex package",
    )
    package_dir = _validate_reference_file(
        package_reference,
        project_root=root,
        hash_field="manifest_sha256",
        label="source OpenAlex package",
    )
    source_manifest = validate_acquisition_package(
        package_dir=package_dir,
        config_path=acquisition_config_path,
        topic_set_path=topic_path,
        split_path=split_path,
    )
    if source_manifest.get("artifact_id") != package_reference["artifact_id"] or source_manifest.get(
        "acquisition_identity"
    ) != package_reference["acquisition_identity"]:
        raise ValueError("source OpenAlex package identity drift。")

    query_runs_payload = load_json_object(package_dir / "query_runs.json", label="query runs")
    query_runs = _require_list(query_runs_payload.get("runs"), "query runs", nonempty=True)
    query_runs_by_id: dict[str, dict[str, Any]] = {}
    for raw_run in query_runs:
        run = _require_mapping(raw_run, "source query run")
        run_id = _require_text(run.get("query_run_id"), "source query_run_id")
        if run_id in query_runs_by_id:
            raise ValueError(f"duplicate source query_run_id：{run_id}。")
        query_runs_by_id[run_id] = run

    roster = _require_list(config["query_roster"], "query roster", nonempty=True)
    if len(roster) != 12:
        raise ValueError("Pilot query roster 必须精确包含 12 runs。")
    seen: set[tuple[str, str]] = set()
    suffixes: dict[str, set[str]] = defaultdict(set)
    for row in roster:
        item = _require_mapping(row, "query roster item")
        _require_exact_fields(
            item,
            {"topic_id", "acquisition_query_id", "source_query_run_id"},
            "query roster item",
        )
        topic_id = _require_text(item["topic_id"], "query roster topic_id")
        query_id = _require_text(item["acquisition_query_id"], "acquisition query ID")
        run_id = _require_text(item["source_query_run_id"], "source query run ID")
        if topic_id not in selected_topics:
            raise ValueError("query roster 引用了非 Pilot Dev Topic。")
        key = (topic_id, query_id)
        if key in seen:
            raise ValueError(f"duplicate Pilot acquisition query：{key}。")
        seen.add(key)
        run = query_runs_by_id.get(run_id)
        if run is None:
            raise ValueError(f"query roster 引用了 unknown source run：{run_id}。")
        if run.get("topic_id") != topic_id or run.get("query_variant_id") != query_id:
            raise ValueError(f"query roster 的 topic/query/run identity 不闭合：{key}。")
        suffixes[topic_id].add(query_id.rsplit("_", 1)[-1])
    if any(suffixes[topic_id] != set(EXPECTED_QUERY_SUFFIXES) for topic_id in selected_topics):
        raise ValueError("每个 Pilot Topic 必须精确保留 aq01–aq06。")

    return PilotInputs(
        project_root=root,
        config_path=path,
        config_sha256=config_sha256,
        config=config,
        topic_set_path=topic_path,
        topic_set_payload=topic_payload,
        topics=topics,
        split_path=split_path,
        split_payload=split_payload,
        split=split,
        acquisition_config_path=acquisition_config_path,
        acquisition_config=acquisition_config,
        package_dir=package_dir,
        source_manifest=source_manifest,
        query_runs_payload=query_runs_payload,
        query_runs_by_id=query_runs_by_id,
        source_hits=_read_jsonl(package_dir / "query_hits.jsonl"),
        source_works=_read_jsonl(package_dir / "works.jsonl"),
    )


@dataclass(frozen=True)
class BridgeArtifacts:
    retrieval_input: dict[str, Any]
    source_records: dict[str, Any]
    source_exclusions: list[dict[str, Any]]
    raw_topic_work_ids: dict[str, set[str]]
    query_diagnostics: list[dict[str, Any]]
    adapter_identity: str


def _artifact_reference(payload: Mapping[str, Any], sha256: str) -> dict[str, str]:
    return {
        "artifact_id": str(payload["artifact_id"]),
        "sha256": _require_sha256(sha256, "artifact reference SHA-256"),
    }


def _config_reference(inputs: PilotInputs) -> dict[str, str]:
    return {
        "artifact_id": inputs.config["artifact_id"],
        "config_identity": inputs.config["config_identity"],
        "sha256": inputs.config_sha256,
    }


def build_query_registry(
    inputs: PilotInputs, *, created_at: str, git_revision: str
) -> dict[str, Any]:
    """Build the explicit aq identity registry without rewriting aq IDs as qv IDs."""

    _require_datetime(created_at, "query registry created_at")
    _require_git_revision(git_revision, "query registry Git revision")
    acquisition_topics = {
        topic["topic_id"]: topic for topic in inputs.acquisition_config["topics"]
    }
    entries: list[dict[str, Any]] = []
    for roster_item in inputs.config["query_roster"]:
        topic_id = roster_item["topic_id"]
        query_id = roster_item["acquisition_query_id"]
        run_id = roster_item["source_query_run_id"]
        run = inputs.query_runs_by_id[run_id]
        source_variants = {
            variant["query_variant_id"]: variant
            for variant in acquisition_topics[topic_id]["query_variants"]
        }
        variant = source_variants.get(query_id)
        if variant is None or run.get("query_text") != variant.get("query_text"):
            raise ValueError(f"{query_id} config/run exact query text drift。")
        query_text = _require_text(variant["query_text"], f"{query_id}.query_text")

        historical_matches = [
            historical
            for historical in inputs.topics[topic_id]["acquisition_query_variants"]
            if historical["query_text"] == query_text
        ]
        if len(historical_matches) > 1:
            raise ValueError(f"{query_id} 匹配多个 historical qv，lineage 不唯一。")
        lineage: dict[str, Any] | None = None
        if historical_matches:
            historical = historical_matches[0]
            lineage = {
                "lineage_type": "exact_topic_and_query_text_match",
                "historical_query_variant_id": historical["query_variant_id"],
                "historical_query_text": historical["query_text"],
                "historical_query_version": historical["version"],
            }
        entries.append(
            {
                "topic_id": topic_id,
                "acquisition_query_id": query_id,
                "exact_query_text": query_text,
                "source_query_run_id": run_id,
                "source_acquisition_run_id": run["acquisition_run_id"],
                "acquisition_config_reference": {
                    "artifact_id": inputs.config["source_acquisition_config"]["artifact_id"],
                    "config_identity": inputs.config["source_acquisition_config"][
                        "config_identity"
                    ],
                    "sha256": inputs.config["source_acquisition_config"]["sha256"],
                },
                "source_package_reference": {
                    "artifact_id": inputs.source_manifest["artifact_id"],
                    "acquisition_identity": inputs.source_manifest["acquisition_identity"],
                    "manifest_sha256": inputs.config["source_openalex_package"][
                        "manifest_sha256"
                    ],
                },
                "historical_topic_query_lineage": lineage,
            }
        )
    entries.sort(key=lambda row: (row["topic_id"], row["acquisition_query_id"]))

    for topic_id in inputs.config["topic_ids"]:
        topic_entries = [entry for entry in entries if entry["topic_id"] == topic_id]
        lineage_ids = {
            entry["historical_topic_query_lineage"]["historical_query_variant_id"]
            for entry in topic_entries
            if entry["historical_topic_query_lineage"] is not None
        }
        expected_lineage_ids = {
            variant["query_variant_id"]
            for variant in inputs.topics[topic_id]["acquisition_query_variants"]
        }
        if lineage_ids != expected_lineage_ids:
            raise ValueError(
                f"{topic_id} historical exact-text lineage 必须精确覆盖 qv1/qv2。"
            )
        if any(
            entry["historical_topic_query_lineage"] is not None
            for entry in topic_entries[2:]
        ):
            raise ValueError(f"{topic_id} aq03–aq06 不得伪装成 historical qv。")

    identity_payload = {
        "protocol_version": inputs.config["protocol_version"],
        "policy": inputs.config["query_identity_policy"],
        "topic_set_reference": inputs.config["topic_set_reference"],
        "source_acquisition_config": inputs.config["source_acquisition_config"],
        "source_openalex_package": inputs.config["source_openalex_package"],
        "queries": entries,
    }
    registry_identity = deterministic_identity(
        QUERY_REGISTRY_IDENTITY_PREFIX, identity_payload
    )
    return {
        "schema_version": PILOT_SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_query_registry",
        "artifact_id": f"srtp_pilot_query_registry_{registry_identity.rsplit(':', 1)[-1][:24]}",
        "registry_identity": registry_identity,
        "protocol_version": inputs.config["protocol_version"],
        "is_fixture": False,
        "created_at": created_at,
        "policy": copy.deepcopy(inputs.config["query_identity_policy"]),
        "topic_set_reference": copy.deepcopy(inputs.config["topic_set_reference"]),
        "source_acquisition_config": copy.deepcopy(
            inputs.config["source_acquisition_config"]
        ),
        "source_openalex_package": copy.deepcopy(
            inputs.config["source_openalex_package"]
        ),
        "queries": entries,
        "provenance": {
            "kind": "pilot_query_identity_adapter",
            "created_by": "pilot_real_data_foundation",
            "created_at": created_at,
            "git_revision": git_revision,
        },
    }


def validate_query_registry(
    registry: Mapping[str, Any],
    *,
    inputs: PilotInputs,
    created_at: str,
    git_revision: str,
) -> dict[str, dict[str, Any]]:
    expected = build_query_registry(
        inputs, created_at=created_at, git_revision=git_revision
    )
    if registry != expected:
        raise ValueError("Pilot query registry semantic/identity drift。")
    queries = registry.get("queries")
    assert isinstance(queries, list)
    return {
        str(query["acquisition_query_id"]): dict(query) for query in queries
    }


def build_topic_adapter(
    inputs: PilotInputs,
    *,
    query_registry: Mapping[str, Any],
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    """Create a scoped W6 topic view whose query IDs remain the real aq IDs."""

    queries_by_topic: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for query in query_registry["queries"]:
        queries_by_topic[str(query["topic_id"])].append(query)
    topics: list[dict[str, Any]] = []
    for topic_id in inputs.config["topic_ids"]:
        original = inputs.topics[topic_id]
        adapted = {
            key: copy.deepcopy(value)
            for key, value in original.items()
            if key not in {"acquisition_query_variants", "provenance"}
        }
        adapted["acquisition_query_variants"] = [
            {
                "query_variant_id": query["acquisition_query_id"],
                "query_text": query["exact_query_text"],
                "version": "pilot-v0.2-aq-registry-v1",
                "status": "frozen",
            }
            for query in sorted(
                queries_by_topic[topic_id],
                key=lambda row: str(row["acquisition_query_id"]),
            )
        ]
        adapted["provenance"] = {
            "kind": "pilot_query_identity_adapter",
            "created_by": "pilot_real_data_foundation",
            "created_at": created_at,
            "git_revision": git_revision,
        }
        topics.append(adapted)

    adapter_identity = deterministic_identity(
        "srtp-pilot-topic-adapter",
        {
            "source_topic_set": inputs.config["topic_set_reference"],
            "query_registry_identity": query_registry["registry_identity"],
            "topic_ids": list(inputs.config["topic_ids"]),
            "topics": topics,
        },
    )
    payload = {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": "w6_topic_set",
        "artifact_id": f"srtp_pilot_topic_adapter_{adapter_identity.rsplit(':', 1)[-1][:24]}",
        "status": "frozen",
        "is_fixture": False,
        "version": "srtp-pilot-v0.2-query-adapter-v1",
        "created_at": created_at,
        "provenance": {
            "kind": "pilot_query_identity_adapter",
            "created_by": "pilot_real_data_foundation",
            "created_at": created_at,
            "git_revision": git_revision,
        },
        "topics": topics,
    }
    validate_topic_set(payload)
    return payload


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_authors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _record_exclusion_reasons(work: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not _clean_text(work.get("title")):
        reasons.append("missing_title")
    year = work.get("publication_year")
    if isinstance(year, bool) or not isinstance(year, int) or not 1800 <= year <= 2200:
        reasons.append("missing_publication_year")
    if not _clean_authors(work.get("authors")):
        reasons.append("missing_authors")
    if not _clean_text(work.get("source_name")):
        reasons.append("missing_venue")
    if not _clean_text(work.get("landing_page_url")):
        reasons.append("missing_landing_page_url")
    raw_doi = _clean_text(work.get("doi"))
    if raw_doi and not DOI_PATTERN.fullmatch(normalize_doi(raw_doi)):
        reasons.append("invalid_doi_for_w6_contract")
    return reasons


def _pilot_record_id(openalex_id: Any) -> str:
    normalized = normalize_openalex_id(openalex_id)
    if not OPENALEX_ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"无法建立合法 Pilot machine ID 的 OpenAlex identity：{openalex_id}")
    return f"pilot_openalex_{normalized.lower()}"


def build_openalex_w6_bridge(
    inputs: PilotInputs,
    *,
    topic_adapter: Mapping[str, Any],
    query_registry: Mapping[str, Any],
    created_at: str,
    git_revision: str,
) -> BridgeArtifacts:
    """Project the 12 committed real runs through the arm-neutral metadata gate."""

    selected_topics = set(inputs.config["topic_ids"])
    roster_run_ids = {
        item["source_query_run_id"] for item in inputs.config["query_roster"]
    }
    roster_by_query = {
        (item["topic_id"], item["acquisition_query_id"]): item
        for item in inputs.config["query_roster"]
    }
    selected_hits = [
        hit
        for hit in inputs.source_hits
        if hit.get("topic_id") in selected_topics
        and hit.get("query_run_id") in roster_run_ids
    ]
    hits_by_source_record: dict[str, list[dict[str, Any]]] = defaultdict(list)
    raw_topic_work_ids: dict[str, set[str]] = {
        topic_id: set() for topic_id in inputs.config["topic_ids"]
    }
    for hit in selected_hits:
        key = (hit.get("topic_id"), hit.get("query_variant_id"))
        roster = roster_by_query.get(key)
        if roster is None or hit.get("query_run_id") != roster["source_query_run_id"]:
            raise ValueError(f"source hit topic/query/run closure drift：{key}。")
        rank = hit.get("source_rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= 80:
            raise ValueError("source hit rank 超出 frozen capture cap 1..80。")
        source_record_id = _require_text(hit.get("record_id"), "source hit record_id")
        hits_by_source_record[source_record_id].append(hit)
        raw_topic_work_ids[str(hit["topic_id"])].add(source_record_id)

    works_by_source_id = {
        _require_text(work.get("record_id"), "source work record_id"): work
        for work in inputs.source_works
    }
    if not set(hits_by_source_record) <= set(works_by_source_id):
        raise ValueError("selected source hits 包含 dangling works。")

    included_source_ids: set[str] = set()
    source_exclusions: list[dict[str, Any]] = []
    for source_record_id in sorted(hits_by_source_record):
        work = works_by_source_id[source_record_id]
        reasons = _record_exclusion_reasons(work)
        if not reasons:
            included_source_ids.add(source_record_id)
            continue
        record_hits = hits_by_source_record[source_record_id]
        source_exclusions.append(
            {
                "source_record_id": source_record_id,
                "openalex_id": work["openalex_id"],
                "topic_ids": sorted({str(hit["topic_id"]) for hit in record_hits}),
                "acquisition_query_ids": sorted(
                    {str(hit["query_variant_id"]) for hit in record_hits}
                ),
                "source_query_run_ids": sorted(
                    {str(hit["query_run_id"]) for hit in record_hits}
                ),
                "source_hit_ids": sorted(str(hit["hit_id"]) for hit in record_hits),
                "reason_codes": reasons,
            }
        )

    eligible_hits = [
        hit for hit in selected_hits if hit["record_id"] in included_source_ids
    ]
    eligible_hit_ids = {str(hit["hit_id"]) for hit in eligible_hits}
    excluded_hit_ids = {
        str(hit["hit_id"])
        for hit in selected_hits
        if hit["record_id"] not in included_source_ids
    }

    revision = inputs.config["source_revision_provenance"]
    acquisition_policy = inputs.acquisition_config["acquisition_policy"]
    runs: list[dict[str, Any]] = []
    for roster_item in sorted(
        inputs.config["query_roster"], key=lambda row: row["source_query_run_id"]
    ):
        source_run = inputs.query_runs_by_id[roster_item["source_query_run_id"]]
        run_id = source_run["query_run_id"]
        raw_run_hits = sorted(
            str(hit["hit_id"])
            for hit in selected_hits
            if hit["query_run_id"] == run_id
        )
        included = sorted(set(raw_run_hits) & eligible_hit_ids)
        excluded = sorted(set(raw_run_hits) & excluded_hit_ids)
        frozen_configuration = {
            "provider": acquisition_policy["provider"],
            "entity": acquisition_policy["entity"],
            "operation": acquisition_policy["operation"],
            "query_text": source_run["query_text"],
            "from_year": acquisition_policy["from_year"],
            "to_year": acquisition_policy["to_year"],
            "max_results_per_query": acquisition_policy["max_results_per_query"],
            "source_config_identity": inputs.acquisition_config["config_identity"],
            "source_config_sha256": inputs.config["source_acquisition_config"]["sha256"],
            "source_acquisition_identity": inputs.source_manifest["acquisition_identity"],
            "source_package_manifest_sha256": inputs.config["source_openalex_package"][
                "manifest_sha256"
            ],
            "git_revision_semantics": revision["w6_git_revision_semantics"],
            "exact_acquisition_execution_revision_captured": revision[
                "exact_acquisition_execution_revision_captured"
            ],
        }
        run_output_sha256 = canonical_json_sha256(
            {
                "source_query_run": source_run,
                "included_source_hit_ids": included,
                "excluded_source_hit_ids": excluded,
                "metadata_policy": inputs.config["metadata_eligibility_policy"],
            }
        )
        runs.append(
            {
                "retrieval_run_id": run_id,
                "topic_id": source_run["topic_id"],
                "acquisition_system": "openalex_native",
                "query_variant_id": source_run["query_variant_id"],
                "method": {
                    "method_id": "openalex_native_audit_v1",
                    "family": "api_native",
                    "model": None,
                },
                "frozen_configuration": frozen_configuration,
                "configuration_sha256": canonical_json_sha256(frozen_configuration),
                "deterministic_seed": None,
                "started_at": source_run["query_started_at"],
                "completed_at": source_run["query_completed_at"],
                "git_revision": revision["w6_compatibility_git_revision"],
                "run_output_sha256": run_output_sha256,
            }
        )

    run_by_id = {run["retrieval_run_id"]: run for run in runs}
    hits: list[dict[str, Any]] = []
    for source_hit in eligible_hits:
        run_id = str(source_hit["query_run_id"])
        hits.append(
            {
                "retrieval_hit_id": source_hit["hit_id"],
                "retrieval_run_id": run_id,
                "record_id": _pilot_record_id(source_hit["openalex_id"]),
                "source_rank": source_hit["source_rank"],
                "source_score": None,
                "score_direction": "not_applicable",
                "retrieved_at": run_by_id[run_id]["completed_at"],
            }
        )
    hits.sort(
        key=lambda hit: (
            hit["retrieval_run_id"],
            hit["source_rank"],
            hit["retrieval_hit_id"],
        )
    )

    retrieval_identity = deterministic_identity(
        "srtp-pilot-w6-retrieval-input",
        {
            "query_registry_identity": query_registry["registry_identity"],
            "metadata_policy": inputs.config["metadata_eligibility_policy"],
            "runs": runs,
            "hits": hits,
        },
    )
    retrieval_payload = {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": "w6_retrieval_provenance",
        "artifact_id": f"srtp_pilot_retrieval_input_{retrieval_identity.rsplit(':', 1)[-1][:24]}",
        "is_fixture": False,
        "created_at": created_at,
        "provenance": {
            "kind": "pilot_openalex_real_data_adapter",
            "created_by": "pilot_real_data_foundation",
            "created_at": created_at,
            "git_revision": git_revision,
        },
        "runs": runs,
        "hits": hits,
    }
    adapted_topics = validate_topic_set(dict(topic_adapter))
    retrieval = validate_retrieval_provenance(
        retrieval_payload, topics=adapted_topics
    )

    hit_ids_by_record: dict[str, list[str]] = defaultdict(list)
    topic_ids_by_record: dict[str, set[str]] = defaultdict(set)
    for hit_id, hit in retrieval["hits"].items():
        hit_ids_by_record[hit["record_id"]].append(hit_id)
        topic_ids_by_record[hit["record_id"]].add(
            retrieval["runs"][hit["retrieval_run_id"]]["topic_id"]
        )
    source_records: list[dict[str, Any]] = []
    for source_record_id in sorted(included_source_ids):
        work = works_by_source_id[source_record_id]
        record_id = _pilot_record_id(work["openalex_id"])
        abstract = _clean_text(work.get("abstract")) or None
        doi = _clean_text(work.get("doi")) or None
        missing_fields = sorted(
            field
            for field, value in (
                ("abstract", abstract),
                ("openalex_id", work["openalex_id"]),
                ("doi", doi),
            )
            if value is None
        )
        completeness_score = round((3 - len(missing_fields)) / 3, 6)
        source_records.append(
            {
                "record_id": record_id,
                "topic_ids": sorted(topic_ids_by_record[record_id]),
                "openalex_id": work["openalex_id"],
                "doi": doi,
                "title": _clean_text(work["title"]),
                "abstract": abstract,
                "publication_year": work["publication_year"],
                "authors": _clean_authors(work["authors"]),
                "venue": _clean_text(work["source_name"]),
                "landing_page_url": _clean_text(work["landing_page_url"]),
                "metadata_completeness": {
                    "status": "partial" if missing_fields else "complete",
                    "missing_fields": missing_fields,
                    "completeness_score": completeness_score,
                },
                "acquisition_provenance_refs": sorted(hit_ids_by_record[record_id]),
                "record_provenance": {
                    "provider": "OpenAlex",
                    "source_record_id": normalize_openalex_id(work["openalex_id"]),
                    "retrieved_at": work["retrieved_at"],
                },
            }
        )
    source_identity = deterministic_identity(
        "srtp-pilot-w6-source-records",
        {
            "retrieval_artifact_id": retrieval_payload["artifact_id"],
            "records": source_records,
        },
    )
    source_payload = {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": "w6_source_records",
        "artifact_id": f"srtp_pilot_source_records_{source_identity.rsplit(':', 1)[-1][:24]}",
        "is_fixture": False,
        "created_at": created_at,
        "provenance": {
            "kind": "pilot_openalex_real_data_adapter",
            "created_by": "pilot_real_data_foundation",
            "created_at": created_at,
            "git_revision": git_revision,
        },
        "records": source_records,
    }
    validate_source_records(
        source_payload, topics=adapted_topics, retrieval=retrieval
    )

    diagnostics: list[dict[str, Any]] = []
    for run in sorted(runs, key=lambda row: row["query_variant_id"]):
        source_run = inputs.query_runs_by_id[run["retrieval_run_id"]]
        raw_count = sum(
            hit["query_run_id"] == run["retrieval_run_id"] for hit in selected_hits
        )
        included_count = sum(
            hit["query_run_id"] == run["retrieval_run_id"] for hit in eligible_hits
        )
        diagnostics.append(
            {
                "topic_id": run["topic_id"],
                "acquisition_query_id": run["query_variant_id"],
                "source_query_run_id": run["retrieval_run_id"],
                "source_retrieved_hit_count": source_run["retrieved_work_count"],
                "scoped_raw_hit_count": raw_count,
                "representable_hit_count": included_count,
                "excluded_hit_count": raw_count - included_count,
            }
        )

    adapter_identity = deterministic_identity(
        ADAPTER_IDENTITY_PREFIX,
        {
            "config": _config_reference(inputs),
            "query_registry_identity": query_registry["registry_identity"],
            "source_package": inputs.config["source_openalex_package"],
            "retrieval_sha256": _payload_sha256(retrieval_payload),
            "source_records_sha256": _payload_sha256(source_payload),
            "source_exclusions": source_exclusions,
        },
    )
    return BridgeArtifacts(
        retrieval_input=retrieval_payload,
        source_records=source_payload,
        source_exclusions=source_exclusions,
        raw_topic_work_ids=raw_topic_work_ids,
        query_diagnostics=diagnostics,
        adapter_identity=adapter_identity,
    )


def _selection_item_id(topic_id: str, canonical_entity_id: str) -> str:
    digest = canonical_json_sha256(
        {"topic_id": topic_id, "canonical_entity_id": canonical_entity_id}
    )
    return f"pilot_selection_item_{digest[:24]}"


def build_canonical_selection_view(
    *,
    config: Mapping[str, Any],
    query_registry: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    records: Mapping[str, Any],
    post_pool: Mapping[str, Any],
    canonical: Mapping[str, Any],
    inputs: Mapping[str, Any],
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    """Collapse post-pool source-record rows into one selectable row per paper."""

    members_by_topic_entity: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for member in post_pool["members"]:
        members_by_topic_entity[
            (str(member["topic_id"]), str(member["canonical_entity_id"]))
        ].append(member)

    relationships_by_entity: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for relationship in canonical["relationships"].values():
        for entity_id in relationship["entity_ids"]:
            relationships_by_entity[str(entity_id)].append(relationship)

    query_registry_by_id = {
        str(query["acquisition_query_id"]): query
        for query in query_registry["queries"]
    }
    items: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {}
    for topic_id in config["topic_ids"]:
        topic_groups = [
            (entity_id, members)
            for (member_topic, entity_id), members in members_by_topic_entity.items()
            if member_topic == topic_id
        ]
        eligible_count = 0
        ineligible_count = 0
        alias_collapse_count = 0
        suspected_entity_ids: set[str] = set()
        for entity_id, members in sorted(topic_groups):
            entity = canonical["entities"][entity_id]
            preferred = records[entity["preferred_record_id"]]
            reason_codes: list[str] = []
            if not _clean_text(preferred.get("title")):
                reason_codes.append("missing_preferred_title")
            if not _clean_text(preferred.get("abstract")):
                reason_codes.append("missing_preferred_abstract")
            if reason_codes:
                ineligible_count += 1
                exclusions.append(
                    {
                        "topic_id": topic_id,
                        "canonical_entity_id": entity_id,
                        "preferred_record_id": entity["preferred_record_id"],
                        "reason_codes": reason_codes,
                    }
                )
                continue

            topic_record_ids = sorted({str(member["record_id"]) for member in members})
            alias_collapse_count += max(0, len(topic_record_ids) - 1)
            query_hit_ids: dict[str, list[str]] = defaultdict(list)
            for member in members:
                for hit_id in member["retrieval_hit_ids"]:
                    hit = retrieval["hits"][hit_id]
                    run = retrieval["runs"][hit["retrieval_run_id"]]
                    if run["topic_id"] != topic_id:
                        raise ValueError("canonical selection query provenance topic drift。")
                    query_hit_ids[str(run["query_variant_id"])].append(str(hit_id))
            query_support: list[dict[str, Any]] = []
            for query_id in sorted(query_hit_ids):
                query = query_registry_by_id.get(query_id)
                if query is None or query["topic_id"] != topic_id:
                    raise ValueError("canonical selection query registry closure drift。")
                query_support.append(
                    {
                        "acquisition_query_id": query_id,
                        "exact_query_text": query["exact_query_text"],
                        "source_query_run_id": query["source_query_run_id"],
                        "retrieval_hit_ids": sorted(set(query_hit_ids[query_id])),
                    }
                )
            if not query_support:
                raise ValueError("canonical selection item 缺少 query/run provenance。")

            relationships = sorted(
                relationships_by_entity.get(entity_id, []),
                key=lambda row: str(row["relationship_id"]),
            )
            if relationships:
                suspected_entity_ids.add(entity_id)
            states = {str(row["review_state"]) for row in relationships}
            suspected_status = (
                "pending_review"
                if "pending_review" in states
                else "confirmed_distinct"
                if states
                else "none"
            )
            source_provenance = []
            for record_id in entity["alias_record_ids"]:
                record = records[record_id]
                source_provenance.append(
                    {
                        "record_id": record_id,
                        "provider": record["record_provenance"]["provider"],
                        "provider_source_record_id": record["record_provenance"][
                            "source_record_id"
                        ],
                        "openalex_id": record["openalex_id"],
                        "doi": record["doi"],
                        "acquisition_hit_ids": list(
                            record["acquisition_provenance_refs"]
                        ),
                    }
                )
            items.append(
                {
                    "selection_item_id": _selection_item_id(topic_id, entity_id),
                    "topic_id": topic_id,
                    "canonical_entity_id": entity_id,
                    "preferred_record_id": entity["preferred_record_id"],
                    "alias_record_ids": list(entity["alias_record_ids"]),
                    "title": preferred["title"],
                    "abstract": preferred["abstract"],
                    "publication_year": preferred["publication_year"],
                    "authors": list(preferred["authors"]),
                    "venue": preferred["venue"],
                    "openalex_ids": list(entity["normalized_openalex_ids"]),
                    "dois": list(entity["normalized_dois"]),
                    "source_provenance": source_provenance,
                    "query_support": query_support,
                    "suspected_duplicate_status": suspected_status,
                    "suspected_relationship_ids": [
                        str(row["relationship_id"]) for row in relationships
                    ],
                }
            )
            eligible_count += 1
        counts[topic_id] = {
            "postcanonical_entity_count": len(topic_groups),
            "eligible_canonical_entity_count": eligible_count,
            "ineligible_canonical_entity_count": ineligible_count,
            "confirmed_alias_record_collapse_count": alias_collapse_count,
            "suspected_duplicate_entity_count": len(suspected_entity_ids),
        }

    items.sort(key=lambda row: (row["topic_id"], row["canonical_entity_id"]))
    exclusions.sort(key=lambda row: (row["topic_id"], row["canonical_entity_id"]))
    identity_payload = {
        "protocol_version": config["protocol_version"],
        "inputs": inputs,
        "policy": config["canonical_selection_policy"],
        "metadata_gate": config["metadata_eligibility_policy"][
            "canonical_selection_required_preferred_fields"
        ],
        "topic_counts": counts,
        "items": items,
        "excluded_entities": exclusions,
    }
    view_identity = deterministic_identity(
        SELECTION_VIEW_IDENTITY_PREFIX, identity_payload
    )
    return {
        "schema_version": PILOT_SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_canonical_selection_view",
        "artifact_id": f"srtp_pilot_canonical_selection_{view_identity.rsplit(':', 1)[-1][:24]}",
        "view_identity": view_identity,
        "protocol_version": config["protocol_version"],
        "is_fixture": False,
        "created_at": created_at,
        "inputs": copy.deepcopy(dict(inputs)),
        "policy": copy.deepcopy(config["canonical_selection_policy"]),
        "metadata_gate": list(
            config["metadata_eligibility_policy"][
                "canonical_selection_required_preferred_fields"
            ]
        ),
        "topic_counts": counts,
        "items": items,
        "excluded_entities": exclusions,
        "provenance": {
            "kind": "pilot_canonical_selection_view",
            "created_by": "pilot_real_data_foundation",
            "created_at": created_at,
            "git_revision": git_revision,
        },
    }


def _hash_order(*parts: str) -> tuple[str, str]:
    joined = "|".join(parts).encode("utf-8")
    return hashlib.sha256(joined).hexdigest(), parts[-1]


def sample_query_balanced_u80(
    *,
    selection_view: Mapping[str, Any],
    query_registry: Mapping[str, Any],
    config: Mapping[str, Any],
    input_references: Mapping[str, Any],
    created_at: str,
    git_revision: str,
    git_worktree_clean: bool,
) -> dict[str, Any]:
    """Sample one U80 per Topic using only stable canonical/query identities."""

    sampling = config["sampling"]
    seed = str(sampling["seed"])
    requested_n = int(sampling["n_per_topic"])
    items_by_topic: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in selection_view["items"]:
        items_by_topic[str(item["topic_id"])].append(item)
    queries_by_topic: dict[str, list[str]] = defaultdict(list)
    for query in query_registry["queries"]:
        queries_by_topic[str(query["topic_id"])].append(
            str(query["acquisition_query_id"])
        )

    topic_outputs: list[dict[str, Any]] = []
    for topic_id in config["topic_ids"]:
        topic_items = {
            str(item["canonical_entity_id"]): item for item in items_by_topic[topic_id]
        }
        if len(topic_items) < requested_n:
            raise ValueError(
                f"{topic_id} eligible canonical universe {len(topic_items)} < {requested_n}，"
                "U80 fail closed。"
            )
        query_ids = sorted(queries_by_topic[topic_id])
        if len(query_ids) != 6:
            raise ValueError(f"{topic_id} U80 sampling 必须使用全部六个 aq runs。")
        query_order = sorted(
            query_ids,
            key=lambda query_id: _hash_order(
                seed, "query-order", topic_id, query_id
            ),
        )
        rosters: dict[str, list[str]] = {query_id: [] for query_id in query_ids}
        for entity_id, item in topic_items.items():
            for support in item["query_support"]:
                query_id = str(support["acquisition_query_id"])
                if query_id not in rosters:
                    raise ValueError("canonical selection view 包含非 roster query。")
                rosters[query_id].append(entity_id)
        for query_id in query_ids:
            rosters[query_id] = sorted(
                set(rosters[query_id]),
                key=lambda entity_id: _hash_order(
                    seed, "entity-order", topic_id, query_id, entity_id
                ),
            )
        empty_query_ids = [
            query_id for query_id in query_ids if not rosters[query_id]
        ]
        if empty_query_ids:
            raise ValueError(
                f"{topic_id} required AQ eligible roster empty: "
                f"{', '.join(empty_query_ids)}; six-query sampling fail closed。"
            )

        positions = {query_id: 0 for query_id in query_ids}
        selected: list[tuple[str, str]] = []
        selected_ids: set[str] = set()
        contribution = Counter()
        while len(selected) < requested_n:
            made_progress = False
            for query_id in query_order:
                roster = rosters[query_id]
                position = positions[query_id]
                while position < len(roster) and roster[position] in selected_ids:
                    position += 1
                positions[query_id] = position
                if position >= len(roster):
                    continue
                entity_id = roster[position]
                positions[query_id] += 1
                selected_ids.add(entity_id)
                selected.append((entity_id, query_id))
                contribution[query_id] += 1
                made_progress = True
                if len(selected) == requested_n:
                    break
            if not made_progress:
                raise ValueError(
                    f"{topic_id} six-query round-robin exhausted before U80，fail closed。"
                )

        ordered_items: list[dict[str, Any]] = []
        for order, (entity_id, first_query_id) in enumerate(selected, start=1):
            item = topic_items[entity_id]
            support_ids = sorted(
                str(support["acquisition_query_id"])
                for support in item["query_support"]
            )
            ordered_items.append(
                {
                    "sample_order": order,
                    "canonical_selection_item_id": item["selection_item_id"],
                    "canonical_entity_id": entity_id,
                    "preferred_record_id": item["preferred_record_id"],
                    "alias_record_ids": list(item["alias_record_ids"]),
                    "all_query_support_ids": support_ids,
                    "first_selected_via_query_id": first_query_id,
                }
            )
        diagnostics = []
        for query_id in sorted(query_ids):
            diagnostics.append(
                {
                    "acquisition_query_id": query_id,
                    "eligible_roster_count": len(rosters[query_id]),
                    "first_selection_contribution_count": contribution[query_id],
                    "support_count_in_u80": sum(
                        query_id in item["all_query_support_ids"] for item in ordered_items
                    ),
                }
            )
        topic_outputs.append(
            {
                "topic_id": topic_id,
                "eligible_canonical_entity_count": len(topic_items),
                "requested_n": requested_n,
                "query_iteration_order": query_order,
                "ordered_canonical_entity_ids": [
                    item["canonical_entity_id"] for item in ordered_items
                ],
                "preferred_record_ids": [
                    item["preferred_record_id"] for item in ordered_items
                ],
                "ordered_items": ordered_items,
                "query_contribution_diagnostics": diagnostics,
            }
        )

    identity_payload = {
        "protocol_version": config["protocol_version"],
        "name": "OpenAlex-query-conditioned calibration universe",
        "inputs": input_references,
        "sampling": sampling,
        "topics": topic_outputs,
    }
    u80_identity = deterministic_identity(U80_IDENTITY_PREFIX, identity_payload)
    return {
        "schema_version": PILOT_SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_u80_calibration_universe",
        "artifact_id": f"srtp_pilot_u80_{u80_identity.rsplit(':', 1)[-1][:24]}",
        "u80_identity": u80_identity,
        "protocol_version": config["protocol_version"],
        "name": "OpenAlex-query-conditioned calibration universe",
        "is_fixture": False,
        "created_at": created_at,
        "inputs": copy.deepcopy(dict(input_references)),
        "sampling": copy.deepcopy(sampling),
        "topic_counts": {topic_id: requested_n for topic_id in config["topic_ids"]},
        "topics": topic_outputs,
        "generation": {
            "git_revision": git_revision,
            "git_worktree_clean": git_worktree_clean,
        },
        "label_access": {
            "dev_labels_read": False,
            "hidden_labels_read": False,
            "ranking_or_synthesis_outputs_read": False,
            "declaration": (
                "U80 generation used only frozen Dev Topic identity, committed OpenAlex "
                "provenance, metadata eligibility, canonical identity, and deterministic hashing."
            ),
        },
    }


def build_eligibility_report(
    *,
    config: Mapping[str, Any],
    bridge: BridgeArtifacts,
    source_records: Mapping[str, Any],
    pre_pool: Mapping[str, Any],
    selection_view: Mapping[str, Any],
    input_references: Mapping[str, Any],
    created_at: str,
    git_revision: str,
) -> dict[str, Any]:
    records_by_topic = Counter()
    for record in source_records["records"]:
        for topic_id in record["topic_ids"]:
            records_by_topic[topic_id] += 1
    source_reason_counts = Counter(
        reason
        for exclusion in bridge.source_exclusions
        for reason in exclusion["reason_codes"]
    )
    source_reason_counts_by_topic: dict[str, Counter[str]] = {
        topic_id: Counter() for topic_id in config["topic_ids"]
    }
    for exclusion in bridge.source_exclusions:
        for topic_id in exclusion["topic_ids"]:
            for reason in exclusion["reason_codes"]:
                source_reason_counts_by_topic[topic_id][reason] += 1

    topics: list[dict[str, Any]] = []
    for topic_id in config["topic_ids"]:
        view_counts = selection_view["topic_counts"][topic_id]
        topics.append(
            {
                "topic_id": topic_id,
                "raw_unique_source_work_count": len(bridge.raw_topic_work_ids[topic_id]),
                "w6_representable_source_record_count": records_by_topic[topic_id],
                "source_record_exclusion_count": (
                    len(bridge.raw_topic_work_ids[topic_id])
                    - records_by_topic[topic_id]
                ),
                "precanonical_pool_record_count": pre_pool["topic_counts"][topic_id],
                "canonical_entity_count": view_counts["postcanonical_entity_count"],
                "eligible_canonical_entity_count": view_counts[
                    "eligible_canonical_entity_count"
                ],
                "canonical_selection_exclusion_count": view_counts[
                    "ineligible_canonical_entity_count"
                ],
                "confirmed_alias_record_collapse_count": view_counts[
                    "confirmed_alias_record_collapse_count"
                ],
                "suspected_duplicate_entity_count": view_counts[
                    "suspected_duplicate_entity_count"
                ],
                "source_exclusion_reason_counts": dict(
                    sorted(source_reason_counts_by_topic[topic_id].items())
                ),
            }
        )

    policy_sha256 = canonical_json_sha256(config["metadata_eligibility_policy"])
    identity_payload = {
        "protocol_version": config["protocol_version"],
        "inputs": input_references,
        "policy_sha256": policy_sha256,
        "source_record_exclusions": bridge.source_exclusions,
        "canonical_selection_exclusions": selection_view["excluded_entities"],
        "query_diagnostics": bridge.query_diagnostics,
        "topics": topics,
    }
    eligibility_identity = deterministic_identity(
        ELIGIBILITY_IDENTITY_PREFIX, identity_payload
    )
    return {
        "schema_version": PILOT_SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_metadata_eligibility_report",
        "artifact_id": f"srtp_pilot_eligibility_{eligibility_identity.rsplit(':', 1)[-1][:24]}",
        "eligibility_identity": eligibility_identity,
        "protocol_version": config["protocol_version"],
        "is_fixture": False,
        "created_at": created_at,
        "inputs": copy.deepcopy(dict(input_references)),
        "policy": copy.deepcopy(config["metadata_eligibility_policy"]),
        "policy_sha256": policy_sha256,
        "source_record_exclusion_count": len(bridge.source_exclusions),
        "source_exclusion_reason_counts": dict(sorted(source_reason_counts.items())),
        "source_record_exclusions": copy.deepcopy(bridge.source_exclusions),
        "canonical_selection_exclusion_count": len(
            selection_view["excluded_entities"]
        ),
        "canonical_selection_exclusions": copy.deepcopy(
            selection_view["excluded_entities"]
        ),
        "query_diagnostics": copy.deepcopy(bridge.query_diagnostics),
        "topics": topics,
        "provenance": {
            "kind": "pilot_arm_neutral_metadata_eligibility",
            "created_by": "pilot_real_data_foundation",
            "created_at": created_at,
            "git_revision": git_revision,
        },
    }


def _loaded_artifact(payload: dict[str, Any]) -> LoadedArtifact:
    return LoadedArtifact(payload=payload, sha256=_payload_sha256(payload))


def _pool_policy(config: Mapping[str, Any]) -> dict[str, Any]:
    pooling = config["pooling_policy"]
    return {
        "name": pooling["name"],
        "version": pooling["version"],
        "parameters": copy.deepcopy(pooling["parameters"]),
        "included_retrieval_run_ids": sorted(
            item["source_query_run_id"] for item in config["query_roster"]
        ),
    }


def _canonicalization_identity(
    *,
    config: Mapping[str, Any],
    source_records_reference: Mapping[str, Any],
    retrieval_reference: Mapping[str, Any],
    canonical_sha256: str,
    post_pool_identity: str,
) -> str:
    return deterministic_identity(
        "srtp-pilot-canonicalization",
        {
            "tool": CANONICALIZATION_TOOL,
            "version": CANONICALIZATION_VERSION,
            "policy": config["canonical_selection_policy"],
            "source_records": source_records_reference,
            "retrieval_provenance": retrieval_reference,
            "canonical_entities_sha256": canonical_sha256,
            "postcanonical_pool_identity": post_pool_identity,
        },
    )


def _build_manifest(
    *,
    inputs: PilotInputs,
    payloads: Mapping[str, Mapping[str, Any]],
    bridge: BridgeArtifacts,
    canonicalization_identity: str,
    created_at: str,
    git_revision: str,
    git_worktree_clean: bool,
) -> dict[str, Any]:
    output_hashes = {
        filename: _payload_sha256(payloads[filename]) for filename in OUTPUT_FILENAMES
    }
    eligibility = payloads[ELIGIBILITY_REPORT_FILENAME]
    u80 = payloads[U80_FILENAME]
    canonical = payloads[CANONICAL_ENTITIES_FILENAME]
    pre_pool = payloads[PRECANONICAL_POOL_FILENAME]
    post_pool = payloads[POSTCANONICAL_POOL_FILENAME]
    query_registry = payloads[QUERY_REGISTRY_FILENAME]

    per_topic = []
    u80_by_topic = {topic["topic_id"]: topic for topic in u80["topics"]}
    for topic in eligibility["topics"]:
        topic_id = topic["topic_id"]
        per_topic.append(
            {
                **copy.deepcopy(topic),
                "u80_count": u80["topic_counts"][topic_id],
                "query_contribution_diagnostics": copy.deepcopy(
                    u80_by_topic[topic_id]["query_contribution_diagnostics"]
                ),
            }
        )

    identities = {
        "config_identity": inputs.config["config_identity"],
        "query_registry_identity": query_registry["registry_identity"],
        "adapter_identity": bridge.adapter_identity,
        "exclusion_policy_sha256": eligibility["policy_sha256"],
        "candidate_pool_identity": pre_pool["pool_identity"],
        "postcanonical_pool_identity": post_pool["pool_identity"],
        "canonicalization_identity": canonicalization_identity,
        "canonical_selection_view_identity": payloads[SELECTION_VIEW_FILENAME][
            "view_identity"
        ],
        "u80_identity": u80["u80_identity"],
    }
    package_identity = deterministic_identity(
        PACKAGE_IDENTITY_PREFIX,
        {
            "protocol_version": inputs.config["protocol_version"],
            "config": _config_reference(inputs),
            "source_openalex_package": inputs.config["source_openalex_package"],
            "query_roster": inputs.config["query_roster"],
            "identities": identities,
            "files": output_hashes,
        },
    )
    raw_unique = set().union(*bridge.raw_topic_work_ids.values())
    return {
        "schema_version": PILOT_SCHEMA_VERSION,
        "artifact_type": "srtp_pilot_real_data_foundation_manifest",
        "artifact_id": f"srtp_pilot_real_data_foundation_{package_identity.rsplit(':', 1)[-1][:24]}",
        "package_identity": package_identity,
        "protocol_version": inputs.config["protocol_version"],
        "status": "frozen",
        "is_fixture": False,
        "created_at": created_at,
        "config": _config_reference(inputs),
        "source_inputs": {
            "frozen_topic_set": copy.deepcopy(inputs.config["topic_set_reference"]),
            "dev_split": copy.deepcopy(inputs.config["dev_split_reference"]),
            "source_acquisition_config": copy.deepcopy(
                inputs.config["source_acquisition_config"]
            ),
            "source_openalex_package": copy.deepcopy(
                inputs.config["source_openalex_package"]
            ),
            "source_revision_provenance": copy.deepcopy(
                inputs.config["source_revision_provenance"]
            ),
            "query_roster": copy.deepcopy(inputs.config["query_roster"]),
        },
        "identities": identities,
        "counts": {
            "topic_count": len(inputs.config["topic_ids"]),
            "query_run_count": len(inputs.config["query_roster"]),
            "raw_unique_source_work_count": len(raw_unique),
            "raw_topic_work_assignment_count": sum(
                len(values) for values in bridge.raw_topic_work_ids.values()
            ),
            "w6_source_record_count": len(
                payloads[SOURCE_RECORDS_FILENAME]["records"]
            ),
            "source_record_exclusion_count": eligibility[
                "source_record_exclusion_count"
            ],
            "precanonical_pool_item_count": len(pre_pool["members"]),
            "canonical_entity_count": len(canonical["entities"]),
            "suspected_relationship_count": len(
                canonical["suspected_relationships"]
            ),
            "canonical_selection_item_count": len(
                payloads[SELECTION_VIEW_FILENAME]["items"]
            ),
            "u80_total_count": sum(u80["topic_counts"].values()),
            "per_topic": per_topic,
        },
        "files": output_hashes,
        "generation": {
            "git_revision": git_revision,
            "git_worktree_clean": git_worktree_clean,
            "created_at": created_at,
        },
        "reproducibility": {
            "command": (
                "python -m app.build_pilot_real_data_foundation "
                "--config configs/pilot/srtp_pilot_v0.2_real_data_foundation_v1.json "
                "--output-dir data/research/pilot/v0.2/real-data-foundation-v1"
            ),
            "offline_only": True,
            "live_openalex_requests": False,
            "frozen_inputs_modified": False,
        },
        "input_boundary": copy.deepcopy(inputs.config["input_boundary"]),
    }


def assemble_pilot_payloads(
    inputs: PilotInputs,
    *,
    created_at: str,
    git_revision: str,
    git_worktree_clean: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Assemble and self-validate the complete deterministic package in memory."""

    _require_datetime(created_at, "package created_at")
    _require_git_revision(git_revision, "package Git revision")
    if not git_worktree_clean:
        raise ValueError("frozen Pilot package 必须从 clean Git worktree 生成。")

    query_registry = build_query_registry(
        inputs, created_at=created_at, git_revision=git_revision
    )
    validate_query_registry(
        query_registry,
        inputs=inputs,
        created_at=created_at,
        git_revision=git_revision,
    )
    topic_adapter = build_topic_adapter(
        inputs,
        query_registry=query_registry,
        created_at=created_at,
        git_revision=git_revision,
    )
    bridge = build_openalex_w6_bridge(
        inputs,
        topic_adapter=topic_adapter,
        query_registry=query_registry,
        created_at=created_at,
        git_revision=git_revision,
    )
    policy = _pool_policy(inputs.config)
    topic_loaded = _loaded_artifact(topic_adapter)
    retrieval_loaded = _loaded_artifact(bridge.retrieval_input)
    source_loaded = _loaded_artifact(bridge.source_records)
    policy_loaded = _loaded_artifact(policy)
    pool_artifacts = build_pool_artifacts(
        topic_set=topic_loaded,
        retrieval_artifacts=[retrieval_loaded],
        source_records=source_loaded,
        policy=policy_loaded,
        generated_at=created_at,
        git_revision=git_revision,
        status="frozen",
        git_worktree_clean=git_worktree_clean,
    )
    retrieval_payload = pool_artifacts.retrieval_provenance
    retrieval_sha256 = _payload_sha256(retrieval_payload)
    source_sha256 = _payload_sha256(bridge.source_records)
    topic_adapter_sha256 = _payload_sha256(topic_adapter)
    pre_pool = pool_artifacts.candidate_pool

    adapted_topics = validate_topic_set(topic_adapter)
    retrieval = validate_retrieval_provenance(
        retrieval_payload, topics=adapted_topics
    )
    records = validate_source_records(
        bridge.source_records, topics=adapted_topics, retrieval=retrieval
    )
    canonical_artifact_seed = deterministic_identity(
        "srtp-pilot-canonical-artifact",
        {
            "source_records": _artifact_reference(
                bridge.source_records, source_sha256
            ),
            "retrieval_provenance": _artifact_reference(
                retrieval_payload, retrieval_sha256
            ),
            "tool": CANONICALIZATION_TOOL,
            "version": CANONICALIZATION_VERSION,
        },
    )
    canonical_artifact_id = (
        "srtp_pilot_canonical_entities_"
        + canonical_artifact_seed.rsplit(":", 1)[-1][:24]
    )
    canonical_payload = build_canonical_entities(
        records,
        artifact_id=canonical_artifact_id,
        created_at=created_at,
        git_revision=git_revision,
        is_fixture=False,
        reviewer=None,
        provenance_kind="pilot_canonicalization_run",
        provenance_created_by="pilot_real_data_foundation",
    )
    canonical_sha256 = _payload_sha256(canonical_payload)
    canonical = validate_canonical_entities(
        canonical_payload, records=records, retrieval=retrieval
    )
    post_pool_artifact_seed = deterministic_identity(
        "srtp-pilot-postcanonical-pool",
        {
            "precanonical_pool_identity": pre_pool["pool_identity"],
            "canonical_entities": _artifact_reference(
                canonical_payload, canonical_sha256
            ),
        },
    )
    post_pool = build_post_canonical_pool(
        pre_pool,
        canonical_payload,
        artifact_id=(
            "srtp_pilot_postcanonical_pool_"
            + post_pool_artifact_seed.rsplit(":", 1)[-1][:24]
        ),
        canonical_artifact_id=canonical_payload["artifact_id"],
        canonical_sha256=canonical_sha256,
        created_at=created_at,
        git_revision=git_revision,
        is_fixture=False,
        provenance_kind="pilot_canonicalization_run",
        provenance_created_by="pilot_real_data_foundation",
    )
    registry = {
        topic_adapter["artifact_id"]: _artifact_reference(
            topic_adapter, topic_adapter_sha256
        ),
        retrieval_payload["artifact_id"]: _artifact_reference(
            retrieval_payload, retrieval_sha256
        ),
        bridge.source_records["artifact_id"]: _artifact_reference(
            bridge.source_records, source_sha256
        ),
        canonical_payload["artifact_id"]: _artifact_reference(
            canonical_payload, canonical_sha256
        ),
    }
    validate_candidate_pool(
        post_pool,
        topics=adapted_topics,
        records=records,
        retrieval=retrieval,
        registry=registry,
        canonical=canonical,
    )
    post_pool_sha256 = _payload_sha256(post_pool)
    canonicalization_identity = _canonicalization_identity(
        config=inputs.config,
        source_records_reference=_artifact_reference(
            bridge.source_records, source_sha256
        ),
        retrieval_reference=_artifact_reference(
            retrieval_payload, retrieval_sha256
        ),
        canonical_sha256=canonical_sha256,
        post_pool_identity=post_pool["pool_identity"],
    )

    query_registry_sha256 = _payload_sha256(query_registry)
    selection_inputs = {
        "frozen_topic_set": {
            "artifact_id": inputs.config["topic_set_reference"]["artifact_id"],
            "sha256": inputs.config["topic_set_reference"]["sha256"],
        },
        "dev_split": {
            "artifact_id": inputs.config["dev_split_reference"]["artifact_id"],
            "sha256": inputs.config["dev_split_reference"]["sha256"],
            "split_identity": inputs.config["dev_split_reference"]["split_identity"],
        },
        "query_registry": _artifact_reference(
            query_registry, query_registry_sha256
        ),
        "topic_adapter": _artifact_reference(
            topic_adapter, topic_adapter_sha256
        ),
        "retrieval_provenance": _artifact_reference(
            retrieval_payload, retrieval_sha256
        ),
        "source_records": _artifact_reference(
            bridge.source_records, source_sha256
        ),
        "candidate_pool": {
            **_artifact_reference(post_pool, post_pool_sha256),
            "pool_identity": post_pool["pool_identity"],
        },
        "canonical_entities": _artifact_reference(
            canonical_payload, canonical_sha256
        ),
    }
    selection_view = build_canonical_selection_view(
        config=inputs.config,
        query_registry=query_registry,
        retrieval=retrieval,
        records=records,
        post_pool=post_pool,
        canonical=canonical,
        inputs=selection_inputs,
        created_at=created_at,
        git_revision=git_revision,
    )
    selection_view_sha256 = _payload_sha256(selection_view)
    eligibility_inputs = {
        **copy.deepcopy(selection_inputs),
        "canonical_selection_view": _artifact_reference(
            selection_view, selection_view_sha256
        ),
    }
    eligibility = build_eligibility_report(
        config=inputs.config,
        bridge=bridge,
        source_records=bridge.source_records,
        pre_pool=pre_pool,
        selection_view=selection_view,
        input_references=eligibility_inputs,
        created_at=created_at,
        git_revision=git_revision,
    )
    eligibility_sha256 = _payload_sha256(eligibility)
    u80_inputs = {
        "config": _config_reference(inputs),
        "frozen_topic_set": copy.deepcopy(inputs.config["topic_set_reference"]),
        "dev_split": copy.deepcopy(inputs.config["dev_split_reference"]),
        "source_openalex_package": copy.deepcopy(
            inputs.config["source_openalex_package"]
        ),
        "acquisition_query_runs": copy.deepcopy(inputs.config["query_roster"]),
        "query_registry": _artifact_reference(
            query_registry, query_registry_sha256
        ),
        "adapter": {
            "adapter_identity": bridge.adapter_identity,
            "retrieval_provenance": _artifact_reference(
                retrieval_payload, retrieval_sha256
            ),
            "source_records": _artifact_reference(
                bridge.source_records, source_sha256
            ),
        },
        "eligibility": {
            **_artifact_reference(eligibility, eligibility_sha256),
            "policy_sha256": eligibility["policy_sha256"],
        },
        "candidate_pool": {
            **_artifact_reference(pre_pool, _payload_sha256(pre_pool)),
            "pool_identity": pre_pool["pool_identity"],
        },
        "canonicalization": {
            "canonicalization_identity": canonicalization_identity,
            "canonical_entities": _artifact_reference(
                canonical_payload, canonical_sha256
            ),
            "postcanonical_pool": {
                **_artifact_reference(post_pool, post_pool_sha256),
                "pool_identity": post_pool["pool_identity"],
            },
        },
        "canonical_selection_view": _artifact_reference(
            selection_view, selection_view_sha256
        ),
    }
    u80 = sample_query_balanced_u80(
        selection_view=selection_view,
        query_registry=query_registry,
        config=inputs.config,
        input_references=u80_inputs,
        created_at=created_at,
        git_revision=git_revision,
        git_worktree_clean=git_worktree_clean,
    )

    payloads: dict[str, dict[str, Any]] = {
        QUERY_REGISTRY_FILENAME: query_registry,
        TOPIC_ADAPTER_FILENAME: topic_adapter,
        RETRIEVAL_FILENAME: retrieval_payload,
        SOURCE_RECORDS_FILENAME: bridge.source_records,
        POOLING_POLICY_FILENAME: policy,
        POOL_STATISTICS_FILENAME: pool_artifacts.statistics,
        PRECANONICAL_POOL_FILENAME: pre_pool,
        CANONICAL_ENTITIES_FILENAME: canonical_payload,
        POSTCANONICAL_POOL_FILENAME: post_pool,
        SELECTION_VIEW_FILENAME: selection_view,
        ELIGIBILITY_REPORT_FILENAME: eligibility,
        U80_FILENAME: u80,
    }
    manifest = _build_manifest(
        inputs=inputs,
        payloads=payloads,
        bridge=bridge,
        canonicalization_identity=canonicalization_identity,
        created_at=created_at,
        git_revision=git_revision,
        git_worktree_clean=git_worktree_clean,
    )
    return payloads, manifest


def capture_git_state(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _require_git_revision(revision, "Git revision")
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"git_revision": revision, "git_worktree_clean": not bool(status.strip())}


def validate_pilot_package(
    package_dir: str | Path,
    *,
    config_path: str | Path,
    project_root: str | Path,
) -> dict[str, Any]:
    """Validate closure by deterministic reconstruction with shared assembly semantics."""

    package = Path(package_dir).resolve()
    if not package.is_dir():
        raise ValueError("Pilot package directory 不存在。")
    expected_names = set(OUTPUT_FILENAMES) | {MANIFEST_FILENAME}
    actual_names = {path.name for path in package.iterdir() if path.is_file()}
    if actual_names != expected_names or any(path.is_dir() for path in package.iterdir()):
        raise ValueError(
            f"Pilot package file closure drift：missing={sorted(expected_names - actual_names)}, "
            f"extra={sorted(actual_names - expected_names)}。"
        )
    inputs = load_and_validate_pilot_inputs(config_path, project_root=project_root)
    manifest = load_json_object(package / MANIFEST_FILENAME, label="Pilot package manifest")
    if (
        manifest.get("schema_version") != PILOT_SCHEMA_VERSION
        or manifest.get("artifact_type")
        != "srtp_pilot_real_data_foundation_manifest"
        or manifest.get("status") != "frozen"
        or manifest.get("is_fixture") is not False
    ):
        raise ValueError("Pilot package manifest header/status drift。")
    if manifest.get("config") != _config_reference(inputs):
        raise ValueError("Pilot package config binding drift。")
    files = _require_mapping(manifest.get("files"), "Pilot package files")
    if set(files) != set(OUTPUT_FILENAMES):
        raise ValueError("Pilot package output roster drift。")
    for filename in OUTPUT_FILENAMES:
        if files[filename] != sha256_file(package / filename):
            raise ValueError(f"Pilot package file hash drift：{filename}。")
    generation = _require_mapping(manifest.get("generation"), "Pilot generation")
    git_revision = _require_git_revision(
        generation.get("git_revision"), "Pilot generation Git revision"
    )
    _require_bool(
        generation.get("git_worktree_clean"), True, "Pilot generation clean state"
    )
    created_at = _require_datetime(generation.get("created_at"), "Pilot generation created_at")
    if created_at != manifest.get("created_at"):
        raise ValueError("Pilot manifest/generation created_at drift。")

    expected_payloads, expected_manifest = assemble_pilot_payloads(
        inputs,
        created_at=created_at,
        git_revision=git_revision,
        git_worktree_clean=True,
    )
    for filename, expected in expected_payloads.items():
        actual = load_json_object(package / filename, label=filename)
        if actual != expected:
            raise ValueError(f"Pilot package semantic closure drift：{filename}。")
    if manifest != expected_manifest:
        raise ValueError("Pilot package manifest identity/count/provenance drift。")
    return manifest


def build_pilot_package(
    *,
    config_path: str | Path,
    output_dir: str | Path,
    project_root: str | Path,
) -> Path:
    """Build, self-validate, and atomically publish the frozen real package."""

    root = Path(project_root).resolve()
    inputs = load_and_validate_pilot_inputs(config_path, project_root=root)
    git_state = capture_git_state(root)
    if not git_state["git_worktree_clean"]:
        raise ValueError("frozen Pilot package 必须在生成开始前的 clean Git worktree 上构建。")
    output = ensure_output_separate_from_inputs(
        output_dir,
        input_paths=[
            inputs.config_path,
            inputs.topic_set_path,
            inputs.split_path,
            inputs.acquisition_config_path,
            inputs.package_dir,
        ],
    )
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Pilot output directory 必须不存在或为空，拒绝覆盖。")
    payloads, manifest = assemble_pilot_payloads(
        inputs,
        created_at=inputs.config["artifact_created_at"],
        git_revision=git_state["git_revision"],
        git_worktree_clean=True,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.publish_", dir=output.parent)
    )
    try:
        for filename in OUTPUT_FILENAMES:
            (staging / filename).write_bytes(_json_bytes(payloads[filename]))
        (staging / MANIFEST_FILENAME).write_bytes(_json_bytes(manifest))
        validate_pilot_package(
            staging, config_path=inputs.config_path, project_root=root
        )
        if output.exists():
            output.rmdir()
        staging.replace(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return output / MANIFEST_FILENAME


__all__ = [
    "ELIGIBILITY_REPORT_FILENAME",
    "MANIFEST_FILENAME",
    "SELECTION_VIEW_FILENAME",
    "U80_FILENAME",
    "assemble_pilot_payloads",
    "build_canonical_selection_view",
    "build_openalex_w6_bridge",
    "build_pilot_package",
    "build_query_registry",
    "capture_git_state",
    "compute_pilot_config_identity",
    "load_and_validate_pilot_inputs",
    "sample_query_balanced_u80",
    "validate_pilot_package",
    "validate_query_registry",
]
