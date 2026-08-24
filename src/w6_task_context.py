"""W6 task-scoped、label-free 的 generation 输入加载器。

``validate_w6_bootstrap_bundle`` 会解析整个公共 bundle（含 annotation / review /
split / hidden-label anchor / benchmark 等 label-aware artifacts）。那是面向
“整包验收”的入口；而 ranking/fusion/synthesis 的 **generation** 进程按 W6
No-Leakage 边界不得读取这些 payload——不是“读了但没用”，而是根本不打开。

本模块提供 generation 专用的最小依赖加载：只读取并哈希校验本任务真实需要的
topic / retrieval provenance / source records / canonical entities / candidate pool /
method artifacts，并按相同的 label-free 校验链验证；bundle manifest 中声明的其他
artifact 只忽略、不打开。

该 loader 不修改任何共享 contract 文件，只是复用它们的 validator。
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


# generation 真实需要的 artifact（label-free 闭包）。
GENERATION_ARTIFACT_NAMES = (
    "topic_set",
    "retrieval_provenance",
    "source_records",
    "canonical_entities",
    "candidate_pool",
    "method_sparse_manifest",
    "method_dense_manifest",
    "method_fusion_manifest",
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

_METHOD_MANIFEST_NAMES = (
    "method_sparse_manifest",
    "method_dense_manifest",
    "method_fusion_manifest",
)


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


def load_w6_generation_context(
    bundle_manifest_path: str | Path,
) -> dict[str, Any]:
    """加载 generation 专用的 label-free W6 上下文。

    只读取 ``GENERATION_ARTIFACT_NAMES`` 声明的 artifact；bundle manifest 中其余
    条目（annotation/review/split/hidden-label/benchmark/synthesis fixture 等）
    只忽略、不打开。所有读取的 artifact 都做 manifest 声明哈希校验，并跑与
    完整 bundle validator 相同的 label-free 校验链。

    返回：``registry`` / ``topics`` / ``records`` / ``canonical`` /
    ``pool_members`` / ``method_packages`` / ``paths`` / ``payloads``。
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

    missing = [name for name in GENERATION_ARTIFACT_NAMES if name not in artifact_refs]
    if missing:
        raise ValueError(
            "W6 bundle 缺少 generation 必需 artifact：" + ", ".join(missing) + "。"
        )

    registry: dict[str, dict[str, str]] = {}
    paths: dict[str, Path] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for name in GENERATION_ARTIFACT_NAMES:
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
        if name not in _METHOD_MANIFEST_NAMES:
            payload = load_json_object(artifact_path, label=f"bundle artifact {name}")
            if payload.get("artifact_id") != artifact_id:
                raise ValueError(f"bundle artifact {name} identity mismatch。")
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

    method_packages: dict[str, dict[str, Any]] = {}
    for name in _METHOD_MANIFEST_NAMES:
        package = validate_w6_method_package(
            paths[name],
            artifact_registry=registry,
            pool_members=pool_members,
            known_method_packages=method_packages,
        )
        expected_artifact_id = artifact_refs[name]["artifact_id"]
        if package["artifact_id"] != expected_artifact_id:
            raise ValueError(
                f"bundle artifact {name} identity mismatch：manifest 内 artifact_id "
                f"{package['artifact_id']} 与 bundle 声明 {expected_artifact_id} 不一致。"
            )
        method_packages[package["artifact_id"]] = package

    return {
        "registry": registry,
        "topics": topics,
        "records": records,
        "canonical": canonical,
        "pool_members": pool_members,
        "method_packages": method_packages,
        "paths": paths,
        "payloads": payloads,
        "bundle_dir": bundle_dir,
    }


def check_frozen_method_identity(
    package: Mapping[str, Any],
    frozen_method_packages: Mapping[str, Mapping[str, Any]],
) -> None:
    """同一 artifact_id 不得代表两份不同内容（fail closed）。

    如果显式传入的 method package 的 ``artifact_id`` 已经在冻结上下文中存在，
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
