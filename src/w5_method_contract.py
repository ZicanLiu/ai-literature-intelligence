"""W5 method-ranking artifact contract and strict validator.

The contract is deliberately algorithm-neutral.  Ranking generation consumes only
the frozen W4 candidate pool and research-query configuration; approved benchmark
judgements are read later by the evaluation stage.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.annotation_tasks import load_research_queries, read_csv_rows, sha256_file
from src.w4_benchmark_validation import TRUSTED_W4_V01_INPUTS


SCHEMA_VERSION = "1.0"
CONTRACT_NAME = "w5_method_ranking"
CONTRACT_VERSION = "1.0"
SCHEMA_VERSION_V11 = "1.1"
CONTRACT_VERSION_V11 = "1.1"
ARTIFACT_TYPE = "method_ranking"

RANKING_FIELDS = [
    "pair_id",
    "research_query_id",
    "method_id",
    "score",
    "rank",
]
RANKING_ROW_COUNT = 60
RANKING_ROWS_PER_QUERY = 20
SCORE_DIRECTION = "higher_is_better"
TIE_BREAKING = ["score_desc", "pair_id_asc"]
METHOD_FAMILIES = frozenset({"baseline", "sparse", "dense", "neural", "hybrid"})
METHOD_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")

FORBIDDEN_RANKING_FIELDS = frozenset(
    {
        "label",
        "final_label",
        "human_label",
        "proposed_label",
        "judgement",
        "judgement_status",
        "judgement_basis",
        "review_decision",
        "reviewer",
        "annotator",
        "adjudication",
    }
)

_TOP_LEVEL_FIELDS = {
    "schema_version",
    "contract_name",
    "contract_version",
    "artifact_type",
    "method",
    "inputs",
    "ranking",
    "generation",
    "label_access",
}
_METHOD_FIELDS = {"method_id", "display_name", "family", "parameters", "model"}
CORE_INPUT_FIELDS = {"candidate_pool", "research_queries"}
_INPUT_FIELDS_BY_VERSION = {
    CONTRACT_VERSION: CORE_INPUT_FIELDS,
    CONTRACT_VERSION_V11: CORE_INPUT_FIELDS | {"source_sample"},
}
_INPUT_REFERENCE_FIELDS = {"path", "sha256", "version"}
_RANKING_REFERENCE_FIELDS = {
    "path",
    "sha256",
    "row_count",
    "score_direction",
    "tie_breaking",
}
_GENERATION_FIELDS = {
    "generated_at",
    "duration_seconds",
    "git_revision",
    "git_worktree_clean",
    "python",
    "platform",
    "dependencies",
}
_PYTHON_FIELDS = {"version", "implementation"}
_PLATFORM_FIELDS = {"system", "release", "machine"}
_LABEL_ACCESS_FIELDS = {"benchmark_labels_read", "declaration"}
_MODEL_FIELDS = {"name", "revision", "adapter"}


def validate_method_output(
    manifest_path: str | Path,
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    """Validate one complete W5 method-output package.

    The returned normalized rows contain numeric ``score`` and ``rank`` values and
    can be passed directly to the W4 evaluator adapter.  This function never reads
    benchmark judgements or labels.
    """
    root = Path(project_root).resolve()
    manifest_file = Path(manifest_path).resolve()
    if not manifest_file.is_file():
        raise ValueError(f"method manifest 不存在：{manifest_file}")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise ValueError(f"method manifest 不是合法 JSON：{error}") from error
    if not isinstance(manifest, dict):
        raise ValueError("method manifest 顶层必须是 JSON object。")

    _validate_manifest(manifest)
    resolved_inputs = _validate_frozen_inputs(
        manifest["inputs"], root=root
    )
    candidate_pool_path = resolved_inputs["candidate_pool"]
    research_queries_path = resolved_inputs["research_queries"]
    ranking_path = _resolve_ranking_path(
        manifest["ranking"]["path"], manifest_file=manifest_file
    )
    declared_ranking_hash = str(manifest["ranking"]["sha256"])
    actual_ranking_hash = sha256_file(ranking_path)
    if actual_ranking_hash != declared_ranking_hash:
        raise ValueError("ranking artifact hash 与 manifest 声明不一致。")

    fields, rows = read_csv_rows(ranking_path)
    forbidden = sorted(set(fields).intersection(FORBIDDEN_RANKING_FIELDS))
    if forbidden:
        raise ValueError(
            "ranking artifact 包含 benchmark label/judgement 禁止字段："
            + ", ".join(forbidden)
            + "。"
        )
    if fields != RANKING_FIELDS:
        raise ValueError(
            "ranking artifact 表头必须严格为：" + ", ".join(RANKING_FIELDS) + "。"
        )

    pool_fields, pool_rows = read_csv_rows(candidate_pool_path)
    required_pool_fields = {"pair_id", "research_query_id"}
    if not required_pool_fields <= set(pool_fields):
        raise ValueError("冻结 Candidate Pool 缺少 pair identity 字段。")
    research_queries = load_research_queries(research_queries_path)
    formal_query_ids = [
        str(item["research_query_id"]) for item in research_queries["queries"]
    ]
    normalized_rows, counts = _validate_ranking_rows(
        rows,
        pool_rows=pool_rows,
        formal_query_ids=formal_query_ids,
        expected_method_id=str(manifest["method"]["method_id"]),
    )
    if manifest["ranking"]["row_count"] != len(normalized_rows):
        raise ValueError("manifest ranking.row_count 与 ranking artifact 实际行数不一致。")

    return {
        "manifest": manifest,
        "manifest_path": manifest_file,
        "manifest_sha256": sha256_file(manifest_file),
        "ranking_path": ranking_path,
        "ranking_sha256": actual_ranking_hash,
        "ranking_rows": normalized_rows,
        "method_id": manifest["method"]["method_id"],
        "counts_by_query": dict(counts),
        "candidate_pool_path": candidate_pool_path,
        "research_queries_path": research_queries_path,
        "input_paths": resolved_inputs,
    }


def _validate_manifest(manifest: dict[str, Any]) -> None:
    _require_exact_fields(manifest, _TOP_LEVEL_FIELDS, "method manifest")
    version_pair = (manifest["schema_version"], manifest["contract_version"])
    supported_version_pairs = {
        (SCHEMA_VERSION, CONTRACT_VERSION),
        (SCHEMA_VERSION_V11, CONTRACT_VERSION_V11),
    }
    if version_pair not in supported_version_pairs:
        raise ValueError(
            "method manifest schema_version/contract_version 必须是 "
            "1.0/1.0 或 1.1/1.1。"
        )
    if manifest["contract_name"] != CONTRACT_NAME:
        raise ValueError(f"contract_name 必须是 {CONTRACT_NAME}。")
    if manifest["artifact_type"] != ARTIFACT_TYPE:
        raise ValueError(f"artifact_type 必须是 {ARTIFACT_TYPE}。")

    method = _require_mapping(manifest, "method")
    _require_exact_fields(method, _METHOD_FIELDS, "method")
    method_id = method["method_id"]
    if (
        not isinstance(method_id, str)
        or method_id != method_id.strip()
        or not METHOD_ID_PATTERN.fullmatch(method_id)
    ):
        raise ValueError(
            "method.method_id 必须是稳定的小写机器标识（a-z、0-9、点、下划线或连字符）。"
        )
    if not _is_nonempty_string(method["display_name"]):
        raise ValueError("method.display_name 不能为空。")
    if method["family"] not in METHOD_FAMILIES:
        raise ValueError("method.family 必须是 baseline/sparse/dense/neural/hybrid。")
    if not isinstance(method["parameters"], dict):
        raise ValueError("method.parameters 必须是 JSON object。")
    model = method["model"]
    if model is not None:
        if not isinstance(model, dict):
            raise ValueError("method.model 必须是 null 或 JSON object。")
        _require_exact_fields(model, _MODEL_FIELDS, "method.model")
        if not _is_nonempty_string(model["name"]) or not _is_nonempty_string(
            model["revision"]
        ):
            raise ValueError("使用预训练模型时必须记录 model name 与 revision。")
        adapter = model["adapter"]
        if adapter is not None and not _is_nonempty_string(adapter):
            raise ValueError("method.model.adapter 必须是 null 或非空字符串。")
    if method["family"] in {"dense", "neural"} and model is None:
        raise ValueError("dense/neural method 必须记录预训练 model name/revision/adapter。")

    inputs = _require_mapping(manifest, "inputs")
    input_fields = _INPUT_FIELDS_BY_VERSION[manifest["contract_version"]]
    _require_exact_fields(inputs, input_fields, "inputs")
    for name in sorted(input_fields):
        reference = _require_mapping(inputs, name)
        _require_exact_fields(reference, _INPUT_REFERENCE_FIELDS, f"inputs.{name}")

    ranking = _require_mapping(manifest, "ranking")
    _require_exact_fields(ranking, _RANKING_REFERENCE_FIELDS, "ranking")
    if ranking["row_count"] != RANKING_ROW_COUNT:
        raise ValueError(f"ranking.row_count 必须是 {RANKING_ROW_COUNT}。")
    if ranking["score_direction"] != SCORE_DIRECTION:
        raise ValueError(f"ranking.score_direction 必须是 {SCORE_DIRECTION}。")
    if ranking["tie_breaking"] != TIE_BREAKING:
        raise ValueError(f"ranking.tie_breaking 必须是 {TIE_BREAKING}。")
    if not _is_sha256(ranking["sha256"]):
        raise ValueError("ranking.sha256 必须是 64 位小写 SHA-256。")

    generation = _require_mapping(manifest, "generation")
    _require_exact_fields(generation, _GENERATION_FIELDS, "generation")
    _require_timezone_datetime(generation["generated_at"], "generation.generated_at")
    duration = generation["duration_seconds"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(float(duration))
        or float(duration) < 0
    ):
        raise ValueError("generation.duration_seconds 必须是有限非负数。")
    revision = generation["git_revision"]
    if not isinstance(revision, str) or not GIT_REVISION_PATTERN.fullmatch(revision):
        raise ValueError("generation.git_revision 必须是完整 40 位小写 Git SHA。")
    if generation["git_worktree_clean"] is not True:
        raise ValueError("正式 method ranking 必须在 clean Git 工作树生成。")
    python = _require_mapping(generation, "python")
    _require_exact_fields(python, _PYTHON_FIELDS, "generation.python")
    if any(not _is_nonempty_string(python[field]) for field in _PYTHON_FIELDS):
        raise ValueError("generation.python 必须记录 version 与 implementation。")
    platform = _require_mapping(generation, "platform")
    _require_exact_fields(platform, _PLATFORM_FIELDS, "generation.platform")
    if any(not _is_nonempty_string(platform[field]) for field in _PLATFORM_FIELDS):
        raise ValueError("generation.platform 必须记录 system/release/machine。")
    dependencies = generation["dependencies"]
    if not isinstance(dependencies, dict):
        raise ValueError("generation.dependencies 必须是 JSON object。")
    for name, version in dependencies.items():
        if not _is_nonempty_string(name) or (
            version is not None and not _is_nonempty_string(version)
        ):
            raise ValueError("generation.dependencies 的名称/版本必须是非空字符串或 null。")

    label_access = _require_mapping(manifest, "label_access")
    _require_exact_fields(label_access, _LABEL_ACCESS_FIELDS, "label_access")
    if label_access["benchmark_labels_read"] is not False:
        raise ValueError("ranking generation 必须声明未读取 approved benchmark labels。")
    if not _is_nonempty_string(label_access["declaration"]):
        raise ValueError("label_access.declaration 不能为空。")


def _validate_frozen_inputs(
    inputs: dict[str, Any], *, root: Path
) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    expected_versions = {
        "candidate_pool": "w4_pilot_v0.1",
        "research_queries": "w4_pilot_v0.1",
        "source_sample": "w2_live_query_sample_v1",
    }
    for manifest_name in sorted(inputs):
        reference = inputs[manifest_name]
        trusted = TRUSTED_W4_V01_INPUTS[manifest_name]
        if reference["path"] != trusted["path"]:
            raise ValueError(f"inputs.{manifest_name}.path 偏离冻结 W4 v0.1 输入。")
        if reference["sha256"] != trusted["sha256"]:
            raise ValueError(f"inputs.{manifest_name}.sha256 偏离冻结 W4 v0.1 hash。")
        expected_version = expected_versions[manifest_name]
        if reference["version"] != expected_version:
            raise ValueError(
                f"inputs.{manifest_name}.version 必须是 {expected_version}。"
            )
        path = _resolve_project_path(reference["path"], root=root)
        if sha256_file(path) != trusted["sha256"]:
            raise ValueError(f"inputs.{manifest_name} 文件已发生 hash 漂移。")
        resolved[manifest_name] = path
    return resolved


def _validate_ranking_rows(
    rows: list[dict[str, str]],
    *,
    pool_rows: list[dict[str, str]],
    formal_query_ids: list[str],
    expected_method_id: str,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    row_count = len(rows)
    pool_by_pair = {row["pair_id"]: row["research_query_id"] for row in pool_rows}
    if len(pool_by_pair) != RANKING_ROW_COUNT:
        raise ValueError("冻结 Candidate Pool 的 pair identity 不是 60 条唯一记录。")

    seen_pairs: set[str] = set()
    normalized: list[dict[str, Any]] = []
    by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row_number, row in enumerate(rows, start=2):
        pair_id = row["pair_id"].strip()
        query_id = row["research_query_id"].strip()
        method_id = row["method_id"].strip()
        if any(
            row[field] != row[field].strip()
            for field in ("pair_id", "research_query_id", "method_id")
        ):
            raise ValueError(
                f"ranking CSV 第 {row_number} 行的 identity 字段不得有首尾空白。"
            )
        if not pair_id:
            raise ValueError(f"ranking CSV 第 {row_number} 行缺少 pair_id。")
        if pair_id in seen_pairs:
            raise ValueError(f"ranking artifact duplicate pair：{pair_id}。")
        seen_pairs.add(pair_id)
        if pair_id not in pool_by_pair:
            raise ValueError(f"ranking artifact 包含未知 pair：{pair_id}。")
        expected_query_id = pool_by_pair[pair_id]
        if query_id != expected_query_id:
            raise ValueError(
                f"pair {pair_id} 的 research_query_id 与冻结 Candidate Pool 不一致。"
            )
        if method_id != expected_method_id:
            raise ValueError(
                f"ranking artifact method_id 不统一或与 manifest 不一致：{method_id!r}。"
            )
        score_text = row["score"].strip()
        try:
            score = float(score_text)
        except ValueError as error:
            raise ValueError(f"pair {pair_id} 的 score 不是数值。") from error
        if not math.isfinite(score):
            raise ValueError(f"pair {pair_id} 的 score 必须是有限数值。")
        rank_text = row["rank"].strip()
        if not rank_text.isdigit() or str(int(rank_text)) != rank_text:
            raise ValueError(f"pair {pair_id} 的 rank 必须是规范正整数。")
        rank = int(rank_text)
        if rank < 1 or rank > RANKING_ROWS_PER_QUERY:
            raise ValueError(f"pair {pair_id} 的 rank 必须在 1..20。")
        normalized_row = {
            "pair_id": pair_id,
            "research_query_id": query_id,
            "method_id": method_id,
            "score": score,
            "rank": rank,
        }
        normalized.append(normalized_row)
        by_query[query_id].append(normalized_row)

    missing_pairs = sorted(set(pool_by_pair).difference(seen_pairs))
    if missing_pairs:
        raise ValueError(
            f"method ranking 必须恰好 {RANKING_ROW_COUNT} 条，实际 {row_count} 条；"
            "缺失冻结 pair："
            + ", ".join(missing_pairs)
            + "。"
        )
    if row_count != RANKING_ROW_COUNT:
        raise ValueError(
            f"method ranking 必须恰好 {RANKING_ROW_COUNT} 条，实际 {row_count} 条。"
        )
    counts = Counter(row["research_query_id"] for row in normalized)
    if set(counts) != set(formal_query_ids) or any(
        counts[query_id] != RANKING_ROWS_PER_QUERY for query_id in formal_query_ids
    ):
        raise ValueError(f"每个 Research Query 必须恰好 20 条：{dict(counts)}。")

    for query_id in formal_query_ids:
        query_rows = by_query[query_id]
        ranks = [row["rank"] for row in query_rows]
        if sorted(ranks) != list(range(1, RANKING_ROWS_PER_QUERY + 1)):
            raise ValueError(f"{query_id} 的 rank 必须完整且唯一覆盖 1..20。")
        expected_order = sorted(
            query_rows, key=lambda row: (-row["score"], row["pair_id"])
        )
        for expected_rank, row in enumerate(expected_order, start=1):
            if row["rank"] != expected_rank:
                raise ValueError(
                    f"{query_id} 的 score/rank 不符合 higher-is-better 与 "
                    "pair_id 升序 tie-breaking。"
                )
    return normalized, counts


def _resolve_project_path(value: Any, *, root: Path) -> Path:
    text = str(value or "").strip()
    if not text or Path(text).is_absolute():
        raise ValueError("冻结输入 path 必须是项目内相对路径。")
    resolved = (root / text).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("冻结输入 path 不得离开项目目录。") from error
    if not resolved.is_file():
        raise ValueError(f"冻结输入文件不存在：{resolved}")
    return resolved


def _resolve_ranking_path(value: Any, *, manifest_file: Path) -> Path:
    text = str(value or "").strip()
    if not text or Path(text).is_absolute():
        raise ValueError("ranking.path 必须是相对 method manifest 的包内路径。")
    package_dir = manifest_file.parent.resolve()
    resolved = (package_dir / text).resolve()
    try:
        resolved.relative_to(package_dir)
    except ValueError as error:
        raise ValueError("ranking.path 不得离开 method output package。") from error
    if not resolved.is_file():
        raise ValueError(f"ranking artifact 不存在：{resolved}")
    return resolved


def _require_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} 必须是 JSON object。")
    return value


def _require_exact_fields(
    payload: dict[str, Any], expected: set[str], label: str
) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected.difference(actual))
        extra = sorted(actual.difference(expected))
        details = []
        if missing:
            details.append("缺少 " + ", ".join(missing))
        if extra:
            details.append("未知 " + ", ".join(extra))
        raise ValueError(f"{label} 字段不符合 schema：" + "；".join(details) + "。")


def _is_sha256(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "")))


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_timezone_datetime(value: Any, label: str) -> None:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{label} 必须是 ISO-8601 时间。") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} 必须包含时区。")
