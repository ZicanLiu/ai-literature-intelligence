"""Offline tests for W6 candidate canonicalization and provenance preservation."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from app.canonicalize_w6 import main as canonicalize_cli_main
from src.w6_canonicalization import (
    MIN_TITLE_IDENTITY_TOKENS,
    SUSPECTED_TITLE_RATIO_THRESHOLD,
    build_canonical_entities,
    build_post_canonical_pool,
    entity_record_mapping,
)
from src.w6_contracts import (
    canonical_json_sha256,
    load_canonicalization_inputs,
    validate_candidate_pool,
    validate_canonical_entities,
    validate_w6_bootstrap_bundle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap" / "valid" / "bundle_manifest.json"
)
GIT_REVISION = "6b9eb12f898bf880c297902463e48f2ff3e0388b"
CREATED_AT = "2026-08-25T09:00:00+08:00"
CANONICAL_ARTIFACT_ID = "w6_test_canonical_entities_v1"


def _record(
    record_id: str,
    *,
    openalex_id: str | None = None,
    doi: str | None = None,
    title: str,
    abstract: str = "A short synthetic abstract for testing.",
) -> dict:
    return {
        "record_id": record_id,
        "topic_ids": ["topic_a"],
        "openalex_id": openalex_id,
        "doi": doi,
        "title": title,
        "abstract": abstract,
        "publication_year": 2024,
        "authors": ["A Author"],
        "venue": "Synthetic Venue",
        "landing_page_url": "https://example.test/papers/" + record_id,
        "metadata_completeness": {
            "status": "complete",
            "missing_fields": [],
            "completeness_score": 1.0,
        },
        "acquisition_provenance_refs": [f"hit_{record_id}"],
        "record_provenance": {
            "provider": "synthetic_openalex",
            "source_record_id": record_id,
            "retrieved_at": "2026-08-24T08:01:01+08:00",
        },
    }


def _build(records: dict, **overrides) -> dict:
    kwargs = {
        "artifact_id": CANONICAL_ARTIFACT_ID,
        "created_at": CREATED_AT,
        "git_revision": GIT_REVISION,
        "is_fixture": True,
    }
    kwargs.update(overrides)
    return build_canonical_entities(records, **kwargs)


class CanonicalizationFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = validate_w6_bootstrap_bundle(BUNDLE_PATH)
        cls.records = cls.bundle["records"]
        cls.retrieval = cls.bundle["retrieval"]
        cls.topics = cls.bundle["topics"]
        cls.pre_pool = cls.bundle["payloads"]["precanonical_candidate_pool"]

    def _canonical(self) -> dict:
        return _build(self.records)

    def test_confirmed_alias_records_map_to_same_entity(self) -> None:
        payload = self._canonical()
        mapping = entity_record_mapping(payload)
        self.assertEqual(mapping["rec_003"], mapping["rec_008"])
        entity = next(
            e for e in payload["entities"] if e["canonical_entity_id"] == mapping["rec_003"]
        )
        self.assertEqual(entity["alias_record_ids"], ["rec_003", "rec_008"])
        self.assertEqual(entity["identity_confidence"], "high")
        self.assertEqual(entity["review_state"], "confirmed")

    def test_suspected_duplicate_records_remain_separate(self) -> None:
        payload = self._canonical()
        mapping = entity_record_mapping(payload)
        self.assertNotEqual(mapping["rec_005"], mapping["rec_010"])
        relationships = payload["suspected_relationships"]
        self.assertEqual(len(relationships), 1)
        self.assertEqual(
            set(relationships[0]["entity_ids"]),
            {mapping["rec_005"], mapping["rec_010"]},
        )
        self.assertEqual(relationships[0]["review_state"], "pending_review")

    def test_every_source_record_is_mapped_and_retained(self) -> None:
        payload = self._canonical()
        mapping = entity_record_mapping(payload)
        self.assertEqual(set(mapping), set(self.records))

    def test_retrieval_provenance_union_is_complete(self) -> None:
        payload = self._canonical()
        mapping = entity_record_mapping(payload)
        entity = next(
            e for e in payload["entities"] if e["canonical_entity_id"] == mapping["rec_003"]
        )
        self.assertEqual(
            entity["source_retrieval_provenance_union"],
            ["hit_dbm_003", "hit_doa_003", "hit_doa_008"],
        )

    def test_preferred_record_is_deterministic(self) -> None:
        payload = self._canonical()
        mapping = entity_record_mapping(payload)
        entity = next(
            e for e in payload["entities"] if e["canonical_entity_id"] == mapping["rec_003"]
        )
        self.assertEqual(entity["preferred_record_id"], "rec_003")

    def test_canonical_payload_passes_contract_validator(self) -> None:
        result = validate_canonical_entities(
            self._canonical(), records=self.records, retrieval=self.retrieval
        )
        self.assertEqual(len(result["entities"]), 9)
        self.assertEqual(len(result["relationships"]), 1)

    def test_deterministic_identity(self) -> None:
        first = self._canonical()
        second = self._canonical()
        self.assertEqual(canonical_json_sha256(first), canonical_json_sha256(second))

    def test_thresholds_are_bounded(self) -> None:
        self.assertGreaterEqual(SUSPECTED_TITLE_RATIO_THRESHOLD, 0.5)
        self.assertLessEqual(SUSPECTED_TITLE_RATIO_THRESHOLD, 1.0)
        self.assertGreaterEqual(MIN_TITLE_IDENTITY_TOKENS, 1)


class CanonicalizationIdentityTests(unittest.TestCase):
    def test_exact_doi_identity_merges(self) -> None:
        records = {
            "r1": _record("r1", doi="https://doi.org/10.5555/paper.1", title="Title One"),
            "r2": _record("r2", doi="DOI:10.5555/PAPER.1", title="Title One Different"),
        }
        mapping = entity_record_mapping(_build(records))
        self.assertEqual(mapping["r1"], mapping["r2"])

    def test_exact_openalex_identity_merges(self) -> None:
        records = {
            "r1": _record("r1", openalex_id="https://openalex.org/W123", title="Title A"),
            "r2": _record("r2", openalex_id="W123", title="Title B"),
        }
        mapping = entity_record_mapping(_build(records))
        self.assertEqual(mapping["r1"], mapping["r2"])

    def test_title_normalization_merges(self) -> None:
        records = {
            "r1": _record("r1", title="Line-Preserving Neural Restoration!"),
            "r2": _record("r2", title="Line Preserving Neural Restoration"),
        }
        mapping = entity_record_mapping(_build(records))
        self.assertEqual(mapping["r1"], mapping["r2"])

    def test_different_openalex_with_same_title_is_not_merged(self) -> None:
        records = {
            "r1": _record("r1", openalex_id="W1", title="A Very Distinctive Paper Title"),
            "r2": _record("r2", openalex_id="W2", title="A Very Distinctive Paper Title"),
        }
        mapping = entity_record_mapping(_build(records))
        self.assertNotEqual(mapping["r1"], mapping["r2"])

    def test_same_openalex_with_different_doi_is_not_merged(self) -> None:
        records = {
            "r1": _record("r1", openalex_id="W1", doi="10.5555/x.1", title="Paper One Title"),
            "r2": _record("r2", openalex_id="W1", doi="10.5555/x.2", title="Paper Two Title"),
        }
        payload = _build(records)
        mapping = entity_record_mapping(payload)
        self.assertNotEqual(mapping["r1"], mapping["r2"])
        self.assertEqual(len(payload["suspected_relationships"]), 1)
        evidence = payload["suspected_relationships"][0]["evidence"]
        self.assertTrue(any("OpenAlex" in item for item in evidence))

    def test_same_doi_with_different_openalex_merges_as_provider_alias(self) -> None:
        records = {
            "r1": _record("r1", openalex_id="W1", doi="10.5555/x.1", title="Alpha Title"),
            "r2": _record("r2", openalex_id="W2", doi="10.5555/x.1", title="Beta Title"),
        }
        mapping = entity_record_mapping(_build(records))
        self.assertEqual(mapping["r1"], mapping["r2"])

    def test_conflicting_identity_is_not_merged(self) -> None:
        records = {
            "r1": _record("r1", doi="10.5555/x.1", title="Identical Title"),
            "r2": _record("r2", doi="10.5555/x.2", title="Identical Title"),
        }
        payload = _build(records)
        mapping = entity_record_mapping(payload)
        self.assertNotEqual(mapping["r1"], mapping["r2"])
        self.assertEqual(len(payload["suspected_relationships"]), 1)
        self.assertIn("conflicting DOI", payload["suspected_relationships"][0]["evidence"][0])

    def test_transitive_conflict_is_not_merged(self) -> None:
        records = {
            "a": _record("a", openalex_id="W1", doi="10.5555/d1", title="Paper One Title"),
            "b": _record("b", openalex_id="W2", doi="10.5555/d1", title="Paper Two Title"),
            "c": _record("c", openalex_id="W2", doi="10.5555/d2", title="Paper Three Title"),
        }
        mapping = entity_record_mapping(_build(records))
        self.assertEqual(mapping["a"], mapping["b"])
        self.assertNotEqual(mapping["b"], mapping["c"])

    def test_generic_title_is_not_auto_confirmed(self) -> None:
        records = {
            "r1": _record("r1", title="machine learning"),
            "r2": _record("r2", title="machine learning"),
        }
        mapping = entity_record_mapping(_build(records))
        self.assertNotEqual(mapping["r1"], mapping["r2"])

    def test_fuzzy_similar_title_is_suspected_not_merged(self) -> None:
        records = {
            "r1": _record("r1", doi="10.5555/x.1", title="Stellar spectra for parameter inference"),
            "r2": _record("r2", doi="10.5555/x.2", title="Stellar spectra for transient inference"),
        }
        payload = _build(records)
        mapping = entity_record_mapping(payload)
        self.assertNotEqual(mapping["r1"], mapping["r2"])
        self.assertEqual(len(payload["suspected_relationships"]), 1)

    def test_conflicting_identity_payload_passes_validator(self) -> None:
        records = {
            "r1": _record("r1", doi="10.5555/x.1", title="Identical Title"),
            "r2": _record("r2", doi="10.5555/x.2", title="Identical Title"),
        }
        result = validate_canonical_entities(_build(records), records=records, retrieval={})
        self.assertEqual(len(result["entities"]), 2)
        self.assertEqual(len(result["relationships"]), 1)


class EvidenceTruthfulnessTests(unittest.TestCase):
    def test_same_doi_different_titles_do_not_fabricate_title_evidence(self) -> None:
        records = {
            "r1": _record("r1", doi="10.5555/x.1", title="Completely Different Alpha"),
            "r2": _record("r2", doi="10.5555/x.1", title="Completely Different Beta"),
        }
        payload = _build(records)
        entity = payload["entities"][0]
        title_evidence = [
            item for item in entity["identity_evidence"]
            if item["evidence_type"] == "normalized_title"
        ]
        self.assertEqual(title_evidence, [])

    def test_same_openalex_different_titles_do_not_fabricate_title_evidence(self) -> None:
        records = {
            "r1": _record("r1", openalex_id="W1", title="Completely Different Alpha"),
            "r2": _record("r2", openalex_id="W1", title="Completely Different Beta"),
        }
        payload = _build(records)
        entity = payload["entities"][0]
        title_evidence = [
            item for item in entity["identity_evidence"]
            if item["evidence_type"] == "normalized_title"
        ]
        self.assertEqual(title_evidence, [])

    def test_shared_title_evidence_scope_matches_records(self) -> None:
        records = {
            "r1": _record("r1", doi="10.5555/x.1", title="Line Preserving Neural Restoration"),
            "r2": _record("r2", doi="10.5555/x.1", title="Line Preserving Neural Restoration"),
        }
        payload = _build(records)
        entity = payload["entities"][0]
        title_evidence = [
            item for item in entity["identity_evidence"]
            if item["evidence_type"] == "normalized_title"
        ]
        self.assertEqual(len(title_evidence), 1)
        self.assertEqual(title_evidence[0]["record_ids"], ["r1", "r2"])


class PostCanonicalPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = validate_w6_bootstrap_bundle(BUNDLE_PATH)
        cls.records = cls.bundle["records"]
        cls.retrieval = cls.bundle["retrieval"]
        cls.topics = cls.bundle["topics"]
        cls.pre_pool = cls.bundle["payloads"]["precanonical_candidate_pool"]

    def _canonical(self) -> dict:
        return _build(self.records)

    def _build_post_pool(self, canonical_sha256: str | None = None) -> dict:
        canonical = self._canonical()
        sha = canonical_sha256 or canonical_json_sha256(canonical)
        return build_post_canonical_pool(
            self.pre_pool,
            canonical,
            artifact_id="w6_test_post_pool_v1",
            canonical_artifact_id=CANONICAL_ARTIFACT_ID,
            canonical_sha256=sha,
            created_at=CREATED_AT,
            git_revision=GIT_REVISION,
            is_fixture=True,
        )

    def _registry(self, canonical_sha256: str | None = None) -> dict:
        sha = canonical_sha256 or canonical_json_sha256(self._canonical())
        registry = dict(self.bundle["registry"])
        registry[CANONICAL_ARTIFACT_ID] = {
            "artifact_id": CANONICAL_ARTIFACT_ID,
            "sha256": sha,
        }
        return registry

    def test_post_pool_passes_contract_validator(self) -> None:
        canonical = self._canonical()
        result = validate_canonical_entities(canonical, records=self.records, retrieval=self.retrieval)
        post_pool = self._build_post_pool()
        members = validate_candidate_pool(
            post_pool,
            topics=self.topics,
            records=self.records,
            retrieval=self.retrieval,
            registry=self._registry(),
            canonical=result,
        )
        self.assertEqual(len(members), 13)
        self.assertEqual(members["pool_denoise_008"]["canonical_entity_id"], "entity_rec_003")
        self.assertEqual(members["pool_denoise_003"]["canonical_entity_id"], "entity_rec_003")

    def test_pre_to_post_retains_source_record_provenance(self) -> None:
        post_pool = self._build_post_pool()
        pre_members = {m["pool_item_id"]: m for m in self.pre_pool["members"]}
        post_members = {m["pool_item_id"]: m for m in post_pool["members"]}
        self.assertEqual(set(pre_members), set(post_members))
        for item_id in pre_members:
            pre = copy.deepcopy(pre_members[item_id])
            post = copy.deepcopy(post_members[item_id])
            pre.pop("canonical_entity_id")
            post.pop("canonical_entity_id")
            self.assertEqual(pre, post)

    def test_post_pool_inputs_reference_canonical_entities(self) -> None:
        post_pool = self._build_post_pool()
        self.assertEqual(
            post_pool["inputs"]["canonical_entities"]["artifact_id"],
            CANONICAL_ARTIFACT_ID,
        )
        self.assertEqual(post_pool["identity_stage"], "post_canonicalization")

    def test_hash_drift_is_rejected(self) -> None:
        canonical = self._canonical()
        result = validate_canonical_entities(canonical, records=self.records, retrieval=self.retrieval)
        post_pool = self._build_post_pool()
        with self.assertRaisesRegex(ValueError, "drift"):
            validate_candidate_pool(
                post_pool,
                topics=self.topics,
                records=self.records,
                retrieval=self.retrieval,
                registry=self._registry("0" * 64),
                canonical=result,
            )


class LoaderAndNoLeakageTests(unittest.TestCase):
    def test_loader_loads_minimal_closure(self) -> None:
        inputs = load_canonicalization_inputs(BUNDLE_PATH)
        self.assertEqual(len(inputs["topics"]), 2)
        self.assertEqual(len(inputs["records"]), 10)
        self.assertEqual(len(inputs["precanonical_pool_members"]), 13)
        self.assertNotIn("canonical_entities", inputs["payloads"])
        self.assertNotIn("candidate_pool", inputs["payloads"])

    def test_loader_does_not_open_downstream_artifacts(self) -> None:
        opened: set[str] = set()

        def audit_hook(event: str, args: tuple) -> None:
            if event == "open" and args:
                path = str(args[0])
                if "w6_bootstrap" in path:
                    opened.add(os.path.basename(path))

        sys.addaudithook(audit_hook)
        try:
            load_canonicalization_inputs(BUNDLE_PATH)
        finally:
            pass
        forbidden = {
            "canonical_entities.json",
            "candidate_pool.json",
            "annotation_task_map.json",
            "annotation_tasks.json",
            "annotation_results.json",
            "annotation_reviews.json",
            "split_manifest.json",
            "hidden_label_anchor.json",
            "benchmark_manifest.json",
            "evidence_units.json",
            "synthesis_input.json",
            "structured_synthesis.json",
        }
        self.assertFalse(opened & forbidden, f"unexpected opened files: {opened & forbidden}")

    def test_loader_rejects_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            copied = Path(temp_dir) / "valid"
            shutil.copytree(BUNDLE_PATH.parent, copied)
            topics = copied / "topics.json"
            payload = json.loads(topics.read_text(encoding="utf-8"))
            payload["topics"][0]["research_question"] += " tampered"
            topics.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load_canonicalization_inputs(copied / "bundle_manifest.json")


class CanonicalizeCliTests(unittest.TestCase):
    def test_cli_produces_valid_artifacts_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "out"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = canonicalize_cli_main(
                    ["--manifest", str(BUNDLE_PATH), "--output-dir", str(out_dir)]
                )
            self.assertEqual(exit_code, 0, output.getvalue())
            self.assertIn("PASSED", output.getvalue())
            for name in (
                "canonical_entities.json",
                "post_canonical_pool.json",
                "pool_bias_audit.json",
            ):
                self.assertTrue((out_dir / name).is_file())
            audit = json.loads((out_dir / "pool_bias_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["alias_sensitivity"]["distinct_canonical_entities"], 9)
            self.assertFalse(audit["label_access"]["relevance_labels_read"])

    def test_cli_embedded_sha_matches_actual_file_sha(self) -> None:
        from src.annotation_tasks import sha256_file

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = canonicalize_cli_main(
                    ["--manifest", str(BUNDLE_PATH), "--output-dir", str(out_dir)]
                )
            self.assertEqual(exit_code, 0)
            post_pool = json.loads((out_dir / "post_canonical_pool.json").read_text(encoding="utf-8"))
            canonical_sha = post_pool["inputs"]["canonical_entities"]["sha256"]
            self.assertEqual(canonical_sha, sha256_file(out_dir / "canonical_entities.json"))
            audit = json.loads((out_dir / "pool_bias_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(
                audit["inputs"]["candidate_pool"]["sha256"],
                sha256_file(out_dir / "post_canonical_pool.json"),
            )

    def test_cli_refuses_output_dir_inside_frozen_input_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            copied = Path(temp_dir) / "valid"
            shutil.copytree(BUNDLE_PATH.parent, copied)
            manifest = copied / "bundle_manifest.json"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = canonicalize_cli_main(
                    ["--manifest", str(manifest), "--output-dir", str(copied)]
                )
            self.assertEqual(exit_code, 1)
            self.assertIn("重合", output.getvalue())

    def test_cli_refuses_non_empty_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "occupied"
            out_dir.mkdir()
            (out_dir / "existing.txt").write_text("keep", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = canonicalize_cli_main(
                    ["--manifest", str(BUNDLE_PATH), "--output-dir", str(out_dir)]
                )
            self.assertEqual(exit_code, 1)
            self.assertIn("非空", output.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
