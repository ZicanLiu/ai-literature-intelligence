"""W6 task-scoped、label-free 的 generation 输入加载器（per-task dependency closure）。

``validate_w6_bootstrap_bundle`` 会解析整个公共 bundle（含 annotation / review /
split / hidden-label anchor / benchmark 等 label-aware artifacts），那是面向
“整包验收”的入口；ranking/fusion/synthesis 的 **generation** 进程按 W6
No-Leakage 边界不得读取这些 payload。

本模块提供真正的 per-task dependency closure 与 trust 边界：

- base label-free context 只固定加载
  ``topic_set / retrieval_provenance / source_records / canonical_entities /
  candidate_pool``；
- bundle manifest 本身做严格结构验证（顶层 exact fields、每个 artifact
  reference exact fields、is_fixture、created_at 时区）， arbitrary metadata
  无法混入 generation 进程；
- 加载时即建立全量 ``artifact_id → entry`` 唯一索引：duplicate artifact_id
  （含 method/非 method 碰撞、same ID 不同 path/SHA）立即 fail closed，
  dependency resolution 不依赖 JSON 顺序；
- method artifacts 按当前任务**实际需要**动态解析：fusion 只加载用户传入的
  method manifests；synthesis 只加载所选 method 及其 manifest 中显式声明的
  传递 method_inputs；显式 manifest 可组成 external dependency graph
  （两阶段：先建 unique explicit artifact_id → path 索引，再解析 DAG，
  与 CLI 参数顺序无关）；
- 每个被解析的 package（含传递 dependency）都绑定当前 generation context
  的真实 artifact identity（topic_set / candidate_pool / auxiliary inputs）；
- 显式 manifest 的 artifact_id 若已被 bundle 冻结记录占用，manifest/ranking
  hash 与 method identity 必须精确一致（fail closed）；
- 每个实际读取的 JSON payload 都经过 ``src/w6_no_leakage`` 的递归
  side-channel guard。

不修改任何共享 contract 文件，只复用它们的 validator。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.annotation_tasks import sha256_file
from src.w6_contracts import (
    PARALLEL_MODULE_FIXTURE_REQUIREMENTS,
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

_BUNDLE_TOP_LEVEL_FIELDS = {
    "schema_version",
    "contract_name",
    "contract_version",
    "bundle_id",
    "is_fixture",
    "created_at",
    "artifacts",
    "parallel_development",
}
_ARTIFACT_REFERENCE_FIELDS = {"artifact_id", "path", "sha256"}


def _require_datetime_with_tz(value: Any, label: str) -> None:
    try:
        parsed = datetime.fromisoformat(str(value or "").strip())
    except ValueError as error:
        raise ValueError(f"{label} 必须是 ISO-8601 时间。") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} 必须包含时区。")


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


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


def _validate_parallel_development_block(value: Any) -> None:
    """复用公共 contract 的 parallel_development 结构约束（P1-1）。

    generation 会解析整个 bundle manifest，因此该块本身必须具备与 full
    Bootstrap validator 等价的结构 guarantee：槽位恰好为六个公共模块、
    每个 entry 只含 depends_on/artifacts、depends_on 只能依赖 w6_bootstrap、
    declared artifact 集合不得偏离公共矩阵——任意 metric / evaluation /
    label metadata 都无法混入。task-scoped subset bundle 合法地只含部分
    artifact，因此不强制 ``artifacts ⊆ 当前 refs``（该闭包由 full validator 负责）。
    """
    if not isinstance(value, dict) or set(value) != set(
        PARALLEL_MODULE_FIXTURE_REQUIREMENTS
    ):
        raise ValueError("parallel_development 必须覆盖六个公共任务槽位。")
    for module_name, requirements in PARALLEL_MODULE_FIXTURE_REQUIREMENTS.items():
        entry = value[module_name]
        if not isinstance(entry, dict) or set(entry) != {"depends_on", "artifacts"}:
            raise ValueError(f"parallel module {module_name} 字段不符合合同。")
        if entry["depends_on"] != ["w6_bootstrap"]:
            raise ValueError(f"{module_name} 不得依赖其他成员尚未合并的 PR/artifact。")
        declared = entry["artifacts"]
        if (
            not isinstance(declared, list)
            or not declared
            or any(not isinstance(item, str) or not item.strip() for item in declared)
        ):
            raise ValueError(f"parallel module {module_name}.artifacts 必须是字符串数组。")
        if set(declared) != requirements:
            raise ValueError(f"{module_name} fixture dependency matrix 漂移。")
    # 纵深防御：该块同样不得携带 label/metric side-channel。
    assert_no_label_side_channel(value, artifact_label="parallel_development")


def _build_artifact_index(
    artifact_refs: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """全量 artifact reference 结构校验 + artifact_id 唯一索引（P1-3）。

    每个 entry 必须精确只含 ``artifact_id / path / sha256`` 且格式合法；
    duplicate artifact_id（含 method/非 method 碰撞、same ID 不同 path/SHA）
    立即 fail closed——artifact identity 不得依赖 JSON 顺序。
    """
    index: dict[str, dict[str, Any]] = {}
    for name, reference in artifact_refs.items():
        if not isinstance(reference, dict) or set(reference) != _ARTIFACT_REFERENCE_FIELDS:
            raise ValueError(
                f"bundle artifact {name} 必须只含 artifact_id/path/sha256。"
            )
        artifact_id = reference["artifact_id"]
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ValueError(f"bundle artifact {name}.artifact_id 非法。")
        if not _is_sha256(reference["sha256"]):
            raise ValueError(f"bundle artifact {name}.sha256 非法。")
        if not isinstance(reference["path"], str) or not reference["path"].strip():
            raise ValueError(f"bundle artifact {name}.path 非法。")
        if artifact_id in index:
            raise ValueError(
                f"bundle duplicate artifact_id：{artifact_id}"
                f"（{index[artifact_id]['name']} 与 {name}）；artifact identity 不得歧义。"
            )
        index[artifact_id] = {"name": name, "reference": reference}
    return index


def load_w6_base_context(
    bundle_manifest_path: str | Path,
) -> dict[str, Any]:
    """加载 generation 的 base label-free 上下文（不含任何 method artifact）。

    bundle manifest 本身做严格结构验证（顶层 exact fields / 每个 artifact
    reference exact fields / is_fixture / created_at 时区），任意 metadata 混入
    即拒绝；只读取 ``BASE_CONTEXT_ARTIFACT_NAMES`` 声明的 5 个 artifact，全部
    经过声明哈希校验、递归 side-channel guard 与 label-free 校验链。

    返回：``registry`` / ``topics`` / ``records`` / ``canonical`` /
    ``pool_members`` / ``paths`` / ``payloads`` / ``bundle_dir`` /
    ``artifact_refs`` / ``artifact_index``（artifact_id → {name, reference}）。
    """
    bundle_path = Path(bundle_manifest_path).resolve()
    bundle_dir = bundle_path.parent
    manifest = load_json_object(bundle_path, label="W6 bundle manifest")
    # 严格结构：顶层只允许合同规定字段，不允许 arbitrary metadata 混入。
    if set(manifest) != _BUNDLE_TOP_LEVEL_FIELDS:
        raise ValueError(
            "W6 bundle manifest 顶层字段不符合合同："
            f"missing={sorted(_BUNDLE_TOP_LEVEL_FIELDS - set(manifest))}, "
            f"extra={sorted(set(manifest) - _BUNDLE_TOP_LEVEL_FIELDS)}。"
        )
    if manifest["schema_version"] != W6_SCHEMA_VERSION:
        raise ValueError("W6 bundle schema_version 非法。")
    if (
        manifest["contract_name"] != W6_CONTRACT_NAME
        or manifest["contract_version"] != W6_CONTRACT_VERSION
    ):
        raise ValueError("W6 bundle contract name/version 非法。")
    if not isinstance(manifest["bundle_id"], str) or not manifest["bundle_id"].strip():
        raise ValueError("W6 bundle bundle_id 非法。")
    if manifest["is_fixture"] is not True:
        raise ValueError("Bootstrap bundle 必须明确标记 synthetic fixture。")
    _require_datetime_with_tz(manifest["created_at"], "bundle created_at")
    _validate_parallel_development_block(manifest["parallel_development"])
    artifact_refs = manifest["artifacts"]
    if not isinstance(artifact_refs, dict):
        raise ValueError("W6 bundle artifacts 必须是 JSON object。")
    artifact_index = _build_artifact_index(artifact_refs)

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
        "artifact_index": artifact_index,
    }


def read_method_manifest_header(manifest_path: str | Path) -> dict[str, Any]:
    """读取 method manifest 的最小 header（artifact_id + method_inputs）。

    用于两阶段 dependency resolution 的 Phase 1：先为全部显式 manifest 建立
    unique ``artifact_id → path`` 索引（duplicate/collision fail closed），
    再解析 dependency DAG，保证结果与 CLI 参数顺序无关。
    """
    manifest_file = Path(manifest_path).resolve()
    payload = load_json_object(manifest_file, label="W6 method manifest")
    assert_no_label_side_channel(
        payload, artifact_label=f"method manifest {manifest_file}"
    )
    return {
        "artifact_id": str(payload.get("artifact_id") or ""),
        "method_inputs": payload.get("method_inputs") or [],
        "manifest_path": manifest_file,
    }


def build_explicit_method_index(
    manifest_paths: list[str | Path],
) -> dict[str, Path]:
    """Phase 1：建立 unique explicit artifact_id → manifest_path 索引。"""
    index: dict[str, Path] = {}
    for manifest_path in manifest_paths:
        header = read_method_manifest_header(manifest_path)
        artifact_id = header["artifact_id"]
        if not artifact_id:
            raise ValueError(f"method manifest 缺少 artifact_id：{manifest_path}。")
        existing = index.get(artifact_id)
        if existing is not None:
            raise ValueError(
                f"显式 manifest artifact_id 重复/冲突：{artifact_id}"
                f"（{existing} 与 {header['manifest_path']}）。"
            )
        index[artifact_id] = header["manifest_path"]
    return index


def _find_dependency_path(
    context: Mapping[str, Any],
    explicit_index: Mapping[str, Path] | None,
    dependency_id: str,
) -> Path:
    """按优先级解析 dependency：显式索引 → bundle 唯一索引。"""
    if explicit_index and dependency_id in explicit_index:
        return explicit_index[dependency_id]
    entry = context["artifact_index"].get(dependency_id)
    if entry is None:
        raise ValueError(
            f"method input {dependency_id} 不在显式输入或 bundle 声明中，"
            "无法建立 generation dependency closure。"
        )
    reference = entry["reference"]
    path = _resolve_within_bundle(reference["path"], bundle_dir=context["bundle_dir"])
    if sha256_file(path) != reference["sha256"]:
        raise ValueError(f"method input {dependency_id} 与 bundle 冻结声明 hash drift。")
    return path


def _resolve_method_recursive(
    context: Mapping[str, Any],
    manifest_path: Path,
    *,
    known: dict[str, dict[str, Any]],
    resolving: set[str],
    explicit_index: Mapping[str, Path] | None,
) -> dict[str, Any]:
    """校验一个 method package 及其显式声明的传递 method_inputs（dependency closure）。

    每个被解析的 package（含传递 dependency）都必须通过公共 contract validator
    并绑定当前 generation context 的真实 artifact identity。
    """
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
        # 先按声明递归解析传递依赖（显式索引 → bundle 唯一索引，逐层校验）。
        for item in manifest_payload.get("method_inputs") or []:
            dependency_id = str(item.get("manifest_artifact_id") or "")
            if dependency_id in known:
                continue
            dependency_path = _find_dependency_path(
                context, explicit_index, dependency_id
            )
            dependency = _resolve_method_recursive(
                context,
                dependency_path,
                known=known,
                resolving=resolving,
                explicit_index=explicit_index,
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
        # 每个被解析的 package（含传递 dependency）都必须绑定当前 context。
        validate_method_against_generation_context(package, context)
    finally:
        resolving.discard(artifact_id)

    # 显式 manifest 的 artifact_id 若已被 bundle 冻结记录占用：
    # manifest/ranking hash 与 method identity 必须与冻结记录精确一致。
    anchor_entry = context["artifact_index"].get(package["artifact_id"])
    if anchor_entry is not None:
        anchor_reference = anchor_entry["reference"]
        anchor_path = _resolve_within_bundle(
            anchor_reference["path"], bundle_dir=context["bundle_dir"]
        )
        if sha256_file(anchor_path) != anchor_reference["sha256"]:
            raise ValueError(
                f"bundle method artifact {package['artifact_id']} manifest hash drift。"
            )
        if anchor_path != manifest_file:
            anchor_package = _resolve_method_recursive(
                context,
                anchor_path,
                known=known,
                resolving=resolving,
                explicit_index=explicit_index,
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
    explicit_index: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """按显式路径解析 method package 及其传递依赖闭包。"""
    return _resolve_method_recursive(
        context,
        Path(manifest_path),
        known=known if known is not None else {},
        resolving=set(),
        explicit_index=explicit_index,
    )


def resolve_bundle_method(
    context: Mapping[str, Any],
    artifact_name: str,
    *,
    known: dict[str, dict[str, Any]] | None = None,
    explicit_index: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """按 bundle artifact 名解析 method package 及其传递依赖闭包。"""
    reference = context["artifact_refs"].get(artifact_name)
    if not isinstance(reference, dict) or set(reference) != _ARTIFACT_REFERENCE_FIELDS:
        raise ValueError(f"bundle 未声明 method artifact：{artifact_name}。")
    manifest_path = _resolve_within_bundle(
        reference["path"], bundle_dir=context["bundle_dir"]
    )
    if sha256_file(manifest_path) != reference["sha256"]:
        raise ValueError(f"bundle method artifact {artifact_name} manifest hash drift。")
    package = _resolve_method_recursive(
        context,
        manifest_path,
        known=known if known is not None else {},
        resolving=set(),
        explicit_index=explicit_index,
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
