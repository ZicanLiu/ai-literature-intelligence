"""基于 src.processor 真实 API 的清洗、去重和评分回归测试。"""

from __future__ import annotations

import math
import unittest
from datetime import datetime

from src.processor import (
    OUTPUT_FIELDS,
    add_preliminary_scores,
    calculate_impact_score,
    calculate_recency_score,
    clean_int,
    clean_papers,
    clean_single_paper,
    count_missing_fields,
    normalize_doi,
    remove_duplicates,
)


class ProcessorRegressionTests(unittest.TestCase):
    def test_empty_paper_list(self) -> None:
        self.assertEqual(clean_papers([], "machine learning"), [])
        self.assertEqual(remove_duplicates([]), ([], []))
        self.assertEqual(add_preliminary_scores([], "machine learning"), [])

    def test_empty_title_is_preserved_as_empty_string(self) -> None:
        paper = clean_single_paper({"title": None}, "keyword")
        self.assertEqual(paper["title"], "")

    def test_missing_doi_is_preserved_as_empty_string(self) -> None:
        paper = clean_single_paper({"title": "Paper"}, "keyword")
        self.assertEqual(paper["doi"], "")

    def test_doi_normalization_removes_known_prefixes_and_case(self) -> None:
        cases = {
            "https://doi.org/10.1000/ABC": "10.1000/abc",
            "HTTP://DOI.ORG/10.1000/ABC": "10.1000/abc",
            "doi.org/10.1000/ABC": "10.1000/abc",
            "DOI:10.1000/ABC": "10.1000/abc",
            " 10.1000/ABC ": "10.1000/abc",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_doi(raw), expected)

    def test_same_doi_is_a_strict_duplicate(self) -> None:
        papers = [
            {"title": "Original", "doi": "10.1000/same", "openalex_id": "W1"},
            {"title": "Different title", "doi": "10.1000/same", "openalex_id": "W2"},
        ]
        unique, duplicates = remove_duplicates(papers)
        self.assertEqual(len(unique), 1)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["duplicate_reason"], "DOI 重复")

    def test_title_substring_is_not_a_duplicate(self) -> None:
        papers = [
            {"title": "Machine Learning for Stellar Spectra", "doi": ""},
            {"title": "Machine Learning for Stellar Spectra Extended Survey", "doi": ""},
        ]
        unique, duplicates = remove_duplicates(papers)
        self.assertEqual(len(unique), 2)
        self.assertEqual(duplicates, [])

    def test_title_case_and_spacing_difference_is_duplicate_without_doi(self) -> None:
        papers = [
            {"title": "Machine Learning for Astronomy", "doi": ""},
            {"title": " machine   learning FOR astronomy ", "doi": ""},
        ]
        unique, duplicates = remove_duplicates(papers)
        self.assertEqual(len(unique), 1)
        self.assertEqual(len(duplicates), 1)
        self.assertIn("标准化标题完全相同", duplicates[0]["duplicate_reason"])

    def test_same_title_with_different_dois_is_not_removed(self) -> None:
        papers = [
            {"title": "Shared title", "doi": "10.1000/one"},
            {"title": "Shared title", "doi": "10.1000/two"},
        ]
        unique, duplicates = remove_duplicates(papers)
        self.assertEqual(len(unique), 2)
        self.assertEqual(duplicates, [])

    def test_citation_extremes_stay_in_range(self) -> None:
        max_log = math.log1p(1_000_000)
        self.assertEqual(calculate_impact_score({"cited_by_count": 0}, max_log), 0.0)
        self.assertEqual(calculate_impact_score({"cited_by_count": None}, max_log), 0.0)
        self.assertAlmostEqual(
            calculate_impact_score({"cited_by_count": 1_000_000}, max_log), 1.0
        )

    def test_abnormal_publication_years_are_bounded(self) -> None:
        current_year = datetime.now().year
        self.assertEqual(
            calculate_recency_score({"publication_year": current_year + 10}), 1.0
        )
        self.assertEqual(
            calculate_recency_score({"publication_year": current_year - 20}), 0.0
        )
        self.assertEqual(calculate_recency_score({"publication_year": None}), 0.0)

    def test_missing_field_count_does_not_treat_zero_as_missing(self) -> None:
        paper = {field: "value" for field in OUTPUT_FIELDS}
        paper.update({"doi": "", "abstract": None, "cited_by_count": 0})
        counts = count_missing_fields([paper])
        self.assertEqual(counts["doi"], 1)
        self.assertEqual(counts["abstract"], 1)
        self.assertEqual(counts["cited_by_count"], 0)

    def test_all_scores_are_between_zero_and_one(self) -> None:
        papers = [
            {
                "title": "Machine Learning for Stellar Spectra",
                "authors": "Researcher",
                "publication_year": datetime.now().year,
                "doi": "10.1000/example",
                "abstract": "Machine learning classifies stellar spectra.",
                "cited_by_count": 50,
                "source_name": "Journal",
                "openalex_id": "https://openalex.org/W1000",
                "landing_page_url": "https://example.org/paper",
            }
        ]
        ranked = add_preliminary_scores(papers, "machine learning stellar spectra")
        self.assertEqual(len(ranked), 1)
        for key in (
            "relevance_score",
            "impact_score",
            "recency_score",
            "completeness_score",
            "preliminary_score",
        ):
            self.assertGreaterEqual(ranked[0][key], 0.0)
            self.assertLessEqual(ranked[0][key], 1.0)

    def test_sparse_input_still_has_all_processor_output_fields(self) -> None:
        # processor 不负责写 CSV；这里验证稀疏输入仍生成稳定字段，storage 才负责表头。
        cleaned = clean_papers([{}], "keyword")
        self.assertEqual(len(cleaned), 1)
        self.assertTrue(set(OUTPUT_FIELDS).issubset(cleaned[0]))

    def test_clean_int_rejects_non_numeric_values_without_crashing(self) -> None:
        self.assertIsNone(clean_int("not-a-number"))
        self.assertIsNone(clean_int(float("nan")))
        self.assertEqual(clean_int("42"), 42)


if __name__ == "__main__":
    unittest.main()
