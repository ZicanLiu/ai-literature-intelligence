"""Issue #21 Batch Runner 离线验收测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from app.batch_runner import main as batch_main
from src.batch_runner import load_batch_definition, run_batch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = PROJECT_ROOT / "configs" / "w2" / "integration_batch.example.json"
RANKING_KEYWORD = "machine learning stellar parameter estimation spectra"


class BatchRunnerTests(unittest.TestCase):
    def test_three_offline_items_create_independent_runs_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = run_batch(
                EXAMPLE_CONFIG,
                project_root=PROJECT_ROOT,
                pipeline_output_root=root / "runs",
                batch_output_root=root / "batches",
            )
            summary = result.summary
            self.assertEqual(summary["item_count"], 3)
            self.assertEqual(summary["success_count"], 3)
            self.assertEqual(summary["failure_count"], 0)
            run_ids = [row["run_id"] for row in summary["items"]]
            self.assertEqual(len(run_ids), len(set(run_ids)))
            self.assertTrue((result.batch_dir / "batch_summary.json").is_file())
            self.assertTrue((result.batch_dir / "batch_summary.csv").is_file())
            for row in summary["items"]:
                run_dir = root / "runs" / row["run_id"]
                config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
                self.assertEqual(config["batch"]["batch_id"], result.batch_id)
                self.assertEqual(config["batch"]["item_id"], row["item_id"])

    def test_continue_on_error_runs_later_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_file = root / "batch.json"
            self._write_config(config_file, continue_on_error=True)
            result = run_batch(
                config_file,
                project_root=PROJECT_ROOT,
                pipeline_output_root=root / "runs",
                batch_output_root=root / "batches",
            )
            self.assertEqual(result.summary["success_count"], 2)
            self.assertEqual(result.summary["failure_count"], 1)
            self.assertEqual(
                [row["status"] for row in result.summary["items"]],
                ["success", "failed", "success"],
            )

    def test_stop_on_error_marks_later_items_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_file = root / "batch.json"
            self._write_config(config_file, continue_on_error=False)
            result = run_batch(
                config_file,
                project_root=PROJECT_ROOT,
                pipeline_output_root=root / "runs",
                batch_output_root=root / "batches",
            )
            self.assertEqual(
                [row["status"] for row in result.summary["items"]],
                ["success", "failed", "not_run_after_failure"],
            )
            self.assertEqual(result.summary["not_run_count"], 1)

    def test_failure_after_parent_creation_keeps_run_traceability(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_file = root / "batch.json"
            payload = {
                "schema_version": "1.0",
                "batch_name": "failed-parent-trace",
                "continue_on_error": True,
                "terms_path": "tests/fixtures/pipeline/domain_terms.csv",
                "items": [
                    {
                        "item_id": "fixture_missing_query",
                        "enabled": True,
                        "acquisition_query_ids": ["q03_parameters"],
                        "ranking_keyword": RANKING_KEYWORD,
                        "mode": "offline",
                        "max_results_per_query": 10,
                        "offline_fixture_path": "tests/fixtures/pipeline/offline_queries.json",
                    }
                ],
            }
            config_file.write_text(json.dumps(payload), encoding="utf-8")
            result = run_batch(
                config_file,
                project_root=PROJECT_ROOT,
                pipeline_output_root=root / "runs",
                batch_output_root=root / "batches",
            )
            row = result.summary["items"][0]
            self.assertEqual(row["status"], "failed")
            self.assertTrue(row["run_id"])
            self.assertEqual(row["run_dir"], row["run_id"])
            self.assertTrue(row["error_summary"])
            failed_config = json.loads(
                (root / "runs" / row["run_id"] / "run_config.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(failed_config["status"], "failed")
            self.assertFalse(failed_config["success"])
            self.assertEqual(failed_config["error_summary"], row["error_summary"])

    def test_ambiguous_legacy_query_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "batch_name": "bad",
                        "items": [
                            {
                                "item_id": "bad_item",
                                "query_id": "q01_broad_ml",
                                "ranking_keyword": RANKING_KEYWORD,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "acquisition_query_ids"):
                load_batch_definition(path)

    def test_boolean_fields_require_real_json_booleans(self) -> None:
        base = {
            "schema_version": "1.0",
            "batch_name": "boolean-validation",
            "continue_on_error": False,
            "items": [
                {
                    "item_id": "item",
                    "enabled": True,
                    "include_unverified_labels": False,
                    "acquisition_query_ids": ["q01_broad_ml"],
                    "ranking_keyword": RANKING_KEYWORD,
                    "mode": "offline",
                }
            ],
        }
        cases = [
            ("continue_on_error", "false", "continue_on_error"),
            ("enabled", 1, "enabled"),
            ("include_unverified_labels", "true", "include_unverified_labels"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "batch.json"
            for field, invalid_value, expected_name in cases:
                with self.subTest(field=field, value=invalid_value):
                    payload = deepcopy(base)
                    if field == "continue_on_error":
                        payload[field] = invalid_value
                    else:
                        payload["items"][0][field] = invalid_value
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, expected_name):
                        load_batch_definition(path)

    def test_batch_cli_runs_example_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exit_code = batch_main(
                [
                    "--config",
                    str(EXAMPLE_CONFIG),
                    "--output-root",
                    str(root / "runs"),
                    "--batch-output-root",
                    str(root / "batches"),
                ]
            )
            self.assertEqual(exit_code, 0)

    @staticmethod
    def _write_config(path: Path, *, continue_on_error: bool) -> None:
        fixture = "tests/fixtures/pipeline/offline_queries.json"
        common = {
            "enabled": True,
            "ranking_keyword": RANKING_KEYWORD,
            "mode": "offline",
            "max_results_per_query": 10,
            "offline_fixture_path": fixture,
        }
        payload = {
            "schema_version": "1.0",
            "batch_name": "continue-policy-test",
            "continue_on_error": continue_on_error,
            "terms_path": "tests/fixtures/pipeline/domain_terms.csv",
            "items": [
                dict(common, item_id="first", acquisition_query_ids=["q01_broad_ml"]),
                dict(common, item_id="broken", acquisition_query_ids=["missing_query"]),
                dict(common, item_id="last", acquisition_query_ids=["q02_classification"]),
            ],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
