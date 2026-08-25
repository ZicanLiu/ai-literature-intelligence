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
from src.annotation_tasks import sha256_file
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
