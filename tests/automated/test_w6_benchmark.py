"""Issue #64 tests for W6 Topic freeze and Benchmark workflow."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.annotation_tasks import sha256_file
from src.w6_benchmark import (
    artifact_paths_from_bootstrap_bundle,
    build_review_plan_payload,
    build_w6_benchmark_package,
    compute_package_identity,
    validate_annotation_protocol,
    validate_benchmark_status_gate,
    validate_frozen_topic_roster,
    validate_topic_freeze_files,
    validate_w6_benchmark_package,
)
from src.w6_contracts import (
    compute_benchmark_identity,
    compute_split_identity,
    load_json_object,
    validate_topic_split,
    validate_w6_bootstrap_bundle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap" / "valid" / "bundle_manifest.json"
PROTOCOL = PROJECT_ROOT / "configs" / "w6" / "annotation_protocol_v1.json"
RESEARCH_ROOT = PROJECT_ROOT / "data" / "research" / "w6" / "v0.2-alpha"
BASE_REVISION = "90811052194801263708627c1eda39a2765e9037"


class W6TopicFreezeTests(unittest.TestCase):
    def test_real_topic_roster_and_topic_level_split_pass(self) -> None:
        result = validate_topic_freeze_files(
            RESEARCH_ROOT / "topics.json",
            RESEARCH_ROOT / "split_manifest.json",
            research_path=RESEARCH_ROOT / "topic_research.json",
        )
        self.assertEqual(len(result["topics"]), 9)
        self.assertEqual(len(result["split_sets"]["dev"]), 5)
        self.assertEqual(len(result["split_sets"]["hidden"]), 4)
        self.assertFalse(result["split_sets"]["dev"] & result["split_sets"]["hidden"])

    def test_near_duplicate_topic_question_fails(self) -> None:
        payload = load_json_object(RESEARCH_ROOT / "topics.json")
        duplicate = copy.deepcopy(payload["topics"][0])
        duplicate["topic_id"] = "w6_topic_duplicate_question"
        duplicate["research_question"] = payload["topics"][1]["research_question"]
        duplicate["acquisition_query_variants"][0]["query_variant_id"] = "dup_qv1"
        duplicate["acquisition_query_variants"][0]["query_text"] = "unique duplicate test query one"
        duplicate["acquisition_query_variants"][1]["query_variant_id"] = "dup_qv2"
        duplicate["acquisition_query_variants"][1]["query_text"] = "unique duplicate test query two"
        payload["topics"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "near-duplicate research question"):
            validate_frozen_topic_roster(payload)

    def test_scope_in_out_contradiction_fails(self) -> None:
        payload = load_json_object(RESEARCH_ROOT / "topics.json")
        payload["topics"][0]["scope_out"][0] = payload["topics"][0]["scope_in"][0]
        with self.assertRaisesRegex(ValueError, "自相矛盾"):
            validate_frozen_topic_roster(payload)

    def test_split_overlap_and_hash_drift_fail(self) -> None:
        topics = validate_frozen_topic_roster(load_json_object(RESEARCH_ROOT / "topics.json"))
        split = load_json_object(RESEARCH_ROOT / "split_manifest.json")
        split["hidden_test_topic_ids"].append(split["dev_topic_ids"][0])
        split["split_identity"] = compute_split_identity(split)
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_topic_split(split, topics=topics)

        split = load_json_object(RESEARCH_ROOT / "split_manifest.json")
        split["topic_set"]["sha256"] = "0" * 64
        split["split_identity"] = compute_split_identity(split)
        with tempfile.TemporaryDirectory() as temp_dir:
            split_path = Path(temp_dir) / "split.json"
            split_path.write_text(json.dumps(split), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "actual frozen Topic Set hash|实际 frozen Topic Set hash"):
                validate_topic_freeze_files(RESEARCH_ROOT / "topics.json", split_path)

    def test_split_chronology_fails(self) -> None:
        split = load_json_object(RESEARCH_ROOT / "split_manifest.json")
        split["frozen_at"] = "2026-08-24T14:00:00+08:00"
        split["split_identity"] = compute_split_identity(split)
        with tempfile.TemporaryDirectory() as temp_dir:
            split_path = Path(temp_dir) / "split.json"
            split_path.write_text(json.dumps(split), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不得早于 Topic Set"):
                validate_topic_freeze_files(RESEARCH_ROOT / "topics.json", split_path)


class W6AnnotationProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = validate_w6_bootstrap_bundle(BOOTSTRAP)
        cls.protocol = validate_annotation_protocol(load_json_object(PROTOCOL))

    def test_protocol_is_blind_evidence_backed_and_preregistered(self) -> None:
        protocol = self.protocol
        self.assertTrue(protocol["frozen_before_annotations"])
        self.assertFalse(protocol["review_policy"]["ranking_signals_allowed"])
        self.assertEqual(protocol["evidence_policy"]["private_reasoning_storage"], "forbidden")
        self.assertIn("lookup_status", protocol["evidence_policy"]["required_result_fields"])

    def test_blind_leakage_policy_drift_fails(self) -> None:
        protocol = copy.deepcopy(self.protocol)
        protocol["blind_view"]["forbidden_signals"].remove("rank")
        with self.assertRaisesRegex(ValueError, "leakage keys"):
            validate_annotation_protocol(protocol)

    def test_review_plan_is_deterministic_and_exposes_incomplete_review(self) -> None:
        kwargs = self._review_plan_kwargs()
        first = build_review_plan_payload(**kwargs)
        second = build_review_plan_payload(**kwargs)
        self.assertEqual(first, second)
        self.assertEqual(
            first["coverage"]["missing_review_annotation_ids"],
            ["annotation_denoise_005"],
        )
        reasons = {
            item["annotation_id"]: item["reasons"] for item in first["review_items"]
        }
        self.assertIn("nonempty_uncertainty", reasons["annotation_denoise_005"])

    def test_insufficient_evidence_enters_review_without_ranking_signal(self) -> None:
        kwargs = self._review_plan_kwargs()
        kwargs["evidence_lookup_statuses"] = {
            annotation_id: "not_needed" for annotation_id in self.bundle["annotations"]
        }
        kwargs["evidence_lookup_statuses"]["annotation_denoise_001"] = "insufficient"
        plan = build_review_plan_payload(**kwargs)
        item = next(
            row for row in plan["review_items"] if row["annotation_id"] == "annotation_denoise_001"
        )
        self.assertIn("evidence_insufficient", item["reasons"])
        self.assertNotIn("rank", json.dumps(plan))

    def test_non_independent_reviewer_fails(self) -> None:
        reviews = copy.deepcopy(self.bundle["reviews"])
        target = reviews["review_denoise_002"]
        target["reviewer_id"] = self.bundle["annotations"][target["annotation_id"]][
            "annotation_provenance"
        ]["actor_id"]
        kwargs = self._review_plan_kwargs()
        kwargs["reviews"] = reviews
        with self.assertRaisesRegex(ValueError, "reviewer 不独立"):
            build_review_plan_payload(**kwargs)

    def _review_plan_kwargs(self) -> dict:
        payloads = self.bundle["payloads"]
        return {
            "annotations": self.bundle["annotations"],
            "reviews": self.bundle["reviews"],
            "tasks": self.bundle["annotation_tasks"],
            "task_mappings": self.bundle["annotation_task_mappings"],
            "split_sets": self.bundle["split_sets"],
            "protocol": self.protocol,
            "protocol_reference": {"artifact_id": self.protocol["artifact_id"], "sha256": sha256_file(PROTOCOL)},
            "annotation_reference": self.bundle["registry"][payloads["annotation_results"]["artifact_id"]],
            "review_reference": self.bundle["registry"][payloads["annotation_reviews"]["artifact_id"]],
            "is_fixture": True,
            "created_at": "2026-08-24T14:25:00+08:00",
            "git_revision": BASE_REVISION,
        }


class W6BenchmarkPackageTests(unittest.TestCase):
    def _build(self, root: Path) -> Path:
        return build_w6_benchmark_package(
            artifact_paths=artifact_paths_from_bootstrap_bundle(BOOTSTRAP),
            annotation_protocol_path=PROTOCOL,
            output_dir=root / "benchmark",
            status="bootstrap_fixture",
            created_at="2026-08-24T14:25:00+08:00",
            git_revision=BASE_REVISION,
            git_worktree_clean=True,
        )

    def test_fixture_driven_builder_and_validator_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = validate_w6_benchmark_package(self._build(Path(temp_dir)))
        self.assertEqual(result["package"]["status"], "bootstrap_fixture")
        self.assertTrue(result["package"]["is_fixture"])
        self.assertEqual(result["benchmark"]["benchmark_version"], "w6_query_relevance_v0.2-alpha.bootstrap-fixture")
        self.assertEqual(result["review_plan"]["status"], "in_review")

    def test_package_hash_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = self._build(Path(temp_dir))
            package = load_json_object(package_path)
            topics_path = package_path.parent / package["artifacts"]["topic_set"]["path"]
            topics_path.write_text(topics_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash drift"):
                validate_w6_benchmark_package(package_path)

    def test_approved_self_promotion_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = self._build(Path(temp_dir))
            package = load_json_object(package_path)
            package["status"] = "approved"
            package["package_identity"] = compute_package_identity(package)
            package_path.write_text(json.dumps(package), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不得自报 approved"):
                validate_w6_benchmark_package(package_path)

    def test_proposed_gate_rejects_incomplete_dev_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = validate_w6_benchmark_package(self._build(Path(temp_dir)))
        with self.assertRaisesRegex(ValueError, "完整覆盖 Dev"):
            validate_benchmark_status_gate(
                "proposed", graph=result["graph"], review_plan=result["review_plan"]
            )

    def test_sealed_candidate_gate_rejects_incomplete_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = validate_w6_benchmark_package(self._build(Path(temp_dir)))
        graph = copy.deepcopy(result["graph"])
        annotated_pool_ids = {
            annotation["pool_item_id"] for annotation in graph["annotations"].values()
        }
        graph["pool_members"] = {
            item_id: member
            for item_id, member in graph["pool_members"].items()
            if item_id in annotated_pool_ids
        }
        with self.assertRaisesRegex(ValueError, "incomplete mandatory review"):
            validate_benchmark_status_gate(
                "sealed_candidate", graph=graph, review_plan=result["review_plan"]
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
