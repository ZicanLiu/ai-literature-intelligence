"""Offline tests for the preregistered W5 Cross-Encoder ranking."""

from __future__ import annotations

import builtins
import json
import math
import sys
import tempfile
import types
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from app.run_cross_encoder_ranking import build_parser
from src.annotation_tasks import read_csv_rows, sha256_file, write_csv_rows
from src.cross_encoder_ranking import (
    ACTIVATION,
    APPLY_SOFTMAX,
    BATCH_SIZE,
    CANDIDATE_POOL_PATH,
    DEVICE,
    FROZEN_MODEL,
    MAX_LENGTH,
    METHOD_ID,
    MODEL_DEPENDENCIES,
    MODEL_NAME,
    MODEL_REVISION,
    RESEARCH_QUERIES_PATH,
    SentenceTransformersCrossEncoderScorer,
    frozen_method_parameters,
    generate_cross_encoder_artifact,
    load_pair_inputs,
    score_and_rank,
    validate_frozen_model_metadata,
)
from src.w5_method_contract import RANKING_FIELDS, validate_method_output


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_POOL = PROJECT_ROOT / CANDIDATE_POOL_PATH
RESEARCH_QUERIES = PROJECT_ROOT / RESEARCH_QUERIES_PATH
TEST_REVISION = "a" * 40


class RecordingScorer:
    def __init__(self, scores: list[object] | None = None) -> None:
        self.scores = scores
        self.calls: list[tuple[list[tuple[str, str]], int]] = []

    def score_pairs(
        self,
        pairs: list[tuple[str, str]],
        *,
        batch_size: int,
    ) -> list[object]:
        copied_pairs = list(pairs)
        self.calls.append((copied_pairs, batch_size))
        if self.scores is not None:
            return list(self.scores)
        return [float(index) for index in range(len(copied_pairs))]


def fake_environment() -> dict[str, object]:
    return {
        "git_revision": TEST_REVISION,
        "git_worktree_clean": True,
        "python": {"version": "3.test", "implementation": "CPython"},
        "platform": {
            "system": "test",
            "release": "test",
            "machine": "test",
        },
        "dependencies": {name: "test" for name in MODEL_DEPENDENCIES},
    }


class CrossEncoderInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = load_pair_inputs(CANDIDATE_POOL, RESEARCH_QUERIES)

    def test_all_60_pairs_and_three_queries_are_preserved(self) -> None:
        self.assertEqual(len(self.inputs), 60)
        self.assertEqual(
            Counter(item.research_query_id for item in self.inputs),
            {
                "rq01_stellar_classification": 20,
                "rq02_stellar_parameters": 20,
                "rq03_spectral_preprocessing": 20,
            },
        )
        self.assertEqual(len({item.pair_id for item in self.inputs}), 60)

    def test_three_missing_abstracts_use_title_only(self) -> None:
        title_only = [item for item in self.inputs if item.title_only]
        self.assertEqual(
            [item.pair_id for item in title_only],
            ["w4_rq01_017", "w4_rq02_001", "w4_rq02_015"],
        )
        pool_by_pair = {
            row["pair_id"]: row for row in read_csv_rows(CANDIDATE_POOL)[1]
        }
        for item in title_only:
            self.assertEqual(item.paper_text, pool_by_pair[item.pair_id]["title"])
            self.assertNotIn("\n\n", item.paper_text)
        self.assertTrue(
            all("\n\n" in item.paper_text for item in self.inputs if not item.title_only)
        )

    def test_query_text_comes_only_from_question_en(self) -> None:
        payload = json.loads(RESEARCH_QUERIES.read_text(encoding="utf-8"))
        expected = {
            query["research_query_id"]: query["question_en"]
            for query in payload["queries"]
        }
        fields, candidate_rows = read_csv_rows(CANDIDATE_POOL)
        for row in candidate_rows:
            row["research_question_en"] = "CANDIDATE QUESTION MUST NOT BE USED"
        with tempfile.TemporaryDirectory() as temp_dir:
            modified_pool = Path(temp_dir) / "candidate_pool.csv"
            write_csv_rows(modified_pool, fields, candidate_rows)
            inputs = load_pair_inputs(modified_pool, RESEARCH_QUERIES)
        for item in inputs:
            self.assertEqual(item.query_text, expected[item.research_query_id])
            self.assertNotEqual(item.query_text, "CANDIDATE QUESTION MUST NOT BE USED")


class CrossEncoderScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = load_pair_inputs(CANDIDATE_POOL, RESEARCH_QUERIES)

    def test_fake_backend_receives_one_batched_call(self) -> None:
        scorer = RecordingScorer()
        rows = score_and_rank(self.inputs, scorer)
        self.assertEqual(len(rows), 60)
        self.assertEqual(len(scorer.calls), 1)
        self.assertEqual(len(scorer.calls[0][0]), 60)
        self.assertEqual(scorer.calls[0][1], 16)

    def test_score_count_mismatch_is_rejected(self) -> None:
        scorer = RecordingScorer([0.0] * 59)
        with self.assertRaisesRegex(ValueError, "返回数量"):
            score_and_rank(self.inputs, scorer)

    def test_non_numeric_and_non_finite_scores_are_rejected(self) -> None:
        invalid_values = ["1.0", None, math.nan, math.inf, -math.inf]
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                scores: list[object] = [0.0] * 60
                scores[0] = invalid
                expected = "不是数值" if invalid in {"1.0", None} else "有限数值"
                with self.assertRaisesRegex(ValueError, expected):
                    score_and_rank(self.inputs, RecordingScorer(scores))

    def test_higher_score_ranks_first_and_ties_use_pair_id(self) -> None:
        canonical = sorted(self.inputs, key=lambda item: item.pair_id)
        scores = [0.0] * len(canonical)
        rq01_indexes = [
            index
            for index, item in enumerate(canonical)
            if item.research_query_id == "rq01_stellar_classification"
        ]
        scores[rq01_indexes[-1]] = 3.5
        rows = score_and_rank(self.inputs, RecordingScorer(scores))
        rq01 = [
            row
            for row in rows
            if row["research_query_id"] == "rq01_stellar_classification"
        ]
        self.assertEqual(rq01[0]["pair_id"], canonical[rq01_indexes[-1]].pair_id)
        tied = [row for row in rq01 if row["score"] == 0.0]
        self.assertEqual(
            [row["pair_id"] for row in tied],
            sorted(row["pair_id"] for row in tied),
        )
        self.assertEqual([row["rank"] for row in rq01], list(range(1, 21)))

    def test_input_order_does_not_change_scores_or_ranks(self) -> None:
        forward = score_and_rank(self.inputs, RecordingScorer())
        reversed_rows = score_and_rank(list(reversed(self.inputs)), RecordingScorer())
        self.assertEqual(forward, reversed_rows)


class CrossEncoderModelTests(unittest.TestCase):
    def test_model_identity_and_parameters_are_frozen(self) -> None:
        self.assertEqual(METHOD_ID, "cross_encoder_msmarco_v1")
        self.assertEqual(MODEL_NAME, "cross-encoder/ms-marco-MiniLM-L6-v2")
        self.assertEqual(
            MODEL_REVISION,
            "233902d25c440f23af6f7d6e94d2946bac0bee0a",
        )
        self.assertEqual(len(MODEL_REVISION), 40)
        parameters = frozen_method_parameters()
        self.assertEqual(parameters["max_length"], 512)
        self.assertEqual(parameters["activation"], "identity")
        self.assertIs(parameters["apply_softmax"], False)
        self.assertEqual(parameters["batch_size"], 16)
        self.assertEqual(parameters["device"], "cpu")

    def test_invalid_model_metadata_is_rejected(self) -> None:
        invalid_models = [
            {"name": MODEL_NAME, "revision": "main", "adapter": None},
            {"name": "another-model", "revision": MODEL_REVISION, "adapter": None},
            {**FROZEN_MODEL, "max_length": 512},
        ]
        for model in invalid_models:
            with self.subTest(model=model):
                with self.assertRaisesRegex(ValueError, "metadata"):
                    validate_frozen_model_metadata(model)

    def test_real_backend_passes_explicit_identity_and_no_softmax(self) -> None:
        constructor_calls: list[tuple[str, dict[str, object]]] = []
        prediction_calls: list[tuple[list[tuple[str, str]], dict[str, object]]] = []

        class FakeIdentity:
            pass

        class FakeScores:
            def tolist(self) -> list[float]:
                return [1.25]

        class FakeCrossEncoder:
            def __init__(self, model_name: str, **kwargs: object) -> None:
                constructor_calls.append((model_name, kwargs))

            def predict(
                self, pairs: list[tuple[str, str]], **kwargs: object
            ) -> FakeScores:
                prediction_calls.append((pairs, kwargs))
                return FakeScores()

        fake_torch = types.ModuleType("torch")
        fake_torch.nn = types.SimpleNamespace(Identity=FakeIdentity)
        fake_sentence_transformers = types.ModuleType("sentence_transformers")
        fake_sentence_transformers.CrossEncoder = FakeCrossEncoder
        with mock.patch.dict(
            sys.modules,
            {
                "torch": fake_torch,
                "sentence_transformers": fake_sentence_transformers,
            },
        ):
            scores = SentenceTransformersCrossEncoderScorer().score_pairs(
                [("query", "paper")], batch_size=BATCH_SIZE
            )

        self.assertEqual(scores, [1.25])
        model_name, constructor_kwargs = constructor_calls[0]
        self.assertEqual(model_name, MODEL_NAME)
        self.assertEqual(constructor_kwargs["revision"], MODEL_REVISION)
        self.assertEqual(constructor_kwargs["max_length"], MAX_LENGTH)
        self.assertEqual(constructor_kwargs["device"], DEVICE)
        self.assertIsInstance(constructor_kwargs["activation_fn"], FakeIdentity)
        _pairs, prediction_kwargs = prediction_calls[0]
        self.assertIs(prediction_kwargs["apply_softmax"], APPLY_SOFTMAX)
        self.assertIsInstance(prediction_kwargs["activation_fn"], FakeIdentity)
        self.assertIs(prediction_kwargs["convert_to_numpy"], True)

    def test_backend_construction_does_not_import_or_download_model(self) -> None:
        original_import = builtins.__import__

        def guarded_import(
            name: str,
            globals: object = None,
            locals: object = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if name in {"torch", "sentence_transformers"}:
                raise AssertionError(f"unexpected model import: {name}")
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=guarded_import):
            scorer = SentenceTransformersCrossEncoderScorer()
        self.assertIsNone(scorer._model)


class CrossEncoderArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.output_dir = Path(self.temp_dir.name) / METHOD_ID

    def _generate(self) -> dict[str, object]:
        return generate_cross_encoder_artifact(
            project_root=PROJECT_ROOT,
            output_dir=self.output_dir,
            scorer=RecordingScorer(),
            environment_snapshot=fake_environment(),
        )

    def test_manifest_ranking_hash_and_public_validator(self) -> None:
        result = self._generate()
        manifest_path = Path(result["manifest_path"])
        ranking_path = Path(result["ranking_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["method"]["model"]), {"name", "revision", "adapter"})
        self.assertEqual(manifest["method"]["model"], dict(FROZEN_MODEL))
        self.assertEqual(manifest["ranking"]["sha256"], sha256_file(ranking_path))
        self.assertEqual(manifest["ranking"]["row_count"], 60)
        self.assertEqual(result["title_only_count"], 3)
        fields, rows = read_csv_rows(ranking_path)
        self.assertEqual(fields, RANKING_FIELDS)
        self.assertEqual(len(rows), 60)
        validated = validate_method_output(manifest_path, project_root=PROJECT_ROOT)
        self.assertEqual(validated["method_id"], METHOD_ID)
        self.assertEqual(len(validated["ranking_rows"]), 60)

    def test_fake_generation_does_not_import_model_stack(self) -> None:
        original_import = builtins.__import__

        def guarded_import(
            name: str,
            globals: object = None,
            locals: object = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if name in {"torch", "sentence_transformers"}:
                raise AssertionError(f"unexpected model import: {name}")
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=guarded_import):
            result = self._generate()
        self.assertEqual(len(result["ranking_rows"]), 60)

    def test_cli_has_no_benchmark_or_label_parameters(self) -> None:
        option_strings = {
            option
            for action in build_parser()._actions
            for option in action.option_strings
        }
        self.assertFalse(
            any("benchmark" in option or "label" in option for option in option_strings)
        )


if __name__ == "__main__":
    unittest.main()
