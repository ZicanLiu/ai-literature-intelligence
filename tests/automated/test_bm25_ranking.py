"""BM25 sparse ranking 与 W5 package 生成的定向测试（全部离线）。"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.bm25_ranking import (
    BM25_B,
    BM25_K1,
    bm25_idf,
    bm25_score,
    build_document_tokens,
    build_pool_rankings,
    compute_corpus_stats,
    rank_scored_pairs,
)
from src.text_relevance import tokenize_text
from src.w5_baseline_export import load_frozen_inputs, write_w5_package
from src.w5_method_contract import RANKING_FIELDS, validate_method_output


PROJECT_ROOT = Path(__file__).resolve().parents[2]

FIXTURE_ENVIRONMENT = {
    "git_revision": "d558a0888e4c71a9d001a67e0640d28394b6ac88",
    "git_worktree_clean": True,
    "python": {"version": "3.fixture", "implementation": "CPython"},
    "platform": {"system": "fixture", "release": "fixture", "machine": "fixture"},
    "dependencies": {},
}
FIXTURE_STARTED_AT = datetime(2026, 8, 17, 20, 0, tzinfo=timezone(timedelta(hours=8)))


def _score_with_tf(frequency: int, doc_length: int, *, df: int, n: int) -> float:
    """手算单查询词 BM25 分数的参考实现，用于核对公式。"""
    average_length = doc_length  # 单文档语料：平均长度即文档长度
    idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
    length_norm = 1.0 - BM25_B + BM25_B * doc_length / average_length
    return idf * (frequency * (BM25_K1 + 1.0)) / (
        frequency + BM25_K1 * length_norm
    )


class BM25FormulaTests(unittest.TestCase):
    def test_preregistered_parameters_are_fixed(self) -> None:
        self.assertEqual(BM25_K1, 1.5)
        self.assertEqual(BM25_B, 0.75)

    def test_score_matches_reference_formula(self) -> None:
        doc_tokens = ["alpha", "beta", "alpha"]
        stats = compute_corpus_stats({"d1": doc_tokens})
        actual = bm25_score(["alpha"], doc_tokens, stats)
        expected = _score_with_tf(2, 2, df=1, n=1)
        self.assertAlmostEqual(actual, expected, places=12)

    def test_absent_term_scores_zero(self) -> None:
        stats = compute_corpus_stats({"d1": ["alpha", "beta"]})
        self.assertEqual(bm25_score(["gamma"], ["alpha", "beta"], stats), 0.0)
        self.assertEqual(bm25_idf(0, 10), math.log(1.0 + (10 + 0.5) / 0.5))

    def test_empty_query_or_document_scores_zero(self) -> None:
        stats = compute_corpus_stats({"d1": ["alpha"]})
        self.assertEqual(bm25_score([], ["alpha"], stats), 0.0)
        self.assertEqual(bm25_score(["alpha"], [], stats), 0.0)

    def test_term_frequency_saturation_is_sublinear(self) -> None:
        doc_tf1 = ["alpha"] + ["filler"] * 20
        doc_tf10 = ["alpha"] * 10 + ["filler"] * 20
        doc_tf100 = ["alpha"] * 100 + ["filler"] * 20
        stats = compute_corpus_stats(
            {"a": doc_tf1, "b": doc_tf10, "c": doc_tf100}
        )
        score_1 = bm25_score(["alpha"], doc_tf1, stats)
        score_10 = bm25_score(["alpha"], doc_tf10, stats)
        score_100 = bm25_score(["alpha"], doc_tf100, stats)
        self.assertGreater(score_100, score_10)
        self.assertGreater(score_10, score_1)
        # 饱和：tf 从 10 涨到 100（10 倍）带来的增量必须远小于 1→10 的增量 ×9。
        self.assertLess(score_100 - score_10, (score_10 - score_1) * 9 * 0.5)

    def test_document_length_normalization(self) -> None:
        short_doc = ["alpha", "beta"]
        long_doc = ["alpha", "beta"] + ["filler"] * 200
        stats = compute_corpus_stats({"short": short_doc, "long": long_doc})
        short_score = bm25_score(["alpha"], short_doc, stats)
        long_score = bm25_score(["alpha"], long_doc, stats)
        self.assertGreater(short_score, long_score)
        # b=0 时长度归一化关闭，两者应相等。
        self.assertAlmostEqual(
            bm25_score(["alpha"], short_doc, stats, b=0.0),
            bm25_score(["alpha"], long_doc, stats, b=0.0),
        )

    def test_missing_abstract_keeps_title_tokens(self) -> None:
        self.assertEqual(
            build_document_tokens("Machine Learning Spectra", None),
            tokenize_text("Machine Learning Spectra"),
        )
        self.assertEqual(build_document_tokens(None, None), [])


class BM25ContractOrderingTests(unittest.TestCase):
    def test_ties_break_by_pair_id_ascending(self) -> None:
        rows = rank_scored_pairs(
            [("w4_rq01_003", 0.5), ("w4_rq01_001", 0.5), ("w4_rq01_002", 0.9)]
        )
        self.assertEqual(
            [(row["pair_id"], row["rank"]) for row in rows],
            [("w4_rq01_002", 1), ("w4_rq01_001", 2), ("w4_rq01_003", 3)],
        )

    def test_all_zero_scores_fall_back_to_pair_id_order(self) -> None:
        rows = rank_scored_pairs(
            [("w4_rq01_010", 0.0), ("w4_rq01_002", 0.0), ("w4_rq01_005", 0.0)]
        )
        self.assertEqual(
            [row["pair_id"] for row in rows],
            ["w4_rq01_002", "w4_rq01_005", "w4_rq01_010"],
        )


class BM25FrozenPoolTests(unittest.TestCase):
    """在真实冻结输入上的端到端测试；只读公共输入，不读任何 label。"""

    @classmethod
    def setUpClass(cls) -> None:
        frozen = load_frozen_inputs(PROJECT_ROOT)
        cls.pool_rows = frozen["pool_rows"]
        cls.research_queries = frozen["research_queries"]
        cls.rows = build_pool_rankings(cls.pool_rows, cls.research_queries)
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp_dir.cleanup)
        cls.package_dir = Path(cls.temp_dir.name) / "bm25_v1"
        cls.manifest = write_w5_package(
            cls.package_dir,
            method_id="bm25_v1",
            display_name="BM25 sparse lexical v1",
            family="sparse",
            parameters={"k1": BM25_K1, "b": BM25_B},
            model=None,
            rows=cls.rows,
            environment=FIXTURE_ENVIRONMENT,
            started_at=FIXTURE_STARTED_AT,
        )

    def test_rows_cover_60_pairs_and_20_per_query(self) -> None:
        self.assertEqual(len(self.rows), 60)
        counts = {}
        for row in self.rows:
            counts[row["research_query_id"]] = counts.get(row["research_query_id"], 0) + 1
        self.assertEqual(
            counts,
            {
                "rq01_stellar_classification": 20,
                "rq02_stellar_parameters": 20,
                "rq03_spectral_preprocessing": 20,
            },
        )

    def test_ranks_cover_1_to_20_per_query(self) -> None:
        for query in self.research_queries["queries"]:
            query_id = query["research_query_id"]
            ranks = sorted(
                row["rank"]
                for row in self.rows
                if row["research_query_id"] == query_id
            )
            self.assertEqual(ranks, list(range(1, 21)))

    def test_scores_are_finite_and_non_negative(self) -> None:
        for row in self.rows:
            self.assertTrue(math.isfinite(row["score"]))
            self.assertGreaterEqual(row["score"], 0.0)

    def test_known_same_paper_aliases_are_kept_as_records(self) -> None:
        pair_ids = {row["pair_id"] for row in self.rows}
        for alias in (
            "w4_rq02_002",
            "w4_rq02_011",
            "w4_rq03_004",
            "w4_rq03_011",
        ):
            self.assertIn(alias, pair_ids)

    def test_generated_package_passes_validator(self) -> None:
        result = validate_method_output(
            self.package_dir / "manifest.json", project_root=PROJECT_ROOT
        )
        self.assertEqual(result["method_id"], "bm25_v1")
        self.assertEqual(len(result["ranking_rows"]), 60)

    def test_frozen_input_hash_drift_is_rejected(self) -> None:
        manifest_path = self.package_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["inputs"]["candidate_pool"]["sha256"] = "0" * 64
        drift_dir = Path(self.temp_dir.name) / "drift"
        drift_dir.mkdir()
        shutil.copyfile(self.package_dir / "ranking.csv", drift_dir / "ranking.csv")
        drift_manifest = drift_dir / "manifest.json"
        drift_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "冻结 W4 v0.1 hash"):
            validate_method_output(drift_manifest, project_root=PROJECT_ROOT)


if __name__ == "__main__":
    unittest.main()
