"""W6 extension of the algorithm-neutral W5 ranking contract.

The CSV remains byte-for-byte compatible at the column-contract level with W5.
Only the manifest and cardinality rules are extended for arbitrary topic-level
pools and canonical identity.  Existing W5 validators and frozen artifacts are not
modified or reinterpreted.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from src.annotation_tasks import sha256_file
from src.w5_method_contract import (
    METHOD_FAMILIES,
    METHOD_ID_PATTERN,
    RANKING_FIELDS,
    SCORE_DIRECTION,
    TIE_BREAKING,
)
from src.w6_contracts import (
    GIT_REVISION_PATTERN,
    W6_SCHEMA_VERSION,
    canonical_json_sha256,
    load_json_object,
    validate_artifact_identity_reference,
)


W6_METHOD_CONTRACT_NAME = "w6_method_ranking_extension"
W6_METHOD_CONTRACT_VERSION = "0.2-alpha"
W6_METHOD_ARTIFACT_TYPE = "method_ranking"
W6_RANKING_FIELDS = RANKING_FIELDS
FORBIDDEN_GENERATION_INPUT_NAMES = frozenset(
    {
        "labels",
        "annotations",
        "annotation_results",
        "judgements",
        "benchmark_labels",
        "hidden_labels",
        "hidden_test_labels",
        "error_analysis",
        "metrics",
    }
)
FORBIDDEN_RANKING_FIELDS = frozenset(
    {
        "label",
        "final_label",
        "human_label",
        "judgement",
        "reviewer",
        "annotator",
        "retrieval_method",
    }
)


def compute_method_configuration_hash(manifest: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "compatibility": manifest.get("compatibility"),
            "method": manifest.get("method"),
            "inputs": manifest.get("inputs"),
            "method_inputs": manifest.get("method_inputs"),
            "score_processing": manifest.get("score_processing"),
            "deterministic_seed": (manifest.get("generation") or {}).get(
                "deterministic_seed"
            ),
        }
    )


def validate_w6_method_package(
    manifest_path: str | Path,
    *,
    artifact_registry: Mapping[str, dict[str, str]],
    pool_members: Mapping[str, dict[str, Any]],
    known_method_packages: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate one frozen W6 method package without reading any relevance label."""
    manifest_file = Path(manifest_path).resolve()
    manifest = load_json_object(manifest_file, label="W6 method manifest")
    _require_exact_fields(
        manifest,
        {
            "schema_version",
            "contract_name",
            "contract_version",
            "artifact_type",
            "artifact_id",
            "is_fixture",
            "status",
            "compatibility",
            "method",
            "inputs",
            "method_inputs",
            "score_processing",
            "ranking",
            "freeze",
            "generation",
            "label_access",
        },
        "W6 method manifest",
    )
    if manifest["schema_version"] != W6_SCHEMA_VERSION:
        raise ValueError("W6 method schema_version 非法。")
    if manifest["contract_name"] != W6_METHOD_CONTRACT_NAME:
        raise ValueError("W6 method contract_name 非法。")
    if manifest["contract_version"] != W6_METHOD_CONTRACT_VERSION:
        raise ValueError("W6 method contract_version 非法。")
    if manifest["artifact_type"] != W6_METHOD_ARTIFACT_TYPE:
        raise ValueError("W6 method artifact_type 非法。")
    artifact_id = _require_id(manifest["artifact_id"], "method artifact_id")
    if not isinstance(manifest["is_fixture"], bool):
        raise ValueError("method is_fixture 必须是 boolean。")
    if manifest["status"] != "frozen":
        raise ValueError("W6 method artifact 必须先 frozen 再评价。")

    compatibility = _require_mapping(manifest["compatibility"], "compatibility")
    if compatibility != {
        "base_contract": "w5_method_ranking",
        "base_ranking_schema_version": "1.0",
        "ranking_fields": RANKING_FIELDS,
        "identity_mapping": {
            "pair_id": "pool_item_id",
            "research_query_id": "topic_id",
        },
        "ranking_unit": "source_record",
    }:
        raise ValueError("W6 method compatibility 必须复用 W5 ranking columns/semantics。")

    method = _require_mapping(manifest["method"], "method")
    _require_exact_fields(
        method,
        {"method_id", "display_name", "family", "parameters", "model"},
        "method",
    )
    method_id = _require_id(method["method_id"], "method.method_id")
    if not METHOD_ID_PATTERN.fullmatch(method_id):
        raise ValueError("method_id 不符合 W5-compatible 机器标识规则。")
    _require_nonempty_string(method["display_name"], "method.display_name")
    if method["family"] not in METHOD_FAMILIES:
        raise ValueError("method.family 必须复用 W5 family vocabulary。")
    _require_mapping(method["parameters"], "method.parameters")
    if method["family"] in {"dense", "neural"}:
        model = _require_mapping(method["model"], "method.model")
        _require_exact_fields(model, {"name", "revision", "adapter"}, "method.model")
        _require_nonempty_string(model["name"], "method.model.name")
        _require_nonempty_string(model["revision"], "method.model.revision")
        if model["adapter"] is not None:
            _require_nonempty_string(model["adapter"], "method.model.adapter")
    elif method["model"] is not None and not isinstance(method["model"], dict):
        raise ValueError("method.model 必须是 null 或 object。")

    inputs = _require_mapping(manifest["inputs"], "inputs")
    expected_input_names = {"topic_set", "candidate_pool", "canonical_entities"}
    if set(inputs) != expected_input_names:
        forbidden = sorted(set(inputs).intersection(FORBIDDEN_GENERATION_INPUT_NAMES))
        if forbidden:
            raise ValueError(
                "method generation inputs 包含 labels/analysis 禁止输入："
                + ", ".join(forbidden)
                + "。"
            )
        raise ValueError("W6 method inputs 必须精确绑定 topic/pool/canonical artifacts。")
    for name, reference in inputs.items():
        _validate_registry_reference(reference, artifact_registry, f"inputs.{name}")

    known = known_method_packages or {}
    method_inputs = _require_list(manifest["method_inputs"], "method_inputs")
    seen_input_methods: set[str] = set()
    seen_input_artifacts: set[str] = set()
    for item in method_inputs:
        input_ref = _require_mapping(item, "method input")
        _require_exact_fields(
            input_ref,
            {
                "method_id",
                "manifest_artifact_id",
                "manifest_sha256",
                "ranking_sha256",
                "uses_raw_score",
                "uses_rank",
            },
            "method input",
        )
        input_method_id = _require_id(input_ref["method_id"], "method input method_id")
        input_artifact_id = _require_id(
            input_ref["manifest_artifact_id"], "method input manifest_artifact_id"
        )
        if input_method_id in seen_input_methods or input_artifact_id in seen_input_artifacts:
            raise ValueError("method_inputs 不得重复 method/artifact。")
        seen_input_methods.add(input_method_id)
        seen_input_artifacts.add(input_artifact_id)
        package = known.get(input_artifact_id)
        if package is None:
            raise ValueError(f"method input 未经过独立验证：{input_artifact_id}。")
        if (
            package["method_id"] != input_method_id
            or package["manifest_sha256"] != input_ref["manifest_sha256"]
            or package["ranking_sha256"] != input_ref["ranking_sha256"]
        ):
            raise ValueError(f"method input identity drift：{input_method_id}。")
        if not isinstance(input_ref["uses_raw_score"], bool) or not isinstance(
            input_ref["uses_rank"], bool
        ):
            raise ValueError("method input score/rank usage 必须是 boolean。")
        if not input_ref["uses_raw_score"] and not input_ref["uses_rank"]:
            raise ValueError("method input 必须明确读取 raw score 或 rank。")
    if method_inputs and method["family"] != "hybrid":
        raise ValueError("包含多个冻结 method inputs 的输出必须声明 hybrid family。")

    score_processing = _require_mapping(manifest["score_processing"], "score_processing")
    _require_exact_fields(
        score_processing,
        {"output_score_semantics", "normalization"},
        "score_processing",
    )
    if score_processing["output_score_semantics"] != SCORE_DIRECTION:
        raise ValueError("output score 必须 higher_is_better。")
    normalization = score_processing["normalization"]
    if normalization is not None:
        normalization = _require_mapping(normalization, "normalization")
        _require_exact_fields(
            normalization,
            {"strategy", "parameters", "fit_scope", "label_access"},
            "normalization",
        )
        _require_nonempty_string(normalization["strategy"], "normalization.strategy")
        _require_mapping(normalization["parameters"], "normalization.parameters")
        if normalization["fit_scope"] not in {"per_topic", "global_frozen_pool"}:
            raise ValueError("normalization.fit_scope 非法。")
        if normalization["label_access"] is not False:
            raise ValueError("score normalization 不得读取 relevance labels。")
    if any(item["uses_raw_score"] for item in method_inputs) and normalization is None:
        raise ValueError("读取多个 raw scores 时必须记录 normalization configuration。")

    ranking = _require_mapping(manifest["ranking"], "ranking")
    _require_exact_fields(
        ranking,
        {"path", "sha256", "row_count", "score_direction", "tie_breaking"},
        "ranking",
    )
    ranking_path = _resolve_ranking_path(ranking["path"], manifest_file=manifest_file)
    if not _is_sha256(ranking["sha256"]) or sha256_file(ranking_path) != ranking["sha256"]:
        raise ValueError("W6 ranking hash mismatch。")
    if ranking["score_direction"] != SCORE_DIRECTION or ranking["tie_breaking"] != TIE_BREAKING:
        raise ValueError("W6 ranking 必须复用 W5 score/tie-breaking semantics。")
    fields, rows = _read_csv(ranking_path)
    forbidden_fields = sorted(set(fields).intersection(FORBIDDEN_RANKING_FIELDS))
    if forbidden_fields:
        raise ValueError("ranking CSV 含 label/provenance 禁止字段：" + ", ".join(forbidden_fields) + "。")
    if fields != RANKING_FIELDS:
        raise ValueError("W6 ranking CSV 必须严格复用 W5 五列表头。")
    normalized_rows, counts = _validate_ranking_rows(
        rows, pool_members=pool_members, expected_method_id=method_id
    )
    if ranking["row_count"] != len(normalized_rows) or len(normalized_rows) != len(pool_members):
        raise ValueError("ranking.row_count 必须等于冻结 W6 pool item count。")

    freeze = _require_mapping(manifest["freeze"], "freeze")
    _require_exact_fields(
        freeze,
        {"frozen_at", "configuration_sha256", "evaluation_started_at"},
        "freeze",
    )
    _require_datetime(freeze["frozen_at"], "freeze.frozen_at")
    if freeze["evaluation_started_at"] is not None:
        _require_datetime(freeze["evaluation_started_at"], "freeze.evaluation_started_at")
        if _parse_datetime(freeze["evaluation_started_at"]) <= _parse_datetime(freeze["frozen_at"]):
            raise ValueError("method 必须先 freeze 再 evaluation。")
    if freeze["configuration_sha256"] != compute_method_configuration_hash(manifest):
        raise ValueError("method frozen configuration hash mismatch。")

    generation = _require_mapping(manifest["generation"], "generation")
    _require_exact_fields(
        generation,
        {
            "generated_at",
            "git_revision",
            "git_worktree_clean",
            "dependencies",
            "deterministic_seed",
        },
        "generation",
    )
    _require_datetime(generation["generated_at"], "generation.generated_at")
    if not GIT_REVISION_PATTERN.fullmatch(str(generation["git_revision"])):
        raise ValueError("generation.git_revision 必须是完整 40 位 Git SHA。")
    if generation["git_worktree_clean"] is not True:
        raise ValueError("正式/fixture frozen method 必须声明 clean generation。")
    _require_mapping(generation["dependencies"], "generation.dependencies")
    seed = generation["deterministic_seed"]
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ValueError("generation.deterministic_seed 必须是 integer/null。")

    label_access = _require_mapping(manifest["label_access"], "label_access")
    _require_exact_fields(
        label_access,
        {"relevance_labels_read", "hidden_test_labels_read", "declaration"},
        "label_access",
    )
    if label_access["relevance_labels_read"] is not False or label_access["hidden_test_labels_read"] is not False:
        raise ValueError("ranking/fusion generation 不得读取 dev/hidden relevance labels。")
    _require_nonempty_string(label_access["declaration"], "label_access.declaration")

    return {
        "manifest": manifest,
        "manifest_path": manifest_file,
        "artifact_id": artifact_id,
        "manifest_sha256": sha256_file(manifest_file),
        "ranking_path": ranking_path,
        "ranking_sha256": ranking["sha256"],
        "ranking_rows": normalized_rows,
        "counts_by_topic": dict(counts),
        "method_id": method_id,
        "status": manifest["status"],
        "input_references": inputs,
    }


def _validate_ranking_rows(
    rows: list[dict[str, str]],
    *,
    pool_members: Mapping[str, dict[str, Any]],
    expected_method_id: str,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row_number, row in enumerate(rows, start=2):
        pair_id = row["pair_id"]
        topic_id = row["research_query_id"]
        method_id = row["method_id"]
        if any(value != value.strip() for value in (pair_id, topic_id, method_id)):
            raise ValueError(f"ranking 第 {row_number} 行 identity 不得含首尾空白。")
        if pair_id in seen:
            raise ValueError(f"ranking duplicate pool item：{pair_id}。")
        seen.add(pair_id)
        member = pool_members.get(pair_id)
        if member is None or member["topic_id"] != topic_id:
            raise ValueError(f"ranking candidate identity mismatch：{pair_id}。")
        if method_id != expected_method_id:
            raise ValueError("ranking method_id 混用或与 manifest 不一致。")
        try:
            score = float(row["score"])
        except ValueError as error:
            raise ValueError(f"ranking {pair_id} score 不是数值。") from error
        if not math.isfinite(score):
            raise ValueError(f"ranking {pair_id} score 必须有限。")
        if not row["rank"].isdigit() or str(int(row["rank"])) != row["rank"]:
            raise ValueError(f"ranking {pair_id} rank 必须是规范正整数。")
        rank = int(row["rank"])
        if rank < 1:
            raise ValueError(f"ranking {pair_id} rank 必须为正。")
        item = {
            "pair_id": pair_id,
            "research_query_id": topic_id,
            "method_id": method_id,
            "score": score,
            "rank": rank,
        }
        normalized.append(item)
        by_topic[topic_id].append(item)
    if seen != set(pool_members):
        raise ValueError("ranking 必须完整且唯一覆盖冻结 W6 Candidate Pool。")
    expected_counts = Counter(member["topic_id"] for member in pool_members.values())
    counts = Counter(row["research_query_id"] for row in normalized)
    if counts != expected_counts:
        raise ValueError("ranking topic counts 与 Candidate Pool 不一致。")
    for topic_id, topic_rows in by_topic.items():
        expected_ranks = list(range(1, len(topic_rows) + 1))
        if sorted(row["rank"] for row in topic_rows) != expected_ranks:
            raise ValueError(f"{topic_id} rank 必须完整唯一覆盖 1..N。")
        expected_order = sorted(topic_rows, key=lambda row: (-row["score"], row["pair_id"]))
        for expected_rank, row in enumerate(expected_order, start=1):
            if row["rank"] != expected_rank:
                raise ValueError(f"{topic_id} score/rank 违反 W5 deterministic ordering。")
    return normalized, counts


def _validate_registry_reference(
    value: Any, registry: Mapping[str, dict[str, str]], label: str
) -> None:
    reference = validate_artifact_identity_reference(value, label)
    trusted = registry.get(reference["artifact_id"])
    if trusted is None or trusted["sha256"] != reference["sha256"]:
        raise ValueError(f"{label} identity/hash drift。")


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        if not fields or len(fields) != len(set(fields)):
            raise ValueError("ranking CSV 表头为空或重复。")
        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"ranking CSV 第 {row_number} 行列数损坏。")
            rows.append({field: row.get(field, "") for field in fields})
    return fields, rows


def _resolve_ranking_path(value: Any, *, manifest_file: Path) -> Path:
    text = str(value or "").strip()
    if not text or Path(text).is_absolute():
        raise ValueError("ranking.path 必须是 method package 内相对路径。")
    package = manifest_file.parent.resolve()
    path = (package / text).resolve()
    try:
        path.relative_to(package)
    except ValueError as error:
        raise ValueError("ranking.path 不得离开 method package。") from error
    if not path.is_file():
        raise ValueError(f"ranking file 不存在：{path}")
    return path


def _require_exact_fields(payload: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{label} 字段不符合 contract：missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}。"
        )


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON object。")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是 JSON array。")
    return value


def _require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} 必须是无首尾空白的非空字符串。")
    return value


def _require_id(value: Any, label: str) -> str:
    text = _require_nonempty_string(value, label)
    if not METHOD_ID_PATTERN.fullmatch(text):
        raise ValueError(f"{label} 必须是小写稳定机器标识。")
    return text


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _parse_datetime(value: Any):
    from datetime import datetime

    text = str(value or "").strip()
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("datetime 必须包含时区。")
    return parsed


def _require_datetime(value: Any, label: str) -> None:
    try:
        _parse_datetime(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} 必须是带时区 ISO-8601 时间。") from error
