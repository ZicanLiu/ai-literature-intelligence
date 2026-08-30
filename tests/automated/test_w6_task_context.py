"""W6 generation task-context（闭包 / No-Leakage / 身份绑定）的离线回归测试。

覆盖 PR #70 第二轮审查的 P1-A / P1-B / P1-C：per-task dependency closure、
递归 side-channel guard（含自洽 rehash 攻击）、method → 当前 context 身份绑定。
"""

from __future__ import annotations

import copy
import csv
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from app import fuse_w6_scores, run_w6_synthesis
from src.annotation_tasks import sha256_file, write_csv_rows
from src.w5_method_contract import RANKING_FIELDS
from src.w6_contracts import (
    canonical_json_sha256,
    compute_pool_identity,
    load_json_object,
)
from src.w6_method_contract import compute_method_configuration_hash
from src.w6_no_leakage import (
    GENERATION_FORBIDDEN_KEYS,
    assert_no_label_side_channel,
    find_forbidden_keys,
)
from src.w6_task_context import (
    BASE_CONTEXT_ARTIFACT_NAMES,
    LABEL_AWARE_ARTIFACT_NAMES,
    derive_output_is_fixture,
    load_w6_base_context,
    resolve_bundle_method,
    resolve_method_path,
    validate_method_against_generation_context,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "w6_bootstrap"
VALID_ROOT = FIXTURE_ROOT / "valid"
BUNDLE_PATH = VALID_ROOT / "bundle_manifest.json"
FAKE_GIT_REVISION = "6b9eb12f898bf880c297902463e48f2ff3e0388b"

METHOD_ARTIFACT_NAMES = (
    "method_sparse_manifest",
    "method_dense_manifest",
    "method_fusion_manifest",
)


def _write_subset_bundle(root: Path, names) -> Path:
    """把指定 artifact 复制为最小 bundle，返回 bundle manifest 路径。"""
    root.mkdir(parents=True, exist_ok=True)
    manifest = load_json_object(BUNDLE_PATH)
    subset = copy.deepcopy(manifest)
    subset["artifacts"] = {name: manifest["artifacts"][name] for name in names}
    bundle_manifest = root / "bundle_manifest.json"
    bundle_manifest.write_text(
        json.dumps(subset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name in names:
        relative = Path(manifest["artifacts"][name]["path"])
        source = VALID_ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.name == "manifest.json" and "method_rankings" in relative.parts:
            shutil.copytree(source.parent, target.parent, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    return bundle_manifest


def _update_artifact(bundle_root: Path, name: str, relative: str, payload: dict) -> None:
    """重写 artifact 文件并同步 bundle manifest 中的声明 sha（自洽 rehash）。"""
    path = bundle_root / relative
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest_path = bundle_root / "bundle_manifest.json"
    manifest = load_json_object(manifest_path)
    manifest["artifacts"][name]["sha256"] = sha256_file(path)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _run_fusion_cli(args) -> int:
    with mock.patch.object(
        fuse_w6_scores, "_git_revision", return_value=FAKE_GIT_REVISION
    ), mock.patch.object(
        fuse_w6_scores, "_git_worktree_clean", return_value=True
    ), redirect_stdout(io.StringIO()):
        return fuse_w6_scores.main(args)


def _run_synthesis_cli(args) -> int:
    with mock.patch.object(
        run_w6_synthesis, "_git_revision", return_value=FAKE_GIT_REVISION
    ), redirect_stdout(io.StringIO()):
        return run_w6_synthesis.main(args)


class NoLeakageGuardTests(unittest.TestCase):
    """P1-B：递归 side-channel guard 的 exact-key policy。"""

    def test_legitimate_payloads_pass(self) -> None:
        # 合法字段不得被误杀：review_state / reviewer / source_score / retrieval 等。
        payload = {
            "retrieval": {"source_score": 0.9, "source_rank": 1},
            "canonicalization_provenance": {"reviewer": "fixture", "tool": "x"},
            "suspected_relationships": {"review_state": "pending_review"},
            "score_processing": {"normalization": {"label_access": False}},
            "freeze": {"evaluation_started_at": None},
            "label_access": {
                "relevance_labels_read": False,
                "hidden_test_labels_read": False,
            },
        }
        self.assertEqual(find_forbidden_keys(payload), [])

    def test_forbidden_keys_detected_recursively(self) -> None:
        cases = [
            ({"frozen_configuration": {"relevance_label": 2}}, ["frozen_configuration.relevance_label"]),
            (
                {"frozen_configuration": {"metric": {"ndcg": 0.99}}},
                ["frozen_configuration.metric", "frozen_configuration.metric.ndcg"],
            ),
            ({"policy": {"parameters": {"review_decision": "approve"}}}, ["policy.parameters.review_decision"]),
            (
                {"policy": {"parameters": {"annotation": {"final_label": 1}}}},
                ["policy.parameters.annotation", "policy.parameters.annotation.final_label"],
            ),
            ({"a": {"b": {"c": {"ndcg": 0.9}}}}, ["a.b.c.ndcg"]),
            (
                {"items": [{"evaluation": {"precision": 1.0}}]},
                ["items.evaluation", "items.evaluation.precision"],
            ),
            ({"METRICS": {"x": 1}}, ["METRICS"]),
            # 语义别名（单复数 / _at_k / 前缀变形）不得绕开。
            ({"relevance_labels": [2]}, ["relevance_labels"]),
            ({"gold_label": 2}, ["gold_label"]),
            ({"target_label": 1}, ["target_label"]),
            ({"review_result": "pass"}, ["review_result"]),
            ({"review_results": []}, ["review_results"]),
            ({"adjudications": {}}, ["adjudications"]),
            ({"evaluation_metric": {"x": 1}}, ["evaluation_metric"]),
            ({"evaluation_metrics": {"ndcg": 1}}, ["evaluation_metrics", "evaluation_metrics.ndcg"]),
            ({"ndcg_at_10": 0.9}, ["ndcg_at_10"]),
            ({"precision_at_k": 0.9}, ["precision_at_k"]),
            ({"recall_at_k": 0.9}, ["recall_at_k"]),
            ({"dev_metric": 0.9}, ["dev_metric"]),
            ({"hidden_metric": 0.9}, ["hidden_metric"]),
        ]
        for payload, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(find_forbidden_keys(payload), expected)
                with self.assertRaisesRegex(ValueError, "side-channel"):
                    assert_no_label_side_channel(payload, artifact_label="test")

    def test_policy_covers_review_vocabulary(self) -> None:
        for key in (
            "label", "labels", "relevance_label", "final_label", "human_label",
            "hidden_label", "hidden_labels", "hidden_test_label", "hidden_test_labels",
            "benchmark_labels", "judgement", "judgements", "annotation", "annotations",
            "annotation_result", "annotation_results", "review", "reviews",
            "review_decision", "adjudication", "metric", "metrics", "ndcg",
            "precision", "recall", "evaluation", "error_analysis",
        ):
            self.assertIn(key, GENERATION_FORBIDDEN_KEYS)


class BaseContextTests(unittest.TestCase):
    def test_base_context_loads_label_free_closure(self) -> None:
        context = load_w6_base_context(BUNDLE_PATH)
        self.assertEqual(len(context["topics"]), 2)
        self.assertEqual(len(context["pool_members"]), 13)
        self.assertEqual(len(context["registry"]), len(BASE_CONTEXT_ARTIFACT_NAMES))
        # base context 不加载任何 method payload / label-aware payload。
        self.assertNotIn("annotation_results", context["payloads"])
        self.assertNotIn("method_sparse_manifest", context["payloads"])
        self.assertIn("method_sparse_manifest", context["artifact_refs"])

    def test_resolve_bundle_method_with_transitive_dependencies(self) -> None:
        context = load_w6_base_context(BUNDLE_PATH)
        known: dict = {}
        package = resolve_bundle_method(context, "method_fusion_manifest", known=known)
        # fusion 的传递依赖 sparse/dense 必须按需加载。
        self.assertEqual(
            set(known),
            {
                "w6_fixture_method_sparse_v1",
                "w6_fixture_method_dense_v1",
                "w6_fixture_method_fusion_v1",
            },
        )
        self.assertEqual(package["method_id"], "w6_fixture_score_fusion_v1")

    def test_method_binding_to_current_context(self) -> None:
        context = load_w6_base_context(BUNDLE_PATH)
        package = resolve_bundle_method(context, "method_sparse_manifest")
        validate_method_against_generation_context(package, context)


class MinimalClosureTests(unittest.TestCase):
    """P1-A：per-task / per-selected-method minimal dependency closure。"""

    def test_fusion_cli_runs_without_preexisting_fusion_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _write_subset_bundle(
                Path(tmp) / "subset",
                [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"],
            )
            rc = _run_fusion_cli(
                [
                    "--bundle", str(bundle),
                    "--manifest", str(Path(tmp) / "subset/method_rankings/fake_sparse/manifest.json"),
                    "--manifest", str(Path(tmp) / "subset/method_rankings/fake_dense/manifest.json"),
                    "--method-id", "w6_closure_fusion",
                    "--output-dir", str(Path(tmp) / "out"),
                ]
            )
            self.assertEqual(rc, 0)

    def test_synthesis_explicit_sparse_minimal_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # 只保留 base + sparse；dense/fusion 完全不存在。
            bundle = _write_subset_bundle(
                Path(tmp) / "subset",
                [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest"],
            )
            rc = _run_synthesis_cli(
                [
                    "--bundle", str(bundle),
                    "--method-manifest",
                    str(Path(tmp) / "subset/method_rankings/fake_sparse/manifest.json"),
                    "--output-dir", str(Path(tmp) / "out"),
                ]
            )
            self.assertEqual(rc, 0)

    def test_synthesis_default_fusion_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _write_subset_bundle(
                Path(tmp) / "subset",
                [*BASE_CONTEXT_ARTIFACT_NAMES, *METHOD_ARTIFACT_NAMES],
            )
            rc = _run_synthesis_cli(
                ["--bundle", str(bundle), "--output-dir", str(Path(tmp) / "out")]
            )
            self.assertEqual(rc, 0)

    def test_synthesis_default_fails_without_transitive_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # fusion 存在，但它声明的传递依赖 sparse 被删除。
            bundle = _write_subset_bundle(
                Path(tmp) / "subset",
                [
                    *BASE_CONTEXT_ARTIFACT_NAMES,
                    "method_dense_manifest",
                    "method_fusion_manifest",
                ],
            )
            rc = _run_synthesis_cli(
                ["--bundle", str(bundle), "--output-dir", str(Path(tmp) / "out")]
            )
            self.assertEqual(rc, 1)


class SideChannelAttackTests(unittest.TestCase):
    """P1-B：自洽 rehash 的 side-channel 攻击必须 fail closed。"""

    def _base_names(self):
        return [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"]

    def _assert_both_clis_fail(self, bundle_root: Path) -> None:
        bundle = bundle_root / "bundle_manifest.json"
        rc_fusion = _run_fusion_cli(
            [
                "--bundle", str(bundle),
                "--manifest", str(bundle_root / "method_rankings/fake_sparse/manifest.json"),
                "--manifest", str(bundle_root / "method_rankings/fake_dense/manifest.json"),
                "--method-id", "w6_attack_fusion",
                "--output-dir", str(bundle_root / "out_f"),
            ]
        )
        rc_synthesis = _run_synthesis_cli(
            [
                "--bundle", str(bundle),
                "--method-manifest",
                str(bundle_root / "method_rankings/fake_sparse/manifest.json"),
                "--output-dir", str(bundle_root / "out_s"),
            ]
        )
        self.assertEqual(rc_fusion, 1)
        self.assertEqual(rc_synthesis, 1)

    def test_retrieval_relevance_label_side_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(root, self._base_names())
            payload = load_json_object(root / "retrieval_runs.json")
            payload["runs"][0]["frozen_configuration"]["relevance_label"] = 2
            # 自洽重算 artifact 内部 identity 与 bundle 声明 sha。
            payload["runs"][0]["configuration_sha256"] = canonical_json_sha256(
                payload["runs"][0]["frozen_configuration"]
            )
            _update_artifact(root, "retrieval_provenance", "retrieval_runs.json", payload)
            self._assert_both_clis_fail(root)

    def test_retrieval_metric_side_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(root, self._base_names())
            payload = load_json_object(root / "retrieval_runs.json")
            payload["runs"][0]["frozen_configuration"]["metric"] = {"ndcg": 0.99}
            payload["runs"][0]["configuration_sha256"] = canonical_json_sha256(
                payload["runs"][0]["frozen_configuration"]
            )
            _update_artifact(root, "retrieval_provenance", "retrieval_runs.json", payload)
            self._assert_both_clis_fail(root)

    def test_pool_policy_annotation_and_review_side_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(root, self._base_names())
            payload = load_json_object(root / "candidate_pool.json")
            payload["policy"]["parameters"]["annotation"] = {"final_label": 1}
            payload["policy"]["parameters"]["review_decision"] = "approve"
            # 自洽重算 pool identity 与 bundle 声明 sha。
            payload["pool_identity"] = compute_pool_identity(payload)
            _update_artifact(root, "candidate_pool", "candidate_pool.json", payload)
            self._assert_both_clis_fail(root)

    def test_records_deep_nested_side_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(root, self._base_names())
            payload = load_json_object(root / "source_records.json")
            payload["records"][0]["record_provenance"]["quality"] = {
                "nested": {"metrics": {"ndcg": 0.99}}
            }
            _update_artifact(root, "source_records", "source_records.json", payload)
            self._assert_both_clis_fail(root)

    def test_method_manifest_side_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(root, self._base_names())
            manifest_path = root / "method_rankings/fake_sparse/manifest.json"
            payload = load_json_object(manifest_path)
            payload["method"]["parameters"]["metrics"] = {"ndcg": 0.99}
            # 自洽重算 method configuration hash 与 bundle 声明 sha。
            payload["freeze"]["configuration_sha256"] = compute_method_configuration_hash(payload)
            _update_artifact(
                root,
                "method_sparse_manifest",
                "method_rankings/fake_sparse/manifest.json",
                payload,
            )
            self._assert_both_clis_fail(root)


class RoleSwapAttackTests(unittest.TestCase):
    """P1-C：method 输入引用必须绑定当前 context 的真实 artifact identity。"""

    def _make_role_swapped_package(
        self, root: Path, *, swap_inputs: bool = False, swap_auxiliary: bool = False
    ) -> Path:
        bundle_manifest = load_json_object(root / "bundle_manifest.json")
        refs = bundle_manifest["artifacts"]
        source = root / "method_rankings/fake_sparse"
        target = root / "method_rankings/attack_sparse"
        shutil.copytree(source, target)
        manifest = load_json_object(target / "manifest.json")
        manifest["artifact_id"] = "w6_attack_method_sparse_v1"
        manifest["method"]["method_id"] = "w6_attack_sparse_v1"
        # ranking.csv 同步新 method_id 并重算 ranking sha（保持内容自洽）。
        rows = []
        with (target / "ranking.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                row["method_id"] = "w6_attack_sparse_v1"
                rows.append(row)
        from src.annotation_tasks import write_csv_rows
        from src.w5_method_contract import RANKING_FIELDS

        write_csv_rows(target / "ranking.csv", RANKING_FIELDS, rows)
        manifest["ranking"]["sha256"] = sha256_file(target / "ranking.csv")
        if swap_inputs:
            # topic_set ↔ candidate_pool 角色互换（引用都是真实 artifact，hash 自洽）。
            manifest["inputs"]["topic_set"] = {
                "artifact_id": refs["candidate_pool"]["artifact_id"],
                "sha256": refs["candidate_pool"]["sha256"],
            }
            manifest["inputs"]["candidate_pool"] = {
                "artifact_id": refs["topic_set"]["artifact_id"],
                "sha256": refs["topic_set"]["sha256"],
            }
        if swap_auxiliary:
            manifest["auxiliary_inputs"]["source_records"] = {
                "artifact_id": refs["canonical_entities"]["artifact_id"],
                "sha256": refs["canonical_entities"]["sha256"],
            }
        manifest["freeze"]["configuration_sha256"] = compute_method_configuration_hash(manifest)
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # 自洽性 sanity check：公共 contract validator 本身接受该 package。
        from src.w6_method_contract import validate_w6_method_package

        context = load_w6_base_context(root / "bundle_manifest.json")
        registry = dict(context["registry"])
        # swapped refs 指向真实 bundle artifact，需要补注册。
        for name in BASE_CONTEXT_ARTIFACT_NAMES:
            entry = refs[name]
            registry.setdefault(
                entry["artifact_id"], {"artifact_id": entry["artifact_id"], "sha256": entry["sha256"]}
            )
        validate_w6_method_package(
            target / "manifest.json",
            artifact_registry=registry,
            pool_members=context["pool_members"],
            known_method_packages={},
        )
        return target / "manifest.json"

    def _base_names(self):
        return [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"]

    def test_topic_pool_swap_fails_fusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(root, self._base_names())
            swapped = self._make_role_swapped_package(root, swap_inputs=True)
            rc = _run_fusion_cli(
                [
                    "--bundle", str(root / "bundle_manifest.json"),
                    "--manifest", str(swapped),
                    "--manifest", str(root / "method_rankings/fake_dense/manifest.json"),
                    "--method-id", "w6_attack_fusion",
                    "--output-dir", str(root / "out_f"),
                ]
            )
            self.assertEqual(rc, 1)

    def test_topic_pool_swap_fails_synthesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(root, self._base_names())
            swapped = self._make_role_swapped_package(root, swap_inputs=True)
            rc = _run_synthesis_cli(
                [
                    "--bundle", str(root / "bundle_manifest.json"),
                    "--method-manifest", str(swapped),
                    "--output-dir", str(root / "out_s"),
                ]
            )
            self.assertEqual(rc, 1)

    def test_auxiliary_swap_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(root, self._base_names())
            swapped = self._make_role_swapped_package(root, swap_auxiliary=True)
            rc = _run_fusion_cli(
                [
                    "--bundle", str(root / "bundle_manifest.json"),
                    "--manifest", str(swapped),
                    "--manifest", str(root / "method_rankings/fake_dense/manifest.json"),
                    "--method-id", "w6_attack_fusion",
                    "--output-dir", str(root / "out_f"),
                ]
            )
            self.assertEqual(rc, 1)
            rc = _run_synthesis_cli(
                [
                    "--bundle", str(root / "bundle_manifest.json"),
                    "--method-manifest", str(swapped),
                    "--output-dir", str(root / "out_s"),
                ]
            )
            self.assertEqual(rc, 1)


class FrozenPathSafetyTests(unittest.TestCase):
    """P1-E：Fusion 输出不得污染 frozen bundle tree。"""

    def test_fusion_cli_rejects_output_inside_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _write_subset_bundle(
                Path(tmp) / "subset",
                [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"],
            )
            for output_dir in (
                Path(tmp) / "subset/generated_fusion",
                Path(tmp) / "subset",
            ):
                rc = _run_fusion_cli(
                    [
                        "--bundle", str(bundle),
                        "--manifest",
                        str(Path(tmp) / "subset/method_rankings/fake_sparse/manifest.json"),
                        "--manifest",
                        str(Path(tmp) / "subset/method_rankings/fake_dense/manifest.json"),
                        "--method-id", "w6_attack_fusion",
                        "--output-dir", str(output_dir),
                    ]
                )
                self.assertEqual(rc, 1, str(output_dir))
            self.assertFalse((Path(tmp) / "subset/generated_fusion").exists())

    def test_fusion_cli_allows_output_outside_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _write_subset_bundle(
                Path(tmp) / "subset",
                [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"],
            )
            rc = _run_fusion_cli(
                [
                    "--bundle", str(bundle),
                    "--manifest",
                    str(Path(tmp) / "subset/method_rankings/fake_sparse/manifest.json"),
                    "--manifest",
                    str(Path(tmp) / "subset/method_rankings/fake_dense/manifest.json"),
                    "--method-id", "w6_attack_fusion",
                    "--output-dir", str(Path(tmp) / "outside/new_output"),
                ]
            )
            self.assertEqual(rc, 0)

    def test_output_dir_junction_overlap_rejected_or_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _write_subset_bundle(
                Path(tmp) / "subset",
                [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"],
            )
            junction = Path(tmp) / "junction_link"
            try:
                junction.symlink_to(Path(tmp) / "subset", target_is_directory=True)
            except OSError as error:
                self.skipTest(f"SKIPPED / NOT EXECUTED：当前平台无法创建 junction/symlink（{error}）。")
            rc = _run_fusion_cli(
                [
                    "--bundle", str(bundle),
                    "--manifest",
                    str(Path(tmp) / "subset/method_rankings/fake_sparse/manifest.json"),
                    "--manifest",
                    str(Path(tmp) / "subset/method_rankings/fake_dense/manifest.json"),
                    "--method-id", "w6_attack_fusion",
                    "--output-dir", str(junction / "generated_fusion"),
                ]
            )
            self.assertEqual(rc, 1)
            self.assertFalse((Path(tmp) / "subset/generated_fusion").exists())


class NestedDependencyRoleSwapTests(unittest.TestCase):
    """P1-1：correct top + 被篡改的传递 dependency（全部 hash 自洽）必须 fail closed。"""

    def _tamper_dependency(self, root: Path, *, swap_auxiliary: bool = False) -> None:
        refs = load_json_object(root / "bundle_manifest.json")["artifacts"]
        sparse_manifest = root / "method_rankings/fake_sparse/manifest.json"
        manifest = load_json_object(sparse_manifest)
        if swap_auxiliary:
            manifest["auxiliary_inputs"]["source_records"] = {
                "artifact_id": refs["canonical_entities"]["artifact_id"],
                "sha256": refs["canonical_entities"]["sha256"],
            }
        else:
            manifest["inputs"]["topic_set"] = {
                "artifact_id": refs["candidate_pool"]["artifact_id"],
                "sha256": refs["candidate_pool"]["sha256"],
            }
            manifest["inputs"]["candidate_pool"] = {
                "artifact_id": refs["topic_set"]["artifact_id"],
                "sha256": refs["topic_set"]["sha256"],
            }
        manifest["freeze"]["configuration_sha256"] = compute_method_configuration_hash(manifest)
        sparse_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # 顶层 fusion 的 method_inputs 与 configuration hash 自洽重算。
        fusion_manifest_path = root / "method_rankings/fake_fusion/manifest.json"
        fusion = load_json_object(fusion_manifest_path)
        for item in fusion["method_inputs"]:
            if item["manifest_artifact_id"] == "w6_fixture_method_sparse_v1":
                item["manifest_sha256"] = sha256_file(sparse_manifest)
        fusion["freeze"]["configuration_sha256"] = compute_method_configuration_hash(fusion)
        fusion_manifest_path.write_text(
            json.dumps(fusion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # bundle 声明同步自洽。
        manifest_path = root / "bundle_manifest.json"
        bundle_manifest = load_json_object(manifest_path)
        bundle_manifest["artifacts"]["method_sparse_manifest"]["sha256"] = sha256_file(
            sparse_manifest
        )
        bundle_manifest["artifacts"]["method_fusion_manifest"]["sha256"] = sha256_file(
            fusion_manifest_path
        )
        manifest_path.write_text(
            json.dumps(bundle_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _assert_nested_swap_fails(self, swap_auxiliary: bool) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(
                root, [*BASE_CONTEXT_ARTIFACT_NAMES, *METHOD_ARTIFACT_NAMES]
            )
            self._tamper_dependency(root, swap_auxiliary=swap_auxiliary)
            bundle = root / "bundle_manifest.json"
            # default synthesis（top=fusion，dep 被篡改）必须 fail。
            rc = _run_synthesis_cli(
                ["--bundle", str(bundle), "--output-dir", str(root / "out_s")]
            )
            self.assertEqual(rc, 1)
            # fusion(top, dense) 也必须 fail。
            rc = _run_fusion_cli(
                [
                    "--bundle", str(bundle),
                    "--manifest", str(root / "method_rankings/fake_fusion/manifest.json"),
                    "--manifest", str(root / "method_rankings/fake_dense/manifest.json"),
                    "--method-id", "w6_nested_attack",
                    "--output-dir", str(root / "out_f"),
                ]
            )
            self.assertEqual(rc, 1)

    def test_nested_dependency_inputs_role_swap_fails(self) -> None:
        self._assert_nested_swap_fails(swap_auxiliary=False)

    def test_nested_dependency_auxiliary_role_swap_fails(self) -> None:
        self._assert_nested_swap_fails(swap_auxiliary=True)


class ManifestMetadataLeakageTests(unittest.TestCase):
    """P1-2：bundle manifest 混入 arbitrary metadata 必须被严格结构拒绝。"""

    def test_bundle_manifest_metadata_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            bundle = _write_subset_bundle(
                root, [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"]
            )
            manifest = load_json_object(bundle)
            manifest["metrics"] = {"ndcg": 0.99}
            manifest["evaluation"] = {"relevance_label": 2}
            bundle.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            rc_fusion = _run_fusion_cli(
                [
                    "--bundle", str(bundle),
                    "--manifest", str(root / "method_rankings/fake_sparse/manifest.json"),
                    "--manifest", str(root / "method_rankings/fake_dense/manifest.json"),
                    "--method-id", "w6_attack_fusion",
                    "--output-dir", str(root / "out_f"),
                ]
            )
            rc_synthesis = _run_synthesis_cli(
                [
                    "--bundle", str(bundle),
                    "--method-manifest", str(root / "method_rankings/fake_sparse/manifest.json"),
                    "--output-dir", str(root / "out_s"),
                ]
            )
            self.assertEqual(rc_fusion, 1)
            self.assertEqual(rc_synthesis, 1)

    def test_alias_side_channel_self_consistent_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(
                root, [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"]
            )
            payload = load_json_object(root / "retrieval_runs.json")
            payload["runs"][0]["frozen_configuration"]["evaluation_metrics"] = {
                "ndcg_at_10": 0.99
            }
            payload["runs"][0]["frozen_configuration"]["gold_label"] = 2
            payload["runs"][0]["configuration_sha256"] = canonical_json_sha256(
                payload["runs"][0]["frozen_configuration"]
            )
            _update_artifact(root, "retrieval_provenance", "retrieval_runs.json", payload)
            rc = _run_fusion_cli(
                [
                    "--bundle", str(root / "bundle_manifest.json"),
                    "--manifest", str(root / "method_rankings/fake_sparse/manifest.json"),
                    "--manifest", str(root / "method_rankings/fake_dense/manifest.json"),
                    "--method-id", "w6_attack_fusion",
                    "--output-dir", str(root / "out_f"),
                ]
            )
            self.assertEqual(rc, 1)


class DuplicateArtifactIdTests(unittest.TestCase):
    """P1-3：duplicate artifact_id 必须立即 fail closed（与 JSON 顺序无关）。"""

    def _bundle_with_duplicate_id(self, root: Path, *, alt_first: bool) -> Path:
        bundle = _write_subset_bundle(
            root, [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"]
        )
        manifest = load_json_object(bundle)
        dense_entry = manifest["artifacts"]["method_dense_manifest"]
        alt_entry = {
            "artifact_id": "w6_fixture_method_sparse_v1",
            "path": dense_entry["path"],
            "sha256": dense_entry["sha256"],
        }
        artifacts = manifest["artifacts"]
        if alt_first:
            rebuilt = {"method_sparse_alt": alt_entry}
            rebuilt.update(artifacts)
            manifest["artifacts"] = rebuilt
        else:
            artifacts["method_sparse_alt"] = alt_entry
        bundle.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return bundle

    def test_duplicate_artifact_id_fails_both_orders(self) -> None:
        for alt_first in (False, True):
            with self.subTest(alt_first=alt_first), tempfile.TemporaryDirectory() as tmp:
                bundle = self._bundle_with_duplicate_id(
                    Path(tmp) / "subset", alt_first=alt_first
                )
                with self.assertRaisesRegex(ValueError, "duplicate artifact_id"):
                    load_w6_base_context(bundle)


def _make_external_copy(
    root: Path, source_dir: Path, *, artifact_id: str, method_id: str
) -> Path:
    """复制 method package 为合法 external package（新 artifact_id/method_id）。"""
    target = root / f"ext_{method_id}"
    shutil.copytree(source_dir, target)
    rows = []
    with (target / "ranking.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            row["method_id"] = method_id
            rows.append(row)
    write_csv_rows(target / "ranking.csv", RANKING_FIELDS, rows)
    manifest = load_json_object(target / "manifest.json")
    manifest["artifact_id"] = artifact_id
    manifest["method"]["method_id"] = method_id
    manifest["ranking"]["sha256"] = sha256_file(target / "ranking.csv")
    manifest["freeze"]["configuration_sha256"] = compute_method_configuration_hash(manifest)
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target / "manifest.json"


class ExternalDependencyOrderTests(unittest.TestCase):
    """P1-4：external dependency resolution 必须与 CLI 参数顺序无关。"""

    def test_external_hybrid_dependency_order_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # B：external dense（无 method_inputs）。
            b_manifest = _make_external_copy(
                root,
                VALID_ROOT / "method_rankings/fake_dense",
                artifact_id="w6_ext_method_dense_v1",
                method_id="w6_ext_dense_v1",
            )
            # A：external hybrid，method_inputs = [external B, bundle sparse]。
            a_dir = root / "ext_w6_ext_fusion_v1"
            shutil.copytree(VALID_ROOT / "method_rankings/fake_fusion", a_dir)
            rows = []
            with (a_dir / "ranking.csv").open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    row["method_id"] = "w6_ext_fusion_v1"
                    rows.append(row)
            write_csv_rows(a_dir / "ranking.csv", RANKING_FIELDS, rows)
            a_manifest = load_json_object(a_dir / "manifest.json")
            a_manifest["artifact_id"] = "w6_ext_method_fusion_v1"
            a_manifest["method"]["method_id"] = "w6_ext_fusion_v1"
            bundle_manifest = load_json_object(BUNDLE_PATH)
            sparse_entry = bundle_manifest["artifacts"]["method_sparse_manifest"]
            sparse_ranking_sha = load_json_object(
                VALID_ROOT / "method_rankings/fake_sparse/manifest.json"
            )["ranking"]["sha256"]
            a_manifest["method_inputs"] = [
                {
                    "method_id": "w6_ext_dense_v1",
                    "manifest_artifact_id": "w6_ext_method_dense_v1",
                    "manifest_sha256": sha256_file(b_manifest),
                    "ranking_sha256": load_json_object(b_manifest)["ranking"]["sha256"],
                    "uses_raw_score": True,
                    "uses_rank": False,
                },
                {
                    "method_id": "w6_fixture_sparse_v1",
                    "manifest_artifact_id": sparse_entry["artifact_id"],
                    "manifest_sha256": sparse_entry["sha256"],
                    "ranking_sha256": sparse_ranking_sha,
                    "uses_raw_score": True,
                    "uses_rank": False,
                },
            ]
            a_manifest["method"]["parameters"]["weights"] = {
                "w6_ext_dense_v1": 0.5,
                "w6_fixture_sparse_v1": 0.5,
            }
            a_manifest["ranking"]["sha256"] = sha256_file(a_dir / "ranking.csv")
            a_manifest["freeze"]["configuration_sha256"] = compute_method_configuration_hash(
                a_manifest
            )
            (a_dir / "manifest.json").write_text(
                json.dumps(a_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            # [A, B] 与 [B, A] 必须行为完全一致。
            outputs = []
            for order in ((a_dir / "manifest.json", b_manifest), (b_manifest, a_dir / "manifest.json")):
                out = root / f"out_{len(outputs)}"
                rc = _run_fusion_cli(
                    [
                        "--manifest", str(order[0]),
                        "--manifest", str(order[1]),
                        "--method-id", "w6_ext_order_fusion",
                        "--output-dir", str(out),
                    ]
                )
                self.assertEqual(rc, 0)
                outputs.append(load_json_object(out / "manifest.json"))
            self.assertEqual(
                outputs[0]["ranking"]["sha256"], outputs[1]["ranking"]["sha256"]
            )
            self.assertEqual(
                outputs[0]["freeze"]["configuration_sha256"],
                outputs[1]["freeze"]["configuration_sha256"],
            )

    def test_duplicate_explicit_artifact_id_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b1 = _make_external_copy(
                root / "a",
                VALID_ROOT / "method_rankings/fake_dense",
                artifact_id="w6_ext_method_dense_v1",
                method_id="w6_ext_dense_v1",
            )
            b2 = _make_external_copy(
                root / "b",
                VALID_ROOT / "method_rankings/fake_dense",
                artifact_id="w6_ext_method_dense_v1",
                method_id="w6_ext_dense_v1",
            )
            rc = _run_fusion_cli(
                [
                    "--manifest", str(b1),
                    "--manifest", str(b2),
                    "--method-id", "w6_ext_order_fusion",
                    "--output-dir", str(root / "out"),
                ]
            )
            self.assertEqual(rc, 1)


class AllowlistSemanticsTests(unittest.TestCase):
    """P1-2（第四轮）：allowlist 必须具备 (path, key, value) 语义。"""

    def test_legitimate_label_provenance_paths_pass(self) -> None:
        payload = {
            "label_access": {
                "relevance_labels_read": False,
                "hidden_test_labels_read": False,
                "declaration": "no labels were read",
            },
            "score_processing": {"normalization": {"label_access": False}},
            "freeze": {"evaluation_started_at": None},
            "suspected_relationships": {"x": {"review_state": "pending_review"}},
            "canonicalization_provenance": {"reviewer": "fixture"},
        }
        self.assertEqual(find_forbidden_keys(payload), [])

    def test_label_read_keys_outside_contract_path_forbidden(self) -> None:
        # 即使值为 false，出现在 free-form object 内也必须 fail closed。
        for value in (True, False):
            with self.subTest(value=value):
                payload = {
                    "frozen_configuration": {"relevance_labels_read": value}
                }
                self.assertEqual(
                    find_forbidden_keys(payload),
                    ["frozen_configuration.relevance_labels_read"],
                )

    def test_label_read_true_anywhere_forbidden(self) -> None:
        payload = {"label_access": {"relevance_labels_read": True}}
        self.assertEqual(
            find_forbidden_keys(payload), ["label_access.relevance_labels_read"]
        )
        payload = {"policy": {"parameters": {"hidden_test_labels_read": True}}}
        self.assertEqual(
            find_forbidden_keys(payload),
            ["policy.parameters.hidden_test_labels_read"],
        )

    def test_retrieval_relevance_labels_read_attack_fails_clis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(
                root, [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"]
            )
            payload = load_json_object(root / "retrieval_runs.json")
            payload["runs"][0]["frozen_configuration"]["relevance_labels_read"] = True
            # 全链 self-consistent rehash。
            payload["runs"][0]["configuration_sha256"] = canonical_json_sha256(
                payload["runs"][0]["frozen_configuration"]
            )
            _update_artifact(root, "retrieval_provenance", "retrieval_runs.json", payload)
            rc = _run_fusion_cli(
                [
                    "--bundle", str(root / "bundle_manifest.json"),
                    "--manifest", str(root / "method_rankings/fake_sparse/manifest.json"),
                    "--manifest", str(root / "method_rankings/fake_dense/manifest.json"),
                    "--method-id", "w6_attack_fusion",
                    "--output-dir", str(root / "out_f"),
                ]
            )
            self.assertEqual(rc, 1)

    def test_pool_hidden_labels_read_attack_fails_clis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(
                root, [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"]
            )
            payload = load_json_object(root / "candidate_pool.json")
            payload["policy"]["parameters"]["hidden_test_labels_read"] = True
            # 全链 self-consistent rehash。
            payload["pool_identity"] = compute_pool_identity(payload)
            _update_artifact(root, "candidate_pool", "candidate_pool.json", payload)
            rc = _run_synthesis_cli(
                [
                    "--bundle", str(root / "bundle_manifest.json"),
                    "--method-manifest",
                    str(root / "method_rankings/fake_sparse/manifest.json"),
                    "--output-dir", str(root / "out_s"),
                ]
            )
            self.assertEqual(rc, 1)


class ParallelDevelopmentContractTests(unittest.TestCase):
    """P1-1（第四轮）：parallel_development 必须具备等价 contract validation。"""

    def _run_both_clis(self, root: Path) -> tuple[int, int]:
        rc_fusion = _run_fusion_cli(
            [
                "--bundle", str(root / "bundle_manifest.json"),
                "--manifest", str(root / "method_rankings/fake_sparse/manifest.json"),
                "--manifest", str(root / "method_rankings/fake_dense/manifest.json"),
                "--method-id", "w6_attack_fusion",
                "--output-dir", str(root / "out_f"),
            ]
        )
        rc_synthesis = _run_synthesis_cli(
            [
                "--bundle", str(root / "bundle_manifest.json"),
                "--method-manifest",
                str(root / "method_rankings/fake_sparse/manifest.json"),
                "--output-dir", str(root / "out_s"),
            ]
        )
        return rc_fusion, rc_synthesis

    def test_parallel_development_metric_slots_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            bundle = _write_subset_bundle(
                root, [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"]
            )
            manifest = load_json_object(bundle)
            manifest["parallel_development"]["metrics"] = {"ndcg": 0.99}
            manifest["parallel_development"]["evaluation"] = {"relevance_label": 2}
            bundle.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            rc_fusion, rc_synthesis = self._run_both_clis(root)
            self.assertEqual(rc_fusion, 1)
            self.assertEqual(rc_synthesis, 1)

    def test_parallel_development_entry_metadata_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            bundle = _write_subset_bundle(
                root, [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"]
            )
            manifest = load_json_object(bundle)
            manifest["parallel_development"]["synthesis_and_fusion"]["metrics"] = {
                "ndcg": 0.99
            }
            bundle.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "字段不符合合同"):
                load_w6_base_context(bundle)

    def test_parallel_development_legitimate_fixture_passes(self) -> None:
        # 原始 fixture 与 subset bundle 的 parallel_development 均合法。
        context = load_w6_base_context(BUNDLE_PATH)
        self.assertEqual(len(context["topics"]), 2)


class FixtureProvenanceTests(unittest.TestCase):
    """P1-1（第五轮）：fixture provenance 必须由可信输入派生并正确传播。"""

    def test_fusion_output_inherits_fixture_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            rc = _run_fusion_cli(
                [
                    "--manifest",
                    str(VALID_ROOT / "method_rankings/fake_sparse/manifest.json"),
                    "--manifest",
                    str(VALID_ROOT / "method_rankings/fake_dense/manifest.json"),
                    "--method-id", "w6_prov_fusion",
                    "--output-dir", str(out),
                ]
            )
            self.assertEqual(rc, 0)
            manifest = load_json_object(out / "manifest.json")
            self.assertIs(manifest["is_fixture"], True)

    def test_synthesis_chain_inherits_fixture_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            rc = _run_synthesis_cli(["--output-dir", str(out)])
            self.assertEqual(rc, 0)
            for name in (
                "evidence_units.json",
                "synthesis_input.json",
                "structured_synthesis.json",
            ):
                payload = load_json_object(out / name)
                self.assertIs(payload["is_fixture"], True, name)

    def test_fusion_output_feeds_synthesis_chain(self) -> None:
        # fixture fusion 输出再进入 synthesis：链上 is_fixture 保持 true。
        with tempfile.TemporaryDirectory() as tmp:
            fusion_out = Path(tmp) / "fusion"
            rc = _run_fusion_cli(
                [
                    "--manifest",
                    str(VALID_ROOT / "method_rankings/fake_sparse/manifest.json"),
                    "--manifest",
                    str(VALID_ROOT / "method_rankings/fake_dense/manifest.json"),
                    "--method-id", "w6_prov_fusion",
                    "--output-dir", str(fusion_out),
                ]
            )
            self.assertEqual(rc, 0)
            synth_out = Path(tmp) / "synth"
            rc = _run_synthesis_cli(
                [
                    "--method-manifest", str(fusion_out / "manifest.json"),
                    "--output-dir", str(synth_out),
                ]
            )
            self.assertEqual(rc, 0)
            payload = load_json_object(synth_out / "structured_synthesis.json")
            self.assertIs(payload["is_fixture"], True)

    def test_mixed_method_fixture_identity_fails_closed(self) -> None:
        # 翻转一个 method package 的 is_fixture（自洽重算 bundle 声明 sha）→ 拒绝。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(
                root, [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"]
            )
            sparse_manifest = root / "method_rankings/fake_sparse/manifest.json"
            payload = load_json_object(sparse_manifest)
            payload["is_fixture"] = False
            _update_artifact(
                root,
                "method_sparse_manifest",
                "method_rankings/fake_sparse/manifest.json",
                payload,
            )
            rc = _run_fusion_cli(
                [
                    "--bundle", str(root / "bundle_manifest.json"),
                    "--manifest", str(sparse_manifest),
                    "--manifest", str(root / "method_rankings/fake_dense/manifest.json"),
                    "--method-id", "w6_prov_fusion",
                    "--output-dir", str(root / "out_f"),
                ]
            )
            self.assertEqual(rc, 1)

    def test_mixed_base_payload_fixture_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "subset"
            _write_subset_bundle(
                root, [*BASE_CONTEXT_ARTIFACT_NAMES, "method_sparse_manifest", "method_dense_manifest"]
            )
            pool = load_json_object(root / "candidate_pool.json")
            pool["is_fixture"] = False
            _update_artifact(root, "candidate_pool", "candidate_pool.json", pool)
            rc = _run_synthesis_cli(
                [
                    "--bundle", str(root / "bundle_manifest.json"),
                    "--method-manifest",
                    str(root / "method_rankings/fake_sparse/manifest.json"),
                    "--output-dir", str(root / "out_s"),
                ]
            )
            self.assertEqual(rc, 1)

    def test_real_like_consistent_non_fixture_derives_false(self) -> None:
        # unit-level：全 False 一致输入 → 输出 False（机制可表达）。
        context = load_w6_base_context(BUNDLE_PATH)
        real_like_payloads = {
            name: {**payload, "is_fixture": False}
            for name, payload in context["payloads"].items()
        }
        real_like_context = {**context, "payloads": real_like_payloads}
        self.assertIs(derive_output_is_fixture(real_like_context, {}), False)
        self.assertIs(derive_output_is_fixture(context, {}), True)
        with self.assertRaisesRegex(ValueError, "不一致"):
            derive_output_is_fixture(
                context,
                {
                    "pkg": {
                        "manifest": {"is_fixture": False},
                    }
                },
            )

    def test_builders_propagate_explicit_fixture_flag(self) -> None:
        # builder 层：is_fixture 为必填，显式 False/True 都正确传播。
        records = load_json_object(VALID_ROOT / "source_records.json")
        from src.w6_synthesis_pipeline import build_evidence_units

        context = load_w6_base_context(BUNDLE_PATH)
        for flag in (False, True):
            payload = build_evidence_units(
                context["records"],
                context["canonical"],
                ["rec_001"],
                artifact_id="w6_prov_evidence",
                created_at="2026-08-25T00:00:00+08:00",
                git_revision=FAKE_GIT_REVISION,
                is_fixture=flag,
            )
            self.assertIs(payload["is_fixture"], flag)


if __name__ == "__main__":
    unittest.main(verbosity=2)
