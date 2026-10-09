"""Operation defaults and safe failure diagnostics; synthetic proposals, no network sockets."""
import copy
import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.comparison_workspace.export.reports import csv_report, markdown, portable
from src.comparison_workspace.services.workspace import Workspace
from src.comparison_workspace.storage.repository import Repository
from tests.automated.test_comparison_workspace_live_ai import KEYS, MODELS, wait_run
from tests.fixtures.comparison_workspace.mock_live_sdk import MockRawResponse, response_for


class S1DiagnosticsTests(unittest.TestCase):
    def setUp(self):
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
        self.repo = Repository(Path(temp.name))
        self.workspace = Workspace(self.repo)
        self.addCleanup(self.workspace.close)
        self.project, demo = self.workspace.seed_demo()
        self.assertEqual(wait_run(self.workspace, demo.id).status, "COMPLETED")
        self.sdk = Mock()
        self.respond = response_for
        self.sdk.responses.create.side_effect = lambda **kw: self.respond(**kw)
        self.sdk.responses.with_raw_response.parse.side_effect = lambda **kw: MockRawResponse(self.respond(**kw))
        constructor = patch("openai.OpenAI", return_value=self.sdk)
        constructor.start()
        self.addCleanup(constructor.stop)

    def configure(self, provider, effort=None):
        self.workspace.live_ai.update(provider, api_key=KEYS[provider], model=MODELS[provider],
                                      reasoning_effort=effort, set_effort=True, acknowledge=True, live_enabled=True)

    def run_attempt(self, provider, stage="analysis", effort=None):
        self.configure(provider, effort)
        before = self.repo.get(self.project.id).model_dump(mode="json")
        queued = self.workspace.start_run(self.project.id, before["revision"], stage, "api")
        return before, wait_run(self.workspace, queued.id)

    def assert_failed_state_unchanged(self, before, run):
        self.assertEqual(run.status, "FAILED")
        self.assertIsNone(run.output)
        self.assertEqual(self.repo.get(self.project.id).model_dump(mode="json"), before)
        restored = Repository(self.repo.data_dir).get_run(run.id)
        self.assertEqual(restored.model_dump(mode="json"), run.model_dump(mode="json"))

    def assert_exported_diagnostics(self, run):
        view = self.workspace.view(self.project.id)
        exported = next(r for r in portable(view)["runs"] if r["id"] == run.id)
        csv_item = next(json.loads(row["record_json"]) for row in csv.DictReader(io.StringIO(csv_report(view)))
                        if row["record_type"] == "runs" and row["id"] == run.id)
        for record in (exported, csv_item):
            self.assertEqual(record["max_output_tokens"], run.max_output_tokens)
            self.assertEqual(record["provider_status"], run.provider_status)
            self.assertEqual(record["incomplete_details"], run.incomplete_details)
            self.assertEqual(record["validation_diagnostic"], run.validation_diagnostic.model_dump() if run.validation_diagnostic else None)
        self.assertIn("provider_status=" + (run.provider_status or "unknown"), markdown(view))
        self.assertIn("max_output_tokens=" + str(run.max_output_tokens), markdown(view))
        if run.validation_diagnostic:
            self.assertIn(run.validation_diagnostic.field_path, markdown(view))

    def test_extraction_defaults_to_none_and_analysis_to_high_with_actual_run_provenance(self):
        for stage, expected, budget in (("extraction", "none", 12000), ("analysis", "high", 32000)):
            with self.subTest(stage=stage):
                _, run = self.run_attempt("deepseek", stage)
                self.assertEqual(run.status, "COMPLETED")
                self.assertEqual(run.reasoning_effort, expected)
                request = self.sdk.responses.create.call_args.kwargs
                self.assertEqual(request["reasoning"], {"effort": expected})
                self.assertEqual(request["max_output_tokens"], budget)
                self.assertEqual(run.max_output_tokens, budget)
                self.assertEqual(self.repo.get_run(run.id).max_output_tokens, budget)
                self.assert_exported_diagnostics(run)
        settings = self.workspace.live_ai.status()["providers"]["deepseek"]
        self.assertIsNone(settings["reasoning_effort"])
        self.assertEqual(settings["reasoning_defaults"], {"extraction": "none", "analysis": "high"})
        self.assertEqual(settings["output_budget_defaults"], {"extraction": 12000, "analysis": 32000})

    def test_explicit_override_wins_and_clearing_restores_operation_default(self):
        for stage, default, budget in (("extraction", "none", 12000), ("analysis", "high", 32000)):
            for effort in ("none", "low", "high", "max", None):
                with self.subTest(stage=stage, effort=effort):
                    _, run = self.run_attempt("deepseek", stage, effort)
                    expected = effort if effort is not None else default
                    self.assertEqual(run.status, "COMPLETED")
                    self.assertEqual(run.reasoning_effort, expected)
                    self.assertEqual(self.sdk.responses.create.call_args.kwargs["reasoning"], {"effort": expected})
                    self.assertEqual(run.max_output_tokens, budget)

    def test_incomplete_response_persists_status_reason_usage_and_never_mutates_project(self):
        def incomplete(**options):
            result = response_for(**options)
            result.status = "incomplete"
            result.incomplete_details = {"reason": "max_output_tokens", "unsafe": KEYS["deepseek"]}
            return result
        self.respond = incomplete
        for provider in KEYS:
            with self.subTest(provider=provider):
                self.sdk.reset_mock()
                before, run = self.run_attempt(provider)
                self.assert_failed_state_unchanged(before, run)
                self.assertEqual(run.provider_status, "incomplete")
                self.assertEqual(run.incomplete_details, {"reason": "max_output_tokens"})
                self.assertEqual(run.requested_model, MODELS[provider])
                self.assertEqual(run.provider_reported_model, MODELS[provider] + "-reported")
                self.assertEqual(run.request_id, "req_mock_live")
                self.assertEqual(run.token_usage["total_tokens"], 30)
                self.assertIsNotNone(run.elapsed_seconds)
                self.assertIn("max_output_tokens", run.failure_reason)
                self.assertIsNone(run.validation_diagnostic)
                self.assert_exported_diagnostics(run)
                method = self.sdk.responses.create if provider == "deepseek" else self.sdk.responses.with_raw_response.parse
                method.assert_called_once()
                self.assertNotIn(KEYS["deepseek"], run.model_dump_json())

    def test_pre_response_failure_keeps_provider_status_and_incomplete_details_unknown(self):
        def failure(**options):
            raise RuntimeError(KEYS["openai"])
        self.respond = failure
        for provider in KEYS:
            with self.subTest(provider=provider):
                before, run = self.run_attempt(provider)
                self.assert_failed_state_unchanged(before, run)
                self.assertIsNone(run.provider_status)
                self.assertIsNone(run.incomplete_details)
                self.assertIsNone(run.provider_reported_model)
                self.assertIsNone(run.validation_diagnostic)
                self.assertNotIn(KEYS["openai"], run.model_dump_json())

    def test_completed_cross_paper_evidence_is_rejected_with_exact_path_and_identities(self):
        def foreign(**options):
            result = response_for(**options)
            result.output_parsed.observations[0].evidence.append(copy.deepcopy(result.output_parsed.observations[1].evidence[0]))
            result.output_text = result.output_parsed.model_dump_json()
            return result
        self.respond = foreign
        for provider in KEYS:
            with self.subTest(provider=provider):
                before, run = self.run_attempt(provider)
                self.assert_failed_state_unchanged(before, run)
                self.assertEqual(run.provider_status, "completed")
                self.assertIn("提供方引用了其他论文的证据", run.failure_reason)
                diagnostic = run.validation_diagnostic
                self.assertEqual(diagnostic.field_path, "$.observations[0].evidence[1].paper_id")
                self.assertEqual(diagnostic.rule, "evidence_paper_ownership")
                a, b = before["papers"][:2]
                self.assertEqual(diagnostic.expected[0].model_dump(), {"paper_id": a["id"], "source_snapshot_id": a["source"]["id"]})
                self.assertEqual(diagnostic.returned.model_dump(), {"paper_id": b["id"], "source_snapshot_id": b["source"]["id"]})
                self.assert_exported_diagnostics(run)

    def test_finding_evidence_stays_within_affected_results_not_all_project_papers(self):
        def foreign(**options):
            result = response_for(**options)
            finding = result.output_parsed.findings[0]
            finding.affected_result_ids = [result.output_parsed.observations[0].result_id]
            finding.evidence = [copy.deepcopy(result.output_parsed.observations[1].evidence[0])]
            result.output_text = result.output_parsed.model_dump_json()
            return result
        self.respond = foreign
        before, run = self.run_attempt("deepseek")
        self.assert_failed_state_unchanged(before, run)
        self.assertEqual(run.validation_diagnostic.field_path, "$.findings[0].evidence[0].paper_id")
        self.assertEqual(run.validation_diagnostic.rule, "evidence_paper_ownership")

    def test_model_cannot_override_host_owned_source_identity(self):
        def foreign_source(**options):
            result = response_for(**options)
            raw = result.output_parsed.model_dump(mode="json")
            raw["observations"][0]["evidence"][0]["source_snapshot_id"] = json.loads(options["input"])["papers"][1]["source"]["id"]
            result.output_parsed = raw
            result.output_text = json.dumps(raw)
            return result
        self.respond = foreign_source
        before, run = self.run_attempt("deepseek")
        self.assert_failed_state_unchanged(before, run)
        self.assertEqual(run.validation_diagnostic.field_path, "$.observations[0].evidence[0].source_snapshot_id")
        self.assertEqual(run.validation_diagnostic.rule, "structured_output_schema")
        self.assertIsNone(run.validation_diagnostic.returned)

    def test_completed_schema_failure_persists_only_safe_field_path(self):
        def malformed(**options):
            result = response_for(**options)
            result.output_parsed = {"observations": KEYS["deepseek"], "findings": []}
            result.output_text = json.dumps(result.output_parsed)
            return result
        self.respond = malformed
        for provider in KEYS:
            with self.subTest(provider=provider):
                before, run = self.run_attempt(provider)
                self.assert_failed_state_unchanged(before, run)
                self.assertEqual(run.provider_status, "completed")
                self.assertEqual(run.validation_diagnostic.field_path, "$.observations")
                self.assertEqual(run.validation_diagnostic.rule, "structured_output_schema")
                self.assertNotIn(KEYS["deepseek"], run.model_dump_json())
                self.assert_exported_diagnostics(run)

    def test_unknown_identity_and_provider_metadata_cannot_leak_credentials_or_paths(self):
        private_path = "/" + "Users" + "/" + "private-test-user" + "/credential.txt"
        def unsafe(**options):
            result = response_for(**options)
            candidate = result.output_parsed.observations[0].evidence[0]
            candidate.evidence_handle = private_path
            result.output_text = result.output_parsed.model_dump_json()
            result.model = result._request_id = KEYS["deepseek"]
            result.incomplete_details = {"reason": KEYS["deepseek"], "private_body": private_path}
            return result
        self.respond = unsafe
        before, run = self.run_attempt("deepseek")
        self.assert_failed_state_unchanged(before, run)
        self.assertIsNone(run.provider_reported_model)
        self.assertIsNone(run.request_id)
        self.assertEqual(run.incomplete_details, {"reason": None})
        self.assertEqual(run.validation_diagnostic.rule, "evidence_handle_identity")
        self.assertIsNone(run.validation_diagnostic.returned)
        view = self.workspace.view(self.project.id)
        for output in (run.model_dump_json(), json.dumps(portable(view)), markdown(view), csv_report(view)):
            self.assertNotIn(private_path, output)
            for key in KEYS.values():
                self.assertNotIn(key, output)
        for file in self.repo.data_dir.rglob("*"):
            if file.is_file():
                for key in KEYS.values():
                    self.assertNotIn(key.encode(), file.read_bytes())
                self.assertNotIn(private_path.encode(), file.read_bytes())

    def test_schema_extra_field_name_is_never_copied_into_diagnostics(self):
        def unsafe(**options):
            result = response_for(**options)
            result.output_parsed = {"observations": [], "findings": [], KEYS["deepseek"]: "private"}
            result.output_text = json.dumps(result.output_parsed)
            return result
        self.respond = unsafe
        before, run = self.run_attempt("deepseek")
        self.assert_failed_state_unchanged(before, run)
        self.assertEqual(run.validation_diagnostic.field_path, "$")
        self.assertNotIn(KEYS["deepseek"], run.model_dump_json())

    def test_untrusted_status_reason_and_usage_are_sanitized_without_raw_exception_dump(self):
        def unsafe_metadata(**options):
            result = response_for(**options)
            result.status = KEYS["deepseek"]
            result.incomplete_details = {"reason": KEYS["deepseek"], "body": KEYS["deepseek"]}
            result.usage = SimpleNamespace(model_dump=lambda **kw: {
                "input_tokens": KEYS["deepseek"], "output_tokens": True, "total_tokens": 30,
                "unsafe": KEYS["deepseek"], "output_tokens_details": {"reasoning_tokens": KEYS["deepseek"]}})
            return result
        self.respond = unsafe_metadata
        for provider in KEYS:
            with self.subTest(provider=provider):
                before, run = self.run_attempt(provider)
                self.assert_failed_state_unchanged(before, run)
                self.assertIsNone(run.provider_status)
                self.assertEqual(run.incomplete_details, {"reason": None})
                self.assertEqual(run.token_usage, {"total_tokens": 30})
                self.assertNotIn(KEYS["deepseek"], run.model_dump_json())


if __name__ == "__main__":
    unittest.main()
