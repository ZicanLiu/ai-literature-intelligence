"""W6 candidate metadata and retrieval diagnostics.

The module consumes only the four public inputs declared for the W6 metadata
diagnostics task: topics, retrieval provenance, source records, and the
pre-canonical candidate pool. It validates those artifacts with the shared W6
contract before producing deterministic diagnostics. It never reads relevance
labels and never mutates source records.
"""

from __future__ import annotations

import copy
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from src.annotation_tasks import sha256_file
from src.w6_contracts import (
    deterministic_identity,
    load_json_object,
    validate_candidate_pool,
    validate_retrieval_provenance,
    validate_source_records,
    validate_topic_set,
)


REPORT_SCHEMA_VERSION = "1.0"
REPORT_ARTIFACT_TYPE = "w6_metadata_retrieval_diagnostics"
TOOL_NAME = "w6_metadata_diagnostics"
TOOL_VERSION = "1.0.0"
DIAGNOSTICS_JSON_NAME = "diagnostics_report.json"
METADATA_CSV_NAME = "metadata_completeness.csv"
GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")

INPUT_ARTIFACT_TYPES = {
    "topic_set": "w6_topic_set",
    "retrieval_provenance": "w6_retrieval_provenance",
    "source_records": "w6_source_records",
    "precanonical_candidate_pool": "w6_candidate_pool",
}

METADATA_FIELD_SPECS = (
    ("abstract", "abstract"),
    ("doi", "doi"),
    ("openalex_id", "openalex_id"),
    ("publication_year", "publication_year"),
    ("venue", "venue"),
    ("authors", "authors"),
    ("landing_page_url", "landing_page_url"),
    ("provider", "record_provenance.provider"),
)
METADATA_FIELD_NAMES = tuple(name for name, _ in METADATA_FIELD_SPECS)
CONTRACT_OPTIONAL_METADATA_FIELDS = ("abstract", "openalex_id", "doi")
ENRICHABLE_FIELDS = frozenset(
    {
        "abstract",
        "doi",
        "openalex_id",
        "publication_year",
        "venue",
        "authors",
        "landing_page_url",
    }
)
METADATA_CSV_COLUMNS = (
    "scope",
    "topic_id",
    "field",
    "field_path",
    "candidate_count",
    "present_count",
    "missing_count",
    "missing_rate",
)


class MetadataContractError(ValueError):
    """Raised when metadata self-description conflicts with record payloads."""

    def __init__(self, issues: Sequence[Mapping[str, Any]]):
        self.issues = [dict(issue) for issue in issues]
        issue_codes = ", ".join(
            sorted({str(issue.get("code", "unknown")) for issue in self.issues})
        )
        super().__init__(
            "source-record metadata contract inconsistent: "
            f"issues={len(self.issues)}, codes={issue_codes}"
        )


class MetadataEnrichmentProvider(Protocol):
    """Minimal offline-testable interface for non-destructive proposals."""

    provider_id: str
    provider_version: str

    def lookup(
        self, record: Mapping[str, Any]
    ) -> Mapping[str, Mapping[str, Any]]:
        """Return ``field -> {value, source}`` proposals for one source record."""


@dataclass(frozen=True)
class ValidatedDiagnosticsInputs:
    """The four contract-validated inputs required by Issue #68."""

    topics: dict[str, dict[str, Any]]
    retrieval: dict[str, Any]
    records: dict[str, dict[str, Any]]
    pool_members: dict[str, dict[str, Any]]
    payloads: dict[str, dict[str, Any]]
    input_references: dict[str, dict[str, Any]]
    is_fixture: bool


def load_and_validate_diagnostics_inputs(
    *,
    topics_path: str | Path,
    retrieval_path: str | Path,
    source_records_path: str | Path,
    precanonical_pool_path: str | Path,
) -> ValidatedDiagnosticsInputs:
    """Load exactly four W6 artifacts and validate relevant cross-references."""

    paths = {
        "topic_set": Path(topics_path),
        "retrieval_provenance": Path(retrieval_path),
        "source_records": Path(source_records_path),
        "precanonical_candidate_pool": Path(precanonical_pool_path),
    }
    payloads = {
        name: load_json_object(path, label=name) for name, path in paths.items()
    }
    input_references: dict[str, dict[str, Any]] = {}
    registry: dict[str, dict[str, str]] = {}
    for name in INPUT_ARTIFACT_TYPES:
        payload = payloads[name]
        artifact_id = payload.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError(f"{name}.artifact_id must be a non-empty string.")
        if artifact_id in registry:
            raise ValueError(f"duplicate input artifact_id: {artifact_id}")
        digest = sha256_file(paths[name])
        registry[artifact_id] = {"artifact_id": artifact_id, "sha256": digest}
        input_references[name] = {
            "artifact_id": artifact_id,
            "artifact_type": payload.get("artifact_type"),
            "schema_version": payload.get("schema_version"),
            "sha256": digest,
            "is_fixture": payload.get("is_fixture"),
        }

    topics = validate_topic_set(payloads["topic_set"])
    retrieval = validate_retrieval_provenance(
        payloads["retrieval_provenance"], topics=topics
    )

    metadata_preflight = analyze_metadata_contract(
        payloads["source_records"].get("records", [])
    )
    issues = metadata_preflight["contract_consistency"]["issues"]
    if issues:
        raise MetadataContractError(issues)

    records = validate_source_records(
        payloads["source_records"], topics=topics, retrieval=retrieval
    )
    pool_members = validate_candidate_pool(
        payloads["precanonical_candidate_pool"],
        topics=topics,
        records=records,
        retrieval=retrieval,
        registry=registry,
    )

    fixture_flags = {payloads[name]["is_fixture"] for name in INPUT_ARTIFACT_TYPES}
    if len(fixture_flags) != 1:
        raise ValueError("diagnostics inputs cannot mix fixture and non-fixture artifacts.")
    return ValidatedDiagnosticsInputs(
        topics=topics,
        retrieval=retrieval,
        records=records,
        pool_members=pool_members,
        payloads=payloads,
        input_references=input_references,
        is_fixture=fixture_flags.pop(),
    )


def analyze_metadata_contract(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Analyze actual missing values and self-description consistency.

    This function is deliberately tolerant enough to describe invalid
    ``missing_fields`` declarations. The artifact loader uses the returned issues
    to fail closed before running cross-artifact diagnostics.
    """

    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("source records must be a sequence.")
    ordered_records = sorted(
        records,
        key=lambda row: (
            0,
            str(row.get("record_id", "")),
        )
        if isinstance(row, Mapping)
        else (1, repr(row)),
    )
    quality = _metadata_quality_summary(
        [record if isinstance(record, Mapping) else {} for record in ordered_records]
    )
    issues: list[dict[str, Any]] = []
    missing_but_valid: list[dict[str, Any]] = []
    inconsistent_record_ids: set[str] = set()
    identity_records: dict[tuple[str, str], list[str]] = defaultdict(list)
    status_distribution: Counter[str] = Counter()

    for index, record in enumerate(ordered_records, start=1):
        if not isinstance(record, Mapping):
            issues.append(
                {"code": "record_not_object", "record_id": f"record_{index}"}
            )
            continue
        record_id = str(record.get("record_id") or f"record_{index}")
        expected_missing = sorted(
            field
            for field in CONTRACT_OPTIONAL_METADATA_FIELDS
            if _is_missing(record.get(field))
        )
        completeness = record.get("metadata_completeness")
        record_issue_count = 0
        if not isinstance(completeness, Mapping):
            issues.append(
                {
                    "code": "metadata_completeness_not_object",
                    "record_id": record_id,
                    "actual_missing_fields": expected_missing,
                }
            )
            record_issue_count += 1
        else:
            status = completeness.get("status")
            status_distribution[str(status)] += 1
            declared_raw = completeness.get("missing_fields")
            if not isinstance(declared_raw, list) or any(
                not isinstance(value, str) for value in declared_raw
            ):
                declared_missing: list[str] = []
                issues.append(
                    {
                        "code": "missing_fields_not_string_list",
                        "record_id": record_id,
                        "actual_missing_fields": expected_missing,
                    }
                )
                record_issue_count += 1
            else:
                declared_missing = sorted(set(declared_raw))
                if len(declared_missing) != len(declared_raw):
                    issues.append(
                        {
                            "code": "duplicate_declared_missing_field",
                            "record_id": record_id,
                            "declared_missing_fields": declared_missing,
                        }
                    )
                    record_issue_count += 1
                if declared_missing != expected_missing:
                    issues.append(
                        {
                            "code": "missing_fields_mismatch",
                            "record_id": record_id,
                            "actual_missing_fields": expected_missing,
                            "declared_missing_fields": declared_missing,
                        }
                    )
                    record_issue_count += 1
            expected_status = "partial" if expected_missing else "complete"
            if status != expected_status:
                issues.append(
                    {
                        "code": "completeness_status_mismatch",
                        "record_id": record_id,
                        "actual_status": status,
                        "expected_status": expected_status,
                    }
                )
                record_issue_count += 1
            score = completeness.get("completeness_score")
            score_valid = (
                not isinstance(score, bool)
                and isinstance(score, (int, float))
                and 0 <= float(score) <= 1
            )
            if not score_valid or (
                expected_status == "complete" and float(score) != 1.0
            ) or (expected_status == "partial" and float(score) >= 1.0):
                issues.append(
                    {
                        "code": "completeness_score_mismatch",
                        "record_id": record_id,
                        "actual_score": score,
                        "expected_status": expected_status,
                    }
                )
                record_issue_count += 1

        provenance = record.get("record_provenance")
        if isinstance(provenance, Mapping):
            provider = provenance.get("provider")
            source_record_id = provenance.get("source_record_id")
            if isinstance(provider, str) and isinstance(source_record_id, str):
                identity_records[(provider.casefold(), source_record_id.casefold())].append(
                    record_id
                )

        if record_issue_count:
            inconsistent_record_ids.add(record_id)
        elif expected_missing:
            missing_but_valid.append(
                {"record_id": record_id, "missing_fields": expected_missing}
            )

    duplicate_identity_count = 0
    for (provider, source_record_id), record_ids in sorted(identity_records.items()):
        if len(record_ids) < 2:
            continue
        duplicate_identity_count += 1
        inconsistent_record_ids.update(record_ids)
        issues.append(
            {
                "code": "duplicate_provider_source_record_id",
                "provider": provider,
                "source_record_id": source_record_id,
                "record_ids": sorted(record_ids),
            }
        )

    issues.sort(
        key=lambda issue: (
            str(issue.get("record_id", "")),
            str(issue.get("code", "")),
            json.dumps(issue, ensure_ascii=False, sort_keys=True),
        )
    )
    quality.update(
        {
            "completeness_status_distribution": [
                {"status": status, "count": count}
                for status, count in sorted(status_distribution.items())
            ],
            "missing_but_valid_record_count": len(missing_but_valid),
            "missing_but_valid_records": missing_but_valid,
            "duplicate_source_identity_count": duplicate_identity_count,
            "contract_consistency": {
                "status": "consistent" if not issues else "inconsistent",
                "issue_count": len(issues),
                "inconsistent_record_count": len(inconsistent_record_ids),
                "issues": issues,
            },
        }
    )
    return quality


def collect_enrichment_proposals(
    records: Mapping[str, Mapping[str, Any]],
    provider: MetadataEnrichmentProvider,
    *,
    lookup_at: str,
) -> list[dict[str, Any]]:
    """Collect deterministic proposals without changing the source records."""

    _require_timezone_datetime(lookup_at, "enrichment lookup_at")
    provider_id = str(getattr(provider, "provider_id", "")).strip()
    provider_version = str(getattr(provider, "provider_version", "")).strip()
    if not provider_id or not provider_version:
        raise ValueError("enrichment provider_id/provider_version must be non-empty.")
    proposals: list[dict[str, Any]] = []
    for record_id in sorted(records):
        record = records[record_id]
        raw_proposals = provider.lookup(copy.deepcopy(record))
        if not isinstance(raw_proposals, Mapping):
            raise ValueError(f"enrichment provider returned non-object for {record_id}.")
        for field in sorted(raw_proposals):
            if field not in ENRICHABLE_FIELDS:
                raise ValueError(f"unsupported enrichment field: {field}")
            proposal = raw_proposals[field]
            if not isinstance(proposal, Mapping) or set(proposal) != {"value", "source"}:
                raise ValueError(
                    f"enrichment proposal {record_id}.{field} must contain value/source."
                )
            source = proposal["source"]
            if not isinstance(source, str) or not source.strip():
                raise ValueError(
                    f"enrichment proposal {record_id}.{field}.source must be non-empty."
                )
            proposed_value = proposal["value"]
            try:
                json.dumps(proposed_value, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"enrichment proposal {record_id}.{field}.value is not JSON-safe."
                ) from error
            old_value = record.get(field)
            if proposed_value == old_value:
                continue
            record_provenance = record.get("record_provenance") or {}
            proposals.append(
                {
                    "record_id": record_id,
                    "field": field,
                    "old_value": old_value,
                    "proposed_value": proposed_value,
                    "provider": provider_id,
                    "provider_version": provider_version,
                    "source": source.strip(),
                    "lookup_at": lookup_at,
                    "source_record_identity": {
                        "provider": record_provenance.get("provider"),
                        "source_record_id": record_provenance.get("source_record_id"),
                    },
                    "provenance": {
                        "kind": "metadata_enrichment_proposal",
                        "applied_to_source_record": False,
                    },
                }
            )
    return proposals


def build_diagnostics_report(
    inputs: ValidatedDiagnosticsInputs,
    *,
    git_revision: str,
    generated_at: str | None = None,
    enrichment_provider: MetadataEnrichmentProvider | None = None,
    enrichment_lookup_at: str | None = None,
) -> dict[str, Any]:
    """Build the semantic report; all collection-valued output is sorted."""

    if not GIT_REVISION_PATTERN.fullmatch(git_revision):
        raise ValueError("git_revision must be a complete 40-character lowercase SHA.")
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _require_timezone_datetime(generated_at, "generated_at")

    metadata = analyze_metadata_contract(list(inputs.records.values()))
    if metadata["contract_consistency"]["issue_count"]:
        raise MetadataContractError(metadata["contract_consistency"]["issues"])
    retrieval = _build_retrieval_diagnostics(inputs)

    if enrichment_provider is None:
        if enrichment_lookup_at is not None:
            raise ValueError("enrichment_lookup_at requires an enrichment provider.")
        enrichment = {
            "status": "not_requested",
            "proposal_count": 0,
            "source_records_modified": False,
            "proposals": [],
        }
    else:
        lookup_at = enrichment_lookup_at or generated_at
        proposals = collect_enrichment_proposals(
            inputs.records, enrichment_provider, lookup_at=lookup_at
        )
        enrichment = {
            "status": "proposals_generated",
            "provider": {
                "provider_id": enrichment_provider.provider_id,
                "provider_version": enrichment_provider.provider_version,
            },
            "proposal_count": len(proposals),
            "source_records_modified": False,
            "proposals": proposals,
        }

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "artifact_type": REPORT_ARTIFACT_TYPE,
        "is_fixture": inputs.is_fixture,
        "generated_at": generated_at,
        "generated_by": {
            "tool": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "git_revision": git_revision,
        },
        "inputs": {
            name: copy.deepcopy(inputs.input_references[name])
            for name in INPUT_ARTIFACT_TYPES
        },
        "counts": {
            "topic_count": len(inputs.topics),
            "retrieval_run_count": len(inputs.retrieval["runs"]),
            "retrieval_hit_count": len(inputs.retrieval["hits"]),
            "source_record_count": len(inputs.records),
            "global_unique_retrieved_record_count": retrieval["summary"][
                "global_unique_record_count"
            ],
            "precanonical_pool_member_count": len(inputs.pool_members),
        },
        "metadata": metadata,
        "retrieval": retrieval,
        "enrichment": enrichment,
        "label_access": {
            "allowed_input_artifacts": list(INPUT_ARTIFACT_TYPES),
            "relevance_labels_read": False,
        },
        "determinism": {
            "semantic_identity_excludes": ["generated_at"],
            "unordered_input_collections_are_sorted": True,
        },
    }


def write_diagnostics_outputs(
    report: Mapping[str, Any], output_dir: str | Path
) -> dict[str, Path]:
    """Write one JSON artifact plus a bound deterministic CSV summary."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / METADATA_CSV_NAME
    json_path = destination / DIAGNOSTICS_JSON_NAME

    rows = _metadata_csv_rows(report)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(METADATA_CSV_COLUMNS),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    final_report = copy.deepcopy(dict(report))
    final_report["outputs"] = {
        "metadata_completeness_csv": {
            "file_name": METADATA_CSV_NAME,
            "sha256": sha256_file(csv_path),
            "columns": list(METADATA_CSV_COLUMNS),
        }
    }
    identity_payload = copy.deepcopy(final_report)
    identity_payload.pop("generated_at", None)
    final_report["report_identity"] = deterministic_identity(
        "w6-diagnostics", identity_payload
    )
    json_path.write_text(
        json.dumps(final_report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return {"report": json_path, "metadata_csv": csv_path}


def run_diagnostics(
    *,
    topics_path: str | Path,
    retrieval_path: str | Path,
    source_records_path: str | Path,
    precanonical_pool_path: str | Path,
    output_dir: str | Path,
    git_revision: str,
    generated_at: str | None = None,
    enrichment_provider: MetadataEnrichmentProvider | None = None,
    enrichment_lookup_at: str | None = None,
) -> dict[str, Any]:
    """Validate inputs, build diagnostics, and write the report artifact."""

    inputs = load_and_validate_diagnostics_inputs(
        topics_path=topics_path,
        retrieval_path=retrieval_path,
        source_records_path=source_records_path,
        precanonical_pool_path=precanonical_pool_path,
    )
    report = build_diagnostics_report(
        inputs,
        git_revision=git_revision,
        generated_at=generated_at,
        enrichment_provider=enrichment_provider,
        enrichment_lookup_at=enrichment_lookup_at,
    )
    paths = write_diagnostics_outputs(report, output_dir)
    return {
        "inputs": inputs,
        "report": load_json_object(paths["report"], label="W6 diagnostics report"),
        "paths": paths,
    }


def _build_retrieval_diagnostics(
    inputs: ValidatedDiagnosticsInputs,
) -> dict[str, Any]:
    runs = inputs.retrieval["runs"]
    hits = inputs.retrieval["hits"]
    records = inputs.records
    hits_by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for hit in hits.values():
        hits_by_run[hit["retrieval_run_id"]].append(hit)

    run_rows: list[dict[str, Any]] = []
    query_run_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    query_hits: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for run_id in sorted(runs):
        run = runs[run_id]
        run_hits = sorted(
            hits_by_run.get(run_id, []), key=lambda row: row["retrieval_hit_id"]
        )
        record_ids = {hit["record_id"] for hit in run_hits}
        query_key = (run["topic_id"], run["query_variant_id"])
        query_run_ids[query_key].add(run_id)
        query_hits[query_key].extend(run_hits)
        run_rows.append(
            {
                "retrieval_run_id": run_id,
                "topic_id": run["topic_id"],
                "query_variant_id": run["query_variant_id"],
                "acquisition_system": run["acquisition_system"],
                "completion_status": "completed",
                "contract_valid": True,
                "started_at": run["started_at"],
                "completed_at": run["completed_at"],
                "run_output_sha256": run["run_output_sha256"],
                "hit_count": len(run_hits),
                "unique_record_count": len(record_ids),
            }
        )

    declared_query_keys = {
        (topic_id, variant["query_variant_id"])
        for topic_id, topic in inputs.topics.items()
        for variant in topic["acquisition_query_variants"]
    }
    all_query_keys = declared_query_keys | set(query_run_ids)
    query_record_sets: dict[tuple[str, str], set[str]] = {}
    query_rows: list[dict[str, Any]] = []
    for topic_id, variant_id in sorted(all_query_keys):
        key = (topic_id, variant_id)
        query_hit_rows = query_hits.get(key, [])
        record_ids = {hit["record_id"] for hit in query_hit_rows}
        query_record_sets[key] = record_ids
        run_ids = sorted(query_run_ids.get(key, set()))
        query_rows.append(
            {
                "topic_id": topic_id,
                "query_variant_id": variant_id,
                "run_count": len(run_ids),
                "retrieval_run_ids": run_ids,
                "acquisition_systems": sorted(
                    {runs[run_id]["acquisition_system"] for run_id in run_ids}
                ),
                "hit_count": len(query_hit_rows),
                "unique_record_count": len(record_ids),
                "metadata": _metadata_quality_summary(
                    [records[record_id] for record_id in sorted(record_ids)]
                ),
            }
        )

    overlap_rows: list[dict[str, Any]] = []
    for topic_id in sorted(inputs.topics):
        variant_ids = sorted(
            variant["query_variant_id"]
            for variant in inputs.topics[topic_id]["acquisition_query_variants"]
        )
        for left_index, left_id in enumerate(variant_ids):
            left_records = query_record_sets.get((topic_id, left_id), set())
            for right_id in variant_ids[left_index + 1 :]:
                right_records = query_record_sets.get((topic_id, right_id), set())
                intersection_count = len(left_records & right_records)
                union_count = len(left_records | right_records)
                overlap_rows.append(
                    {
                        "topic_id": topic_id,
                        "left_query_variant_id": left_id,
                        "right_query_variant_id": right_id,
                        "intersection_count": intersection_count,
                        "union_count": union_count,
                        "jaccard": (
                            round(intersection_count / union_count, 6)
                            if union_count
                            else None
                        ),
                    }
                )

    pool_records_by_topic: dict[str, set[str]] = defaultdict(set)
    for member in inputs.pool_members.values():
        pool_records_by_topic[member["topic_id"]].add(member["record_id"])

    topic_rows: list[dict[str, Any]] = []
    global_unique_records: set[str] = set()
    global_topic_record_count = 0
    global_multi_query_count = 0
    global_single_query_count = 0
    for topic_id in sorted(inputs.topics):
        topic_run_ids = {
            run_id for run_id, run in runs.items() if run["topic_id"] == topic_id
        }
        topic_hits = [
            hit for hit in hits.values() if hit["retrieval_run_id"] in topic_run_ids
        ]
        retrieved_records = {hit["record_id"] for hit in topic_hits}
        global_unique_records.update(retrieved_records)
        global_topic_record_count += len(retrieved_records)
        record_query_memberships: dict[str, set[str]] = defaultdict(set)
        for key, record_ids in query_record_sets.items():
            if key[0] != topic_id:
                continue
            for record_id in record_ids:
                record_query_memberships[record_id].add(key[1])
        multi_query_count = sum(
            len(variant_ids) > 1 for variant_ids in record_query_memberships.values()
        )
        single_query_count = sum(
            len(variant_ids) == 1 for variant_ids in record_query_memberships.values()
        )
        global_multi_query_count += multi_query_count
        global_single_query_count += single_query_count
        pooled_records = pool_records_by_topic.get(topic_id, set())
        topic_rows.append(
            {
                "topic_id": topic_id,
                "run_count": len(topic_run_ids),
                "declared_query_variant_count": len(
                    inputs.topics[topic_id]["acquisition_query_variants"]
                ),
                "executed_query_variant_count": len(
                    {runs[run_id]["query_variant_id"] for run_id in topic_run_ids}
                ),
                "hit_count": len(topic_hits),
                "unique_record_count": len(retrieved_records),
                "multi_query_record_count": multi_query_count,
                "single_query_only_record_count": single_query_count,
                "retrieved_metadata": _metadata_quality_summary(
                    [records[record_id] for record_id in sorted(retrieved_records)]
                ),
                "precanonical_pool_member_count": len(pooled_records),
                "precanonical_pool_unique_record_count": len(pooled_records),
                "retrieved_not_pooled_count": len(retrieved_records - pooled_records),
                "pooled_not_retrieved_count": len(pooled_records - retrieved_records),
                "precanonical_pool_metadata": _metadata_quality_summary(
                    [records[record_id] for record_id in sorted(pooled_records)]
                ),
            }
        )

    pool_payload = inputs.payloads["precanonical_candidate_pool"]
    return {
        "summary": {
            "run_count": len(runs),
            "hit_count": len(hits),
            "declared_query_variant_count": len(declared_query_keys),
            "executed_query_variant_count": len(query_run_ids),
            "global_unique_record_count": len(global_unique_records),
            "topic_record_count": global_topic_record_count,
            "multi_query_topic_record_count": global_multi_query_count,
            "single_query_only_topic_record_count": global_single_query_count,
        },
        "runs": run_rows,
        "query_variants": query_rows,
        "pairwise_query_overlap": overlap_rows,
        "topics": topic_rows,
        "precanonical_pool": {
            "identity_stage": pool_payload["identity_stage"],
            "pool_identity": pool_payload["pool_identity"],
            "included_retrieval_run_count": len(
                pool_payload["policy"]["included_retrieval_run_ids"]
            ),
            "member_count": len(inputs.pool_members),
            "global_unique_record_count": len(
                {member["record_id"] for member in inputs.pool_members.values()}
            ),
            "topic_counts": [
                {"topic_id": topic_id, "count": count}
                for topic_id, count in sorted(pool_payload["topic_counts"].items())
            ],
        },
    }


def _metadata_quality_summary(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ordered_records = sorted(records, key=lambda row: str(row.get("record_id", "")))
    total = len(ordered_records)
    fields: dict[str, dict[str, Any]] = {}
    for field, path in METADATA_FIELD_SPECS:
        missing_count = sum(
            _is_missing(_metadata_value(record, field)) for record in ordered_records
        )
        fields[field] = {
            "field_path": path,
            "candidate_count": total,
            "present_count": total - missing_count,
            "missing_count": missing_count,
            "missing_rate": round(missing_count / total, 6) if total else None,
        }

    year_counts = Counter(
        record.get("publication_year")
        for record in ordered_records
        if not _is_missing(record.get("publication_year"))
    )
    venue_counts = Counter(
        str(record.get("venue"))
        for record in ordered_records
        if not _is_missing(record.get("venue"))
    )
    provider_counts = Counter(
        str(_metadata_value(record, "provider"))
        for record in ordered_records
        if not _is_missing(_metadata_value(record, "provider"))
    )
    return {
        "candidate_count": total,
        "fields": fields,
        "year_distribution": [
            {"publication_year": year, "count": count}
            for year, count in sorted(year_counts.items())
        ],
        "venue_distribution": [
            {"venue": venue, "count": count}
            for venue, count in sorted(venue_counts.items())
        ],
        "provider_distribution": [
            {"provider": provider, "count": count}
            for provider, count in sorted(provider_counts.items())
        ],
    }


def _metadata_csv_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scopes: list[tuple[str, str, Mapping[str, Any]]] = [
        ("source_records", "", report["metadata"])
    ]
    for topic in report["retrieval"]["topics"]:
        scopes.append(
            ("retrieved_topic", topic["topic_id"], topic["retrieved_metadata"])
        )
        scopes.append(
            (
                "precanonical_pool_topic",
                topic["topic_id"],
                topic["precanonical_pool_metadata"],
            )
        )
    scope_order = {
        "source_records": 0,
        "retrieved_topic": 1,
        "precanonical_pool_topic": 2,
    }
    for scope, topic_id, metadata in sorted(
        scopes, key=lambda item: (scope_order[item[0]], item[1])
    ):
        for field in METADATA_FIELD_NAMES:
            stats = metadata["fields"][field]
            rows.append(
                {
                    "scope": scope,
                    "topic_id": topic_id,
                    "field": field,
                    "field_path": stats["field_path"],
                    "candidate_count": stats["candidate_count"],
                    "present_count": stats["present_count"],
                    "missing_count": stats["missing_count"],
                    "missing_rate": (
                        f"{stats['missing_rate']:.6f}"
                        if stats["missing_rate"] is not None
                        else ""
                    ),
                }
            )
    return rows


def _metadata_value(record: Mapping[str, Any], field: str) -> Any:
    if field == "provider":
        provenance = record.get("record_provenance")
        return provenance.get("provider") if isinstance(provenance, Mapping) else None
    return record.get(field)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


def _require_timezone_datetime(value: str, label: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO-8601 string with timezone.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO-8601 datetime.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include timezone.")
