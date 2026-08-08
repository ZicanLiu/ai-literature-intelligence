"""质量门禁 validator、编排和返回码的离线回归测试。"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from app.quality_gate import exit_code_for_result, main, run_quality_gate
from src.validation import (
    ALLOWED_RELEVANCE_LABELS,
    ValidationResult,
    run_unittest_suite,
    scan_sensitive_risks,
    validate_csv_file,
    validate_json_file,
    validate_label_values,
    validate_markdown_links,
    validate_numeric_ranges,
    validate_references,
    validate_run_config,
    validate_unique_ids,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "tests/fixtures/validation"
VALID = FIXTURE_ROOT / "valid"
INVALID = FIXTURE_ROOT / "invalid"


def rows_from(result: ValidationResult) -> list[dict[str, str]]:
    return list(result.details.get("rows", []))


def make_minimal_project(root: Path) -> None:
    for name in ("app", "src", "tests", "docs", "data"):
        (root / name).mkdir(parents=True, exist_ok=True)


class ValidationFixtureTests(unittest.TestCase):
    def test_valid_fixture_passes_structure_ids_labels_relations_and_ranges(self) -> None:
        sample = validate_csv_file(VALID / "sample_ids.csv", required_headers=("openalex_id",))
        labels = validate_csv_file(
            VALID / "labels.csv",
            required_headers=("annotation_id", "openalex_id", "label"),
        )
        metrics = validate_csv_file(VALID / "metrics.csv")
        self.assertEqual(sample.status, "passed")
        self.assertEqual(labels.status, "passed")
        self.assertEqual(metrics.status, "passed")
        self.assertEqual(
            validate_unique_ids(rows_from(labels), "annotation_id", "labels.csv").status,
            "passed",
        )
        self.assertEqual(
            validate_label_values(
                rows_from(labels), "label", ALLOWED_RELEVANCE_LABELS, "labels.csv"
            ).status,
            "passed",
        )
        sample_ids = {row["openalex_id"] for row in rows_from(sample)}
        self.assertEqual(
            validate_references(
                rows_from(labels), "openalex_id", sample_ids, "labels.csv"
            ).status,
            "passed",
        )
        self.assertEqual(
            validate_numeric_ranges(
                rows_from(metrics),
                ("similarity_score", "precision", "ndcg"),
                0.0,
                1.0,
                "metrics.csv",
            ).status,
            "passed",
        )

    def test_missing_required_column_fails(self) -> None:
        result = validate_csv_file(
            INVALID / "missing_columns.csv", required_headers=("openalex_id",)
        )
        self.assertEqual(result.status, "failed")
        self.assertTrue(any("缺少字段" in error for error in result.errors))

    def test_duplicate_id_fails(self) -> None:
        table = validate_csv_file(INVALID / "duplicate_ids.csv")
        result = validate_unique_ids(rows_from(table), "case_id", "duplicate_ids.csv")
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(result.errors), 1)

    def test_invalid_label_fails(self) -> None:
        table = validate_csv_file(INVALID / "invalid_labels.csv")
        result = validate_label_values(
            rows_from(table), "label", ALLOWED_RELEVANCE_LABELS, "invalid_labels.csv"
        )
        self.assertEqual(result.status, "failed")

    def test_annotation_id_missing_from_sample_fails(self) -> None:
        table = validate_csv_file(INVALID / "missing_reference.csv")
        result = validate_references(
            rows_from(table),
            "openalex_id",
            {"https://openalex.org/W100001"},
            "missing_reference.csv",
        )
        self.assertEqual(result.status, "failed")
        self.assertIn("数据关联失效", result.errors[0])

    def test_similarity_out_of_range_fails(self) -> None:
        table = validate_csv_file(INVALID / "out_of_range.csv")
        result = validate_numeric_ranges(
            rows_from(table), ("similarity_score",), 0.0, 1.0, "out_of_range.csv"
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(result.errors), 1)

    def test_metrics_out_of_range_or_non_numeric_fail(self) -> None:
        table = validate_csv_file(INVALID / "out_of_range.csv")
        result = validate_numeric_ranges(
            rows_from(table), ("precision", "ndcg"), 0.0, 1.0, "out_of_range.csv"
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(result.errors), 2)

    def test_broken_markdown_local_link_fails(self) -> None:
        result = validate_markdown_links(
            FIXTURE_ROOT, (Path("invalid/broken_link.md"),)
        )
        self.assertEqual(result.status, "failed")
        self.assertIn("does-not-exist.csv", result.errors[0])

    def test_invalid_run_config_status_and_success_type_fail(self) -> None:
        result = validate_run_config(INVALID / "run_config.json")
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(result.errors), 2)

    def test_valid_run_config_passes(self) -> None:
        self.assertEqual(validate_run_config(VALID / "run_config.json").status, "passed")


class SecurityAndOrchestrationTests(unittest.TestCase):
    def test_sensitive_filename_rule_triggers_without_reading_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / ".env").write_bytes(b"")
            result = scan_sensitive_risks(root, (Path(".env"),))
        self.assertEqual(result.status, "failed")
        self.assertIn("敏感文件名", result.errors[0])

    def test_secret_shape_is_reported_without_echoing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            secret = "sk-" + "x" * 24
            (root / "code.py").write_text(f'TOKEN = "{secret}"', encoding="utf-8")
            result = scan_sensitive_risks(root, (Path("code.py"),))
        self.assertEqual(result.status, "failed")
        self.assertNotIn(secret, "\n".join(result.errors))

    def test_obvious_placeholder_in_tests_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = root / "tests/automated/example.py"
            path.parent.mkdir(parents=True)
            path.write_text(
                'api_key = "test-api-key-must-never-appear-in-output"\n',
                encoding="utf-8",
            )
            result = scan_sensitive_risks(root, (Path("tests/automated/example.py"),))
        self.assertEqual(result.status, "passed")

    def test_secret_shaped_value_in_tests_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = root / "tests/automated/example.py"
            path.parent.mkdir(parents=True)
            secret = "production-" + "x" * 24
            path.write_text(f'api_key = "{secret}"\n', encoding="utf-8")
            result = scan_sensitive_risks(root, (Path("tests/automated/example.py"),))
        self.assertEqual(result.status, "failed")
        self.assertNotIn(secret, "\n".join(result.errors))

    def test_placeholder_outside_tests_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = root / "src/example.py"
            path.parent.mkdir(parents=True)
            path.write_text(
                'api_key = "test-api-key-must-never-appear-in-output"\n',
                encoding="utf-8",
            )
            result = scan_sensitive_risks(root, (Path("src/example.py"),))
        self.assertEqual(result.status, "failed")

    def test_full_gate_allows_duplicate_ids_in_dedup_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            make_minimal_project(root)
            path = root / "data/samples/w2/dedup/combined_raw.csv"
            path.parent.mkdir(parents=True)
            path.write_text(
                "openalex_id,title\nhttps://openalex.org/W1,one\n"
                "https://openalex.org/W1,two\n",
                encoding="utf-8",
            )
            result = run_quality_gate(root, "full", run_tests=False, check_imports=False)
        self.assertEqual(result.status, "passed")

    def test_full_gate_rejects_duplicate_ids_in_curated_sample(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            make_minimal_project(root)
            path = root / "data/samples/w2/ranking/papers.csv"
            path.parent.mkdir(parents=True)
            path.write_text(
                "openalex_id,title\nhttps://openalex.org/W1,one\n"
                "https://openalex.org/W1,two\n",
                encoding="utf-8",
            )
            result = run_quality_gate(root, "full", run_tests=False, check_imports=False)
        self.assertEqual(result.status, "failed")
        self.assertTrue(any("ID 重复" in error for error in result.errors))

    def test_full_gate_excludes_deliberately_invalid_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            make_minimal_project(root)
            path = root / "tests/fixtures/ranking/labels_invalid_deliberate.csv"
            path.parent.mkdir(parents=True)
            path.write_text(
                "openalex_id,label\nhttps://openalex.org/W1,非法标签\n",
                encoding="utf-8",
            )
            result = run_quality_gate(root, "full", run_tests=False, check_imports=False)
        self.assertEqual(result.status, "passed")

    def test_full_gate_still_rejects_invalid_formal_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            make_minimal_project(root)
            path = root / "data/samples/w2/ranking/labels.csv"
            path.parent.mkdir(parents=True)
            path.write_text(
                "openalex_id,label\nhttps://openalex.org/W1,非法标签\n",
                encoding="utf-8",
            )
            result = run_quality_gate(root, "full", run_tests=False, check_imports=False)
        self.assertEqual(result.status, "failed")
        self.assertTrue(any("标签非法" in error for error in result.errors))

    def test_invalid_json_fails_without_exposing_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "broken.json"
            path.write_text("{broken", encoding="utf-8")
            result = validate_json_file(path)
        self.assertEqual(result.status, "failed")
        self.assertIn("JSON 无法解析", result.errors[0])

    def test_basic_gate_can_validate_minimal_project_without_tests_or_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            make_minimal_project(root)
            (root / "config.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            (root / "README.md").write_text("[config](config.json)\n", encoding="utf-8")
            result = run_quality_gate(
                root, "basic", run_tests=False, check_imports=False
            )
        self.assertEqual(result.status, "passed")

    def test_test_runner_uses_environment_guard_against_recursion(self) -> None:
        with patch.dict(os.environ, {"ASTRO_QUALITY_GATE_RUNNING": "1"}):
            result = run_unittest_suite(PROJECT_ROOT)
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.details["test_status"], "already_running")
        self.assertTrue(result.warnings)

    def test_exit_code_is_zero_for_pass_and_one_for_failure(self) -> None:
        self.assertEqual(exit_code_for_result(ValidationResult()), 0)
        failed = ValidationResult(errors=["failure"])
        self.assertEqual(exit_code_for_result(failed), 1)

    def test_cli_main_returns_structured_result_code(self) -> None:
        passed = ValidationResult(details={"level": "basic", "file_count": 1})
        failed = ValidationResult(
            errors=["failure"], details={"level": "basic", "file_count": 1}
        )
        with patch("app.quality_gate.run_quality_gate", return_value=passed):
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["--level", "basic"]), 0)
        with patch("app.quality_gate.run_quality_gate", return_value=failed):
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["--level", "basic"]), 1)

    def test_csv_row_with_wrong_column_count_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "bad.csv"
            path.write_text("id,value\n1,ok,extra\n", encoding="utf-8")
            result = validate_csv_file(path)
        self.assertEqual(result.status, "failed")
        self.assertIn("行列数不一致", result.errors[0])


if __name__ == "__main__":
    unittest.main()
