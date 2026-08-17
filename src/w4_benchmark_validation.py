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

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
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

# These repository-reviewed anchors are deliberately outside the benchmark
# package manifest.  A package cannot bless modified frozen inputs by merely
# updating its own path/hash declarations.
TRUSTED_W4_V01_INPUTS = {
    "pool_manifest": {
        "path": "data/annotation_tasks/w4/pool_manifest_v0.1.json",
        "sha256": "4105ca89174c1705766567c3968c0bd9114fdd13c43309a8eec1cc29547cd405",
    },
    "candidate_pool": {
        "path": "data/annotation_tasks/w4/candidate_pool_v0.1.csv",
        "sha256": "25f608eb4c94218dfa220ba108b15ec846b2bd418174501420a468c376ed17cc",
    },
    "assignments": {
        "path": "data/annotation_tasks/w4/assignments_v0.1.csv",
        "sha256": "5cbeccf6c48c92517df57804d07aa9bcf3f359abad2b4d18d9f7c7b271fa46a2",
    },
    "research_queries": {
        "path": "configs/w4/research_queries.json",
        "sha256": "c77ec74ef4567614d3dfb6dab937b85398f95128cdb29e823587715002d99ab1",
    },
    "source_sample": {
        "path": "data/samples/w2/domain_query/live_query_sample.csv",
        "sha256": "d9179396b22b223e58a730fc41a97f6c7f6a5c976042a97a881e51bc956eda34",
    },
}

TRUSTED_W4_V01_ANNOTATIONS = {
    "liuzican": {
        "path": "data/annotation_tasks/w4/annotations/liuzican.csv",
        "sha256": "c96c7cf6b085632ae2e307674ebe53724f1b2b9248dc241e8149cc63af8c2b52",
    },
    "wuziheng": {
        "path": "data/annotation_tasks/w4/annotations/wuziheng.csv",
        "sha256": "70179464b3cef919f359e3ede6fd29680bf3c2ee165f22cc9d694488ebc31d44",
    },
    "jiafucheng": {
        "path": "data/annotation_tasks/w4/annotations/jiafucheng.csv",
        "sha256": "2c7cd7e9f1e8df26ac2b920883c8b9d5ad7f57157851a330a4d8bee16fa53540",
    },
    "chenxingyu": {
        "path": "data/annotation_tasks/w4/annotations/chenxingyu.csv",
        "sha256": "1ba56d7c1a5476e1fc12a095b563e1fa3994fa092357dca457954784a9ffc14b",
    },
    "huangbin": {
        "path": "data/annotation_tasks/w4/annotations/huangbin.csv",
        "sha256": "5ba5dcb95d1b3f329fa5bab9ae2d87415a5bcf8f5954c0a1b3b268dd80d08abb",
    },
    "puzhengjie": {
        "path": "data/annotation_tasks/w4/annotations/puzhengjie.csv",
        "sha256": "e0d01760f4e5f4ce23e6178761a66e675e8b7ad6877eb6da04129bb680e5674f",
    },
}

TRUSTED_W4_V01_REVIEW_DRAFT = {
    "path": "data/benchmarks/w4_query_relevance/v0.1.0-draft.1/manifest.json",
    "sha256": "6d71d914c88f1dfd7909fdc2d9705e4b238d51f362d1ce16eeda111044e2bd01",
}

APPROVAL_CHECKLIST_FIELDS = (
    "all_disagreements_human_reviewed",
    "original_annotation_provenance_verified",
    "frozen_input_anchor_verified",
    "jiafucheng_provenance_checked",
    "parent_draft_reviewed",
)

BLIND_AUDIT_PROVENANCE_FILES = (
    "blind_manifest",
    "blind_audit",
    "human_ai_comparison",
    "review_queue",
    "comparison_summary",
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

    _validate_frozen_input_anchors(
        inputs=inputs,
        annotations=annotations,
        resolved=resolved,
        annotation_paths=annotation_paths,
        benchmark_reference_year=manifest.get("reference_year"),
    )
    input_set_identity = compute_input_set_identity(inputs)
    if manifest.get("input_set_identity") != input_set_identity:
        raise ValueError(
            "benchmark input_set_identity 与可信冻结输入/annotation hash 不一致。"
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

    _validate_approval_metadata(
        manifest,
        require_approved=require_approved,
    )
    if manifest.get("status") == "approved":
        _validate_blind_ai_audit_provenance(manifest, project_root=root)
        _validate_parent_package(
            manifest=manifest,
            manifest_file=manifest_file,
            project_root=root,
            current_paths=resolved,
            current_input_set_identity=input_set_identity,
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
        "input_set_identity": input_set_identity,
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


def compute_input_set_identity(inputs: dict[str, Any]) -> str:
    """Return a stable identity for the complete frozen W4 input set.

    The caller must validate the values against repository-trusted anchors before
    treating this identity as authoritative.  Keeping the identity separate from
    the package artifact hashes lets an approved package bind exactly to the draft
    that humans reviewed.
    """
    payload = {
        "frozen_inputs": {
            name: {
                "path": str(inputs[name].get("path") or ""),
                "sha256": str(inputs[name].get("sha256") or ""),
            }
            for name in sorted(TRUSTED_W4_V01_INPUTS)
        },
        "annotations": {
            slug: {
                "path": str(inputs["annotations"][slug].get("path") or ""),
                "sha256": str(inputs["annotations"][slug].get("sha256") or ""),
            }
            for slug in sorted(TRUSTED_W4_V01_ANNOTATIONS)
        },
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _validate_frozen_input_anchors(
    *,
    inputs: dict[str, Any],
    annotations: dict[str, Any],
    resolved: dict[str, Path],
    annotation_paths: dict[str, Path],
    benchmark_reference_year: Any,
) -> None:
    """Cross-check package declarations, W4 pool manifest and trusted anchors."""
    for name, trusted in TRUSTED_W4_V01_INPUTS.items():
        declared = inputs.get(name)
        if not isinstance(declared, dict):
            raise ValueError(f"inputs.{name} 必须是 object。")
        if declared.get("path") != trusted["path"]:
            raise ValueError(f"inputs.{name} path 不匹配可信 W4 v0.1 锚点。")
        if declared.get("sha256") != trusted["sha256"]:
            raise ValueError(f"inputs.{name} hash 不匹配可信 W4 v0.1 锚点。")
        if sha256_file(resolved[name]) != trusted["sha256"]:
            raise ValueError(f"inputs.{name} 文件已偏离可信 W4 v0.1 hash 锚点。")

    for slug, trusted in TRUSTED_W4_V01_ANNOTATIONS.items():
        declared = annotations.get(slug)
        if not isinstance(declared, dict):
            raise ValueError(f"inputs.annotations.{slug} 必须是 object。")
        if declared.get("path") != trusted["path"]:
            raise ValueError(f"annotation {slug} path 不匹配可信原始 provenance 锚点。")
        if declared.get("sha256") != trusted["sha256"]:
            raise ValueError(f"annotation {slug} hash 不匹配可信原始 provenance 锚点。")
        if sha256_file(annotation_paths[slug]) != trusted["sha256"]:
            raise ValueError(f"annotation {slug} 文件已偏离可信原始 hash 锚点。")

    try:
        pool_manifest = json.loads(
            resolved["pool_manifest"].read_text(encoding="utf-8-sig")
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"冻结 pool manifest 不是合法 JSON：{error}") from error
    if not isinstance(pool_manifest, dict):
        raise ValueError("冻结 pool manifest 顶层必须是 JSON object。")
    if (
        pool_manifest.get("schema_version") != "1.0"
        or pool_manifest.get("pool_version") != "w4_pilot_v0.1"
        or pool_manifest.get("status") != "frozen"
    ):
        raise ValueError("pool_manifest 不是可信的 frozen W4 v0.1。")
    frozen_reference_year = pool_manifest.get("reference_year")
    if benchmark_reference_year != frozen_reference_year:
        raise ValueError(
            "benchmark reference_year 必须与冻结 pool manifest 一致："
            f"{benchmark_reference_year!r} != {frozen_reference_year!r}。"
        )

    artifact_refs = pool_manifest.get("artifacts")
    source_refs = pool_manifest.get("source_files")
    if not isinstance(artifact_refs, dict) or not isinstance(source_refs, list):
        raise ValueError("pool_manifest 缺少冻结 artifacts/source_files provenance。")
    expected_internal_refs = {
        "candidate_pool": artifact_refs.get("candidate_pool"),
        "assignments": artifact_refs.get("assignments"),
    }
    source_by_path = {
        item.get("path"): item
        for item in source_refs
        if isinstance(item, dict) and item.get("path")
    }
    expected_internal_refs.update(
        {
            "research_queries": source_by_path.get(
                TRUSTED_W4_V01_INPUTS["research_queries"]["path"]
            ),
            "source_sample": source_by_path.get(
                TRUSTED_W4_V01_INPUTS["source_sample"]["path"]
            ),
        }
    )
    for name, internal in expected_internal_refs.items():
        if not isinstance(internal, dict):
            raise ValueError(f"pool_manifest 缺少 {name} 的冻结 provenance。")
        declared = inputs[name]
        if (
            internal.get("path") != declared.get("path")
            or internal.get("sha256") != declared.get("sha256")
        ):
            raise ValueError(f"inputs.{name} 与 pool_manifest 冻结 provenance 不一致。")


def validate_proposal_annotation_provenance(
    proposal: dict[str, str],
    *,
    pool_row: dict[str, str],
    primary: dict[str, str],
    secondary: dict[str, str],
) -> None:
    """Verify proposal evidence against the immutable pool and annotations."""
    pair_id = pool_row["pair_id"]
    expected = {
        "research_query_id": pool_row["research_query_id"],
        "openalex_id": pool_row["openalex_id"],
        "title": pool_row["title"],
        "annotator_a": primary["annotator"],
        "label_a": primary["label"],
        "reason_a": primary["reason"],
        "annotator_b": secondary["annotator"],
        "label_b": secondary["label"],
        "reason_b": secondary["reason"],
    }
    for field, expected_value in expected.items():
        if proposal[field] != expected_value:
            raise ValueError(
                f"adjudication proposal 的 {field} 与原始 annotation provenance "
                f"不一致：{pair_id}。"
            )


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
            if (
                not row["reviewer"].strip()
                or not row["reviewed_at"].strip()
                or not row["review_note"].strip()
            ):
                raise ValueError(
                    f"reviewed proposal 必须记录 reviewer/time/note：{pair_id}。"
                )
            _require_iso8601(row["reviewed_at"], f"proposal reviewed_at ({pair_id})")
            proposed = row["proposed_final_label"].strip()
            reviewed = row["reviewed_label"].strip()
            if row["review_decision"] == "approve" and reviewed != proposed:
                raise ValueError(f"approve proposal 必须采用 proposed label：{pair_id}。")
            if row["review_decision"] == "modify" and reviewed == proposed:
                raise ValueError(f"modify proposal 必须修改 proposed label：{pair_id}。")
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
        primary_annotation = annotation_by_slug[primary["annotator_slug"]][pair_id]
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
            if row["judgement_status"] == "ready":
                if row["judgement_basis"] != "primary_annotation":
                    raise ValueError(
                        f"single annotation judgement provenance 无效：{pair_id}。"
                    )
                if final_label != row["primary_label"]:
                    raise ValueError(
                        f"single annotation judgement 必须来自 primary：{pair_id}。"
                    )
                _require_blank_review_fields(row, pair_id=pair_id)
            elif row["judgement_status"] == "adjudicated":
                _validate_blind_audit_human_override(
                    row,
                    pair_id=pair_id,
                    original_label=row["primary_label"],
                )
            else:
                raise ValueError(
                    f"single annotation 只能是 ready 或完成人工 blind-audit review：{pair_id}。"
                )
        else:
            _compare_annotation_provenance(
                row,
                role="secondary",
                expected_slug=secondary["annotator_slug"],
                annotation_by_slug=annotation_by_slug,
            )
            secondary_annotation = annotation_by_slug[secondary["annotator_slug"]][
                pair_id
            ]
            if row["primary_label"] == row["secondary_label"]:
                if row["agreement_status"] != "agreement":
                    raise ValueError(f"双标一致 pair 的状态必须是 agreement：{pair_id}。")
                if row["judgement_status"] == "ready":
                    if row["judgement_basis"] != "double_annotation_agreement":
                        raise ValueError(f"双标一致 judgement provenance 无效：{pair_id}。")
                    if final_label != row["primary_label"]:
                        raise ValueError(
                            f"双标一致 judgement 必须直接采用共同标签：{pair_id}。"
                        )
                    _require_blank_review_fields(row, pair_id=pair_id)
                elif row["judgement_status"] == "adjudicated":
                    _validate_blind_audit_human_override(
                        row,
                        pair_id=pair_id,
                        original_label=row["primary_label"],
                    )
                else:
                    raise ValueError(
                        f"双标一致 pair 只能是 ready 或完成人工 blind-audit review：{pair_id}。"
                    )
            else:
                disagreement_ids.add(pair_id)
                if row["agreement_status"] != "disagreement":
                    raise ValueError(f"双标分歧 pair 的状态必须是 disagreement：{pair_id}。")
                if row["judgement_basis"] != "ai_adjudication_proposal":
                    raise ValueError(f"双标分歧 judgement basis 无效：{pair_id}。")
                proposal = proposals_by_pair.get(pair_id)
                if proposal is None:
                    raise ValueError(f"双标分歧缺少独立 adjudication proposal：{pair_id}。")
                validate_proposal_annotation_provenance(
                    proposal,
                    pool_row=pool_row,
                    primary=primary_annotation,
                    secondary=secondary_annotation,
                )
                if proposed_label != proposal["proposed_final_label"]:
                    raise ValueError(f"judgement 与 adjudication proposal 标签不一致：{pair_id}。")
                if row["adjudication_ai_assistance"] != "label_suggestion":
                    raise ValueError(f"AI proposal 必须记录 label_suggestion：{pair_id}。")
                if row["judgement_status"] not in {
                    "pending_human_review",
                    "adjudicated",
                }:
                    raise ValueError(
                        f"双标分歧只能是 pending_human_review/adjudicated：{pair_id}。"
                    )
                if row["judgement_status"] == "pending_human_review":
                    if final_label or any(
                        row[field].strip()
                        for field in (
                            "review_decision",
                            "reviewer",
                            "reviewed_at",
                            "review_note",
                        )
                    ):
                        raise ValueError(
                            f"pending adjudication 不得写入人工 final/review：{pair_id}。"
                        )
                    if proposal["proposal_status"] != "pending_human_review":
                        raise ValueError(
                            f"pending judgement 的 proposal 也必须 pending：{pair_id}。"
                        )
                else:
                    if (
                        final_label not in APPROVED_LABELS
                        or not row["reviewer"].strip()
                        or not row["reviewed_at"].strip()
                        or not row["review_note"].strip()
                    ):
                        raise ValueError(
                            f"已 adjudicated pair 必须记录 final/reviewer/time/note：{pair_id}。"
                        )
                    _require_independent_reviewer(row, pair_id=pair_id)
                    _require_iso8601(
                        row["reviewed_at"], f"judgement reviewed_at ({pair_id})"
                    )
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
                        ("review_note", "review_note"),
                    ):
                        if row[judgement_field] != proposal[proposal_field]:
                            raise ValueError(
                                f"judgement 与 proposal 的人工 review provenance 不一致：{pair_id}。"
                            )
                    if row["review_decision"] == "approve" and final_label != proposed_label:
                        raise ValueError(
                            f"approve adjudication 必须采用 AI proposed label：{pair_id}。"
                        )
                    if row["review_decision"] == "modify" and final_label == proposed_label:
                        raise ValueError(
                            f"modify adjudication 必须修改 AI proposed label：{pair_id}。"
                        )

        if require_approved:
            if final_label not in APPROVED_LABELS:
                raise ValueError(f"strict benchmark 要求 60/60 final_label：{pair_id}。")
            if row["judgement_status"] == "pending_human_review":
                raise ValueError(f"strict benchmark 拒绝 pending human review：{pair_id}。")
            if (
                row["agreement_status"] == "disagreement"
                and row["judgement_status"] != "adjudicated"
            ):
                raise ValueError(f"strict benchmark 要求分歧完成人工 adjudication：{pair_id}。")
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


def _require_blank_review_fields(row: dict[str, str], *, pair_id: str) -> None:
    fields = (
        "proposed_label",
        "adjudication_ai_assistance",
        "review_decision",
        "reviewer",
        "reviewed_at",
        "review_note",
    )
    if any(row[field].strip() for field in fields):
        raise ValueError(f"非分歧 judgement 不得包含 adjudication/review 字段：{pair_id}。")


def _validate_blind_audit_human_override(
    row: dict[str, str], *, pair_id: str, original_label: str
) -> None:
    """Validate an explicit human override triggered by the frozen blind audit."""
    if row["judgement_basis"] != "blind_ai_audit_human_review":
        raise ValueError(f"blind-audit override 必须记录独立 review provenance：{pair_id}。")
    if row["final_label"] not in APPROVED_LABELS:
        raise ValueError(f"blind-audit override 必须记录最终 0/1/2：{pair_id}。")
    if row["final_label"] == original_label:
        raise ValueError(f"未修改原 judgement 时不得伪造 blind-audit override：{pair_id}。")
    if row["proposed_label"].strip():
        raise ValueError(f"非原始分歧的 blind-audit override 不得伪造 proposal：{pair_id}。")
    if row["adjudication_ai_assistance"] != "label_suggestion":
        raise ValueError(f"blind-audit override 必须记录 AI label_suggestion provenance：{pair_id}。")
    if row["review_decision"] != "modify":
        raise ValueError(f"blind-audit override 必须记录 modify 决定：{pair_id}。")
    if any(
        not row[field].strip()
        for field in ("reviewer", "reviewed_at", "review_note")
    ):
        raise ValueError(
            f"blind-audit override 必须记录 reviewer/time/note：{pair_id}。"
        )
    _require_independent_reviewer(row, pair_id=pair_id)
    _require_iso8601(row["reviewed_at"], f"blind-audit reviewed_at ({pair_id})")


def _require_independent_reviewer(row: dict[str, str], *, pair_id: str) -> None:
    original_annotators = {
        value
        for value in (row["primary_annotator"], row["secondary_annotator"])
        if value.strip()
    }
    if row["reviewer"] in original_annotators:
        raise ValueError(f"独立 reviewer 不得是该 pair 的原 annotator：{pair_id}。")


def _validate_blind_ai_audit_provenance(
    manifest: dict[str, Any], *, project_root: Path
) -> None:
    provenance = manifest.get("blind_ai_audit_provenance")
    if not isinstance(provenance, dict):
        raise ValueError("approved benchmark 必须保留 Blind AI Audit provenance。")
    if provenance.get("description") != (
        "human annotation + independent blind AI evidence audit + "
        "independent human review/adjudication"
    ):
        raise ValueError("Blind AI Audit provenance description 无效。")
    if (
        provenance.get("blind_phase_completed_before_human_comparison") is not True
        or provenance.get("reviewer_independence_checked") is not True
    ):
        raise ValueError("Blind AI Audit 必须在 human comparison 前冻结并核对 reviewer independence。")
    required_reviews = provenance.get("required_review_count")
    if (
        not isinstance(required_reviews, int)
        or isinstance(required_reviews, bool)
        or required_reviews <= 0
        or provenance.get("completed_review_count") != required_reviews
    ):
        raise ValueError("Blind AI Audit review queue 必须全部完成人工复核。")
    files = provenance.get("files")
    if not isinstance(files, dict) or set(files) != set(BLIND_AUDIT_PROVENANCE_FILES):
        raise ValueError("Blind AI Audit provenance 文件集合不完整。")
    for name in BLIND_AUDIT_PROVENANCE_FILES:
        _validate_file_reference(
            project_root,
            files[name],
            f"blind_ai_audit_provenance.files.{name}",
        )


def _validate_approval_metadata(
    manifest: dict[str, Any], *, require_approved: bool
) -> None:
    """Require package-level approval evidence in addition to row status flags."""
    del require_approved  # status drives the same checks in review and strict modes.
    approval = manifest.get("approval")
    if not isinstance(approval, dict):
        raise ValueError("benchmark manifest 必须包含 approval metadata。")
    checklist = approval.get("checklist")
    if not isinstance(checklist, dict) or set(checklist) != set(
        APPROVAL_CHECKLIST_FIELDS
    ):
        raise ValueError("approval.checklist 必须完整记录 protocol 人工 review checklist。")

    review_provenance = manifest.get("annotation_review_provenance")
    if not isinstance(review_provenance, dict):
        raise ValueError("benchmark manifest 缺少 annotation_review_provenance。")
    chen = review_provenance.get("chenxingyu")
    jia = review_provenance.get("jiafucheng")
    if not isinstance(chen, dict) or chen.get("status") != "human_confirmed":
        raise ValueError("陈星妤 annotation provenance 必须记录本人已审核确认。")
    if (
        not isinstance(jia, dict)
        or jia.get("status") != "human_judgement_with_recorded_ai_assistance"
        or jia.get("github_self_confirmation_recorded") is not False
    ):
        raise ValueError("贾馥诚 provenance 必须准确记录人工判断及 AI 辅助，且不得伪造 GitHub 确认。")

    status = manifest.get("status")
    if status == "proposed":
        if approval.get("status") != "pending_human_review":
            raise ValueError("proposed benchmark 的 approval.status 必须 pending_human_review。")
        if any(
            str(approval.get(field) or "").strip()
            for field in ("approved_by", "approved_at", "review_note")
        ):
            raise ValueError("proposed benchmark 不得伪造 package-level approval。")
        if any(value is not False for value in checklist.values()):
            raise ValueError("proposed benchmark 的 approval checklist 不得提前完成。")
        if manifest.get("parent_package") is not None:
            raise ValueError("proposed draft 不应声明已审核 parent_package。")
        if jia.get("protocol_review_checklist_required") is not True:
            raise ValueError("draft 必须保留贾馥诚 provenance 的人工 review checklist。")
        return

    if approval.get("status") != "approved":
        raise ValueError("approved benchmark 的 approval.status 必须为 approved。")
    if any(value is not True for value in checklist.values()):
        raise ValueError("approved benchmark 必须完成全部 protocol 人工 review checklist。")
    if any(
        not str(approval.get(field) or "").strip()
        for field in ("approved_by", "approved_at", "review_note")
    ):
        raise ValueError("approved benchmark 必须记录 approved_by/approved_at/review_note。")
    _require_iso8601(str(approval["approved_at"]), "approval.approved_at")
    if jia.get("protocol_review_checklist_required") is not False:
        raise ValueError("approved benchmark 必须明确完成贾馥诚 provenance checklist。")
    if any(
        not str(jia.get(field) or "").strip()
        for field in (
            "protocol_review_confirmed_by",
            "protocol_review_confirmed_at",
            "protocol_review_note",
        )
    ):
        raise ValueError("approved benchmark 必须记录贾馥诚 provenance 的人工核验信息。")
    _require_iso8601(
        str(jia["protocol_review_confirmed_at"]),
        "jiafucheng.protocol_review_confirmed_at",
    )


def _require_iso8601(value: str, label: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} 必须是合法 ISO-8601 时间。") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} 必须包含 timezone offset。")


def _validate_parent_package(
    *,
    manifest: dict[str, Any],
    manifest_file: Path,
    project_root: Path,
    current_paths: dict[str, Path],
    current_input_set_identity: str,
) -> None:
    """Bind an approved package to the immutable draft humans actually reviewed."""
    parent_ref = manifest.get("parent_package")
    if not isinstance(parent_ref, dict):
        raise ValueError("approved benchmark 必须声明被人工审核的 parent draft package。")
    if (
        parent_ref.get("path") != TRUSTED_W4_V01_REVIEW_DRAFT["path"]
        or parent_ref.get("sha256") != TRUSTED_W4_V01_REVIEW_DRAFT["sha256"]
    ):
        raise ValueError("parent_package 未绑定经代码审查固定的 W4 v0.1 review draft。")
    parent_manifest = _validate_file_reference(
        project_root,
        parent_ref,
        "parent_package",
    )
    if parent_manifest == manifest_file:
        raise ValueError("approved benchmark 不能把自身声明为 parent draft。")
    parent_result = validate_benchmark_package(
        parent_manifest,
        project_root=project_root,
        require_approved=False,
    )
    parent_payload = parent_result["manifest"]
    if parent_payload.get("status") != "proposed" or "draft" not in str(
        parent_payload.get("benchmark_version") or ""
    ).casefold():
        raise ValueError("approved benchmark 的 parent 必须是 proposed draft package。")
    if parent_ref.get("benchmark_version") != parent_payload.get("benchmark_version"):
        raise ValueError("parent_package benchmark_version 与被审核 draft 不一致。")
    if parent_ref.get("input_set_identity") != parent_result["input_set_identity"]:
        raise ValueError("parent_package input_set_identity 与被审核 draft 不一致。")
    if current_input_set_identity != parent_result["input_set_identity"]:
        raise ValueError("approved benchmark 的冻结 input set 已偏离被审核 draft。")

    parent_paths = parent_result["paths"]
    for artifact_name in ("judgements", "adjudication_proposals"):
        if current_paths[artifact_name] == parent_paths[artifact_name]:
            raise ValueError(
                "approved benchmark 必须在新 package 中保存人工 review 后的 artifact："
                f"{artifact_name}。"
            )

    _compare_parent_artifact_rows(
        current_path=current_paths["judgements"],
        parent_path=parent_paths["judgements"],
        immutable_fields=(
            "pair_id",
            "research_query_id",
            "openalex_id",
            "proposed_label",
            "agreement_status",
            "primary_annotator",
            "primary_label",
            "primary_ai_assistance",
            "secondary_annotator",
            "secondary_label",
            "secondary_ai_assistance",
        ),
        label="judgements",
    )
    _compare_parent_artifact_rows(
        current_path=current_paths["adjudication_proposals"],
        parent_path=parent_paths["adjudication_proposals"],
        immutable_fields=tuple(PROPOSAL_FIELDS[:15]),
        label="adjudication_proposals",
    )


def _compare_parent_artifact_rows(
    *,
    current_path: Path,
    parent_path: Path,
    immutable_fields: tuple[str, ...],
    label: str,
) -> None:
    _current_fields, current_rows = read_csv_rows(current_path)
    _parent_fields, parent_rows = read_csv_rows(parent_path)
    current_by_pair = {row["pair_id"]: row for row in current_rows}
    parent_by_pair = {row["pair_id"]: row for row in parent_rows}
    if set(current_by_pair) != set(parent_by_pair):
        raise ValueError(f"approved {label} pair identity 已偏离 parent draft。")
    for pair_id, parent_row in parent_by_pair.items():
        current_row = current_by_pair[pair_id]
        for field in immutable_fields:
            if current_row[field] != parent_row[field]:
                raise ValueError(
                    f"approved {label}.{field} 已偏离被审核 parent draft：{pair_id}。"
                )


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
