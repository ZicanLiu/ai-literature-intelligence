"""Offline regression tests for the W6 Research Contract Bootstrap."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.validate_w6_bootstrap import main as validate_cli_main
from src.w5_method_contract import RANKING_FIELDS
from src.w6_contracts import (
    BLIND_TASK_FORBIDDEN_KEYS,
    PARALLEL_MODULE_FIXTURE_REQUIREMENTS,
    _find_forbidden_keys,
    load_json_object,
    validate_annotation_results,
    validate_annotation_reviews,
    validate_blind_annotation_tasks,
    validate_benchmark_manifest,
    validate_candidate_pool,
    validate_canonical_entities,
    validate_hidden_label_reveal,
    validate_retrieval_provenance,
    validate_source_records,
    validate_topic_set,
    validate_topic_split,
    validate_w6_bootstrap_bundle,
)
from src.w6_method_contract import W6_RANKING_FIELDS, validate_w6_method_package
from src.w6_synthesis_contract import validate_structured_synthesis


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap"
VALID_ROOT = FIXTURE_ROOT / "valid"
INVALID_ROOT = FIXTURE_ROOT / "invalid"
BUNDLE_PATH = VALID_ROOT / "bundle_manifest.json"
INVALID_CASES = {
    case["case_id"]: case
    for case in load_json_object(INVALID_ROOT / "invalid_cases.json")["cases"]
}


def _resolve_mutation_parent(payload, path):
    current = payload
    for part in path[:-1]:
        current = current[part]
    return current, path[-1]


def _apply_set(payload, path, value) -> None:
    parent, key = _resolve_mutation_parent(payload, path)
    parent[key] = copy.deepcopy(value)


def invalid_payload(case_id: str) -> dict:
    case = INVALID_CASES[case_id]
    payload = load_json_object(VALID_ROOT / case["base"])
    operation = case["operation"]
    if operation == "set":
        _apply_set(payload, case["path"], case["value"])
    elif operation == "delete":
        parent, key = _resolve_mutation_parent(payload, case["path"])
        del parent[key]
    elif operation == "append":
        parent, key = _resolve_mutation_parent(payload, case["path"])
        parent[key].append(copy.deepcopy(case["value"]))
    elif operation == "append_copy":
        parent, key = _resolve_mutation_parent(payload, case["path"])
        source_parent, source_key = _resolve_mutation_parent(
            payload, case["copy_from"]
        )
        parent[key].append(copy.deepcopy(source_parent[source_key]))
    elif operation == "set_many":
        for change in case["changes"]:
            _apply_set(payload, change["path"], change["value"])
    else:
        raise AssertionError(f"unknown invalid fixture operation: {operation}")
    return payload


class W6ValidBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = validate_w6_bootstrap_bundle(BUNDLE_PATH)

    def test_complete_bundle_passes(self) -> None:
        self.assertEqual(len(self.bundle["topics"]), 2)
        self.assertEqual(len(self.bundle["records"]), 10)
        self.assertEqual(len(self.bundle["pool_members"]), 13)
        self.assertEqual(len(self.bundle["method_packages"]), 3)
        self.assertEqual(len(self.bundle["reviews"]), 2)

    def test_fixture_covers_identity_and_metadata_boundaries(self) -> None:
        records = self.bundle["records"]
        canonical = self.bundle["canonical"]
        self.assertIsNone(records["rec_006"]["abstract"])
        self.assertEqual(
            canonical["entities"]["entity_003"]["alias_record_ids"],
            ["rec_003", "rec_008"],
        )
        self.assertEqual(
            canonical["relationships"]["suspect_005_010"]["review_state"],
            "pending_review",
        )
        self.assertNotEqual(
            canonical["entity_by_record"]["rec_005"],
            canonical["entity_by_record"]["rec_010"],
        )

    def test_fixture_covers_multi_and_single_retriever_membership(self) -> None:
        pool = self.bundle["pool_members"]
        self.assertEqual(len(pool["pool_denoise_001"]["source_system_membership"]), 2)
        self.assertEqual(
            pool["pool_transient_009"]["source_system_membership"],
            ["dense_fixture"],
        )

    def test_blind_projection_contains_no_retrieval_or_ranking_fields(self) -> None:
        tasks = self.bundle["payloads"]["annotation_tasks"]["tasks"]
        self.assertFalse(_find_forbidden_keys(tasks, BLIND_TASK_FORBIDDEN_KEYS))
        self.assertEqual(len(tasks), len(self.bundle["pool_members"]))

    def test_ai_annotation_provenance_is_explicit(self) -> None:
        annotations = self.bundle["annotations"].values()
        actor_types = {
            row["annotation_provenance"]["actor_type"] for row in annotations
        }
        labels = {row["relevance_label"] for row in annotations}
        self.assertIn("ai_assistant", actor_types)
        self.assertIn("ai_assisted_human", actor_types)
        self.assertEqual(labels, {0, 1, 2})

    def test_dev_hidden_split_is_topic_level(self) -> None:
        split = self.bundle["split_sets"]
        self.assertFalse(split["dev"] & split["hidden"])
        self.assertEqual(
            split["dev"] | split["hidden"], set(self.bundle["topics"])
        )

    def test_hidden_fixture_reveal_requires_matching_anchor(self) -> None:
        labels = validate_hidden_label_reveal(
            anchor_path=VALID_ROOT / "hidden_label_anchor.json",
            hidden_labels_path=VALID_ROOT / "sealed" / "fake_hidden_labels.json",
            split_payload=self.bundle["payloads"]["split_manifest"],
            topics=self.bundle["topics"],
            pool_members=self.bundle["pool_members"],
        )
        self.assertEqual(len(labels), 6)
        self.assertTrue(
            all(
                self.bundle["pool_members"][item_id]["topic_id"]
                in self.bundle["split_sets"]["hidden"]
                for item_id in labels
            )
        )

    def test_hidden_reveal_rejects_hash_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tampered = Path(temp_dir) / "hidden.json"
            payload = load_json_object(
                VALID_ROOT / "sealed" / "fake_hidden_labels.json"
            )
            payload["labels"][0]["relevance_label"] = 2
            tampered.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "hash"):
                validate_hidden_label_reveal(
                    anchor_path=VALID_ROOT / "hidden_label_anchor.json",
                    hidden_labels_path=tampered,
                    split_payload=self.bundle["payloads"]["split_manifest"],
                    topics=self.bundle["topics"],
                    pool_members=self.bundle["pool_members"],
                )

    def test_w6_ranking_columns_are_w5_compatible(self) -> None:
        self.assertIs(W6_RANKING_FIELDS, RANKING_FIELDS)
        fusion = self.bundle["method_packages"]["w6_fixture_method_fusion_v1"]
        normalization = fusion["manifest"]["score_processing"]["normalization"]
        self.assertIsNotNone(normalization)
        self.assertFalse(normalization["label_access"])
        self.assertEqual(len(fusion["manifest"]["method_inputs"]), 2)

    def test_synthesis_contains_supported_partial_and_unsupported_claims(self) -> None:
        claims = self.bundle["payloads"]["structured_synthesis"]["claims"]
        self.assertEqual(
            {claim["support_status"] for claim in claims},
            {"supported", "partially_supported", "unsupported"},
        )

    def test_six_modules_only_depend_on_bootstrap(self) -> None:
        matrix = self.bundle["manifest"]["parallel_development"]
        self.assertEqual(set(matrix), set(PARALLEL_MODULE_FIXTURE_REQUIREMENTS))
        for name, requirements in PARALLEL_MODULE_FIXTURE_REQUIREMENTS.items():
            self.assertEqual(matrix[name]["depends_on"], ["w6_bootstrap"])
            self.assertEqual(set(matrix[name]["artifacts"]), requirements)

    def test_cli_passes_on_public_fixture(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = validate_cli_main(["--manifest", str(BUNDLE_PATH)])
        self.assertEqual(exit_code, 0, output.getvalue())
        self.assertIn("PASSED", output.getvalue())


class W6InvalidFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = validate_w6_bootstrap_bundle(BUNDLE_PATH)

    def test_topic_overlap_fixture_fails(self) -> None:
        payload = invalid_payload("split_overlap")
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_topic_split(payload, topics=self.bundle["topics"])

    def test_duplicate_topic_fixture_fails(self) -> None:
        payload = invalid_payload("duplicate_topics")
        with self.assertRaisesRegex(ValueError, "duplicate topic_id"):
            validate_topic_set(payload)

    def test_unknown_retrieval_topic_fixture_fails(self) -> None:
        payload = invalid_payload("retrieval_unknown_topic")
        with self.assertRaisesRegex(ValueError, "unknown topic"):
            validate_retrieval_provenance(payload, topics=self.bundle["topics"])

    def test_missing_source_provenance_fixture_fails(self) -> None:
        payload = invalid_payload("source_missing_provenance")
        with self.assertRaisesRegex(ValueError, "字段不符合 contract"):
            validate_source_records(
                payload,
                topics=self.bundle["topics"],
                retrieval=self.bundle["retrieval"],
            )

    def test_blind_score_leak_fixture_fails(self) -> None:
        payload = invalid_payload("blind_task_score_leak")
        with self.assertRaisesRegex(ValueError, "泄漏"):
            validate_blind_annotation_tasks(
                payload,
                topics=self.bundle["topics"],
                records=self.bundle["records"],
                pool_members=self.bundle["pool_members"],
            )

    def test_canonical_dangling_alias_fixture_fails(self) -> None:
        payload = invalid_payload("canonical_dangling_alias")
        with self.assertRaisesRegex(ValueError, "dangling alias"):
            validate_canonical_entities(
                payload,
                records=self.bundle["records"],
                retrieval=self.bundle["retrieval"],
            )

    def test_candidate_identity_mismatch_fixture_fails(self) -> None:
        payload = invalid_payload("candidate_identity_mismatch")
        with self.assertRaisesRegex(ValueError, "candidate identity mismatch"):
            validate_candidate_pool(
                payload,
                topics=self.bundle["topics"],
                records=self.bundle["records"],
                retrieval=self.bundle["retrieval"],
                canonical=self.bundle["canonical"],
            )

    def test_illegal_annotation_label_fixture_fails(self) -> None:
        payload = invalid_payload("annotation_illegal_label")
        with self.assertRaisesRegex(ValueError, "illegal relevance label"):
            validate_annotation_results(
                payload, tasks=self.bundle["annotation_tasks"]
            )

    def test_annotation_unknown_candidate_fixture_fails(self) -> None:
        payload = invalid_payload("annotation_unknown_candidate")
        with self.assertRaisesRegex(ValueError, "不存在 candidate/task"):
            validate_annotation_results(
                payload, tasks=self.bundle["annotation_tasks"]
            )

    def test_review_unknown_annotation_fixture_fails(self) -> None:
        payload = invalid_payload("review_unknown_annotation")
        with self.assertRaisesRegex(ValueError, "unknown/duplicate annotation"):
            validate_annotation_reviews(
                payload, annotations=self.bundle["annotations"]
            )

    def test_public_hidden_topic_annotation_fixture_fails(self) -> None:
        payload = invalid_payload("annotation_hidden_topic_public")
        annotations = validate_annotation_results(
            payload, tasks=self.bundle["annotation_tasks"]
        )
        with self.assertRaisesRegex(ValueError, "hidden-test labels"):
            validate_benchmark_manifest(
                self.bundle["payloads"]["benchmark_manifest"],
                registry=self.bundle["registry"],
                topics=self.bundle["topics"],
                pool_members=self.bundle["pool_members"],
                canonical=self.bundle["canonical"],
                annotations=annotations,
                reviews=self.bundle["reviews"],
                split_sets=self.bundle["split_sets"],
            )

    def test_hidden_label_generation_input_fixture_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    invalid_payload("method_hidden_generation_input"),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "禁止输入"):
                validate_w6_method_package(
                    manifest_path,
                    artifact_registry=self.bundle["registry"],
                    pool_members=self.bundle["pool_members"],
                    known_method_packages={},
                )

    def test_dangling_synthesis_evidence_fixture_fails(self) -> None:
        payload = invalid_payload("synthesis_dangling_evidence")
        with self.assertRaisesRegex(ValueError, "dangling evidence"):
            validate_structured_synthesis(
                payload,
                synthesis_input=self.bundle["synthesis_input"],
                evidence=self.bundle["evidence_units"],
                canonical=self.bundle["canonical"],
            )

    def test_supported_claim_without_evidence_fixture_fails(self) -> None:
        payload = invalid_payload("synthesis_supported_without_evidence")
        with self.assertRaisesRegex(ValueError, "没有 paper/evidence"):
            validate_structured_synthesis(
                payload,
                synthesis_input=self.bundle["synthesis_input"],
                evidence=self.bundle["evidence_units"],
                canonical=self.bundle["canonical"],
            )

    def test_bundle_manifest_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            copied = Path(temp_dir) / "valid"
            shutil.copytree(VALID_ROOT, copied)
            (copied / "bundle_manifest.json").write_text(
                json.dumps(
                    invalid_payload("bundle_hash_mismatch"),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate_w6_bootstrap_bundle(copied / "bundle_manifest.json")

    def test_method_input_identity_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "fake_fusion"
            shutil.copytree(
                VALID_ROOT / "method_rankings" / "fake_fusion", package_dir
            )
            manifest_path = package_dir / "manifest.json"
            manifest = load_json_object(manifest_path)
            manifest["method_inputs"][0]["ranking_sha256"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            known = {
                artifact_id: package
                for artifact_id, package in self.bundle["method_packages"].items()
                if artifact_id != "w6_fixture_method_fusion_v1"
            }
            with self.assertRaisesRegex(ValueError, "identity drift"):
                validate_w6_method_package(
                    manifest_path,
                    artifact_registry=self.bundle["registry"],
                    pool_members=self.bundle["pool_members"],
                    known_method_packages=known,
                )

    def test_public_bundle_hash_tampering_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            copied = Path(temp_dir) / "valid"
            shutil.copytree(VALID_ROOT, copied)
            topics = copied / "topics.json"
            payload = load_json_object(topics)
            payload["topics"][0]["research_question"] += " tampered"
            topics.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate_w6_bootstrap_bundle(copied / "bundle_manifest.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
