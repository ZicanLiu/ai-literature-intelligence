"""W6 candidate canonicalization: source records -> canonical paper entities.

Canonicalization is *not* deduplication-by-deletion. Every source record is kept,
and each record is mapped onto a canonical entity:

    record A ┐
             ├──> canonical entity X
    record B ┘

Only high-confidence *confirmed* identity may share one canonical entity:

    - exact normalized OpenAlex ID;
    - exact normalized DOI;
    - exact normalized title (guarded against conflicting DOI).

Low/medium-confidence similar records are *not* merged. They are emitted as
``suspected_duplicate`` relationships and remain two independent entities.

All record-level provenance (source record identity, alias, retrieval hits,
retrieval system, query variant, source rank/score) is preserved verbatim; the
post-canonical pool only adds ``canonical_entity_id`` per member.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Mapping

from src.w6_contracts import (
    W6_SCHEMA_VERSION,
    compute_pool_identity,
    normalize_doi,
    normalize_openalex_id,
    normalize_title,
)


CANONICALIZATION_TOOL = "w6_identity_mapper"
CANONICALIZATION_VERSION = "v1"
SUSPECTED_TITLE_RATIO_THRESHOLD = 0.80


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self._parent = {item: item for item in items}

    def find(self, item: str) -> str:
        parent = self._parent
        root = item
        while parent[root] != root:
            root = parent[root]
        while parent[item] != root:
            parent[item], item = root, parent[item]
        return root

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self._parent[root_left] = root_right


def _normalized_identity(record: Mapping[str, Any]) -> dict[str, str | None]:
    return {
        "openalex": (
            normalize_openalex_id(record["openalex_id"]) if record["openalex_id"] else None
        ),
        "doi": normalize_doi(record["doi"]) if record["doi"] else None,
        "title": normalize_title(record["title"]),
    }


def _cluster_records(records: Mapping[str, Any]) -> list[set[str]]:
    """Group records into confirmed canonical entities via union-find.

    Confirmed identity priority (strongest first): exact normalized OpenAlex ID,
    exact normalized DOI, exact normalized title. Title identity is accepted only
    when the title group does not contain conflicting non-empty DOIs.
    """
    record_ids = list(records)
    union_find = _UnionFind(record_ids)
    identities = {record_id: _normalized_identity(records[record_id]) for record_id in record_ids}

    by_doi: dict[str, list[str]] = defaultdict(list)
    by_openalex: dict[str, list[str]] = defaultdict(list)
    by_title: dict[str, list[str]] = defaultdict(list)
    for record_id in record_ids:
        identity = identities[record_id]
        if identity["doi"]:
            by_doi[identity["doi"]].append(record_id)
        if identity["openalex"]:
            by_openalex[identity["openalex"]].append(record_id)
        by_title[identity["title"]].append(record_id)

    for group in by_doi.values():
        for record_id in group[1:]:
            union_find.union(group[0], record_id)
    for group in by_openalex.values():
        for record_id in group[1:]:
            union_find.union(group[0], record_id)
    for group in by_title.values():
        if len(group) < 2:
            continue
        dois = {identities[record_id]["doi"] for record_id in group if identities[record_id]["doi"]}
        if len(dois) > 1:
            # Conflicting identity: identical title but different DOIs. Do not merge;
            # these records stay independent and become a suspected relationship.
            continue
        for record_id in group[1:]:
            union_find.union(group[0], record_id)

    groups: dict[str, set[str]] = defaultdict(set)
    for record_id in record_ids:
        groups[union_find.find(record_id)].add(record_id)
    return [set(group) for group in groups.values()]


def _preferred_record(group: set[str], records: Mapping[str, Any]) -> str:
    """Deterministic preferred-record selection.

    Prefer most complete metadata, then a DOI, then an abstract, then the smallest
    record_id.
    """

    def key(record_id: str) -> tuple:
        record = records[record_id]
        score = float(record["metadata_completeness"]["completeness_score"])
        return (-score, not bool(record["doi"]), not bool(record["abstract"]), record_id)

    return sorted(group, key=key)[0]


def _build_entity(
    group: set[str],
    records: Mapping[str, Any],
    *,
    tool: str,
    version: str,
    created_at: str,
    git_revision: str,
    reviewer: str | None,
) -> dict[str, Any]:
    aliases = sorted(group)
    preferred = _preferred_record(group, records)
    openalex_ids = sorted(
        {normalize_openalex_id(records[r]["openalex_id"]) for r in aliases if records[r]["openalex_id"]}
    )
    dois = sorted(
        {normalize_doi(records[r]["doi"]) for r in aliases if records[r]["doi"]}
    )
    union = sorted(
        {hit_id for r in aliases for hit_id in records[r]["acquisition_provenance_refs"]}
    )

    evidence: list[dict[str, Any]] = []
    for openalex_id in openalex_ids:
        evidence.append(
            {
                "evidence_type": "openalex_id",
                "value": openalex_id,
                "record_ids": sorted(
                    r
                    for r in aliases
                    if records[r]["openalex_id"]
                    and normalize_openalex_id(records[r]["openalex_id"]) == openalex_id
                ),
            }
        )
    for doi in dois:
        evidence.append(
            {
                "evidence_type": "normalized_doi",
                "value": doi,
                "record_ids": sorted(
                    r
                    for r in aliases
                    if records[r]["doi"] and normalize_doi(records[r]["doi"]) == doi
                ),
            }
        )
    evidence.append(
        {
            "evidence_type": "normalized_title",
            "value": normalize_title(records[preferred]["title"]),
            "record_ids": aliases,
        }
    )

    return {
        "canonical_entity_id": f"entity_{preferred}",
        "preferred_record_id": preferred,
        "normalized_openalex_ids": openalex_ids,
        "normalized_dois": dois,
        "normalized_title": normalize_title(records[preferred]["title"]),
        "alias_record_ids": aliases,
        "identity_evidence": evidence,
        "identity_confidence": "high",
        "review_state": "confirmed",
        "canonicalization_provenance": {
            "tool": tool,
            "version": version,
            "created_at": created_at,
            "git_revision": git_revision,
            "reviewer": reviewer,
        },
        "source_retrieval_provenance_union": union,
    }


def _suspected_evidence(ratio: float, *, doi_conflict: bool) -> list[str]:
    if doi_conflict:
        return ["identical normalized title with conflicting DOI identity"]
    evidence = ["similar normalized titles"]
    if ratio >= 1.0:
        evidence[0] = "identical normalized title"
    return evidence


def build_canonical_entities(
    records: Mapping[str, Any],
    *,
    artifact_id: str,
    created_at: str,
    git_revision: str,
    tool: str = CANONICALIZATION_TOOL,
    version: str = CANONICALIZATION_VERSION,
    reviewer: str | None = None,
    provenance_kind: str = "canonicalization_run",
    provenance_created_by: str = "w6_canonicalization",
    is_fixture: bool = True,
) -> dict[str, Any]:
    """Build a ``w6_canonical_entities`` payload from source records.

    The mapping is deterministic given the same ``records``: entity IDs, preferred
    records, alias groups and suspected relationships depend only on record
    identity, not on input order or time.
    """
    groups = _cluster_records(records)
    entities_by_id: dict[str, dict[str, Any]] = {}
    for group in groups:
        entity = _build_entity(
            group,
            records,
            tool=tool,
            version=version,
            created_at=created_at,
            git_revision=git_revision,
            reviewer=reviewer,
        )
        entities_by_id[entity["canonical_entity_id"]] = entity

    record_to_entity = {
        record_id: entity_id
        for entity_id, entity in entities_by_id.items()
        for record_id in entity["alias_record_ids"]
    }

    relationships: dict[str, dict[str, Any]] = {}
    entity_ids = sorted(entities_by_id)
    for left_index in range(len(entity_ids)):
        for right_index in range(left_index + 1, len(entity_ids)):
            left_id = entity_ids[left_index]
            right_id = entity_ids[right_index]
            left_title = normalize_title(
                records[entities_by_id[left_id]["preferred_record_id"]]["title"]
            )
            right_title = normalize_title(
                records[entities_by_id[right_id]["preferred_record_id"]]["title"]
            )
            ratio = SequenceMatcher(None, left_title, right_title).ratio()
            if ratio < SUSPECTED_TITLE_RATIO_THRESHOLD:
                continue
            doi_conflict = ratio >= 1.0
            relationship_id = f"suspect_{left_id}_{right_id}"
            relationships[relationship_id] = {
                "relationship_id": relationship_id,
                "entity_ids": [left_id, right_id],
                "relationship_type": "suspected_duplicate",
                "review_state": "pending_review",
                "confidence": "medium",
                "evidence": _suspected_evidence(ratio, doi_conflict=doi_conflict),
                "provenance": {
                    "kind": provenance_kind,
                    "created_by": provenance_created_by,
                    "created_at": created_at,
                    "git_revision": git_revision,
                },
            }

    return {
        "schema_version": W6_SCHEMA_VERSION,
        "artifact_type": "w6_canonical_entities",
        "artifact_id": artifact_id,
        "is_fixture": is_fixture,
        "created_at": created_at,
        "provenance": {
            "kind": provenance_kind,
            "created_by": provenance_created_by,
            "created_at": created_at,
            "git_revision": git_revision,
        },
        "entities": [entities_by_id[entity_id] for entity_id in entity_ids],
        "suspected_relationships": [
            relationships[relationship_id] for relationship_id in sorted(relationships)
        ],
    }


def entity_record_mapping(canonical_payload: Mapping[str, Any]) -> dict[str, str]:
    """Derive record_id -> canonical_entity_id from a canonical entities payload."""
    mapping: dict[str, str] = {}
    for entity in canonical_payload["entities"]:
        for record_id in entity["alias_record_ids"]:
            mapping[record_id] = entity["canonical_entity_id"]
    return mapping


def build_post_canonical_pool(
    pre_pool_payload: Mapping[str, Any],
    canonical_payload: Mapping[str, Any],
    *,
    artifact_id: str,
    canonical_artifact_id: str,
    canonical_sha256: str,
    created_at: str,
    git_revision: str,
    provenance_kind: str = "canonicalization_run",
    provenance_created_by: str = "w6_canonicalization",
    is_fixture: bool = True,
) -> dict[str, Any]:
    """Deterministically transform a pre-canonical pool into a post-canonical pool.

    Every pre-pool member is retained unchanged except that its
    ``canonical_entity_id`` is filled from the canonical mapping; the pool
    ``identity_stage``, ``inputs`` and deterministic ``pool_identity`` are updated.
    """
    post_pool = copy.deepcopy(dict(pre_pool_payload))
    record_to_entity = entity_record_mapping(canonical_payload)
    for member in post_pool["members"]:
        member["canonical_entity_id"] = record_to_entity[member["record_id"]]

    post_pool["artifact_id"] = artifact_id
    post_pool["identity_stage"] = "post_canonicalization"
    post_pool["created_at"] = created_at
    post_pool["provenance"] = {
        "kind": provenance_kind,
        "created_by": provenance_created_by,
        "created_at": created_at,
        "git_revision": git_revision,
    }
    post_pool["is_fixture"] = is_fixture
    post_pool["inputs"]["canonical_entities"] = {
        "artifact_id": canonical_artifact_id,
        "sha256": canonical_sha256,
    }
    post_pool["pool_identity"] = compute_pool_identity(post_pool)
    return post_pool
