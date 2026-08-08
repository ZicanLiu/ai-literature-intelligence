"""
W2 去重模块自动测试。

覆盖：相同 OpenAlex ID、相同 DOI、DOI URL 前缀差异、标题完全相同、
标点差异、标题带副标题、年份相差 1 年、作者明显不同、高相似但不自动删除、
低相似不进入队列、空标题、特殊字符、pair_id 不重复、来源追踪字段不丢失、
不同 ID 同标题不自动合并、空标题+空作者不进入队列。
"""

import csv
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import review_duplicates
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
SPECIAL_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "dedup"
COMBINED_SAMPLE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "samples"
    / "w2"
    / "dedup"
    / "combined_w2_raw.csv"
)


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

    def test_arxiv_removed(self):
        title = "Deep Learning for Stars [arXiv:2301.12345v2]"
        result = normalize_title(title)
        self.assertNotIn("arxiv", result)
        self.assertNotIn("2301", result)

    def test_empty_title(self):
        self.assertEqual(normalize_title(""), "")
        self.assertEqual(normalize_title(None), "")
        self.assertEqual(tokenize_title(""), set())

    def test_special_characters_handled(self):
        title = "Stellar <scp>ML</scp> &amp; spectra--test"
        result = normalize_title(title)
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)
        self.assertNotIn("&", result)


class TestExactDedup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.papers = load_fixture()

    def test_same_openalex_id(self):
        result = find_exact_duplicates(self.papers)
        exact = result["exact_duplicates"]
        self.assertEqual(result["stats"]["same_openalex_id"], 1)
        oa_ids_merged = {d["merged_openalex_id"] for d in exact if d["rule"] == "same_openalex_id"}
        self.assertIn("https://openalex.org/W1000000001", oa_ids_merged)

    def test_same_doi_with_url_prefix_diff(self):
        result = find_exact_duplicates(self.papers)
        self.assertEqual(result["stats"]["same_doi"], 1)
        doi_dups = [d for d in result["exact_duplicates"] if d["rule"] == "same_doi"]
        self.assertEqual(len(doi_dups), 1)
        self.assertEqual(doi_dups[0]["merged_openalex_id"], "https://openalex.org/W3000000003")

    def test_same_normalized_title_both_no_id_no_doi(self):
        no_id_no_doi = [
            p for p in self.papers
            if not (p.get("openalex_id") or "").strip()
            and not (p.get("doi") or "").strip()
        ]
        result = find_exact_duplicates(no_id_no_doi)
        self.assertEqual(result["stats"]["same_title_no_id"], 1)

    def test_different_ids_same_title_not_auto_merged(self):
        papers = [
            {
                "keyword": "test", "run_id": "r1",
                "openalex_id": "https://openalex.org/WAA", "doi": "",
                "title": "Identical Title Here", "authors": "A B", "publication_year": 2022,
            },
            {
                "keyword": "test", "run_id": "r2",
                "openalex_id": "https://openalex.org/WBB", "doi": "",
                "title": "Identical Title Here", "authors": "A B", "publication_year": 2022,
            },
        ]
        result = find_exact_duplicates(papers)
        self.assertEqual(result["stats"]["same_title_no_id"], 0,
            "Different OpenAlex IDs with same title must NOT be auto-merged")

    def test_kept_papers_no_duplicates(self):
        result = find_exact_duplicates(self.papers)
        kept_ids = {p.get("openalex_id", "") for p in result["kept_papers"]}
        for dup in result["exact_duplicates"]:
            merged_id = dup.get("merged_openalex_id", "")
            if dup["rule"] == "same_openalex_id":
                continue
            if not merged_id:
                continue
            self.assertNotIn(merged_id, kept_ids)


class TestSuspectedDedup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.papers = load_fixture()

    def test_punctuation_difference_is_suspected(self):
        kept = find_exact_duplicates(self.papers)["kept_papers"]
        result = find_suspected_duplicates(kept)
        suspected = result["suspected_duplicates"]
        pair_ids = {s["pair_id"] for s in suspected}
        left_ids = {s["left_id"] for s in suspected}
        right_ids = {s["right_id"] for s in suspected}
        self.assertIn("https://openalex.org/W4000000004", left_ids | right_ids,
            "Punctuation-differing pair should be in suspected queue")
        self.assertIn("https://openalex.org/W5000000005", left_ids | right_ids,
            "Punctuation-differing pair should be in suspected queue")

    def test_year_difference_1_in_suspected_queue(self):
        kept = find_exact_duplicates(self.papers)["kept_papers"]
        result = find_suspected_duplicates(kept)
        suspected = result["suspected_duplicates"]
        left_ids = {s["left_id"] for s in suspected}
        right_ids = {s["right_id"] for s in suspected}
        all_ids = left_ids | right_ids
        self.assertIn("https://openalex.org/W8000000008", all_ids,
            "Year-diff=1 pair (W8000000008) should be in suspected queue")
        self.assertIn("https://openalex.org/W9000000009", all_ids,
            "Year-diff=1 pair (W9000000009) should be in suspected queue")
        year_pairs = [s for s in suspected if s["year_difference"] == 1]
        self.assertGreater(len(year_pairs), 0)

    def test_all_suspected_are_pending(self):
        kept = find_exact_duplicates(self.papers)["kept_papers"]
        result = find_suspected_duplicates(kept)
        for s in result["suspected_duplicates"]:
            self.assertEqual(s["review_status"], "pending")
            self.assertEqual(s["recommended_action"], "manual_review")

    def test_low_similarity_not_in_queue(self):
        kept = find_exact_duplicates(self.papers)["kept_papers"]
        result = find_suspected_duplicates(kept)
        suspected = result["suspected_duplicates"]
        all_ids = set()
        for s in suspected:
            all_ids.add(s["left_id"])
            all_ids.add(s["right_id"])
        self.assertNotIn("https://openalex.org/W1600000016", all_ids,
            "Low-similarity paper W1600000016 should not be in suspected queue")
        self.assertNotIn("https://openalex.org/W1700000017", all_ids,
            "Low-similarity paper W1700000017 should not be in suspected queue")

    def test_pair_ids_unique(self):
        kept = find_exact_duplicates(self.papers)["kept_papers"]
        result = find_suspected_duplicates(kept)
        pair_ids = [s["pair_id"] for s in result["suspected_duplicates"]]
        self.assertEqual(len(pair_ids), len(set(pair_ids)))

    def test_source_tracking_preserved_with_specific_values(self):
        kept = find_exact_duplicates(self.papers)["kept_papers"]
        result = find_suspected_duplicates(kept)
        run_ids_seen = set()
        for s in result["suspected_duplicates"]:
            self.assertTrue(s.get("left_keyword"), "left_keyword should not be empty")
            self.assertTrue(s.get("right_keyword"), "right_keyword should not be empty")
            self.assertTrue(s.get("left_run_id"), "left_run_id should not be empty")
            self.assertTrue(s.get("right_run_id"), "right_run_id should not be empty")
            run_ids_seen.add(s["left_run_id"])
            run_ids_seen.add(s["right_run_id"])
        self.assertIn("test-run-007", run_ids_seen)
        self.assertIn("test-run-008", run_ids_seen)

    def test_exact_and_suspected_separated(self):
        exact_result = find_exact_duplicates(self.papers)
        kept = exact_result["kept_papers"]
        suspected_result = find_suspected_duplicates(kept)
        exact_merged_ids = {d["merged_openalex_id"] for d in exact_result["exact_duplicates"]}
        exact_kept_ids = {d["kept_openalex_id"] for d in exact_result["exact_duplicates"]}
        all_exact_ids = exact_merged_ids | exact_kept_ids
        for s in suspected_result["suspected_duplicates"]:
            if s["left_id"] in all_exact_ids and s["right_id"] in all_exact_ids:
                continue
            self.assertNotIn(s["left_id"], exact_merged_ids,
                f"Left ID {s['left_id']} was exact-merged but still in suspected")
            self.assertNotIn(s["right_id"], exact_merged_ids,
                f"Right ID {s['right_id']} was exact-merged but still in suspected")

    def test_empty_title_empty_authors_not_in_suspected_queue(self):
        papers = [
            {
                "keyword": "test", "run_id": "r1",
                "openalex_id": "https://openalex.org/W_EMPTY_1", "doi": "",
                "title": "", "authors": "", "publication_year": 2020,
            },
            {
                "keyword": "test", "run_id": "r2",
                "openalex_id": "https://openalex.org/W_EMPTY_2", "doi": "",
                "title": "", "authors": "", "publication_year": 2020,
            },
        ]
        exact = find_exact_duplicates(papers)
        kept = exact["kept_papers"]
        result = find_suspected_duplicates(kept)
        self.assertEqual(len(result["suspected_duplicates"]), 0,
            "Empty title + empty authors must NOT enter suspected queue")

    def test_different_ids_same_title_only_in_suspected_not_exact(self):
        papers = [
            {
                "keyword": "test", "run_id": "r1",
                "openalex_id": "https://openalex.org/W_DIFF_1", "doi": "",
                "title": "Same Title Different ID", "authors": "Author One; Author Two",
                "publication_year": 2021,
            },
            {
                "keyword": "test", "run_id": "r2",
                "openalex_id": "https://openalex.org/W_DIFF_2", "doi": "",
                "title": "Same Title Different ID", "authors": "Author One; Author Two",
                "publication_year": 2021,
            },
        ]
        exact = find_exact_duplicates(papers)
        self.assertEqual(exact["stats"]["same_openalex_id"], 0)
        self.assertEqual(exact["stats"]["same_title_no_id"], 0,
            "Different IDs with same title must NOT be auto-merged as exact")
        kept = exact["kept_papers"]
        result = find_suspected_duplicates(kept)
        self.assertGreaterEqual(len(result["suspected_duplicates"]), 1,
            "Different IDs with same title should enter suspected queue")


class TestSimilarityFunctions(unittest.TestCase):
    def test_jaccard_identical(self):
        tokens = {"stellar", "spectra", "classification"}
        self.assertAlmostEqual(jaccard_similarity(tokens, tokens), 1.0)

    def test_jaccard_disjoint(self):
        self.assertAlmostEqual(jaccard_similarity({"a", "b"}, {"c", "d"}), 0.0)

    def test_jaccard_partial(self):
        a = {"stellar", "spectra", "classification"}
        b = {"stellar", "spectra", "regression"}
        self.assertAlmostEqual(jaccard_similarity(a, b), 0.5)

    def test_jaccard_both_empty(self):
        self.assertAlmostEqual(jaccard_similarity(set(), set()), 0.0)

    def test_sequence_identical(self):
        self.assertAlmostEqual(
            sequence_similarity("stellar spectra classification",
                               "stellar spectra classification"), 1.0)

    def test_sequence_different(self):
        sim = sequence_similarity(
            "stellar spectra classification with machine learning",
            "lunar surface composition analysis")
        self.assertLess(sim, 0.5)

    def test_sequence_one_empty(self):
        self.assertAlmostEqual(sequence_similarity("stellar spectra", ""), 0.0)

    def test_sequence_both_empty(self):
        self.assertAlmostEqual(sequence_similarity("", ""), 0.0)

    def test_author_surname_extraction(self):
        surnames = extract_author_surnames("John Smith; Jane Doe")
        self.assertIn("smith", surnames)
        self.assertIn("doe", surnames)

    def test_author_overlap_high(self):
        self.assertAlmostEqual(
            author_overlap_ratio(["smith", "doe", "brown"], ["smith", "doe", "white"]), 0.5)

    def test_author_overlap_low(self):
        self.assertAlmostEqual(
            author_overlap_ratio(["smith", "doe"], ["wang", "zhang"]), 0.0)

    def test_author_overlap_both_empty(self):
        self.assertAlmostEqual(author_overlap_ratio([], []), 0.0)

    def test_doi_normalize_url_prefix(self):
        self.assertEqual(normalize_doi("https://doi.org/10.1234/test"), "10.1234/test")
        self.assertEqual(normalize_doi("http://doi.org/10.1234/test"), "10.1234/test")
        self.assertEqual(normalize_doi("doi:10.1234/test"), "10.1234/test")

    def test_pair_id_deterministic(self):
        self.assertEqual(generate_pair_id("W1", "W2"), generate_pair_id("W1", "W2"))

    def test_pair_id_different(self):
        self.assertNotEqual(generate_pair_id("W1", "W2"), generate_pair_id("W3", "W4"))


class TestReviewDuplicatesCli(unittest.TestCase):
    @staticmethod
    def write_review_file(path: Path) -> None:
        fields = [
            "pair_id",
            "left_id",
            "right_id",
            "left_title",
            "right_title",
            "review_status",
        ]
        with path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            writer.writerow(
                {
                    "pair_id": "SP-test",
                    "left_id": "W1",
                    "right_id": "W2",
                    "left_title": "First title",
                    "right_title": "Second title",
                    "review_status": "pending",
                }
            )

    def test_generate_command_runs_without_argparse_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            review_file = temp_path / "suspected.csv"
            with (
                patch.object(review_duplicates, "ANALYSIS_DIR", temp_path / "analysis"),
                patch.object(review_duplicates, "DEFAULT_REVIEW_FILE", review_file),
                redirect_stdout(io.StringIO()),
            ):
                result = review_duplicates.main(
                    ["--generate", "--combined-csv", str(COMBINED_SAMPLE)]
                )
            self.assertEqual(result, 0)
            self.assertTrue((temp_path / "analysis" / "dedup_summary_w2.csv").exists())

    def test_list_command_runs_without_stats_attribute_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            review_file = Path(temp_dir) / "suspected.csv"
            self.write_review_file(review_file)
            output = io.StringIO()
            with redirect_stdout(output):
                result = review_duplicates.main(
                    ["--review-file", str(review_file), "--list"]
                )
            self.assertEqual(result, 0)
            self.assertIn("共 1 对待审核", output.getvalue())

    def test_stats_command_parses_and_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            review_file = Path(temp_dir) / "suspected.csv"
            self.write_review_file(review_file)
            output = io.StringIO()
            with redirect_stdout(output):
                result = review_duplicates.main(
                    ["--review-file", str(review_file), "--stats"]
                )
            self.assertEqual(result, 0)
            self.assertIn("审核统计（共 1 对）", output.getvalue())

    def test_unknown_argument_returns_argparse_error(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as context:
                review_duplicates.main(["--unknown-option"])
        self.assertEqual(context.exception.code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
