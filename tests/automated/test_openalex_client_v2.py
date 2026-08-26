"""OpenAlex v2 客户端和独立 CLI 的纯离线自动测试。"""

from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import requests

from app import openalex_fetch_v2 as cli
from src.openalex_client_v2 import (
    OPENALEX_WORKS_URL,
    OpenAlexClientV2Error,
    fetch_openalex_papers_v2,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "openalex"
TEST_API_KEY = "test-api-key-must-never-appear-in-output"


class StubResponse:
    """只实现客户端会访问的 requests.Response 接口。"""

    def __init__(
        self,
        status_code: int = 200,
        payload: Any | None = None,
        *,
        headers: dict[str, str] | None = None,
        json_error: ValueError | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = dict(headers or {})
        self._json_error = json_error

    def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class SequencedGet:
    """按顺序返回响应或抛出异常，并保留脱离网络的调用证据。"""

    def __init__(self, *events: Any) -> None:
        self.events = list(events)
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, url: str, *, params: dict[str, Any], timeout: float
    ) -> StubResponse:
        self.calls.append(
            {"url": url, "params": dict(params), "timeout": timeout}
        )
        if not self.events:
            raise AssertionError("测试响应已耗尽；客户端发出了意外请求。")
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


def load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURE_ROOT / name).open(encoding="utf-8") as file:
        return json.load(file)


def make_work(index: int) -> dict[str, Any]:
    """构造字段完整且 ID 稳定的合成 OpenAlex work。"""

    return {
        "id": f"https://openalex.org/W{900000 + index}",
        "display_name": f"Synthetic offline work {index}",
        "authorships": [
            {"author": {"display_name": f"Offline Author {index}"}}
        ],
        "publication_year": 2020 + index % 5,
        "doi": f"https://doi.org/10.0000/offline.{index}",
        "abstract_inverted_index": {"offline": [0], "fixture": [1]},
        "cited_by_count": index,
        "primary_location": {
            "landing_page_url": f"https://example.org/offline/{index}",
            "source": {"display_name": "Offline Fixture Journal"},
        },
    }


def make_payload(
    works: list[dict[str, Any]],
    *,
    next_cursor: str | None,
    count: int | None = None,
) -> dict[str, Any]:
    return {
        "meta": {
            "count": len(works) if count is None else count,
            "per_page": len(works),
            "next_cursor": next_cursor,
        },
        "results": works,
    }


def successful_response(
    works: list[dict[str, Any]], *, next_cursor: str | None = None
) -> StubResponse:
    return StubResponse(
        payload=make_payload(works, next_cursor=next_cursor)
    )


class OpenAlexClientV2Tests(unittest.TestCase):
    """所有 HTTP、等待和时钟均由测试替身控制。"""

    def fetch(
        self,
        request_get: SequencedGet,
        *,
        keyword: str = "machine learning stellar spectra",
        max_results: int = 20,
        sleep_fn: Mock | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return fetch_openalex_papers_v2(
            keyword,
            max_results,
            api_key=TEST_API_KEY,
            request_get=request_get,
            sleep_fn=sleep_fn or Mock(),
            **kwargs,
        )

    def test_single_page_success_uses_fixture_and_project_fields(self) -> None:
        request_get = SequencedGet(
            StubResponse(payload=load_fixture("single_page.json"))
        )

        result = self.fetch(request_get, timeout_seconds=7)

        self.assertEqual(len(result["papers"]), 2)
        self.assertEqual(
            result["papers"][0]["openalex_id"],
            "https://openalex.org/W1001",
        )
        self.assertEqual(result["papers"][0]["abstract"], "stellar spectra")
        self.assertEqual(result["stats"]["status"], "success")
        self.assertEqual(result["stats"]["stopped_reason"], "cursor_exhausted")
        self.assertEqual(result["stats"]["page_count"], 1)
        self.assertEqual(result["stats"]["request_count"], 1)
        self.assertEqual(request_get.calls[0]["url"], OPENALEX_WORKS_URL)
        self.assertEqual(request_get.calls[0]["timeout"], 7)
        self.assertEqual(request_get.calls[0]["params"]["cursor"], "*")
        self.assertEqual(request_get.calls[0]["params"]["per_page"], 20)
        self.assertIn("publication_date", request_get.calls[0]["params"]["select"])
        self.assertIn("type", request_get.calls[0]["params"]["select"].split(","))

    def test_supported_result_limits_20_100_120_and_150(self) -> None:
        for requested in (20, 100, 120, 150):
            with self.subTest(requested=requested):
                first_size = min(100, requested)
                events: list[StubResponse] = [
                    successful_response(
                        [make_work(index) for index in range(first_size)],
                        next_cursor=("page-2" if requested > 100 else "unused"),
                    )
                ]
                if requested > 100:
                    events.append(
                        successful_response(
                            [
                                make_work(index)
                                for index in range(first_size, requested)
                            ],
                            next_cursor="unused-page-3",
                        )
                    )
                request_get = SequencedGet(*events)

                result = self.fetch(request_get, max_results=requested)

                self.assertEqual(len(result["papers"]), requested)
                self.assertEqual(
                    len({paper["openalex_id"] for paper in result["papers"]}),
                    requested,
                )
                self.assertEqual(
                    result["stats"]["stopped_reason"], "max_results_reached"
                )
                self.assertEqual(
                    result["stats"]["page_count"], 1 if requested <= 100 else 2
                )
                self.assertEqual(
                    [call["params"]["per_page"] for call in request_get.calls],
                    [requested]
                    if requested <= 100
                    else [100, requested - 100],
                )
                if requested == 20:
                    self.assertTrue(
                        {"raw_response", "papers"}.issubset(result.keys())
                    )
                    self.assertEqual(len(result["raw_response"]["results"]), 20)
                    self.assertEqual(
                        result["raw_response"]["results"][0]["id"],
                        result["papers"][0]["openalex_id"],
                    )
                    self.assertEqual(
                        set(result["papers"][0]),
                        {
                            "title",
                            "authors",
                            "publication_year",
                            "doi",
                            "abstract",
                            "cited_by_count",
                            "source_name",
                            "openalex_id",
                            "landing_page_url",
                            "keyword",
                            "retrieved_at",
                        },
                    )

    def test_stops_at_max_results_without_requesting_another_page(self) -> None:
        request_get = SequencedGet(
            successful_response(
                [make_work(index) for index in range(25)],
                next_cursor="should-not-be-requested",
            )
        )

        result = self.fetch(request_get, max_results=20)

        self.assertEqual(len(result["papers"]), 20)
        self.assertEqual(len(request_get.calls), 1)
        self.assertEqual(result["stats"]["stopped_reason"], "max_results_reached")

    def test_last_page_short_returns_actual_count_without_padding(self) -> None:
        request_get = SequencedGet(
            successful_response(
                [make_work(index) for index in range(100)],
                next_cursor="short-last-page",
            ),
            successful_response(
                [make_work(index) for index in range(100, 107)],
                next_cursor=None,
            ),
        )

        result = self.fetch(request_get, max_results=150)

        self.assertEqual(len(result["papers"]), 107)
        self.assertEqual(result["stats"]["actual_result_count"], 107)
        self.assertEqual(result["stats"]["page_count"], 2)
        self.assertEqual(result["stats"]["stopped_reason"], "cursor_exhausted")
        self.assertEqual(
            [call["params"]["per_page"] for call in request_get.calls],
            [100, 50],
        )

    def test_cross_page_duplicate_openalex_id_is_skipped(self) -> None:
        request_get = SequencedGet(
            StubResponse(payload=load_fixture("cursor_page_1.json")),
            StubResponse(
                payload=load_fixture("cursor_page_2_with_duplicate.json")
            ),
        )

        result = self.fetch(request_get, max_results=10)

        ids = [paper["openalex_id"] for paper in result["papers"]]
        self.assertEqual(ids, [f"https://openalex.org/W{n}" for n in range(2001, 2006)])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(result["stats"]["duplicate_records_skipped"], 1)
        self.assertEqual(result["stats"]["output_duplicate_id_count"], 0)
        self.assertEqual(result["stats"]["actual_result_count"], 5)
        self.assertEqual(request_get.calls[0]["params"]["cursor"], "*")
        self.assertEqual(
            request_get.calls[1]["params"]["cursor"], "cursor-page-2"
        )

    def test_temporary_server_error_retries_then_succeeds(self) -> None:
        sleep_fn = Mock()
        request_get = SequencedGet(
            StubResponse(status_code=503, payload={}),
            successful_response([make_work(1)]),
        )

        result = self.fetch(
            request_get,
            max_results=1,
            max_retries=2,
            backoff_base_seconds=0.25,
            sleep_fn=sleep_fn,
        )

        self.assertEqual(result["stats"]["request_count"], 2)
        self.assertEqual(result["stats"]["retry_count"], 1)
        sleep_fn.assert_called_once_with(0.25)

    def test_timeout_retries_then_succeeds(self) -> None:
        sleep_fn = Mock()
        request_get = SequencedGet(
            requests.Timeout("offline timeout"),
            successful_response([make_work(1)]),
        )

        result = self.fetch(
            request_get,
            max_results=1,
            max_retries=1,
            backoff_base_seconds=0.5,
            sleep_fn=sleep_fn,
        )

        self.assertEqual(result["stats"]["request_count"], 2)
        self.assertEqual(result["stats"]["retry_count"], 1)
        sleep_fn.assert_called_once_with(0.5)

    def test_retry_after_on_429_overrides_exponential_delay(self) -> None:
        sleep_fn = Mock()
        request_get = SequencedGet(
            StubResponse(
                status_code=429,
                payload={},
                headers={"Retry-After": "3.5"},
            ),
            successful_response([make_work(1)]),
        )

        result = self.fetch(
            request_get,
            max_results=1,
            max_retries=1,
            backoff_base_seconds=0.1,
            max_backoff_seconds=10,
            sleep_fn=sleep_fn,
        )

        self.assertEqual(result["stats"]["retry_count"], 1)
        sleep_fn.assert_called_once_with(3.5)

    def test_exceeding_retry_limit_returns_safe_failure_stats(self) -> None:
        sleep_fn = Mock()
        request_get = SequencedGet(
            StubResponse(status_code=502, payload={}),
            StubResponse(status_code=503, payload={}),
            StubResponse(status_code=504, payload={}),
        )

        with self.assertRaises(OpenAlexClientV2Error) as raised:
            self.fetch(
                request_get,
                max_results=20,
                max_retries=2,
                backoff_base_seconds=0.5,
                sleep_fn=sleep_fn,
            )

        error = raised.exception
        self.assertEqual(error.stats["request_count"], 3)
        self.assertEqual(error.stats["retry_count"], 2)
        self.assertEqual(error.stats["page_count"], 0)
        self.assertEqual(error.stats["status"], "failed")
        self.assertEqual(error.stats["stopped_reason"], "request_failed")
        self.assertEqual(sleep_fn.call_args_list[0].args, (0.5,))
        self.assertEqual(sleep_fn.call_args_list[1].args, (1.0,))

    def test_http_400_is_not_retried(self) -> None:
        sleep_fn = Mock()
        request_get = SequencedGet(StubResponse(status_code=400, payload={}))

        with self.assertRaises(OpenAlexClientV2Error) as raised:
            self.fetch(
                request_get,
                max_retries=5,
                sleep_fn=sleep_fn,
            )

        self.assertIn("HTTP 400", raised.exception.summary)
        self.assertEqual(raised.exception.stats["request_count"], 1)
        self.assertEqual(raised.exception.stats["retry_count"], 0)
        sleep_fn.assert_not_called()

    def test_invalid_json_has_a_finite_retry_and_can_recover(self) -> None:
        sleep_fn = Mock()
        request_get = SequencedGet(
            StubResponse(json_error=ValueError("invalid offline JSON")),
            successful_response([make_work(1)]),
        )

        result = self.fetch(
            request_get,
            max_results=1,
            max_retries=1,
            backoff_base_seconds=0,
            sleep_fn=sleep_fn,
        )

        self.assertEqual(result["stats"]["request_count"], 2)
        self.assertEqual(result["stats"]["retry_count"], 1)
        sleep_fn.assert_called_once_with(0)

    def test_invalid_json_exhaustion_fails_safely(self) -> None:
        request_get = SequencedGet(
            StubResponse(json_error=ValueError("invalid page one")),
            StubResponse(json_error=ValueError("invalid page two")),
        )

        with self.assertRaises(OpenAlexClientV2Error) as raised:
            self.fetch(request_get, max_retries=1)

        self.assertIn("无效 JSON", raised.exception.summary)
        self.assertEqual(raised.exception.stats["request_count"], 2)
        self.assertEqual(raised.exception.stats["retry_count"], 1)

    def test_invalid_year_filter_is_rejected_before_http(self) -> None:
        for filters in (
            {"from_year": 2025, "to_year": 2024},
            {"from_year": 999},
            {"to_year": "2024"},
        ):
            with self.subTest(filters=filters):
                request_get = SequencedGet()
                with self.assertRaises(OpenAlexClientV2Error) as raised:
                    self.fetch(request_get, **filters)
                self.assertEqual(request_get.calls, [])
                self.assertEqual(
                    raised.exception.stats["stopped_reason"],
                    "invalid_parameters",
                )
                self.assertEqual(raised.exception.stats["status"], "failed")
                self.assertEqual(raised.exception.stats["applied_filters"], {})

    def test_non_finite_timing_values_are_rejected_before_http(self) -> None:
        for timing in (
            {"timeout_seconds": float("nan")},
            {"timeout_seconds": float("inf")},
            {"backoff_base_seconds": float("nan")},
            {"max_backoff_seconds": float("inf")},
        ):
            with self.subTest(timing=timing):
                request_get = SequencedGet()
                with self.assertRaises(OpenAlexClientV2Error) as raised:
                    self.fetch(request_get, **timing)
                self.assertEqual(request_get.calls, [])
                self.assertEqual(
                    raised.exception.stats["stopped_reason"],
                    "invalid_parameters",
                )

    def test_malformed_nested_work_is_reported_as_safe_client_error(self) -> None:
        malformed_work = make_work(1)
        malformed_work["primary_location"] = ["not", "an", "object"]
        request_get = SequencedGet(successful_response([malformed_work]))

        with self.assertRaises(OpenAlexClientV2Error) as raised:
            self.fetch(request_get, max_results=1)

        self.assertEqual(raised.exception.stats["status"], "failed")
        self.assertEqual(
            raised.exception.stats["stopped_reason"], "response_invalid"
        )
        self.assertIn("无法转换", raised.exception.summary)
        self.assertNotIn(TEST_API_KEY, str(raised.exception))

    def test_year_filters_are_sent_and_recorded(self) -> None:
        request_get = SequencedGet(successful_response([make_work(1)]))

        result = self.fetch(
            request_get,
            max_results=1,
            from_year=2019,
            to_year=2024,
        )

        self.assertEqual(
            request_get.calls[0]["params"]["filter"],
            "from_publication_date:2019-01-01,to_publication_date:2024-12-31",
        )
        self.assertEqual(
            result["stats"]["applied_filters"],
            {"from_year": 2019, "to_year": 2024},
        )

    def test_omitting_filters_preserves_unfiltered_request(self) -> None:
        request_get = SequencedGet(successful_response([make_work(1)]))

        result = self.fetch(request_get, max_results=1)

        self.assertNotIn("filter", request_get.calls[0]["params"])
        self.assertEqual(result["stats"]["applied_filters"], {})

    def test_request_statistics_are_correct_and_elapsed_is_deterministic(self) -> None:
        sleep_fn = Mock()
        clock = Mock(side_effect=[100.0, 101.23456])
        request_get = SequencedGet(
            StubResponse(status_code=503, payload={}),
            successful_response(
                [make_work(index) for index in range(100)],
                next_cursor="stats-page-2",
            ),
            successful_response(
                [make_work(index) for index in range(100, 120)],
                next_cursor="not-requested",
            ),
        )

        result = self.fetch(
            request_get,
            max_results=120,
            from_year=2020,
            max_retries=1,
            backoff_base_seconds=0,
            sleep_fn=sleep_fn,
            monotonic_fn=clock,
        )

        stats = result["stats"]
        self.assertEqual(
            {key: stats[key] for key in (
                "requested_max_results",
                "actual_result_count",
                "page_count",
                "request_count",
                "retry_count",
                "applied_filters",
                "elapsed_seconds",
                "stopped_reason",
                "status",
            )},
            {
                "requested_max_results": 120,
                "actual_result_count": 120,
                "page_count": 2,
                "request_count": 3,
                "retry_count": 1,
                "applied_filters": {"from_year": 2020},
                "elapsed_seconds": 1.235,
                "stopped_reason": "max_results_reached",
                "status": "success",
            },
        )

    def test_repeated_cursor_fails_before_an_infinite_loop(self) -> None:
        request_get = SequencedGet(
            successful_response([make_work(1)], next_cursor="*")
        )

        with self.assertRaises(OpenAlexClientV2Error) as raised:
            self.fetch(request_get, max_results=2)

        self.assertEqual(len(request_get.calls), 1)
        self.assertEqual(raised.exception.stats["page_count"], 1)
        self.assertEqual(raised.exception.stats["actual_result_count"], 1)
        self.assertEqual(raised.exception.stats["stopped_reason"], "cursor_stalled")

    def test_failure_summary_and_stats_do_not_expose_api_key_or_paths(self) -> None:
        request_get = SequencedGet(StubResponse(status_code=400, payload={}))

        with self.assertRaises(OpenAlexClientV2Error) as raised:
            self.fetch(request_get)

        rendered = json.dumps(
            {
                "error_summary": raised.exception.summary,
                **raised.exception.stats,
            },
            ensure_ascii=False,
        )
        self.assertNotIn(TEST_API_KEY, rendered)
        self.assertNotIn(str(Path.home()), rendered)


class OpenAlexFetchV2CliTests(unittest.TestCase):
    def test_cli_summary_is_offline_reproducible_and_secret_safe(self) -> None:
        stats = {
            "requested_max_results": 120,
            "actual_result_count": 2,
            "page_count": 2,
            "request_count": 3,
            "retry_count": 1,
            "applied_filters": {"from_year": 2020},
            "elapsed_seconds": 0.125,
            "stopped_reason": "cursor_exhausted",
            "status": "success",
            "duplicate_records_skipped": 0,
            "output_duplicate_id_count": 0,
        }
        fake_result = {
            "papers": [
                {"openalex_id": "https://openalex.org/W1"},
                {"openalex_id": "https://openalex.org/W2"},
            ],
            "stats": stats,
            "raw_response": {"results": []},
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            summary_path = Path(temporary_directory) / "live_summary.csv"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch.object(cli, "load_dotenv") as load_dotenv,
                patch.object(cli.os, "getenv", return_value=TEST_API_KEY),
                patch.object(
                    cli,
                    "fetch_openalex_papers_v2",
                    return_value=fake_result,
                ) as fetch,
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                return_code = cli.main(
                    [
                        "--keyword",
                        "machine learning stellar spectra",
                        "--max-results",
                        "120",
                        "--from-year",
                        "2020",
                        "--summary-output",
                        str(summary_path),
                    ]
                )

            self.assertEqual(return_code, 0, stdout.getvalue() + stderr.getvalue())
            load_dotenv.assert_called_once_with(dotenv_path=cli.PROJECT_ROOT / ".env")
            self.assertEqual(fetch.call_args.kwargs["api_key"], TEST_API_KEY)
            self.assertTrue(summary_path.is_file())
            with summary_path.open(encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                rows = list(reader)
            self.assertEqual(reader.fieldnames, cli.SUMMARY_FIELDS)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["keyword"], "machine learning stellar spectra")
            self.assertEqual(rows[0]["requested_max_results"], "120")
            self.assertEqual(rows[0]["actual_result_count"], "2")
            self.assertEqual(rows[0]["page_count"], "2")
            self.assertEqual(rows[0]["request_count"], "3")
            self.assertEqual(rows[0]["retry_count"], "1")
            self.assertEqual(rows[0]["applied_filters"], '{"from_year":2020}')
            self.assertEqual(rows[0]["elapsed_seconds"], "0.125")
            self.assertEqual(rows[0]["stopped_reason"], "cursor_exhausted")
            self.assertEqual(rows[0]["status"], "success")
            self.assertEqual(rows[0]["duplicate_ids_present"], "false")

            raw_summary = summary_path.read_bytes()
            self.assertTrue(raw_summary.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r\n", raw_summary)

            rendered = (
                stdout.getvalue()
                + stderr.getvalue()
                + raw_summary.decode("utf-8-sig")
            )
            self.assertNotIn(TEST_API_KEY, rendered)
            self.assertNotIn(temporary_directory, rendered)
            self.assertNotIn(str(Path.home()), rendered)


if __name__ == "__main__":
    unittest.main()
