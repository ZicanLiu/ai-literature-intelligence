"""排序评价指标与两阶段排序的离线单元测试。

只使用内存构造数据和 tests/fixtures/ranking/ 下的 fixture，
不依赖网络，不读取 .env 或真实 API Key，不写入正式输出目录。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.evaluate_ranking import (
    STAGE1_LEVEL_GATE,
    STAGE2_SCORE_WEIGHTS,
    apply_two_stage_ranking,
    assign_stage1_level,
    prepare_baseline_papers,
    load_papers_csv,
    select_ranking_error_cases,
)
from src import processor
from src.evaluation import (
    build_grade_map,
    count_irrelevant_in_top_k,
    evaluate_ranking,
    load_label_csv,
    ndcg_at_k,
    parse_relevance_label,
    precision_at_k,
    validate_k,
    average_rank_of_highly_relevant,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "ranking"
FIXTURE_KEYWORD = "machine learning stellar parameter estimation spectra"

BASELINE_WEIGHTS_SNAPSHOT = {
    "relevance_score": 0.40,
    "impact_score": 0.30,
    "recency_score": 0.20,
    "completeness_score": 0.10,
}


class KnownAnswerMetricTests(unittest.TestCase):
    """Precision@K 与 NDCG@K 的手算已知答案。"""

    @classmethod
    def setUpClass(cls) -> None:
        with (FIXTURE_DIR / "ranking_known_answer.json").open(
            encoding="utf-8"
        ) as file:
            cls.fixture = json.load(file)
        cls.ranked_ids = cls.fixture["ranked_ids"]
        cls.labels = cls.fixture["labels"]
        cls.expected = cls.fixture["expected"]
        cls.tolerance = cls.fixture["tolerance"]

    def test_precision_at_k_matches_hand_computed_values(self) -> None:
        grade_map = build_grade_map(self.labels)
        self.assertAlmostEqual(
            precision_at_k(self.ranked_ids, grade_map, 3),
            self.expected["precision_at_3"],
            delta=self.tolerance,
        )
        self.assertAlmostEqual(
            precision_at_k(self.ranked_ids, grade_map, 5),
            self.expected["precision_at_5"],
            delta=self.tolerance,
        )

    def test_ndcg_at_k_matches_hand_computed_values(self) -> None:
        grade_map = build_grade_map(self.labels)
        self.assertAlmostEqual(
            ndcg_at_k(self.ranked_ids, grade_map, 3),
            self.expected["ndcg_at_3"],
            delta=self.tolerance,
        )
        self.assertAlmostEqual(
            ndcg_at_k(self.ranked_ids, grade_map, 5),
            self.expected["ndcg_at_5"],
            delta=self.tolerance,
        )

    def test_irrelevant_count_and_average_rank_match(self) -> None:
        grade_map = build_grade_map(self.labels)
        self.assertEqual(
            count_irrelevant_in_top_k(self.ranked_ids, grade_map, 3),
            self.expected["irrelevant_in_top_3"],
        )
        self.assertEqual(
            count_irrelevant_in_top_k(self.ranked_ids, grade_map, 5),
            self.expected["irrelevant_in_top_5"],
        )
        self.assertAlmostEqual(
            average_rank_of_highly_relevant(self.ranked_ids, grade_map),
            self.expected["average_rank_of_highly_relevant"],
            delta=self.tolerance,
        )


class LabelParsingTests(unittest.TestCase):
    """标签解析：合法取值、未标注、待讨论和非法标签。"""

    def test_allowed_labels_map_to_grades(self) -> None:
        self.assertEqual(parse_relevance_label("高度相关"), 2)
        self.assertEqual(parse_relevance_label("部分相关"), 1)
        self.assertEqual(parse_relevance_label("不相关"), 0)

    def test_unlabeled_and_pending_discussion_have_no_grade(self) -> None:
        self.assertIsNone(parse_relevance_label(None))
        self.assertIsNone(parse_relevance_label(""))
        self.assertIsNone(parse_relevance_label("   "))
        self.assertIsNone(parse_relevance_label("待讨论"))

    def test_illegal_label_raises_value_error(self) -> None:
        for illegal in ("非常相关", "2", "high", "相关"):
            with self.subTest(label=illegal):
                with self.assertRaises(ValueError):
                    parse_relevance_label(illegal)

    def test_illegal_label_csv_raises_via_fixture(self) -> None:
        labels = load_label_csv(FIXTURE_DIR / "labels_invalid_deliberate.csv")
        with self.assertRaises(ValueError):
            build_grade_map(labels)

    def test_fixture_labels_csv_loads_expected_rows(self) -> None:
        labels = load_label_csv(FIXTURE_DIR / "labels.csv")
        self.assertEqual(len(labels), 11)
        self.assertNotIn("https://openalex.org/W9000000012", labels)

    def test_missing_label_file_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            load_label_csv(FIXTURE_DIR / "not_exist.csv")


class UnlabeledPaperTests(unittest.TestCase):
    """未标注论文不能自动算作不相关。"""

    def test_unlabeled_paper_is_not_counted_as_irrelevant(self) -> None:
        ranked_ids = ["X", "Y"]
        grade_map = build_grade_map({"X": "不相关"})
        self.assertEqual(count_irrelevant_in_top_k(ranked_ids, grade_map, 2), 1)

    def test_unlabeled_paper_contributes_zero_gain_but_keeps_position(self) -> None:
        grade_map = build_grade_map({"A": "高度相关"})
        ndcg_with_gap = ndcg_at_k(["U", "A"], grade_map, 2)
        self.assertIsNotNone(ndcg_with_gap)
        self.assertLess(ndcg_with_gap, 1.0)

    def test_ndcg_is_none_without_any_graded_label(self) -> None:
        self.assertIsNone(ndcg_at_k(["A"], {}, 10))
        self.assertIsNone(ndcg_at_k(["A"], build_grade_map({"A": "待讨论"}), 10))

    def test_average_rank_is_none_without_highly_relevant(self) -> None:
        grade_map = build_grade_map({"A": "部分相关", "B": "不相关"})
        self.assertIsNone(average_rank_of_highly_relevant(["A", "B"], grade_map))

    def test_invalid_k_is_rejected(self) -> None:
        for invalid_k in (0, -1, 1.5, "3", True):
            with self.subTest(k=invalid_k):
                with self.assertRaises(ValueError):
                    validate_k(invalid_k)


class TwoStageRankingTests(unittest.TestCase):
    """两阶段排序：第一阶段分层、第二阶段稳定性和 baseline 保留。"""

    @classmethod
    def setUpClass(cls) -> None:
        raw_papers = load_papers_csv(FIXTURE_DIR / "papers.csv")
        cls.baseline_papers = prepare_baseline_papers(raw_papers, FIXTURE_KEYWORD)
        cls.ranked_papers = apply_two_stage_ranking(
            cls.baseline_papers, FIXTURE_KEYWORD
        )
        cls.labels = load_label_csv(FIXTURE_DIR / "labels.csv")
        cls.grade_map = build_grade_map(cls.labels)

    def test_stage1_level_thresholds(self) -> None:
        self.assertEqual(assign_stage1_level(0.20), "high")
        self.assertEqual(assign_stage1_level(0.05), "medium")
        self.assertEqual(assign_stage1_level(0.0499), "low")
        self.assertEqual(assign_stage1_level(None), "low")
        self.assertEqual(set(STAGE1_LEVEL_GATE), {"high", "medium", "low"})

    def test_stage1_assigns_levels_to_every_paper(self) -> None:
        for paper in self.ranked_papers:
            self.assertIn(paper["stage1_relevance_level"], STAGE1_LEVEL_GATE)
            self.assertEqual(
                paper["stage1_relevance_score"],
                paper["combined_relevance_score"],
            )

    def test_stage2_order_is_stable_and_sorted(self) -> None:
        rerun = apply_two_stage_ranking(self.baseline_papers, FIXTURE_KEYWORD)
        self.assertEqual(
            [paper["openalex_id"] for paper in self.ranked_papers],
            [paper["openalex_id"] for paper in rerun],
        )
        scores = [paper["stage2_ranking_score"] for paper in self.ranked_papers]
        self.assertEqual(scores, sorted(scores, reverse=True))
        new_ranks = [paper["new_rank"] for paper in self.ranked_papers]
        self.assertEqual(new_ranks, list(range(1, len(new_ranks) + 1)))

    def test_stage2_weights_are_fixed_and_documented(self) -> None:
        self.assertAlmostEqual(sum(STAGE2_SCORE_WEIGHTS.values()), 1.0, places=6)
        self.assertGreater(
            STAGE2_SCORE_WEIGHTS["relevance_score"],
            STAGE2_SCORE_WEIGHTS["impact_score"],
        )

    def test_baseline_ranking_is_fully_preserved(self) -> None:
        self.assertEqual(processor.PRELIMINARY_SCORE_WEIGHTS, BASELINE_WEIGHTS_SNAPSHOT)
        for paper in self.ranked_papers:
            self.assertEqual(
                paper["baseline_preliminary_score"], paper["preliminary_score"]
            )
        baseline_ids = [paper["openalex_id"] for paper in self.baseline_papers]
        old_order_ids = [
            paper["openalex_id"]
            for paper in sorted(self.ranked_papers, key=lambda item: item["old_rank"])
        ]
        self.assertEqual(old_order_ids, baseline_ids)

    def test_two_stage_requires_preliminary_score(self) -> None:
        with self.assertRaises(ValueError):
            apply_two_stage_ranking([{"title": "no score"}], FIXTURE_KEYWORD)

    def test_highly_relevant_rank_before_irrelevant(self) -> None:
        highly_relevant_ranks = [
            paper["new_rank"]
            for paper in self.ranked_papers
            if self.grade_map.get(paper["openalex_id"]) == 2
        ]
        irrelevant_ranks = [
            paper["new_rank"]
            for paper in self.ranked_papers
            if self.grade_map.get(paper["openalex_id"]) == 0
        ]
        self.assertEqual(len(highly_relevant_ranks), 4)
        self.assertEqual(len(irrelevant_ranks), 3)
        self.assertLess(max(highly_relevant_ranks), min(irrelevant_ranks))

    def test_missing_abstract_paper_is_still_ranked(self) -> None:
        paper = next(
            item
            for item in self.ranked_papers
            if item["openalex_id"] == "https://openalex.org/W9000000008"
        )
        self.assertEqual(paper["abstract_relevance_score"], 0.0)
        self.assertGreater(paper["combined_relevance_score"], 0.0)
        self.assertGreaterEqual(paper["new_rank"], 1)

    def test_unlabeled_fixture_paper_is_not_treated_as_irrelevant(self) -> None:
        new_ids = [paper["openalex_id"] for paper in self.ranked_papers]
        metrics = evaluate_ranking(new_ids, self.labels, 12)
        unlabeled_rank = new_ids.index("https://openalex.org/W9000000012") + 1
        self.assertLessEqual(unlabeled_rank, 12)
        self.assertEqual(metrics["irrelevant_in_top_k"], 3)
        self.assertEqual(metrics["labeled_count"], 11)

    def test_error_cases_have_minimum_count_and_explanations(self) -> None:
        cases = select_ranking_error_cases(self.ranked_papers, min_cases=5)
        self.assertGreaterEqual(len(cases), 5)
        for case in cases:
            self.assertTrue(case["explanation"])
            self.assertIn("openalex_id", case)


if __name__ == "__main__":
    unittest.main()
