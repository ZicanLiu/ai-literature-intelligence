"""Offline tests for the W5 SPECTER2 ranking implementation."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.annotation_tasks import load_research_queries, read_csv_rows
from src.specter2_ranking import (
    BASE_MODEL_ID,
    BASE_MODEL_REVISION,
    FROZEN_SIMILARITY,
    METHOD_ID,
    MISSING_ABSTRACT_FALLBACK,
    PAPER_ADAPTER_ID,
    PAPER_ADAPTER_REVISION,
    QUERY_ADAPTER_ID,
    QUERY_ADAPTER_REVISION,
    build_paper_text,
    generate_ranking_rows,
    generate_specter2_artifact,
    validate_generation_inputs,
)
from src.w5_method_contract import validate_method_output


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_POOL = (
    PROJECT_ROOT / "data" / "annotation_tasks" / "w4" / "candidate_pool_v0.1.csv"
)
RESEARCH_QUERIES = PROJECT_ROOT / "configs" / "w4" / "research_queries.json"
TEST_REVISION = "d3a733bc68372847cfbbc65e42d2a0493370bfea"


class DeterministicFakeBackend:
    separator_token = "[SEP]"
    model_manifest = {
        "name": BASE_MODEL_ID,
        "revision": BASE_MODEL_REVISION,
        "adapter": (
            f"query={QUERY_ADAPTER_ID}@{QUERY_ADAPTER_REVISION};"
            f"paper={PAPER_ADAPTER_ID}@{PAPER_ADAPTER_REVISION}"
        ),
    }
    parameters_manifest = {
        "query_text_field": "question_en",
        "paper_input": "title + tokenizer.sep_token + abstract",
        "missing_abstract_fallback": MISSING_ABSTRACT_FALLBACK,
        "max_length": 512,
        "pooling": "cls",
        "similarity": FROZEN_SIMILARITY,
        "score_direction": "higher_is_better",
        "batch_size": 8,
        "device": "fake-cpu",
        "dtype": "float32",
    }
    dependencies = {"fake-embedding-backend": "1.0"}

    def __init__(self, *, ties: bool = False) -> None:
        self.ties = ties
        self.query_texts: list[str] = []
        self.paper_texts: list[str] = []

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        self.query_texts = list(texts)
        return [[0.0, 0.0] for _text in texts]

    def embed_papers(self, texts: list[str]) -> list[list[float]]:
        self.paper_texts = list(texts)
        if self.ties:
            return [[0.0, 0.0] for _text in texts]
        return [
            [float((index % 20) + 1), float(len(text) % 7)]
            for index, text in enumerate(texts)
        ]


def clean_environment() -> dict:
    return {
        "git_revision": TEST_REVISION,
        "git_worktree_clean": True,
        "python": {"version": "3.fixture", "implementation": "CPython"},
        "platform": {"system": "fixture", "release": "fixture", "machine": "fixture"},
        "dependencies": {"fake-embedding-backend": "1.0"},
    }


class Specter2RankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pool_rows = read_csv_rows(CANDIDATE_POOL)[1]
        cls.research_queries = load_research_queries(RESEARCH_QUERIES)

    def test_generation_inputs_are_exactly_the_two_frozen_files(self) -> None:
        with mock.patch(
            "src.specter2_ranking.read_csv_rows", wraps=read_csv_rows
        ) as csv_reader, mock.patch(
            "src.specter2_ranking.load_research_queries", wraps=load_research_queries
        ) as query_reader:
            rows, queries = validate_generation_inputs(
                project_root=PROJECT_ROOT,
                candidate_pool_path=CANDIDATE_POOL,
                research_queries_path=RESEARCH_QUERIES,
            )
        self.assertEqual(len(rows), 60)
        self.assertEqual(len(queries["queries"]), 3)
        self.assertEqual(csv_reader.call_args.args[0].resolve(), CANDIDATE_POOL.resolve())
        self.assertEqual(
            query_reader.call_args.args[0].resolve(), RESEARCH_QUERIES.resolve()
        )
        signature = inspect.signature(generate_ranking_rows)
        self.assertNotIn("labels", signature.parameters)
        self.assertNotIn("benchmark", signature.parameters)

    def test_fake_backend_generates_valid_60_pair_contract_package(self) -> None:
        backend = DeterministicFakeBackend()
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.specter2_ranking._capture_generation_environment",
            return_value=clean_environment(),
        ):
            result = generate_specter2_artifact(
                project_root=PROJECT_ROOT,
                candidate_pool_path=CANDIDATE_POOL,
                research_queries_path=RESEARCH_QUERIES,
                output_dir=Path(temp_dir) / "specter2",
                backend=backend,
            )
            validated = validate_method_output(
                result["manifest_path"], project_root=PROJECT_ROOT
            )
        self.assertEqual(validated["method_id"], METHOD_ID)
        self.assertEqual(len(validated["ranking_rows"]), 60)
        self.assertEqual(set(validated["counts_by_query"].values()), {20})
        self.assertEqual(result["stats"]["missing_abstract_count"], 3)

    def test_missing_abstract_uses_title_only_without_deleting_pair(self) -> None:
        backend = DeterministicFakeBackend()
        rows, stats = generate_ranking_rows(
            pool_rows=self.pool_rows,
            research_queries=self.research_queries,
            backend=backend,
        )
        missing_indices = [
            index
            for index, row in enumerate(self.pool_rows)
            if not row["abstract"].strip()
        ]
        self.assertEqual(len(missing_indices), 3)
        self.assertEqual(stats["missing_abstract_count"], 3)
        self.assertEqual(len(rows), 60)
        for index in missing_indices:
            self.assertEqual(backend.paper_texts[index], self.pool_rows[index]["title"])
            self.assertNotIn(backend.separator_token, backend.paper_texts[index])

    def test_paper_text_uses_official_title_separator_abstract_format(self) -> None:
        self.assertEqual(
            build_paper_text("Title", "Abstract", separator="[SEP]"),
            "Title[SEP]Abstract",
        )
        self.assertEqual(
            build_paper_text("Title", "", separator="[SEP]"),
            "Title",
        )

    def test_score_is_higher_for_the_nearer_embedding(self) -> None:
        backend = DeterministicFakeBackend()
        rows, _stats = generate_ranking_rows(
            pool_rows=self.pool_rows,
            research_queries=self.research_queries,
            backend=backend,
        )
        for query_id in {row["research_query_id"] for row in rows}:
            query_rows = [row for row in rows if row["research_query_id"] == query_id]
            ordered_scores = [float(row["score"]) for row in query_rows]
            self.assertEqual(ordered_scores, sorted(ordered_scores, reverse=True))

    def test_ties_are_deterministic_by_pair_id(self) -> None:
        backend = DeterministicFakeBackend(ties=True)
        first, _ = generate_ranking_rows(
            pool_rows=self.pool_rows,
            research_queries=self.research_queries,
            backend=backend,
        )
        second, _ = generate_ranking_rows(
            pool_rows=self.pool_rows,
            research_queries=self.research_queries,
            backend=DeterministicFakeBackend(ties=True),
        )
        self.assertEqual(first, second)
        for query_id in {row["research_query_id"] for row in first}:
            pair_ids = [
                row["pair_id"] for row in first if row["research_query_id"] == query_id
            ]
            self.assertEqual(pair_ids, sorted(pair_ids))

    def test_manifest_freezes_real_model_and_adapter_metadata(self) -> None:
        backend = DeterministicFakeBackend()
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.specter2_ranking._capture_generation_environment",
            return_value=clean_environment(),
        ):
            result = generate_specter2_artifact(
                project_root=PROJECT_ROOT,
                candidate_pool_path=CANDIDATE_POOL,
                research_queries_path=RESEARCH_QUERIES,
                output_dir=Path(temp_dir) / "specter2",
                backend=backend,
            )
            manifest = result["manifest"]
        self.assertEqual(manifest["method"]["model"]["name"], BASE_MODEL_ID)
        self.assertEqual(
            manifest["method"]["model"]["revision"], BASE_MODEL_REVISION
        )
        self.assertIn(QUERY_ADAPTER_REVISION, manifest["method"]["model"]["adapter"])
        self.assertIn(PAPER_ADAPTER_REVISION, manifest["method"]["model"]["adapter"])
        self.assertEqual(
            manifest["method"]["parameters"]["similarity"], FROZEN_SIMILARITY
        )
        self.assertFalse(manifest["label_access"]["benchmark_labels_read"])

    def test_fake_backend_path_never_instantiates_real_model(self) -> None:
        with mock.patch(
            "src.specter2_ranking.Specter2EmbeddingBackend",
            side_effect=AssertionError("real backend must not be constructed"),
        ):
            rows, _stats = generate_ranking_rows(
                pool_rows=self.pool_rows,
                research_queries=self.research_queries,
                backend=DeterministicFakeBackend(),
            )
        self.assertEqual(len(rows), 60)


if __name__ == "__main__":
    unittest.main()
