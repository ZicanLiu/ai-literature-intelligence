"""Evidence handles, unchanged ownership guards, and optional read-only historical replay."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from openai import OpenAI as SDKClient

from src.comparison_workspace.domain.models import (
    AnalysisOutput, ExtractionOutput, OutputValidationFailure, Project, Run,
)
from src.comparison_workspace.providers.base import ProviderResult
from src.comparison_workspace.providers.deepseek_provider import DeepSeekProvider
from src.comparison_workspace.providers.evidence_handles import APIAnalysisOutput, APIExtractionOutput
from src.comparison_workspace.providers.openai_provider import OpenAIProvider
from src.comparison_workspace.services.workspace import Workspace
from src.comparison_workspace.storage.repository import Repository
from tests.automated.test_comparison_workspace_live_ai import KEYS, MODELS, wait_run
from tests.fixtures.comparison_workspace.mock_live_sdk import MockRawResponse, response_for


class EvidenceHandleTests(unittest.TestCase):
    def setUp(self):
        env = {name: os.environ[name] for name in
               ("PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432", "SYSTEMROOT", "WINDIR") if name in os.environ}
        env["DISABLE_LIVE_API"] = "false"  # Mock SDK only; socket guards apply to every test.
        guard = patch.dict(os.environ, env, clear=True)
        guard.start()
        self.addCleanup(guard.stop)
        for name in ("connect", "connect_ex"):
            guard = patch("socket.socket." + name, side_effect=AssertionError("Network forbidden"))
            guard.start()
            self.addCleanup(guard.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Workspace(Repository(Path(temp.name)))
        self.addCleanup(self.workspace.close)
        self.project, run = self.workspace.seed_demo()
        self.assertEqual(wait_run(self.workspace, run.id).status, "COMPLETED")
        self.sdk = Mock()
        self.respond = response_for
        self.sdk.responses.create.side_effect = lambda **kw: self.respond(**kw)
        self.sdk.responses.with_raw_response.parse.side_effect = lambda **kw: MockRawResponse(self.respond(**kw))
        guard = patch("openai.OpenAI", return_value=self.sdk)
        guard.start()
        self.addCleanup(guard.stop)

    def attempt(self, provider, stage):
        self.workspace.live_ai.update(provider, api_key=KEYS[provider], model=MODELS[provider],
                                      acknowledge=True, live_enabled=True)
        before = self.workspace.repo.get(self.project.id).model_dump(mode="json")
        queued = self.workspace.start_run(self.project.id, before["revision"], stage, "api")
        return before, wait_run(self.workspace, queued.id)

    def assert_rejected(self, before, run, rule):
        self.assertEqual(run.status, "FAILED")
        self.assertIsNone(run.output)
        self.assertEqual(run.validation_diagnostic.rule, rule)
        self.assertEqual(self.workspace.repo.get(self.project.id).model_dump(mode="json"), before)
        self.assertEqual(run.provider_status, "completed")
        self.assertEqual(run.request_id, "req_mock_live")

    @staticmethod
    def first_group(stage):
        return "results" if stage == "extraction" else "observations"

    def test_successful_cross_paper_findings_and_host_owned_evidence(self):
        for provider in KEYS:
            for stage in ("extraction", "analysis"):
                with self.subTest(provider=provider, stage=stage):
                    before, run = self.attempt(provider, stage)
                    self.assertEqual(run.status, "COMPLETED")
                    for item in run.output["evidence"]:
                        paper = next(p for p in before["papers"] if p["id"] == item["paper_id"])
                        self.assertEqual(item["source_snapshot_id"], paper["source"]["id"])
                        self.assertEqual(item["page_text_sha256"], paper["source"]["pages"][item["page_index"]]["text_sha256"])
                        self.assertEqual(item["locator_status"], "LOCATED")
                    raw = run.output["provider_output"]
                    reference = raw[self.first_group(stage)][0]["evidence"][0]
                    self.assertEqual(set(reference), {"evidence_handle", "quote"})
                    binding = run.output["evidence_handle_sources"][reference["evidence_handle"]]
                    self.assertEqual(binding, {key: run.output["evidence"][0][key]
                                               for key in ("paper_id", "source_snapshot_id", "page_index")})
                    if stage == "analysis":
                        self.assertEqual(run.output["findings"][0]["category"], "SUPPORTED_PREREQUISITE")
                        self.assertEqual(len(run.output["findings"][0]["affected_result_ids"]), 3)

    def test_other_paper_handle_is_resolved_truthfully_and_strictly_rejected(self):
        for stage in ("extraction", "analysis"):
            group = self.first_group(stage)
            def foreign(**options):
                result = response_for(**options)
                candidates = getattr(result.output_parsed, group)
                candidates[0].evidence = copy.deepcopy(candidates[1].evidence)
                result.output_text = result.output_parsed.model_dump_json()
                return result
            self.respond = foreign
            for provider in KEYS:
                with self.subTest(stage=stage, provider=provider):
                    before, run = self.attempt(provider, stage)
                    self.assert_rejected(before, run, "evidence_paper_ownership")
                    self.assertEqual(run.validation_diagnostic.field_path, f"$.{group}[0].evidence[0].paper_id")
                    self.assertEqual(run.validation_diagnostic.returned.paper_id, before["papers"][1]["id"])
                    self.assertEqual(run.validation_diagnostic.returned.source_snapshot_id, before["papers"][1]["source"]["id"])

    def test_real_sdk_parses_nonempty_handle_output_using_in_memory_transport(self):
        for provider, adapter_type in (("openai", OpenAIProvider), ("deepseek", DeepSeekProvider)):
            for stage in ("extraction", "analysis"):
                with self.subTest(provider=provider, stage=stage):
                    calls = []
                    def transport(request):
                        options = json.loads(request.content)
                        calls.append(options)
                        proposal = response_for(**options)
                        return httpx.Response(200, headers={"x-request-id": "req_in_memory"}, json={
                            "id": "resp_mock", "object": "response", "created_at": 1, "status": "completed",
                            "model": MODELS[provider],
                            "output": [{"id": "msg_mock", "type": "message", "role": "assistant", "status": "completed",
                                        "content": [{"type": "output_text", "text": proposal.output_text, "annotations": []}]}],
                            "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}})
                    with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
                        with SDKClient(api_key=KEYS[provider], http_client=http_client, max_retries=0) as sdk:
                            adapter = adapter_type(explicit_enabled=True, hard_offline=False, api_key=KEYS[provider],
                                                   model=MODELS[provider], client=sdk)
                            before = self.workspace.repo.get(self.project.id)
                            queued = self.workspace.start_run(before.id, before.revision, stage, "api", provider=adapter)
                            run = wait_run(self.workspace, queued.id)
                    self.assertEqual(run.status, "COMPLETED", run.failure_reason)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(run.request_id, "req_in_memory")
                    self.assertTrue(run.output["evidence_handle_sources"])
                    self.assertTrue(all(e["locator_status"] == "LOCATED" for e in run.output["evidence"]))

    def test_missing_duplicate_unknown_and_forged_evidence_references(self):
        for stage in ("extraction", "analysis"):
            group = self.first_group(stage)
            for case in ("missing", "duplicate", "unknown", "forged"):
                def invalid(**options):
                    result = response_for(**options)
                    raw = result.output_parsed.model_dump(mode="json")
                    refs = raw[group][0]["evidence"]
                    if case == "missing":
                        del refs[0]["evidence_handle"]
                    elif case == "duplicate":
                        refs.append(copy.deepcopy(refs[0]))
                    else:
                        refs[0]["evidence_handle"] = "not-declared" if case == "unknown" else refs[0]["evidence_handle"] + "-forged"
                    result.output_parsed, result.output_text = raw, json.dumps(raw)
                    return result
                self.respond = invalid
                for provider in KEYS:
                    with self.subTest(stage=stage, case=case, provider=provider):
                        before, run = self.attempt(provider, stage)
                        self.assert_rejected(before, run, "structured_output_schema" if case == "missing" else "evidence_handle_identity")
                        self.assertIsNone(run.validation_diagnostic.returned)

    def test_explicit_model_identity_fields_cannot_override_the_handle(self):
        for stage in ("extraction", "analysis"):
            group = self.first_group(stage)
            for field in ("paper_id", "source_snapshot_id", "page_index"):
                def override(**options):
                    result = response_for(**options)
                    raw = result.output_parsed.model_dump(mode="json")
                    raw[group][0]["evidence"][0][field] = 0 if field == "page_index" else "other-paper"
                    result.output_parsed, result.output_text = raw, json.dumps(raw)
                    return result
                self.respond = override
                for provider in KEYS:
                    with self.subTest(stage=stage, field=field, provider=provider):
                        before, run = self.attempt(provider, stage)
                        self.assert_rejected(before, run, "structured_output_schema")

    def test_handle_from_another_request_is_not_accepted(self):
        previous = None
        def reuse(**options):
            nonlocal previous
            result = response_for(**options)
            reference = result.output_parsed.results[0].evidence[0]
            if previous is None:
                previous = reference.evidence_handle
            else:
                reference.evidence_handle = previous
            result.output_text = result.output_parsed.model_dump_json()
            return result
        self.respond = reuse
        self.assertEqual(self.attempt("deepseek", "extraction")[1].status, "COMPLETED")
        before, run = self.attempt("deepseek", "extraction")
        self.assert_rejected(before, run, "evidence_handle_identity")

    def test_false_quote_does_not_trigger_identity_or_text_repair(self):
        for stage in ("extraction", "analysis"):
            group = self.first_group(stage)
            def wrong_quote(**options):
                result = response_for(**options)
                # The other paper's complete page is not a quote from this paper.
                other = json.loads(options["input"])["papers"][1]["source"]["pages"][0]["text"]
                getattr(result.output_parsed, group)[0].evidence[0].quote = other
                result.output_text = result.output_parsed.model_dump_json()
                return result
            self.respond = wrong_quote
            before, run = self.attempt("deepseek", stage)
            self.assertEqual(run.status, "COMPLETED")
            evidence = run.output["evidence"][0]
            self.assertEqual(evidence["paper_id"], before["papers"][0]["id"])
            self.assertEqual(evidence["source_snapshot_id"], before["papers"][0]["source"]["id"])
            self.assertEqual(evidence["locator_status"], "INVALID")
            self.assertIsNone(evidence["start"])
            if stage == "analysis":
                self.assertEqual(run.output["observations"][0]["state"], "AMBIGUOUS")

    def test_same_page_can_support_distinct_quotes_without_duplicate_references(self):
        def distinct(**options):
            result = response_for(**options)
            refs = result.output_parsed.results[0].evidence
            text = json.loads(options["input"])["papers"][0]["source"]["pages"][0]["text"]
            quote = next(line for line in text.splitlines() if line.strip() and line != refs[0].quote and text.count(line) == 1)
            refs.append(refs[0].model_copy(update={"quote": quote}))
            result.output_text = result.output_parsed.model_dump_json()
            return result
        self.respond = distinct
        _, run = self.attempt("deepseek", "extraction")
        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual([e["locator_status"] for e in run.output["evidence"][:2]], ["LOCATED", "LOCATED"])
        self.assertNotEqual(run.output["evidence"][0]["id"], run.output["evidence"][1]["id"])

    def test_ambiguous_snapshot_identity_and_tampered_page_fail_before_sending(self):
        for case in ("paper", "source", "page", "hash"):
            snapshot = self.project.model_dump(mode="json")
            a, b = snapshot["papers"][:2]
            if case == "paper":
                b["id"] = a["id"]
            elif case == "source":
                b["source"]["id"] = a["source"]["id"]
            elif case == "page":
                a["source"]["pages"][0]["page_index"] = 1
            else:
                a["source"]["pages"][0]["text"] += "modified"
            adapter = DeepSeekProvider(explicit_enabled=True, hard_offline=False, api_key=KEYS["deepseek"],
                                       model=MODELS["deepseek"], client=self.sdk)
            from src.comparison_workspace.providers.base import ProviderFailure
            with self.subTest(case=case), self.assertRaises(ProviderFailure):
                adapter.extract_results(snapshot)
        self.sdk.responses.create.assert_not_called()

    def test_legacy_source_mismatch_is_still_rejected_by_workspace_validator(self):
        p = self.project
        a, b = p.papers[:2]
        raw = AnalysisOutput(observations=[dict(result_id=a.active_target_result_id, dimension="x", value="x",
            state="PRESENT", evidence=[dict(paper_id=a.id, source_snapshot_id=b.source.id, page_index=0, quote="x")])], findings=[])
        run = Run(project_id=p.id, input_revision=p.revision, input_snapshot=p.model_dump(mode="json"),
                  mode="import", stage="analysis", provider="import")
        with self.assertRaises(OutputValidationFailure) as caught:
            self.workspace.validate_output(p, run, ProviderResult(raw))
        self.assertEqual(caught.exception.diagnostic.rule, "evidence_source_identity")

    def test_saved_s1b_diagnostic_matches_unchanged_guard(self):
        fixture = Path(__file__).parents[1] / "fixtures/comparison_workspace/s1b_identity_diagnostic_20261008.json"
        saved = json.loads(fixture.read_text(encoding="utf-8"))
        expected = saved["validation_diagnostic"]["expected"][0]
        returned = saved["validation_diagnostic"]["returned"]
        p = self.project.model_copy(deep=True)
        p.papers = p.papers[:2]
        for paper, identity in zip(p.papers, (expected, returned)):
            paper.id, paper.source.id = identity["paper_id"], identity["source_snapshot_id"]
        # A diagnostic scaffold, NOT a reconstruction of the missing model response.
        result = dict(paper_id=expected["paper_id"], title="Diagnostic scaffold", description="Unknown original semantics",
                      experiment_identity="Not research evidence", evidence=[])
        third = {**result, "evidence": [{**returned, "page_index": 0, "quote": "Unknown original quote"}]}
        raw = ExtractionOutput(results=[result, result, third])
        run = Run(project_id=p.id, input_revision=p.revision, input_snapshot=p.model_dump(mode="json"),
                  mode="api", stage=saved["stage"], provider="deepseek")
        with self.assertRaises(OutputValidationFailure) as caught:
            self.workspace.validate_output(p, run, ProviderResult(raw, provider_status=saved["provider_status"]))
        self.assertEqual(caught.exception.diagnostic.model_dump(mode="json"), saved["validation_diagnostic"])


@unittest.skipUnless(os.getenv("COMPARISON_IDENTITY_REPLAY_ROOT"), "Optional external S1-A captures not configured")
class HistoricalIdentityReplayTests(unittest.TestCase):
    def test_saved_s1a_proposals_roundtrip_both_adapters_without_identity_or_locator_changes(self):
        root = Path(os.environ["COMPARISON_IDENTITY_REPLAY_ROOT"]) / "captures"
        runs = [Run.model_validate_json(path.read_text(encoding="utf-8")) for path in root.glob("run_*.json")]
        successful = [run for run in runs if run.status == "COMPLETED"]
        self.assertEqual({run.stage for run in successful}, {"extraction", "analysis"})
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Repository(Path(temp)))
            self.addCleanup(workspace.close)
            for run in successful:
                original = run.output["provider_output"]
                canonical_schema = ExtractionOutput if run.stage == "extraction" else AnalysisOutput
                wire_schema = APIExtractionOutput if run.stage == "extraction" else APIAnalysisOutput
                def replay(**options):
                    inputs = json.loads(options["input"])
                    lookup = {(p["id"], p["source"]["id"], page["page_index"]): page["evidence_handle"]
                              for p in inputs["papers"] for page in p["source"]["pages"]}
                    wire = copy.deepcopy(original)
                    for candidates in wire.values():
                        for candidate in candidates:
                            candidate["evidence"] = [{"evidence_handle": lookup[(e["paper_id"], e["source_snapshot_id"], e["page_index"])],
                                                      "quote": e["quote"]} for e in candidate["evidence"]]
                    return SimpleNamespace(output_parsed=wire_schema.model_validate(wire), output_text=json.dumps(wire),
                                           model=run.provider_reported_model, _request_id=run.request_id, usage=None, status="completed")
                for adapter_type in (OpenAIProvider, DeepSeekProvider):
                    with self.subTest(stage=run.stage, adapter=adapter_type.__name__), patch.dict(os.environ, {"DISABLE_LIVE_API": "false"}), \
                            patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
                        sdk = Mock()
                        sdk.responses.create.side_effect = replay
                        sdk.responses.with_raw_response.parse.side_effect = lambda **kw: MockRawResponse(replay(**kw))
                        adapter = adapter_type(explicit_enabled=True, hard_offline=False, api_key="mock-placeholder", model="mock", client=sdk)
                        snapshot = copy.deepcopy(run.input_snapshot)
                        response = (adapter.extract_results(snapshot) if run.stage == "extraction"
                                    else adapter.analyze_comparison(snapshot, [], []))
                        self.assertEqual(response.output.model_dump(mode="json"), canonical_schema.model_validate(original).model_dump(mode="json"))
                        self.assertEqual(snapshot, run.input_snapshot)
                        output = workspace.validate_output(Project.model_validate(snapshot), run, response)
                        # New IDs/timestamps are expected. Compare every original source binding and locator exactly.
                        def evidence_values(items):
                            return [{key: value for key, value in item.items() if key != "id"} for item in items]
                        self.assertEqual(evidence_values(output["evidence"]), evidence_values(run.output["evidence"]))
                        for group in ("observations", "findings") if run.stage == "analysis" else ("results",):
                            def semantic_values(items):
                                return [{k: v for k, v in item.items() if k not in {"id", "evidence_ids", "provenance"}} for item in items]
                            self.assertEqual(semantic_values(output[group]), semantic_values(run.output[group]))


if __name__ == "__main__":
    unittest.main()
