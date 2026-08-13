"""W4 Benchmark Evaluation Adapter 的定向离线测试。

覆盖：W4 标签解析、labels 加载、judged 指标复用、error case 分类，以及用真实
candidate pool + source 样例的端到端评价。全部离线，不读取网络、.env 或 API Key，
不写入正式输出目录。
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from src.annotation_tasks import load_research_queries, read_csv_rows
from src.evaluation import (
    count_irrelevant_in_top_k,
    filter_grades_to_ranked,
    judged_count_at_k,
    judged_ndcg_at_k,
    judged_precision_at_k,
)
from src.w4_benchmark_evaluation import (
    ERROR_CASE_FIELDS,
    METRIC_KEYS,
    METRIC_KS,
    average_metrics,
    build_error_cases,
    build_metric_rows,
    build_source_index,
    classify_error_case,
    compute_method_metrics,
    evaluate_benchmark,
    load_benchmark_labels,
    parse_w4_label,
    rank_query_papers,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_POOL = (
    PROJECT_ROOT / "data" / "annotation_tasks" / "w4" / "candidate_pool_v0.1.csv"
)
RESEARCH_QUERIES = PROJECT_ROOT / "configs" / "w4" / "research_queries.json"
SOURCE_CSV = (
    PROJECT_ROOT / "data" / "samples" / "w2" / "domain_query" / "live_query_sample.csv"
)


class W4LabelParsingTests(unittest.TestCase):
    """W4 Query Relevance 标签解析。"""

    def test_digit_labels_map_to_grades(self) -> None:
        self.assertEqual(parse_w4_label("2"), 2)
        self.assertEqual(parse_w4_label("1"), 1)
        self.assertEqual(parse_w4_label("0"), 0)

    def test_unlabeled_and_pending_have_no_grade(self) -> None:
        self.assertIsNone(parse_w4_label(None))
        self.assertIsNone(parse_w4_label(""))
        self.assertIsNone(parse_w4_label("   "))
        self.assertIsNone(parse_w4_label("?"))

    def test_illegal_label_raises_value_error(self) -> None:
        for illegal in ("3", "高度相关", "high", "-1"):
            with self.subTest(label=illegal):
                with self.assertRaises(ValueError):
                    parse_w4_label(illegal)


class BenchmarkLabelLoadingTests(unittest.TestCase):
    """adjudicated labels 文件加载。"""

    def _write_labels(self, rows: list[tuple[str, str]]) -> Path:
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "labels.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["pair_id", "label"])
            writer.writerows(rows)
        return path

    def test_load_pair_id_to_label(self) -> None:
        path = self._write_labels(
            [("w4_rq01_001", "2"), ("w4_rq01_002", "0"), ("w4_rq01_003", "?")]
        )
        labels = load_benchmark_labels(path)
        self.assertEqual(
            labels,
            {"w4_rq01_001": "2", "w4_rq01_002": "0", "w4_rq01_003": "?"},
        )

    def test_empty_label_row_is_skipped(self) -> None:
        path = self._write_labels([("w4_rq01_001", "2"), ("w4_rq01_002", "")])
        labels = load_benchmark_labels(path)
        self.assertNotIn("w4_rq01_002", labels)

    def test_missing_columns_raise_value_error(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "labels.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            handle.write("openalex_id,label\n")
        with self.assertRaises(ValueError):
            load_benchmark_labels(path)

    def test_missing_file_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            load_benchmark_labels(Path(tempfile.mkdtemp()) / "not_exist.csv")


class MethodMetricsTests(unittest.TestCase):
    """指标必须复用 src.evaluation 的 judged（condensed）口径。"""

    def setUp(self) -> None:
        self.ranked_ids = ["A", "B", "C", "D", "E", "F"]
        self.grade_map = {"A": 2, "B": 0, "C": 1}

    def test_metrics_match_evaluation_functions(self) -> None:
        metrics = compute_method_metrics(self.ranked_ids, self.grade_map)
        filtered = filter_grades_to_ranked(self.ranked_ids, self.grade_map)
        for k in METRIC_KS:
            self.assertEqual(
                metrics[f"ndcg_at_{k}"],
                judged_ndcg_at_k(self.ranked_ids, filtered, k),
            )
            self.assertEqual(
                metrics[f"precision_at_{k}"],
                judged_precision_at_k(self.ranked_ids, filtered, k),
            )
            self.assertEqual(
                metrics[f"irrelevant_top_{k}"],
                count_irrelevant_in_top_k(self.ranked_ids, filtered, k),
            )
            self.assertEqual(
                metrics[f"coverage_at_{k}"],
                judged_count_at_k(self.ranked_ids, filtered, k)
                / len(self.ranked_ids[:k]),
            )

    def test_metric_keys_are_exactly_the_core_set(self) -> None:
        metrics = compute_method_metrics(self.ranked_ids, self.grade_map)
        self.assertEqual(set(metrics), set(METRIC_KEYS))
        self.assertEqual(
            METRIC_KEYS,
            [
                "ndcg_at_5",
                "ndcg_at_10",
                "precision_at_5",
                "precision_at_10",
                "coverage_at_5",
                "coverage_at_10",
                "irrelevant_top_5",
                "irrelevant_top_10",
            ],
        )

    def test_unlabeled_paper_is_not_irrelevant(self) -> None:
        metrics = compute_method_metrics(["U", "A", "B"], {"A": 2})
        self.assertEqual(metrics["irrelevant_top_5"], 0)
        # U 未标注，不算不相关，也不稀释 judged precision。
        self.assertEqual(metrics["precision_at_5"], 1.0)

    def test_metrics_none_without_graded_labels(self) -> None:
        metrics = compute_method_metrics(["A", "B", "C"], {})
        self.assertIsNone(metrics["ndcg_at_5"])
        self.assertIsNone(metrics["precision_at_5"])
        # coverage 按「原始 Top K 中已标注比例」计算，无标注时是 0.0 而非 None。
        self.assertEqual(metrics["coverage_at_5"], 0.0)
        self.assertEqual(metrics["irrelevant_top_5"], 0)


class ErrorCaseClassificationTests(unittest.TestCase):
    """候选错误类型 A/B/C/D/E 的判定。"""

    def test_type_a_highly_relevant_ranked_low(self) -> None:
        self.assertIn("A", classify_error_case("2", 10, 12))

    def test_type_a_not_fired_when_highly_relevant_in_top_k(self) -> None:
        self.assertNotIn("A", classify_error_case("2", 1, 3))

    def test_type_b_irrelevant_in_top_k(self) -> None:
        self.assertIn("B", classify_error_case("0", 4, 9))
        self.assertIn("B", classify_error_case("0", 9, 4))

    def test_type_c_baseline_high_two_stage_drops(self) -> None:
        self.assertIn("C", classify_error_case("1", 2, 8))

    def test_type_d_two_stage_high_baseline_low(self) -> None:
        self.assertIn("D", classify_error_case("1", 8, 2))

    def test_type_e_pending_discussion(self) -> None:
        self.assertIn("E", classify_error_case("?", 5, 5))

    def test_no_type_for_middle_grades(self) -> None:
        self.assertEqual(classify_error_case("1", 6, 6), [])

    def test_multiple_types_can_coexist(self) -> None:
        # 高度相关且排名靠后（A），同时 baseline 高、two-stage 明显下降（C）。
        types = classify_error_case("2", 3, 10)
        self.assertIn("A", types)
        self.assertIn("C", types)


class BenchmarkEndToEndTests(unittest.TestCase):
    """用真实 candidate pool + source 样例的端到端评价。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.pool_rows = read_csv_rows(CANDIDATE_POOL)[1]
        cls.research_queries = load_research_queries(RESEARCH_QUERIES)
        cls.source_index = build_source_index(SOURCE_CSV)
        # 合成 labels：全部 pair 标「高度相关」，得到确定、可断言的指标值。
        cls.labels = {row["pair_id"]: "2" for row in cls.pool_rows}
        cls.result = evaluate_benchmark(
            pool_rows=cls.pool_rows,
            labels=cls.labels,
            research_queries=cls.research_queries,
            source_index=cls.source_index,
            reference_year=2026,
        )

    def test_three_research_queries_evaluated_separately(self) -> None:
        expected = {
            str(q["research_query_id"])
            for q in self.research_queries["queries"]
        }
        self.assertEqual(set(self.result["per_query"]), expected)

    def test_each_query_has_20_pairs_and_20_labels(self) -> None:
        for query_result in self.result["per_query"].values():
            self.assertEqual(query_result["pair_count"], 20)
            self.assertEqual(query_result["labeled_count"], 20)

    def test_each_query_has_baseline_and_two_stage_metrics(self) -> None:
        for query_result in self.result["per_query"].values():
            for method in ("baseline", "two_stage"):
                self.assertEqual(set(query_result[method]), set(METRIC_KEYS))

    def test_all_highly_relevant_gives_perfect_metrics(self) -> None:
        for query_result in self.result["per_query"].values():
            for method in ("baseline", "two_stage"):
                metrics = query_result[method]
                self.assertAlmostEqual(metrics["ndcg_at_5"], 1.0)
                self.assertAlmostEqual(metrics["precision_at_5"], 1.0)
                self.assertAlmostEqual(metrics["coverage_at_5"], 1.0)
                self.assertEqual(metrics["irrelevant_top_5"], 0)

    def test_macro_average_of_perfect_queries_is_perfect(self) -> None:
        for method in ("baseline", "two_stage"):
            metrics = self.result["macro"][method]
            self.assertAlmostEqual(metrics["ndcg_at_5"], 1.0)
            self.assertAlmostEqual(metrics["precision_at_5"], 1.0)

    def test_error_cases_cover_all_pairs_with_required_fields(self) -> None:
        rows = build_error_cases(self.result["per_query"], self.labels)
        self.assertEqual(len(rows), 60)
        for row in rows:
            self.assertEqual(set(row), set(ERROR_CASE_FIELDS))
            self.assertEqual(
                row["rank_delta"], row["baseline_rank"] - row["two_stage_rank"]
            )

    def test_metric_rows_include_macro_summary(self) -> None:
        rows = build_metric_rows(self.result)
        research_ids = {row["research_query_id"] for row in rows}
        self.assertIn("macro", research_ids)
        self.assertEqual(len(rows), 3 * 2 + 2)

    def test_rank_query_papers_reuses_existing_ranking(self) -> None:
        query = self.research_queries["queries"][0]
        pairs = [
            row
            for row in self.pool_rows
            if row["research_query_id"] == query["research_query_id"]
        ]
        ranking = rank_query_papers(
            pairs, self.source_index, query["ranking_keyword"], 2026
        )
        self.assertEqual(len(ranking["baseline_ids"]), 20)
        self.assertEqual(len(ranking["two_stage_ids"]), 20)
        by_old = sorted(
            ranking["ranked_papers"], key=lambda paper: paper["old_rank"]
        )
        by_new = sorted(
            ranking["ranked_papers"], key=lambda paper: paper["new_rank"]
        )
        self.assertEqual(
            ranking["baseline_ids"], [paper["openalex_id"] for paper in by_old]
        )
        self.assertEqual(
            ranking["two_stage_ids"], [paper["openalex_id"] for paper in by_new]
        )
        for paper in ranking["ranked_papers"]:
            self.assertTrue(paper.get("pair_id"))

    def test_source_index_contains_all_pool_works(self) -> None:
        for row in self.pool_rows:
            self.assertIn(row["openalex_id"], self.source_index)

    def test_pool_missing_required_field_raises(self) -> None:
        bad_rows = [{"pair_id": "x", "research_query_id": "rq"}]
        with self.assertRaises(ValueError):
            evaluate_benchmark(
                pool_rows=bad_rows,
                labels={},
                research_queries=self.research_queries,
                source_index=self.source_index,
            )


class AverageMetricsTests(unittest.TestCase):
    """macro average 跳过 None，全 None 保持 None。"""

    def _metrics(self, ndcg5: float | None, ndcg10: float | None) -> dict:
        base = {key: 0 for key in METRIC_KEYS}
        base["ndcg_at_5"] = ndcg5
        base["ndcg_at_10"] = ndcg10
        return base

    def test_average_skips_none(self) -> None:
        averaged = average_metrics(
            [self._metrics(1.0, None), self._metrics(0.5, None)]
        )
        self.assertAlmostEqual(averaged["ndcg_at_5"], 0.75)
        self.assertIsNone(averaged["ndcg_at_10"])

    def test_average_all_none_stays_none(self) -> None:
        averaged = average_metrics(
            [self._metrics(None, None), self._metrics(None, None)]
        )
        self.assertIsNone(averaged["ndcg_at_5"])


if __name__ == "__main__":
    unittest.main()
