"""Tests for the algorithm-neutral W5 multi-method experiment runner."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.evaluate_w5_methods import main as evaluate_cli_main
from src.annotation_tasks import read_csv_rows, sha256_file, write_csv_rows
from src.w5_experiment import METRIC_FIELDS, run_w5_experiment
from src.w5_method_contract import RANKING_FIELDS, validate_method_output


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "w5_method_contract"
BENCHMARK_MANIFEST = (
    PROJECT_ROOT
    / "data"
    / "benchmarks"
    / "w4_query_relevance"
    / "v0.1.0"
    / "manifest.json"
)
BASE_REVISION = "d3a733bc68372847cfbbc65e42d2a0493370bfea"


def clean_experiment_environment() -> dict:
    return {
        "git_revision": BASE_REVISION,
        "git_dirty": False,
        "python": {
            "version": "3.fixture",
            "implementation": "CPython",
            "cache_tag": "fixture",
        },
        "platform": {"system": "fixture", "release": "fixture", "machine": "fixture"},
        "requirements": {"path": "requirements.txt", "sha256": "0" * 64},
        "dependencies": {"fixture-generator": "1.0"},
    }


class W5ExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def _create_package(
        self,
        *,
        package_name: str,
        fixture_name: str,
        method_id: str,
        family: str,
    ) -> Path:
        package_dir = self.root / package_name
        package_dir.mkdir(parents=True)
        ranking_path = package_dir / "ranking.csv"
        shutil.copyfile(FIXTURE_DIR / fixture_name, ranking_path)
        _fields, rows = read_csv_rows(ranking_path)
        for row in rows:
            row["method_id"] = method_id
        write_csv_rows(ranking_path, RANKING_FIELDS, rows)
        model = None
        if family in {"dense", "neural"}:
            model = {
                "name": "fixture-encoder",
                "revision": "fixture-v1",
                "adapter": None,
            }
        manifest = {
            "schema_version": "1.0",
            "contract_name": "w5_method_ranking",
            "contract_version": "1.0",
            "artifact_type": "method_ranking",
            "method": {
                "method_id": method_id,
                "display_name": method_id,
                "family": family,
                "parameters": {"fixture_only": True},
                "model": model,
            },
            "inputs": {
                "candidate_pool": {
                    "path": "data/annotation_tasks/w4/candidate_pool_v0.1.csv",
                    "sha256": (
                        "25f608eb4c94218dfa220ba108b15ec846b2bd418174501420a468c376ed17cc"
                    ),
                    "version": "w4_pilot_v0.1",
                },
                "research_queries": {
                    "path": "configs/w4/research_queries.json",
                    "sha256": (
                        "c77ec74ef4567614d3dfb6dab937b85398f95128cdb29e823587715002d99ab1"
                    ),
                    "version": "w4_pilot_v0.1",
                },
            },
            "ranking": {
                "path": "ranking.csv",
                "sha256": sha256_file(ranking_path),
                "row_count": 60,
                "score_direction": "higher_is_better",
                "tie_breaking": ["score_desc", "pair_id_asc"],
            },
            "generation": {
                "generated_at": "2026-08-17T20:00:00+08:00",
                "duration_seconds": 0.0,
                "git_revision": BASE_REVISION,
                "git_worktree_clean": True,
                "python": {"version": "3.fixture", "implementation": "CPython"},
                "platform": {
                    "system": "fixture",
                    "release": "fixture",
                    "machine": "fixture",
                },
                "dependencies": {"fixture-generator": "1.0"},
            },
            "label_access": {
                "benchmark_labels_read": False,
                "declaration": "Fixture ranking generated without benchmark labels.",
            },
        }
        manifest_path = package_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest_path

    def _run(self, manifests: list[Path], name: str = "experiment") -> dict:
        return run_w5_experiment(
            method_manifest_paths=manifests,
            benchmark_manifest_path=BENCHMARK_MANIFEST,
            output_dir=self.root / name,
            project_root=PROJECT_ROOT,
            require_clean_git=False,
        )

    def test_one_method_outputs_three_queries_and_macro(self) -> None:
        manifest = self._create_package(
            package_name="lexical",
            fixture_name="lexical_fixture.csv",
            method_id="fixture_lexical_v1",
            family="sparse",
        )
        result = self._run([manifest])
        self.assertEqual(result["method_ids"], ["fixture_lexical_v1"])
        self.assertEqual(len(result["metric_rows"]), 4)
        self.assertEqual(
            {row["research_query_id"] for row in result["metric_rows"]},
            {
                "rq01_stellar_classification",
                "rq02_stellar_parameters",
                "rq03_spectral_preprocessing",
                "macro",
            },
        )
        fields, rows = read_csv_rows(result["metrics_path"])
        self.assertEqual(fields, METRIC_FIELDS)
        self.assertEqual(len(rows), 4)
        self.assertTrue(result["experiment_manifest_path"].is_file())

    def test_multiple_unrecognized_method_families_share_one_runner(self) -> None:
        sparse = self._create_package(
            package_name="sparse",
            fixture_name="lexical_fixture.csv",
            method_id="future_sparse_v7",
            family="sparse",
        )
        hybrid = self._create_package(
            package_name="hybrid",
            fixture_name="dense_fixture.csv",
            method_id="future_hybrid_v9",
            family="hybrid",
        )
        result = self._run([sparse, hybrid])
        self.assertEqual(
            result["method_ids"], ["future_sparse_v7", "future_hybrid_v9"]
        )
        self.assertEqual(len(result["metric_rows"]), 8)
        self.assertEqual(len(result["experiment_manifest"]["methods"]), 2)
        self.assertFalse(
            result["experiment_manifest"]["evaluation"][
                "method_selection_or_best_claim"
            ]
        )

    def test_duplicate_method_id_is_rejected_before_benchmark_labels(self) -> None:
        first = self._create_package(
            package_name="first",
            fixture_name="lexical_fixture.csv",
            method_id="duplicate_v1",
            family="sparse",
        )
        second = self._create_package(
            package_name="second",
            fixture_name="dense_fixture.csv",
            method_id="duplicate_v1",
            family="hybrid",
        )
        with mock.patch(
            "src.w5_experiment.validate_benchmark_package"
        ) as benchmark_validator:
            with self.assertRaisesRegex(ValueError, "duplicate method_id"):
                self._run([first, second])
        benchmark_validator.assert_not_called()

    def test_invalid_manifest_is_rejected_before_benchmark_labels(self) -> None:
        manifest = self._create_package(
            package_name="invalid",
            fixture_name="lexical_fixture.csv",
            method_id="invalid_v1",
            family="sparse",
        )
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["ranking"]["sha256"] = "0" * 64
        manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with mock.patch(
            "src.w5_experiment.validate_benchmark_package"
        ) as benchmark_validator:
            with self.assertRaisesRegex(ValueError, "invalid method manifest"):
                self._run([manifest])
        benchmark_validator.assert_not_called()

    def test_candidate_pool_mismatch_is_rejected_before_benchmark_labels(self) -> None:
        first = self._create_package(
            package_name="first",
            fixture_name="lexical_fixture.csv",
            method_id="first_v1",
            family="sparse",
        )
        second = self._create_package(
            package_name="second",
            fixture_name="dense_fixture.csv",
            method_id="second_v1",
            family="dense",
        )
        first_package = validate_method_output(first, project_root=PROJECT_ROOT)
        second_package = copy.deepcopy(
            validate_method_output(second, project_root=PROJECT_ROOT)
        )
        second_package["manifest"]["inputs"]["candidate_pool"]["sha256"] = "0" * 64
        with mock.patch(
            "src.w5_experiment.validate_method_output",
            side_effect=[first_package, second_package],
        ), mock.patch(
            "src.w5_experiment.validate_benchmark_package"
        ) as benchmark_validator:
            with self.assertRaisesRegex(ValueError, "同一 Candidate Pool"):
                self._run([first, second])
        benchmark_validator.assert_not_called()

    def test_experiment_manifest_freezes_method_and_output_hashes(self) -> None:
        method = self._create_package(
            package_name="method",
            fixture_name="dense_fixture.csv",
            method_id="dense_fixture_v1",
            family="dense",
        )
        result = self._run([method])
        payload = result["experiment_manifest"]
        self.assertEqual(payload["benchmark"]["status"], "approved")
        self.assertEqual(
            payload["methods"][0]["manifest_sha256"], sha256_file(method)
        )
        self.assertEqual(
            payload["outputs"][0]["sha256"], sha256_file(result["metrics_path"])
        )
        self.assertEqual(payload["outputs"][0]["row_count"], 4)

    def test_cli_accepts_public_fixture_package(self) -> None:
        method = self._create_package(
            package_name="cli",
            fixture_name="lexical_fixture.csv",
            method_id="cli_fixture_v1",
            family="sparse",
        )
        output = io.StringIO()
        with mock.patch(
            "src.w5_experiment.capture_experiment_environment",
            return_value=clean_experiment_environment(),
        ), contextlib.redirect_stdout(output):
            exit_code = evaluate_cli_main(
                [
                    "--method-manifest",
                    str(method),
                    "--output-dir",
                    str(self.root / "cli-output"),
                ]
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("cli_fixture_v1", output.getvalue())
        self.assertIn("不自动宣称最佳方法", output.getvalue())


if __name__ == "__main__":
    unittest.main()
