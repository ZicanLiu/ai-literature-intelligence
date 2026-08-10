"""统一 Pipeline 的轻量批量执行器。"""

from __future__ import annotations

import csv
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.pipeline import PipelineConfig, PipelineRunError, run_unified_pipeline
from src.run_context import keyword_slug, safe_error_summary


BATCH_SCHEMA_VERSION = "1.0"
BATCH_SUMMARY_FIELDS = [
    "item_id",
    "status",
    "mode",
    "acquisition_query_ids",
    "ranking_keyword",
    "run_id",
    "run_dir",
    "combined_count",
    "exact_duplicate_count",
    "kept_count",
    "suspected_pair_count",
    "ranked_count",
    "error_summary",
]


@dataclass
class BatchResult:
    batch_id: str
    batch_dir: Path
    summary: dict[str, Any]


def load_batch_definition(path: Path) -> dict[str, Any]:
    """读取并验证 batch 顶层结构，不解析任何环境变量。"""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("batch config 顶层必须是 JSON object。")
    if "schema_version" in payload and not isinstance(payload["schema_version"], str):
        raise ValueError("schema_version 必须是 JSON string。")
    batch_name = str(payload.get("batch_name") or "").strip()
    if not batch_name:
        raise ValueError("batch_name 不能为空。")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("batch config 至少需要一个 items 条目。")
    _json_boolean(payload, "continue_on_error", False, "batch")
    item_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("每个 batch item 必须是 JSON object。")
        item_id = str(item.get("item_id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", item_id):
            raise ValueError(f"batch item_id 不是安全标识符：{item_id!r}")
        if item_id in item_ids:
            raise ValueError(f"batch item_id 重复：{item_id}")
        item_ids.add(item_id)
        _json_boolean(item, "enabled", True, f"batch item {item_id}")
        _json_boolean(
            item,
            "include_unverified_labels",
            False,
            f"batch item {item_id}",
        )
        if "mode" in item and (
            not isinstance(item["mode"], str)
            or item["mode"] not in {"offline", "live"}
        ):
            raise ValueError(
                f"batch item {item_id} 的 mode 必须是 offline 或 live 字符串。"
            )
        if "query_id" in item and "acquisition_query_ids" not in item:
            raise ValueError(
                f"batch item {item_id} 使用了含义不明确的 query_id；"
                "请显式提供 acquisition_query_ids。"
            )
    return payload


def batch_contains_live(definition: dict[str, Any]) -> bool:
    return any(
        item.get("enabled", True) and item.get("mode", "offline") == "live"
        for item in definition["items"]
    )


def run_batch(
    batch_config_path: Path,
    *,
    project_root: Path,
    pipeline_output_root: Path | None = None,
    batch_output_root: Path | None = None,
) -> BatchResult:
    """顺序执行多个独立 parent run，并生成 batch 级摘要。"""
    project_root = Path(project_root).resolve()
    definition = load_batch_definition(batch_config_path)
    batch_name = str(definition["batch_name"]).strip()
    continue_on_error = _json_boolean(
        definition, "continue_on_error", False, "batch"
    )
    pipeline_output_root = Path(
        pipeline_output_root or project_root / "outputs" / "experiments"
    ).resolve()
    batch_output_root = Path(
        batch_output_root or project_root / "outputs" / "batches"
    ).resolve()
    batch_output_root.mkdir(parents=True, exist_ok=True)
    batch_id, batch_dir = _create_batch_dir(batch_output_root, batch_name)
    started_at = datetime.now().astimezone()

    snapshot = {
        "schema_version": definition.get("schema_version", BATCH_SCHEMA_VERSION),
        "batch_id": batch_id,
        "batch_name": batch_name,
        "continue_on_error": continue_on_error,
        "source_config": _safe_path(Path(batch_config_path), project_root),
        "terms_path": _safe_config_path(
            definition.get("terms_path", "data/domain/stellar_spectra_terms_w2.csv"),
            project_root,
        ),
        "items": [_sanitise_item_paths(item, project_root) for item in definition["items"]],
    }
    _write_json(batch_dir / "batch_config.json", snapshot)

    rows: list[dict[str, Any]] = []
    halted = False
    for item in definition["items"]:
        item_id = str(item["item_id"]).strip()
        if halted:
            rows.append(_summary_row(item, status="not_run_after_failure"))
            continue
        if not _json_boolean(item, "enabled", True, f"batch item {item_id}"):
            rows.append(_summary_row(item, status="skipped"))
            continue

        try:
            pipeline_config = _pipeline_config_from_item(
                definition,
                item,
                batch_id=batch_id,
                project_root=project_root,
                output_root=pipeline_output_root,
            )
            result = run_unified_pipeline(pipeline_config)
            counts = result.run_config["counts"]
            row = _summary_row(
                item,
                status="success",
                run_id=result.run_id,
                run_dir=_safe_path(result.run_dir, project_root),
            )
            for field in (
                "combined_count",
                "exact_duplicate_count",
                "kept_count",
                "suspected_pair_count",
                "ranked_count",
            ):
                row[field] = counts[field]
            rows.append(row)
        except PipelineRunError as error:
            rows.append(
                _summary_row(
                    item,
                    status="failed",
                    run_id=error.run_id,
                    run_dir=_safe_path(error.run_dir, project_root),
                    error_summary=error.summary,
                )
            )
            if not continue_on_error:
                halted = True
        except Exception as error:
            rows.append(
                _summary_row(
                    item,
                    status="failed",
                    error_summary=safe_error_summary(error, project_root, batch_dir),
                )
            )
            if not continue_on_error:
                halted = True

    success_count = sum(row["status"] == "success" for row in rows)
    failure_count = sum(row["status"] == "failed" for row in rows)
    skipped_count = sum(row["status"] == "skipped" for row in rows)
    not_run_count = sum(row["status"] == "not_run_after_failure" for row in rows)
    status = "completed" if failure_count == 0 else "completed_with_errors"
    summary = {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "batch_name": batch_name,
        "status": status,
        "success": failure_count == 0,
        "continue_on_error": continue_on_error,
        "created_at": started_at.isoformat(timespec="seconds"),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "item_count": len(rows),
        "success_count": success_count,
        "failure_count": failure_count,
        "skipped_count": skipped_count,
        "not_run_count": not_run_count,
        "items": rows,
    }
    _write_json(batch_dir / "batch_summary.json", summary)
    _write_csv(batch_dir / "batch_summary.csv", rows)
    return BatchResult(batch_id=batch_id, batch_dir=batch_dir, summary=summary)


def _pipeline_config_from_item(
    definition: dict[str, Any],
    item: dict[str, Any],
    *,
    batch_id: str,
    project_root: Path,
    output_root: Path,
) -> PipelineConfig:
    query_ids = item.get("acquisition_query_ids")
    if not isinstance(query_ids, list):
        raise ValueError(f"batch item {item['item_id']} 缺少 acquisition_query_ids list。")
    terms_value = item.get("terms_path", definition.get("terms_path", "data/domain/stellar_spectra_terms_w2.csv"))
    labels_value = item.get("labels_path")
    fixture_value = item.get("offline_fixture_path")
    return PipelineConfig(
        project_root=project_root,
        terms_path=_resolve_project_path(project_root, terms_value),
        acquisition_query_ids=tuple(str(value) for value in query_ids),
        ranking_keyword=str(item.get("ranking_keyword") or ""),
        mode=str(item.get("mode", "offline")),
        max_results_per_query=item.get("max_results_per_query", 20),
        output_root=output_root,
        run_name=str(item.get("run_name") or item["item_id"]),
        from_year=item.get("from_year"),
        to_year=item.get("to_year"),
        labels_path=(
            _resolve_project_path(project_root, labels_value) if labels_value else None
        ),
        evaluation_k=item.get("evaluation_k", 10),
        include_unverified_labels=_json_boolean(
            item,
            "include_unverified_labels",
            False,
            f"batch item {item['item_id']}",
        ),
        offline_fixture_path=(
            _resolve_project_path(project_root, fixture_value) if fixture_value else None
        ),
        batch_id=batch_id,
        batch_item_id=str(item["item_id"]),
    )


def _summary_row(
    item: dict[str, Any],
    *,
    status: str,
    run_id: str = "",
    run_dir: str = "",
    error_summary: str = "",
) -> dict[str, Any]:
    query_ids = item.get("acquisition_query_ids", [])
    return {
        "item_id": str(item.get("item_id", "")),
        "status": status,
        "mode": str(item.get("mode", "offline")),
        "acquisition_query_ids": list(query_ids) if isinstance(query_ids, list) else [],
        "ranking_keyword": str(item.get("ranking_keyword", "")),
        "run_id": run_id,
        "run_dir": run_dir,
        "combined_count": "",
        "exact_duplicate_count": "",
        "kept_count": "",
        "suspected_pair_count": "",
        "ranked_count": "",
        "error_summary": error_summary,
    }


def _json_boolean(
    mapping: dict[str, Any], field: str, default: bool, context: str
) -> bool:
    value = mapping.get(field, default)
    if not isinstance(value, bool):
        raise ValueError(f"{context} 的 {field} 必须使用 JSON boolean true/false。")
    return value


def _create_batch_dir(output_root: Path, batch_name: str) -> tuple[str, Path]:
    for _ in range(5):
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S%f")
        batch_id = f"{timestamp}_{keyword_slug(batch_name, 32)}_{uuid.uuid4().hex[:6]}"
        batch_dir = output_root / batch_id
        try:
            batch_dir.mkdir(exist_ok=False)
            return batch_id, batch_dir
        except FileExistsError:
            continue
    raise OSError("连续生成的 batch 目录均已存在。")


def _resolve_project_path(project_root: Path, value: Any) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def _safe_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _safe_config_path(value: Any, project_root: Path) -> str:
    return _safe_path(_resolve_project_path(project_root, value), project_root)


def _sanitise_item_paths(item: dict[str, Any], project_root: Path) -> dict[str, Any]:
    cleaned = dict(item)
    for field in ("terms_path", "labels_path", "offline_fixture_path"):
        if cleaned.get(field):
            cleaned[field] = _safe_config_path(cleaned[field], project_root)
    return cleaned


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BATCH_SUMMARY_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            serialised = dict(row)
            serialised["acquisition_query_ids"] = json.dumps(
                serialised["acquisition_query_ids"], ensure_ascii=False, separators=(",", ":")
            )
            writer.writerow(serialised)
