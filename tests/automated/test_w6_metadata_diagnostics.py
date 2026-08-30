"""Offline tests for W6 metadata and retrieval diagnostics."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from app.w6_metadata_diagnostics import main as diagnostics_cli_main
from src.annotation_tasks import sha256_file
from src.w6_contracts import compute_pool_identity, load_json_object
from src.w6_metadata_diagnostics import (
    MetadataContractError,
    analyze_metadata_contract,
    build_diagnostics_report,
    collect_enrichment_proposals,
    load_and_validate_diagnostics_inputs,
    run_diagnostics,
    write_diagnostics_outputs,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VALID_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap" / "valid"
TOPICS_PATH = VALID_ROOT / "topics.json"
RETRIEVAL_PATH = VALID_ROOT / "retrieval_runs.json"
SOURCE_RECORDS_PATH = VALID_ROOT / "source_records.json"
PRECANONICAL_POOL_PATH = VALID_ROOT / "precanonical_candidate_pool.json"
TEST_REVISION = "a" * 40
TEST_TIME = "2026-08-30T08:00:00+08:00"


def _load_payload(path: Path) -> dict:
    return load_json_object(path)


def _valid_inputs():
    return load_and_validate_diagnostics_inputs(
        topics_path=TOPICS_PATH,
        retrieval_path=RETRIEVAL_PATH,
        source_records_path=SOURCE_RECORDS_PATH,
        precanonical_pool_path=PRECANONICAL_POOL_PATH,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_four_artifacts(
    root: Path,
    *,
    topics: dict | None = None,
    retrieval: dict | None = None,
    source_records: dict | None = None,
    pool: dict | None = None,
) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    payloads = {
        "topics": copy.deepcopy(topics or _load_payload(TOPICS_PATH)),
        "retrieval": copy.deepcopy(retrieval or _load_payload(RETRIEVAL_PATH)),
        "source_records": copy.deepcopy(
            source_records or _load_payload(SOURCE_RECORDS_PATH)
        ),
        "pool": copy.deepcopy(pool or _load_payload(PRECANONICAL_POOL_PATH)),
    }
    paths = {
        "topics": root / "topics.json",
        "retrieval": root / "retrieval.json",
        "source_records": root / "source_records.json",
        "pool": root / "pool.json",
    }
    for name in ("topics", "retrieval", "source_records"):
        _write_json(paths[name], payloads[name])

    pool_payload = payloads["pool"]
    pool_payload["inputs"]["topic_set"] = {
        "artifact_id": payloads["topics"]["artifact_id"],
        "sha256": sha256_file(paths["topics"]),
    }
    pool_payload["inputs"]["retrieval_provenance"] = {
        "artifact_id": payloads["retrieval"]["artifact_id"],
        "sha256": sha256_file(paths["retrieval"]),
    }
    pool_payload["inputs"]["source_records"] = {
        "artifact_id": payloads["source_records"]["artifact_id"],
        "sha256": sha256_file(paths["source_records"]),
    }
    pool_payload["pool_identity"] = compute_pool_identity(pool_payload)
    _write_json(paths["pool"], pool_payload)
    return paths


def _load_written_inputs(paths: dict[str, Path]):
    return load_and_validate_diagnostics_inputs(
        topics_path=paths["topics"],
        retrieval_path=paths["retrieval"],
        source_records_path=paths["source_records"],
        precanonical_pool_path=paths["pool"],
    )


def _by_id(rows: list[dict], field: str) -> dict[str, dict]:
    return {row[field]: row for row in rows}


class DeterministicFakeProvider:
    provider_id = "fake_metadata_provider"
    provider_version = "fixture-v1"

    def lookup(self, record):
        if record["record_id"] == "rec_006":
            return {
                "doi": {
                    "value": "10.5555/fake.enrichment.006",
                    "source": "https://example.test/fake-provider/rec-006",
                }
            }
        return {}


class MetadataContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_payload = _load_payload(SOURCE_RECORDS_PATH)

    def record(self, record_id: str) -> dict:
        return copy.deepcopy(
            next(
                row
                for row in self.source_payload["records"]
                if row["record_id"] == record_id
            )
        )

    def test_complete_metadata_is_consistent(self) -> None:
        report = analyze_metadata_contract([self.record("rec_001")])
        self.assertEqual(report["contract_consistency"]["issue_count"], 0)
        self.assertEqual(report["fields"]["abstract"]["missing_count"], 0)
        self.assertEqual(report["fields"]["provider"]["missing_count"], 0)

    def test_missing_abstract_and_doi_are_valid_missing(self) -> None:
        report = analyze_metadata_contract([self.record("rec_006")])
        self.assertEqual(report["contract_consistency"]["status"], "consistent")
        self.assertEqual(report["fields"]["abstract"]["missing_count"], 1)
        self.assertEqual(report["fields"]["doi"]["missing_count"], 1)
        self.assertEqual(
            report["missing_but_valid_records"],
            [{"record_id": "rec_006", "missing_fields": ["abstract", "doi"]}],
        )

    def test_missing_openalex_id_is_valid_when_declared(self) -> None:
        record = self.record("rec_001")
        record["openalex_id"] = None
        record["metadata_completeness"] = {
            "status": "partial",
            "missing_fields": ["openalex_id"],
            "completeness_score": 0.8,
        }
        report = analyze_metadata_contract([record])
        self.assertEqual(report["contract_consistency"]["issue_count"], 0)
        self.assertEqual(report["fields"]["openalex_id"]["missing_count"], 1)

    def test_null_abstract_without_declaration_is_inconsistent(self) -> None:
        record = self.record("rec_001")
        record["abstract"] = None
        report = analyze_metadata_contract([record])
        codes = {issue["code"] for issue in report["contract_consistency"]["issues"]}
        self.assertIn("missing_fields_mismatch", codes)
        self.assertIn("completeness_status_mismatch", codes)

    def test_declared_missing_abstract_that_exists_is_inconsistent(self) -> None:
        record = self.record("rec_001")
        record["metadata_completeness"] = {
            "status": "partial",
            "missing_fields": ["abstract"],
            "completeness_score": 0.9,
        }
        report = analyze_metadata_contract([record])
        codes = {issue["code"] for issue in report["contract_consistency"]["issues"]}
        self.assertIn("missing_fields_mismatch", codes)
        self.assertIn("completeness_status_mismatch", codes)

    def test_duplicate_provider_source_identity_is_reported(self) -> None:
        first = self.record("rec_001")
        second = self.record("rec_002")
        second["record_provenance"] = copy.deepcopy(first["record_provenance"])
        report = analyze_metadata_contract([first, second])
        duplicates = [
            issue
            for issue in report["contract_consistency"]["issues"]
            if issue["code"] == "duplicate_provider_source_record_id"
        ]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["record_ids"], ["rec_001", "rec_002"])

    def test_fake_provider_proposes_without_mutating_source(self) -> None:
        inputs = _valid_inputs()
        before = copy.deepcopy(inputs.records)
        proposals = collect_enrichment_proposals(
            inputs.records,
            DeterministicFakeProvider(),
            lookup_at=TEST_TIME,
        )
        self.assertEqual(inputs.records, before)
        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal["record_id"], "rec_006")
        self.assertEqual(proposal["field"], "doi")
        self.assertIsNone(proposal["old_value"])
        self.assertFalse(proposal["provenance"]["applied_to_source_record"])


class BootstrapDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = _valid_inputs()
        cls.report = build_diagnostics_report(
            cls.inputs, git_revision=TEST_REVISION, generated_at=TEST_TIME
        )

    def test_task_loader_consumes_correct_artifact_collections(self) -> None:
        self.assertEqual(len(self.inputs.topics), 2)
        self.assertEqual(len(self.inputs.retrieval["runs"]), 6)
        self.assertEqual(len(self.inputs.retrieval["hits"]), 17)
        self.assertEqual(len(self.inputs.records), 10)
        self.assertEqual(len(self.inputs.pool_members), 13)

    def test_bootstrap_metadata_counts_are_correct(self) -> None:
        metadata = self.report["metadata"]
        expected_missing = {
            "abstract": 1,
            "doi": 1,
            "openalex_id": 0,
            "publication_year": 0,
            "venue": 0,
            "authors": 0,
            "landing_page_url": 0,
            "provider": 0,
        }
        self.assertEqual(
            {field: stats["missing_count"] for field, stats in metadata["fields"].items()},
            expected_missing,
        )
        self.assertEqual(metadata["contract_consistency"]["issue_count"], 0)
        self.assertEqual(metadata["missing_but_valid_record_count"], 1)

    def test_run_level_diagnostics_use_separate_hits(self) -> None:
        runs = _by_id(self.report["retrieval"]["runs"], "retrieval_run_id")
        self.assertEqual(runs["run_denoise_openalex"]["hit_count"], 5)
        self.assertEqual(runs["run_denoise_bm25"]["hit_count"], 3)
        self.assertEqual(runs["run_denoise_tail"]["hit_count"], 1)
        self.assertEqual(runs["run_transient_openalex"]["hit_count"], 4)
        self.assertEqual(runs["run_transient_dense"]["hit_count"], 3)
        self.assertEqual(runs["run_transient_tail"]["hit_count"], 1)
        self.assertTrue(all(row["contract_valid"] for row in runs.values()))
        self.assertTrue(
            all(row["completion_status"] == "completed" for row in runs.values())
        )

    def test_multiple_runs_for_one_query_variant_are_aggregated(self) -> None:
        queries = {
            (row["topic_id"], row["query_variant_id"]): row
            for row in self.report["retrieval"]["query_variants"]
        }
        denoise_qv2 = queries[("w6_fixture_topic_denoising", "denoise_qv2")]
        transient_qv2 = queries[("w6_fixture_topic_transients", "transient_qv2")]
        self.assertEqual(denoise_qv2["run_count"], 2)
        self.assertEqual(denoise_qv2["hit_count"], 4)
        self.assertEqual(denoise_qv2["unique_record_count"], 4)
        self.assertEqual(transient_qv2["run_count"], 2)
        self.assertEqual(transient_qv2["hit_count"], 4)

    def test_pairwise_overlap_and_multi_single_counts(self) -> None:
        overlap = self.report["retrieval"]["pairwise_query_overlap"]
        self.assertEqual(
            [
                (row["intersection_count"], row["union_count"], row["jaccard"])
                for row in overlap
            ],
            [(2, 7, 0.285714), (2, 6, 0.333333)],
        )
        summary = self.report["retrieval"]["summary"]
        self.assertEqual(summary["global_unique_record_count"], 10)
        self.assertEqual(summary["topic_record_count"], 13)
        self.assertEqual(summary["multi_query_topic_record_count"], 4)
        self.assertEqual(summary["single_query_only_topic_record_count"], 9)

    def test_topic_and_pool_diagnostics_are_correct(self) -> None:
        topics = _by_id(self.report["retrieval"]["topics"], "topic_id")
        denoise = topics["w6_fixture_topic_denoising"]
        transient = topics["w6_fixture_topic_transients"]
        self.assertEqual(
            (
                denoise["run_count"],
                denoise["hit_count"],
                denoise["unique_record_count"],
                denoise["precanonical_pool_member_count"],
            ),
            (3, 9, 7, 7),
        )
        self.assertEqual(
            (
                transient["run_count"],
                transient["hit_count"],
                transient["unique_record_count"],
                transient["precanonical_pool_member_count"],
            ),
            (3, 8, 6, 6),
        )
        self.assertEqual(denoise["retrieved_not_pooled_count"], 0)
        self.assertEqual(transient["pooled_not_retrieved_count"], 0)

    def test_pool_metadata_rates_and_year_venue_distributions(self) -> None:
        topics = _by_id(self.report["retrieval"]["topics"], "topic_id")
        denoise = topics["w6_fixture_topic_denoising"]["precanonical_pool_metadata"]
        transient = topics["w6_fixture_topic_transients"][
            "precanonical_pool_metadata"
        ]
        self.assertEqual(denoise["fields"]["abstract"]["missing_rate"], 0.142857)
        self.assertEqual(denoise["fields"]["doi"]["missing_count"], 1)
        self.assertEqual(transient["fields"]["abstract"]["missing_rate"], 0.166667)
        self.assertEqual(
            denoise["year_distribution"],
            [
                {"publication_year": 2020, "count": 1},
                {"publication_year": 2021, "count": 1},
                {"publication_year": 2022, "count": 1},
                {"publication_year": 2023, "count": 1},
                {"publication_year": 2024, "count": 1},
                {"publication_year": 2025, "count": 2},
            ],
        )
        venue_counts = {row["venue"]: row["count"] for row in denoise["venue_distribution"]}
        self.assertEqual(venue_counts["Fixture Spectroscopy"], 2)

    def test_report_binds_input_identity_and_csv_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = write_diagnostics_outputs(self.report, temporary)
            written = load_json_object(paths["report"])
            self.assertEqual(
                written["inputs"]["source_records"]["sha256"],
                sha256_file(SOURCE_RECORDS_PATH),
            )
            self.assertEqual(
                written["outputs"]["metadata_completeness_csv"]["sha256"],
                sha256_file(paths["metadata_csv"]),
            )
            self.assertTrue(written["report_identity"].startswith("w6-diagnostics:sha256:"))
            self.assertFalse(written["label_access"]["relevance_labels_read"])

    def test_report_is_deterministic_under_mapping_order_changes(self) -> None:
        reversed_inputs = replace(
            self.inputs,
            topics=dict(reversed(list(self.inputs.topics.items()))),
            retrieval={
                "runs": dict(reversed(list(self.inputs.retrieval["runs"].items()))),
                "hits": dict(reversed(list(self.inputs.retrieval["hits"].items()))),
            },
            records=dict(reversed(list(self.inputs.records.items()))),
            pool_members=dict(reversed(list(self.inputs.pool_members.items()))),
        )
        reordered_report = build_diagnostics_report(
            reversed_inputs, git_revision=TEST_REVISION, generated_at=TEST_TIME
        )
        self.assertEqual(self.report, reordered_report)
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_paths = write_diagnostics_outputs(self.report, first)
            second_paths = write_diagnostics_outputs(reordered_report, second)
            self.assertEqual(
                first_paths["report"].read_bytes(), second_paths["report"].read_bytes()
            )
            self.assertEqual(
                first_paths["metadata_csv"].read_bytes(),
                second_paths["metadata_csv"].read_bytes(),
            )

    def test_diagnostics_ignore_artifact_collection_order(self) -> None:
        retrieval = _load_payload(RETRIEVAL_PATH)
        retrieval["runs"].reverse()
        retrieval["hits"].reverse()
        source_records = _load_payload(SOURCE_RECORDS_PATH)
        source_records["records"].reverse()
        pool = _load_payload(PRECANONICAL_POOL_PATH)
        pool["members"].reverse()
        with tempfile.TemporaryDirectory() as temporary:
            paths = _write_four_artifacts(
                Path(temporary),
                retrieval=retrieval,
                source_records=source_records,
                pool=pool,
            )
            reordered = build_diagnostics_report(
                _load_written_inputs(paths),
                git_revision=TEST_REVISION,
                generated_at=TEST_TIME,
            )
        self.assertEqual(self.report["metadata"], reordered["metadata"])
        original_retrieval = copy.deepcopy(self.report["retrieval"])
        reordered_retrieval = copy.deepcopy(reordered["retrieval"])
        original_pool_identity = original_retrieval["precanonical_pool"].pop(
            "pool_identity"
        )
        reordered_pool_identity = reordered_retrieval["precanonical_pool"].pop(
            "pool_identity"
        )
        self.assertEqual(original_retrieval, reordered_retrieval)
        self.assertNotEqual(original_pool_identity, reordered_pool_identity)

    def test_non_object_record_has_structured_consistency_issue(self) -> None:
        analysis = analyze_metadata_contract([None])
        self.assertEqual(analysis["contract_consistency"]["issue_count"], 1)
        self.assertEqual(
            analysis["contract_consistency"]["issues"][0]["code"],
            "record_not_object",
        )

    def test_build_report_does_not_mutate_source_provenance(self) -> None:
        before = copy.deepcopy(self.inputs.records)
        build_diagnostics_report(
            self.inputs,
            git_revision=TEST_REVISION,
            generated_at=TEST_TIME,
            enrichment_provider=DeterministicFakeProvider(),
            enrichment_lookup_at=TEST_TIME,
        )
        self.assertEqual(self.inputs.records, before)


class ContractAndCliTests(unittest.TestCase):
    def test_same_query_variant_id_can_be_reused_across_topics(self) -> None:
        topics = _load_payload(TOPICS_PATH)
        retrieval = _load_payload(RETRIEVAL_PATH)
        replacements = {
            "transient_qv1": "denoise_qv1",
            "transient_qv2": "denoise_qv2",
        }
        transient = next(
            row
            for row in topics["topics"]
            if row["topic_id"] == "w6_fixture_topic_transients"
        )
        for variant in transient["acquisition_query_variants"]:
            variant["query_variant_id"] = replacements[variant["query_variant_id"]]
        for run in retrieval["runs"]:
            if run["topic_id"] == "w6_fixture_topic_transients":
                run["query_variant_id"] = replacements[run["query_variant_id"]]
        with tempfile.TemporaryDirectory() as temporary:
            paths = _write_four_artifacts(
                Path(temporary), topics=topics, retrieval=retrieval
            )
            inputs = _load_written_inputs(paths)
            report = build_diagnostics_report(
                inputs, git_revision=TEST_REVISION, generated_at=TEST_TIME
            )
        shared_qv1 = [
            row
            for row in report["retrieval"]["query_variants"]
            if row["query_variant_id"] == "denoise_qv1"
        ]
        self.assertEqual(len(shared_qv1), 2)
        self.assertEqual(
            {row["topic_id"] for row in shared_qv1},
            {"w6_fixture_topic_denoising", "w6_fixture_topic_transients"},
        )

    def test_inconsistent_artifact_fails_closed_with_structured_error(self) -> None:
        source = _load_payload(SOURCE_RECORDS_PATH)
        rec006 = next(row for row in source["records"] if row["record_id"] == "rec_006")
        rec006["metadata_completeness"]["missing_fields"] = []
        with tempfile.TemporaryDirectory() as temporary:
            paths = _write_four_artifacts(Path(temporary), source_records=source)
            with self.assertRaises(MetadataContractError) as context:
                _load_written_inputs(paths)
        self.assertIn("missing_fields_mismatch", {i["code"] for i in context.exception.issues})

    def test_invalid_artifact_type_is_rejected(self) -> None:
        topics = _load_payload(TOPICS_PATH)
        topics["artifact_type"] = "not_w6_topics"
        with tempfile.TemporaryDirectory() as temporary:
            paths = _write_four_artifacts(Path(temporary), topics=topics)
            with self.assertRaisesRegex(ValueError, "artifact_type"):
                _load_written_inputs(paths)

    def test_missing_hit_to_record_reference_is_rejected(self) -> None:
        retrieval = _load_payload(RETRIEVAL_PATH)
        retrieval["hits"][0]["record_id"] = "rec_missing"
        with tempfile.TemporaryDirectory() as temporary:
            paths = _write_four_artifacts(Path(temporary), retrieval=retrieval)
            with self.assertRaisesRegex(ValueError, "provenance"):
                _load_written_inputs(paths)

    def test_cli_end_to_end_works_from_another_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "out"
            old_cwd = Path.cwd()
            stdout = io.StringIO()
            stderr = io.StringIO()
            try:
                os.chdir(root)
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exit_code = diagnostics_cli_main(
                        [
                            "--topics",
                            str(TOPICS_PATH),
                            "--retrieval",
                            str(RETRIEVAL_PATH),
                            "--source-records",
                            str(SOURCE_RECORDS_PATH),
                            "--precanonical-pool",
                            str(PRECANONICAL_POOL_PATH),
                            "--output-dir",
                            str(output),
                        ]
                    )
            finally:
                os.chdir(old_cwd)
            self.assertEqual(exit_code, 0, stderr.getvalue())
            self.assertTrue((output / "diagnostics_report.json").is_file())
            self.assertTrue((output / "metadata_completeness.csv").is_file())
            self.assertIn("runs=6", stdout.getvalue())

    def test_label_free_dependency_closure_uses_only_four_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs_root = root / "inputs"
            inputs_root.mkdir()
            copied = {}
            for name, source in {
                "topics": TOPICS_PATH,
                "retrieval": RETRIEVAL_PATH,
                "source_records": SOURCE_RECORDS_PATH,
                "pool": PRECANONICAL_POOL_PATH,
            }.items():
                target = inputs_root / source.name
                shutil.copy2(source, target)
                copied[name] = target
            result = run_diagnostics(
                topics_path=copied["topics"],
                retrieval_path=copied["retrieval"],
                source_records_path=copied["source_records"],
                precanonical_pool_path=copied["pool"],
                output_dir=root / "outputs",
                git_revision=TEST_REVISION,
                generated_at=TEST_TIME,
            )
            self.assertEqual(result["report"]["counts"]["retrieval_hit_count"], 17)
            self.assertEqual(
                sorted(path.name for path in inputs_root.iterdir()),
                [
                    "precanonical_candidate_pool.json",
                    "retrieval_runs.json",
                    "source_records.json",
                    "topics.json",
                ],
            )


if __name__ == "__main__":
    unittest.main()
