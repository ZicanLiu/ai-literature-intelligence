"""W6 标准化分数融合的离线回归测试（Issue #65 Part A）。"""

from __future__ import annotations

import copy
import csv
import io
import json
import math
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from app import fuse_w6_scores
from src.annotation_tasks import sha256_file, write_csv_rows
from src.w5_method_contract import RANKING_FIELDS
from src.w6_contracts import load_json_object, validate_w6_bootstrap_bundle
from src.w6_method_contract import (
    compute_method_configuration_hash,
    validate_w6_method_package,
)
from src.w6_score_fusion import (
    fuse_method_rankings,
    normalize_scores,
    validate_fusion_input_packages,
)
from src.w6_task_context import (
    GENERATION_ARTIFACT_NAMES,
    LABEL_AWARE_ARTIFACT_NAMES,
    load_w6_generation_context,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap"
VALID_ROOT = FIXTURE_ROOT / "valid"
BUNDLE_PATH = VALID_ROOT / "bundle_manifest.json"
CONFIG_PATH = PROJECT_ROOT / "configs" / "w6" / "score_fusion_primary.json"
FAKE_GIT_REVISION = "6b9eb12f898bf880c297902463e48f2ff3e0388b"


class NormalizeScoresTests(unittest.TestCase):
    def test_z_score_values(self) -> None:
        result = normalize_scores([1.0, 2.0, 3.0], "z_score")
        expected = [-1.224744871391589, 0.0, 1.224744871391589]
        for actual, want in zip(result, expected):
            self.assertAlmostEqual(actual, want, places=12)

    def test_min_max_values(self) -> None:
        self.assertEqual(normalize_scores([1.0, 2.0, 3.0], "min_max"), [0.0, 0.5, 1.0])

    def test_robust_values(self) -> None:
        # median=3，Tukey exclusive hinges Q1=1.5/Q3=4.5，IQR=3。
        result = normalize_scores([1.0, 2.0, 3.0, 4.0, 5.0], "robust")
        expected = [-2 / 3, -1 / 3, 0.0, 1 / 3, 2 / 3]
        for actual, want in zip(result, expected):
            self.assertAlmostEqual(actual, want, places=12)

    def test_z_score_zero_variance(self) -> None:
        self.assertEqual(normalize_scores([4.0, 4.0, 4.0], "z_score"), [0.0, 0.0, 0.0])

    def test_min_max_zero_variance(self) -> None:
        self.assertEqual(normalize_scores([4.0, 4.0], "min_max"), [0.5, 0.5])

    def test_robust_zero_iqr(self) -> None:
        self.assertEqual(normalize_scores([7.0, 7.0, 7.0, 7.0], "robust"), [0.0] * 4)

    def test_negative_scores(self) -> None:
        self.assertEqual(normalize_scores([-5.0, -1.0], "min_max"), [0.0, 1.0])
        result = normalize_scores([-2.0, -1.0], "z_score")
        self.assertAlmostEqual(result[0], -1.0, places=12)
        self.assertAlmostEqual(result[1], 1.0, places=12)

    def test_non_finite_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "有限"):
            normalize_scores([1.0, float("nan")], "z_score")
        with self.assertRaisesRegex(ValueError, "有限"):
            normalize_scores([float("inf"), 1.0], "min_max")

    def test_unknown_strategy_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "normalization 策略"):
            normalize_scores([1.0], "sigmoid")

    def test_empty_input_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能为空"):
            normalize_scores([], "z_score")

    # ---- 极端但合法的 finite 输入（P1-3 回归） ----

    def test_singleton_all_strategies(self) -> None:
        # 合法 W6 cardinality 允许单候选 topic；singleton 不得崩溃。
        self.assertEqual(normalize_scores([5.0], "z_score"), [0.0])
        self.assertEqual(normalize_scores([5.0], "min_max"), [0.5])
        self.assertEqual(normalize_scores([5.0], "robust"), [0.0])

    def test_extreme_finite_values(self) -> None:
        extreme = [1e308, -1e308]
        self.assertEqual(normalize_scores(extreme, "min_max"), [1.0, 0.0])
        result = normalize_scores(extreme, "z_score")
        self.assertAlmostEqual(result[0], 1.0, places=12)
        self.assertAlmostEqual(result[1], -1.0, places=12)
        result = normalize_scores(extreme, "robust")
        self.assertAlmostEqual(result[0], 0.5, places=12)
        self.assertAlmostEqual(result[1], -0.5, places=12)

    def test_extreme_span(self) -> None:
        result = normalize_scores([0.0, 1e308], "min_max")
        self.assertEqual(result, [0.0, 1.0])
        result = normalize_scores([0.0, 1e308], "robust")
        self.assertAlmostEqual(result[0], -0.5, places=12)
        self.assertAlmostEqual(result[1], 0.5, places=12)

    def test_extreme_variance_overflow_fallback(self) -> None:
        result = normalize_scores([1e307, -1e307, 1e307, -1e307], "z_score")
        for value in result:
            self.assertTrue(math.isfinite(value))
        self.assertAlmostEqual(result[0], 1.0, places=6)
        self.assertAlmostEqual(result[1], -1.0, places=6)


class W6ScoreFusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = validate_w6_bootstrap_bundle(BUNDLE_PATH)
        cls.registry = cls.bundle["registry"]
        cls.pool_members = cls.bundle["pool_members"]
        cls.paths = cls.bundle["paths"]

    def _validate_inputs(self, names=("method_sparse_manifest", "method_dense_manifest")):
        packages = []
        known = dict(self.bundle["method_packages"])
        for name in names:
            package = validate_w6_method_package(
                self.paths[name],
                artifact_registry=self.registry,
                pool_members=self.pool_members,
                known_method_packages=known,
            )
            packages.append(package)
            known[package["artifact_id"]] = package
        return packages

    def _fuse_fixtures(self, **overrides):
        packages = self._validate_inputs()
        kwargs = {
            "output_method_id": "w6_test_fusion",
            "strategy": "z_score",
            "fit_scope": "per_topic",
            "weights": {"w6_fixture_sparse_v1": 0.5, "w6_fixture_dense_v1": 0.5},
        }
        kwargs.update(overrides)
        return fuse_method_rankings(packages, **kwargs)

    def _write_and_validate_package(self, tmp_dir: Path, fusion, packages, method_id):
        ranking_path = tmp_dir / "ranking.csv"
        write_csv_rows(ranking_path, RANKING_FIELDS, fusion["rows"])
        ranking_sha256 = sha256_file(ranking_path)
        method_inputs = [
            {
                "method_id": package["method_id"],
                "manifest_artifact_id": package["artifact_id"],
                "manifest_sha256": package["manifest_sha256"],
                "ranking_sha256": package["ranking_sha256"],
                "uses_raw_score": True,
                "uses_rank": False,
            }
            for package in packages
        ]
        known = dict(self.bundle["method_packages"])
        known.update({package["artifact_id"]: package for package in packages})
        manifest = fuse_w6_scores.build_manifest(
            output_method_id=method_id,
            display_name="W6 Test Fusion",
            frozen_inputs={
                name: packages[0]["input_references"][name]
                for name in ("topic_set", "candidate_pool")
            },
            ranking_sha256=ranking_sha256,
            row_count=len(fusion["rows"]),
            fusion=fusion,
            method_inputs=method_inputs,
            git_revision=FAKE_GIT_REVISION,
        )
        manifest_path = tmp_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return validate_w6_method_package(
            manifest_path,
            artifact_registry=self.registry,
            pool_members=self.pool_members,
            known_method_packages=known,
        )

    def _make_third_package(self, root: Path) -> Path:
        """复制 fake_dense 为 method_id 不同、分数不同的第三个合法 package。"""
        source = VALID_ROOT / "method_rankings" / "fake_dense"
        target = root / "fake_dense_v2"
        shutil.copytree(source, target)
        rows = []
        with (target / "ranking.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                row["method_id"] = "w6_fixture_dense_v2"
                row["score"] = str(round(1.0 - float(row["score"]), 6))
                rows.append(row)
        by_topic: dict[str, list[dict]] = {}
        for row in rows:
            by_topic.setdefault(row["research_query_id"], []).append(row)
        ordered = []
        for topic_id in sorted(by_topic):
            topic_rows = sorted(
                by_topic[topic_id], key=lambda row: (-float(row["score"]), row["pair_id"])
            )
            for rank, row in enumerate(topic_rows, start=1):
                row["rank"] = str(rank)
                ordered.append(row)
        write_csv_rows(target / "ranking.csv", RANKING_FIELDS, ordered)
        manifest = load_json_object(target / "manifest.json")
        manifest["artifact_id"] = "w6_fixture_method_dense_v2"
        manifest["method"]["method_id"] = "w6_fixture_dense_v2"
        manifest["ranking"]["sha256"] = sha256_file(target / "ranking.csv")
        manifest["freeze"]["configuration_sha256"] = compute_method_configuration_hash(manifest)
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return target / "manifest.json"

    # ---- 输入校验 ----

    def test_two_fixture_inputs_accepted(self) -> None:
        packages = self._validate_inputs()
        validate_fusion_input_packages(packages)

    def test_single_input_rejected(self) -> None:
        packages = self._validate_inputs()[:1]
        with self.assertRaisesRegex(ValueError, "至少需要两个"):
            validate_fusion_input_packages(packages)

    def test_duplicate_method_rejected(self) -> None:
        packages = self._validate_inputs()
        with self.assertRaisesRegex(ValueError, "method_id 重复"):
            validate_fusion_input_packages([packages[0], packages[0]])

    def test_duplicate_ranking_rejected(self) -> None:
        packages = self._validate_inputs()
        twin = copy.deepcopy(packages[1])
        twin["method_id"] = "w6_fixture_dense_twin"
        twin["manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "同一 ranking artifact 被重复融合"):
            validate_fusion_input_packages([packages[1], twin])

    def test_pool_mismatch_rejected(self) -> None:
        packages = self._validate_inputs()
        drifted = copy.deepcopy(packages[1])
        drifted["input_references"]["candidate_pool"] = {
            "artifact_id": "w6_fixture_candidate_pool_v1",
            "sha256": "0" * 64,
        }
        with self.assertRaisesRegex(ValueError, "topic/pool artifact identity"):
            validate_fusion_input_packages([packages[0], drifted])

    def test_candidate_identity_mismatch_rejected(self) -> None:
        packages = self._validate_inputs()
        drifted = copy.deepcopy(packages[1])
        drifted["ranking_rows"] = drifted["ranking_rows"][1:]
        drifted["ranking_sha256"] = "1" * 64
        with self.assertRaisesRegex(ValueError, "candidate identity"):
            validate_fusion_input_packages([packages[0], drifted])

    # ---- 融合语义 ----

    def test_fused_scores_match_independent_computation(self) -> None:
        fusion = self._fuse_fixtures()
        scores = {row["pair_id"]: row["score"] for row in fusion["rows"]}
        # 独立手算：per-topic z-score 后 0.5/0.5 加权。
        self.assertAlmostEqual(scores["pool_denoise_001"], 1.00412178535489, places=12)
        self.assertAlmostEqual(scores["pool_denoise_003"], 1.0106323490797435, places=12)
        self.assertAlmostEqual(scores["pool_denoise_004"], -1.4573808237248866, places=12)

    def test_fused_ranking_shape_and_order(self) -> None:
        fusion = self._fuse_fixtures()
        rows = fusion["rows"]
        self.assertEqual(len(rows), 13)
        self.assertEqual({row["method_id"] for row in rows}, {"w6_test_fusion"})
        by_topic: dict[str, list[dict]] = {}
        for row in rows:
            by_topic.setdefault(row["research_query_id"], []).append(row)
        self.assertEqual({topic: len(items) for topic, items in by_topic.items()},
                         {"w6_fixture_topic_denoising": 7, "w6_fixture_topic_transients": 6})
        for topic_rows in by_topic.values():
            self.assertEqual([row["rank"] for row in topic_rows],
                             list(range(1, len(topic_rows) + 1)))
            ordered = sorted(topic_rows, key=lambda row: (-row["score"], row["pair_id"]))
            self.assertEqual([row["pair_id"] for row in topic_rows],
                             [row["pair_id"] for row in ordered])

    def test_deterministic_and_order_independent(self) -> None:
        first = self._fuse_fixtures()
        second = self._fuse_fixtures()
        self.assertEqual(first["rows"], second["rows"])
        reversed_packages = list(reversed(self._validate_inputs()))
        third = fuse_method_rankings(
            reversed_packages,
            output_method_id="w6_test_fusion",
            strategy="z_score",
            fit_scope="per_topic",
            weights={"w6_fixture_sparse_v1": 0.5, "w6_fixture_dense_v1": 0.5},
        )
        self.assertEqual(first["rows"], third["rows"])

    def test_tie_break_by_pair_id(self) -> None:
        def fake_package(method_id, sha_seed, scores):
            return {
                "method_id": method_id,
                "manifest_sha256": sha_seed,
                "ranking_sha256": sha_seed[::-1],
                "input_references": {
                    "topic_set": {"artifact_id": "t", "sha256": "a" * 64},
                    "candidate_pool": {"artifact_id": "p", "sha256": "b" * 64},
                },
                "ranking_rows": [
                    {
                        "pair_id": pair_id,
                        "research_query_id": "topic_x",
                        "method_id": method_id,
                        "score": score,
                        "rank": rank,
                    }
                    for rank, (pair_id, score) in enumerate(scores.items(), start=1)
                ],
            }

        packages = [
            fake_package("method_a", "1" * 64, {"item_a": 1.0, "item_b": 2.0}),
            fake_package("method_b", "2" * 64, {"item_a": 2.0, "item_b": 1.0}),
        ]
        fusion = fuse_method_rankings(
            packages,
            output_method_id="fusion_x",
            strategy="z_score",
            fit_scope="per_topic",
            weights={"method_a": 0.5, "method_b": 0.5},
        )
        # 两个 item 融合分相同（0.0），必须由 pair_id 字典序打破。
        self.assertEqual([row["pair_id"] for row in fusion["rows"]], ["item_a", "item_b"])
        self.assertEqual(fusion["rows"][0]["score"], fusion["rows"][1]["score"])

    def test_fit_scope_changes_normalization(self) -> None:
        per_topic = self._fuse_fixtures(fit_scope="per_topic")
        global_scope = self._fuse_fixtures(fit_scope="global_frozen_pool")
        self.assertNotEqual(
            [row["score"] for row in per_topic["rows"]],
            [row["score"] for row in global_scope["rows"]],
        )

    def test_min_max_and_robust_strategies_run(self) -> None:
        for strategy in ("min_max", "robust"):
            fusion = self._fuse_fixtures(strategy=strategy)
            self.assertEqual(len(fusion["rows"]), 13)
            self.assertEqual(fusion["strategy"], strategy)

    # ---- weights ----

    def test_weight_missing_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "精确覆盖"):
            self._fuse_fixtures(weights={"w6_fixture_sparse_v1": 1.0})

    def test_weight_extra_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "精确覆盖"):
            self._fuse_fixtures(
                weights={
                    "w6_fixture_sparse_v1": 0.5,
                    "w6_fixture_dense_v1": 0.5,
                    "w6_fixture_unknown": 0.1,
                }
            )

    def test_weight_non_finite_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "有限"):
            self._fuse_fixtures(
                weights={"w6_fixture_sparse_v1": float("nan"), "w6_fixture_dense_v1": 0.5}
            )

    def test_weight_bool_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "数值"):
            self._fuse_fixtures(
                weights={"w6_fixture_sparse_v1": True, "w6_fixture_dense_v1": 0.5}
            )

    # ---- 输出 package 过 W6 contract ----

    def test_output_package_passes_w6_contract(self) -> None:
        packages = self._validate_inputs()
        fusion = fuse_method_rankings(
            packages,
            output_method_id="w6_test_fusion",
            strategy="z_score",
            fit_scope="per_topic",
            weights={"w6_fixture_sparse_v1": 0.5, "w6_fixture_dense_v1": 0.5},
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = self._write_and_validate_package(
                Path(tmp), fusion, packages, "w6_test_fusion"
            )
        manifest = result["manifest"]
        self.assertEqual(manifest["method"]["family"], "hybrid")
        self.assertEqual(manifest["status"], "frozen")
        normalization = manifest["score_processing"]["normalization"]
        self.assertEqual(normalization["strategy"], "z_score")
        self.assertEqual(normalization["fit_scope"], "per_topic")
        self.assertIs(normalization["label_access"], False)
        self.assertEqual(
            set(manifest["method"]["parameters"]["weights"]),
            {"w6_fixture_sparse_v1", "w6_fixture_dense_v1"},
        )
        label_access = manifest["label_access"]
        self.assertIs(label_access["relevance_labels_read"], False)
        self.assertIs(label_access["hidden_test_labels_read"], False)
        self.assertEqual(len(manifest["method_inputs"]), 2)
        self.assertTrue(all(item["uses_raw_score"] for item in manifest["method_inputs"]))

    def test_three_method_inputs_pass_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            third_manifest = self._make_third_package(Path(tmp))
            packages = self._validate_inputs()
            known = dict(self.bundle["method_packages"])
            known.update({p["artifact_id"]: p for p in packages})
            third = validate_w6_method_package(
                third_manifest,
                artifact_registry=self.registry,
                pool_members=self.pool_members,
                known_method_packages=known,
            )
            packages.append(third)
            fusion = fuse_method_rankings(
                packages,
                output_method_id="w6_test_fusion3",
                strategy="z_score",
                fit_scope="per_topic",
                weights={
                    "w6_fixture_sparse_v1": 0.4,
                    "w6_fixture_dense_v1": 0.4,
                    "w6_fixture_dense_v2": 0.2,
                },
            )
            package_dir = Path(tmp) / "out3"
            package_dir.mkdir()
            result = self._write_and_validate_package(
                package_dir, fusion, packages, "w6_test_fusion3"
            )
            self.assertEqual(len(result["ranking_rows"]), 13)
            self.assertEqual(len(result["manifest"]["method_inputs"]), 3)

    # ---- 输入 artifact drift / label 禁令 ----

    def test_manifest_tamper_input_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "fake_sparse"
            shutil.copytree(VALID_ROOT / "method_rankings" / "fake_sparse", target)
            manifest = load_json_object(target / "manifest.json")
            manifest["method"]["display_name"] = "tampered"
            (target / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            # manifest 被篡改后 freeze.configuration_sha256 立即失效。
            with self.assertRaisesRegex(ValueError, "configuration hash mismatch"):
                validate_w6_method_package(
                    target / "manifest.json",
                    artifact_registry=self.registry,
                    pool_members=self.pool_members,
                    known_method_packages={},
                )

    def test_ranking_hash_drift_input_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "fake_sparse"
            shutil.copytree(VALID_ROOT / "method_rankings" / "fake_sparse", target)
            ranking_path = target / "ranking.csv"
            text = ranking_path.read_text(encoding="utf-8-sig")
            ranking_path.write_text(text.replace("9.0", "9.1", 1), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate_w6_method_package(
                    target / "manifest.json",
                    artifact_registry=self.registry,
                    pool_members=self.pool_members,
                    known_method_packages={},
                )

    def test_label_access_prohibited_in_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "fake_sparse"
            shutil.copytree(VALID_ROOT / "method_rankings" / "fake_sparse", target)
            manifest = load_json_object(target / "manifest.json")
            manifest["inputs"]["hidden_labels"] = {
                "artifact_id": "w6_fixture_hidden_anchor_v1",
                "sha256": self.registry["w6_fixture_hidden_anchor_v1"]["sha256"],
            }
            (target / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "禁止输入"):
                validate_w6_method_package(
                    target / "manifest.json",
                    artifact_registry=self.registry,
                    pool_members=self.pool_members,
                    known_method_packages={},
                )

    # ---- CLI ----

    def _run_cli(self, extra_args, output_dir: Path, *, reverse: bool = False,
                 bundle: Path | None = None) -> int:
        manifests = [
            str(self.paths["method_sparse_manifest"]),
            str(self.paths["method_dense_manifest"]),
        ]
        if reverse:
            manifests.reverse()
        argv = []
        if bundle is not None:
            argv += ["--bundle", str(bundle)]
        argv += [
            "--manifest",
            manifests[0],
            "--manifest",
            manifests[1],
            "--output-dir",
            str(output_dir),
            *extra_args,
        ]
        with mock.patch.object(
            fuse_w6_scores, "_git_revision", return_value=FAKE_GIT_REVISION
        ), mock.patch.object(
            fuse_w6_scores, "_git_worktree_clean", return_value=True
        ), redirect_stdout(io.StringIO()):
            return fuse_w6_scores.main(argv)

    def test_cli_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            rc = self._run_cli(["--method-id", "w6_cli_fusion"], output_dir)
            self.assertEqual(rc, 0)
            result = validate_w6_method_package(
                output_dir / "manifest.json",
                artifact_registry=self.registry,
                pool_members=self.pool_members,
                known_method_packages={
                    package["artifact_id"]: package
                    for package in self._validate_inputs()
                },
            )
            self.assertEqual(result["method_id"], "w6_cli_fusion")
            # 默认等权 0.5/0.5。
            self.assertEqual(
                result["manifest"]["method"]["parameters"]["weights"],
                {"w6_fixture_sparse_v1": 0.5, "w6_fixture_dense_v1": 0.5},
            )

    def test_cli_with_frozen_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            rc = self._run_cli(["--config", str(CONFIG_PATH)], output_dir)
            self.assertEqual(rc, 0)
            result = validate_w6_method_package(
                output_dir / "manifest.json",
                artifact_registry=self.registry,
                pool_members=self.pool_members,
                known_method_packages={
                    package["artifact_id"]: package
                    for package in self._validate_inputs()
                },
            )
            self.assertEqual(result["method_id"], "w6_zscore_fusion_fixture_v1")

    def test_cli_config_conflicts_with_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rc = self._run_cli(
                ["--config", str(CONFIG_PATH), "--method-id", "w6_other"], Path(tmp) / "out"
            )
            self.assertEqual(rc, 1)

    def test_cli_config_hash_tamper_rejected(self) -> None:
        config = load_json_object(CONFIG_PATH)
        config["weights"]["w6_fixture_dense_v1"] = 0.9
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "configuration_sha256"):
                fuse_w6_scores.load_fusion_config(config_path)

    def test_cli_requires_two_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            argv = [
                "--manifest",
                str(self.paths["method_sparse_manifest"]),
                "--method-id",
                "w6_cli_fusion",
                "--output-dir",
                str(Path(tmp) / "out"),
            ]
            with redirect_stdout(io.StringIO()):
                rc = fuse_w6_scores.main(argv)
            self.assertEqual(rc, 1)

    def test_cli_rejects_nonempty_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            (output_dir / "junk.txt").write_text("x", encoding="utf-8")
            rc = self._run_cli(["--method-id", "w6_cli_fusion"], output_dir)
            self.assertEqual(rc, 1)

    def test_cli_rejects_bad_weight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rc = self._run_cli(
                [
                    "--method-id",
                    "w6_cli_fusion",
                    "--weight",
                    "w6_fixture_sparse_v1=0.5",
                    "--weight",
                    "w6_fixture_dense_v1=not_a_number",
                ],
                Path(tmp) / "out",
            )
            self.assertEqual(rc, 1)

    def test_cli_rejects_unknown_weight_method(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rc = self._run_cli(
                [
                    "--method-id",
                    "w6_cli_fusion",
                    "--weight",
                    "w6_fixture_sparse_v1=0.5",
                    "--weight",
                    "w6_fixture_unknown=0.5",
                ],
                Path(tmp) / "out",
            )
            self.assertEqual(rc, 1)

    # ---- P1-3 / P1-4 / P1-2 回归 ----

    def test_singleton_topic_fusion(self) -> None:
        for strategy in ("z_score", "min_max", "robust"):
            packages = [
                _fake_package("method_a", "3" * 64, [("only_item", "topic_x", 2.0)]),
                _fake_package("method_b", "4" * 64, [("only_item", "topic_x", 0.5)]),
            ]
            fusion = fuse_method_rankings(
                packages,
                output_method_id="fusion_x",
                strategy=strategy,
                fit_scope="per_topic",
                weights={"method_a": 0.5, "method_b": 0.5},
            )
            self.assertEqual(len(fusion["rows"]), 1)
            self.assertEqual(fusion["rows"][0]["rank"], 1)
            self.assertTrue(math.isfinite(fusion["rows"][0]["score"]))

    def test_fused_score_overflow_rejected(self) -> None:
        packages = [
            _fake_package(
                "method_a", "3" * 64, [("item_a", "topic_x", 2.0), ("item_b", "topic_x", 1.0)]
            ),
            _fake_package(
                "method_b", "4" * 64, [("item_a", "topic_x", 2.0), ("item_b", "topic_x", 1.0)]
            ),
        ]
        with self.assertRaisesRegex(ValueError, "融合分数必须有限"):
            fuse_method_rankings(
                packages,
                output_method_id="fusion_x",
                strategy="z_score",
                fit_scope="per_topic",
                weights={"method_a": 1e308, "method_b": 1e308},
            )

    def test_cli_manifest_order_preserves_configuration_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out1 = Path(tmp) / "o1"
            out2 = Path(tmp) / "o2"
            self.assertEqual(self._run_cli(["--method-id", "w6_cli_fusion"], out1), 0)
            self.assertEqual(
                self._run_cli(["--method-id", "w6_cli_fusion"], out2, reverse=True), 0
            )
            m1 = load_json_object(out1 / "manifest.json")
            m2 = load_json_object(out2 / "manifest.json")
            # 输入顺序不得影响 semantic configuration identity。
            self.assertEqual(m1["ranking"]["sha256"], m2["ranking"]["sha256"])
            self.assertEqual(m1["method_inputs"], m2["method_inputs"])
            self.assertEqual(
                m1["freeze"]["configuration_sha256"], m2["freeze"]["configuration_sha256"]
            )
            self.assertEqual(
                [item["method_id"] for item in m1["method_inputs"]],
                ["w6_fixture_dense_v1", "w6_fixture_sparse_v1"],
            )

    def test_cli_same_artifact_id_different_content_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tampered_manifest = _make_tampered_same_id_package(Path(tmp))
            with mock.patch.object(
                fuse_w6_scores, "_git_revision", return_value=FAKE_GIT_REVISION
            ), mock.patch.object(
                fuse_w6_scores, "_git_worktree_clean", return_value=True
            ), redirect_stdout(io.StringIO()):
                rc = fuse_w6_scores.main(
                    [
                        "--manifest",
                        str(tampered_manifest),
                        "--manifest",
                        str(self.paths["method_dense_manifest"]),
                        "--method-id",
                        "w6_cli_fusion",
                        "--output-dir",
                        str(Path(tmp) / "out"),
                    ]
                )
            self.assertEqual(rc, 1)


def _fake_package(method_id, sha_seed, rows):
    return {
        "method_id": method_id,
        "manifest_sha256": sha_seed,
        "ranking_sha256": sha_seed[::-1],
        "input_references": {
            "topic_set": {"artifact_id": "t", "sha256": "a" * 64},
            "candidate_pool": {"artifact_id": "p", "sha256": "b" * 64},
        },
        "ranking_rows": [
            {
                "pair_id": pair_id,
                "research_query_id": topic_id,
                "method_id": method_id,
                "score": score,
                "rank": rank,
            }
            for rank, (pair_id, topic_id, score) in enumerate(rows, start=1)
        ],
    }


def _make_tampered_same_id_package(root: Path) -> Path:
    """构造 artifact_id/method_id 不变但内容不同且内部自洽的 sparse package。"""
    source = VALID_ROOT / "method_rankings" / "fake_sparse"
    target = root / "fake_sparse_tampered"
    shutil.copytree(source, target)
    rows = []
    with (target / "ranking.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            row["score"] = str(round(float(row["score"]) + 0.5, 6))
            rows.append(row)
    by_topic: dict[str, list[dict]] = {}
    for row in rows:
        by_topic.setdefault(row["research_query_id"], []).append(row)
    ordered = []
    for topic_id in sorted(by_topic):
        topic_rows = sorted(
            by_topic[topic_id], key=lambda row: (-float(row["score"]), row["pair_id"])
        )
        for rank, row in enumerate(topic_rows, start=1):
            row["rank"] = str(rank)
            ordered.append(row)
    write_csv_rows(target / "ranking.csv", RANKING_FIELDS, ordered)
    manifest = load_json_object(target / "manifest.json")
    manifest["ranking"]["sha256"] = sha256_file(target / "ranking.csv")
    manifest["freeze"]["configuration_sha256"] = compute_method_configuration_hash(manifest)
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target / "manifest.json"


def _tracked_open_calls(func):
    """运行 func 并记录所有 Path.open 访问的文件路径。"""
    opened: list[str] = []
    real_open = Path.open

    def tracking_open(self, *args, **kwargs):
        opened.append(str(self))
        return real_open(self, *args, **kwargs)

    with mock.patch.object(Path, "open", tracking_open):
        result = func()
    return result, opened


def _assert_no_label_aware_access(testcase: unittest.TestCase, opened: list[str]) -> None:
    hits = sorted(
        {path for path in opened for name in LABEL_AWARE_ARTIFACT_NAMES if name in path}
    )
    testcase.assertEqual(hits, [])


def _copy_generation_subset(destination: Path) -> Path:
    """只复制 generation 声明依赖的 artifact，构造最小 bundle。"""
    root = destination / "subset"
    root.mkdir(parents=True)
    manifest = load_json_object(BUNDLE_PATH)
    subset = copy.deepcopy(manifest)
    subset["artifacts"] = {
        name: manifest["artifacts"][name] for name in GENERATION_ARTIFACT_NAMES
    }
    (root / "bundle_manifest.json").write_text(
        json.dumps(subset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name in GENERATION_ARTIFACT_NAMES:
        relative = Path(manifest["artifacts"][name]["path"])
        source = VALID_ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.name == "manifest.json" and "method_rankings" in relative.parts:
            shutil.copytree(source.parent, target.parent, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    return root


class TaskContextLeakageTests(unittest.TestCase):
    """P1-1：generation 进程绝不打开 label-aware artifacts。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = validate_w6_bootstrap_bundle(BUNDLE_PATH)

    def test_loader_matches_bundle_context(self) -> None:
        ctx = load_w6_generation_context(BUNDLE_PATH)
        self.assertEqual(len(ctx["topics"]), 2)
        self.assertEqual(len(ctx["pool_members"]), 13)
        self.assertEqual(len(ctx["method_packages"]), 3)
        self.assertEqual(len(ctx["registry"]), len(GENERATION_ARTIFACT_NAMES))
        self.assertNotIn("annotation_results", ctx["payloads"])
        self.assertNotIn("split_manifest", ctx["payloads"])

    def test_loader_never_opens_label_aware_artifacts(self) -> None:
        _, opened = _tracked_open_calls(lambda: load_w6_generation_context(BUNDLE_PATH))
        _assert_no_label_aware_access(self, opened)

    def test_fusion_cli_never_opens_label_aware_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def run() -> int:
                with mock.patch.object(
                    fuse_w6_scores, "_git_revision", return_value=FAKE_GIT_REVISION
                ), mock.patch.object(
                    fuse_w6_scores, "_git_worktree_clean", return_value=True
                ), redirect_stdout(io.StringIO()):
                    return fuse_w6_scores.main(
                        [
                            "--manifest",
                            str(self.bundle["paths"]["method_sparse_manifest"]),
                            "--manifest",
                            str(self.bundle["paths"]["method_dense_manifest"]),
                            "--method-id",
                            "w6_cli_fusion",
                            "--output-dir",
                            str(Path(tmp) / "out"),
                        ]
                    )

            rc, opened = _tracked_open_calls(run)
        self.assertEqual(rc, 0)
        _assert_no_label_aware_access(self, opened)

    def test_fusion_cli_runs_on_declared_closure_subset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subset_root = _copy_generation_subset(Path(tmp))
            with mock.patch.object(
                fuse_w6_scores, "_git_revision", return_value=FAKE_GIT_REVISION
            ), mock.patch.object(
                fuse_w6_scores, "_git_worktree_clean", return_value=True
            ), redirect_stdout(io.StringIO()):
                rc = fuse_w6_scores.main(
                    [
                        "--bundle",
                        str(subset_root / "bundle_manifest.json"),
                        "--manifest",
                        str(subset_root / "method_rankings/fake_sparse/manifest.json"),
                        "--manifest",
                        str(subset_root / "method_rankings/fake_dense/manifest.json"),
                        "--method-id",
                        "w6_cli_fusion",
                        "--output-dir",
                        str(Path(tmp) / "out"),
                    ]
                )
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
