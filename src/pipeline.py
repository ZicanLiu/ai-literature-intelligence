"""W2 统一文献处理 Pipeline。

该模块只编排现有领域查询、OpenAlex v2、清洗、两级去重、baseline、
TF-IDF 两阶段排序和可选评价，不复制或调整各成员提交的研究算法。
"""

from __future__ import annotations

import csv
import json
import platform
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.ranking import (
    COMPARISON_FIELDS,
    ERROR_CASE_FIELDS,
    STAGE1_HIGH_THRESHOLD,
    STAGE1_LEVEL_GATE,
    STAGE1_MEDIUM_THRESHOLD,
    STAGE2_SCORE_WEIGHTS,
    apply_two_stage_ranking,
    build_comparison_rows,
    select_ranking_error_cases,
)
from src.deduplication import find_exact_duplicates, find_suspected_duplicates
from src.domain_query import build_query_set, load_domain_terms, write_query_set
from src.evaluation import evaluate_ranking
from src.openalex_client_v2 import fetch_openalex_papers_v2
from src.processor import OUTPUT_FIELDS, PRELIMINARY_SCORE_WEIGHTS, add_preliminary_scores, clean_papers
from src.run_context import build_run_id, safe_error_summary
from src.text_relevance import ABSTRACT_WEIGHT, TITLE_WEIGHT


PIPELINE_SCHEMA_VERSION = "1.0"
PROVENANCE_FIELDS = ["source_query_ids", "source_run_ids", "source_keywords"]
COMBINED_FIELDS = OUTPUT_FIELDS + ["run_id"] + PROVENANCE_FIELDS
RANKED_FIELDS = COMBINED_FIELDS + [
    "relevance_score",
    "impact_score",
    "recency_score",
    "completeness_score",
    "preliminary_score",
    "baseline_preliminary_score",
    "old_rank",
    "title_relevance_score",
    "abstract_relevance_score",
    "combined_relevance_score",
    "stage1_relevance_score",
    "stage1_relevance_level",
    "stage2_ranking_score",
    "new_rank",
    "rank_change",
]
EXACT_FIELDS = [
    "rule",
    "kept_openalex_id",
    "kept_title",
    "merged_openalex_id",
    "merged_title",
    "source_keyword",
    "source_run_id",
    "merged_at",
]
SUSPECTED_FIELDS = [
    "pair_id",
    "left_id",
    "right_id",
    "left_title",
    "right_title",
    "title_similarity",
    "author_overlap",
    "year_difference",
    "doi_relation",
    "suspected_reason",
    "recommended_action",
    "review_status",
    "reviewer_note",
    "left_keyword",
    "right_keyword",
    "left_run_id",
    "right_run_id",
    "created_at",
]
QUERY_STATS_FIELDS = [
    "query_id",
    "keyword",
    "child_run_id",
    "requested_max_results",
    "actual_result_count",
    "cleaned_result_count",
    "page_count",
    "request_count",
    "retry_count",
    "duplicate_records_skipped",
    "status",
    "stopped_reason",
    "elapsed_seconds",
]

FetchFunction = Callable[[dict[str, Any], str, "PipelineConfig"], dict[str, Any]]


@dataclass(frozen=True)
class PipelineConfig:
    """一次 parent run 的可复现配置。"""

    project_root: Path
    terms_path: Path
    acquisition_query_ids: tuple[str, ...]
    ranking_keyword: str
    mode: str = "offline"
    max_results_per_query: int = 20
    output_root: Path | None = None
    run_name: str | None = None
    from_year: int | None = None
    to_year: int | None = None
    labels_path: Path | None = None
    evaluation_k: int = 10
    include_unverified_labels: bool = False
    offline_fixture_path: Path | None = None
    suspected_jaccard_threshold: float = 0.50
    suspected_sequence_threshold: float = 0.65
    batch_id: str | None = None
    batch_item_id: str | None = None


@dataclass
class PipelineResult:
    """统一 Pipeline 的内存结果和输出位置。"""

    run_id: str
    run_dir: Path
    run_config: dict[str, Any]
    combined_papers: list[dict[str, Any]]
    exact_duplicates: list[dict[str, Any]]
    kept_papers: list[dict[str, Any]]
    suspected_duplicates: list[dict[str, Any]]
    ranked_papers: list[dict[str, Any]]
    evaluation: dict[str, Any] | None


class PipelineRunError(RuntimeError):
    """Pipeline 已创建 parent run 后发生的结构化失败。"""

    def __init__(self, summary: str, *, run_id: str, run_dir: Path):
        super().__init__(summary)
        self.summary = summary
        self.run_id = run_id
        self.run_dir = Path(run_dir)


def run_unified_pipeline(
    config: PipelineConfig,
    *,
    fetcher: FetchFunction | None = None,
) -> PipelineResult:
    """执行一个多 acquisition query、单 ranking keyword 的 parent run。"""
    clean_config = _validate_config(config, fetcher_supplied=fetcher is not None)
    query_set = _build_and_select_query_set(clean_config)
    selected_queries = query_set["selected_queries"]
    run_dir, run_id = _create_run_directory(clean_config)
    started_at = datetime.now().astimezone()
    started_clock = time.monotonic()

    output_files = _output_file_map(bool(clean_config.labels_path))
    child_runs = [
        {
            "query_id": query["query_id"],
            "keyword": query["keyword"],
            "child_run_id": f"{run_id}__{query['query_id']}",
        }
        for query in selected_queries
    ]
    run_config = _initial_run_config(
        clean_config,
        run_id,
        started_at,
        child_runs,
        output_files,
    )
    config_file = run_dir / "run_config.json"
    _write_json(config_file, run_config)

    try:
        domain_file = run_dir / output_files["domain_query_set"]
        write_query_set(query_set["full_query_set"], domain_file)
        resolved_fetcher = fetcher or _resolve_default_fetcher(clean_config)

        combined_papers: list[dict[str, Any]] = []
        query_stats: list[dict[str, Any]] = []
        for query, child in zip(selected_queries, child_runs):
            fetch_result = resolved_fetcher(query, child["child_run_id"], clean_config)
            papers, raw_response, stats = _validate_fetch_result(fetch_result, query)
            cleaned = clean_papers(papers, query["keyword"])
            for paper in cleaned:
                _attach_provenance(paper, query, child["child_run_id"])
            combined_papers.extend(cleaned)

            query_dir = run_dir / "retrieval" / query["query_id"]
            _write_json(query_dir / "raw_response.json", raw_response)
            _write_json(query_dir / "cleaned_papers.json", cleaned)
            query_stats.append(
                _normalise_query_stats(query, child["child_run_id"], stats, len(cleaned), clean_config)
            )

        _write_json(run_dir / output_files["query_stats_json"], query_stats)
        _write_csv(run_dir / output_files["query_stats_csv"], query_stats, QUERY_STATS_FIELDS)
        _write_json(run_dir / output_files["combined_json"], combined_papers)
        _write_csv(run_dir / output_files["combined_csv"], combined_papers, COMBINED_FIELDS)

        exact_result = find_exact_duplicates(combined_papers, merge_provenance=True)
        exact_duplicates = exact_result["exact_duplicates"]
        kept_papers = exact_result["kept_papers"]
        suspected_result = find_suspected_duplicates(
            kept_papers,
            jaccard_threshold=clean_config.suspected_jaccard_threshold,
            sequence_threshold=clean_config.suspected_sequence_threshold,
        )
        suspected_duplicates = suspected_result["suspected_duplicates"]

        _write_csv(run_dir / output_files["exact_duplicates"], exact_duplicates, EXACT_FIELDS)
        _write_json(run_dir / output_files["deduplicated_json"], kept_papers)
        _write_csv(run_dir / output_files["deduplicated_csv"], kept_papers, COMBINED_FIELDS)
        _write_csv(
            run_dir / output_files["suspected_duplicates"],
            suspected_duplicates,
            SUSPECTED_FIELDS,
        )
        dedup_summary = {
            "combined_count": len(combined_papers),
            "exact_duplicate_count": len(exact_duplicates),
            "kept_count": len(kept_papers),
            "suspected_pair_count": len(suspected_duplicates),
            "exact_rules": exact_result["stats"],
            "suspected_reasons": suspected_result["stats"].get("reasons", {}),
            "suspected_records_removed": 0,
        }
        _write_json(run_dir / output_files["dedup_summary"], dedup_summary)

        baseline_papers = add_preliminary_scores(
            kept_papers,
            clean_config.ranking_keyword,
            reference_year=started_at.year,
        )
        ranked_papers = apply_two_stage_ranking(
            baseline_papers, clean_config.ranking_keyword
        )
        _write_csv(run_dir / output_files["ranked_papers"], ranked_papers, RANKED_FIELDS)
        _write_csv(
            run_dir / output_files["ranking_comparison"],
            build_comparison_rows(ranked_papers),
            COMPARISON_FIELDS,
        )
        _write_csv(
            run_dir / output_files["ranking_error_cases"],
            select_ranking_error_cases(ranked_papers),
            ERROR_CASE_FIELDS,
        )

        evaluation_result = None
        label_stats = None
        if clean_config.labels_path is not None:
            labels, label_stats = load_pipeline_labels(
                clean_config.labels_path,
                include_unverified=clean_config.include_unverified_labels,
            )
            old_order = sorted(ranked_papers, key=lambda paper: paper["old_rank"])
            new_order = sorted(ranked_papers, key=lambda paper: paper["new_rank"])
            evaluation_result = {
                "policy": label_stats,
                "baseline": evaluate_ranking(
                    [paper.get("openalex_id", "") for paper in old_order],
                    labels,
                    clean_config.evaluation_k,
                ),
                "two_stage": evaluate_ranking(
                    [paper.get("openalex_id", "") for paper in new_order],
                    labels,
                    clean_config.evaluation_k,
                ),
            }
            _write_json(run_dir / output_files["evaluation_metrics"], evaluation_result)

        counts = {
            "query_count": len(selected_queries),
            "retrieved_count": sum(row["actual_result_count"] for row in query_stats),
            "cleaned_count": sum(row["cleaned_result_count"] for row in query_stats),
            "combined_count": len(combined_papers),
            "exact_duplicate_count": len(exact_duplicates),
            "kept_count": len(kept_papers),
            "suspected_pair_count": len(suspected_duplicates),
            "ranked_count": len(ranked_papers),
            "evaluation_labels_used": (label_stats or {}).get("used_rows", 0),
        }
        _write_summary(run_dir / output_files["run_summary"], run_id, clean_config, counts)

        completed_at = datetime.now().astimezone()
        run_config.update(
            {
                "status": "completed",
                "success": True,
                "completed_at": completed_at.isoformat(timespec="seconds"),
                "elapsed_seconds": round(time.monotonic() - started_clock, 3),
                "counts": counts,
                "evaluation_policy": label_stats,
            }
        )
        _write_json(config_file, run_config)
        return PipelineResult(
            run_id=run_id,
            run_dir=run_dir,
            run_config=run_config,
            combined_papers=combined_papers,
            exact_duplicates=exact_duplicates,
            kept_papers=kept_papers,
            suspected_duplicates=suspected_duplicates,
            ranked_papers=ranked_papers,
            evaluation=evaluation_result,
        )
    except Exception as error:
        error_summary = safe_error_summary(error, clean_config.project_root, run_dir)
        run_config.update(
            {
                "status": "failed",
                "success": False,
                "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "elapsed_seconds": round(time.monotonic() - started_clock, 3),
                "error_summary": error_summary,
            }
        )
        _write_json(config_file, run_config)
        raise PipelineRunError(
            error_summary,
            run_id=run_id,
            run_dir=run_dir,
        ) from error


def build_offline_fixture_fetcher(path: Path) -> FetchFunction:
    """从测试 fixture 构造离线 fetcher；不会请求网络或读取环境密钥。"""
    fixture_path = Path(path)
    with fixture_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    query_payloads = payload.get("queries") if isinstance(payload, dict) else None
    if not isinstance(query_payloads, dict):
        raise ValueError("offline fixture 必须包含 queries 对象。")

    def fetch(query: dict[str, Any], child_run_id: str, config: PipelineConfig) -> dict[str, Any]:
        del child_run_id
        item = query_payloads.get(query["query_id"])
        if not isinstance(item, dict) or not isinstance(item.get("papers"), list):
            raise ValueError(f"offline fixture 缺少查询 {query['query_id']} 的 papers。")
        papers = [dict(paper) for paper in item["papers"]]
        papers = papers[: config.max_results_per_query]
        stats = dict(item.get("stats") or {})
        stats.setdefault("page_count", 0)
        stats.setdefault("request_count", 0)
        stats.setdefault("retry_count", 0)
        stats.setdefault("duplicate_records_skipped", 0)
        stats.setdefault("status", "success")
        stats.setdefault("stopped_reason", "offline_fixture")
        stats.setdefault("elapsed_seconds", 0.0)
        stats["requested_max_results"] = config.max_results_per_query
        stats["actual_result_count"] = len(papers)
        return {
            "papers": papers,
            "raw_response": item.get("raw_response", {"source": "offline_fixture", "results": papers}),
            "stats": stats,
        }

    return fetch


def load_pipeline_csv(path: Path) -> list[dict[str, Any]]:
    """读取 Pipeline CSV，并把 JSON array provenance 恢复成 list。"""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for field in PROVENANCE_FIELDS:
            if field in row:
                try:
                    value = json.loads(row[field])
                except (TypeError, json.JSONDecodeError) as error:
                    raise ValueError(f"{field} 不是有效 JSON array。") from error
                if not isinstance(value, list):
                    raise ValueError(f"{field} 必须是 JSON array。")
                row[field] = value
    return rows


def load_pipeline_labels(
    path: Path, *, include_unverified: bool = False
) -> tuple[dict[str, str], dict[str, Any]]:
    """读取评价标签；默认排除明确 AI 草稿和待人工复核行。"""
    label_path = Path(path)
    with label_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        if not {"openalex_id", "label"} <= fields:
            raise ValueError("评价标签 CSV 必须包含 openalex_id 和 label。")
        labels: dict[str, str] = {}
        seen_openalex_ids: set[str] = set()
        total_rows = 0
        excluded_ai_assisted = 0
        excluded_pending_review = 0
        for row in reader:
            total_rows += 1
            openalex_id = (row.get("openalex_id") or "").strip()
            label = (row.get("label") or "").strip()
            annotator = (row.get("annotator") or "").strip().casefold()
            review_status = (row.get("review_status") or "").strip()
            if not openalex_id or not label:
                continue
            if openalex_id in seen_openalex_ids:
                raise ValueError(
                    f"评价标签 CSV 的 openalex_id 重复：{openalex_id}。"
                    "不允许静默覆盖，请先修正标签文件。"
                )
            seen_openalex_ids.add(openalex_id)
            if not include_unverified and annotator == "ai-assisted-draft":
                excluded_ai_assisted += 1
                continue
            if not include_unverified and "待人工复核" in review_status:
                excluded_pending_review += 1
                continue
            labels[openalex_id] = label
    return labels, {
        "include_unverified_labels": include_unverified,
        "policy": (
            "explicit_all_rows" if include_unverified else "exclude_ai_assisted_and_pending_review"
        ),
        "total_rows": total_rows,
        "used_rows": len(labels),
        "excluded_ai_assisted_rows": excluded_ai_assisted,
        "excluded_pending_review_rows": excluded_pending_review,
        "note": "评价标签只用于 judged 离线指标，不进入评分公式。",
    }


def _validate_config(config: PipelineConfig, *, fetcher_supplied: bool) -> PipelineConfig:
    ranking_keyword = str(config.ranking_keyword or "").strip()
    if not ranking_keyword:
        raise ValueError("ranking_keyword 必须显式提供，不能由 acquisition query 推断。")
    query_ids = tuple(str(value).strip() for value in config.acquisition_query_ids)
    if not query_ids or any(not value for value in query_ids):
        raise ValueError("至少需要一个 acquisition query ID。")
    if len(query_ids) != len(set(query_ids)):
        raise ValueError("acquisition query ID 不能重复。")
    for query_id in query_ids:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", query_id):
            raise ValueError(f"query_id 不是安全标识符：{query_id!r}")
    if config.mode not in {"offline", "live"}:
        raise ValueError("mode 必须是 offline 或 live。")
    if isinstance(config.max_results_per_query, bool) or not isinstance(
        config.max_results_per_query, int
    ) or config.max_results_per_query <= 0:
        raise ValueError("max_results_per_query 必须是正整数。")
    if isinstance(config.evaluation_k, bool) or not isinstance(config.evaluation_k, int) or config.evaluation_k <= 0:
        raise ValueError("evaluation_k 必须是正整数。")
    for name, year in (("from_year", config.from_year), ("to_year", config.to_year)):
        if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1000 <= year <= 9999):
            raise ValueError(f"{name} 必须是 1000 到 9999 的整数。")
    if config.from_year is not None and config.to_year is not None and config.from_year > config.to_year:
        raise ValueError("from_year 不能晚于 to_year。")
    if config.mode == "offline" and not fetcher_supplied and config.offline_fixture_path is None:
        raise ValueError("offline 模式需要 --offline-fixture 或注入 fetcher。")
    for name, value in (
        ("suspected_jaccard_threshold", config.suspected_jaccard_threshold),
        ("suspected_sequence_threshold", config.suspected_sequence_threshold),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError(f"{name} 必须在 0 到 1 之间。")
    output_root = config.output_root or config.project_root / "outputs" / "experiments"
    return PipelineConfig(
        **{
            **config.__dict__,
            "project_root": Path(config.project_root).resolve(),
            "terms_path": Path(config.terms_path).resolve(),
            "output_root": Path(output_root).resolve(),
            "acquisition_query_ids": query_ids,
            "ranking_keyword": ranking_keyword,
            "labels_path": Path(config.labels_path).resolve() if config.labels_path else None,
            "offline_fixture_path": (
                Path(config.offline_fixture_path).resolve() if config.offline_fixture_path else None
            ),
        }
    )


def _build_and_select_query_set(config: PipelineConfig) -> dict[str, Any]:
    terms = load_domain_terms(config.terms_path)
    query_set = build_query_set(
        terms,
        source_path=_safe_source_path(config.terms_path, config.project_root),
    )
    by_id = {query["query_id"]: query for query in query_set["queries"]}
    missing = [query_id for query_id in config.acquisition_query_ids if query_id not in by_id]
    if missing:
        raise ValueError("领域查询集中不存在：" + ", ".join(missing))
    return {
        "full_query_set": query_set,
        "selected_queries": [by_id[query_id] for query_id in config.acquisition_query_ids],
    }


def _create_run_directory(config: PipelineConfig) -> tuple[Path, str]:
    assert config.output_root is not None
    config.output_root.mkdir(parents=True, exist_ok=True)
    for _ in range(5):
        run_id = build_run_id(
            config.mode,
            config.ranking_keyword,
            config.max_results_per_query,
            config.run_name,
        )
        run_dir = config.output_root / run_id
        try:
            run_dir.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        for relative in ("domain", "retrieval", "dedup", "ranking", "reports"):
            (run_dir / relative).mkdir()
        if config.labels_path is not None:
            (run_dir / "evaluation").mkdir()
        return run_dir, run_id
    raise OSError("连续生成的 parent run 目录均已存在。")


def _resolve_default_fetcher(config: PipelineConfig) -> FetchFunction:
    if config.mode == "offline":
        assert config.offline_fixture_path is not None
        return build_offline_fixture_fetcher(config.offline_fixture_path)

    def live_fetcher(query: dict[str, Any], child_run_id: str, current: PipelineConfig) -> dict[str, Any]:
        del child_run_id
        return fetch_openalex_papers_v2(
            query["keyword"],
            current.max_results_per_query,
            from_year=current.from_year,
            to_year=current.to_year,
        )

    return live_fetcher


def _validate_fetch_result(
    result: dict[str, Any], query: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    if not isinstance(result, dict) or not isinstance(result.get("papers"), list):
        raise ValueError(f"查询 {query['query_id']} 的 fetcher 返回结构无效。")
    if any(not isinstance(paper, dict) for paper in result["papers"]):
        raise ValueError(f"查询 {query['query_id']} 返回了非对象 paper。")
    raw_response = result.get("raw_response", {})
    stats = result.get("stats", {})
    if not isinstance(raw_response, dict) or not isinstance(stats, dict):
        raise ValueError(f"查询 {query['query_id']} 的 raw_response 或 stats 无效。")
    return result["papers"], raw_response, stats


def _attach_provenance(paper: dict[str, Any], query: dict[str, Any], child_run_id: str) -> None:
    paper["run_id"] = child_run_id
    paper["source_query_ids"] = [query["query_id"]]
    paper["source_run_ids"] = [child_run_id]
    paper["source_keywords"] = [query["keyword"]]


def _normalise_query_stats(
    query: dict[str, Any],
    child_run_id: str,
    stats: dict[str, Any],
    cleaned_count: int,
    config: PipelineConfig,
) -> dict[str, Any]:
    return {
        "query_id": query["query_id"],
        "keyword": query["keyword"],
        "child_run_id": child_run_id,
        "requested_max_results": config.max_results_per_query,
        "actual_result_count": int(stats.get("actual_result_count", cleaned_count)),
        "cleaned_result_count": cleaned_count,
        "page_count": int(stats.get("page_count", 0)),
        "request_count": int(stats.get("request_count", 0)),
        "retry_count": int(stats.get("retry_count", 0)),
        "duplicate_records_skipped": int(stats.get("duplicate_records_skipped", 0)),
        "status": str(stats.get("status", "success")),
        "stopped_reason": str(stats.get("stopped_reason", "")),
        "elapsed_seconds": float(stats.get("elapsed_seconds", 0.0)),
    }


def _initial_run_config(
    config: PipelineConfig,
    run_id: str,
    started_at: datetime,
    child_runs: list[dict[str, str]],
    output_files: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "run_id": run_id,
        "parent_run_id": run_id,
        "created_at": started_at.isoformat(timespec="seconds"),
        "mode": config.mode,
        "keyword": config.ranking_keyword,
        "ranking_keyword": config.ranking_keyword,
        "max_results": config.max_results_per_query,
        "max_results_per_query": config.max_results_per_query,
        "from_year": config.from_year,
        "to_year": config.to_year,
        "run_name": config.run_name,
        "batch": (
            {"batch_id": config.batch_id, "item_id": config.batch_item_id}
            if config.batch_id is not None
            else None
        ),
        "status": "running",
        "success": False,
        "python_version": platform.python_version(),
        "code_revision": _git_revision(config.project_root),
        "domain_terms_source": _safe_source_path(config.terms_path, config.project_root),
        "acquisition_query_ids": list(config.acquisition_query_ids),
        "acquisition_queries": child_runs,
        "evaluation": {
            "enabled": config.labels_path is not None,
            "label_file": (
                _safe_source_path(config.labels_path, config.project_root)
                if config.labels_path is not None
                else None
            ),
            "k": config.evaluation_k,
            "include_unverified_labels": config.include_unverified_labels,
        },
        "algorithms": {
            "exact_dedup": {
                "rules": ["same_openalex_id", "same_doi", "same_title_no_id"],
                "merge_provenance": True,
                "metadata_fusion": False,
            },
            "suspected_dedup": {
                "jaccard_threshold": config.suspected_jaccard_threshold,
                "sequence_threshold": config.suspected_sequence_threshold,
                "automatic_removal": False,
            },
            "preliminary_score_weights": PRELIMINARY_SCORE_WEIGHTS,
            "recency_reference_year": started_at.year,
            "tfidf_text_weights": {"title": TITLE_WEIGHT, "abstract": ABSTRACT_WEIGHT},
            "stage1_thresholds": {
                "high": STAGE1_HIGH_THRESHOLD,
                "medium": STAGE1_MEDIUM_THRESHOLD,
            },
            "stage1_gates": STAGE1_LEVEL_GATE,
            "stage2_weights": STAGE2_SCORE_WEIGHTS,
        },
        "output_files": output_files,
        "counts": {},
    }


def _output_file_map(has_evaluation: bool) -> dict[str, str]:
    files = {
        "domain_query_set": "domain/domain_query_set.json",
        "query_stats_json": "retrieval/query_stats.json",
        "query_stats_csv": "retrieval/query_stats.csv",
        "combined_json": "retrieval/combined_papers.json",
        "combined_csv": "retrieval/combined_papers.csv",
        "exact_duplicates": "dedup/exact_duplicates.csv",
        "deduplicated_json": "dedup/deduplicated_papers.json",
        "deduplicated_csv": "dedup/deduplicated_papers.csv",
        "suspected_duplicates": "dedup/suspected_duplicates.csv",
        "dedup_summary": "dedup/summary.json",
        "ranked_papers": "ranking/ranked_papers.csv",
        "ranking_comparison": "ranking/baseline_vs_two_stage.csv",
        "ranking_error_cases": "ranking/error_cases.csv",
        "run_summary": "reports/run_summary.txt",
    }
    if has_evaluation:
        files["evaluation_metrics"] = "evaluation/metrics.json"
    return files


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            serialised = {}
            for field in fields:
                value = row.get(field, "")
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                elif value is None:
                    value = ""
                serialised[field] = value
            writer.writerow(serialised)


def _write_summary(
    path: Path,
    run_id: str,
    config: PipelineConfig,
    counts: dict[str, int],
) -> None:
    lines = [
        "W2 unified pipeline run summary",
        f"run_id: {run_id}",
        f"mode: {config.mode}",
        "acquisition_query_ids: " + ", ".join(config.acquisition_query_ids),
        f"ranking_keyword: {config.ranking_keyword}",
        f"max_results_per_query: {config.max_results_per_query}",
        "",
    ]
    lines.extend(f"{key}: {value}" for key, value in counts.items())
    lines.extend(
        [
            "",
            "suspected duplicate pairs are review-only and were not removed.",
            "preliminary_score is an internal explainable baseline, not academic value.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _safe_source_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _git_revision(project_root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(project_root), "describe", "--tags", "--always", "--dirty"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None
