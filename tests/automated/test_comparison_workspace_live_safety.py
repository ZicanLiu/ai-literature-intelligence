"""Revocation races and response provenance: synthetic inputs, no network sockets."""
import copy
import csv
import io
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from src.comparison_workspace.domain.models import Run
from src.comparison_workspace.export.reports import csv_report, markdown, portable
from src.comparison_workspace.providers.base import ProviderFailure
from src.comparison_workspace.services.workspace import Workspace
from src.comparison_workspace.storage.repository import Repository
from tests.automated.test_comparison_workspace_live_ai import KEYS, MODELS, wait_run
from tests.fixtures.comparison_workspace.mock_live_sdk import MockRawResponse, response_for


class LiveSafetyTests(unittest.TestCase):
    def setUp(self):
        # Windows platform.machine() lazily caches architecture from these OS variables.
        # Keep real OS metadata while discarding all provider credentials/configuration.
        system_environment = {name: os.environ[name] for name in
                              ("PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432", "SYSTEMROOT", "WINDIR")
                              if name in os.environ}
        environment = patch.dict(os.environ, system_environment, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        for method in ("connect", "connect_ex"):
            guard = patch("socket.socket." + method, side_effect=AssertionError("Network sockets forbidden"))
            guard.start()
            self.addCleanup(guard.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Workspace(Repository(Path(temp.name)))
        self.addCleanup(self.workspace.close)
        self.settings = self.workspace.live_ai
        self.project, demo = self.workspace.seed_demo()
        wait_run(self.workspace, demo.id)
        self.sdk = Mock()
        self.sdk.responses.with_raw_response.parse.side_effect = lambda **kw: MockRawResponse(response_for(**kw))
        self.sdk.responses.create.side_effect = response_for
        self.sdk.models.list.return_value = SimpleNamespace(data=[SimpleNamespace(id=m) for m in MODELS.values()])
        constructor = patch("openai.OpenAI", return_value=self.sdk)
        constructor.start()
        self.addCleanup(constructor.stop)

    def configure(self, provider):
        self.settings.update(provider, api_key=KEYS[provider], model=MODELS[provider],
                             reasoning_effort="high" if provider == "deepseek" else None,
                             set_effort=True, acknowledge=True, live_enabled=True)

    def revoke(self, provider, event):
        if event == "consent":
            self.settings.update(provider, acknowledge=False)
        elif event == "off":
            self.settings.update(provider, live_enabled=False)
        elif event == "clear":
            self.settings.clear(provider)
        elif event == "switch":
            self.settings.update("deepseek" if provider == "openai" else "openai")
        elif event == "replace":
            self.settings.update(provider, api_key="different-test-credential")
        elif event == "offline":
            os.environ["DISABLE_LIVE_API"] = "true"
        else:
            raise AssertionError("Unknown event")

    def generation_request(self, provider):
        return self.sdk.responses.with_raw_response.parse if provider == "openai" else self.sdk.responses.create

    def block_worker(self):
        entered, release = threading.Event(), threading.Event()
        def hold():
            entered.set()
            if not release.wait(10):
                raise AssertionError("Worker barrier timed out")
        future = self.workspace.executor.submit(hold)
        self.addCleanup(release.set)
        self.assertTrue(entered.wait(5))
        return release, future

    def test_queued_revocations_never_revive_with_same_session_key(self):
        for provider in KEYS:
            for event in ("consent", "off", "clear", "switch", "replace"):
                with self.subTest(provider=provider, event=event):
                    self.configure(provider)
                    self.sdk.reset_mock()
                    release, blocker = self.block_worker()
                    try:
                        old = self.workspace.start_run(self.project.id, self.project.revision, "analysis", "api")
                        self.assertEqual(self.workspace.repo.get_run(old.id).status, "QUEUED")
                        self.revoke(provider, event)
                        self.configure(provider)  # Restore exactly the old key/provider/model/booleans.
                    finally:
                        release.set()
                    blocker.result(timeout=5)
                    failed = wait_run(self.workspace, old.id)
                    self.assertEqual(failed.status, "FAILED")
                    self.assertIsNone(failed.provider_reported_model)
                    self.generation_request(provider).assert_not_called()
                    new = self.workspace.start_run(self.project.id, self.project.revision, "analysis", "api")
                    self.assertEqual(wait_run(self.workspace, new.id).status, "COMPLETED")
                    self.generation_request(provider).assert_called_once()

    def test_clear_same_value_environment_fallback_does_not_revive_generation_or_connection(self):
        for provider in KEYS:
            with self.subTest(provider=provider), patch.dict(os.environ, {f"{provider.upper()}_API_KEY": KEYS[provider]}):
                self.configure(provider)
                old_generation = self.settings.adapter()
                old_connection = self.settings.adapter(connection_test=True)
                self.settings.clear(provider)
                self.settings.update(provider, acknowledge=True, live_enabled=True)
                self.assertEqual(self.settings.status()["providers"][provider]["credential_source"], "environment")
                self.sdk.reset_mock()
                for old in (old_generation, old_connection):
                    with self.assertRaises(ProviderFailure):
                        if old is old_connection:
                            old.test_connection()
                        else:
                            old.extract_results(self.project.model_dump(mode="json"))
                self.generation_request(provider).assert_not_called()
                self.sdk.models.list.assert_not_called()
                self.assertTrue(self.settings.adapter(connection_test=True).test_connection()["ok"])
                self.sdk.models.list.assert_called_once()
                self.settings.adapter().extract_results(self.project.model_dump(mode="json"))
                self.generation_request(provider).assert_called_once()

    def test_queued_model_effort_and_input_snapshot_survive_later_configuration(self):
        for provider in KEYS:
            with self.subTest(provider=provider):
                self.configure(provider)
                self.sdk.reset_mock()
                p = self.workspace.repo.get(self.project.id)
                release, blocker = self.block_worker()
                try:
                    old = self.workspace.start_run(p.id, p.revision, "analysis", "api")
                    frozen = copy.deepcopy(old.input_snapshot)
                    later_model = "deepseek-v4-pro" if provider == "deepseek" else "mock-openai-later"
                    self.settings.update(provider, model=later_model, reasoning_effort=None,
                                         set_effort=True)
                    self.workspace.patch(p.id, p.revision, {"question": p.question + " later"})
                finally:
                    release.set()
                blocker.result(timeout=5)
                run = wait_run(self.workspace, old.id)
                self.assertEqual(run.status, "STALE")
                self.assertEqual(run.requested_model, MODELS[provider])
                self.assertEqual(run.input_snapshot, frozen)
                options = self.generation_request(provider).call_args.kwargs
                self.assertEqual(options["model"], MODELS[provider])
                self.assertEqual(json.loads(options["input"])["question"], frozen["question"])
                if provider == "deepseek":
                    self.assertEqual(run.reasoning_effort, "high")
                    self.assertEqual(options["reasoning"], {"effort": "high"})

    def test_final_boundary_blocks_revocation_after_serialization_and_client_preparation(self):
        for provider in KEYS:
            for operation in ("generation", "connection"):
                events = ("consent", "clear", "switch", "offline") if operation == "generation" else ("clear", "switch", "offline")
                for event in events:
                    with self.subTest(provider=provider, operation=operation, event=event):
                        os.environ["DISABLE_LIVE_API"] = "false"
                        self.configure(provider)
                        self.sdk.reset_mock()
                        adapter = self.settings.adapter(connection_test=operation == "connection")
                        entered, release = threading.Event(), threading.Event()
                        begin_send = adapter._begin_send
                        def boundary(op):
                            entered.set()
                            if not release.wait(5):
                                raise AssertionError("Send barrier timed out")
                            begin_send(op)
                        with patch.object(adapter, "_begin_send", side_effect=boundary), ThreadPoolExecutor(1) as pool:
                            task = pool.submit(adapter.test_connection if operation == "connection" else
                                               adapter.extract_results, *([] if operation == "connection" else
                                               [self.project.model_dump(mode="json")]))
                            try:
                                self.assertTrue(entered.wait(5))
                                self.revoke(provider, event)
                            finally:
                                release.set()
                            with self.assertRaises(ProviderFailure):
                                task.result(timeout=5)
                        self.assertFalse(adapter.send_started)
                        self.generation_request(provider).assert_not_called()
                        self.sdk.models.list.assert_not_called()

    def test_client_preparation_cannot_bypass_final_check_and_connection_is_operation_specific(self):
        for provider in KEYS:
            for connection in (False, True):
                with self.subTest(provider=provider, connection=connection):
                    self.configure(provider)
                    adapter = self.settings.adapter(connection_test=connection)
                    self.sdk.reset_mock()
                    def prepare():
                        self.settings.clear(provider)
                        return self.sdk
                    with patch.object(adapter, "_make_client", side_effect=prepare), self.assertRaises(ProviderFailure):
                        if connection:
                            adapter.test_connection()
                        else:
                            adapter.extract_results(self.project.model_dump(mode="json"))
                    self.generation_request(provider).assert_not_called()
                    self.sdk.models.list.assert_not_called()
            self.settings.update(provider, api_key=KEYS[provider], model=MODELS[provider])
            adapter = self.settings.adapter(connection_test=True)
            with self.assertRaises(ProviderFailure):
                adapter.extract_results(self.project.model_dump(mode="json"))
            self.assertTrue(adapter.test_connection()["ok"])

    def test_old_connection_does_not_revive_after_clear_switch_replacement_or_observed_offline(self):
        for provider in KEYS:
            for event in ("clear", "switch", "replace", "offline"):
                with self.subTest(provider=provider, event=event):
                    os.environ["DISABLE_LIVE_API"] = "false"
                    self.configure(provider)
                    adapter = self.settings.adapter(connection_test=True)
                    self.revoke(provider, event)
                    self.settings.status()  # The service observes the deployment offline transition.
                    os.environ["DISABLE_LIVE_API"] = "false"
                    self.configure(provider)
                    self.sdk.reset_mock()
                    with self.assertRaises(ProviderFailure):
                        adapter.test_connection()
                    self.sdk.models.list.assert_not_called()
                    self.assertTrue(self.settings.adapter(connection_test=True).test_connection()["ok"])
                    self.sdk.models.list.assert_called_once()

    def test_revocation_after_send_entry_returns_promptly_and_does_not_claim_recall(self):
        for provider in KEYS:
            for connection in (False, True):
                with self.subTest(provider=provider, connection=connection):
                    self.configure(provider)
                    adapter = self.settings.adapter(connection_test=connection)
                    entered, release = threading.Event(), threading.Event()
                    request = self.sdk.models.list if connection else self.generation_request(provider)
                    original = request.side_effect
                    def sent(**kw):
                        entered.set()
                        if not release.wait(5):
                            raise AssertionError("In-flight barrier timed out")
                        return request.return_value if connection else original(**kw)
                    request.side_effect = sent
                    try:
                        with ThreadPoolExecutor(2) as pool:
                            task = pool.submit(adapter.test_connection if connection else adapter.extract_results,
                                               *([] if connection else [self.project.model_dump(mode="json")]))
                            try:
                                self.assertTrue(entered.wait(5))
                                self.assertTrue(adapter.send_started)
                                pool.submit(self.settings.update, provider, acknowledge=False).result(timeout=1)
                                self.assertFalse(self.settings.status()["api_enabled"])
                            finally:
                                release.set()
                            result = task.result(timeout=5)
                            self.assertTrue(result["ok"] if connection else result.model)
                    finally:
                        request.side_effect = original

    def test_restart_discards_session_authorization_and_interrupts_without_retry(self):
        captured = {}
        for provider in KEYS:
            self.configure(provider)
            captured[provider] = self.settings.adapter()
        self.settings.close()
        for provider in KEYS:
            for status in ("QUEUED", "RUNNING"):
                self.workspace.repo.add_run(Run(project_id=self.project.id, input_revision=self.project.revision,
                    input_snapshot=self.project.model_dump(mode="json"), mode="api", provider=provider, stage="analysis",
                    requested_model=MODELS[provider], status=status))
        self.sdk.reset_mock()
        restarted = Workspace(Repository(self.workspace.repo.data_dir))
        self.addCleanup(restarted.close)
        state = restarted.live_ai.status()
        self.assertFalse(state["live_enabled"])
        self.assertTrue(all(not p["credential_configured"] and not p["consent_acknowledged"] for p in state["providers"].values()))
        self.assertEqual([r.status for r in restarted.repo.runs(self.project.id)][:4], ["INTERRUPTED"] * 4)
        for provider in KEYS:
            self.configure(provider)
            self.assertFalse(captured[provider].enabled)
        self.sdk.responses.with_raw_response.parse.assert_not_called()
        self.sdk.responses.create.assert_not_called()
        self.sdk.models.list.assert_not_called()

    def test_pre_response_sdk_failures_never_invent_reported_model(self):
        request = httpx.Request("POST", "https://example.invalid/responses")
        for provider in KEYS:
            for error in (APIStatusError(KEYS[provider], response=httpx.Response(401, request=request,
                          headers={"x-request-id": "req_auth"}), body=None), APITimeoutError(request=request),
                          APIConnectionError(message=KEYS[provider], request=request), RuntimeError(KEYS[provider])):
                with self.subTest(provider=provider, error=type(error).__name__):
                    self.configure(provider)
                    method = self.generation_request(provider)
                    original = method.side_effect
                    method.side_effect = error
                    try:
                        run = self.workspace.start_run(self.project.id, self.project.revision, "analysis", "api")
                        failed = wait_run(self.workspace, run.id)
                    finally:
                        method.side_effect = original
                    self.assertEqual(failed.status, "FAILED")
                    self.assertEqual(failed.requested_model, MODELS[provider])
                    self.assertIsNone(failed.provider_reported_model)
                    self.assertIsNone(failed.model)
                    self.assertIsNone(failed.provider_status)
                    self.assertIsNone(failed.incomplete_details)
                    self.assertNotIn(KEYS[provider], failed.model_dump_json())
                    if isinstance(error, APIStatusError):
                        self.assertEqual(failed.request_id, "req_auth")

    def test_real_sdk_mock_transport_retains_response_metadata_before_local_schema_failure(self):
        # Exercise actual SDK parsing with in-memory HTTP transport, never a socket.
        for provider in KEYS:
            for case in ("success", "schema", "refusal", "incomplete", "identity", "missing_model"):
                with self.subTest(provider=provider, case=case):
                    self.configure(provider)
                    adapter = self.settings.adapter()
                    calls = []
                    output = {"observations": [], "findings": []}
                    if case == "schema":
                        output["observations"] = "invalid"
                    if case == "identity":
                        output["observations"] = [{"result_id": "not-active", "dimension": "x", "value": "x",
                                                   "state": "PRESENT", "evidence": []}]
                    text = json.dumps(output)
                    def transport(request):
                        calls.append(json.loads(request.content))
                        content = [{"type": "refusal", "refusal": "mock refusal"}] if case == "refusal" else [
                            {"type": "output_text", "text": text, "annotations": []}]
                        return httpx.Response(200, headers={"x-request-id": "req_reported"}, json={
                            "id": "resp_mock", "object": "response", "created_at": 1,
                            "status": "incomplete" if case == "incomplete" else "completed",
                            "incomplete_details": {"reason": "max_output_tokens"} if case == "incomplete" else None,
                            "model": None if case == "missing_model" else "provider-B",
                            "output": [{"id": "msg_mock", "type": "message", "role": "assistant",
                                        "status": "completed", "content": content}],
                            "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}})
                    with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
                        adapter._client = OpenAI(api_key=KEYS[provider], base_url=adapter.base_url,
                                                 http_client=http_client, max_retries=0)
                        run = self.workspace.start_run(self.project.id, self.project.revision, "analysis", "api", provider=adapter)
                        finished = wait_run(self.workspace, run.id)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(finished.requested_model, MODELS[provider])
                    self.assertEqual(finished.provider_reported_model, None if case == "missing_model" else "provider-B")
                    self.assertEqual(finished.request_id, "req_reported")
                    self.assertEqual(finished.token_usage["total_tokens"], 5)
                    self.assertEqual(finished.provider_status, "incomplete" if case == "incomplete" else "completed")
                    self.assertEqual(finished.incomplete_details, {"reason": "max_output_tokens"} if case == "incomplete" else None)
                    self.assertEqual(finished.status, "COMPLETED" if case in {"success", "missing_model"} else "FAILED")
                    view = self.workspace.view(self.project.id)
                    exported = portable(view)
                    item = next(r for r in exported["runs"] if r["id"] == run.id)
                    self.assertEqual(item["provider_reported_model"], finished.provider_reported_model)
                    self.assertEqual(item["requested_model"], MODELS[provider])
                    records = csv.DictReader(io.StringIO(csv_report(view)))
                    item = next(json.loads(r["record_json"]) for r in records if r["record_type"] == "runs" and r["id"] == run.id)
                    self.assertEqual(item["provider_reported_model"], finished.provider_reported_model)
                    self.assertIn("requested_model=" + MODELS[provider], markdown(view))
                    for key in KEYS.values():
                        self.assertNotIn(key, markdown(view))

    def test_legacy_model_is_preserved_without_backfilling_requested_or_reported_fields(self):
        legacy = Run(project_id=self.project.id, input_revision=self.project.revision,
                     input_snapshot=self.project.model_dump(mode="json"), mode="api", stage="analysis",
                     provider="openai", model="ambiguous-legacy", status="FAILED")
        self.workspace.repo.add_run(legacy)
        restored = self.workspace.repo.get_run(legacy.id)
        self.assertEqual(restored.model, "ambiguous-legacy")
        self.assertIsNone(restored.requested_model)
        self.assertIsNone(restored.provider_reported_model)
        text = markdown(self.workspace.view(self.project.id))
        self.assertIn("provider_reported_model=未取得服务端返回模型", text)
        self.assertIn("仅兼容保留，来源不由此字段推断", text)


if __name__ == "__main__":
    unittest.main()
