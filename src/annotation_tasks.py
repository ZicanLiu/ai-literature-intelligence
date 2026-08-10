"""W4 Pilot candidate pool、双标分配和个人标注任务生成。"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.processor import add_preliminary_scores, clean_papers
from src.ranking import apply_two_stage_ranking


POOL_VERSION = "w4_pilot_v0.1"
SELECTION_ALGORITHM = "w4_stratified_rank_v1"

ANNOTATORS = {
    "liuzican": "刘子璨",
    "wuziheng": "武子恒",
    "jiafucheng": "贾馥诚",
    "chenxingyu": "陈星妤",
    "huangbin": "黄斌",
    "puzhengjie": "蒲正杰",
}

RESEARCH_QUERY_FIELDS = (
    "research_query_id",
    "question_zh",
    "question_en",
    "acquisition_query_ids",
    "ranking_keyword",
    "scope_in",
    "scope_out",
    "description",
)

CANDIDATE_POOL_FIELDS = [
    "pair_id",
    "research_query_id",
    "research_question_zh",
    "research_question_en",
    "acquisition_query_id",
    "openalex_id",
    "title",
    "abstract",
    "landing_page_url",
    "publication_year",
    "doi",
    "source_query_ids",
    "source_run_ids",
    "pool_version",
    "selection_bucket",
]

ASSIGNMENT_FIELDS = [
    "pair_id",
    "annotator_slug",
    "annotator_name",
    "assignment_role",
]

ANNOTATION_TASK_FIELDS = [
    "pair_id",
    "research_query_id",
    "research_question_zh",
    "research_question_en",
    "openalex_id",
    "title",
    "abstract",
    "landing_page_url",
    "publication_year",
    "doi",
    "annotator",
    "label",
    "confidence",
    "evidence_level",
    "reason",
    "source_checked",
    "evidence_url",
    "ai_assistance",
]

READONLY_TASK_FIELDS = [
    "pair_id",
    "research_query_id",
    "research_question_zh",
    "research_question_en",
    "openalex_id",
    "title",
    "abstract",
    "landing_page_url",
    "publication_year",
    "doi",
]

FORBIDDEN_SELECTION_FIELDS = {
    "label",
    "annotation_id",
    "review_status",
    "ai_assistance",
    "hard_negative_label",
}


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """严格读取 UTF-8 CSV，并拒绝空表头、重复表头和损坏行。"""
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        if not fields or any(not field.strip() for field in fields):
            raise ValueError(f"CSV 表头不能为空：{csv_path.name}")
        if len(fields) != len(set(fields)):
            raise ValueError(f"CSV 表头不能重复：{csv_path.name}")
        rows = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"CSV 第 {row_number} 行列数与表头不一致：{csv_path.name}")
            rows.append({field: row.get(field, "") for field in fields})
    return fields, rows


def write_csv_rows(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    """使用 UTF-8 with BOM 和固定字段顺序写入 CSV。"""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def load_research_queries(path: Path) -> dict[str, Any]:
    """读取并校验 W4 research query 配置。"""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("queries"), list):
        raise ValueError("W4 research query 配置必须包含 queries 数组。")
    if payload.get("pilot_version") != POOL_VERSION:
        raise ValueError(f"pilot_version 必须是 {POOL_VERSION}。")
    seen: set[str] = set()
    for index, query in enumerate(payload["queries"], start=1):
        if not isinstance(query, dict):
            raise ValueError(f"第 {index} 个 research query 必须是 JSON object。")
        missing = [field for field in RESEARCH_QUERY_FIELDS if field not in query]
        if missing:
            raise ValueError("research query 缺少字段：" + ", ".join(missing))
        query_id = str(query["research_query_id"]).strip()
        if not query_id or query_id in seen:
            raise ValueError(f"research_query_id 为空或重复：{query_id!r}")
        if not isinstance(query["acquisition_query_ids"], list) or not query[
            "acquisition_query_ids"
        ]:
            raise ValueError(f"{query_id} 必须包含 acquisition_query_ids。")
        if not str(query["ranking_keyword"]).strip():
            raise ValueError(f"{query_id} 必须显式提供 ranking_keyword。")
        for field in ("scope_in", "scope_out"):
            if not isinstance(query[field], list) or not query[field]:
                raise ValueError(f"{query_id} 的 {field} 必须是非空数组。")
        seen.add(query_id)
    if len(payload["queries"]) != 3:
        raise ValueError("W4 Pilot v0.1 必须包含三个 research query。")
    return payload


def build_candidate_pool(
    research_queries_path: Path,
    source_csv_path: Path,
    *,
    reference_year: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """仅依据 retrieval provenance 和现有排序生成 3×20 candidate pair。"""
    query_config = load_research_queries(research_queries_path)
    source_fields, source_rows = read_csv_rows(source_csv_path)
    forbidden = FORBIDDEN_SELECTION_FIELDS.intersection(source_fields)
    if forbidden:
        raise ValueError(
            "候选来源包含禁止用于选样的人工判断字段：" + ", ".join(sorted(forbidden))
        )
    required_source = {
        "openalex_id",
        "title",
        "abstract",
        "landing_page_url",
        "publication_year",
        "doi",
        "source_query_ids",
        "source_run_ids",
    }
    missing_source = required_source.difference(source_fields)
    if missing_source:
        raise ValueError("候选来源缺少字段：" + ", ".join(sorted(missing_source)))

    selected_rows: list[dict[str, Any]] = []
    query_details: dict[str, Any] = {}
    for query_index, query in enumerate(query_config["queries"], start=1):
        research_query_id = str(query["research_query_id"])
        acquisition_ids = [str(value) for value in query["acquisition_query_ids"]]
        if len(acquisition_ids) != 1:
            raise ValueError(
                f"{research_query_id} 的 v0.1 candidate contract 要求一个 acquisition query。"
            )
        acquisition_id = acquisition_ids[0]
        eligible = [
            row
            for row in source_rows
            if acquisition_id in _parse_list_field(row["source_query_ids"])
        ]
        eligible.sort(key=lambda row: (row["openalex_id"], row["title"].casefold()))
        openalex_ids = [row["openalex_id"].strip() for row in eligible]
        if len(openalex_ids) != len(set(openalex_ids)):
            raise ValueError(f"{research_query_id} 的候选来源存在重复 OpenAlex ID。")
        if len(eligible) < 25:
            raise ValueError(
                f"{research_query_id} 只有 {len(eligible)} 条候选，"
                "不足以执行当前 5×4 分层规则。"
            )

        cleaned = clean_papers(eligible, str(query["ranking_keyword"]))
        baseline = add_preliminary_scores(
            cleaned,
            str(query["ranking_keyword"]),
            reference_year=reference_year,
        )
        ranked = apply_two_stage_ranking(baseline, str(query["ranking_keyword"]))
        ranked_by_new = sorted(
            ranked,
            key=lambda paper: (
                int(paper["new_rank"]),
                paper.get("openalex_id") or "",
                paper.get("title") or "",
            ),
        )
        bucketed = _select_stratified_rows(ranked_by_new)
        source_by_id = {row["openalex_id"].strip(): row for row in eligible}

        provisional = []
        for bucket, paper in bucketed:
            source = source_by_id[str(paper["openalex_id"]).strip()]
            provisional.append(
                {
                    "research_query_id": research_query_id,
                    "research_question_zh": str(query["question_zh"]),
                    "research_question_en": str(query["question_en"]),
                    "acquisition_query_id": acquisition_id,
                    "openalex_id": paper["openalex_id"],
                    "title": paper["title"],
                    "abstract": paper["abstract"],
                    "landing_page_url": paper["landing_page_url"],
                    "publication_year": paper["publication_year"],
                    "doi": paper["doi"],
                    "source_query_ids": json.dumps(
                        _parse_list_field(source["source_query_ids"]),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "source_run_ids": json.dumps(
                        _parse_list_field(source["source_run_ids"]),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "pool_version": POOL_VERSION,
                    "selection_bucket": bucket,
                }
            )

        # pair_id 不按排名顺序编号，避免个人标注视图从编号推断 selection bucket。
        provisional.sort(
            key=lambda row: hashlib.sha256(
                (
                    f"{POOL_VERSION}|{research_query_id}|{row['openalex_id']}"
                ).encode("utf-8")
            ).hexdigest()
        )
        for pair_index, row in enumerate(provisional, start=1):
            row["pair_id"] = f"w4_rq{query_index:02d}_{pair_index:03d}"
            selected_rows.append(row)

        query_details[research_query_id] = {
            "acquisition_query_id": acquisition_id,
            "eligible_count": len(eligible),
            "selected_count": len(provisional),
            "bucket_counts": dict(Counter(row["selection_bucket"] for row in provisional)),
        }

    errors = validate_candidate_pool(selected_rows)
    if errors:
        raise ValueError("Candidate Pool 不变量失败：" + "; ".join(errors))
    return selected_rows, query_details


def _select_stratified_rows(
    ranked_by_new: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    """选择 top/middle/bottom/rank-shift 各五条，且不重复。"""
    count = len(ranked_by_new)
    middle_start = (count - 5) // 2
    groups = {
        "top": ranked_by_new[:5],
        "middle": ranked_by_new[middle_start : middle_start + 5],
        "bottom": ranked_by_new[-5:],
    }
    used = {
        str(paper.get("openalex_id") or "")
        for rows in groups.values()
        for paper in rows
    }
    remaining = [
        paper
        for paper in ranked_by_new
        if str(paper.get("openalex_id") or "") not in used
    ]
    remaining.sort(
        key=lambda paper: (
            -abs(int(paper.get("rank_change") or 0)),
            int(paper.get("new_rank") or 0),
            str(paper.get("openalex_id") or ""),
            str(paper.get("title") or "").casefold(),
        )
    )
    groups["rank_shift"] = remaining[:5]
    if any(len(rows) != 5 for rows in groups.values()):
        raise ValueError("分层选样无法为四个 bucket 各提供五条候选。")
    return [
        (bucket, paper)
        for bucket in ("top", "middle", "bottom", "rank_shift")
        for paper in groups[bucket]
    ]


def build_balanced_assignments(
    candidate_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """确定性生成 60 primary + 30 secondary，并平衡六人工作量。"""
    pool_rows = sorted(
        candidate_rows,
        key=lambda row: (str(row["research_query_id"]), str(row["pair_id"])),
    )
    annotator_slugs = list(ANNOTATORS)
    primary_by_pair: dict[str, str] = {}
    assignments: list[dict[str, str]] = []
    for index, row in enumerate(pool_rows):
        slug = annotator_slugs[index % len(annotator_slugs)]
        pair_id = str(row["pair_id"])
        primary_by_pair[pair_id] = slug
        assignments.append(_assignment_row(pair_id, slug, "primary"))

    partnership_counts: Counter[tuple[str, str]] = Counter()
    query_ids = sorted({str(row["research_query_id"]) for row in pool_rows})
    for query_index, research_query_id in enumerate(query_ids):
        query_rows = [
            row for row in pool_rows if row["research_query_id"] == research_query_id
        ]
        secondary_pairs = sorted(
            query_rows,
            key=lambda row: hashlib.sha256(
                f"{POOL_VERSION}|secondary|{row['pair_id']}".encode("utf-8")
            ).hexdigest(),
        )[:10]
        quotas = Counter(
            annotator_slugs[(query_index * 10 + index) % len(annotator_slugs)]
            for index in range(10)
        )
        chosen = _solve_secondary_assignments(
            secondary_pairs,
            quotas,
            primary_by_pair,
            partnership_counts,
        )
        for row, slug in zip(secondary_pairs, chosen):
            pair_id = str(row["pair_id"])
            assignments.append(_assignment_row(pair_id, slug, "secondary"))
            partnership_counts[tuple(sorted((primary_by_pair[pair_id], slug)))] += 1

    assignments.sort(
        key=lambda row: (
            row["pair_id"],
            0 if row["assignment_role"] == "primary" else 1,
        )
    )
    errors = validate_assignment_invariants(candidate_rows, assignments)
    if errors:
        raise ValueError("Assignment 不变量失败：" + "; ".join(errors))
    return assignments


def _solve_secondary_assignments(
    pair_rows: list[dict[str, Any]],
    quotas: Counter[str],
    primary_by_pair: dict[str, str],
    partnership_counts: Counter[tuple[str, str]],
) -> list[str]:
    """在固定每人配额下避免自双标，并尽量分散双标搭档。"""
    chosen: list[str] = []

    def search(index: int) -> bool:
        if index == len(pair_rows):
            return all(value == 0 for value in quotas.values())
        pair_id = str(pair_rows[index]["pair_id"])
        primary = primary_by_pair[pair_id]
        options = [
            slug for slug, remaining in quotas.items() if remaining > 0 and slug != primary
        ]
        options.sort(
            key=lambda slug: (
                partnership_counts[tuple(sorted((primary, slug)))],
                list(ANNOTATORS).index(slug),
            )
        )
        for slug in options:
            quotas[slug] -= 1
            chosen.append(slug)
            if search(index + 1):
                return True
            chosen.pop()
            quotas[slug] += 1
        return False

    if not search(0):
        raise ValueError("无法在既定配额下生成 secondary assignment。")
    return chosen


def validate_candidate_pool(candidate_rows: list[dict[str, Any]]) -> list[str]:
    """检查 W4 v0.1 candidate pool 的冻结不变量。"""
    errors: list[str] = []
    if len(candidate_rows) != 60:
        errors.append(f"candidate pair 应为 60，实际 {len(candidate_rows)}")
    pair_ids = [str(row.get("pair_id") or "") for row in candidate_rows]
    if len(pair_ids) != len(set(pair_ids)) or any(not value for value in pair_ids):
        errors.append("pair_id 必须非空且唯一")
    per_query = Counter(str(row.get("research_query_id") or "") for row in candidate_rows)
    if len(per_query) != 3 or any(count != 20 for count in per_query.values()):
        errors.append(f"每个 research query 必须有 20 pair：{dict(per_query)}")
    query_paper = [
        (str(row.get("research_query_id") or ""), str(row.get("openalex_id") or ""))
        for row in candidate_rows
    ]
    if len(query_paper) != len(set(query_paper)):
        errors.append("同一 research_query_id + openalex_id 不得重复")
    if any(row.get("pool_version") != POOL_VERSION for row in candidate_rows):
        errors.append("所有 pair 必须使用固定 pool_version")
    return errors


def validate_assignment_invariants(
    candidate_rows: list[dict[str, Any]],
    assignments: list[dict[str, str]],
) -> list[str]:
    """检查 60/30/90、每人 15 和独立双标等核心约束。"""
    errors = validate_candidate_pool(candidate_rows)
    pool_by_pair = {str(row["pair_id"]): row for row in candidate_rows}
    if len(assignments) != 90:
        errors.append(f"assignment 应为 90，实际 {len(assignments)}")
    duplicate_keys = [
        (row.get("pair_id", ""), row.get("annotator_slug", "")) for row in assignments
    ]
    if len(duplicate_keys) != len(set(duplicate_keys)):
        errors.append("同一 pair 不能重复分配给同一 annotator")
    unknown_pairs = sorted(
        {row.get("pair_id", "") for row in assignments}.difference(pool_by_pair)
    )
    if unknown_pairs:
        errors.append("assignment 包含 candidate pool 之外的 pair")
    unknown_annotators = sorted(
        {row.get("annotator_slug", "") for row in assignments}.difference(ANNOTATORS)
    )
    if unknown_annotators:
        errors.append("assignment 包含未知 annotator")
    invalid_roles = sorted(
        {
            row.get("assignment_role", "")
            for row in assignments
            if row.get("assignment_role") not in {"primary", "secondary"}
        }
    )
    if invalid_roles:
        errors.append("assignment_role 只能是 primary 或 secondary")
    if any(
        row.get("annotator_slug") in ANNOTATORS
        and row.get("annotator_name") != ANNOTATORS[row["annotator_slug"]]
        for row in assignments
    ):
        errors.append("annotator_name 与 annotator_slug 不匹配")

    by_pair: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in assignments:
        by_pair[row.get("pair_id", "")].append(row)
    secondary_count = 0
    for pair_id in pool_by_pair:
        rows = by_pair.get(pair_id, [])
        primaries = [row for row in rows if row.get("assignment_role") == "primary"]
        secondaries = [row for row in rows if row.get("assignment_role") == "secondary"]
        if len(primaries) != 1:
            errors.append(f"{pair_id} 必须恰有一个 primary")
        if len(secondaries) > 1 or len(rows) > 2:
            errors.append(f"{pair_id} 不得超过两个 annotator")
        if primaries and secondaries and (
            primaries[0].get("annotator_slug") == secondaries[0].get("annotator_slug")
        ):
            errors.append(f"{pair_id} 的 primary 与 secondary 不能相同")
        secondary_count += len(secondaries)
    if secondary_count != 30:
        errors.append(f"secondary assignment 应为 30，实际 {secondary_count}")

    per_annotator = Counter(row.get("annotator_slug", "") for row in assignments)
    if any(per_annotator.get(slug, 0) != 15 for slug in ANNOTATORS):
        errors.append(f"每人必须有 15 条：{dict(per_annotator)}")
    secondary_by_query: Counter[str] = Counter()
    secondary_by_query_annotator: Counter[tuple[str, str]] = Counter()
    partnership_counts: Counter[tuple[str, str]] = Counter()
    for row in assignments:
        if row.get("assignment_role") == "secondary" and row.get("pair_id") in pool_by_pair:
            research_query_id = str(
                pool_by_pair[row["pair_id"]]["research_query_id"]
            )
            secondary_by_query[research_query_id] += 1
            secondary_by_query_annotator[
                (research_query_id, row.get("annotator_slug", ""))
            ] += 1
    if any(count != 10 for count in secondary_by_query.values()) or len(
        secondary_by_query
    ) != 3:
        errors.append(f"每个 research query 必须有 10 个 secondary：{dict(secondary_by_query)}")
    if any(count not in {1, 2} for count in secondary_by_query_annotator.values()) or len(
        secondary_by_query_annotator
    ) != 18:
        errors.append("每个 research query 的 secondary 应在六人间按 1/2 条均衡分配")
    for rows in by_pair.values():
        if len(rows) == 2:
            slugs = tuple(sorted(row.get("annotator_slug", "") for row in rows))
            partnership_counts[slugs] += 1
    if len(partnership_counts) != 15 or max(partnership_counts.values(), default=0) > 3:
        errors.append("双标搭档必须覆盖六人全部 15 种组合，且单一组合不超过 3 条")
    return errors


def bootstrap_w4_files(
    *,
    project_root: Path,
    research_queries_path: Path,
    source_csv_path: Path,
    output_dir: Path,
    reference_year: int,
    force: bool = False,
) -> dict[str, Path]:
    """生成并冻结 candidate pool、assignment、template 和 manifest。"""
    root = Path(project_root).resolve()
    output_dir = Path(output_dir)
    targets = {
        "candidate_pool": output_dir / "candidate_pool_v0.1.csv",
        "assignments": output_dir / "assignments_v0.1.csv",
        "template": output_dir / "annotation_template.csv",
        "manifest": output_dir / "pool_manifest_v0.1.json",
    }
    existing = [path.name for path in targets.values() if path.exists()]
    if existing and not force:
        raise FileExistsError("拒绝覆盖已冻结文件：" + ", ".join(existing))

    candidate_rows, query_details = build_candidate_pool(
        research_queries_path,
        source_csv_path,
        reference_year=reference_year,
    )
    assignments = build_balanced_assignments(candidate_rows)
    write_csv_rows(targets["candidate_pool"], CANDIDATE_POOL_FIELDS, candidate_rows)
    write_csv_rows(targets["assignments"], ASSIGNMENT_FIELDS, assignments)
    write_csv_rows(targets["template"], ANNOTATION_TASK_FIELDS, [])

    per_annotator = Counter(row["annotator_slug"] for row in assignments)
    secondary_by_query: Counter[str] = Counter()
    pool_by_pair = {row["pair_id"]: row for row in candidate_rows}
    assigned_by_pair: dict[str, list[str]] = defaultdict(list)
    for row in assignments:
        assigned_by_pair[row["pair_id"]].append(row["annotator_slug"])
        if row["assignment_role"] == "secondary":
            secondary_by_query[pool_by_pair[row["pair_id"]]["research_query_id"]] += 1
    partnership_counts = Counter(
        "|".join(sorted(slugs))
        for slugs in assigned_by_pair.values()
        if len(slugs) == 2
    )
    manifest = {
        "schema_version": "1.0",
        "pool_version": POOL_VERSION,
        "status": "frozen",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_revision": _git_revision(root),
        "git_revision_note": (
            "生成前的公共基线 HEAD；包含本 manifest 的提交将在人工评审后产生。"
        ),
        "reference_year": reference_year,
        "source_files": [
            {
                "path": _safe_path(Path(source_csv_path), root),
                "sha256": sha256_file(source_csv_path),
            },
            {
                "path": _safe_path(Path(research_queries_path), root),
                "sha256": sha256_file(research_queries_path),
            },
        ],
        "candidate_pair_count": len(candidate_rows),
        "unique_openalex_work_count": len(
            {row["openalex_id"] for row in candidate_rows}
        ),
        "counts_by_research_query": query_details,
        "selection": {
            "algorithm": SELECTION_ALGORITHM,
            "rule": (
                "对每个 acquisition query 的 30 条既有 live 命中重新计算当前 baseline 与"
                "two-stage ranking；选择 new_rank top 5、中间 5、bottom 5，再从剩余记录中"
                "按 abs(rank_change) 降序选择 5 条。"
            ),
            "stable_input_order": "openalex_id, title",
            "stable_tie_break": "abs(rank_change) desc, new_rank, openalex_id, title",
            "pair_id_order": "selected records sorted by SHA-256(pool_version|research_query_id|openalex_id)",
            "manual_labels_used": False,
            "label_leakage_prevention": (
                "未读取 W1/W2 relevance labels、AI-assisted labels、hard negative labels 或"
                "其他人工判断结果；个人任务不包含分数、排名、引用信号或 selection bucket。"
            ),
        },
        "assignment": {
            "algorithm": "w4_balanced_double_annotation_v1",
            "total_count": len(assignments),
            "primary_count": sum(
                row["assignment_role"] == "primary" for row in assignments
            ),
            "secondary_count": sum(
                row["assignment_role"] == "secondary" for row in assignments
            ),
            "per_annotator": dict(per_annotator),
            "secondary_by_research_query": dict(secondary_by_query),
            "partnership_counts": dict(sorted(partnership_counts.items())),
        },
        "artifacts": {
            name: {
                "path": _safe_path(path, root),
                "sha256": sha256_file(path),
            }
            for name, path in targets.items()
            if name != "manifest"
        },
    }
    targets["manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return targets


def create_annotation_task(
    *,
    annotator_slug: str,
    candidate_pool_path: Path,
    assignments_path: Path,
    output_path: Path,
    force: bool = False,
) -> Path:
    """只生成指定 annotator 的任务文件，默认拒绝覆盖。"""
    slug = str(annotator_slug).strip()
    if slug not in ANNOTATORS:
        raise ValueError("未知 annotator：" + slug)
    output_path = Path(output_path)
    if output_path.exists() and not force:
        raise FileExistsError(f"标注文件已存在，拒绝覆盖：{output_path.name}")

    pool_fields, candidate_rows = read_csv_rows(candidate_pool_path)
    assignment_fields, assignments = read_csv_rows(assignments_path)
    if pool_fields != CANDIDATE_POOL_FIELDS:
        raise ValueError("candidate pool 表头与 v0.1 契约不一致。")
    if assignment_fields != ASSIGNMENT_FIELDS:
        raise ValueError("assignment 表头与 v0.1 契约不一致。")
    errors = validate_assignment_invariants(candidate_rows, assignments)
    if errors:
        raise ValueError("公共 assignment 无效：" + "; ".join(errors))

    assigned_pair_ids = sorted(
        row["pair_id"] for row in assignments if row["annotator_slug"] == slug
    )
    if len(assigned_pair_ids) != 15:
        raise ValueError(f"{slug} 应有 15 条任务，实际 {len(assigned_pair_ids)}。")
    pool_by_pair = {row["pair_id"]: row for row in candidate_rows}
    task_rows = []
    for pair_id in assigned_pair_ids:
        source = pool_by_pair[pair_id]
        row = {field: source.get(field, "") for field in READONLY_TASK_FIELDS}
        row.update(
            {
                "annotator": slug,
                "label": "",
                "confidence": "",
                "evidence_level": "",
                "reason": "",
                "source_checked": "",
                "evidence_url": "",
                "ai_assistance": "",
            }
        )
        task_rows.append(row)
    write_csv_rows(output_path, ANNOTATION_TASK_FIELDS, task_rows)
    return output_path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_list_field(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("provenance 字段必须是数组或分号分隔字符串。")
        values = parsed
    else:
        values = text.split(";")
    result = []
    for value_item in values:
        item = str(value_item).strip()
        if item and item not in result:
            result.append(item)
    return result


def _assignment_row(pair_id: str, slug: str, role: str) -> dict[str, str]:
    return {
        "pair_id": pair_id,
        "annotator_slug": slug,
        "annotator_name": ANNOTATORS[slug],
        "assignment_role": role,
    }


def _safe_path(path: Path, project_root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return Path(path).name


def _git_revision(project_root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None
