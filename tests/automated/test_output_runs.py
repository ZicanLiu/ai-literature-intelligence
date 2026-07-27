"""CLI 与独立实验目录的离线回归测试。"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_RANKED_FIELDS = [
    "title",
    "authors",
    "publication_year",
    "doi",
    "abstract",
    "cited_by_count",
    "source_name",
    "openalex_id",
    "landing_page_url",
    "keyword",
    "retrieved_at",
    "relevance_score",
    "impact_score",
    "recency_score",
    "completeness_score",
    "preliminary_score",
]
WINDOWS_INVALID_CHARS = set('<>:"/\\|?*')


class OutputRunTests(unittest.TestCase):
    """通过 subprocess 使用真实 CLI，但只运行本地 mock 数据。"""

    def run_cli(
        self,
        output_root: Path,
        *,
        keyword: str = "machine learning astronomical spectra",
        max_results: str = "20",
        run_name: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            "-m",
            "app.main",
            "--mode",
            "mock",
            "--keyword",
            keyword,
            "--max-results",
            max_results,
            "--output-root",
            str(output_root),
        ]
        if run_name is not None:
            command.extend(["--run-name", run_name])

        environment = os.environ.copy()
        environment.pop("OPENALEX_API_KEY", None)
        environment["MPLBACKEND"] = "Agg"
        environment["PYTHONUTF8"] = "1"
        return subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )

    @staticmethod
    def run_directories(output_root: Path) -> list[Path]:
        if not output_root.exists():
            return []
        return sorted(path for path in output_root.iterdir() if path.is_dir())

    @staticmethod
    def load_config(run_dir: Path) -> dict:
        with (run_dir / "run_config.json").open(encoding="utf-8") as file:
            return json.load(file)

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def test_mock_run_creates_complete_artifacts_and_consistent_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "runs"
            result = self.run_cli(output_root)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            run_directories = self.run_directories(output_root)
            self.assertEqual(len(run_directories), 1)
            run_dir = run_directories[0]
            config = self.load_config(run_dir)

            self.assertTrue(config["success"])
            self.assertEqual(config["status"], "completed")
            self.assertEqual(
                config["counts"],
                {"raw": 20, "cleaned": 20, "unique": 18, "duplicates": 2},
            )
            self.assertGreaterEqual(config["duration_seconds"], 0)
            self.assertEqual(
                config["scoring_weights"],
                {
                    "relevance_score": 0.4,
                    "impact_score": 0.3,
                    "recency_score": 0.2,
                    "completeness_score": 0.1,
                },
            )

            expected_paths = [
                run_dir / "run_config.json",
                run_dir / "raw" / "raw_response.json",
                run_dir / "tables" / "papers_ranked.csv",
                run_dir / "tables" / "duplicates_removed.csv",
                run_dir / "figures" / "top10_citations.png",
                run_dir / "figures" / "top10_preliminary_score.png",
                run_dir / "reports" / "run_summary.txt",
                run_dir / "data" / "literature.db",
            ]
            for path in expected_paths:
                self.assertTrue(path.is_file(), path)
                self.assertGreater(path.stat().st_size, 0, path)

            ranked_csv = run_dir / "tables" / "papers_ranked.csv"
            with ranked_csv.open(encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                rows = list(reader)
            self.assertEqual(reader.fieldnames, EXPECTED_RANKED_FIELDS)
            self.assertEqual(len(rows), config["counts"]["unique"])

            with (run_dir / "tables" / "duplicates_removed.csv").open(
                encoding="utf-8-sig", newline=""
            ) as file:
                duplicate_rows = list(csv.DictReader(file))
            self.assertEqual(len(duplicate_rows), config["counts"]["duplicates"])

            with (run_dir / "raw" / "raw_response.json").open(
                encoding="utf-8"
            ) as file:
                raw_response = json.load(file)
            self.assertEqual(len(raw_response["results"]), config["counts"]["raw"])

            connection = sqlite3.connect(run_dir / "data" / "literature.db")
            try:
                sqlite_count = connection.execute(
                    "SELECT COUNT(*) FROM papers"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(sqlite_count, config["counts"]["unique"])

            config_text = (run_dir / "run_config.json").read_text(encoding="utf-8")
            self.assertNotIn(str(Path.home()), config_text)
            for relative_path in config["output_files"].values():
                self.assertFalse(Path(relative_path).is_absolute())

            summary = (run_dir / "reports" / "run_summary.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("原始文献数量：20", summary)
            self.assertIn("清洗后文献数量：20", summary)
            self.assertIn("去重后文献数量：18", summary)
            self.assertIn("被去重文献数量：2", summary)

    def test_same_keyword_runs_twice_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "runs"
            first_result = self.run_cli(output_root)
            self.assertEqual(first_result.returncode, 0, first_result.stdout)
            first_run = self.run_directories(output_root)[0]
            first_csv = first_run / "tables" / "papers_ranked.csv"
            first_hash = self.sha256(first_csv)

            second_result = self.run_cli(output_root)
            self.assertEqual(second_result.returncode, 0, second_result.stdout)
            run_directories = self.run_directories(output_root)

            self.assertEqual(len(run_directories), 2)
            self.assertNotEqual(run_directories[0].name, run_directories[1].name)
            self.assertTrue(first_run.is_dir())
            self.assertEqual(self.sha256(first_csv), first_hash)
            self.assertEqual(
                {self.load_config(path)["keyword"] for path in run_directories},
                {"machine learning astronomical spectra"},
            )

    def test_different_keywords_are_stored_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "runs"
            keywords = [
                "machine learning astronomical spectra",
                "machine learning stellar spectra",
            ]
            for keyword in keywords:
                result = self.run_cli(output_root, keyword=keyword)
                self.assertEqual(result.returncode, 0, result.stdout)

            run_directories = self.run_directories(output_root)
            self.assertEqual(len(run_directories), 2)
            self.assertEqual(
                {self.load_config(path)["keyword"] for path in run_directories},
                set(keywords),
            )
            self.assertNotEqual(run_directories[0].name, run_directories[1].name)

    def test_chinese_and_special_keyword_uses_safe_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "runs"
            keyword = "恒星光谱：机器学习 / ? *"
            result = self.run_cli(output_root, keyword=keyword, max_results="3")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            run_dir = self.run_directories(output_root)[0]
            self.assertFalse(WINDOWS_INVALID_CHARS.intersection(run_dir.name))
            self.assertRegex(run_dir.name, r"_query-[0-9a-f]{8}_n3_")
            self.assertEqual(self.load_config(run_dir)["keyword"], keyword)

    def test_invalid_max_results_are_rejected_without_run_directory(self) -> None:
        for invalid_value in ("0", "-1", "not-an-integer"):
            with self.subTest(max_results=invalid_value):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    output_root = Path(temporary_directory) / "runs"
                    result = self.run_cli(output_root, max_results=invalid_value)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.run_directories(output_root), [])

    def test_empty_keyword_is_rejected_without_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "runs"
            result = self.run_cli(output_root, keyword="   ")

            self.assertEqual(result.returncode, 1)
            self.assertIn("keyword", result.stdout)
            self.assertEqual(self.run_directories(output_root), [])

    def test_custom_output_root_and_run_name_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "custom-results"
            result = self.run_cli(
                output_root,
                keyword="stellar spectra",
                max_results="5",
                run_name="README check: 中文 / ?",
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            run_directories = self.run_directories(output_root)
            self.assertEqual(len(run_directories), 1)
            run_dir = run_directories[0]
            self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]+", run_dir.name))
            config = self.load_config(run_dir)
            self.assertEqual(config["keyword"], "stellar spectra")
            self.assertEqual(config["max_results"], 5)


if __name__ == "__main__":
    unittest.main()
