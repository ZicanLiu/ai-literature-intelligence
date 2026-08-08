"""领域词典、查询扩展和标注追溯的离线回归测试。"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from app.build_domain_queries import main as build_main
from src.domain_query import (
    ALLOWED_CATEGORIES,
    QueryBlueprint,
    build_query_set,
    load_domain_terms,
    load_relevance_labels,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TERMS_PATH = PROJECT_ROOT / "data/domain/stellar_spectra_terms_w2.csv"
FIXTURE_DIR = PROJECT_ROOT / "tests/fixtures/domain_query"
LABEL_PATH = PROJECT_ROOT / "data/manual/relevance_labels_w2_baseline.csv"
HARD_NEGATIVE_PATH = PROJECT_ROOT / "data/manual/hard_negative_cases_w2.csv"
TRACE_SAMPLE_PATHS = (
    PROJECT_ROOT / "data/samples/openalex_stellar_spectra_100.csv",
    PROJECT_ROOT / "data/samples/w2/domain_query/live_query_sample.csv",
)
TERM_HEADER = [
    "term_id",
    "term",
    "normalized_term",
    "category",
    "strength",
    "include_in_query",
    "example",
    "note",
    "source",
    "synonym",
]


class DomainTermTests(unittest.TestCase):
    def test_real_dictionary_loads_at_least_forty_valid_terms(self) -> None:
        terms = load_domain_terms(TERMS_PATH)
        self.assertGreaterEqual(len(terms), 40)
        self.assertTrue(all(term.category in ALLOWED_CATEGORIES for term in terms))
        self.assertEqual(len({term.term_id for term in terms}), len(terms))

    def test_duplicate_term_id_is_rejected(self) -> None:
        rows = [
            self.make_term("duplicate", "first"),
            self.make_term("duplicate", "second"),
        ]
        with self.term_file(rows) as path:
            with self.assertRaisesRegex(ValueError, "term_id 重复"):
                load_domain_terms(path)

    def test_duplicate_normalized_term_is_case_insensitive(self) -> None:
        rows = [
            self.make_term("one", "Stellar Spectrum"),
            self.make_term("two", "stellar spectrum"),
        ]
        with self.term_file(rows) as path:
            with self.assertRaisesRegex(ValueError, "normalized_term 重复"):
                load_domain_terms(path)

    def test_invalid_category_is_rejected(self) -> None:
        with self.term_file([self.make_term("one", "term", "made_up")]) as path:
            with self.assertRaisesRegex(ValueError, "category 非法"):
                load_domain_terms(path)

    def test_include_in_query_is_strict_boolean(self) -> None:
        row = self.make_term("one", "term")
        row["include_in_query"] = "yes"
        with self.term_file([row]) as path:
            with self.assertRaisesRegex(ValueError, "true 或 false"):
                load_domain_terms(path)

    def test_empty_term_is_rejected(self) -> None:
        row = self.make_term("one", "term")
        row["term"] = "  "
        with self.term_file([row]) as path:
            with self.assertRaisesRegex(ValueError, "term 不能为空"):
                load_domain_terms(path)

    def make_term(
        self, term_id: str, normalized: str, category: str = "spectrum_term"
    ) -> dict[str, str]:
        return {
            "term_id": term_id,
            "term": normalized,
            "normalized_term": normalized,
            "category": category,
            "strength": "8",
            "include_in_query": "true",
            "example": "example",
            "note": "note",
            "source": "fixture",
            "synonym": "",
        }

    def term_file(self, rows: list[dict[str, str]]):
        return TemporaryCsv(TERM_HEADER, rows)


class QueryGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.terms = load_domain_terms(TERMS_PATH)

    def test_generation_is_deterministic(self) -> None:
        first = build_query_set(self.terms)
        second = build_query_set(self.terms)
        self.assertEqual(first, second)

    def test_six_queries_are_nonempty_and_unique(self) -> None:
        result = build_query_set(self.terms)
        queries = result["queries"]
        self.assertEqual(len(queries), 6)
        self.assertEqual(len({query["query_id"] for query in queries}), 6)
        self.assertEqual(len({query["keyword"] for query in queries}), 6)
        self.assertTrue(all(query["keyword"].strip() for query in queries))
        self.assertTrue(all("title_abstract:" not in query["keyword"] for query in queries))

    def test_excluded_term_cannot_enter_query(self) -> None:
        blueprint = QueryBlueprint(
            "bad_query", "must fail", ("stellar spectrum", "photometry")
        )
        with self.assertRaisesRegex(ValueError, "include_in_query=false"):
            build_query_set(self.terms, (blueprint,))

    def test_unicode_and_special_char_term_does_not_crash_loading(self) -> None:
        row = DomainTermTests().make_term("unicode_term", "光谱 / spectrum β")
        with TemporaryCsv(TERM_HEADER, [row]) as path:
            terms = load_domain_terms(path)
        self.assertEqual(terms[0].term, "光谱 / spectrum β")

    def test_cli_writes_stable_json_to_requested_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "queries.json"
            args = ["--terms", str(TERMS_PATH), "--output", str(output)]
            self.assertEqual(build_main(args), 0)
            first = output.read_bytes()
            self.assertEqual(build_main(args), 0)
            self.assertEqual(output.read_bytes(), first)
            self.assertEqual(json.loads(first)["query_count"], 6)


class RelevanceLabelTests(unittest.TestCase):
    def test_valid_labels_are_parsed_and_traceable(self) -> None:
        labels = load_relevance_labels(
            FIXTURE_DIR / "labels_valid.csv", (FIXTURE_DIR / "sample_papers.csv",)
        )
        self.assertEqual(len(labels), 2)
        self.assertEqual({row["label"] for row in labels}, {"高度相关", "待讨论"})

    def test_invalid_label_is_rejected(self) -> None:
        rows = [self.valid_label(label="相关")]
        with TemporaryCsv(list(rows[0]), rows) as path:
            with self.assertRaisesRegex(ValueError, "label 非法"):
                load_relevance_labels(path, (FIXTURE_DIR / "sample_papers.csv",))

    def test_untraceable_openalex_id_is_rejected(self) -> None:
        rows = [self.valid_label(openalex_id="https://openalex.org/W999999")]
        with TemporaryCsv(list(rows[0]), rows) as path:
            with self.assertRaisesRegex(ValueError, "无法追溯"):
                load_relevance_labels(path, (FIXTURE_DIR / "sample_papers.csv",))

    def test_committed_fifty_labels_are_unique_and_traceable(self) -> None:
        labels = load_relevance_labels(LABEL_PATH, TRACE_SAMPLE_PATHS)
        self.assertEqual(len(labels), 50)
        self.assertEqual(len({row["openalex_id"] for row in labels}), 50)
        self.assertEqual(
            sum(row["annotator"] == "AI-assisted-draft" for row in labels), 13
        )
        counts = {
            label: sum(row["label"] == label for row in labels)
            for label in ("高度相关", "部分相关", "不相关", "待讨论")
        }
        self.assertEqual(
            counts,
            {"高度相关": 24, "部分相关": 1, "不相关": 23, "待讨论": 2},
        )

    def test_twelve_hard_negatives_are_unique_and_traceable(self) -> None:
        with HARD_NEGATIVE_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        traceable_ids: set[str] = set()
        for sample_path in TRACE_SAMPLE_PATHS:
            with sample_path.open("r", encoding="utf-8-sig", newline="") as handle:
                traceable_ids.update(
                    row["openalex_id"] for row in csv.DictReader(handle)
                )
        ids = [row["openalex_id"] for row in rows]
        self.assertEqual(len(rows), 12)
        self.assertEqual(len(set(ids)), 12)
        self.assertTrue(set(ids).issubset(traceable_ids))
        self.assertTrue(all(row["reason"].strip() for row in rows))

    def valid_label(self, **updates: str) -> dict[str, str]:
        row = {
            "annotation_id": "test_001",
            "openalex_id": "https://openalex.org/W100001",
            "source_query_ids": "q01_broad_ml",
            "title": "Traceable stellar spectrum paper",
            "label": "高度相关",
            "reason": "specific reason",
            "object_type": "star",
            "task_type": "classification",
            "matched_positive_terms": "stellar spectrum",
            "matched_negative_terms": "",
            "evidence_source": "fixture sample",
            "annotator": "fixture",
            "review_status": "已确认",
        }
        row.update(updates)
        return row


class TemporaryCsv:
    """让测试能在上下文结束时精确清理临时 CSV。"""

    def __init__(self, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
        self.fieldnames = fieldnames
        self.rows = rows
        self.directory: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        self.directory = tempfile.TemporaryDirectory()
        path = Path(self.directory.name) / "fixture.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.fieldnames)
            writer.writeheader()
            writer.writerows(self.rows)
        return path

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        assert self.directory is not None
        self.directory.cleanup()


if __name__ == "__main__":
    unittest.main()
