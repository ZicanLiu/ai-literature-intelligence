"""W6 pool bias audit: retriever overlap / unique contribution / multi-system
support / leave-one-retriever-out / record-vs-entity alias sensitivity.

The audit derives its retriever roster strictly from the frozen post-canonical
pool policy (``included_retrieval_run_ids``) and validates the closure between pool
member hits, retrieval runs, acquisition systems and that frozen roster. It never
reads relevance labels, metrics or error analysis, and never interprets pooled
coverage as real recall.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping

from src.w6_contracts import W6_SCHEMA_VERSION


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


def _derive_system_families(
    retrieval: Mapping[str, Any], included: set[str]
) -> dict[str, str]:
    runs = retrieval["runs"]
    unknown = sorted(included - set(runs))
    if unknown:
        raise ValueError(
            "audit included_retrieval_run_ids 引用 unknown run：" + ", ".join(unknown)
        )
    families: dict[str, str] = {}
    for run in runs.values():
        if run["retrieval_run_id"] not in included:
            continue
        system = run["acquisition_system"]
        family = run["method"]["family"]
        if system in families and families[system] != family:
            raise ValueError(
                f"acquisition_system {system} 在 included runs 中声明了冲突的 family："
                f"{families[system]} vs {family}"
            )
        families[system] = family
    return families


def audit_pool_bias(
    *,
    retrieval: Mapping[str, Any],
    post_pool_payload: Mapping[str, Any],
    canonical: Mapping[str, Any],
    artifact_id: str,
    pool_reference: Mapping[str, str],
    canonical_reference: Mapping[str, str],
    created_at: str,
    git_revision: str,
    is_fixture: bool,
    provenance_kind: str = "pool_bias_audit",
    provenance_created_by: str = "w6_pool_audit",
) -> dict[str, Any]:
    """Produce a deterministic, label-free bias audit over a post-canonical pool.

    The retriever roster is derived from the frozen pool policy, not from a
    caller-supplied argument, and is closed against the retrieval provenance.
    """
    included_run_ids = list(post_pool_payload["policy"]["included_retrieval_run_ids"])
    included = set(included_run_ids)
    system_families = _derive_system_families(retrieval, included)
    systems = sorted(system_families)

    pool_members = {
        member["pool_item_id"]: member for member in post_pool_payload["members"]
    }
    # Defensive closure: every pooled hit must belong to the frozen included roster.
    hits = retrieval["hits"]
    for member in pool_members.values():
        for hit_id in member["retrieval_hit_ids"]:
            hit = hits.get(hit_id)
            if hit is None or hit["retrieval_run_id"] not in included:
                raise ValueError(
                    f"pool member {member['pool_item_id']} 的 retrieval hit "
                    f"{hit_id} 不在 frozen included roster。"
                )

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
        "system_family": {system: system_families[system] for system in systems},
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
