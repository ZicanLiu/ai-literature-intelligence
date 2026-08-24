"""Issue #64 tests for the label-free Boundary-Aware ranking prototype."""

from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path

from src.w6_boundary_ranking import (
    BOUNDARY_DIMENSIONS,
    BoundaryAssessment,
    BoundaryRankingConfig,
    DeterministicFakeBoundaryBackend,
    DeterministicLexicalBoundaryBackend,
    build_boundary_aware_rankings,
    build_w6_boundary_method_package,
    load_boundary_ranking_config,
)
from src.w6_contracts import load_json_object, validate_w6_bootstrap_bundle
from src.w6_method_contract import validate_w6_method_package


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap" / "valid" / "bundle_manifest.json"
CONFIG = PROJECT_ROOT / "configs" / "w6" / "boundary_aware_structured_lexical_v1.json"
BASE_REVISION = "90811052194801263708627c1eda39a2765e9037"


def assessment(
    value: float, *, mismatch: float = 0.0, missing_abstract: bool = False
) -> BoundaryAssessment:
    return BoundaryAssessment(
        dimension_scores={dimension: value for dimension in BOUNDARY_DIMENSIONS},
        scope_out_overlap=mismatch,
        boundary_case_overlap=0.0,
        missing_abstract=missing_abstract,
        evidence_summary="Deterministic synthetic compatibility assessment.",
    )


class W6BoundaryRankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = validate_w6_bootstrap_bundle(BOOTSTRAP)

    def test_preregistered_config_matches_frozen_defaults_and_rejects_label_access(self) -> None:
        self.assertEqual(load_boundary_ranking_config(CONFIG), BoundaryRankingConfig())
        payload = load_json_object(CONFIG)
        payload["input_policy"]["hidden_test_labels_read"] = True
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no-label policy"):
                load_boundary_ranking_config(config_path)

    def test_fake_backend_generation_is_deterministic_and_dynamic(self) -> None:
        assessments = {
            item_id: assessment(0.8 if index % 2 == 0 else 0.2)
            for index, item_id in enumerate(sorted(self.bundle["pool_members"]))
        }
        backend = DeterministicFakeBoundaryBackend(assessments)
        first = build_boundary_aware_rankings(
            topics=self.bundle["topics"],
            pool_members=self.bundle["pool_members"],
            records=self.bundle["records"],
            backend=backend,
        )
        reversed_pool = dict(reversed(list(self.bundle["pool_members"].items())))
        second = build_boundary_aware_rankings(
            topics=self.bundle["topics"],
            pool_members=reversed_pool,
            records=self.bundle["records"],
            backend=backend,
        )
        self.assertEqual(first["rows"], second["rows"])
        self.assertEqual(len(first["rows"]), len(self.bundle["pool_members"]))

    def test_boundary_mismatch_penalizes_otherwise_equal_candidate(self) -> None:
        topic_id = "topic_test"
        topics = {
            topic_id: {
                "research_question": "classify stellar spectra",
                "scientific_object": "stars",
                "data_modality": "optical spectra",
                "target_task": "classification",
                "method_role": "primary classifier",
                "scope_in": ["stellar spectra classification"],
                "scope_out": ["galaxy regression"],
                "boundary_cases": ["parameter regression instead of classification"],
            }
        }
        records = {
            "record_a": {"title": "same text", "abstract": "same text"},
            "record_b": {"title": "same text", "abstract": "same text"},
        }
        pool = {
            "item_a": {"topic_id": topic_id, "record_id": "record_a"},
            "item_b": {"topic_id": topic_id, "record_id": "record_b"},
        }
        backend = DeterministicFakeBoundaryBackend(
            {"item_a": assessment(1.0), "item_b": assessment(1.0, mismatch=1.0)}
        )
        result = build_boundary_aware_rankings(
            topics=topics, pool_members=pool, records=records, backend=backend
        )
        rows = {row["pair_id"]: row for row in result["rows"]}
        self.assertGreater(rows["item_a"]["score"], rows["item_b"]["score"])
        self.assertEqual(rows["item_a"]["rank"], 1)

    def test_missing_abstract_is_retained_with_title_only(self) -> None:
        result = build_boundary_aware_rankings(
            topics=self.bundle["topics"],
            pool_members=self.bundle["pool_members"],
            records=self.bundle["records"],
            backend=DeterministicLexicalBoundaryBackend(),
        )
        missing_items = {
            item_id
            for item_id, member in self.bundle["pool_members"].items()
            if self.bundle["records"][member["record_id"]]["abstract"] is None
        }
        ranked_items = {row["pair_id"] for row in result["rows"]}
        self.assertTrue(missing_items)
        self.assertTrue(missing_items <= ranked_items)
        self.assertTrue(
            all(result["diagnostics"][item_id]["missing_abstract"] for item_id in missing_items)
        )

    def test_invalid_fake_assessment_fails_closed(self) -> None:
        item_ids = sorted(self.bundle["pool_members"])
        invalid = BoundaryAssessment(
            dimension_scores={"scientific_object": 0.5},
            scope_out_overlap=0.0,
            boundary_case_overlap=0.0,
            missing_abstract=False,
            evidence_summary="Deliberately incomplete deterministic assessment.",
        )
        backend = DeterministicFakeBoundaryBackend(
            {item_id: (invalid if item_id == item_ids[0] else assessment(0.5)) for item_id in item_ids}
        )
        with self.assertRaisesRegex(ValueError, "dimensions 不完整"):
            build_boundary_aware_rankings(
                topics=self.bundle["topics"],
                pool_members=self.bundle["pool_members"],
                records=self.bundle["records"],
                backend=backend,
            )

    def test_generation_api_has_no_label_input(self) -> None:
        parameters = inspect.signature(build_boundary_aware_rankings).parameters
        self.assertFalse(
            {"labels", "judgements", "annotations", "metrics", "hidden_labels"} & set(parameters)
        )

    def test_generated_method_package_declares_auxiliary_text_and_validates(self) -> None:
        payloads = self.bundle["payloads"]
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = build_w6_boundary_method_package(
                topics=self.bundle["topics"],
                pool_members=self.bundle["pool_members"],
                records=self.bundle["records"],
                artifact_registry=self.bundle["registry"],
                topic_reference=self.bundle["registry"][payloads["topic_set"]["artifact_id"]],
                candidate_pool_reference=self.bundle["registry"][payloads["candidate_pool"]["artifact_id"]],
                source_records_reference=self.bundle["registry"][payloads["source_records"]["artifact_id"]],
                output_dir=Path(temp_dir) / "method",
                is_fixture=True,
                generated_at="2026-08-24T14:25:00+08:00",
                frozen_at="2026-08-24T14:25:01+08:00",
                git_revision=BASE_REVISION,
                git_worktree_clean=True,
                backend=DeterministicLexicalBoundaryBackend(),
            )
            result = validate_w6_method_package(
                manifest_path,
                artifact_registry=self.bundle["registry"],
                pool_members=self.bundle["pool_members"],
                known_method_packages={},
            )
            manifest = load_json_object(manifest_path)
        self.assertIn("source_records", manifest["auxiliary_inputs"])
        self.assertFalse(manifest["label_access"]["relevance_labels_read"])
        self.assertFalse(manifest["label_access"]["hidden_test_labels_read"])
        self.assertEqual(len(result["ranking_rows"]), len(self.bundle["pool_members"]))

    def test_auxiliary_input_hash_drift_fails_before_generation(self) -> None:
        payloads = self.bundle["payloads"]
        bad_source_ref = dict(
            self.bundle["registry"][payloads["source_records"]["artifact_id"]]
        )
        bad_source_ref["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "source_records input identity/hash drift"):
                build_w6_boundary_method_package(
                    topics=self.bundle["topics"],
                    pool_members=self.bundle["pool_members"],
                    records=self.bundle["records"],
                    artifact_registry=self.bundle["registry"],
                    topic_reference=self.bundle["registry"][payloads["topic_set"]["artifact_id"]],
                    candidate_pool_reference=self.bundle["registry"][payloads["candidate_pool"]["artifact_id"]],
                    source_records_reference=bad_source_ref,
                    output_dir=Path(temp_dir) / "method",
                    is_fixture=True,
                    generated_at="2026-08-24T14:25:00+08:00",
                    frozen_at="2026-08-24T14:25:01+08:00",
                    git_revision=BASE_REVISION,
                    git_worktree_clean=True,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
