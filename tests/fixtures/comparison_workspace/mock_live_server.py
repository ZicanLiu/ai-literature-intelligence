"""Browser-only mock server. Real provider adapters + actual API/storage; SDK transport replaced."""
import argparse
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from unittest.mock import Mock, patch

import uvicorn

from app.comparison_workspace_api import create_app
from tests.fixtures.comparison_workspace.mock_live_sdk import MockRawResponse, response_for


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    # Explicitly discard environment credentials in the test child; no .env loading.
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "COMPARISON_OPENAI_MODEL", "COMPARISON_DEEPSEEK_MODEL"):
        os.environ.pop(name, None)
    os.environ["DISABLE_LIVE_API"] = "false"
    scenario = "success"
    def respond(**options):
        if scenario == "failure":
            raise RuntimeError("Simulated failure before response")
        result = response_for(**options)
        if scenario == "schema":
            result.output_parsed = {"observations": "invalid", "findings": []}
            result.output_text = '{"observations":"invalid","findings":[]}'
        elif scenario == "incomplete":
            result.status = "incomplete"
            result.incomplete_details = {"reason": "max_output_tokens"}
        elif scenario == "identity":
            result.output_parsed.observations[0].evidence = result.output_parsed.observations[1].evidence
            result.output_text = result.output_parsed.model_dump_json()
        elif scenario in {"unknown-handle", "duplicate-handle"}:
            inputs = json.loads(options["input"])
            group = "results" if inputs["stage"] == "extraction" else "observations"
            refs = getattr(result.output_parsed, group)[0].evidence
            refs.append(refs[0].model_copy(update={"evidence_handle": "untrusted-not-declared"})
                        if scenario == "unknown-handle" else refs[0].model_copy())
            result.output_text = result.output_parsed.model_dump_json()
        elif scenario == "empty-extraction":
            result.output_parsed = {"results": []}
            result.output_text = '{"results":[]}'
        elif scenario == "json-syntax":
            result.output_text = '{"observations":['
        elif scenario == "root-shape":
            result.output_parsed = []
            result.output_text = '[]'
        return result
    sdk = Mock()
    sdk.responses.parse.side_effect = respond
    sdk.responses.with_raw_response.parse.side_effect = lambda **kw: MockRawResponse(sdk.responses.parse(**kw))
    sdk.responses.create.side_effect = respond
    sdk.models.list.return_value = SimpleNamespace(data=[SimpleNamespace(id=name) for name in
                                                    ("mock-openai", "deepseek-flash", "deepseek-v4-pro")])
    with patch("openai.OpenAI", return_value=sdk):
        app = create_app(data_dir=args.data_dir)
        frontend = next(route for route in app.routes if route.name == "frontend")
        app.router.routes.remove(frontend)
        release = threading.Event()
        # Test-only controls live exclusively in this SDK-mocked fixture, never in the product API.
        @app.post("/_test/pause-worker")
        def pause_worker():
            release.clear()
            entered = threading.Event()
            def hold():
                entered.set()
                if not release.wait(30):
                    raise AssertionError("Browser worker barrier timed out")
            app.state.workspace.executor.submit(hold)
            if not entered.wait(5):
                raise AssertionError("Browser worker did not reach barrier")
            sdk.reset_mock()
            return {"paused": True}

        @app.post("/_test/release-worker")
        def release_worker():
            release.set()
            return {"released": True}

        @app.get("/_test/sdk-counts")
        def counts():
            return {"openai": sdk.responses.with_raw_response.parse.call_count,
                    "deepseek": sdk.responses.create.call_count, "connection": sdk.models.list.call_count}

        @app.post("/_test/scenario/{value}")
        def set_scenario(value: Literal["success", "failure", "schema", "incomplete", "identity",
                                       "unknown-handle", "duplicate-handle", "empty-extraction", "json-syntax", "root-shape"]):
            nonlocal scenario
            scenario = value
            return {"scenario": scenario}

        app.router.routes.append(frontend)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
