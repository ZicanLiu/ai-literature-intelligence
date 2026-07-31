"""OpenAlex Works API v2 客户端。

该模块在旧客户端之外提供 cursor 分页、有限重试、年份筛选和请求统计。
它不负责读取 ``.env``、保存文件或接入正式主流程；调用方应显式传入 API Key。
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable
from typing import Any

import requests

from src.openalex_client import convert_openalex_work


OPENALEX_WORKS_URL = "https://api.openalex.org/works"
OPENALEX_MAX_PER_PAGE = 100
OPENALEX_SELECT_FIELDS = (
    "id,display_name,authorships,publication_year,doi,"
    "abstract_inverted_index,cited_by_count,primary_location"
)
RETRYABLE_STATUS_CODES = {408, 429}


class OpenAlexClientV2Error(RuntimeError):
    """带有安全摘要和脱敏请求统计的 v2 客户端错误。"""

    def __init__(self, summary: str, stats: dict[str, Any]):
        super().__init__(summary)
        self.summary = summary
        self.stats = dict(stats)


class _PageRequestError(Exception):
    """仅在模块内部传递已经脱敏的单页请求错误。"""


def fetch_openalex_papers_v2(
    keyword: str,
    max_results: int = 20,
    *,
    from_year: int | None = None,
    to_year: int | None = None,
    timeout_seconds: float = 20,
    max_retries: int = 3,
    backoff_base_seconds: float = 1.0,
    max_backoff_seconds: float = 30.0,
    api_key: str | None = None,
    request_get: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    monotonic_fn: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """按关键词检索 OpenAlex Works，并返回去重后的聚合结果。

    ``max_retries`` 表示首次请求之外允许的额外尝试次数。成功返回值保留
    旧客户端的 ``raw_response`` 和 ``papers`` 键，并新增 ``stats``。
    最终失败时抛出 :class:`OpenAlexClientV2Error`；异常文本和统计均不含
    API Key、完整请求 URL或个人路径。
    """

    clock = monotonic_fn or time.monotonic
    started_at = clock()
    stats = _initial_stats(max_results)

    try:
        clean_keyword = _validate_inputs(
            keyword=keyword,
            max_results=max_results,
            from_year=from_year,
            to_year=to_year,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            backoff_base_seconds=backoff_base_seconds,
            max_backoff_seconds=max_backoff_seconds,
        )
    except ValueError as error:
        stats["stopped_reason"] = "invalid_parameters"
        stats["status"] = "failed"
        _finish_stats(stats, started_at, clock)
        raise OpenAlexClientV2Error(str(error), stats) from None

    resolved_api_key = api_key if api_key is not None else os.getenv("OPENALEX_API_KEY")
    if not isinstance(resolved_api_key, str) or not resolved_api_key.strip():
        stats["stopped_reason"] = "missing_api_key"
        stats["status"] = "failed"
        _finish_stats(stats, started_at, clock)
        raise OpenAlexClientV2Error(
            "OpenAlex live 请求需要本地配置 OPENALEX_API_KEY。", stats
        ) from None

    get = request_get or requests.get
    sleeper = sleep_fn or time.sleep
    base_params: dict[str, Any] = {
        "search": clean_keyword,
        "select": OPENALEX_SELECT_FIELDS,
        "api_key": resolved_api_key.strip(),
    }
    filter_expression = _build_filter_expression(from_year, to_year)
    if filter_expression:
        base_params["filter"] = filter_expression
        stats["applied_filters"] = {
            name: year
            for name, year in (("from_year", from_year), ("to_year", to_year))
            if year is not None
        }

    cursor = "*"
    seen_cursors: set[str] = set()
    seen_openalex_ids: set[str] = set()
    aggregated_works: list[dict[str, Any]] = []
    page_meta: list[dict[str, Any]] = []

    while len(aggregated_works) < max_results:
        if cursor in seen_cursors:
            _raise_client_error(
                "OpenAlex 返回了重复 cursor，已停止以避免分页死循环。",
                stats,
                "cursor_stalled",
                started_at,
                clock,
                len(aggregated_works),
            )
        seen_cursors.add(cursor)

        remaining = max_results - len(aggregated_works)
        params = dict(base_params)
        params.update(
            {
                "cursor": cursor,
                "per_page": min(OPENALEX_MAX_PER_PAGE, remaining),
            }
        )

        try:
            payload = _request_json_page(
                request_get=get,
                params=params,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                backoff_base_seconds=backoff_base_seconds,
                max_backoff_seconds=max_backoff_seconds,
                sleep_fn=sleeper,
                stats=stats,
            )
        except _PageRequestError as error:
            _raise_client_error(
                str(error),
                stats,
                "request_failed",
                started_at,
                clock,
                len(aggregated_works),
            )

        results = payload["results"]
        meta = payload["meta"]
        next_cursor = meta.get("next_cursor")
        stats["page_count"] += 1
        page_meta.append(
            {
                "count": meta.get("count"),
                "per_page": meta.get("per_page"),
                "next_cursor": next_cursor,
            }
        )

        for work in results:
            raw_openalex_id = work.get("id")
            openalex_id = (
                raw_openalex_id.strip()
                if isinstance(raw_openalex_id, str)
                else ""
            )
            if openalex_id and openalex_id in seen_openalex_ids:
                stats["duplicate_records_skipped"] += 1
                continue
            if openalex_id:
                seen_openalex_ids.add(openalex_id)
            aggregated_works.append(work)
            if len(aggregated_works) >= max_results:
                break

        stats["actual_result_count"] = len(aggregated_works)
        if len(aggregated_works) >= max_results:
            stats["stopped_reason"] = "max_results_reached"
            break
        if not results:
            stats["stopped_reason"] = "results_exhausted"
            break
        if next_cursor is None or next_cursor == "":
            stats["stopped_reason"] = "cursor_exhausted"
            break
        if not isinstance(next_cursor, str):
            _raise_client_error(
                "OpenAlex 返回了无法识别的 cursor 格式。",
                stats,
                "request_failed",
                started_at,
                clock,
                len(aggregated_works),
            )
        cursor = next_cursor

    try:
        papers = [
            convert_openalex_work(work, clean_keyword) for work in aggregated_works
        ]
    except (AttributeError, TypeError, ValueError):
        _raise_client_error(
            "OpenAlex 响应包含无法转换的字段结构。",
            stats,
            "response_invalid",
            started_at,
            clock,
            len(aggregated_works),
        )
    stats["actual_result_count"] = len(papers)
    stats["output_duplicate_id_count"] = _count_output_duplicate_ids(papers)
    stats["status"] = "success"
    _finish_stats(stats, started_at, clock)

    raw_response = {
        "meta": {
            "aggregation": "openalex_v2_cursor_pages",
            "page_count": stats["page_count"],
            "requested_max_results": max_results,
            "actual_result_count": len(aggregated_works),
        },
        "page_meta": page_meta,
        "results": aggregated_works,
    }
    return {"raw_response": raw_response, "papers": papers, "stats": stats}


def _initial_stats(max_results: object) -> dict[str, Any]:
    return {
        "requested_max_results": (
            max_results
            if isinstance(max_results, int) and not isinstance(max_results, bool)
            else None
        ),
        "actual_result_count": 0,
        "page_count": 0,
        "request_count": 0,
        "retry_count": 0,
        "applied_filters": {},
        "elapsed_seconds": 0.0,
        "stopped_reason": "",
        "status": "running",
        "duplicate_records_skipped": 0,
        "output_duplicate_id_count": 0,
    }


def _validate_inputs(
    *,
    keyword: object,
    max_results: object,
    from_year: object,
    to_year: object,
    timeout_seconds: object,
    max_retries: object,
    backoff_base_seconds: object,
    max_backoff_seconds: object,
) -> str:
    if not isinstance(keyword, str) or not keyword.strip():
        raise ValueError("keyword 不能为空或只包含空白字符。")
    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise ValueError("max_results 必须是正整数。")
    if max_results <= 0:
        raise ValueError("max_results 必须大于 0。")
    for name, year in (("from_year", from_year), ("to_year", to_year)):
        if year is None:
            continue
        if isinstance(year, bool) or not isinstance(year, int):
            raise ValueError(f"{name} 必须是四位整数年份。")
        if year < 1000 or year > 9999:
            raise ValueError(f"{name} 必须在 1000 到 9999 之间。")
    if from_year is not None and to_year is not None and from_year > to_year:
        raise ValueError("from_year 不能晚于 to_year。")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds 必须大于 0。")
    if (
        isinstance(max_retries, bool)
        or not isinstance(max_retries, int)
        or max_retries < 0
    ):
        raise ValueError("max_retries 必须是大于或等于 0 的整数。")
    for name, value, allow_zero in (
        ("backoff_base_seconds", backoff_base_seconds, True),
        ("max_backoff_seconds", max_backoff_seconds, False),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} 必须是数字。")
        if not math.isfinite(value):
            raise ValueError(f"{name} 必须是有限数字。")
        if (allow_zero and value < 0) or (not allow_zero and value <= 0):
            comparator = "大于或等于 0" if allow_zero else "大于 0"
            raise ValueError(f"{name} 必须{comparator}。")
    return keyword.strip()


def _build_filter_expression(
    from_year: int | None, to_year: int | None
) -> str:
    filters: list[str] = []
    if from_year is not None:
        filters.append(f"from_publication_date:{from_year:04d}-01-01")
    if to_year is not None:
        filters.append(f"to_publication_date:{to_year:04d}-12-31")
    return ",".join(filters)


def _request_json_page(
    *,
    request_get: Callable[..., Any],
    params: dict[str, Any],
    timeout_seconds: float,
    max_retries: int,
    backoff_base_seconds: float,
    max_backoff_seconds: float,
    sleep_fn: Callable[[float], None],
    stats: dict[str, Any],
) -> dict[str, Any]:
    attempt = 0
    while True:
        stats["request_count"] += 1
        try:
            response = request_get(
                OPENALEX_WORKS_URL,
                params=params,
                timeout=timeout_seconds,
            )
        except requests.Timeout:
            summary = "OpenAlex 请求超时，已达到有限重试上限。"
            if _can_retry(attempt, max_retries):
                _wait_before_retry(
                    attempt,
                    None,
                    backoff_base_seconds,
                    max_backoff_seconds,
                    sleep_fn,
                    stats,
                )
                attempt += 1
                continue
            raise _PageRequestError(summary) from None
        except (requests.ConnectionError, requests.exceptions.ChunkedEncodingError):
            summary = "OpenAlex 连接暂时失败，已达到有限重试上限。"
            if _can_retry(attempt, max_retries):
                _wait_before_retry(
                    attempt,
                    None,
                    backoff_base_seconds,
                    max_backoff_seconds,
                    sleep_fn,
                    stats,
                )
                attempt += 1
                continue
            raise _PageRequestError(summary) from None
        except requests.RequestException:
            raise _PageRequestError("OpenAlex 网络请求失败，未执行盲目重试。") from None

        status_code = response.status_code
        is_retryable_status = (
            status_code in RETRYABLE_STATUS_CODES or 500 <= status_code <= 599
        )
        if is_retryable_status:
            if _can_retry(attempt, max_retries):
                _wait_before_retry(
                    attempt,
                    response,
                    backoff_base_seconds,
                    max_backoff_seconds,
                    sleep_fn,
                    stats,
                )
                attempt += 1
                continue
            if status_code == 429:
                summary = "OpenAlex 触发限流，已达到有限重试上限。"
            else:
                summary = "OpenAlex 临时服务错误，已达到有限重试上限。"
            raise _PageRequestError(summary) from None
        if status_code == 400:
            raise _PageRequestError(
                "OpenAlex 拒绝了请求参数（HTTP 400），未执行重试。"
            ) from None
        if status_code == 401:
            raise _PageRequestError(
                "OpenAlex 认证失败（HTTP 401），未执行重试。"
            ) from None
        if status_code == 403:
            raise _PageRequestError(
                "OpenAlex 拒绝访问（HTTP 403），未执行重试。"
            ) from None
        if status_code == 404:
            raise _PageRequestError(
                "OpenAlex 接口资源不存在（HTTP 404），未执行重试。"
            ) from None
        if status_code < 200 or status_code >= 300:
            raise _PageRequestError(
                f"OpenAlex 请求失败（HTTP {status_code}），未执行重试。"
            ) from None

        # JSON 解析必须与网络异常分开捕获；requests.JSONDecodeError 也属于
        # RequestException，混在同一 try 中会导致错误分类不准确。
        try:
            payload = response.json()
        except ValueError:
            if _can_retry(attempt, max_retries):
                _wait_before_retry(
                    attempt,
                    response,
                    backoff_base_seconds,
                    max_backoff_seconds,
                    sleep_fn,
                    stats,
                )
                attempt += 1
                continue
            raise _PageRequestError(
                "OpenAlex 返回了无效 JSON，已达到有限重试上限。"
            ) from None

        if not isinstance(payload, dict):
            raise _PageRequestError("OpenAlex 响应 JSON 顶层结构无效。") from None
        results = payload.get("results")
        meta = payload.get("meta")
        if not isinstance(results, list) or not isinstance(meta, dict):
            raise _PageRequestError("OpenAlex 响应缺少有效的 results 或 meta。") from None
        if any(not isinstance(work, dict) for work in results):
            raise _PageRequestError("OpenAlex results 中包含无效记录。") from None
        return payload


def _can_retry(attempt: int, max_retries: int) -> bool:
    return attempt < max_retries


def _wait_before_retry(
    retry_index: int,
    response: Any | None,
    backoff_base_seconds: float,
    max_backoff_seconds: float,
    sleep_fn: Callable[[float], None],
    stats: dict[str, Any],
) -> None:
    delay = min(
        max_backoff_seconds,
        backoff_base_seconds * (2**retry_index),
    )
    if response is not None:
        retry_after = response.headers.get("Retry-After", "")
        try:
            retry_after_seconds = float(retry_after)
        except (TypeError, ValueError):
            retry_after_seconds = -1
        if retry_after_seconds >= 0:
            delay = min(max_backoff_seconds, retry_after_seconds)
    stats["retry_count"] += 1
    sleep_fn(delay)


def _finish_stats(
    stats: dict[str, Any],
    started_at: float,
    monotonic_fn: Callable[[], float],
) -> None:
    stats["elapsed_seconds"] = round(max(0.0, monotonic_fn() - started_at), 3)


def _raise_client_error(
    summary: str,
    stats: dict[str, Any],
    stopped_reason: str,
    started_at: float,
    monotonic_fn: Callable[[], float],
    actual_result_count: int,
) -> None:
    stats["actual_result_count"] = actual_result_count
    stats["stopped_reason"] = stopped_reason
    stats["status"] = "failed"
    _finish_stats(stats, started_at, monotonic_fn)
    raise OpenAlexClientV2Error(summary, stats) from None


def _count_output_duplicate_ids(papers: list[dict[str, Any]]) -> int:
    ids = [
        paper.get("openalex_id", "").strip()
        for paper in papers
        if isinstance(paper.get("openalex_id"), str)
        and paper.get("openalex_id", "").strip()
    ]
    return len(ids) - len(set(ids))


if __name__ == "__main__":
    print("openalex_client_v2.py 提供独立的分页检索客户端。")
    print("请通过 python3 -m app.openalex_fetch_v2 执行 live 查询。")
