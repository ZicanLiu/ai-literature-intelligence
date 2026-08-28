"""Offline tests for the W6 pool bias audit (label-free)."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.w6_canonicalization import build_canonical_entities, build_post_canonical_pool
from src.w6_contracts import (
    canonical_json_sha256,
    validate_candidate_pool,
    validate_canonical_entities,
    validate_w6_bootstrap_bundle,
)
from src.w6_pool_audit import audit_pool_bias


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap" / "valid" / "bundle_manifest.json"
)
GIT_REVISION = "6b9eb12f898bf880c297902463e48f2ff3e0388b"
CREATED_AT = "2026-08-25T09:00:00+08:00"
CANONICAL_ARTIFACT_ID = "w6_test_canonical_entities_v1"


class PoolBiasAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = validate_w6_bootstrap_bundle(BUNDLE_PATH)
        cls.records = cls.bundle["records"]
        cls.retrieval = cls.bundle["retrieval"]
        cls.topics = cls.bundle["topics"]
        cls.pre_pool = cls.bundle["payloads"]["precanonical_candidate_pool"]

        canonical = build_canonical_entities(
            cls.records,
            artifact_id=CANONICAL_ARTIFACT_ID,
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )
        cls.canonical = validate_canonical_entities(
            canonical, records=cls.records, retrieval=cls.retrieval
        )
        canonical_sha256 = canonical_json_sha256(canonical)
        post_pool = build_post_canonical_pool(
            cls.pre_pool,
            canonical,
            artifact_id="w6_test_post_pool_v1",
            canonical_artifact_id=CANONICAL_ARTIFACT_ID,
            canonical_sha256=canonical_sha256,
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )
        registry = dict(cls.bundle["registry"])
        registry[CANONICAL_ARTIFACT_ID] = {
            "artifact_id": CANONICAL_ARTIFACT_ID,
            "sha256": canonical_sha256,
        }
        cls.pool_members = validate_candidate_pool(
            post_pool,
            topics=cls.topics,
            records=cls.records,
            retrieval=cls.retrieval,
            registry=registry,
            canonical=cls.canonical,
        )
        cls.audit = audit_pool_bias(
            retrieval=cls.retrieval,
            pool_members=cls.pool_members,
            canonical=cls.canonical,
            included_run_ids=post_pool["policy"]["included_retrieval_run_ids"],
            artifact_id="w6_test_audit_v1",
            pool_reference={"artifact_id": "w6_test_post_pool_v1", "sha256": "0" * 64},
            canonical_reference={
                "artifact_id": CANONICAL_ARTIFACT_ID,
                "sha256": canonical_sha256,
            },
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
        )

    def test_audit_declares_label_free(self) -> None:
        self.assertFalse(self.audit["label_access"]["relevance_labels_read"])

    def test_record_and_entity_counts(self) -> None:
        sensitivity = self.audit["alias_sensitivity"]
        self.assertEqual(sensitivity["total_pool_items"], 13)
        self.assertEqual(sensitivity["distinct_source_records"], 10)
        self.assertEqual(sensitivity["distinct_canonical_entities"], 9)
        self.assertEqual(sensitivity["confirmed_alias_entity_count"], 1)
        self.assertEqual(sensitivity["suspected_relationship_count"], 1)

    def test_multi_system_support_histogram(self) -> None:
        record_histogram = self.audit["record_level"]["multi_system_support"]
        self.assertEqual(sum(record_histogram.values()), 10)
        self.assertIn("2", record_histogram)

    def test_unique_contribution_counts(self) -> None:
        per_system = self.audit["record_level"]["per_system"]
        # rec_009 is found only by the dense retriever.
        self.assertEqual(per_system["dense_fixture"]["unique_item_count"], 1)
        # rec_005 is found only by bm25.
        self.assertEqual(per_system["bm25_fixture"]["unique_item_count"], 1)

    def test_leave_one_retriever_out_record_level(self) -> None:
        loo = self.audit["record_level"]["leave_one_out"]
        self.assertEqual(loo["openalex_native"]["lost_item_count"], 3)
        self.assertEqual(loo["dense_fixture"]["lost_item_count"], 1)
        self.assertEqual(loo["bm25_fixture"]["lost_item_count"], 1)
        self.assertEqual(loo["deterministic_random_tail"]["lost_item_count"], 0)

    def test_leave_one_retriever_out_entity_level(self) -> None:
        loo = self.audit["entity_level"]["leave_one_out"]
        # rec_008 (openalex-only) is an alias of entity_rec_003, which is also hit
        # by bm25 through rec_003; so entity-level openalex-only loss is lower.
        self.assertEqual(loo["openalex_native"]["lost_item_count"], 2)
        self.assertEqual(loo["dense_fixture"]["lost_item_count"], 1)

    def test_alias_sensitivity_record_vs_entity_differs(self) -> None:
        record_loo = self.audit["record_level"]["leave_one_out"]["openalex_native"]
        entity_loo = self.audit["entity_level"]["leave_one_out"]["openalex_native"]
        self.assertGreater(record_loo["lost_item_count"], entity_loo["lost_item_count"])

    def test_pairwise_overlap_is_symmetric(self) -> None:
        overlap = self.audit["record_level"]["pairwise_overlap"]
        systems = self.audit["acquisition_systems"]
        for left in systems:
            for right in systems:
                self.assertEqual(overlap[left][right], overlap[right][left])

    def test_system_family_mapping(self) -> None:
        families = self.audit["system_family"]
        self.assertEqual(families["bm25_fixture"], "sparse")
        self.assertEqual(families["dense_fixture"], "dense")


if __name__ == "__main__":
    unittest.main(verbosity=2)
