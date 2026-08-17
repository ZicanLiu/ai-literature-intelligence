"""W4 Pilot Query Relevance judged-set package validation.

The validator has two deliberately separate policies:

* draft validation verifies the frozen inputs, 60-pair identity, provenance and
  proposal structure while allowing unresolved adjudications;
* strict validation additionally requires an approved package and a final
  graded relevance label for every pair.

This separation keeps smoke/partial evaluation useful without allowing a draft
artifact to be mistaken for an approved experiment benchmark.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.annotation_tasks import (
    ANNOTATORS,
    ASSIGNMENT_FIELDS,
    CANDIDATE_POOL_FIELDS,
    load_research_queries,
    read_csv_rows,
    sha256_file,
    validate_assignment_invariants,
)
from src.annotation_validation import validate_annotation_file


BENCHMARK_NAME = "w4_pilot_query_relevance_record_level"
BENCHMARK_VERSION = "w4_query_relevance_pilot_v0.1.0-draft.1"
APPROVED_LABELS = frozenset({"0", "1", "2"})
AI_ASSISTANCE_VALUES = frozenset(
    {"", "none", "translation", "explanation", "label_suggestion"}
)

JUDGEMENT_FIELDS = [
    "pair_id",
    "research_query_id",
    "openalex_id",
    "final_label",
    "proposed_label",
    "judgement_status",
    "agreement_status",
    "judgement_basis",
    "primary_annotator",
    "primary_label",
    "primary_ai_assistance",
    "secondary_annotator",
    "secondary_label",
    "secondary_ai_assistance",
    "adjudication_ai_assistance",
    "review_decision",
    "reviewer",
    "reviewed_at",
    "review_note",
    "benchmark_version",
]

PROPOSAL_FIELDS = [
    "pair_id",
    "research_query_id",
    "openalex_id",
    "title",
    "annotator_a",
    "label_a",
    "reason_a",
    "annotator_b",
    "label_b",
    "reason_b",
    "proposed_final_label",
    "proposal_reason",
    "evidence_level",
    "evidence_sources",
    "confidence",
    "proposal_status",
    "review_decision",
    "reviewed_label",
    "reviewer",
    "reviewed_at",
    "review_note",
]


def validate_benchmark_package(
    manifest_path: str | Path,
    *,
    project_root: str | Path,
    require_approved: bool = True,
) -> dict[str, Any]:
    """Validate a versioned W4 benchmark package and return resolved inputs.

    ``require_approved=False`` is intended only for reviewing a draft package.
    Formal evaluation must use the default strict policy.
    """
    root = Path(project_root).resolve()
    manifest_file = Path(manifest_path).resolve()
    if not manifest_file.is_file():
        raise ValueError(f"benchmark manifest 不存在：{manifest_file}")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise ValueError(f"benchmark manifest 不是合法 JSON：{error}") from error
    if not isinstance(manifest, dict):
        raise ValueError("benchmark manifest 顶层必须是 JSON object。")

    _validate_manifest_identity(manifest, require_approved=require_approved)
    inputs = _require_mapping(manifest, "inputs")
    artifacts = _require_mapping(manifest, "artifacts")

    required_inputs = {
        "candidate_pool",
        "assignments",
        "research_queries",
        "source_sample",
        "pool_manifest",
    }
    missing_inputs = required_inputs.difference(inputs)
    if missing_inputs:
        raise ValueError(
            "benchmark manifest 缺少 inputs：" + ", ".join(sorted(missing_inputs))
        )
    if "judgements" not in artifacts or "adjudication_proposals" not in artifacts:
        raise ValueError(
            "benchmark manifest artifacts 必须包含 judgements 和 adjudication_proposals。"
        )

    resolved: dict[str, Path] = {}
    for name in sorted(required_inputs):
        resolved[name] = _validate_file_reference(
            root, inputs[name], f"inputs.{name}"
        )
    for name in ("judgements", "adjudication_proposals"):
        resolved[name] = _validate_file_reference(
            root, artifacts[name], f"artifacts.{name}"
        )

    annotations = inputs.get("annotations")
    if not isinstance(annotations, dict) or set(annotations) != set(ANNOTATORS):
        raise ValueError("benchmark manifest 必须记录六名 annotator 的原始文件及 hash。")
    annotation_paths: dict[str, Path] = {}
    for slug in ANNOTATORS:
        annotation_paths[slug] = _validate_file_reference(
            root, annotations[slug], f"inputs.annotations.{slug}"
        )

    pool_fields, pool_rows = read_csv_rows(resolved["candidate_pool"])
    assignment_fields, assignments = read_csv_rows(resolved["assignments"])
    if pool_fields != CANDIDATE_POOL_FIELDS:
        raise ValueError("candidate pool 表头与冻结 W4 v0.1 契约不一致。")
    if assignment_fields != ASSIGNMENT_FIELDS:
        raise ValueError("assignments 表头与冻结 W4 v0.1 契约不一致。")
    assignment_errors = validate_assignment_invariants(pool_rows, assignments)
    if assignment_errors:
        raise ValueError("冻结 assignment 无效：" + "; ".join(assignment_errors))

    research_queries = load_research_queries(resolved["research_queries"])
    formal_query_ids = [
        str(query["research_query_id"]) for query in research_queries["queries"]
    ]
    pool_by_pair = {row["pair_id"]: row for row in pool_rows}
    _validate_pool_counts(pool_rows, formal_query_ids)

    annotation_by_slug: dict[str, dict[str, dict[str, str]]] = {}
    for slug, path in annotation_paths.items():
        errors = validate_annotation_file(
            annotation_path=path,
            candidate_pool_path=resolved["candidate_pool"],
            assignments_path=resolved["assignments"],
        )
        if errors:
            raise ValueError(f"原始 annotation {slug} 无效：" + "; ".join(errors))
        _fields, rows = read_csv_rows(path)
        annotation_by_slug[slug] = {row["pair_id"]: row for row in rows}

    judgement_fields, judgement_rows = read_csv_rows(resolved["judgements"])
    if judgement_fields != JUDGEMENT_FIELDS:
        raise ValueError("judgements.csv 表头与 judged-set 契约不一致。")
    proposal_fields, proposal_rows = read_csv_rows(resolved["adjudication_proposals"])
    if proposal_fields != PROPOSAL_FIELDS:
        raise ValueError("adjudication_proposals.csv 表头与复核契约不一致。")

    assignments_by_pair: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in assignments:
        assignments_by_pair[row["pair_id"]].append(row)
    proposals_by_pair = _validate_proposals(proposal_rows, pool_by_pair)
    labels = _validate_judgements(
        judgement_rows,
        pool_by_pair=pool_by_pair,
        assignments_by_pair=assignments_by_pair,
        annotation_by_slug=annotation_by_slug,
        proposals_by_pair=proposals_by_pair,
        benchmark_version=str(manifest.get("benchmark_version") or ""),
        require_approved=require_approved,
    )

    declared_counts = manifest.get("counts")
    actual_statuses = Counter(row["agreement_status"] for row in judgement_rows)
    expected_counts = {
        "pair_count": 60,
        "research_query_count": 3,
        "single_annotation_pairs": actual_statuses["single_annotation"],
        "agreement_pairs": actual_statuses["agreement"],
        "disagreement_pairs": actual_statuses["disagreement"],
        "pending_human_review_pairs": sum(
            row["judgement_status"] == "pending_human_review"
            for row in judgement_rows
        ),
    }
    if declared_counts != expected_counts:
        raise ValueError(
            f"benchmark manifest counts 与 judgements 不一致：{declared_counts!r} != "
            f"{expected_counts!r}。"
        )

    return {
        "manifest": manifest,
        "manifest_path": manifest_file,
        "benchmark_hash": sha256_file(manifest_file),
        "paths": resolved,
        "annotation_paths": annotation_paths,
        "labels": labels,
        "pair_count": len(judgement_rows),
        "counts_by_query": dict(Counter(row["research_query_id"] for row in judgement_rows)),
    }


def _validate_manifest_identity(
    manifest: dict[str, Any], *, require_approved: bool
) -> None:
    if manifest.get("schema_version") != "1.0":
        raise ValueError("benchmark manifest schema_version 必须是 1.0。")
    if manifest.get("benchmark_name") != BENCHMARK_NAME:
        raise ValueError(f"benchmark_name 必须是 {BENCHMARK_NAME}。")
    version = str(manifest.get("benchmark_version") or "").strip()
    if not version:
        raise ValueError("benchmark_version 不能为空。")
    if manifest.get("evaluation_target") != "query_relevance":
        raise ValueError("Pilot Benchmark 只能评价 Query Relevance。")
    if manifest.get("label_scheme") != {
        "type": "graded_relevance",
        "allowed_values": [0, 1, 2],
    }:
        raise ValueError("benchmark label_scheme 必须是 0/1/2 graded relevance。")
    if manifest.get("record_unit") != "research_query_id + openalex_id":
        raise ValueError("benchmark 必须声明 record-level query-paper pair 单位。")
    status = str(manifest.get("status") or "").strip()
    if status not in {"proposed", "approved"}:
        raise ValueError("benchmark status 只能是 proposed 或 approved。")
    if status == "approved" and "draft" in version.casefold():
        raise ValueError("approved benchmark 必须提升为不含 draft 后缀的新版本。")
    if require_approved and status != "approved":
        raise ValueError(
            "strict benchmark 模式拒绝未 approved 的 package；当前 status="
            f"{status!r}。"
        )


def _validate_pool_counts(
    pool_rows: list[dict[str, str]], formal_query_ids: list[str]
) -> None:
    if len(pool_rows) != 60:
        raise ValueError(f"strict benchmark 必须对应 60/60 pair，实际 {len(pool_rows)}。")
    counts = Counter(row["research_query_id"] for row in pool_rows)
    if set(counts) != set(formal_query_ids) or any(
        counts[query_id] != 20 for query_id in formal_query_ids
    ):
        raise ValueError(f"每个 Research Query 必须是 20/20：{dict(counts)}。")


def _validate_proposals(
    rows: list[dict[str, str]], pool_by_pair: dict[str, dict[str, str]]
) -> dict[str, dict[str, str]]:
    proposals: dict[str, dict[str, str]] = {}
    for row in rows:
        pair_id = row["pair_id"].strip()
        if not pair_id or pair_id in proposals:
            raise ValueError("adjudication proposal 的 pair_id 必须非空且唯一。")
        if pair_id not in pool_by_pair:
            raise ValueError(f"adjudication proposal 包含未知 pair：{pair_id}。")
        if row["research_query_id"] != pool_by_pair[pair_id]["research_query_id"]:
            raise ValueError(f"adjudication proposal 的 research_query_id 不匹配：{pair_id}。")
        if row["openalex_id"] != pool_by_pair[pair_id]["openalex_id"]:
            raise ValueError(f"adjudication proposal 的 openalex_id 不匹配：{pair_id}。")
        if row["title"] != pool_by_pair[pair_id]["title"]:
            raise ValueError(f"adjudication proposal 的 title 不匹配：{pair_id}。")
        if row["proposed_final_label"].strip() not in APPROVED_LABELS:
            raise ValueError(f"adjudication proposal 必须给出 0/1/2：{pair_id}。")
        if row["proposal_status"] not in {"pending_human_review", "reviewed"}:
            raise ValueError(f"adjudication proposal 状态无效：{pair_id}。")
        if not row["proposal_reason"].strip() or not row["evidence_sources"].strip():
            raise ValueError(f"adjudication proposal 必须包含理由和证据来源：{pair_id}。")
        if row["proposal_status"] == "pending_human_review":
            if any(
                row[field].strip()
                for field in (
                    "review_decision",
                    "reviewed_label",
                    "reviewer",
                    "reviewed_at",
                    "review_note",
                )
            ):
                raise ValueError(f"pending proposal 不得伪造人工 review：{pair_id}。")
        else:
            if row["review_decision"] not in {"approve", "modify"}:
                raise ValueError(f"reviewed proposal 必须记录 approve/modify：{pair_id}。")
            if row["reviewed_label"].strip() not in APPROVED_LABELS:
                raise ValueError(f"reviewed proposal 必须记录最终 0/1/2：{pair_id}。")
            if not row["reviewer"].strip() or not row["reviewed_at"].strip():
                raise ValueError(f"reviewed proposal 必须记录 reviewer/time：{pair_id}。")
        proposals[pair_id] = row
    return proposals


def _validate_judgements(
    rows: list[dict[str, str]],
    *,
    pool_by_pair: dict[str, dict[str, str]],
    assignments_by_pair: dict[str, list[dict[str, str]]],
    annotation_by_slug: dict[str, dict[str, dict[str, str]]],
    proposals_by_pair: dict[str, dict[str, str]],
    benchmark_version: str,
    require_approved: bool,
) -> dict[str, str]:
    if len(rows) != 60:
        raise ValueError(f"judged set 必须包含 60/60 pair，实际 {len(rows)}。")
    seen: set[str] = set()
    labels: dict[str, str] = {}
    disagreement_ids: set[str] = set()
    for row in rows:
        pair_id = row["pair_id"].strip()
        if not pair_id or pair_id in seen:
            raise ValueError("judged set 的 pair_id 必须非空且唯一。")
        seen.add(pair_id)
        if pair_id not in pool_by_pair:
            raise ValueError(f"judged set 包含未知 pair：{pair_id}。")
        pool_row = pool_by_pair[pair_id]
        if row["research_query_id"] != pool_row["research_query_id"]:
            raise ValueError(f"judgement research_query_id 不匹配：{pair_id}。")
        if row["openalex_id"] != pool_row["openalex_id"]:
            raise ValueError(f"judgement openalex_id 不匹配：{pair_id}。")
        if row["benchmark_version"] != benchmark_version:
            raise ValueError(f"judgement benchmark_version 不匹配：{pair_id}。")

        final_label = row["final_label"].strip()
        proposed_label = row["proposed_label"].strip()
        if row["judgement_status"] not in {
            "ready",
            "pending_human_review",
            "adjudicated",
        }:
            raise ValueError(f"judgement_status 无效：{pair_id}。")
        if final_label and final_label not in APPROVED_LABELS:
            raise ValueError(f"final_label 只能是 0/1/2，不能是 ? 或其他值：{pair_id}。")
        if proposed_label and proposed_label not in APPROVED_LABELS:
            raise ValueError(f"proposed_label 只能是 0/1/2：{pair_id}。")
        for field in (
            "primary_ai_assistance",
            "secondary_ai_assistance",
            "adjudication_ai_assistance",
        ):
            if row[field] not in AI_ASSISTANCE_VALUES:
                raise ValueError(f"{field} 取值无效：{pair_id}。")

        assigned = assignments_by_pair[pair_id]
        primary = next(item for item in assigned if item["assignment_role"] == "primary")
        secondary = next(
            (item for item in assigned if item["assignment_role"] == "secondary"),
            None,
        )
        _compare_annotation_provenance(
            row,
            role="primary",
            expected_slug=primary["annotator_slug"],
            annotation_by_slug=annotation_by_slug,
        )
        if secondary is None:
            if any(
                row[field].strip()
                for field in (
                    "secondary_annotator",
                    "secondary_label",
                    "secondary_ai_assistance",
                )
            ):
                raise ValueError(f"single annotation pair 不得伪造 secondary：{pair_id}。")
            if row["agreement_status"] != "single_annotation":
                raise ValueError(f"single annotation 状态不匹配：{pair_id}。")
            if row["judgement_status"] != "ready" or row["judgement_basis"] != "primary_annotation":
                raise ValueError(f"single annotation judgement provenance 无效：{pair_id}。")
            if final_label != row["primary_label"]:
                raise ValueError(f"single annotation judgement 必须来自 primary：{pair_id}。")
        else:
            _compare_annotation_provenance(
                row,
                role="secondary",
                expected_slug=secondary["annotator_slug"],
                annotation_by_slug=annotation_by_slug,
            )
            if row["primary_label"] == row["secondary_label"]:
                if row["agreement_status"] != "agreement":
                    raise ValueError(f"双标一致 pair 的状态必须是 agreement：{pair_id}。")
                if row["judgement_status"] != "ready" or row["judgement_basis"] != "double_annotation_agreement":
                    raise ValueError(f"双标一致 judgement provenance 无效：{pair_id}。")
                if final_label != row["primary_label"]:
                    raise ValueError(f"双标一致 judgement 必须直接采用共同标签：{pair_id}。")
            else:
                disagreement_ids.add(pair_id)
                if row["agreement_status"] != "disagreement":
                    raise ValueError(f"双标分歧 pair 的状态必须是 disagreement：{pair_id}。")
                if row["judgement_basis"] != "ai_adjudication_proposal":
                    raise ValueError(f"双标分歧 judgement basis 无效：{pair_id}。")
                proposal = proposals_by_pair.get(pair_id)
                if proposal is None:
                    raise ValueError(f"双标分歧缺少独立 adjudication proposal：{pair_id}。")
                if proposed_label != proposal["proposed_final_label"]:
                    raise ValueError(f"judgement 与 adjudication proposal 标签不一致：{pair_id}。")
                if row["adjudication_ai_assistance"] != "label_suggestion":
                    raise ValueError(f"AI proposal 必须记录 label_suggestion：{pair_id}。")
                if row["judgement_status"] == "pending_human_review" and final_label:
                    raise ValueError(f"pending adjudication 不得写入人类 final_label：{pair_id}。")
                if row["judgement_status"] == "adjudicated" and (
                    not final_label or not row["reviewer"].strip() or not row["reviewed_at"].strip()
                ):
                    raise ValueError(f"已 adjudicated pair 必须记录 final/reviewer/time：{pair_id}。")
                if row["judgement_status"] == "adjudicated":
                    if proposal["proposal_status"] != "reviewed":
                        raise ValueError(f"已 adjudicated pair 的 proposal 必须 reviewed：{pair_id}。")
                    if row["review_decision"] not in {"approve", "modify"}:
                        raise ValueError(f"已 adjudicated pair 必须记录 approve/modify：{pair_id}。")
                    if proposal["reviewed_label"] != final_label:
                        raise ValueError(f"proposal reviewed_label 与 final_label 不一致：{pair_id}。")
                    for judgement_field, proposal_field in (
                        ("review_decision", "review_decision"),
                        ("reviewer", "reviewer"),
                        ("reviewed_at", "reviewed_at"),
                    ):
                        if row[judgement_field] != proposal[proposal_field]:
                            raise ValueError(
                                f"judgement 与 proposal 的人工 review provenance 不一致：{pair_id}。"
                            )

        if require_approved:
            if final_label not in APPROVED_LABELS:
                raise ValueError(f"strict benchmark 要求 60/60 final_label：{pair_id}。")
            if row["judgement_status"] == "pending_human_review":
                raise ValueError(f"strict benchmark 拒绝 pending human review：{pair_id}。")
        if final_label:
            labels[pair_id] = final_label

    missing = sorted(set(pool_by_pair).difference(seen))
    if missing:
        raise ValueError("judged set 缺少 candidate pair：" + ", ".join(missing) + "。")
    extra_proposals = sorted(set(proposals_by_pair).difference(disagreement_ids))
    if extra_proposals:
        raise ValueError("adjudication proposal 只能对应真实分歧：" + ", ".join(extra_proposals))
    if set(proposals_by_pair) != disagreement_ids:
        raise ValueError("每个双标分歧必须恰有一个 adjudication proposal。")
    return labels


def _compare_annotation_provenance(
    row: dict[str, str],
    *,
    role: str,
    expected_slug: str,
    annotation_by_slug: dict[str, dict[str, dict[str, str]]],
) -> None:
    pair_id = row["pair_id"]
    if row[f"{role}_annotator"] != expected_slug:
        raise ValueError(f"{role} annotator 与 assignment 不一致：{pair_id}。")
    annotation = annotation_by_slug[expected_slug].get(pair_id)
    if annotation is None:
        raise ValueError(f"原始 annotation 缺少 assigned pair：{pair_id}。")
    if row[f"{role}_label"] != annotation["label"]:
        raise ValueError(f"{role} label 与原始 annotation 不一致：{pair_id}。")
    if row[f"{role}_ai_assistance"] != annotation["ai_assistance"]:
        raise ValueError(f"{role} AI provenance 与原始 annotation 不一致：{pair_id}。")


def _validate_file_reference(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是包含 path/sha256 的 object。")
    relative = Path(str(value.get("path") or ""))
    if not str(relative) or relative.is_absolute():
        raise ValueError(f"{label}.path 必须是项目内相对路径。")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label}.path 不得逃逸项目目录。") from error
    if not resolved.is_file():
        raise ValueError(f"{label}.path 文件不存在：{relative.as_posix()}")
    expected_hash = str(value.get("sha256") or "").strip()
    actual_hash = sha256_file(resolved)
    if expected_hash != actual_hash:
        raise ValueError(
            f"{label} hash 不匹配：expected={expected_hash}, actual={actual_hash}。"
        )
    return resolved


def _require_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"benchmark manifest 的 {key} 必须是 object。")
    return value
