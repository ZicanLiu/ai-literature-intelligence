"""TF-IDF 词法相关性模块的离线单元测试。

只使用内存构造数据和 tests/fixtures/ranking/ 下的已知答案 fixture，
不依赖网络，不读取 .env 或真实 API Key。
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from src.text_relevance import (
    ABSTRACT_WEIGHT,
    SCORE_FIELDS,
    TITLE_WEIGHT,
    TextRelevanceScorer,
    add_text_relevance_scores,
    build_idf,
    cosine_similarity,
    tfidf_vector,
    tokenize_text,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "ranking"


class TokenizeTests(unittest.TestCase):
    """词项拆分：英文小写词、中文二字组和特殊字符处理。"""

    def test_english_text_is_lowercased_and_split(self) -> None:
        self.assertEqual(
            tokenize_text("Machine Learning, Spectra!"),
            ["machine", "learning", "spectra"],
        )

    def test_chinese_text_becomes_bigrams(self) -> None:
        self.assertEqual(
            tokenize_text("恒星光谱"),
            ["恒星", "星光", "光谱"],
        )

    def test_single_chinese_character_is_kept(self) -> None:
        self.assertEqual(tokenize_text("星"), ["星"])

    def test_special_characters_are_ignored(self) -> None:
        self.assertEqual(tokenize_text("!@#$%^&*() ???"), [])

    def test_empty_and_none_text_return_empty_list(self) -> None:
        self.assertEqual(tokenize_text(""), [])
        self.assertEqual(tokenize_text(None), [])


class TfidfKnownAnswerTests(unittest.TestCase):
    """用 fixture 中的手算已知答案验证 IDF 和余弦相似度。"""

    @classmethod
    def setUpClass(cls) -> None:
        with (FIXTURE_DIR / "tfidf_known_answer.json").open(
            encoding="utf-8"
        ) as file:
            cls.fixture = json.load(file)

    def test_idf_matches_hand_computed_values(self) -> None:
        documents = [
            tokenize_text(text) for text in self.fixture["documents"].values()
        ]
        idf = build_idf(documents)
        for token, expected in self.fixture["expected_idf"].items():
            with self.subTest(token=token):
                self.assertAlmostEqual(
                    idf[token], expected, delta=self.fixture["tolerance"]
                )

    def test_cosine_matches_hand_computed_values(self) -> None:
        documents = {
            name: tokenize_text(text)
            for name, text in self.fixture["documents"].items()
        }
        idf = build_idf(list(documents.values()))
        query_vector = tfidf_vector(tokenize_text(self.fixture["query"]), idf)
        for name, expected in self.fixture["expected_cosine"].items():
            with self.subTest(document=name):
                document_vector = tfidf_vector(documents[name], idf)
                self.assertAlmostEqual(
                    cosine_similarity(query_vector, document_vector),
                    expected,
                    delta=self.fixture["tolerance"],
                )


class RelevanceScoreTests(unittest.TestCase):
    """三个相关性分数字段的行为与边界。"""

    def test_full_match_scores_higher_than_partial_match(self) -> None:
        papers = [
            {
                "title": "Machine Learning for Stellar Spectra",
                "abstract": "Machine learning estimates stellar parameters from spectra.",
            },
            {
                "title": "Machine Learning Workshop",
                "abstract": "A workshop about machine learning tools.",
            },
        ]
        scored = add_text_relevance_scores(papers, "machine learning stellar spectra")
        self.assertGreater(
            scored[0]["combined_relevance_score"],
            scored[1]["combined_relevance_score"],
        )
        self.assertGreater(scored[0]["combined_relevance_score"], 0.0)

    def test_complete_mismatch_scores_zero(self) -> None:
        papers = [
            {
                "title": "Deep Sea Fish Tracking",
                "abstract": "A sonar system for marine biology.",
            }
        ]
        scored = add_text_relevance_scores(papers, "machine learning stellar spectra")
        for field in SCORE_FIELDS:
            self.assertEqual(scored[0][field], 0.0)

    def test_missing_abstract_still_produces_scores(self) -> None:
        papers = [
            {
                "title": "Machine Learning for Stellar Spectra",
                "abstract": "",
            }
        ]
        scored = add_text_relevance_scores(papers, "machine learning spectra")
        self.assertEqual(scored[0]["abstract_relevance_score"], 0.0)
        self.assertGreater(scored[0]["title_relevance_score"], 0.0)
        self.assertAlmostEqual(
            scored[0]["combined_relevance_score"],
            round(TITLE_WEIGHT * scored[0]["title_relevance_score"], 4),
            places=4,
        )

    def test_missing_title_still_produces_scores(self) -> None:
        papers = [
            {
                "title": "",
                "abstract": "machine learning estimates stellar parameters from spectra",
            }
        ]
        scored = add_text_relevance_scores(papers, "machine learning spectra")
        self.assertEqual(scored[0]["title_relevance_score"], 0.0)
        self.assertGreater(scored[0]["abstract_relevance_score"], 0.0)

    def test_empty_query_scores_zero(self) -> None:
        papers = [
            {
                "title": "Machine Learning for Stellar Spectra",
                "abstract": "machine learning spectra",
            }
        ]
        for query in ("", "   ", None):
            with self.subTest(query=query):
                scored = add_text_relevance_scores(papers, query or "")
                for field in SCORE_FIELDS:
                    self.assertEqual(scored[0][field], 0.0)

    def test_empty_corpus_returns_empty_list(self) -> None:
        self.assertEqual(add_text_relevance_scores([], "machine learning"), [])

    def test_query_terms_outside_corpus_score_zero(self) -> None:
        papers = [
            {
                "title": "Machine Learning for Stellar Spectra",
                "abstract": "machine learning spectra",
            }
        ]
        scored = add_text_relevance_scores(papers, "zzzqqq xxyyww")
        for field in SCORE_FIELDS:
            self.assertEqual(scored[0][field], 0.0)

    def test_special_character_text_and_query_do_not_crash(self) -> None:
        papers = [{"title": "!@#$%^&*()", "abstract": "??? ---"}]
        scored = add_text_relevance_scores(papers, "!!! ???")
        for field in SCORE_FIELDS:
            self.assertEqual(scored[0][field], 0.0)

    def test_chinese_keyword_matches_chinese_title(self) -> None:
        papers = [
            {"title": "恒星光谱的机器学习应用", "abstract": ""},
            {"title": "深海鱼类的声呐跟踪", "abstract": ""},
        ]
        scored = add_text_relevance_scores(papers, "恒星光谱 机器学习")
        self.assertGreater(scored[0]["combined_relevance_score"], 0.0)
        self.assertEqual(scored[1]["combined_relevance_score"], 0.0)

    def test_single_paper_corpus(self) -> None:
        papers = [
            {
                "title": "Machine Learning for Stellar Spectra",
                "abstract": "machine learning spectra",
            }
        ]
        scored = add_text_relevance_scores(papers, "machine learning")
        self.assertGreater(scored[0]["combined_relevance_score"], 0.0)

    def test_scores_stay_within_zero_to_one(self) -> None:
        papers = [
            {
                "title": "Machine Learning for Stellar Spectra",
                "abstract": "machine learning " * 50 + "stellar spectra",
            },
            {
                "title": "machine machine machine",
                "abstract": "machine " * 100,
            },
            {"title": "", "abstract": ""},
        ]
        scored = add_text_relevance_scores(papers, "machine learning stellar spectra")
        for paper in scored:
            for field in SCORE_FIELDS:
                with self.subTest(field=field, title=paper["title"]):
                    self.assertGreaterEqual(paper[field], 0.0)
                    self.assertLessEqual(paper[field], 1.0)

    def test_combined_score_uses_fixed_documented_weights(self) -> None:
        self.assertAlmostEqual(TITLE_WEIGHT + ABSTRACT_WEIGHT, 1.0, places=6)
        papers = [
            {
                "title": "Machine Learning for Stellar Spectra",
                "abstract": "machine learning estimates parameters from spectra",
            }
        ]
        scored = add_text_relevance_scores(papers, "machine learning spectra")
        expected_combined = (
            TITLE_WEIGHT * scored[0]["title_relevance_score"]
            + ABSTRACT_WEIGHT * scored[0]["abstract_relevance_score"]
        )
        self.assertAlmostEqual(
            scored[0]["combined_relevance_score"],
            round(expected_combined, 4),
            places=4,
        )

    def test_scorer_does_not_modify_input_papers(self) -> None:
        papers = [{"title": "Machine Learning Spectra", "abstract": "spectra"}]
        add_text_relevance_scores(papers, "machine learning")
        self.assertEqual(papers, [{"title": "Machine Learning Spectra", "abstract": "spectra"}])

    def test_cosine_similarity_edge_cases(self) -> None:
        self.assertEqual(cosine_similarity({}, {"a": 1.0}), 0.0)
        self.assertEqual(cosine_similarity({"a": 1.0}, {}), 0.0)
        self.assertTrue(math.isclose(cosine_similarity({"a": 2.0}, {"a": 5.0}), 1.0))

    def test_scorer_with_empty_paper_list(self) -> None:
        scorer = TextRelevanceScorer([], "machine learning")
        self.assertEqual(scorer.score_papers([]), [])
        scores = scorer.score_paper({"title": "machine learning", "abstract": ""})
        self.assertEqual(scores["combined_relevance_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
