"""W5 Method Ranking Contract, validator CLI and evaluator-adapter tests."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.validate_w5_method import main as validate_cli_main
from src.annotation_tasks import (
    load_research_queries,
    read_csv_rows,
    sha256_file,
    write_csv_rows,
)
from src.w4_benchmark_evaluation import evaluate_contract_ranking
from src.w5_method_contract import RANKING_FIELDS, validate_method_output


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "w5_method_contract"
CANDIDATE_POOL = (
    PROJECT_ROOT / "data" / "annotation_tasks" / "w4" / "candidate_pool_v0.1.csv"
)
RESEARCH_QUERIES = PROJECT_ROOT / "configs" / "w4" / "research_queries.json"
BASE_REVISION = "d558a0888e4c71a9d001a67e0640d28394b6ac88"


class MethodContractTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.manifest_path, self.ranking_path = self._create_package(
            package_name="lexical",
            fixture_name="lexical_fixture.csv",
            method_id="fixture_lexical_v1",
            family="sparse",
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

    def _load_manifest(self) -> dict:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def _save_manifest(self, manifest: dict) -> None:
        self.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _load_rows(self) -> list[dict[str, str]]:
        return read_csv_rows(self.ranking_path)[1]

    def _save_rows(
        self,
        rows: list[dict[str, str]],
        *,
        fields: list[str] | None = None,
        refresh_manifest_hash: bool = True,
    ) -> None:
        write_csv_rows(self.ranking_path, fields or RANKING_FIELDS, rows)
        if refresh_manifest_hash:
            manifest = self._load_manifest()
            manifest["ranking"]["sha256"] = sha256_file(self.ranking_path)
            self._save_manifest(manifest)


class MethodContractPositiveTests(MethodContractTestCase):
    def test_lexical_fixture_is_valid_and_ties_are_deterministic(self) -> None:
        result = validate_method_output(
            self.manifest_path,
            project_root=PROJECT_ROOT,
        )
        self.assertEqual(result["method_id"], "fixture_lexical_v1")
        self.assertEqual(len(result["ranking_rows"]), 60)
        self.assertEqual(
            result["counts_by_query"],
            {
                "rq01_stellar_classification": 20,
                "rq02_stellar_parameters": 20,
                "rq03_spectral_preprocessing": 20,
            },
        )

    def test_dense_fixture_uses_the_same_contract(self) -> None:
        manifest_path, _ranking_path = self._create_package(
            package_name="dense",
            fixture_name="dense_fixture.csv",
            method_id="fixture_dense_v1",
            family="dense",
        )
        result = validate_method_output(manifest_path, project_root=PROJECT_ROOT)
        self.assertEqual(result["method_id"], "fixture_dense_v1")
        self.assertEqual(len(result["ranking_rows"]), 60)

    def test_cli_validates_package(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = validate_cli_main(["--manifest", str(self.manifest_path)])
        self.assertEqual(exit_code, 0)
        self.assertIn("fixture_lexical_v1", output.getvalue())
        self.assertIn("pairs=60", output.getvalue())


class MethodContractNegativeTests(MethodContractTestCase):
    def test_missing_pair_and_wrong_total_are_rejected(self) -> None:
        rows = self._load_rows()
        rows.pop()
        self._save_rows(rows)
        with self.assertRaisesRegex(ValueError, "缺失冻结 pair"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_unknown_pair_is_rejected(self) -> None:
        rows = self._load_rows()
        rows[0]["pair_id"] = "w4_unknown_001"
        self._save_rows(rows)
        with self.assertRaisesRegex(ValueError, "未知 pair"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_duplicate_pair_is_rejected(self) -> None:
        rows = self._load_rows()
        rows[1]["pair_id"] = rows[0]["pair_id"]
        self._save_rows(rows)
        with self.assertRaisesRegex(ValueError, "duplicate pair"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_research_query_mismatch_is_rejected(self) -> None:
        rows = self._load_rows()
        rows[0]["research_query_id"] = "rq02_stellar_parameters"
        self._save_rows(rows)
        with self.assertRaisesRegex(ValueError, "Candidate Pool 不一致"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_mixed_method_id_is_rejected(self) -> None:
        rows = self._load_rows()
        rows[0]["method_id"] = "another_method"
        self._save_rows(rows)
        with self.assertRaisesRegex(ValueError, "method_id 不统一"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_non_finite_score_is_rejected(self) -> None:
        rows = self._load_rows()
        rows[0]["score"] = "NaN"
        self._save_rows(rows)
        with self.assertRaisesRegex(ValueError, "有限数值"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_missing_rank_is_rejected(self) -> None:
        rows = self._load_rows()
        rows[0]["rank"] = ""
        self._save_rows(rows)
        with self.assertRaisesRegex(ValueError, "rank 必须是规范正整数"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_duplicate_rank_is_rejected(self) -> None:
        rows = self._load_rows()
        rows[2]["rank"] = rows[1]["rank"]
        self._save_rows(rows)
        with self.assertRaisesRegex(ValueError, "完整且唯一覆盖"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_score_rank_order_is_rejected(self) -> None:
        rows = self._load_rows()
        rows[2]["rank"], rows[4]["rank"] = rows[4]["rank"], rows[2]["rank"]
        self._save_rows(rows)
        with self.assertRaisesRegex(ValueError, "score/rank"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_tie_break_order_is_rejected(self) -> None:
        rows = self._load_rows()
        rows[0]["rank"], rows[1]["rank"] = rows[1]["rank"], rows[0]["rank"]
        self._save_rows(rows)
        with self.assertRaisesRegex(ValueError, "tie-breaking"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_frozen_input_hash_drift_is_rejected(self) -> None:
        manifest = self._load_manifest()
        manifest["inputs"]["candidate_pool"]["sha256"] = "0" * 64
        self._save_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "冻结 W4 v0.1 hash"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_ranking_hash_mismatch_is_rejected(self) -> None:
        rows = self._load_rows()
        rows[0]["score"] = "99.0"
        self._save_rows(rows, refresh_manifest_hash=False)
        with self.assertRaisesRegex(ValueError, "artifact hash"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_forbidden_benchmark_field_is_rejected(self) -> None:
        rows = self._load_rows()
        for row in rows:
            row["final_label"] = ""
        self._save_rows(rows, fields=RANKING_FIELDS + ["final_label"])
        with self.assertRaisesRegex(ValueError, "禁止字段"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_schema_version_mismatch_is_rejected(self) -> None:
        manifest = self._load_manifest()
        manifest["schema_version"] = "2.0"
        self._save_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "schema_version"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_label_access_declaration_must_be_false(self) -> None:
        manifest = self._load_manifest()
        manifest["label_access"]["benchmark_labels_read"] = True
        self._save_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "未读取 approved benchmark labels"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)

    def test_formal_output_must_declare_clean_generation(self) -> None:
        manifest = self._load_manifest()
        manifest["generation"]["git_worktree_clean"] = False
        self._save_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "clean Git"):
            validate_method_output(self.manifest_path, project_root=PROJECT_ROOT)


class ContractEvaluationAdapterTests(MethodContractTestCase):
    def test_adapter_consumes_validated_artifact_without_method_hardcoding(self) -> None:
        package = validate_method_output(
            self.manifest_path,
            project_root=PROJECT_ROOT,
        )
        pool_rows = read_csv_rows(CANDIDATE_POOL)[1]
        research_queries = load_research_queries(RESEARCH_QUERIES)
        labels = {row["pair_id"]: "2" for row in pool_rows}
        result = evaluate_contract_ranking(
            pool_rows=pool_rows,
            labels=labels,
            research_queries=research_queries,
            method_package=package,
        )
        self.assertEqual(result["method_id"], "fixture_lexical_v1")
        self.assertEqual(len(result["per_query"]), 3)
        for query_result in result["per_query"].values():
            self.assertEqual(query_result["pair_count"], 20)
            self.assertEqual(query_result["labeled_count"], 20)
            self.assertEqual(query_result["metrics"]["ndcg_at_5"], 1.0)
        self.assertEqual(result["macro"]["precision_at_10"], 1.0)

    def test_adapter_rejects_unvalidated_shape(self) -> None:
        pool_rows = read_csv_rows(CANDIDATE_POOL)[1]
        with self.assertRaisesRegex(ValueError, "validator"):
            evaluate_contract_ranking(
                pool_rows=pool_rows,
                labels={},
                research_queries=load_research_queries(RESEARCH_QUERIES),
                method_package={"method_id": "x"},
            )


if __name__ == "__main__":
    unittest.main()
