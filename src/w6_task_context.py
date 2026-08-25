"""W6 task-scoped、label-free 的 generation 输入加载器（per-task dependency closure）。

``validate_w6_bootstrap_bundle`` 会解析整个公共 bundle（含 annotation / review /
split / hidden-label anchor / benchmark 等 label-aware artifacts），那是面向
“整包验收”的入口；ranking/fusion/synthesis 的 **generation** 进程按 W6
No-Leakage 边界不得读取这些 payload。

本模块提供真正的 per-task dependency closure：

- base label-free context 只固定加载
  ``topic_set / retrieval_provenance / source_records / canonical_entities /
  candidate_pool``；
- method artifacts 按当前任务**实际需要**动态解析：fusion 只加载用户传入的
  method manifests；synthesis 只加载所选 method 及其 manifest 中显式声明的
  传递 method_inputs（从 bundle 声明中按 artifact_id 定位并逐层校验）；
- 动态加载不牺牲 trust：每个 method 都经过公共 contract validator
  （schema / ranking hash / method-input chain / pool cardinality），且
  显式 manifest 的 artifact_id 若已被 bundle 冻结记录占用，manifest/ranking
  hash 与 method identity 必须精确一致（fail closed）；
- 每个实际读取的 JSON payload 都经过 ``src/w6_no_leakage`` 的递归
  side-channel guard。

不修改任何共享 contract 文件，只复用它们的 validator。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from src.annotation_tasks import sha256_file
from src.w6_contracts import (
    W6_CONTRACT_NAME,
    W6_CONTRACT_VERSION,
    W6_SCHEMA_VERSION,
    load_json_object,
    validate_candidate_pool,
    validate_canonical_entities,
    validate_retrieval_provenance,
    validate_source_records,
    validate_topic_set,
)
from src.w6_method_contract import validate_w6_method_package
from src.w6_no_leakage import assert_no_label_side_channel


# base label-free context 固定读取的 artifact（method artifacts 按需动态加载）。
BASE_CONTEXT_ARTIFACT_NAMES = (
    "topic_set",
    "retrieval_provenance",
    "source_records",
    "canonical_entities",
    "candidate_pool",
)

# generation 进程绝不得打开的 label-aware artifact 文件名（供文件访问级测试断言）。
LABEL_AWARE_ARTIFACT_NAMES = frozenset(
    {
        "annotation_results.json",
        "annotation_reviews.json",
        "annotation_task_map.json",
        "annotation_tasks.json",
        "split_manifest.json",
        "hidden_label_anchor.json",
        "benchmark_manifest.json",
    }
)

# 公共 contract 允许的 auxiliary input name → base context 中的 artifact 名。
AUXILIARY_INPUT_ARTIFACT_NAMES = {
    "source_records": "source_records",
    "canonical_entities": "canonical_entities",
    "retrieval_provenance": "retrieval_provenance",
}


def _resolve_within_bundle(value: Any, *, bundle_dir: Path) -> Path:
    text = str(value or "").strip()
    if not text or Path(text).is_absolute():
        raise ValueError("artifact path 必须是 bundle 内相对路径。")
    resolved = (bundle_dir / text).resolve()
    try:
        resolved.relative_to(bundle_dir.resolve())
    except ValueError as error:
        raise ValueError("artifact path 不得离开 bundle。") from error
    if not resolved.is_file():
        raise ValueError(f"artifact file 不存在：{resolved}")
    return resolved


def load_w6_base_context(
    bundle_manifest_path: str | Path,
) -> dict[str, Any]:
    """加载 generation 的 base label-free 上下文（不含任何 method artifact）。

    只读取 ``BASE_CONTEXT_ARTIFACT_NAMES`` 声明的 5 个 artifact；bundle manifest
    中其余条目（method manifests、annotation/review/split/hidden-label/benchmark/
    synthesis fixture 等）只保留声明引用、不打开文件。所有读取的 payload 都做
    声明哈希校验、递归 side-channel guard 与 label-free 校验链。

    返回：``registry`` / ``topics`` / ``records`` / ``canonical`` /
    ``pool_members`` / ``paths`` / ``payloads`` / ``bundle_dir`` /
    ``artifact_refs``（bundle 原始声明，供 method 动态解析定位）。
    """
    bundle_path = Path(bundle_manifest_path).resolve()
    bundle_dir = bundle_path.parent
    manifest = load_json_object(bundle_path, label="W6 bundle manifest")
    if manifest.get("schema_version") != W6_SCHEMA_VERSION:
        raise ValueError("W6 bundle schema_version 非法。")
    if (
        manifest.get("contract_name") != W6_CONTRACT_NAME
        or manifest.get("contract_version") != W6_CONTRACT_VERSION
    ):
        raise ValueError("W6 bundle contract name/version 非法。")
    artifact_refs = manifest.get("artifacts")
    if not isinstance(artifact_refs, dict):
        raise ValueError("W6 bundle artifacts 必须是 JSON object。")

    missing = [name for name in BASE_CONTEXT_ARTIFACT_NAMES if name not in artifact_refs]
    if missing:
        raise ValueError(
            "W6 bundle 缺少 generation 必需 artifact：" + ", ".join(missing) + "。"
        )

    registry: dict[str, dict[str, str]] = {}
    paths: dict[str, Path] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for name in BASE_CONTEXT_ARTIFACT_NAMES:
        reference = artifact_refs[name]
        if not isinstance(reference, dict) or set(reference) != {
            "artifact_id",
            "path",
            "sha256",
        }:
            raise ValueError(f"bundle artifact {name} 必须只含 artifact_id/path/sha256。")
        artifact_path = _resolve_within_bundle(reference["path"], bundle_dir=bundle_dir)
        if sha256_file(artifact_path) != reference["sha256"]:
            raise ValueError(f"bundle artifact {name} manifest hash mismatch。")
        artifact_id = reference["artifact_id"]
        registry[artifact_id] = {"artifact_id": artifact_id, "sha256": reference["sha256"]}
        paths[name] = artifact_path
        payload = load_json_object(artifact_path, label=f"bundle artifact {name}")
        if payload.get("artifact_id") != artifact_id:
            raise ValueError(f"bundle artifact {name} identity mismatch。")
        assert_no_label_side_channel(payload, artifact_label=f"bundle artifact {name}")
        payloads[name] = payload

    topics = validate_topic_set(payloads["topic_set"])
    retrieval = validate_retrieval_provenance(
        payloads["retrieval_provenance"], topics=topics
    )
    records = validate_source_records(
        payloads["source_records"], topics=topics, retrieval=retrieval
    )
    canonical = validate_canonical_entities(
        payloads["canonical_entities"], records=records, retrieval=retrieval
    )
    pool_members = validate_candidate_pool(
        payloads["candidate_pool"],
        topics=topics,
        records=records,
        retrieval=retrieval,
        registry=registry,
        canonical=canonical,
    )

    return {
        "registry": registry,
        "topics": topics,
        "records": records,
        "canonical": canonical,
        "pool_members": pool_members,
        "paths": paths,
        "payloads": payloads,
        "bundle_dir": bundle_dir,
        "artifact_refs": artifact_refs,
    }


def _find_bundle_method_entry(
    context: Mapping[str, Any], artifact_id: str
) -> Mapping[str, Any] | None:
    for reference in context["artifact_refs"].values():
        if isinstance(reference, dict) and reference.get("artifact_id") == artifact_id:
            return reference
    return None


def _resolve_method_recursive(
    context: Mapping[str, Any],
    manifest_path: Path,
    *,
    known: dict[str, dict[str, Any]],
    resolving: set[str],
) -> dict[str, Any]:
    """校验一个 method package 及其显式声明的传递 method_inputs（dependency closure）。"""
    manifest_file = Path(manifest_path).resolve()
    manifest_payload = load_json_object(manifest_file, label="W6 method manifest")
    assert_no_label_side_channel(
        manifest_payload, artifact_label=f"method manifest {manifest_file}"
    )
    artifact_id = str(manifest_payload.get("artifact_id") or "")
    if artifact_id in resolving:
        raise ValueError(f"method_inputs 存在循环依赖：{artifact_id}。")
    resolving.add(artifact_id)
    try:
        # 先按声明递归解析传递依赖（从 bundle 声明定位，逐层校验）。
        for item in manifest_payload.get("method_inputs") or []:
            dependency_id = str(item.get("manifest_artifact_id") or "")
            if dependency_id in known:
                continue
            entry = _find_bundle_method_entry(context, dependency_id)
            if entry is None:
                raise ValueError(
                    f"method input {dependency_id} 不在 bundle 声明中，"
                    "无法建立 generation dependency closure。"
                )
            dependency_path = _resolve_within_bundle(
                entry["path"], bundle_dir=context["bundle_dir"]
            )
            if sha256_file(dependency_path) != entry["sha256"]:
                raise ValueError(
                    f"method input {dependency_id} 与 bundle 冻结声明 hash drift。"
                )
            dependency = _resolve_method_recursive(
                context, dependency_path, known=known, resolving=resolving
            )
            if dependency["artifact_id"] != dependency_id:
                raise ValueError(
                    f"method input identity mismatch：{dependency_id}。"
                )
            known[dependency["artifact_id"]] = dependency

        package = validate_w6_method_package(
            manifest_file,
            artifact_registry=context["registry"],
            pool_members=context["pool_members"],
            known_method_packages=known,
        )
    finally:
        resolving.discard(artifact_id)

    # 显式 manifest 的 artifact_id 若已被 bundle 冻结记录占用：
    # manifest/ranking hash 与 method identity 必须与冻结记录精确一致。
    anchor = _find_bundle_method_entry(context, package["artifact_id"])
    if anchor is not None:
        anchor_path = _resolve_within_bundle(
            anchor["path"], bundle_dir=context["bundle_dir"]
        )
        if sha256_file(anchor_path) != anchor["sha256"]:
            raise ValueError(
                f"bundle method artifact {package['artifact_id']} manifest hash drift。"
            )
        if anchor_path != manifest_file:
            anchor_package = _resolve_method_recursive(
                context, anchor_path, known=known, resolving=resolving
            )
            check_frozen_method_identity(
                package, {anchor_package["artifact_id"]: anchor_package}
            )
    known[package["artifact_id"]] = package
    return package


def resolve_method_path(
    context: Mapping[str, Any],
    manifest_path: str | Path,
    *,
    known: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """按显式路径解析 method package 及其传递依赖闭包。"""
    return _resolve_method_recursive(
        context, Path(manifest_path), known=known if known is not None else {}, resolving=set()
    )


def resolve_bundle_method(
    context: Mapping[str, Any],
    artifact_name: str,
    *,
    known: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """按 bundle artifact 名解析 method package 及其传递依赖闭包。"""
    reference = context["artifact_refs"].get(artifact_name)
    if not isinstance(reference, dict) or set(reference) != {
        "artifact_id",
        "path",
        "sha256",
    }:
        raise ValueError(f"bundle 未声明 method artifact：{artifact_name}。")
    manifest_path = _resolve_within_bundle(
        reference["path"], bundle_dir=context["bundle_dir"]
    )
    if sha256_file(manifest_path) != reference["sha256"]:
        raise ValueError(f"bundle method artifact {artifact_name} manifest hash drift。")
    package = _resolve_method_recursive(
        context, manifest_path, known=known if known is not None else {}, resolving=set()
    )
    if package["artifact_id"] != reference["artifact_id"]:
        raise ValueError(f"bundle method artifact {artifact_name} identity mismatch。")
    return package


def validate_method_against_generation_context(
    package: Mapping[str, Any],
    context: Mapping[str, Any],
) -> None:
    """要求 method 的输入引用绑定**当前 context** 的真实 artifact identity。

    不仅比较多个 method 相互之间一致，而是 method → current trusted context：
    ``inputs.topic_set`` / ``inputs.candidate_pool`` 必须精确等于当前 context 的
    Topic Set / Candidate Pool（artifact_id + sha256）；声明使用的每个
    auxiliary input（source_records / canonical_entities / retrieval_provenance）
    也必须等于 context 对应 artifact identity，防止 role-swap。
    """
    registry = context["registry"]
    payloads = context["payloads"]

    def expected_reference(artifact_name: str) -> dict[str, str]:
        artifact_id = payloads[artifact_name]["artifact_id"]
        return {"artifact_id": artifact_id, "sha256": registry[artifact_id]["sha256"]}

    inputs = package["input_references"]
    for name, artifact_name in (("topic_set", "topic_set"), ("candidate_pool", "candidate_pool")):
        expected = expected_reference(artifact_name)
        if inputs.get(name) != expected:
            raise ValueError(
                f"method {package['method_id']} 的 inputs.{name} 未绑定当前 "
                f"generation context 的 {artifact_name} identity（{inputs.get(name)} != {expected}）。"
            )
    for name, reference in package["auxiliary_input_references"].items():
        artifact_name = AUXILIARY_INPUT_ARTIFACT_NAMES.get(name)
        if artifact_name is None:
            raise ValueError(
                f"method {package['method_id']} 声明了未知 auxiliary input：{name}。"
            )
        expected = expected_reference(artifact_name)
        if reference != expected:
            raise ValueError(
                f"method {package['method_id']} 的 auxiliary_inputs.{name} 未绑定当前 "
                f"generation context 的 {artifact_name} identity。"
            )


def check_frozen_method_identity(
    package: Mapping[str, Any],
    frozen_method_packages: Mapping[str, Mapping[str, Any]],
) -> None:
    """同一 artifact_id 不得代表两份不同内容（fail closed）。

    如果显式传入的 method package 的 ``artifact_id`` 已经在冻结记录中存在，
    则 manifest sha、ranking sha、method identity 必须与冻结记录精确一致；
    真正的新 method artifact 必须使用新的 artifact ID 并走显式 freeze 流程。
    """
    frozen = frozen_method_packages.get(package["artifact_id"])
    if frozen is None:
        return
    if (
        package["manifest_sha256"] != frozen["manifest_sha256"]
        or package["ranking_sha256"] != frozen["ranking_sha256"]
        or package["method_id"] != frozen["method_id"]
    ):
        raise ValueError(
            f"method artifact_id {package['artifact_id']} 已被冻结记录占用，"
            "但 manifest/ranking hash 或 method identity 不一致；"
            "新内容必须使用新的 artifact_id，不得覆盖已冻结 identity。"
        )
