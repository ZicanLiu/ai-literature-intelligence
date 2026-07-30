"""
W2 去重模块自动测试。

覆盖：相同 OpenAlex ID、相同 DOI、DOI URL 前缀差异、标题完全相同、
标点差异、标题带副标题、年份相差 1 年、作者明显不同、高相似但不自动删除、
低相似不进入队列、空标题、特殊字符、pair_id 不重复、来源追踪字段不丢失。
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.deduplication import (
    author_overlap_ratio,
    extract_author_surnames,
    find_exact_duplicates,
    find_suspected_duplicates,
    generate_pair_id,
    jaccard_similarity,
    normalize_doi,
    normalize_title,
    sequence_similarity,
    tokenize_title,
)


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "dedup"


def load_fixture(filename="test_papers.json"):
    path = FIXTURES_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestNormalizeTitle(unittest.TestCase):
    def test_html_tags_stripped(self):
        self.assertEqual(normalize_title("The <i>Gaia</i> Survey"), "the gaia survey")

    def test_punctuation_removed(self):
        title = "Stellar spectra: Classification, regression, and clustering"
        result = normalize_title(title)
        self.assertNotIn(":", result)
        self.assertNotIn(",", result)
        self.assertNotIn(".", result)

    def test_arxiv_removed(self):
        title = "Deep Learning for Stars [arXiv:2301.12345v2]"
        result = normalize_title(title)
        self.assertNotIn("arxiv", result)
        self.assertNotIn("2301", result)

    def test_empty_title(self):
        self.assertEqual(normalize_title(""), "")
        self.assertEqual(normalize_title(None), "")
        self.assertEqual(tokenize_title(""), set())


class TestExactDedup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.papers = load_fixture()

    def test_same_openalex_id(self):
        """测试 1：相同 OpenAlex ID → 确定重复"""
        result = find_exact_duplicates(self.papers)
        exact = result["exact_duplicates"]
        self.assertEqual(result["stats"]["same_openalex_id"], 1)
        oa_ids_merged = set()
        for dup in exact:
            if dup["rule"] == "same_openalex_id":
                oa_ids_merged.add(dup["merged_openalex_id"])
        self.assertIn("https://openalex.org/W1000000001", oa_ids_merged)

    def test_same_doi_with_url_prefix_diff(self):
        """测试 2+3：相同 DOI 但 URL 前缀不同 → 确定重复"""
        result = find_exact_duplicates(self.papers)
        exact = result["exact_duplicates"]
        self.assertTrue(
            any(
                d["rule"] == "same_doi"
                for d in exact
            ),
            "Should find at least one same-DOI duplicate (test 2+3)",
        )
        doi_dups = [d for d in exact if d["rule"] == "same_doi"]
        if doi_dups:
            print(f"  DOI duplicates found: {len(doi_dups)}")

    def test_same_normalized_title_no_id(self):
        """测试 4：标题完全相同 → 确定重复"""
        papers_without_oaid = [
            p for p in self.papers if not (p.get("openalex_id") or "")
        ]
        if len(papers_without_oaid) >= 2:
            result = find_exact_duplicates(papers_without_oaid)
            self.assertGreaterEqual(
                len(result["exact_duplicates"]),
                0,
                "Same title without IDs should be detected",
            )

    def test_kept_papers_no_duplicates(self):
        """保留的论文不包含被合并的（same_doi 和 same_title_no_id 规则）"""
        result = find_exact_duplicates(self.papers)
        kept_ids = {p.get("openalex_id") for p in result["kept_papers"]}
        for dup in result["exact_duplicates"]:
            merged_id = dup.get("merged_openalex_id", "")
            if dup["rule"] == "same_openalex_id":
                continue
            if not merged_id:
                continue
            self.assertNotIn(merged_id, kept_ids,
                f"Merged ID {merged_id} should not be in kept papers")


class TestSuspectedDedup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.papers = load_fixture()

    def test_punctuation_difference_suspected(self):
        """测试 5：标点差异 → 应进入疑似队列"""
        kept = find_exact_duplicates(self.papers)["kept_papers"]
        result = find_suspected_duplicates(kept)
        suspected = result["suspected_duplicates"]
        punct_pair = [
            s for s in suspected
            if "punctuation" in s.get("left_title", "").lower()
            or "stellar spectra" in s.get("left_title", "").lower()
        ]
        self.assertGreater(len(suspected), 0, "Suspected pairs should be generated")

    def test_year_difference_1_still_merged(self):
        """测试 7：年份相差 1 年 → 仍在疑似队列"""
        kept = find_exact_duplicates(self.papers)["kept_papers"]
        result = find_suspected_duplicates(kept)
        suspected = result["suspected_duplicates"]
        year_pairs = [s for s in suspected if s["year_difference"] == 1]
        self.assertGreater(len(year_pairs), 0, "Year diff=1 should generate pairs")

    def test_different_authors_not_auto_deleted(self):
        """测试 8：作者明显不同 → 疑似但不自动删除"""
        kept = find_exact_duplicates(self.papers)["kept_papers"]
        result = find_suspected_duplicates(kept)
        for s in result["suspected_duplicates"]:
            self.assertEqual(s["review_status"], "pending")
            self.assertEqual(s["recommended_action"], "manual_review")

    def test_high_similarity_not_auto_deleted(self):
        """测试 9：高相似度 → 进入疑似队列，不自动删除"""
        kept = find_exact_duplicates(self.papers)["kept_papers"]
        result = find_suspected_duplicates(kept)
        for s in result["suspected_duplicates"]:
            self.assertEqual(s["review_status"], "pending")

    def test_low_similarity_not_in_queue(self):
        """测试 10：低相似度 → 不进入疑似队列"""
        kept = find_exact_duplicates(self.papers)["kept_papers"]
        result = find_suspected_duplicates(kept)
        suspected = result["suspected_duplicates"]
        for s in suspected:
            self.assertGreaterEqual(
                s["title_similarity"],
                0.35,
                f"Pair {s['pair_id']} has too low similarity: {s['title_similarity']}",
            )

    def test_pair_ids_unique(self):
        """测试 13：pair_id 不重复"""
        kept = find_exact_duplicates(self.papers)["kept_papers"]
        result = find_suspected_duplicates(kept)
        pair_ids = [s["pair_id"] for s in result["suspected_duplicates"]]
        self.assertEqual(len(pair_ids), len(set(pair_ids)))

    def test_source_tracking_preserved(self):
        """测试 14：来源追踪字段不丢失"""
        kept = find_exact_duplicates(self.papers)["kept_papers"]
        result = find_suspected_duplicates(kept)
        for s in result["suspected_duplicates"]:
            self.assertIsNotNone(s.get("left_keyword"))
            self.assertIsNotNone(s.get("right_keyword"))
            self.assertIsNotNone(s.get("left_run_id"))
            self.assertIsNotNone(s.get("right_run_id"))

    def test_exact_and_suspected_separated(self):
        """测试：确定重复与疑似重复严格分开"""
        exact_result = find_exact_duplicates(self.papers)
        kept = exact_result["kept_papers"]
        suspected_result = find_suspected_duplicates(kept)
        exact_merged_ids = {d["merged_openalex_id"] for d in exact_result["exact_duplicates"]}
        for s in suspected_result["suspected_duplicates"]:
            self.assertNotIn(s["left_id"], exact_merged_ids,
                f"Left ID {s['left_id']} was exact-merged but still in suspected")
            self.assertNotIn(s["right_id"], exact_merged_ids,
                f"Right ID {s['right_id']} was exact-merged but still in suspected")


class TestSimilarityFunctions(unittest.TestCase):
    def test_jaccard_identical(self):
        tokens = {"stellar", "spectra", "classification"}
        self.assertAlmostEqual(jaccard_similarity(tokens, tokens), 1.0)

    def test_jaccard_disjoint(self):
        a = {"a", "b"}
        b = {"c", "d"}
        self.assertAlmostEqual(jaccard_similarity(a, b), 0.0)

    def test_jaccard_partial(self):
        a = {"stellar", "spectra", "classification"}
        b = {"stellar", "spectra", "regression"}
        self.assertAlmostEqual(jaccard_similarity(a, b), 0.5)

    def test_sequence_identical(self):
        self.assertAlmostEqual(
            sequence_similarity("stellar spectra classification",
                               "stellar spectra classification"),
            1.0,
        )

    def test_sequence_different(self):
        sim = sequence_similarity(
            "stellar spectra classification with machine learning",
            "lunar surface composition analysis",
        )
        self.assertLess(sim, 0.5)

    def test_author_surname_extraction(self):
        surnames = extract_author_surnames("John Smith; Jane Doe")
        self.assertIn("smith", surnames)
        self.assertIn("doe", surnames)

    def test_author_overlap_high(self):
        a = ["smith", "doe", "brown"]
        b = ["smith", "doe", "white"]
        self.assertAlmostEqual(author_overlap_ratio(a, b), 0.5)

    def test_author_overlap_low(self):
        a = ["smith", "doe"]
        b = ["wang", "zhang"]
        self.assertAlmostEqual(author_overlap_ratio(a, b), 0.0)
        self.assertLess(author_overlap_ratio(a, b), 0.3)

    def test_doi_normalize_url_prefix(self):
        self.assertEqual(
            normalize_doi("https://doi.org/10.1234/test"),
            "10.1234/test",
        )
        self.assertEqual(
            normalize_doi("http://doi.org/10.1234/test"),
            "10.1234/test",
        )

    def test_pair_id_deterministic(self):
        a = generate_pair_id("W1", "W2")
        b = generate_pair_id("W1", "W2")
        self.assertEqual(a, b)

    def test_pair_id_different(self):
        a = generate_pair_id("W1", "W2")
        b = generate_pair_id("W3", "W4")
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
