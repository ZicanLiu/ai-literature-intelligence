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
    filter_grades_to_ranked,
    judged_count_at_k,
    judged_ndcg_at_k,
    judged_precision_at_k,
    load_label_csv,
    parse_relevance_label,
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
    """judged Precision@K 与 judged NDCG@K 的手算已知答案。"""

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

    def test_judged_precision_at_k_matches_hand_computed_values(self) -> None:
        grade_map = build_grade_map(self.labels)
        self.assertAlmostEqual(
            judged_precision_at_k(self.ranked_ids, grade_map, 3),
            self.expected["judged_precision_at_3"],
            delta=self.tolerance,
        )
        self.assertAlmostEqual(
            judged_precision_at_k(self.ranked_ids, grade_map, 5),
            self.expected["judged_precision_at_5"],
            delta=self.tolerance,
        )

    def test_judged_ndcg_at_k_matches_hand_computed_values(self) -> None:
        grade_map = build_grade_map(self.labels)
        self.assertAlmostEqual(
            judged_ndcg_at_k(self.ranked_ids, grade_map, 3),
            self.expected["judged_ndcg_at_3"],
            delta=self.tolerance,
        )
        self.assertAlmostEqual(
            judged_ndcg_at_k(self.ranked_ids, grade_map, 5),
            self.expected["judged_ndcg_at_5"],
            delta=self.tolerance,
        )

    def test_judged_count_and_coverage_match(self) -> None:
        grade_map = build_grade_map(self.labels)
        self.assertEqual(
            judged_count_at_k(self.ranked_ids, grade_map, 3),
            self.expected["judged_count_at_3"],
        )
        self.assertEqual(
            judged_count_at_k(self.ranked_ids, grade_map, 5),
            self.expected["judged_count_at_5"],
        )
        metrics = evaluate_ranking(self.ranked_ids, self.labels, 5)
        self.assertAlmostEqual(
            metrics["coverage_at_k"], self.expected["coverage_at_5"], delta=self.tolerance
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
    """未标注论文不能自动算作不相关，也不能压低 judged 指标。"""

    def test_unlabeled_paper_is_not_counted_as_irrelevant(self) -> None:
        ranked_ids = ["X", "Y"]
        grade_map = build_grade_map({"X": "不相关"})
        self.assertEqual(count_irrelevant_in_top_k(ranked_ids, grade_map, 2), 1)

    def test_unlabeled_paper_does_not_penalize_judged_ndcg(self) -> None:
        grade_map = build_grade_map({"A": "高度相关"})
        self.assertEqual(judged_ndcg_at_k(["U", "A"], grade_map, 2), 1.0)

    def test_unlabeled_paper_does_not_dilute_judged_precision(self) -> None:
        grade_map = build_grade_map({"A": "高度相关"})
        self.assertEqual(judged_precision_at_k(["U", "A"], grade_map, 2), 1.0)
        self.assertEqual(judged_count_at_k(["U", "A"], grade_map, 2), 1)

    def test_condensed_precision_takes_top_k_after_removing_unlabeled(self) -> None:
        # 完整 condensed 口径：先删除未标注的 U，再从压缩排名取前 1 篇。
        grade_map = build_grade_map({"A": "高度相关"})
        self.assertEqual(judged_precision_at_k(["U", "A"], grade_map, 1), 1.0)

    def test_condensed_ndcg_takes_top_k_after_removing_unlabeled(self) -> None:
        # 同上：A 在压缩后排第 1，DCG@1 = IDCG@1，NDCG@1 = 1.0。
        grade_map = build_grade_map({"A": "高度相关"})
        self.assertEqual(judged_ndcg_at_k(["U", "A"], grade_map, 1), 1.0)

    def test_judged_metrics_are_none_without_any_judged_paper_in_top_k(self) -> None:
        grade_map = build_grade_map({"A": "高度相关"})
        self.assertIsNone(judged_precision_at_k(["U", "V"], grade_map, 2))
        # 排名列表中没有任何已标注论文时，过滤后等级表为空，NDCG 无定义。
        self.assertIsNone(
            judged_ndcg_at_k(
                ["U", "V"], filter_grades_to_ranked(["U", "V"], grade_map), 2
            )
        )

    def test_ndcg_is_none_without_any_graded_label(self) -> None:
        self.assertIsNone(judged_ndcg_at_k(["A"], {}, 10))
        self.assertIsNone(judged_ndcg_at_k(["A"], build_grade_map({"A": "待讨论"}), 10))

    def test_average_rank_is_none_without_highly_relevant(self) -> None:
        grade_map = build_grade_map({"A": "部分相关", "B": "不相关"})
        self.assertIsNone(average_rank_of_highly_relevant(["A", "B"], grade_map))

    def test_invalid_k_is_rejected(self) -> None:
        for invalid_k in (0, -1, 1.5, "3", True):
            with self.subTest(k=invalid_k):
                with self.assertRaises(ValueError):
                    validate_k(invalid_k)


class LabelsOutsideRankingTests(unittest.TestCase):
    """标签文件中不在本次排名列表内的论文不参与 IDCG 和 labeled_count。"""

    def test_filter_grades_to_ranked_drops_outside_labels(self) -> None:
        grade_map = build_grade_map({"A": "高度相关", "Z": "高度相关"})
        self.assertEqual(filter_grades_to_ranked(["A", "B"], grade_map), {"A": 2})

    def test_outside_labels_do_not_change_ndcg_or_labeled_count(self) -> None:
        labels_inside = {"A": "高度相关", "B": "不相关"}
        labels_with_outside = dict(labels_inside, Z="高度相关", Y="高度相关")
        ranked_ids = ["A", "B"]
        inside = evaluate_ranking(ranked_ids, labels_inside, 2)
        with_outside = evaluate_ranking(ranked_ids, labels_with_outside, 2)
        self.assertEqual(with_outside["labeled_count"], 2)
        self.assertEqual(with_outside["judged_ndcg_at_k"], inside["judged_ndcg_at_k"])
        self.assertEqual(
            with_outside["judged_precision_at_k"], inside["judged_precision_at_k"]
        )


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


LIVE_SAMPLE_CSV = (
    PROJECT_ROOT / "data" / "samples" / "w2" / "ranking" / "live_ranking_sample.csv"
)
LIVE_SAMPLE_KEYWORD = "machine learning stellar parameter estimation spectra"

# 离线重算必须与样本一致的分数字段与名次字段。
LIVE_REPRODUCIBLE_SCORE_FIELDS = [
    "baseline_preliminary_score",
    "title_relevance_score",
    "abstract_relevance_score",
    "combined_relevance_score",
    "stage2_ranking_score",
]
LIVE_REPRODUCIBLE_RANK_FIELDS = ["old_rank", "new_rank"]

# 样本必须包含的来源追踪字段。
LIVE_PROVENANCE_FIELDS = ["keyword", "retrieved_at", "run_id"]

# 样本必须包含的 baseline 完整度计算字段。
LIVE_BASELINE_INPUT_FIELDS = [
    "title",
    "authors",
    "publication_year",
    "doi",
    "abstract",
    "cited_by_count",
    "source_name",
    "landing_page_url",
]


class LiveSampleFieldTests(unittest.TestCase):
    """live 样本字段完整性：足以重算 baseline，且带来源追踪。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = load_papers_csv(LIVE_SAMPLE_CSV)

    def test_sample_contains_baseline_input_and_provenance_fields(self) -> None:
        required = set(LIVE_BASELINE_INPUT_FIELDS) | set(LIVE_PROVENANCE_FIELDS)
        for field in required:
            with self.subTest(field=field):
                self.assertIn(field, self.rows[0])
        # 缺失值必须保存为空（读入后为 None），不允许出现字符串 "nan"：
        # 它会被 completeness 误判为字段存在，且不同 pandas 版本处理不一致。
        for row in self.rows:
            for value in row.values():
                self.assertNotEqual(str(value).strip().lower(), "nan")

    def test_provenance_fields_are_non_empty(self) -> None:
        for row in self.rows:
            for field in LIVE_PROVENANCE_FIELDS:
                with self.subTest(field=field, openalex_id=row["openalex_id"]):
                    self.assertTrue(str(row.get(field) or "").strip())
            self.assertEqual(row["keyword"], LIVE_SAMPLE_KEYWORD)


class LiveSampleReproductionTests(unittest.TestCase):
    """从 live 样本 CSV 离线重算，结果必须与样本保存的分数和名次一致。

    注意：recency_score 依赖运行时年份，样本在与 retrieved_at 不同的年份
    重算时需要按样本 README 的流程重新生成，届时本测试也应随新样本一起更新。
    """

    @classmethod
    def setUpClass(cls) -> None:
        raw_papers = load_papers_csv(LIVE_SAMPLE_CSV)
        baseline_papers = prepare_baseline_papers(raw_papers, LIVE_SAMPLE_KEYWORD)
        cls.ranked_papers = apply_two_stage_ranking(
            baseline_papers, LIVE_SAMPLE_KEYWORD
        )
        cls.stored_by_id = {paper["openalex_id"]: paper for paper in raw_papers}

    def test_every_stored_paper_is_reproduced(self) -> None:
        self.assertEqual(len(self.ranked_papers), len(self.stored_by_id))
        for paper in self.ranked_papers:
            self.assertIn(paper["openalex_id"], self.stored_by_id)

    def test_scores_match_stored_values(self) -> None:
        for paper in self.ranked_papers:
            stored = self.stored_by_id[paper["openalex_id"]]
            for field in LIVE_REPRODUCIBLE_SCORE_FIELDS:
                with self.subTest(field=field, openalex_id=paper["openalex_id"]):
                    self.assertAlmostEqual(
                        paper[field],
                        float(stored[field]),
                        places=4,
                    )

    def test_ranks_and_levels_match_stored_values(self) -> None:
        for paper in self.ranked_papers:
            stored = self.stored_by_id[paper["openalex_id"]]
            for field in LIVE_REPRODUCIBLE_RANK_FIELDS:
                with self.subTest(field=field, openalex_id=paper["openalex_id"]):
                    self.assertEqual(paper[field], int(stored[field]))
            self.assertEqual(
                paper["stage1_relevance_level"], stored["stage1_relevance_level"]
            )


if __name__ == "__main__":
    unittest.main()
