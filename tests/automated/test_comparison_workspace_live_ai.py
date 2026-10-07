"""BYO provider regressions: synthetic documents and sentinel credentials, strictly mocked transport."""
import copy
import io
import json
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.comparison_workspace_api import create_app
from src.comparison_workspace.demo.content import pdf_path
from src.comparison_workspace.domain.models import AnalysisOutput, WorkspaceError
from src.comparison_workspace.providers.base import ProviderFailure
from src.comparison_workspace.providers.deepseek_provider import DeepSeekProvider
from src.comparison_workspace.providers.openai_provider import OpenAIProvider
from src.comparison_workspace.services.live_ai import LiveAISettings, model_capabilities
from src.comparison_workspace.services.workspace import Workspace
from src.comparison_workspace.storage.repository import Repository
from tests.fixtures.comparison_workspace.mock_live_sdk import MockRawResponse, response_for

ROOT = Path(__file__).resolve().parents[2]
# Assemble sentinels so configured complete secrets cannot occur in Git/build/reports.
KEYS = {name: "sk-test-" + name.upper() + "-" + "SUPER-SECRET" for name in ("openai", "deepseek")}
MODELS = {"openai": "mock-openai", "deepseek": "deepseek-flash"}


def wait_run(workspace, run_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = workspace.repo.get_run(run_id)
        if run.status not in {"QUEUED", "RUNNING"}:
            return run
        time.sleep(.01)
    raise AssertionError("Mock run did not finish")


class SessionSettingsTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.settings = LiveAISettings()

    def test_default_off_absent_kill_switch_and_independent_configuration(self):
        state = self.settings.status()
        self.assertFalse(state["hard_offline"])
        self.assertFalse(state["live_enabled"])
        for provider in KEYS:
            other = "deepseek" if provider == "openai" else "openai"
            settings = LiveAISettings()
            state = settings.update(provider, api_key=KEYS[provider], model=MODELS[provider])
            self.assertEqual(state["providers"][provider]["credential_source"], "session")
            self.assertFalse(state["providers"][other]["credential_configured"])
            with self.assertRaises(WorkspaceError):
                settings.adapter()

    def test_switching_and_clear_preserve_other_provider(self):
        for provider in KEYS:
            self.settings.update(provider, api_key=KEYS[provider], model=MODELS[provider], acknowledge=True)
        for provider in KEYS:
            self.settings.update(provider, live_enabled=True)
            adapter = self.settings.adapter()
            self.assertEqual(adapter._api_key, KEYS[provider])
            self.assertEqual(adapter.model, MODELS[provider])
        self.settings.clear("openai")
        state = self.settings.status()
        self.assertFalse(state["providers"]["openai"]["credential_configured"])
        self.assertTrue(state["providers"]["deepseek"]["credential_configured"])

    def test_environment_fallback_session_precedence_and_close(self):
        for provider in KEYS:
            with self.subTest(provider=provider), patch.dict(os.environ, {
                    f"{provider.upper()}_API_KEY": "environment-placeholder",
                    f"COMPARISON_{provider.upper()}_MODEL": MODELS[provider]}):
                self.settings.update(provider, acknowledge=True, live_enabled=True)
                self.assertEqual(self.settings.adapter()._api_key, "environment-placeholder")
                adapter_type = OpenAIProvider if provider == "openai" else DeepSeekProvider
                self.assertEqual(adapter_type.from_environment(explicit_enabled=True)._api_key, "environment-placeholder")
                self.settings.update(provider, api_key=KEYS[provider])
                self.assertEqual(self.settings.adapter()._api_key, KEYS[provider])
                state = self.settings.clear(provider)
                self.assertEqual(state["providers"][provider]["credential_source"], "environment")
                self.assertFalse(state["api_enabled"])
        self.settings.close()
        self.assertTrue(all(not item["credential_configured"] for item in self.settings.status()["providers"].values()))

    def test_consent_and_kill_switch_apply_to_both_generation_and_connection(self):
        for provider in KEYS:
            self.settings.update(provider, api_key=KEYS[provider], model=MODELS[provider])
            with self.assertRaises(WorkspaceError):
                self.settings.update(provider, live_enabled=True)
            self.settings.update(provider, acknowledge=True, live_enabled=True)
            adapter = self.settings.adapter()
            with patch.dict(os.environ, {"DISABLE_LIVE_API": "true"}), patch("openai.OpenAI") as sdk:
                for connection_test in (False, True):
                    with self.assertRaises(WorkspaceError):
                        self.settings.adapter(connection_test=connection_test)
                with self.assertRaises(ProviderFailure):
                    adapter.extract_results({})
                sdk.assert_not_called()

    def test_snapshot_controls_and_revoke_when_switching_provider(self):
        self.settings.update("deepseek", api_key=KEYS["deepseek"], model="deepseek-flash",
                             reasoning_effort="high", set_effort=True, acknowledge=True, live_enabled=True)
        captured = self.settings.adapter()
        self.settings.update("deepseek", model="deepseek-v4-pro", reasoning_effort="none", set_effort=True)
        self.assertEqual(captured.model, "deepseek-flash")
        self.assertEqual(captured.reasoning_effort, "high")
        self.settings.update("openai", api_key=KEYS["openai"], model=MODELS["openai"], acknowledge=True, live_enabled=True)
        self.assertFalse(captured.enabled)

    def test_key_replacement_revokes_captured_credential(self):
        self.settings.update("openai", api_key=KEYS["openai"], model=MODELS["openai"], acknowledge=True, live_enabled=True)
        captured = self.settings.adapter()
        self.settings.clear("openai")
        self.assertFalse(captured.enabled)
        self.settings.update("openai", api_key="replacement-placeholder", acknowledge=True, live_enabled=True)
        self.assertFalse(captured.enabled)

    def test_model_capabilities(self):
        flash = model_capabilities("deepseek", "deepseek-flash")
        self.assertTrue(flash["image"])
        self.assertTrue(flash["json_schema"])
        self.assertTrue(flash["reasoning_effort"])
        self.assertFalse(model_capabilities("deepseek", "deepseek-v4-pro")["image"])
        self.assertIsNone(model_capabilities("openai", "arbitrary-selected-model")["image"])
        self.assertEqual(flash["workspace_input_mode"], "extracted_text")


class DeepSeekAdapterTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"DISABLE_LIVE_API": "false"})
        environment.start()
        self.addCleanup(environment.stop)
        self.snapshot = {"id": "project", "revision": 0, "question": "question", "scope": "",
                         "papers": [], "observations": [], "evidence": []}
        self.client = Mock()
        self.response = SimpleNamespace(model="deepseek-reported", _request_id="req_mock", status="completed",
                                        output_text='{"observations":[],"findings":[]}', usage=None)
        self.client.responses.create.return_value = self.response
        self.provider = DeepSeekProvider(api_key=KEYS["deepseek"], model="deepseek-flash",
                                         reasoning_effort="high", explicit_enabled=True,
                                         hard_offline=False, client=self.client)

    def test_schema_local_validation_reasoning_and_text_only(self):
        result = self.provider.analyze_comparison(self.snapshot, [], [])
        options = self.client.responses.create.call_args.kwargs
        self.assertEqual(options["text"]["format"]["schema"], AnalysisOutput.model_json_schema())
        self.assertEqual(options["reasoning"], {"effort": "high"})
        self.assertNotIn("store", options)
        self.assertNotIn(KEYS["deepseek"], json.dumps(options))
        self.assertIsInstance(options["input"], str)
        self.assertEqual(result.request_id, "req_mock")
        self.assertEqual(result.model, "deepseek-reported")
        self.client.responses.parse.assert_not_called()

    def test_each_reasoning_setting_and_default(self):
        for effort in (None, "none", "low", "high", "max"):
            self.provider.reasoning_effort = effort
            self.provider.analyze_comparison(self.snapshot, [], [])
            options = self.client.responses.create.call_args.kwargs
            self.assertEqual(options["reasoning"], {"effort": effort if effort is not None else "high"})

    def test_invalid_incomplete_refused_output_is_rejected_without_retry(self):
        for text, status in (("not json", "completed"), ('{"observations":"invalid","findings":[]}', "completed"),
                             ('{"observations":[],"findings":[],"extra":true}', "completed"),
                             ("", "completed"), ('{"observations":[],"findings":[]}', "incomplete")):
            with self.subTest(text=text):
                self.client.reset_mock()
                self.response.output_text, self.response.status = text, status
                with self.assertRaises(ProviderFailure):
                    self.provider.analyze_comparison(self.snapshot, [], [])
                self.client.responses.create.assert_called_once()

    def test_official_endpoint_zero_retries_and_timeout(self):
        with patch("openai.OpenAI", return_value=self.client) as sdk:
            provider = DeepSeekProvider(api_key=KEYS["deepseek"], model="deepseek-v4-pro",
                                        explicit_enabled=True, hard_offline=False)
            provider.analyze_comparison(self.snapshot, [], [])
            self.assertEqual(sdk.call_args.kwargs["base_url"], "https://api.deepseek.com")
            self.assertEqual(sdk.call_args.kwargs["max_retries"], 0)
            self.assertEqual(sdk.call_args.kwargs["timeout"], 120.)

    def test_connection_success_and_model_unavailable(self):
        self.client.models.list.return_value = SimpleNamespace(data=[SimpleNamespace(id="deepseek-flash")])
        self.assertTrue(self.provider.test_connection()["ok"])
        self.client.responses.create.assert_not_called()
        self.client.models.list.return_value = SimpleNamespace(data=[])
        with self.assertRaisesRegex(ProviderFailure, "模型"):
            self.provider.test_connection()

    def test_safe_failure_request_id_is_retained(self):
        request = httpx.Request("POST", "https://api.deepseek.com/responses")
        self.client.responses.create.side_effect = APIStatusError("private body", response=httpx.Response(
            429, request=request, headers={"x-request-id": "req_rate_limit"}), body=None)
        with self.assertRaises(ProviderFailure) as caught:
            self.provider.analyze_comparison(self.snapshot, [], [])
        self.assertEqual(caught.exception.request_id, "req_rate_limit")

    def test_auth_rate_model_network_timeout_failures_are_safe_and_never_retried(self):
        request = httpx.Request("POST", "https://api.deepseek.com/responses")
        errors = [APIStatusError(KEYS["deepseek"], response=httpx.Response(status, request=request,
                         headers={"x-request-id": KEYS["deepseek"]}), body={"key": KEYS["deepseek"]})
                  for status in (401, 403, 404, 429, 500)]
        errors += [APITimeoutError(request=request), APIConnectionError(message=KEYS["deepseek"], request=request)]
        for error in errors:
            for operation in ("generate", "connection"):
                with self.subTest(error=type(error).__name__, operation=operation):
                    self.client.reset_mock()
                    self.client.responses.create.side_effect = error
                    self.client.models.list.side_effect = error
                    with self.assertRaises(ProviderFailure) as caught:
                        if operation == "generate":
                            self.provider.analyze_comparison(self.snapshot, [], [])
                        else:
                            self.provider.test_connection()
                    self.assertNotIn(KEYS["deepseek"], str(caught.exception))
                    self.assertNotIn(KEYS["deepseek"], str(caught.exception.request_id))
                    method = self.client.responses.create if operation == "generate" else self.client.models.list
                    method.assert_called_once()


class LiveHTTPTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Repository(Path(temp.name))
        self.workspace = Workspace(self.repo)
        self.client = TestClient(create_app(workspace=self.workspace), base_url="http://127.0.0.1")
        self.client.__enter__()
        self.addCleanup(lambda: self.client.__exit__(None, None, None))
        self.sdk = Mock()
        self.sdk.responses.parse.side_effect = response_for
        self.sdk.responses.with_raw_response.parse.side_effect = lambda **kw: MockRawResponse(self.sdk.responses.parse(**kw))
        self.sdk.responses.create.side_effect = response_for
        self.sdk.models.list.return_value = SimpleNamespace(data=[SimpleNamespace(id=m) for m in MODELS.values()])
        constructor = patch("openai.OpenAI", return_value=self.sdk)
        self.constructor = constructor.start()
        self.addCleanup(constructor.stop)

    def setup_provider(self, provider, live=False):
        return self.client.patch("/api/ai-settings", json={"provider": provider, "api_key": KEYS[provider],
            "model": MODELS[provider], "reasoning_effort": "high" if provider == "deepseek" else None,
            "acknowledge": live, "live_enabled": live})

    def create_uploaded_project(self):
        p = self.client.post("/api/projects", json={"title": "mock live", "question": "Compare reported results"}).json()
        for letter in ("A", "B"):
            p = self.client.post(f'/api/projects/{p["id"]}/papers', data={"expected_revision": p["revision"]},
                                 files={"file": ("public-synthetic.pdf", pdf_path(letter).read_bytes(), "application/pdf")}).json()
        return p

    def test_both_mock_extraction_selection_analysis_evidence_correction_export_and_no_persistence(self):
        logs = io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        self.addCleanup(lambda: logging.getLogger().removeHandler(handler))
        for provider in KEYS:
            self.assertEqual(self.setup_provider(provider, live=True).status_code, 200)
            self.assertEqual(self.client.post("/api/ai-settings/test-connection").status_code, 200)
            p = self.create_uploaded_project()
            result = self.client.post(f'/api/projects/{p["id"]}/extractions', json={"mode": "api", "expected_revision": p["revision"]})
            self.assertEqual(result.status_code, 202)
            extraction = wait_run(self.workspace, result.json()["run_id"])
            self.assertEqual(extraction.status, "COMPLETED")
            p = self.client.get(f'/api/projects/{p["id"]}').json()
            for paper in p["papers"]:
                p = self.client.patch(f'/api/projects/{p["id"]}/papers/{paper["id"]}/active-result',
                    json={"expected_revision": p["revision"], "result_id": paper["results"][0]["id"]}).json()
            result = self.client.post(f'/api/projects/{p["id"]}/analyses', json={"mode": "api", "expected_revision": p["revision"]})
            analysis = wait_run(self.workspace, result.json()["run_id"])
            self.assertEqual(analysis.status, "COMPLETED")
            self.assertEqual(analysis.provider, provider)
            self.assertEqual(analysis.requested_model, MODELS[provider])
            self.assertEqual(analysis.provider_reported_model, MODELS[provider]+"-reported")
            self.assertEqual(analysis.input_modality, "EXTRACTED_TEXT")
            self.assertEqual(analysis.reasoning_effort, "high" if provider == "deepseek" else None)
            self.assertEqual(analysis.request_id, "req_mock_live")
            self.assertEqual(analysis.token_usage["total_tokens"], 30)
            self.assertIsNotNone(analysis.elapsed_seconds)
            self.assertEqual(analysis.input_snapshot["revision"], analysis.input_revision)
            self.assertTrue(all(p["source"]["sha256"] and p["active_target_result_id"] for p in analysis.input_snapshot["papers"]))
            p = self.client.get(f'/api/projects/{p["id"]}').json()
            self.assertTrue(all(e["locator_status"] == "LOCATED" for e in p["evidence"]))
            original = copy.deepcopy(analysis.output)
            observation = p["observations"][0]
            corrected = self.client.post(f'/api/projects/{p["id"]}/corrections', json={"expected_revision": p["revision"],
                "target_kind": "observation", "target_id": observation["id"], "after": {"value": "Reviewed mock evidence"},
                "rationale": "Synthetic source reviewed", "evidence_ids": observation["evidence_ids"]})
            self.assertEqual(corrected.status_code, 201)
            self.assertEqual(self.repo.get_run(analysis.id).output, original)
            for path in ("/api/capabilities", "/api/projects", f'/api/projects/{p["id"]}', f'/api/runs/{analysis.id}',
                         *(f'/api/projects/{p["id"]}/exports/{kind}' for kind in ("markdown", "json", "csv"))):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                for key in KEYS.values():
                    self.assertNotIn(key, response.text)
            for file in self.repo.data_dir.rglob("*"):
                if file.is_file():
                    for key in KEYS.values():
                        self.assertNotIn(key.encode(), file.read_bytes())
        for key in KEYS.values():
            self.assertNotIn(key, logs.getvalue())
        # A fresh process settings object cannot recover session credentials from this database.
        restarted = Workspace(Repository(self.repo.data_dir))
        self.addCleanup(restarted.close)
        self.assertFalse(restarted.live_ai.status()["live_enabled"])
        self.assertTrue(all(not item["credential_configured"] for item in restarted.live_ai.status()["providers"].values()))

    def test_validation_errors_do_not_echo_key_or_browser_endpoint(self):
        for provider in KEYS:
            for extra in ({"base_url": "https://example.invalid"}, {"provider": "arbitrary"}, {"model": []}, {"model": KEYS[provider]},
                          {"reasoning_effort": "unsupported"}, {"api_key": [KEYS[provider]]}):
                response = self.client.patch("/api/ai-settings", json={"provider": provider,
                                                    "api_key": KEYS[provider], **extra})
                self.assertEqual(response.status_code, 422)
                self.assertNotIn(KEYS[provider], response.text)
            self.assertEqual(self.setup_provider(provider).status_code, 200)
        self.constructor.assert_not_called()

    def test_explicit_false_withdraws_and_wins_over_enable_but_omission_preserves(self):
        p = self.create_uploaded_project()
        for provider in KEYS:
            for enable in (None, True):
                with self.subTest(provider=provider, conflicting_enable=enable):
                    self.setup_provider(provider, live=True)
                    self.sdk.reset_mock()
                    captured = self.workspace.live_ai.adapter()
                    body = {"provider": provider, "acknowledge": False}
                    if enable is not None:
                        body["live_enabled"] = enable
                    response = self.client.patch("/api/ai-settings", json=body)
                    self.assertEqual(response.status_code, 200)
                    state = response.json()
                    self.assertFalse(state["providers"][provider]["consent_acknowledged"])
                    self.assertFalse(state["live_enabled"])
                    self.assertFalse(state["api_enabled"])
                    denied = self.client.post(f'/api/projects/{p["id"]}/extractions',
                                              json={"expected_revision": p["revision"], "mode": "api"})
                    self.assertEqual(denied.status_code, 422)
                    with self.assertRaises(ProviderFailure):
                        captured.extract_results(p)
                    self.sdk.responses.with_raw_response.parse.assert_not_called()
                    self.sdk.responses.create.assert_not_called()
            self.setup_provider(provider, live=True)
            body = {"provider": provider, "model": MODELS[provider]}
            if provider == "deepseek":
                body["reasoning_effort"] = "none"
            response = self.client.patch("/api/ai-settings", json=body)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["providers"][provider]["consent_acknowledged"])
            self.assertTrue(response.json()["api_enabled"])

    def test_disabled_live_no_automatic_calls_and_hard_offline_http(self):
        p = self.create_uploaded_project()
        for provider in KEYS:
            self.setup_provider(provider)
            result = self.client.post(f'/api/projects/{p["id"]}/extractions', json={"mode": "api", "expected_revision": p["revision"]})
            self.assertEqual(result.status_code, 422)
            with patch.dict(os.environ, {"DISABLE_LIVE_API": "true"}):
                self.assertEqual(self.setup_provider(provider, live=True).status_code, 422)
                self.assertEqual(self.client.post("/api/ai-settings/test-connection").status_code, 422)
            self.constructor.assert_not_called()
        self.assertEqual(self.repo.runs(p["id"]), [])

    def test_remote_origin_and_host_cannot_configure_credentials(self):
        for headers in ({"Origin": "https://example.invalid"}, {"Host": "example.invalid", "Origin": "http://example.invalid"}):
            response = self.client.patch("/api/ai-settings", json={"provider": "deepseek", "api_key": KEYS["deepseek"]}, headers=headers)
            self.assertIn(response.status_code, (400, 403))
        self.assertFalse(self.workspace.live_ai.status()["providers"]["deepseek"]["credential_configured"])

    def test_error_responses_and_failed_runs_never_persist_sdk_secret(self):
        p = self.create_uploaded_project()
        for provider in KEYS:
            self.setup_provider(provider, live=True)
            self.sdk.models.list.side_effect = RuntimeError(KEYS[provider])
            error = self.client.post("/api/ai-settings/test-connection")
            self.assertEqual(error.status_code, 422)
            self.assertNotIn(KEYS[provider], error.text)
            self.sdk.responses.parse.side_effect = RuntimeError(KEYS[provider])
            self.sdk.responses.create.side_effect = RuntimeError(KEYS[provider])
            result = self.client.post(f'/api/projects/{p["id"]}/extractions', json={"mode": "api", "expected_revision": p["revision"]})
            run = wait_run(self.workspace, result.json()["run_id"])
            self.assertEqual(run.status, "FAILED")
            self.assertNotIn(KEYS[provider], self.client.get(f'/api/runs/{run.id}').text)
            self.assertNotIn(KEYS[provider].encode(), self.repo.db.read_bytes())

    def test_complete_sentinels_absent_from_sources_build_and_reports(self):
        # Persistence scan targets declared product inputs/outputs, not unrelated private workspace files.
        targets = [ROOT/"app/comparison_workspace_api.py", ROOT/"app/comparison_workspace_main.py"]
        for directory in ("src/comparison_workspace", "web/comparison-workspace/src", "web/comparison-workspace/dist",
                          "reports/comparison_workspace_v011_20261005", "reports/comparison_workspace_v011_live_fix_20261006",
                          "tests/fixtures/comparison_workspace", "web/comparison-workspace/test-results",
                          "web/comparison-workspace/playwright-report", "temp/workspace-live-browser-tests"):
            targets.extend(p for p in (ROOT/directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        for target in targets:
            for key in KEYS.values():
                self.assertNotIn(key.encode(), target.read_bytes(), str(target.relative_to(ROOT)))


if __name__ == "__main__":
    unittest.main()
