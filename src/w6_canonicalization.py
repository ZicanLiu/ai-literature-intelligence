"""W6 candidate canonicalization: source records -> canonical paper entities.

Canonicalization is *not* deduplication-by-deletion. Every source record is kept,
and each record is mapped onto a canonical entity:

    record A ┐
             ├──> canonical entity X
    record B ┘

Only high-confidence *confirmed* identity may share one canonical entity:

    - exact normalized DOI (authoritative; may reconcile different provider
      OpenAlex IDs);
    - exact normalized OpenAlex ID (only when it does not produce a DOI conflict);
    - exact normalized title (only when non-generic and free of DOI / OpenAlex
      conflict).

A confirmed component must stay identity-consistent: at most one distinct
non-empty DOI, and multiple OpenAlex IDs only when reconciled by a shared DOI.
Conflicting identities are never auto-merged; they stay independent and become a
``suspected_duplicate`` relationship.

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
MIN_TITLE_IDENTITY_TOKENS = 3


def _normalized_identity(record: Mapping[str, Any]) -> dict[str, str | None]:
    return {
        "openalex": (
            normalize_openalex_id(record["openalex_id"]) if record["openalex_id"] else None
        ),
        "doi": normalize_doi(record["doi"]) if record["doi"] else None,
        "title": normalize_title(record["title"]),
    }


def _title_is_strong(title: str) -> bool:
    return len(title.split()) >= MIN_TITLE_IDENTITY_TOKENS


class _UnionFind:
    """Union-find that retains component-level strong-identity provenance."""

    def __init__(self, record_ids: list[str], identities: Mapping[str, Mapping[str, str | None]]) -> None:
        self._parent = {rid: rid for rid in record_ids}
        self._dois = {
            rid: frozenset({identities[rid]["doi"]}) if identities[rid]["doi"] else frozenset()
            for rid in record_ids
        }
        self._openalex = {
            rid: frozenset({identities[rid]["openalex"]}) if identities[rid]["openalex"] else frozenset()
            for rid in record_ids
        }

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
        if root_left == root_right:
            return
        # Keep the representative deterministic even if callers enumerate an
        # identity group in a different order.
        if root_right < root_left:
            root_left, root_right = root_right, root_left
        self._parent[root_right] = root_left
        self._dois[root_left] = self._dois[root_left] | self._dois[root_right]
        self._openalex[root_left] = self._openalex[root_left] | self._openalex[root_right]

    def roots_for(self, record_ids: list[str]) -> list[str]:
        return sorted({self.find(record_id) for record_id in record_ids})

    def identifiers_for(
        self, record_ids: list[str]
    ) -> tuple[frozenset[str], list[frozenset[str]]]:
        roots = self.roots_for(record_ids)
        dois = frozenset().union(*(self._dois[root] for root in roots))
        openalex_sets = [self._openalex[root] for root in roots if self._openalex[root]]
        return dois, openalex_sets

    def union_all(self, record_ids: list[str]) -> None:
        roots = self.roots_for(record_ids)
        if not roots:
            return
        anchor = roots[0]
        for root in roots[1:]:
            self.union(anchor, root)


def _openalex_group_is_compatible(
    union_find: _UnionFind, record_ids: list[str]
) -> bool:
    """An exact OpenAlex group may merge only without a DOI conflict."""
    dois, _ = union_find.identifiers_for(record_ids)
    return len(dois) <= 1


def _title_group_is_compatible(
    union_find: _UnionFind, record_ids: list[str]
) -> bool:
    """Require one unambiguous strong-identity interpretation for a title group.

    A DOI already present somewhere in one component cannot reconcile an unrelated
    OpenAlex identity from another component.  If multiple components carry
    OpenAlex identities, they must share an actual OpenAlex identity; components
    with no OpenAlex identity may join only when the whole title group remains
    unambiguous.  Evaluating the complete group avoids greedy/union-order choices
    for a title-only record between conflicting strong identities.
    """
    dois, openalex_sets = union_find.identifiers_for(record_ids)
    if len(dois) > 1:
        return False
    if len(openalex_sets) <= 1:
        return True
    return bool(set.intersection(*(set(values) for values in openalex_sets)))


def _cluster_records(records: Mapping[str, Any]) -> list[set[str]]:
    """Group records into confirmed canonical entities (identity-consistent)."""
    record_ids = sorted(records)
    identities = {rid: _normalized_identity(records[rid]) for rid in record_ids}
    union_find = _UnionFind(record_ids, identities)

    # Phase A — DOI (authoritative): same DOI always merges.
    by_doi: dict[str, list[str]] = defaultdict(list)
    for rid in record_ids:
        if identities[rid]["doi"]:
            by_doi[identities[rid]["doi"]].append(rid)
    for doi in sorted(by_doi):
        union_find.union_all(by_doi[doi])

    # Phase B — OpenAlex: merge only if the component stays DOI-consistent.
    by_openalex: dict[str, list[str]] = defaultdict(list)
    for rid in record_ids:
        if identities[rid]["openalex"]:
            by_openalex[identities[rid]["openalex"]].append(rid)
    for openalex_id in sorted(by_openalex):
        group = by_openalex[openalex_id]
        if _openalex_group_is_compatible(union_find, group):
            union_find.union_all(group)

    # Phase C — exact normalized title: only non-generic and conflict-free.
    by_title: dict[str, list[str]] = defaultdict(list)
    for rid in record_ids:
        title = identities[rid]["title"]
        if _title_is_strong(title):
            by_title[title].append(rid)
    for title in sorted(by_title):
        group = by_title[title]
        if _title_group_is_compatible(union_find, group):
            union_find.union_all(group)

    groups: dict[str, set[str]] = defaultdict(set)
    for rid in record_ids:
        groups[union_find.find(rid)].add(rid)
    return [set(group) for group in groups.values()]


def _preferred_record(group: set[str], records: Mapping[str, Any]) -> str:
    """Deterministic preferred-record selection (display attribute only)."""

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
    title_records: dict[str, list[str]] = defaultdict(list)
    for record_id in aliases:
        title_records[normalize_title(records[record_id]["title"])].append(record_id)
    for title, record_ids in sorted(title_records.items()):
        if len(record_ids) >= 2:
            evidence.append(
                {
                    "evidence_type": "normalized_title",
                    "value": title,
                    "record_ids": sorted(record_ids),
                }
            )
    if not evidence:
        # A record without OpenAlex/DOI still needs its title as identity evidence.
        evidence.append(
            {
                "evidence_type": "normalized_title",
                "value": normalize_title(records[preferred]["title"]),
                "record_ids": aliases,
            }
        )

    return {
        "canonical_entity_id": f"entity_{aliases[0]}",
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


def _suspected_evidence(
    entity: Mapping[str, Any], other: Mapping[str, Any], title_ratio: float
) -> list[str]:
    shared_openalex = set(entity["normalized_openalex_ids"]) & set(
        other["normalized_openalex_ids"]
    )
    if shared_openalex:
        return ["shared OpenAlex with conflicting DOI"]
    if title_ratio >= 1.0:
        entity_dois = set(entity["normalized_dois"])
        other_dois = set(other["normalized_dois"])
        if entity_dois and other_dois and entity_dois != other_dois:
            return ["identical normalized title with conflicting DOI"]
        entity_openalex = set(entity["normalized_openalex_ids"])
        other_openalex = set(other["normalized_openalex_ids"])
        if entity_openalex and other_openalex and entity_openalex != other_openalex:
            return ["identical normalized title with conflicting OpenAlex"]
        return ["identical normalized title"]
    return ["similar normalized titles"]


def build_canonical_entities(
    records: Mapping[str, Any],
    *,
    artifact_id: str,
    created_at: str,
    git_revision: str,
    is_fixture: bool,
    tool: str = CANONICALIZATION_TOOL,
    version: str = CANONICALIZATION_VERSION,
    reviewer: str | None = None,
    provenance_kind: str = "canonicalization_run",
    provenance_created_by: str = "w6_canonicalization",
) -> dict[str, Any]:
    """Build a ``w6_canonical_entities`` payload from source records.

    Deterministic given the same ``records``: entity IDs, preferred records, alias
    groups and suspected relationships depend only on record identity, not on
    input order or time.
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

    relationships: dict[str, dict[str, Any]] = {}
    entity_ids = sorted(entities_by_id)
    for left_index in range(len(entity_ids)):
        for right_index in range(left_index + 1, len(entity_ids)):
            left_id = entity_ids[left_index]
            right_id = entity_ids[right_index]
            left_entity = entities_by_id[left_id]
            right_entity = entities_by_id[right_id]
            left_titles = {
                normalize_title(records[record_id]["title"])
                for record_id in left_entity["alias_record_ids"]
            }
            right_titles = {
                normalize_title(records[record_id]["title"])
                for record_id in right_entity["alias_record_ids"]
            }
            ratio = max(
                SequenceMatcher(None, left_title, right_title).ratio()
                for left_title in left_titles
                for right_title in right_titles
            )
            shared_openalex = bool(
                set(left_entity["normalized_openalex_ids"])
                & set(right_entity["normalized_openalex_ids"])
            )
            if ratio < SUSPECTED_TITLE_RATIO_THRESHOLD and not shared_openalex:
                continue
            relationship_id = f"suspect_{left_id}_{right_id}"
            relationships[relationship_id] = {
                "relationship_id": relationship_id,
                "entity_ids": [left_id, right_id],
                "relationship_type": "suspected_duplicate",
                "review_state": "pending_review",
                "confidence": "medium",
                "evidence": _suspected_evidence(left_entity, right_entity, ratio),
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
    is_fixture: bool,
    provenance_kind: str = "canonicalization_run",
    provenance_created_by: str = "w6_canonicalization",
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
