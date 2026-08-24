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
from src.annotation_tasks import sha256_file
from src.w5_method_contract import RANKING_FIELDS
import src.w6_contracts as w6_contracts
from src.w6_contracts import (
    BLIND_TASK_FORBIDDEN_KEYS,
    PARALLEL_MODULE_FIXTURE_REQUIREMENTS,
    _find_forbidden_keys,
    build_annotation_task_map,
    build_blind_annotation_tasks,
    compute_benchmark_identity,
    compute_pool_identity,
    compute_split_identity,
    load_json_object,
    validate_annotation_results,
    validate_annotation_reviews,
    validate_annotation_task_map,
    validate_blind_annotation_tasks,
    validate_benchmark_manifest,
    validate_candidate_pool,
    validate_canonical_entities,
    validate_hidden_label_anchor,
    validate_retrieval_provenance,
    validate_source_records,
    validate_topic_set,
    validate_topic_split,
    validate_w6_bootstrap_bundle,
)
from src.w6_method_contract import (
    W6_RANKING_FIELDS,
    compute_method_configuration_hash,
    validate_w6_method_package,
)
from src.w6_synthesis_contract import (
    validate_evidence_units,
    validate_structured_synthesis,
    validate_synthesis_input,
)


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


def _annotation_validation_kwargs(bundle: dict) -> dict:
    return {
        "tasks": bundle["annotation_tasks"],
        "task_mappings": bundle["annotation_task_mappings"],
        "split": bundle["payloads"]["split_manifest"],
        "split_sets": bundle["split_sets"],
        "registry": bundle["registry"],
    }


def _copy_task_subset(task_name: str, destination: Path) -> Path:
    root = destination / task_name
    root.mkdir(parents=True)
    manifest = load_json_object(BUNDLE_PATH)
    if task_name == "quality_gate":
        shutil.copy2(BUNDLE_PATH, root / "bundle_manifest.json")
    else:
        subset_manifest = copy.deepcopy(manifest)
        subset_manifest["artifacts"] = {
            name: manifest["artifacts"][name]
            for name in PARALLEL_MODULE_FIXTURE_REQUIREMENTS[task_name]
        }
        subset_manifest["parallel_development"] = {
            task_name: manifest["parallel_development"][task_name]
        }
        (root / "bundle_manifest.json").write_text(
            json.dumps(subset_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    for artifact_name in PARALLEL_MODULE_FIXTURE_REQUIREMENTS[task_name]:
        relative = Path(manifest["artifacts"][artifact_name]["path"])
        source = VALID_ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.name == "manifest.json" and "method_rankings" in relative.parts:
            shutil.copytree(source.parent, target.parent, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    return root


def _load_task_subset(root: Path, task_name: str):
    manifest = load_json_object(root / "bundle_manifest.json")
    payloads = {}
    paths = {}
    registry = {}
    for name in PARALLEL_MODULE_FIXTURE_REQUIREMENTS[task_name]:
        reference = manifest["artifacts"][name]
        path = root / reference["path"]
        if not path.is_file():
            raise FileNotFoundError(f"missing declared fixture artifact: {name}")
        if sha256_file(path) != reference["sha256"]:
            raise ValueError(f"isolated fixture hash drift: {name}")
        paths[name] = path
        payloads[name] = load_json_object(path)
        registry[reference["artifact_id"]] = {
            "artifact_id": reference["artifact_id"],
            "sha256": reference["sha256"],
        }
    return manifest, payloads, paths, registry


def _validate_isolated_task(root: Path, task_name: str) -> None:
    if task_name == "quality_gate":
        validate_w6_bootstrap_bundle(root / "bundle_manifest.json")
        return
    _, payloads, paths, registry = _load_task_subset(root, task_name)
    topics = validate_topic_set(payloads["topic_set"])
    retrieval = validate_retrieval_provenance(
        payloads["retrieval_provenance"], topics=topics
    )
    records = validate_source_records(
        payloads["source_records"], topics=topics, retrieval=retrieval
    )
    if "precanonical_candidate_pool" in payloads:
        pre_pool = validate_candidate_pool(
            payloads["precanonical_candidate_pool"],
            topics=topics,
            records=records,
            retrieval=retrieval,
            registry=registry,
        )
        assert pre_pool
    if task_name == "multi_retriever_pool":
        assert any(len(row["retrieval_hit_ids"]) > 1 for row in pre_pool.values())
        return
    if task_name == "metadata_diagnostics":
        missing_counts = {
            record_id: len(record["metadata_completeness"]["missing_fields"])
            for record_id, record in records.items()
        }
        assert missing_counts["rec_006"] == 2
        return

    canonical = validate_canonical_entities(
        payloads["canonical_entities"], records=records, retrieval=retrieval
    )
    pool_members = validate_candidate_pool(
        payloads["candidate_pool"],
        topics=topics,
        records=records,
        retrieval=retrieval,
        registry=registry,
        canonical=canonical,
    )
    if task_name == "canonicalization_audit":
        assert canonical["entity_by_record"]["rec_003"] == canonical["entity_by_record"]["rec_008"]
        return

    if task_name == "leader":
        mappings = validate_annotation_task_map(
            payloads["annotation_task_map"],
            records=records,
            pool_members=pool_members,
            registry=registry,
        )
        tasks = validate_blind_annotation_tasks(
            payloads["annotation_tasks"],
            topics=topics,
            records=records,
            task_mappings=mappings,
            registry=registry,
        )
        split_sets = validate_topic_split(payloads["split_manifest"], topics=topics)
        annotations = validate_annotation_results(
            payloads["annotation_results"],
            tasks=tasks,
            task_mappings=mappings,
            split=payloads["split_manifest"],
            split_sets=split_sets,
            registry=registry,
        )
        reviews = validate_annotation_reviews(
            payloads["annotation_reviews"], annotations=annotations
        )
        validate_hidden_label_anchor(
            payloads["hidden_label_anchor"],
            split=payloads["split_manifest"],
            split_sets=split_sets,
            registry=registry,
        )
        method_package = validate_w6_method_package(
            paths["method_sparse_manifest"],
            artifact_registry=registry,
            pool_members=pool_members,
            known_method_packages={},
        )
        validate_benchmark_manifest(
            payloads["benchmark_manifest"],
            registry=registry,
            topics=topics,
            pool_members=pool_members,
            canonical=canonical,
            annotations=annotations,
            reviews=reviews,
            split_sets=split_sets,
        )
        assert annotations and method_package["ranking_rows"]
        return

    method_packages = {}
    for name in ("method_sparse_manifest", "method_dense_manifest"):
        package = validate_w6_method_package(
            paths[name],
            artifact_registry=registry,
            pool_members=pool_members,
            known_method_packages=method_packages,
        )
        method_packages[package["artifact_id"]] = package
    fusion = validate_w6_method_package(
        paths["method_fusion_manifest"],
        artifact_registry=registry,
        pool_members=pool_members,
        known_method_packages=method_packages,
    )
    method_packages[fusion["artifact_id"]] = fusion
    evidence = validate_evidence_units(
        payloads["evidence_units"], records=records, canonical=canonical
    )
    synthesis_input = validate_synthesis_input(
        payloads["synthesis_input"],
        registry=registry,
        topics=topics,
        pool_members=pool_members,
        method_packages=method_packages,
        records=records,
        canonical=canonical,
        evidence=evidence,
        expected_artifact_ids={
            "topic_set": payloads["topic_set"]["artifact_id"],
            "source_records": payloads["source_records"]["artifact_id"],
            "retrieval_provenance": payloads["retrieval_provenance"]["artifact_id"],
            "evidence_units": payloads["evidence_units"]["artifact_id"],
        },
    )
    claims = validate_structured_synthesis(
        payloads["structured_synthesis"],
        synthesis_input=synthesis_input,
        evidence=evidence,
        canonical=canonical,
    )
    assert claims


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

    def test_precanonical_pool_has_no_canonical_dependency(self) -> None:
        payload = self.bundle["payloads"]["precanonical_candidate_pool"]
        self.assertNotIn("canonical_entities", payload["inputs"])
        self.assertTrue(self.bundle["precanonical_pool_members"])

    def test_blind_projection_contains_no_retrieval_or_ranking_fields(self) -> None:
        tasks = self.bundle["payloads"]["annotation_tasks"]["tasks"]
        self.assertFalse(_find_forbidden_keys(tasks, BLIND_TASK_FORBIDDEN_KEYS))
        self.assertEqual(len(tasks), len(self.bundle["pool_members"]))
        serialized = json.dumps(tasks, ensure_ascii=False)
        self.assertNotIn("pool_denoise_001", serialized)
        self.assertNotIn("rec_001", serialized)

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

    def test_hidden_labels_remain_external_and_bootstrap_has_no_reveal_api(self) -> None:
        anchor = self.bundle["payloads"]["hidden_label_anchor"]
        self.assertEqual(
            anchor["storage"], {"location": "external", "repository_path": None}
        )
        self.assertFalse(hasattr(w6_contracts, "validate_hidden_label_reveal"))
        self.assertFalse((VALID_ROOT / "sealed" / "fake_hidden_labels.json").exists())

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

    def test_each_parallel_task_validates_from_only_its_declared_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir)
            for task_name in PARALLEL_MODULE_FIXTURE_REQUIREMENTS:
                root = _copy_task_subset(task_name, destination)
                _validate_isolated_task(root, task_name)

    def test_each_parallel_task_fails_when_a_declared_artifact_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir)
            manifest = load_json_object(BUNDLE_PATH)
            for task_name, requirements in PARALLEL_MODULE_FIXTURE_REQUIREMENTS.items():
                root = _copy_task_subset(task_name, destination)
                missing_name = sorted(requirements)[0]
                missing = root / manifest["artifacts"][missing_name]["path"]
                missing.unlink()
                with self.assertRaises((FileNotFoundError, ValueError)):
                    _validate_isolated_task(root, task_name)

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
                task_mappings=self.bundle["annotation_task_mappings"],
                registry=self.bundle["registry"],
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
                registry=self.bundle["registry"],
                canonical=self.bundle["canonical"],
            )

    def test_illegal_annotation_label_fixture_fails(self) -> None:
        payload = invalid_payload("annotation_illegal_label")
        with self.assertRaisesRegex(ValueError, "illegal relevance label"):
            validate_annotation_results(
                payload, **_annotation_validation_kwargs(self.bundle)
            )

    def test_annotation_unknown_candidate_fixture_fails(self) -> None:
        payload = invalid_payload("annotation_unknown_candidate")
        with self.assertRaisesRegex(ValueError, "不存在 candidate/task"):
            validate_annotation_results(
                payload, **_annotation_validation_kwargs(self.bundle)
            )

    def test_review_unknown_annotation_fixture_fails(self) -> None:
        payload = invalid_payload("review_unknown_annotation")
        with self.assertRaisesRegex(ValueError, "unknown/duplicate annotation"):
            validate_annotation_reviews(
                payload, annotations=self.bundle["annotations"]
            )

    def test_public_hidden_topic_annotation_fixture_fails(self) -> None:
        payload = invalid_payload("annotation_hidden_topic_public")
        with self.assertRaisesRegex(ValueError, "hidden-test topic"):
            validate_annotation_results(
                payload, **_annotation_validation_kwargs(self.bundle)
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

    def test_pool_provenance_union_cannot_be_self_reported_away(self) -> None:
        payload = copy.deepcopy(self.bundle["payloads"]["candidate_pool"])
        payload["members"][0]["retrieval_hit_ids"] = ["hit_doa_001"]
        payload["members"][0]["source_system_membership"] = ["openalex_native"]
        payload["pool_identity"] = compute_pool_identity(payload)
        with self.assertRaisesRegex(ValueError, "provenance union"):
            validate_candidate_pool(
                payload,
                topics=self.bundle["topics"],
                records=self.bundle["records"],
                retrieval=self.bundle["retrieval"],
                registry=self.bundle["registry"],
                canonical=self.bundle["canonical"],
            )

    def test_blind_id_does_not_encode_method_rank_or_pool_identity(self) -> None:
        pool = copy.deepcopy(self.bundle["pool_members"])
        member = pool.pop("pool_denoise_001")
        member["pool_item_id"] = "bm25_rank_001"
        pool[member["pool_item_id"]] = member
        mappings = build_annotation_task_map(records=self.bundle["records"], pool_members=pool)
        mapping_by_task = {row["annotation_task_id"]: row for row in mappings}
        tasks = build_blind_annotation_tasks(
            topics=self.bundle["topics"],
            records=self.bundle["records"],
            task_mappings=mapping_by_task,
        )
        serialized = json.dumps(tasks, ensure_ascii=False)
        self.assertNotIn("bm25", serialized)
        self.assertNotIn("rank_001", serialized)

    def test_split_frozen_after_annotation_start_fails_even_with_new_identity(self) -> None:
        split = copy.deepcopy(self.bundle["payloads"]["split_manifest"])
        split["frozen_at"] = "2026-08-24T08:59:00+08:00"
        split["split_identity"] = compute_split_identity(split)
        split_sets = validate_topic_split(split, topics=self.bundle["topics"])
        annotations = copy.deepcopy(self.bundle["payloads"]["annotation_results"])
        annotations["split"]["sha256"] = "1" * 64
        registry = copy.deepcopy(self.bundle["registry"])
        registry[split["artifact_id"]]["sha256"] = "1" * 64
        with self.assertRaisesRegex(ValueError, "annotation_started_at"):
            validate_annotation_results(
                annotations,
                tasks=self.bundle["annotation_tasks"],
                task_mappings=self.bundle["annotation_task_mappings"],
                split=split,
                split_sets=split_sets,
                registry=registry,
            )

    def test_hidden_anchor_wrong_split_hash_fails(self) -> None:
        anchor = copy.deepcopy(self.bundle["payloads"]["hidden_label_anchor"])
        anchor["split"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "drift"):
            validate_hidden_label_anchor(
                anchor,
                split=self.bundle["payloads"]["split_manifest"],
                split_sets=self.bundle["split_sets"],
                registry=self.bundle["registry"],
            )

    def test_annotation_split_hash_replacement_fails(self) -> None:
        annotations = copy.deepcopy(self.bundle["payloads"]["annotation_results"])
        annotations["split"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "drift"):
            validate_annotation_results(
                annotations, **_annotation_validation_kwargs(self.bundle)
            )

    def test_bootstrap_rejects_revealed_split_state(self) -> None:
        split = copy.deepcopy(self.bundle["payloads"]["split_manifest"])
        split["reveal_state"] = "revealed"
        split["split_identity"] = compute_split_identity(split)
        with self.assertRaisesRegex(ValueError, "sealed"):
            validate_topic_split(split, topics=self.bundle["topics"])

    def test_bootstrap_benchmark_cannot_self_declare_approved(self) -> None:
        benchmark = copy.deepcopy(self.bundle["payloads"]["benchmark_manifest"])
        benchmark["status"] = "approved"
        benchmark["review_provenance"]["status"] = "approved"
        benchmark["benchmark_identity"] = compute_benchmark_identity(benchmark)
        with self.assertRaisesRegex(ValueError, "approval/promotion|approved"):
            validate_benchmark_manifest(
                benchmark,
                registry=self.bundle["registry"],
                topics=self.bundle["topics"],
                pool_members=self.bundle["pool_members"],
                canonical=self.bundle["canonical"],
                annotations=self.bundle["annotations"],
                reviews=self.bundle["reviews"],
                split_sets=self.bundle["split_sets"],
            )

    def test_source_metadata_missing_fields_must_match_actual_values(self) -> None:
        payload = copy.deepcopy(self.bundle["payloads"]["source_records"])
        payload["records"][0]["doi"] = None
        with self.assertRaisesRegex(ValueError, "missing_fields"):
            validate_source_records(
                payload,
                topics=self.bundle["topics"],
                retrieval=self.bundle["retrieval"],
            )

    def test_duplicate_provider_source_record_identity_fails(self) -> None:
        payload = copy.deepcopy(self.bundle["payloads"]["source_records"])
        payload["records"][1]["record_provenance"] = copy.deepcopy(
            payload["records"][0]["record_provenance"]
        )
        with self.assertRaisesRegex(ValueError, "duplicate provider"):
            validate_source_records(
                payload,
                topics=self.bundle["topics"],
                retrieval=self.bundle["retrieval"],
            )

    def test_malformed_doi_and_openalex_identity_fail(self) -> None:
        for field, value, expected in (
            ("doi", "not-a-doi", "DOI"),
            ("openalex_id", "not-an-openalex-work", "OpenAlex"),
        ):
            payload = copy.deepcopy(self.bundle["payloads"]["source_records"])
            payload["records"][0][field] = value
            with self.assertRaisesRegex(ValueError, expected):
                validate_source_records(
                    payload,
                    topics=self.bundle["topics"],
                    retrieval=self.bundle["retrieval"],
                )

    def test_fusion_with_only_one_method_input_fails_after_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "fake_fusion"
            shutil.copytree(VALID_ROOT / "method_rankings" / "fake_fusion", package_dir)
            manifest_path = package_dir / "manifest.json"
            manifest = load_json_object(manifest_path)
            manifest["method_inputs"] = manifest["method_inputs"][:1]
            manifest["method"]["parameters"]["weights"] = {
                "w6_fixture_sparse_v1": 1.0
            }
            manifest["freeze"]["configuration_sha256"] = (
                compute_method_configuration_hash(manifest)
            )
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            known = {
                artifact_id: package
                for artifact_id, package in self.bundle["method_packages"].items()
                if artifact_id != "w6_fixture_method_fusion_v1"
            }
            with self.assertRaisesRegex(ValueError, "至少需要两个"):
                validate_w6_method_package(
                    manifest_path,
                    artifact_registry=self.bundle["registry"],
                    pool_members=self.bundle["pool_members"],
                    known_method_packages=known,
                )

    def test_fusion_weights_must_exactly_cover_method_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "fake_fusion"
            shutil.copytree(VALID_ROOT / "method_rankings" / "fake_fusion", package_dir)
            manifest_path = package_dir / "manifest.json"
            manifest = load_json_object(manifest_path)
            del manifest["method"]["parameters"]["weights"]["w6_fixture_dense_v1"]
            manifest["freeze"]["configuration_sha256"] = (
                compute_method_configuration_hash(manifest)
            )
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            known = {
                artifact_id: package
                for artifact_id, package in self.bundle["method_packages"].items()
                if artifact_id != "w6_fixture_method_fusion_v1"
            }
            with self.assertRaisesRegex(ValueError, "weights"):
                validate_w6_method_package(
                    manifest_path,
                    artifact_registry=self.bundle["registry"],
                    pool_members=self.bundle["pool_members"],
                    known_method_packages=known,
                )

    def test_hidden_labels_are_forbidden_as_auxiliary_method_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            manifest = load_json_object(
                VALID_ROOT / "method_rankings" / "fake_sparse" / "manifest.json"
            )
            manifest["auxiliary_inputs"]["hidden_labels"] = {
                "artifact_id": "forbidden_hidden_labels",
                "sha256": "0" * 64,
            }
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "禁止输入"):
                validate_w6_method_package(
                    manifest_path,
                    artifact_registry=self.bundle["registry"],
                    pool_members=self.bundle["pool_members"],
                    known_method_packages={},
                )

    def test_synthesis_cannot_cite_unselected_other_topic_paper(self) -> None:
        payload = copy.deepcopy(self.bundle["payloads"]["structured_synthesis"])
        payload["claims"][0]["supporting_canonical_entity_ids"] = ["entity_007"]
        payload["claims"][0]["evidence_refs"] = ["evidence_007"]
        with self.assertRaisesRegex(ValueError, "ranked selection"):
            validate_structured_synthesis(
                payload,
                synthesis_input=self.bundle["synthesis_input"],
                evidence=self.bundle["evidence_units"],
                canonical=self.bundle["canonical"],
            )

    def test_synthesis_cannot_cite_unselected_same_topic_paper(self) -> None:
        payload = copy.deepcopy(self.bundle["payloads"]["structured_synthesis"])
        payload["claims"][0]["supporting_canonical_entity_ids"] = ["entity_006"]
        payload["claims"][0]["evidence_refs"] = ["evidence_006"]
        with self.assertRaisesRegex(ValueError, "ranked selection"):
            validate_structured_synthesis(
                payload,
                synthesis_input=self.bundle["synthesis_input"],
                evidence=self.bundle["evidence_units"],
                canonical=self.bundle["canonical"],
            )

    def test_rejected_evidence_cannot_support_verified_claim(self) -> None:
        evidence = copy.deepcopy(self.bundle["evidence_units"])
        evidence["evidence_003"]["extraction_status"] = "rejected"
        with self.assertRaisesRegex(ValueError, "rejected"):
            validate_structured_synthesis(
                self.bundle["payloads"]["structured_synthesis"],
                synthesis_input=self.bundle["synthesis_input"],
                evidence=evidence,
                canonical=self.bundle["canonical"],
            )

    def test_structured_synthesis_must_bind_input_hash(self) -> None:
        payload = copy.deepcopy(self.bundle["payloads"]["structured_synthesis"])
        payload["synthesis_input"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "actual synthesis input hash|实际 synthesis input hash"):
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
