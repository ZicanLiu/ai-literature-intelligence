"""W4 个人 Query Relevance 标注文件的数据契约验证。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from src.annotation_tasks import (
    ANNOTATION_TASK_FIELDS,
    ANNOTATORS,
    ASSIGNMENT_FIELDS,
    CANDIDATE_POOL_FIELDS,
    READONLY_TASK_FIELDS,
    read_csv_rows,
    validate_assignment_invariants,
)


VALID_LABELS = {"2", "1", "0", "?"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_EVIDENCE_LEVELS = {"A", "B", "C"}
VALID_AI_ASSISTANCE = {"none", "translation", "explanation", "label_suggestion"}
VALID_SOURCE_CHECKED = {
    "title_abstract",
    "openalex",
    "ads_scix",
    "arxiv",
    "publisher",
    "doi_page",
    "pdf_fulltext",
}
EXTERNAL_SOURCES = VALID_SOURCE_CHECKED.difference({"title_abstract"})


def validate_annotation_file(
    *,
    annotation_path: Path,
    candidate_pool_path: Path,
    assignments_path: Path,
) -> list[str]:
    """只验证格式和数据契约，不判断 label 是否正确。"""
    annotation_path = Path(annotation_path)
    errors: list[str] = []
    try:
        task_fields, task_rows = read_csv_rows(annotation_path)
    except (OSError, UnicodeError, ValueError) as error:
        return [f"标注 CSV 无法读取：{type(error).__name__}"]
    if task_fields != ANNOTATION_TASK_FIELDS:
        errors.append("标注 CSV 表头或字段顺序与 W4 v0.1 契约不一致")

    try:
        pool_fields, candidate_rows = read_csv_rows(candidate_pool_path)
        assignment_fields, assignments = read_csv_rows(assignments_path)
    except (OSError, UnicodeError, ValueError) as error:
        errors.append(f"公共 W4 数据无法读取：{type(error).__name__}")
        return errors
    if pool_fields != CANDIDATE_POOL_FIELDS:
        errors.append("公共 candidate pool 表头无效")
    if assignment_fields != ASSIGNMENT_FIELDS:
        errors.append("公共 assignment 表头无效")
    errors.extend(validate_assignment_invariants(candidate_rows, assignments))

    annotator_slug = annotation_path.stem
    if annotator_slug not in ANNOTATORS:
        errors.append("文件名必须使用已登记的 annotator slug")
        return _deduplicate(errors)

    expected_pairs = {
        row["pair_id"]
        for row in assignments
        if row.get("annotator_slug") == annotator_slug
    }
    actual_pair_ids = [row.get("pair_id", "").strip() for row in task_rows]
    if len(actual_pair_ids) != len(set(actual_pair_ids)):
        errors.append("pair_id 不得重复")
    missing_pairs = sorted(expected_pairs.difference(actual_pair_ids))
    extra_pairs = sorted(set(actual_pair_ids).difference(expected_pairs))
    if missing_pairs:
        errors.append("缺少已分配 pair：" + ", ".join(missing_pairs))
    if extra_pairs:
        errors.append("包含未分配 pair：" + ", ".join(extra_pairs))
    if len(task_rows) != len(expected_pairs):
        errors.append(f"该 annotator 应提交 {len(expected_pairs)} 行，实际 {len(task_rows)} 行")

    pool_by_pair = {row["pair_id"]: row for row in candidate_rows}
    for row_number, row in enumerate(task_rows, start=2):
        pair_id = row.get("pair_id", "").strip()
        if row.get("annotator", "").strip() != annotator_slug:
            errors.append(f"第 {row_number} 行 annotator 与文件名不一致")
        source = pool_by_pair.get(pair_id)
        if source is not None:
            for field in READONLY_TASK_FIELDS:
                if row.get(field, "") != source.get(field, ""):
                    errors.append(f"第 {row_number} 行只读字段被修改：{field}")

        label = row.get("label", "").strip()
        confidence = row.get("confidence", "").strip()
        evidence_level = row.get("evidence_level", "").strip()
        reason = row.get("reason", "").strip()
        source_checked_text = row.get("source_checked", "").strip()
        evidence_url_text = row.get("evidence_url", "").strip()
        ai_assistance = row.get("ai_assistance", "").strip()

        if label not in VALID_LABELS:
            errors.append(f"第 {row_number} 行 label 必须是 2/1/0/?")
        if confidence not in VALID_CONFIDENCE:
            errors.append(f"第 {row_number} 行 confidence 非法")
        if evidence_level not in VALID_EVIDENCE_LEVELS:
            errors.append(f"第 {row_number} 行 evidence_level 非法")
        if not reason:
            errors.append(f"第 {row_number} 行 reason 不能为空")
        if ai_assistance not in VALID_AI_ASSISTANCE:
            errors.append(f"第 {row_number} 行 ai_assistance 非法")

        checked_sources = _split_controlled_values(source_checked_text)
        if not checked_sources:
            errors.append(f"第 {row_number} 行 source_checked 不能为空")
        invalid_sources = sorted(set(checked_sources).difference(VALID_SOURCE_CHECKED))
        if invalid_sources:
            errors.append(f"第 {row_number} 行 source_checked 包含非法值")
        if len(checked_sources) != len(set(checked_sources)):
            errors.append(f"第 {row_number} 行 source_checked 不应重复")

        landing_page_url = row.get("landing_page_url", "").strip()
        if landing_page_url and not _is_http_url(landing_page_url):
            errors.append(f"第 {row_number} 行 landing_page_url 格式非法")
        evidence_urls = _split_controlled_values(evidence_url_text)
        if any(not _is_http_url(value) for value in evidence_urls):
            errors.append(f"第 {row_number} 行 evidence_url 格式非法")

        if evidence_level == "A" and set(checked_sources) != {"title_abstract"}:
            errors.append(f"第 {row_number} 行 A 级证据应只使用 title_abstract")
        if evidence_level in {"B", "C"}:
            if not set(checked_sources).intersection(EXTERNAL_SOURCES):
                errors.append(f"第 {row_number} 行 B/C 级证据必须记录外部来源")
            if not evidence_urls:
                errors.append(f"第 {row_number} 行 B/C 级证据必须填写 evidence_url")
        if evidence_level == "C" and "pdf_fulltext" not in checked_sources:
            errors.append(f"第 {row_number} 行 C 级证据必须记录 pdf_fulltext")

    return _deduplicate(errors)


def annotation_summary(annotation_path: Path) -> dict[str, object]:
    """返回不评价正确性的安全完成度摘要。"""
    _fields, rows = read_csv_rows(annotation_path)
    return {
        "row_count": len(rows),
        "label_counts": dict(Counter(row.get("label", "").strip() for row in rows)),
        "confidence_counts": dict(
            Counter(row.get("confidence", "").strip() for row in rows)
        ),
        "evidence_level_counts": dict(
            Counter(row.get("evidence_level", "").strip() for row in rows)
        ),
        "ai_assistance_counts": dict(
            Counter(row.get("ai_assistance", "").strip() for row in rows)
        ),
    }


def _split_controlled_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _deduplicate(errors: list[str]) -> list[str]:
    return list(dict.fromkeys(errors))
