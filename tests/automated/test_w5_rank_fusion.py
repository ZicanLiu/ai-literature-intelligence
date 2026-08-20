"""W5 通用 RRF 混合排序融合测试。

覆盖：两个合法 fixture、多输入、RRF 数学结果、k=60、确定性并列、identical ranks、
输入 method_id 重复、pair identity 不一致、RQ 不一致、invalid manifest、artifact hash、
输出 W5 validator PASS、不访问 label。
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from app.fuse_w5_rankings import main as fuse_cli_main
from app.validate_w5_method import main as validate_cli_main
from src.annotation_tasks import read_csv_rows, sha256_file
from src.w5_method_contract import RANKING_FIELDS, validate_method_output
from src.w5_rank_fusion import (
    RRF_K,
    RRF_ORDER_SEMANTIC,
    compute_rrf_score,
    fuse_rankings,
    validate_fusion_inputs,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "w5_method_contract"
BASE_REVISION = "d558a0888e4c71a9d001a67e0640d28394b6ac88"


class FusionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def _create_package(
        self,
        package_name: str,
        fixture_name: str,
        method_id: str,
        family: str,
        *,
        rewrite_method_id: bool = False,
    ) -> tuple[Path, Path]:
        package_dir = self.root / package_name
        package_dir.mkdir(parents=True)
        ranking_path = package_dir / "ranking.csv"
        shutil.copyfile(FIXTURE_DIR / fixture_name, ranking_path)
        if rewrite_method_id:
            fields, rows = read_csv_rows(ranking_path)
            for row in rows:
                row["method_id"] = method_id
            _write_rows(ranking_path, rows)
        model = None
        if family in {"dense", "neural"}:
            model = {"name": "fixture-encoder", "revision": "fixture-v1", "adapter": None}
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

    def _validated_package(
        self,
        package_name: str,
        fixture_name: str,
        method_id: str,
        family: str,
        *,
        rewrite_method_id: bool = False,
    ) -> dict:
        manifest_path, _ = self._create_package(
            package_name,
            fixture_name,
            method_id,
            family,
            rewrite_method_id=rewrite_method_id,
        )
        return validate_method_output(manifest_path, project_root=PROJECT_ROOT)


def _write_rows(path: Path, rows: list[dict]) -> None:
    import csv

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RANKING_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in RANKING_FIELDS})


def _fake_package(
    *,
    method_id: str,
    manifest_hash: str,
    ranking_hash: str,
    pairs: list[tuple[str, str, int]],
    candidate_pool: str = "pool.csv",
    research_queries: str = "rq.json",
) -> dict:
    return {
        "method_id": method_id,
        "manifest_sha256": manifest_hash,
        "ranking_sha256": ranking_hash,
        "ranking_rows": [
            {
                "pair_id": pair_id,
                "research_query_id": query_id,
                "method_id": method_id,
                "score": float(rank),
                "rank": rank,
            }
            for pair_id, query_id, rank in pairs
        ],
        "candidate_pool_path": candidate_pool,
        "research_queries_path": research_queries,
    }


class RrfMathTests(unittest.TestCase):
    def test_k_is_fixed_60(self) -> None:
        self.assertEqual(RRF_K, 60)

    def test_single_rank_score_is_exact(self) -> None:
        self.assertEqual(compute_rrf_score([1], k=60), Fraction(1, 61))

    def test_two_rank_score_is_exact(self) -> None:
        self.assertEqual(compute_rrf_score([1, 20], k=60), Fraction(141, 4880))

    def test_rrf_is_commutative(self) -> None:
        self.assertEqual(
            compute_rrf_score([1, 20, 5], k=60),
            compute_rrf_score([20, 5, 1], k=60),
        )


class FusionPositiveTests(FusionTestCase):
    def test_two_fixtures_fuse_deterministically(self) -> None:
        lexical = self._validated_package(
            "lexical", "lexical_fixture.csv", "fixture_lexical_v1", "sparse"
        )
        dense = self._validated_package(
            "dense", "dense_fixture.csv", "fixture_dense_v1", "dense"
        )
        result_a = fuse_rankings([lexical, dense], output_method_id="rrf_hybrid_v1")
        result_b = fuse_rankings([lexical, dense], output_method_id="rrf_hybrid_v1")
        self.assertEqual(len(result_a["rows"]), 60)
        self.assertEqual(result_a["rows"], result_b["rows"])
        self.assertEqual(result_a["rrf_k"], 60)
        self.assertEqual(
            result_a["input_method_ids"],
            ["fixture_lexical_v1", "fixture_dense_v1"],
        )
        self.assertEqual(result_a["input_order_semantic"], RRF_ORDER_SEMANTIC)

    def test_symmetric_tie_is_broken_by_pair_id(self) -> None:
        lexical = self._validated_package(
            "lexical", "lexical_fixture.csv", "fixture_lexical_v1", "sparse"
        )
        dense = self._validated_package(
            "dense", "dense_fixture.csv", "fixture_dense_v1", "dense"
        )
        result = fuse_rankings([lexical, dense], output_method_id="rrf_hybrid_v1")
        by_pair = {row["pair_id"]: row for row in result["rows"]}
        self.assertAlmostEqual(
            by_pair["w4_rq01_001"]["score"],
            by_pair["w4_rq01_020"]["score"],
            places=12,
        )
        self.assertEqual(by_pair["w4_rq01_001"]["rank"], 1)
        self.assertEqual(by_pair["w4_rq01_020"]["rank"], 2)
        self.assertEqual(by_pair["w4_rq01_010"]["rank"], 19)
        self.assertEqual(by_pair["w4_rq01_011"]["rank"], 20)

    def test_identical_ranks_preserve_order(self) -> None:
        first = self._validated_package(
            "lex_a", "lexical_fixture.csv", "fixture_lexical_v1", "sparse"
        )
        second = self._validated_package(
            "lex_b",
            "lexical_fixture.csv",
            "fixture_lexical_b_v1",
            "sparse",
            rewrite_method_id=True,
        )
        result = fuse_rankings([first, second], output_method_id="rrf_hybrid_v1")
        by_pair = {row["pair_id"]: row for row in result["rows"]}
        self.assertEqual(by_pair["w4_rq01_001"]["rank"], 1)
        self.assertEqual(by_pair["w4_rq01_020"]["rank"], 20)

    def test_multi_input_fusion_sums_three_terms(self) -> None:
        lexical = self._validated_package(
            "lexical", "lexical_fixture.csv", "fixture_lexical_v1", "sparse"
        )
        dense = self._validated_package(
            "dense", "dense_fixture.csv", "fixture_dense_v1", "dense"
        )
        dense_b = self._validated_package(
            "dense_b",
            "dense_fixture.csv",
            "fixture_dense_b_v1",
            "dense",
            rewrite_method_id=True,
        )
        result = fuse_rankings(
            [lexical, dense, dense_b], output_method_id="rrf_hybrid_v1"
        )
        self.assertEqual(len(result["rows"]), 60)
        self.assertEqual(len(result["input_method_ids"]), 3)
        by_pair = {row["pair_id"]: row for row in result["rows"]}
        # w4_rq01_001: lexical rank 1, dense rank 20, dense_b rank 20
        expected = Fraction(1, 61) + Fraction(1, 80) + Fraction(1, 80)
        self.assertAlmostEqual(by_pair["w4_rq01_001"]["score"], float(expected), places=12)

    def test_output_package_passes_w5_validator(self) -> None:
        lexical = self._validated_package(
            "lexical", "lexical_fixture.csv", "fixture_lexical_v1", "sparse"
        )
        dense = self._validated_package(
            "dense", "dense_fixture.csv", "fixture_dense_v1", "dense"
        )
        result = fuse_rankings([lexical, dense], output_method_id="rrf_hybrid_v1")

        out_dir = self.root / "hybrid_out"
        out_dir.mkdir()
        ranking_path = out_dir / "ranking.csv"
        _write_rows(ranking_path, result["rows"])
        manifest = {
            "schema_version": "1.0",
            "contract_name": "w5_method_ranking",
            "contract_version": "1.0",
            "artifact_type": "method_ranking",
            "method": {
                "method_id": "rrf_hybrid_v1",
                "display_name": "rrf hybrid v1",
                "family": "hybrid",
                "parameters": {
                    "rrf_k": result["rrf_k"],
                    "input_method_ids": result["input_method_ids"],
                    "input_manifest_sha256": result["input_manifest_sha256"],
                    "input_ranking_sha256": result["input_ranking_sha256"],
                    "input_order_semantic": result["input_order_semantic"],
                },
                "model": None,
            },
            "inputs": lexical["manifest"]["inputs"],
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
                "platform": {"system": "fixture", "release": "fixture", "machine": "fixture"},
                "dependencies": {},
            },
            "label_access": {
                "benchmark_labels_read": False,
                "declaration": "RRF fusion without benchmark labels.",
            },
        }
        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        validated = validate_method_output(manifest_path, project_root=PROJECT_ROOT)
        self.assertEqual(validated["method_id"], "rrf_hybrid_v1")
        self.assertEqual(len(validated["ranking_rows"]), 60)
        self.assertEqual(
            validated["counts_by_query"]["rq01_stellar_classification"], 20
        )


class FusionValidationTests(FusionTestCase):
    def _two_valid_fixture_packages(self) -> list[dict]:
        lexical = self._validated_package(
            "lexical", "lexical_fixture.csv", "fixture_lexical_v1", "sparse"
        )
        dense = self._validated_package(
            "dense", "dense_fixture.csv", "fixture_dense_v1", "dense"
        )
        return [lexical, dense]

    def test_single_input_is_rejected(self) -> None:
        lexical = self._validated_package(
            "lexical", "lexical_fixture.csv", "fixture_lexical_v1", "sparse"
        )
        with self.assertRaisesRegex(ValueError, "至少需要两个"):
            fuse_rankings([lexical], output_method_id="rrf_hybrid_v1")

    def test_duplicate_method_id_is_rejected(self) -> None:
        a = _fake_package(
            method_id="dup_v1",
            manifest_hash="a" * 64,
            ranking_hash="b" * 64,
            pairs=[("p1", "q1", 1), ("p2", "q1", 2)],
        )
        b = _fake_package(
            method_id="dup_v1",
            manifest_hash="c" * 64,
            ranking_hash="d" * 64,
            pairs=[("p1", "q1", 1), ("p2", "q1", 2)],
        )
        with self.assertRaisesRegex(ValueError, "method_id 重复"):
            validate_fusion_inputs([a, b])

    def test_same_artifact_twice_is_rejected(self) -> None:
        a = _fake_package(
            method_id="m_a",
            manifest_hash="e" * 64,
            ranking_hash="f" * 64,
            pairs=[("p1", "q1", 1)],
        )
        b = _fake_package(
            method_id="m_b",
            manifest_hash="e" * 64,
            ranking_hash="g" * 64,
            pairs=[("p1", "q1", 1)],
        )
        with self.assertRaisesRegex(ValueError, "重复融合"):
            validate_fusion_inputs([a, b])

    def test_pair_identity_mismatch_is_rejected(self) -> None:
        a = _fake_package(
            method_id="m_a",
            manifest_hash="h" * 64,
            ranking_hash="i" * 64,
            pairs=[("p1", "q1", 1), ("p2", "q1", 2)],
        )
        b = _fake_package(
            method_id="m_b",
            manifest_hash="j" * 64,
            ranking_hash="k" * 64,
            pairs=[("p1", "q1", 1), ("p3", "q1", 2)],
        )
        with self.assertRaisesRegex(ValueError, "pair identity"):
            validate_fusion_inputs([a, b])

    def test_research_query_mismatch_is_rejected(self) -> None:
        a = _fake_package(
            method_id="m_a",
            manifest_hash="l" * 64,
            ranking_hash="m" * 64,
            pairs=[("p1", "q1", 1)],
        )
        b = _fake_package(
            method_id="m_b",
            manifest_hash="n" * 64,
            ranking_hash="o" * 64,
            pairs=[("p1", "q2", 1)],
        )
        with self.assertRaisesRegex(ValueError, "pair identity"):
            validate_fusion_inputs([a, b])

    def test_candidate_pool_mismatch_is_rejected(self) -> None:
        a = _fake_package(
            method_id="m_a",
            manifest_hash="p" * 64,
            ranking_hash="q" * 64,
            pairs=[("p1", "q1", 1)],
            candidate_pool="pool_a.csv",
        )
        b = _fake_package(
            method_id="m_b",
            manifest_hash="r" * 64,
            ranking_hash="s" * 64,
            pairs=[("p1", "q1", 1)],
            candidate_pool="pool_b.csv",
        )
        with self.assertRaisesRegex(ValueError, "Candidate Pool"):
            validate_fusion_inputs([a, b])


class FusionCliTests(FusionTestCase):
    def test_cli_fuses_two_packages_and_self_validates(self) -> None:
        lexical_manifest, _ = self._create_package(
            "lexical", "lexical_fixture.csv", "fixture_lexical_v1", "sparse"
        )
        dense_manifest, _ = self._create_package(
            "dense", "dense_fixture.csv", "fixture_dense_v1", "dense"
        )
        out_dir = self.root / "cli_out"
        output = io.StringIO()
        with patch(
            "app.fuse_w5_rankings._git_revision", return_value=BASE_REVISION
        ), patch("app.fuse_w5_rankings._git_worktree_clean", return_value=True):
            with contextlib.redirect_stdout(output):
                exit_code = fuse_cli_main(
                    [
                        "--manifest",
                        str(lexical_manifest),
                        "--manifest",
                        str(dense_manifest),
                        "--method-id",
                        "rrf_hybrid_cli_v1",
                        "--output-dir",
                        str(out_dir),
                    ]
                )
        self.assertEqual(exit_code, 0, output.getvalue())
        self.assertTrue((out_dir / "ranking.csv").is_file())
        self.assertTrue((out_dir / "manifest.json").is_file())
        # 输出可通过 validator CLI 验证
        validate_out = io.StringIO()
        with contextlib.redirect_stdout(validate_out):
            code = validate_cli_main(["--manifest", str(out_dir / "manifest.json")])
        self.assertEqual(code, 0, validate_out.getvalue())
        self.assertIn("rrf_hybrid_cli_v1", validate_out.getvalue())

    def test_cli_rejects_invalid_manifest(self) -> None:
        missing = self.root / "nope" / "manifest.json"
        out_dir = self.root / "out"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = fuse_cli_main(
                [
                    "--manifest",
                    str(missing),
                    "--manifest",
                    str(missing),
                    "--method-id",
                    "rrf_hybrid_v1",
                    "--output-dir",
                    str(out_dir),
                ]
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("校验失败", output.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
