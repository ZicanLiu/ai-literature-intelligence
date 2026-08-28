"""W6 pool bias audit: retriever overlap / unique contribution / multi-system
support / leave-one-retriever-out / record-vs-entity alias sensitivity.

This audit reads only the frozen retrieval provenance, source records, pool
membership and canonical mapping. It never reads relevance labels, metrics or
error analysis, and it never interprets pooled coverage as real recall.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping

from src.w6_contracts import W6_SCHEMA_VERSION


def _system_families(
    retrieval: Mapping[str, Any], included_run_ids: set[str]
) -> dict[str, str]:
    families: dict[str, str] = {}
    for run in retrieval["runs"].values():
        if run["retrieval_run_id"] in included_run_ids:
            families[run["acquisition_system"]] = run["method"]["family"]
    return families


def _item_systems(pool_members: Mapping[str, Any], *, entity_level: bool) -> dict[str, set[str]]:
    item_systems: dict[str, set[str]] = defaultdict(set)
    for member in pool_members.values():
        key = member["canonical_entity_id"] if entity_level else member["record_id"]
        item_systems[key].update(member["source_system_membership"])
    return dict(item_systems)


def _per_system_report(
    systems: list[str], item_systems: Mapping[str, set[str]]
) -> dict[str, dict[str, Any]]:
    items = list(item_systems)
    total = len(items)
    report: dict[str, dict[str, Any]] = {}
    for system in systems:
        supported = {item for item in items if system in item_systems[item]}
        unique = {item for item in items if item_systems[item] == {system}}
        report[system] = {
            "retrieved_item_count": len(supported),
            "unique_item_count": len(unique),
            "unique_item_ratio": round(len(unique) / total, 6) if total else 0.0,
        }
    return report


def _pairwise_overlap(
    systems: list[str], item_systems: Mapping[str, set[str]]
) -> dict[str, dict[str, int]]:
    return {
        left: {
            right: sum(
                1
                for item in item_systems
                if left in item_systems[item] and right in item_systems[item]
            )
            for right in systems
        }
        for left in systems
    }


def _multi_system_support(item_systems: Mapping[str, set[str]]) -> dict[str, int]:
    histogram = Counter(len(systems) for systems in item_systems.values())
    return {str(support): histogram[support] for support in sorted(histogram)}


def _leave_one_out(
    systems: list[str], item_systems: Mapping[str, set[str]]
) -> dict[str, dict[str, Any]]:
    items = list(item_systems)
    total = len(items)
    report: dict[str, dict[str, Any]] = {}
    for system in systems:
        lost = {item for item in items if item_systems[item] == {system}}
        report[system] = {
            "lost_item_count": len(lost),
            "lost_item_ratio": round(len(lost) / total, 6) if total else 0.0,
        }
    return report


def audit_pool_bias(
    *,
    retrieval: Mapping[str, Any],
    pool_members: Mapping[str, Any],
    canonical: Mapping[str, Any],
    included_run_ids: list[str],
    artifact_id: str,
    pool_reference: Mapping[str, str],
    canonical_reference: Mapping[str, str],
    created_at: str,
    git_revision: str,
    provenance_kind: str = "pool_bias_audit",
    provenance_created_by: str = "w6_pool_audit",
    is_fixture: bool = True,
) -> dict[str, Any]:
    """Produce a deterministic, label-free bias audit over a post-canonical pool."""
    included = set(included_run_ids)
    systems = sorted(
        {
            run["acquisition_system"]
            for run in retrieval["runs"].values()
            if run["retrieval_run_id"] in included
        }
    )
    system_families = _system_families(retrieval, included)

    record_systems = _item_systems(pool_members, entity_level=False)
    entity_systems = _item_systems(pool_members, entity_level=True)

    total_pool_items = len(pool_members)
    distinct_records = len(record_systems)
    distinct_entities = len(entity_systems)
    alias_entity_count = sum(
        1
        for entity in canonical["entities"].values()
        if len(entity["alias_record_ids"]) > 1
    )
    suspected_relationship_count = len(canonical["relationships"])

    return {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": "w6_pool_bias_audit",
        "artifact_id": artifact_id,
        "is_fixture": is_fixture,
        "created_at": created_at,
        "provenance": {
            "kind": provenance_kind,
            "created_by": provenance_created_by,
            "created_at": created_at,
            "git_revision": git_revision,
        },
        "label_access": {
            "relevance_labels_read": False,
            "declaration": (
                "Pool bias audit reads only retrieval provenance, source records, "
                "pool membership and canonical mapping; no relevance labels, metrics "
                "or error analysis were read, and pooled coverage is not recall."
            ),
        },
        "inputs": {
            "candidate_pool": dict(pool_reference),
            "canonical_entities": dict(canonical_reference),
        },
        "included_retrieval_run_ids": sorted(included_run_ids),
        "acquisition_systems": systems,
        "system_family": {system: system_families.get(system, "unknown") for system in systems},
        "record_level": {
            "total_records": distinct_records,
            "per_system": _per_system_report(systems, record_systems),
            "pairwise_overlap": _pairwise_overlap(systems, record_systems),
            "multi_system_support": _multi_system_support(record_systems),
            "leave_one_out": _leave_one_out(systems, record_systems),
        },
        "entity_level": {
            "total_entities": distinct_entities,
            "per_system": _per_system_report(systems, entity_systems),
            "pairwise_overlap": _pairwise_overlap(systems, entity_systems),
            "multi_system_support": _multi_system_support(entity_systems),
            "leave_one_out": _leave_one_out(systems, entity_systems),
        },
        "alias_sensitivity": {
            "total_pool_items": total_pool_items,
            "distinct_source_records": distinct_records,
            "distinct_canonical_entities": distinct_entities,
            "confirmed_alias_entity_count": alias_entity_count,
            "suspected_relationship_count": suspected_relationship_count,
            "record_to_entity_ratio": (
                round(distinct_records / distinct_entities, 6) if distinct_entities else 0.0
            ),
        },
    }
