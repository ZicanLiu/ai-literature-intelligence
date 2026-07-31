"""OpenAlex v2 独立命令行入口。

该入口用于验证分页、筛选、有限重试和请求统计，不接入 ``app.main`` 的
正式处理流程。API Key 只从仓库根目录的 ``.env`` 或当前环境变量读取。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.openalex_client_v2 import OpenAlexClientV2Error, fetch_openalex_papers_v2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_FIELDS = [
    "query_id",
    "run_id",
    "retrieved_at",
    "keyword",
    "requested_max_results",
    "actual_result_count",
    "page_count",
    "request_count",
    "retry_count",
    "applied_filters",
    "elapsed_seconds",
    "stopped_reason",
    "status",
    "duplicate_ids_present",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 OpenAlex v2 客户端执行 cursor 分页检索。"
    )
    parser.add_argument("--keyword", required=True, help="实际发送的完整检索关键词。")
    parser.add_argument(
        "--max-results",
        type=int,
        default=20,
        help="最多返回的去重文献数量，默认 20。",
    )
    parser.add_argument("--from-year", type=int, help="可选的起始发表年份（含）。")
    parser.add_argument("--to-year", type=int, help="可选的结束发表年份（含）。")
    parser.add_argument(
        "--timeout-seconds", type=float, default=20, help="单次 HTTP 请求超时秒数。"
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="每页首次请求之外允许的最大重试次数。",
    )
    parser.add_argument(
        "--backoff-base-seconds",
        type=float,
        default=1.0,
        help="指数退避的基础等待秒数。",
    )
    parser.add_argument(
        "--max-backoff-seconds",
        type=float,
        default=30.0,
        help="单次重试等待上限秒数。",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="可选的一行式 live 运行摘要 CSV 输出路径。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    api_key = os.getenv("OPENALEX_API_KEY")

    try:
        result = fetch_openalex_papers_v2(
            keyword=args.keyword,
            max_results=args.max_results,
            from_year=args.from_year,
            to_year=args.to_year,
            timeout_seconds=args.timeout_seconds,
            max_retries=args.max_retries,
            backoff_base_seconds=args.backoff_base_seconds,
            max_backoff_seconds=args.max_backoff_seconds,
            api_key=api_key,
        )
    except OpenAlexClientV2Error as error:
        safe_failure = {"error_summary": error.summary, **error.stats}
        print(json.dumps(safe_failure, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "stopped_reason": "unexpected_error",
                    "error_summary": "OpenAlex v2 运行发生未预期错误，已隐藏敏感调试信息。",
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    papers = result["papers"]
    stats = result["stats"]
    duplicate_ids_present = _duplicate_ids_present(papers)
    safe_output = {
        "keyword": args.keyword.strip(),
        **stats,
        "duplicate_ids_present": duplicate_ids_present,
    }
    print(json.dumps(safe_output, ensure_ascii=False, indent=2))

    if args.summary_output is not None:
        try:
            summary_path = _resolve_output_path(args.summary_output)
            summary_row = build_summary_row(
                keyword=args.keyword.strip(),
                stats=stats,
                duplicate_ids_present=duplicate_ids_present,
            )
            save_summary_csv(summary_row, summary_path)
        except Exception:
            print(
                "运行成功，但摘要 CSV 写入失败；已隐藏本地路径详情。",
                file=sys.stderr,
            )
            return 1
        print(f"摘要已保存：{_display_path(summary_path)}")
    return 0


def build_summary_row(
    *,
    keyword: str,
    stats: dict[str, Any],
    duplicate_ids_present: bool,
) -> dict[str, Any]:
    completed_at = datetime.now(timezone.utc).replace(microsecond=0)
    query_config = {
        "keyword": keyword,
        "max_results": stats["requested_max_results"],
        "applied_filters": stats["applied_filters"],
    }
    query_digest = hashlib.sha256(
        json.dumps(
            query_config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:12]
    run_timestamp = completed_at.strftime("%Y%m%dT%H%M%SZ")
    return {
        "query_id": f"openalex-v2-{query_digest}",
        "run_id": f"openalex-v2-live-{run_timestamp}-{uuid.uuid4().hex[:8]}",
        "retrieved_at": completed_at.isoformat(),
        "keyword": keyword,
        "requested_max_results": stats["requested_max_results"],
        "actual_result_count": stats["actual_result_count"],
        "page_count": stats["page_count"],
        "request_count": stats["request_count"],
        "retry_count": stats["retry_count"],
        "applied_filters": json.dumps(
            stats["applied_filters"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "elapsed_seconds": stats["elapsed_seconds"],
        "stopped_reason": stats["stopped_reason"],
        "status": stats["status"],
        "duplicate_ids_present": str(duplicate_ids_present).lower(),
    }


def save_summary_csv(summary_row: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=SUMMARY_FIELDS,
            lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerow(summary_row)
    temporary_path.replace(output_path)


def _resolve_output_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return PROJECT_ROOT / expanded


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


def _duplicate_ids_present(papers: list[dict[str, Any]]) -> bool:
    ids = [
        paper["openalex_id"].strip()
        for paper in papers
        if isinstance(paper.get("openalex_id"), str)
        and paper["openalex_id"].strip()
    ]
    return len(ids) != len(set(ids))


if __name__ == "__main__":
    raise SystemExit(main())
