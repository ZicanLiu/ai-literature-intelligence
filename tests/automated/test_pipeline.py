"""统一 Pipeline 的离线端到端与 provenance 回归测试。"""

from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from copy import deepcopy
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

from app.run_pipeline import main as pipeline_main
from src.deduplication import find_exact_duplicates
from src.pipeline import (
    RANKED_FIELDS,
    PipelineConfig,
    load_pipeline_csv,
    load_pipeline_labels,
    run_unified_pipeline,
)
from src.processor import add_preliminary_scores, calculate_recency_score


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "pipeline"
RANKING_KEYWORD = "machine learning stellar parameter estimation spectra"


class UnifiedPipelineEndToEndTests(unittest.TestCase):
    """两个 acquisition query 合成一个可追溯 parent run。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.output_root = Path(cls.temp_dir.name) / "experiments"
        cls.config = PipelineConfig(
            project_root=PROJECT_ROOT,
            terms_path=FIXTURE_DIR / "domain_terms.csv",
            acquisition_query_ids=("q01_broad_ml", "q02_classification"),
            ranking_keyword=RANKING_KEYWORD,
            mode="offline",
            max_results_per_query=10,
            output_root=cls.output_root,
            run_name="pipeline-e2e",
            labels_path=FIXTURE_DIR / "labels.csv",
            offline_fixture_path=FIXTURE_DIR / "offline_queries.json",
        )
        cls.result = run_unified_pipeline(cls.config)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def test_complete_offline_e2e_counts_and_evaluation(self) -> None:
        counts = self.result.run_config["counts"]
        self.assertEqual(counts["query_count"], 2)
        self.assertEqual(counts["combined_count"], 8)
        self.assertEqual(counts["exact_duplicate_count"], 2)
        self.assertEqual(counts["kept_count"], 6)
        self.assertGreaterEqual(counts["suspected_pair_count"], 1)
        self.assertEqual(counts["ranked_count"], 6)
        self.assertIsNotNone(self.result.evaluation)
        self.assertEqual(self.result.evaluation["policy"]["used_rows"], 4)

    def test_same_openalex_id_unions_all_provenance(self) -> None:
        paper = next(
            item
            for item in self.result.kept_papers
            if item["openalex_id"] == "https://openalex.org/W1000000002"
        )
        self.assertEqual(
            paper["source_query_ids"], ["q01_broad_ml", "q02_classification"]
        )
        self.assertEqual(len(paper["source_run_ids"]), 2)
        self.assertEqual(len(paper["source_keywords"]), 2)

    def test_different_openalex_ids_with_same_doi_use_exact_rule(self) -> None:
        doi_records = [
            row for row in self.result.exact_duplicates if row["rule"] == "same_doi"
        ]
        self.assertEqual(len(doi_records), 1)
        kept = next(
            item
            for item in self.result.kept_papers
            if item["openalex_id"] == "https://openalex.org/W1000000004"
        )
        self.assertEqual(
            kept["source_query_ids"], ["q01_broad_ml", "q02_classification"]
        )

    def test_cleaning_finishes_before_provenance_is_attached(self) -> None:
        self.assertEqual(len(self.result.combined_papers), 8)
        for paper in self.result.combined_papers:
            self.assertIsInstance(paper["source_query_ids"], list)
            self.assertIsInstance(paper["source_run_ids"], list)
            self.assertIsInstance(paper["source_keywords"], list)
            self.assertTrue(paper["run_id"])

    def test_suspected_pairs_enter_queue_without_removal(self) -> None:
        ids = {
            frozenset((row["left_id"], row["right_id"]))
            for row in self.result.suspected_duplicates
        }
        expected_pair = frozenset(
            (
                "https://openalex.org/W1000000006",
                "https://openalex.org/W1000000007",
            )
        )
        self.assertIn(expected_pair, ids)
        self.assertEqual(len(self.result.ranked_papers), len(self.result.kept_papers))
        self.assertEqual(
            self.result.run_config["algorithms"]["suspected_dedup"]["automatic_removal"],
            False,
        )

    def test_output_round_trip_preserves_provenance_and_w2_fields(self) -> None:
        output_file = self.result.run_dir / "ranking" / "ranked_papers.csv"
        rows = load_pipeline_csv(output_file)
        self.assertEqual(len(rows), 6)
        required = {
            "source_query_ids",
            "source_run_ids",
            "source_keywords",
            "combined_relevance_score",
            "stage1_relevance_level",
            "stage2_ranking_score",
            "old_rank",
            "new_rank",
            "rank_change",
        }
        self.assertTrue(required <= set(rows[0]))
        self.assertEqual(list(rows[0]), RANKED_FIELDS)
        self.assertIsInstance(rows[0]["source_query_ids"], list)

    def test_run_config_records_reproducible_parameters_without_absolute_paths(self) -> None:
        config = self.result.run_config
        self.assertEqual(config["ranking_keyword"], RANKING_KEYWORD)
        self.assertEqual(
            config["acquisition_query_ids"], ["q01_broad_ml", "q02_classification"]
        )
        self.assertIn("stage2_weights", config["algorithms"])
        self.assertEqual(config["status"], "completed")
        rendered = json.dumps(config, ensure_ascii=False)
        self.assertNotIn(str(PROJECT_ROOT), rendered)
        self.assertNotIn(str(self.output_root), rendered)

    def test_same_configuration_creates_a_second_unique_parent_run(self) -> None:
        second = run_unified_pipeline(self.config)
        self.assertNotEqual(second.run_id, self.result.run_id)
        self.assertTrue(self.result.run_dir.is_dir())
        self.assertTrue(second.run_dir.is_dir())


class UnifiedPipelineValidationTests(unittest.TestCase):
    def test_exact_alias_chain_and_provenance_do_not_mutate_input(self) -> None:
        papers = [
            {
                "openalex_id": "W1",
                "doi": "DOI-X",
                "title": "A",
                "source_query_ids": ["q1"],
                "source_run_ids": ["r1"],
                "source_keywords": ["k1"],
            },
            {
                "openalex_id": "W2",
                "doi": "DOI-X",
                "title": "B",
                "source_query_ids": ["q2"],
                "source_run_ids": ["r2"],
                "source_keywords": ["k2"],
            },
            {
                "openalex_id": "W2",
                "doi": "DOI-Y",
                "title": "C",
                "source_query_ids": ["q3"],
                "source_run_ids": ["r3"],
                "source_keywords": ["k3"],
            },
        ]
        before = deepcopy(papers)
        result = find_exact_duplicates(papers, merge_provenance=True)
        self.assertEqual(papers, before)
        self.assertEqual(len(result["kept_papers"]), 1)
        self.assertEqual(
            [row["rule"] for row in result["exact_duplicates"]],
            ["same_doi", "same_openalex_id"],
        )
        kept = result["kept_papers"][0]
        self.assertEqual(kept["source_query_ids"], ["q1", "q2", "q3"])
        self.assertEqual(kept["source_run_ids"], ["r1", "r2", "r3"])
        self.assertEqual(kept["source_keywords"], ["k1", "k2", "k3"])

    def test_conflicting_exact_aliases_are_rejected_in_merge_mode(self) -> None:
        papers = [
            {"openalex_id": "W1", "doi": "DOI-X", "title": "A"},
            {"openalex_id": "W2", "doi": "DOI-Y", "title": "B"},
            {"openalex_id": "W1", "doi": "DOI-Y", "title": "Conflict"},
        ]
        with self.assertRaisesRegex(ValueError, "标识冲突"):
            find_exact_duplicates(papers, merge_provenance=True)

    def test_explicit_recency_reference_year_controls_baseline_score(self) -> None:
        paper = {
            "title": "Stellar spectrum",
            "abstract": "machine learning",
            "publication_year": 2020,
            "cited_by_count": 0,
            "doi": "",
            "authors": "",
            "source_name": "",
            "landing_page_url": "",
        }
        self.assertEqual(calculate_recency_score(paper, reference_year=2025), 0.5)
        self.assertEqual(calculate_recency_score(paper, reference_year=2028), 0.2)
        scored = add_preliminary_scores(
            [paper], RANKING_KEYWORD, reference_year=2025
        )
        self.assertEqual(scored[0]["recency_score"], 0.5)
        self.assertEqual(
            calculate_recency_score(paper),
            calculate_recency_score(paper, reference_year=datetime.now().year),
        )

    def test_missing_ranking_keyword_is_rejected_before_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "experiments"
            config = PipelineConfig(
                project_root=PROJECT_ROOT,
                terms_path=FIXTURE_DIR / "domain_terms.csv",
                acquisition_query_ids=("q01_broad_ml",),
                ranking_keyword="   ",
                mode="offline",
                output_root=output_root,
                offline_fixture_path=FIXTURE_DIR / "offline_queries.json",
            )
            with self.assertRaisesRegex(ValueError, "ranking_keyword"):
                run_unified_pipeline(config)
            self.assertFalse(output_root.exists())

    def test_default_label_policy_excludes_ai_draft_and_pending_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            label_file = Path(temp_dir) / "labels.csv"
            with label_file.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["openalex_id", "label", "annotator", "review_status"],
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {"openalex_id": "W1", "label": "高度相关", "annotator": "student", "review_status": "confirmed"},
                        {"openalex_id": "W2", "label": "不相关", "annotator": "AI-assisted-draft", "review_status": "待人工复核"},
                        {"openalex_id": "W3", "label": "部分相关", "annotator": "student", "review_status": "待人工复核"},
                    ]
                )
            labels, stats = load_pipeline_labels(label_file)
            self.assertEqual(labels, {"W1": "高度相关"})
            self.assertEqual(stats["excluded_ai_assisted_rows"], 1)
            self.assertEqual(stats["excluded_pending_review_rows"], 1)
            all_labels, all_stats = load_pipeline_labels(
                label_file, include_unverified=True
            )
            self.assertEqual(len(all_labels), 3)
            self.assertEqual(all_stats["used_rows"], 3)

    def test_duplicate_label_openalex_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            label_file = Path(temp_dir) / "labels.csv"
            with label_file.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["openalex_id", "label"])
                writer.writeheader()
                writer.writerows(
                    [
                        {"openalex_id": "W1", "label": "高度相关"},
                        {"openalex_id": "W1", "label": "不相关"},
                    ]
                )
            with self.assertRaisesRegex(ValueError, "openalex_id 重复"):
                load_pipeline_labels(label_file)

    def test_cli_runs_offline_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code = pipeline_main(
                [
                    "--query-ids",
                    "q01_broad_ml",
                    "q02_classification",
                    "--ranking-keyword",
                    RANKING_KEYWORD,
                    "--mode",
                    "offline",
                    "--max-results-per-query",
                    "10",
                    "--terms",
                    str(FIXTURE_DIR / "domain_terms.csv"),
                    "--offline-fixture",
                    str(FIXTURE_DIR / "offline_queries.json"),
                    "--labels",
                    str(FIXTURE_DIR / "labels.csv"),
                    "--output-root",
                    str(Path(temp_dir) / "runs"),
                ]
            )
            self.assertEqual(exit_code, 0)

    def test_cli_post_creation_failure_is_safe_and_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "runs"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = pipeline_main(
                    [
                        "--query-ids",
                        "q03_parameters",
                        "--ranking-keyword",
                        RANKING_KEYWORD,
                        "--mode",
                        "offline",
                        "--terms",
                        str(FIXTURE_DIR / "domain_terms.csv"),
                        "--offline-fixture",
                        str(FIXTURE_DIR / "offline_queries.json"),
                        "--output-root",
                        str(output_root),
                    ]
                )
            self.assertEqual(exit_code, 1)
            self.assertIn("Pipeline 运行失败", stdout.getvalue())
            run_dirs = list(output_root.iterdir())
            self.assertEqual(len(run_dirs), 1)
            config = json.loads(
                (run_dirs[0] / "run_config.json").read_text(encoding="utf-8")
            )
            self.assertEqual(config["status"], "failed")
            self.assertFalse(config["success"])
            self.assertNotIn(str(PROJECT_ROOT), stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
