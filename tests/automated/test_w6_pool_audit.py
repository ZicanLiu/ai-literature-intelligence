"""Offline tests for the W6 pool bias audit (label-free, roster-closed)."""

from __future__ import annotations

import copy
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
            is_fixture=True,
        )
        cls.canonical = validate_canonical_entities(
            canonical, records=cls.records, retrieval=cls.retrieval
        )
        canonical_sha256 = canonical_json_sha256(canonical)
        cls.post_pool = build_post_canonical_pool(
            cls.pre_pool,
            canonical,
            artifact_id="w6_test_post_pool_v1",
            canonical_artifact_id=CANONICAL_ARTIFACT_ID,
            canonical_sha256=canonical_sha256,
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
            is_fixture=True,
        )
        cls.audit = audit_pool_bias(
            retrieval=cls.retrieval,
            post_pool_payload=cls.post_pool,
            canonical=cls.canonical,
            artifact_id="w6_test_audit_v1",
            pool_reference={"artifact_id": "w6_test_post_pool_v1", "sha256": "0" * 64},
            canonical_reference={
                "artifact_id": CANONICAL_ARTIFACT_ID,
                "sha256": canonical_sha256,
            },
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
            is_fixture=True,
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
        self.assertEqual(per_system["dense_fixture"]["unique_item_count"], 1)
        self.assertEqual(per_system["bm25_fixture"]["unique_item_count"], 1)

    def test_leave_one_retriever_out_record_level(self) -> None:
        loo = self.audit["record_level"]["leave_one_out"]
        self.assertEqual(loo["openalex_native"]["lost_item_count"], 3)
        self.assertEqual(loo["dense_fixture"]["lost_item_count"], 1)
        self.assertEqual(loo["bm25_fixture"]["lost_item_count"], 1)
        self.assertEqual(loo["deterministic_random_tail"]["lost_item_count"], 0)

    def test_leave_one_retriever_out_entity_level(self) -> None:
        loo = self.audit["entity_level"]["leave_one_out"]
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


class AuditRosterClosureTests(unittest.TestCase):
    def _audit(self, retrieval, post_pool, canonical=None) -> dict:
        canonical = canonical or {"entities": {}, "relationships": {}}
        return audit_pool_bias(
            retrieval=retrieval,
            post_pool_payload=post_pool,
            canonical=canonical,
            artifact_id="a",
            pool_reference={"artifact_id": "p", "sha256": "0" * 64},
            canonical_reference={"artifact_id": "c", "sha256": "0" * 64},
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
            is_fixture=True,
        )

    def _fixture_post_pool(self) -> tuple[dict, dict, dict]:
        bundle = validate_w6_bootstrap_bundle(BUNDLE_PATH)
        canonical_payload = build_canonical_entities(
            bundle["records"],
            artifact_id=CANONICAL_ARTIFACT_ID,
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
            is_fixture=True,
        )
        canonical = validate_canonical_entities(
            canonical_payload, records=bundle["records"], retrieval=bundle["retrieval"]
        )
        post_pool = build_post_canonical_pool(
            bundle["payloads"]["precanonical_candidate_pool"],
            canonical_payload,
            artifact_id="p",
            canonical_artifact_id=CANONICAL_ARTIFACT_ID,
            canonical_sha256=canonical_json_sha256(canonical_payload),
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
            is_fixture=True,
        )
        return bundle, canonical, post_pool

    def test_unknown_included_run_is_rejected(self) -> None:
        retrieval = {"runs": {}, "hits": {}}
        post_pool = {"policy": {"included_retrieval_run_ids": ["unknown_run"]}, "members": []}
        with self.assertRaisesRegex(ValueError, "unknown run"):
            self._audit(retrieval, post_pool)

    def test_member_hit_outside_frozen_roster_is_rejected(self) -> None:
        bundle, canonical_result, post_pool = self._fixture_post_pool()
        post_pool = copy.deepcopy(post_pool)
        # 从冻结 roster 删除一个 run，但其 member 仍引用该 run 的 hit。
        post_pool["policy"]["included_retrieval_run_ids"].remove("run_denoise_openalex")
        with self.assertRaisesRegex(ValueError, "不在 frozen included roster"):
            self._audit(bundle["retrieval"], post_pool, canonical_result)

    def test_missing_declared_system_is_rejected(self) -> None:
        bundle, canonical, post_pool = self._fixture_post_pool()
        tampered = copy.deepcopy(post_pool)
        member = next(
            item for item in tampered["members"]
            if len(item["source_system_membership"]) > 1
        )
        member["source_system_membership"] = member["source_system_membership"][:-1]
        with self.assertRaisesRegex(ValueError, "source_system_membership"):
            self._audit(bundle["retrieval"], tampered, canonical)

    def test_extra_declared_system_is_rejected(self) -> None:
        bundle, canonical, post_pool = self._fixture_post_pool()
        tampered = copy.deepcopy(post_pool)
        tampered["members"][0]["source_system_membership"].append("fabricated_system")
        with self.assertRaisesRegex(ValueError, "source_system_membership"):
            self._audit(bundle["retrieval"], tampered, canonical)

    def test_wrong_declared_system_is_rejected(self) -> None:
        bundle, canonical, post_pool = self._fixture_post_pool()
        tampered = copy.deepcopy(post_pool)
        tampered["members"][0]["source_system_membership"] = ["fabricated_system"]
        with self.assertRaisesRegex(ValueError, "source_system_membership"):
            self._audit(bundle["retrieval"], tampered, canonical)

    def test_conflicting_family_within_system_is_rejected(self) -> None:
        retrieval = {
            "runs": {
                "r1": {
                    "retrieval_run_id": "r1",
                    "acquisition_system": "sys_a",
                    "method": {"family": "sparse"},
                },
                "r2": {
                    "retrieval_run_id": "r2",
                    "acquisition_system": "sys_a",
                    "method": {"family": "dense"},
                },
            },
            "hits": {},
        }
        post_pool = {
            "policy": {"included_retrieval_run_ids": ["r1", "r2"]},
            "members": [],
        }
        with self.assertRaisesRegex(ValueError, "冲突的 family"):
            self._audit(retrieval, post_pool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
