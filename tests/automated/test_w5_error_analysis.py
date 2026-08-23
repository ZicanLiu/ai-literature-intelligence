"""Tests for the formal W5 Error Analysis contract."""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from app.analyze_w5_errors import main as analyze_cli_main
from src.annotation_tasks import read_csv_rows, sha256_file, write_csv_rows
from src.w5_error_analysis import (
    ERROR_CASE_FIELDS,
    RANK_SHIFT_MIN_DELTA,
    RELEVANT_BURIED_MIN_RANK,
    TAXONOMY_MAPPING_FIELDS,
    analyze_w5_errors,
    build_taxonomy_mapping,
    render_analysis_outputs,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "w5_method_contract"
CANDIDATE_POOL = (
    PROJECT_ROOT / "data" / "annotation_tasks" / "w4" / "candidate_pool_v0.1.csv"
)
BENCHMARK_MANIFEST = (
    PROJECT_ROOT
    / "data"
    / "benchmarks"
    / "w4_query_relevance"
    / "v0.1.0"
    / "manifest.json"
)
TAXONOMY_SOURCE = (
    PROJECT_ROOT / "data" / "analysis" / "w4_query_boundary_examples.csv"
)
TAXONOMY_MAPPING = (
    PROJECT_ROOT
    / "data"
    / "analysis"
    / "w5_error_taxonomy"
    / "w5_taxonomy_mapping.csv"
)
BASE_REVISION = "d558a0888e4c71a9d001a67e0640d28394b6ac88"
RANKING_FIELDS = ["pair_id", "research_query_id", "method_id", "score", "rank"]


class W5ErrorAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.lexical_manifest, self.lexical_ranking = self._create_package(
            package_name="lexical",
            fixture_name="lexical_fixture.csv",
            method_id="fixture_lexical_v1",
            family="sparse",
        )
        self.dense_manifest, self.dense_ranking = self._create_package(
            package_name="dense",
            fixture_name="dense_fixture.csv",
            method_id="fixture_dense_v1",
            family="dense",
        )

    def _create_package(
        self,
        *,
        package_name: str,
        fixture_name: str,
        method_id: str,
        family: str,
    ) -> tuple[Path, Path]:
        package_dir = self.root / package_name
        package_dir.mkdir(parents=True)
        ranking_path = package_dir / "ranking.csv"
        shutil.copyfile(FIXTURE_DIR / fixture_name, ranking_path)
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
                "display_name": method_id.replace("_", " "),
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
                "declaration": "Synthetic ranking created without benchmark judgements.",
            },
        }
        manifest_path = package_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest_path, ranking_path

    def _analyze(self, manifests: list[Path] | None = None) -> dict:
        return analyze_w5_errors(
            manifests or [self.lexical_manifest],
            benchmark_manifest_path=BENCHMARK_MANIFEST,
            taxonomy_mapping_path=TAXONOMY_MAPPING,
            taxonomy_source_path=TAXONOMY_SOURCE,
            project_root=PROJECT_ROOT,
        )

    def _mutate_ranking(self, manifest_path: Path, mutation) -> None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ranking_path = manifest_path.parent / manifest["ranking"]["path"]
        _fields, rows = read_csv_rows(ranking_path)
        mutation(rows)
        write_csv_rows(ranking_path, RANKING_FIELDS, rows)
        manifest["ranking"]["sha256"] = sha256_file(ranking_path)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_single_lexical_manifest_joins_approved_labels(self) -> None:
        result = self._analyze()
        self.assertEqual([item["method_id"] for item in result["methods"]], ["fixture_lexical_v1"])
        self.assertEqual(len(result["pair_rows"]), 60)
        first = next(row for row in result["pair_rows"] if row["pair_id"] == "w4_rq01_001")
        self.assertEqual(first["research_query_id"], "rq01_stellar_classification")
        self.assertEqual(first["final_label"], "0")
        self.assertEqual(first["rank"], 1)
        self.assertEqual(first["example_role"], "unclassified")

    def test_dense_fixture_and_multiple_methods_produce_rank_shift(self) -> None:
        result = self._analyze([self.lexical_manifest, self.dense_manifest])
        self.assertEqual(
            [item["method_id"] for item in result["methods"]],
            ["fixture_dense_v1", "fixture_lexical_v1"],
        )
        self.assertEqual(len(result["pair_rows"]), 120)
        shift = next(row for row in result["rank_shift_rows"] if row["pair_id"] == "w4_rq01_001")
        self.assertEqual(shift["min_rank"], 1)
        self.assertEqual(shift["max_rank"], 20)
        self.assertEqual(shift["rank_shift"], 19)
        self.assertGreaterEqual(shift["rank_shift"], RANK_SHIFT_MIN_DELTA)

    def test_taxonomy_mapping_and_sixty_pair_coverage(self) -> None:
        source_fields, source_rows = read_csv_rows(TAXONOMY_SOURCE)
        self.assertTrue({"example_role", "boundary_type"} <= set(source_fields))
        mapping_fields, mapping_rows = read_csv_rows(TAXONOMY_MAPPING)
        self.assertEqual(mapping_fields, TAXONOMY_MAPPING_FIELDS)
        self.assertEqual(mapping_rows, build_taxonomy_mapping(source_rows))
        self.assertEqual(
            Counter(row["example_role"] for row in mapping_rows),
            {"scope_in": 6, "hard_negative": 12, "boundary": 2},
        )

        result = self._analyze()
        benchmark_coverage = {
            row["category"]: row
            for row in result["coverage_rows"]
            if row["coverage_scope"] == "benchmark_coverage"
        }
        self.assertEqual(
            {key: row["count"] for key, row in benchmark_coverage.items()},
            {"scope_in": 6, "hard_negative": 12, "boundary": 2, "unclassified": 40},
        )
        self.assertTrue(all(row["denominator"] == 60 for row in benchmark_coverage.values()))

    def test_irrelevant_top5_and_top10_use_approved_label(self) -> None:
        result = self._analyze()
        cases = {
            (row["case_type"], row["pair_id"]): row
            for row in result["error_case_rows"]
        }
        top5 = cases[("irrelevant_top_k", "w4_rq01_001")]
        self.assertEqual((top5["final_label"], top5["rank"]), ("0", 1))
        self.assertEqual((top5["in_top5"], top5["in_top10"]), (1, 1))
        top10_only = cases[("irrelevant_top_k", "w4_rq01_010")]
        self.assertEqual((top10_only["final_label"], top10_only["rank"]), ("0", 10))
        self.assertEqual((top10_only["in_top5"], top10_only["in_top10"]), (0, 1))

        scope_rows = [
            row for row in result["matrix_rows"] if row["example_role"] == "scope_in"
        ]
        self.assertTrue(scope_rows)
        self.assertTrue(all(row["irrelevant_top10"] == 0 for row in scope_rows))

    def test_relevant_buried_uses_fixed_threshold(self) -> None:
        result = self._analyze()
        buried = next(
            row
            for row in result["error_case_rows"]
            if row["case_type"] == "relevant_buried"
            and row["pair_id"] == "w4_rq01_017"
        )
        self.assertEqual(buried["final_label"], "2")
        self.assertEqual(buried["rank"], 17)
        self.assertGreaterEqual(buried["rank"], RELEVANT_BURIED_MIN_RANK)

    def test_hard_negative_top_k_requires_w4_evidence(self) -> None:
        result = self._analyze()
        hard_negative = next(
            row
            for row in result["error_case_rows"]
            if row["case_type"] == "hard_negative_top_k"
            and row["pair_id"] == "w4_rq02_002"
        )
        self.assertEqual(hard_negative["example_role"], "hard_negative")
        self.assertEqual(hard_negative["error_type"], "existing_labels_as_input")
        self.assertEqual(hard_negative["rank"], 2)
        self.assertTrue(hard_negative["source"].endswith("#qb_010"))

    def test_same_openalex_work_pairs_are_not_collapsed(self) -> None:
        _fields, pool_rows = read_csv_rows(CANDIDATE_POOL)
        pool_by_pair = {row["pair_id"]: row for row in pool_rows}
        aliases = ("w4_rq01_011", "w4_rq02_014")
        self.assertEqual(
            pool_by_pair[aliases[0]]["openalex_id"],
            pool_by_pair[aliases[1]]["openalex_id"],
        )
        result = self._analyze([self.lexical_manifest, self.dense_manifest])
        alias_rows = [row for row in result["pair_rows"] if row["pair_id"] in aliases]
        self.assertEqual(len(alias_rows), 4)
        self.assertEqual(
            {row["pair_id"] for row in alias_rows},
            set(aliases),
        )
        self.assertEqual(
            {row["pair_id"]: row["final_label"] for row in alias_rows},
            {"w4_rq01_011": "2", "w4_rq02_014": "0"},
        )

    def test_invalid_manifest_fails_before_benchmark_is_opened(self) -> None:
        rows = read_csv_rows(self.lexical_ranking)[1]
        rows[0]["score"] = "999"
        write_csv_rows(self.lexical_ranking, RANKING_FIELDS, rows)
        with self.assertRaisesRegex(ValueError, "artifact hash"):
            analyze_w5_errors(
                [self.lexical_manifest],
                benchmark_manifest_path=self.root / "missing-benchmark.json",
                taxonomy_mapping_path=TAXONOMY_MAPPING,
                taxonomy_source_path=TAXONOMY_SOURCE,
                project_root=PROJECT_ROOT,
            )

    def test_unknown_duplicate_and_rq_mismatch_fail_closed(self) -> None:
        mutations = {
            "unknown": lambda rows: rows[0].__setitem__("pair_id", "w4_unknown_001"),
            "duplicate": lambda rows: rows[1].__setitem__("pair_id", rows[0]["pair_id"]),
            "rq_mismatch": lambda rows: rows[0].__setitem__(
                "research_query_id", "rq02_stellar_parameters"
            ),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                manifest, _ranking = self._create_package(
                    package_name=f"invalid-{name}",
                    fixture_name="lexical_fixture.csv",
                    method_id=f"fixture_{name}_v1",
                    family="sparse",
                )
                self._mutate_ranking(manifest, mutation)
                with self.assertRaises(ValueError):
                    self._analyze([manifest])

    def test_zero_manifests_and_duplicate_method_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "至少需要一个"):
            analyze_w5_errors(
                [],
                benchmark_manifest_path=BENCHMARK_MANIFEST,
                taxonomy_mapping_path=TAXONOMY_MAPPING,
                taxonomy_source_path=TAXONOMY_SOURCE,
                project_root=PROJECT_ROOT,
            )
        duplicate_manifest, _ranking = self._create_package(
            package_name="duplicate-method",
            fixture_name="lexical_fixture.csv",
            method_id="fixture_lexical_v1",
            family="sparse",
        )
        with self.assertRaisesRegex(ValueError, "method_id 必须唯一"):
            self._analyze([self.lexical_manifest, duplicate_manifest])

    def test_tampered_taxonomy_mapping_is_rejected(self) -> None:
        tampered = self.root / "tampered_mapping.csv"
        _fields, rows = read_csv_rows(TAXONOMY_MAPPING)
        rows[0]["pair_id"] = "w4_unknown_001"
        write_csv_rows(tampered, TAXONOMY_MAPPING_FIELDS, rows)
        with self.assertRaisesRegex(ValueError, "确定性转换"):
            analyze_w5_errors(
                [self.lexical_manifest],
                benchmark_manifest_path=BENCHMARK_MANIFEST,
                taxonomy_mapping_path=tampered,
                taxonomy_source_path=TAXONOMY_SOURCE,
                project_root=PROJECT_ROOT,
            )

    def test_tampered_w4_taxonomy_source_is_rejected(self) -> None:
        tampered_source = self.root / "tampered_w4_source.csv"
        shutil.copyfile(TAXONOMY_SOURCE, tampered_source)
        with tampered_source.open("a", encoding="utf-8", newline="") as handle:
            handle.write("\n")
        with self.assertRaisesRegex(ValueError, "frozen evidence"):
            analyze_w5_errors(
                [self.lexical_manifest],
                benchmark_manifest_path=BENCHMARK_MANIFEST,
                taxonomy_mapping_path=TAXONOMY_MAPPING,
                taxonomy_source_path=tampered_source,
                project_root=PROJECT_ROOT,
            )

    def test_outputs_are_deterministic_regardless_of_manifest_order(self) -> None:
        first = render_analysis_outputs(
            self._analyze([self.lexical_manifest, self.dense_manifest])
        )
        second = render_analysis_outputs(
            self._analyze([self.dense_manifest, self.lexical_manifest])
        )
        self.assertEqual(first, second)
        self.assertEqual(set(first), {
            "analysis_summary.json",
            "pair_analysis.csv",
            "method_error_type_matrix.csv",
            "error_cases.csv",
            "rank_shifts.csv",
            "coverage.csv",
        })
        error_fields = next(csv.reader(io.StringIO(first["error_cases.csv"])))
        self.assertEqual(error_fields, ERROR_CASE_FIELDS)

    def test_analysis_does_not_modify_inputs(self) -> None:
        inputs = [
            self.lexical_manifest,
            self.lexical_ranking,
            self.dense_manifest,
            self.dense_ranking,
            BENCHMARK_MANIFEST,
            TAXONOMY_SOURCE,
            TAXONOMY_MAPPING,
        ]
        before = {path: sha256_file(path) for path in inputs}
        self._analyze([self.lexical_manifest, self.dense_manifest])
        after = {path: sha256_file(path) for path in inputs}
        self.assertEqual(before, after)

    def test_src_import_has_no_application_side_effects(self) -> None:
        import_dir = self.root / "import-only"
        import_dir.mkdir()
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        completed = subprocess.run(
            [sys.executable, "-c", "import src.w5_error_analysis"],
            cwd=import_dir,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(list(import_dir.iterdir()), [])

    def test_cli_writes_complete_output_set(self) -> None:
        output_dir = self.root / "cli-output"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = analyze_cli_main(
                [
                    "--manifest",
                    str(self.lexical_manifest),
                    "--manifest",
                    str(self.dense_manifest),
                    "--output-dir",
                    str(output_dir),
                ]
            )
        self.assertEqual(exit_code, 0, stdout.getvalue())
        self.assertEqual(
            {path.name for path in output_dir.iterdir()},
            {
                "analysis_summary.json",
                "pair_analysis.csv",
                "method_error_type_matrix.csv",
                "error_cases.csv",
                "rank_shifts.csv",
                "coverage.csv",
            },
        )
        self.assertFalse(any(path.name.endswith(".tmp") for path in output_dir.iterdir()))

    def test_cli_invalid_input_writes_nothing(self) -> None:
        rows = read_csv_rows(self.lexical_ranking)[1]
        rows[0]["score"] = "999"
        write_csv_rows(self.lexical_ranking, RANKING_FIELDS, rows)
        output_dir = self.root / "must-not-exist"
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = analyze_cli_main(
                [
                    "--manifest",
                    str(self.lexical_manifest),
                    "--output-dir",
                    str(output_dir),
                ]
            )
        self.assertEqual(exit_code, 1)
        self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
