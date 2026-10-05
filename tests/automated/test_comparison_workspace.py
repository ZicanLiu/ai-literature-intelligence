"""Product regressions use synthetic PDFs only; no network, labels or private evidence."""
from __future__ import annotations

import copy
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from app.comparison_workspace_api import create_app, default_data_dir
from src.comparison_workspace.demo.content import pdf_path
from src.comparison_workspace.domain.models import (
    AnalysisOutput, Category, EvidenceCandidate, FindingCandidate, Mode, Observation,
    PageText, Project, Run, WorkspaceError,
)
from src.comparison_workspace.export.reports import csv_report, markdown, portable
from src.comparison_workspace.pdf.sources import MAX_BYTES, locate, parse_pdf, sha256
from src.comparison_workspace.providers.base import ProviderFailure, ProviderResult
from src.comparison_workspace.providers.imported import PrecomputedImportProvider
from src.comparison_workspace.providers.openai_provider import OpenAIProvider
from src.comparison_workspace.services.workspace import Workspace
from src.comparison_workspace.storage.repository import Repository


def wait_run(workspace, run):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        saved = workspace.repo.get_run(run.id)
        if saved.status not in {"QUEUED", "RUNNING"}:
            return saved
        time.sleep(0.01)
    raise AssertionError("offline run did not finish")


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Repository(Path(self.temp.name) / "data")
        self.w = Workspace(self.repo)
        self.addCleanup(self.w.close)
        self.p, run = self.w.seed_demo()
        self.run = wait_run(self.w, run)
        self.assertEqual(self.run.status, "COMPLETED")
        self.p = self.repo.get(self.p.id)
        self.a, self.b, self.c = self.p.papers
        self.raw = pdf_path("A").read_bytes()

    def run_analysis(self, mode="demo", provider=None):
        p = self.repo.get(self.p.id)
        return wait_run(self.w, self.w.start_run(p.id, p.revision, "analysis", mode, provider=provider))

    def evidence(self, paper=None, page=1, quote="Evaluation split: random split."):
        p = paper or self.a
        return EvidenceCandidate(paper_id=p.id, source_snapshot_id=p.source.id, page_index=page, quote=quote)

    def import_document(self):
        p = self.repo.get(self.p.id)
        return {"schema_version": p.schema_version, "project_id": p.id, "input_revision": p.revision,
                "question": p.question, "scope": p.scope,
                "sources": {x.id: {"source_snapshot_id": x.source.id, "sha256": x.source.sha256} for x in p.papers},
                "active_target_result_ids": {x.id: x.active_target_result_id for x in p.papers},
                "analysis": {"observations": [], "findings": []}}

    def test_valid_pdf_and_exact_raw_bytes(self):
        self.assertEqual(self.a.source.page_count, 2)
        self.assertEqual(self.a.source.parse_status, "TEXT_EXTRACTED")
        self.assertEqual(self.a.source.sha256, sha256(self.raw))
        self.assertEqual((self.repo.sources_dir / f"{self.a.source.id}.pdf").read_bytes(), self.raw)
        for x in self.p.papers:
            for page in x.source.pages:
                self.assertIn("SYNTHETIC DEMO", page.text)
                self.assertIn("NOT RESEARCH EVIDENCE", page.text)

    def test_corrupt_and_encrypted_pdf_rejected(self):
        for data in (b"not pdf", b"%PDF-1.7\nbroken"):
            with self.subTest(data=data), self.assertRaises(WorkspaceError):
                parse_pdf(data, "broken.pdf")
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        writer.encrypt("test-only-password")
        stream = io.BytesIO()
        writer.write(stream)
        with self.assertRaisesRegex(WorkspaceError, "加密"):
            parse_pdf(stream.getvalue(), "encrypted.pdf")

    def test_size_and_page_limits_reject_without_truncation(self):
        with self.assertRaises(WorkspaceError) as context:
            parse_pdf(b"%PDF-" + b"0" * MAX_BYTES, "large.pdf")
        self.assertEqual(context.exception.status_code, 413)
        writer = PdfWriter()
        for _ in range(101):
            writer.add_blank_page(width=100, height=100)
        stream = io.BytesIO()
        writer.write(stream)
        with self.assertRaises(WorkspaceError) as context:
            parse_pdf(stream.getvalue(), "pages.pdf")
        self.assertEqual(context.exception.status_code, 413)

    def test_duplicate_upload_unicode_filename_and_no_client_paths(self):
        p = self.w.create("真实上传路径测试", "报告了什么？")
        updated = self.w.upload(p.id, 0, self.raw, "文件夹/论文_🪐.pdf")
        self.assertEqual(updated.papers[0].source.original_filename, "论文_🪐.pdf")
        with self.assertRaises(WorkspaceError) as context:
            self.w.upload(p.id, updated.revision, self.raw, "another.pdf")
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(len(self.repo.get(p.id).papers), 1)

    def test_correct_page_quote_and_unicode_offsets(self):
        span = locate(self.evidence(), self.a)
        self.assertEqual(span.locator_status, "LOCATED")
        text = self.a.source.pages[1].text
        self.assertEqual(text[span.start:span.end], span.quote)
        paper = self.a.model_copy(deep=True)
        text = "前缀🪐 文本😀测试 结束"
        paper.source.pages[0] = PageText(page_index=0, text=text, text_sha256=sha256(text.encode()))
        span = locate(self.evidence(paper, 0, "文本😀测试"), paper)
        self.assertEqual(span.start, 4)
        self.assertEqual(span.end, 9)
        self.assertEqual(span.page_text_sha256, sha256(text.encode()))
        self.assertEqual(text[span.start:span.end], span.quote)

    def test_invalid_page_mismatch_and_repeated_quote_are_reviewable(self):
        for candidate in (self.evidence(page=-1), self.evidence(page=99),
                          self.evidence(quote="nonexistent quotation")):
            span = locate(candidate, self.a)
            self.assertEqual(span.locator_status, "INVALID")
            self.assertIsNone(span.start)
            self.assertTrue(span.review_reason)
        p = self.a.model_copy(deep=True)
        p.source.pages[0].text = "same / same"
        span = locate(self.evidence(p, 0, "same"), p)
        self.assertEqual(span.locator_status, "INVALID")
        self.assertIn("歧义", span.review_reason)

    def test_cross_paper_locator_and_observation_rejected(self):
        with self.assertRaises(WorkspaceError):
            locate(self.evidence(self.b), self.a)
        ev = next(e for e in self.p.evidence if e.paper_id == self.b.id)
        with self.assertRaises(WorkspaceError):
            self.w.add_observation(self.p.id, self.p.revision,
                {"result_id": self.a.active_target_result_id, "dimension": "another",
                 "value": "x", "state": "PRESENT", "evidence_ids": [ev.id]})
        self.assertEqual(self.repo.get(self.p.id).revision, self.p.revision)

    def test_multiple_candidates_and_exactly_one_active_target(self):
        self.assertEqual([len(p.results) for p in self.p.papers], [2, 2, 2])
        p = self.w.select(self.p.id, self.p.revision, self.a.id, self.a.results[1].id)
        self.assertEqual(p.papers[0].active_target_result_id, self.a.results[1].id)
        self.assertTrue(self.w.view(p.id)["analysis_stale"])
        self.assertEqual(self.repo.get_run(self.run.id).output, self.run.output)
        with self.assertRaises(WorkspaceError):
            self.w.select(p.id, p.revision, self.a.id, self.b.results[0].id)

    def test_cannot_analyze_before_active_targets_selected(self):
        p = self.w.select(self.p.id, self.p.revision, self.b.id, None)
        with self.assertRaisesRegex(WorkspaceError, "活动目标"):
            self.w.start_run(p.id, p.revision, "analysis", "demo")

    def test_report_question_differences_are_allowed_not_blockers(self):
        view = self.w.view(self.p.id)
        cats = [f["category"] for f in view["findings"]]
        self.assertIn(Category.ALLOWED, cats)
        self.assertNotIn(Category.BLOCKER, cats)
        self.assertTrue(any(o["state"] == "NOT_LOCATED" for o in view["observations"]))

    def test_question_conditioning_blocker_coexists_with_unknown(self):
        p = self.w.patch(self.p.id, self.p.revision, {"demo_question": "protocol"})
        self.assertTrue(self.w.view(p.id)["analysis_stale"])
        self.assertEqual(self.run_analysis().status, "COMPLETED")
        view = self.w.view(p.id)
        cats = {f["category"] for f in view["findings"]}
        self.assertEqual(cats, {c.value for c in Category})
        blockers = [f for f in view["findings"] if f["category"] == Category.BLOCKER]
        self.assertIn("随机", blockers[0]["explanation"])
        self.assertTrue(any(o["state"] == "NOT_LOCATED" for o in view["observations"]))

    def test_resource_evidence_missing_never_invents_efficiency(self):
        self.w.patch(self.p.id, self.p.revision, {"demo_question": "efficiency"})
        self.run_analysis()
        view = self.w.view(self.p.id)
        self.assertNotIn(Category.BLOCKER, {f["category"] for f in view["findings"]})
        unresolved = [f for f in view["findings"] if f["category"] == Category.UNRESOLVED]
        self.assertTrue(any("无法计算" in f["explanation"] for f in unresolved))
        resources = [o for o in view["observations"] if o["dimension"] == "资源 / 预算"]
        self.assertEqual(sum(o["state"] == "NOT_LOCATED" for o in resources), 2)

    def test_blank_scanned_pdf_is_technical_state_not_scientific_finding(self):
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        stream = io.BytesIO()
        writer.write(stream)
        source = parse_pdf(stream.getvalue(), "scan.pdf")
        self.assertEqual(source.parse_status, "NO_TEXT")
        with patch("src.comparison_workspace.pdf.sources.PdfReader") as reader:
            page = Mock()
            page.extract_text.side_effect = RuntimeError("test parser failed")
            reader.return_value.is_encrypted = False
            reader.return_value.pages = [page]
            failed = parse_pdf(b"%PDF-test", "failure.pdf")
        self.assertEqual(failed.parse_status, "EXTRACTION_FAILED")
        self.assertTrue(failed.pages[0].error)
        self.repo.mutate(self.p.id, self.p.revision,
                         lambda p: setattr(p.papers[0].source, "parse_status", "NO_TEXT"))
        p = self.repo.get(self.p.id)
        with self.assertRaisesRegex(WorkspaceError, "技术限制"):
            self.w.start_run(p.id, p.revision, "analysis", "demo")
        self.assertEqual(self.repo.get_run(self.run.id).output, self.run.output)

    def test_correction_is_append_only_original_and_chain_retained(self):
        obs = self.p.observations[0]
        original = obs.model_dump(mode="json")
        p = self.w.correct(self.p.id, self.p.revision, "observation", obs.id,
                           {"value": "修订一"}, "从原文核对", obs.evidence_ids)
        p = self.w.correct(p.id, p.revision, "observation", obs.id,
                           {"value": "修订二"}, "进一步说明", obs.evidence_ids)
        self.assertEqual(self.repo.get(p.id).observations[0].model_dump(mode="json"), original)
        self.assertEqual(len(p.corrections), 2)
        self.assertEqual(p.corrections[1].before["value"], "修订一")
        self.assertEqual(self.w.view(p.id)["observations"][0]["value"], "修订二")
        self.assertEqual(self.repo.get_run(self.run.id).output, self.run.output)
        self.assertTrue(self.w.view(p.id)["analysis_stale"])
        self.run_analysis()
        self.assertEqual(self.w.view(p.id)["observations"][0]["value"], "修订二")

    def test_result_and_identity_corrections_preserve_originals(self):
        r = self.a.results[0]
        p = self.w.correct(self.p.id, self.p.revision, "result", r.id,
                           {"title": "用户选定主实验"}, "核对实验身份", r.evidence_ids)
        p = self.w.correct(p.id, p.revision, "identity", self.a.id,
                           {"title": "修订的论文标题"}, "核对标题", [])
        view = self.w.view(p.id)
        self.assertEqual(view["papers"][0]["results"][0]["title"], "用户选定主实验")
        self.assertEqual(view["papers"][0]["identity"]["title"]["source"], "user-correction")
        self.assertEqual(self.repo.get(p.id).papers[0].results[0].title, r.title)

    def test_finding_correction_keeps_original_run_output(self):
        f = self.run.output["findings"][0]
        p = self.w.correct(self.p.id, self.p.revision, "finding", f["id"],
                           {"explanation": "用户复核后的解释"}, "细化解释", f["evidence_ids"])
        effective = next(x for x in self.w.view(p.id)["findings"] if x["id"] == f["id"])
        self.assertEqual(effective["explanation"], "用户复核后的解释")
        self.assertEqual(self.repo.get_run(self.run.id).output["findings"][0], f)

    def test_revision_conflict_rolls_back_without_partial_correction(self):
        self.w.patch(self.p.id, self.p.revision, {"title": "更新项目"})
        with self.assertRaises(WorkspaceError) as context:
            self.w.correct(self.p.id, self.p.revision, "observation", self.p.observations[0].id,
                           {"value": "wrong revision"}, "stale", [])
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(self.repo.get(self.p.id).corrections, [])

    def test_stale_background_run_never_replaces_current_project(self):
        entered, release = threading.Event(), threading.Event()
        service = self.w
        class SlowProvider:
            def analyze_comparison(self, snapshot, active, corrections):
                entered.set()
                if not release.wait(5):
                    raise AssertionError("test release timeout")
                return service.providers["demo"].analyze_comparison(snapshot, active, corrections)
        run = self.w.start_run(self.p.id, self.p.revision, "analysis", "import", provider=SlowProvider())
        self.assertTrue(entered.wait(5))
        try:
            p = self.w.patch(self.p.id, self.p.revision, {"question": "changed while running"})
        finally:
            release.set()
        finished = wait_run(self.w, run)
        self.assertEqual(finished.status, "STALE")
        self.assertTrue(finished.output)
        self.assertEqual(self.repo.get(p.id).current_analysis_run_id, self.run.id)
        self.assertEqual(self.repo.get(p.id).question, "changed while running")

    def test_reopen_and_interrupted_jobs_survive_restart(self):
        self.w.close()
        p = self.repo.get(self.p.id)
        run = Run(project_id=p.id, input_revision=p.revision, input_snapshot=p.model_dump(mode="json"),
                  stage="analysis", mode=Mode.MANUAL, provider="Manual")
        self.repo.add_run(run)
        reopened = Workspace(Repository(self.repo.data_dir))
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.view(p.id)["papers"][0]["source"]["sha256"], self.a.source.sha256)
        self.assertEqual(reopened.repo.get_run(run.id).status, "INTERRUPTED")
        self.assertEqual(reopened.repo.get_run(self.run.id).status, "COMPLETED")

    def test_manual_pdf_workflow_works_without_api(self):
        p = self.w.create("手工项目", "哪个方法报告更高数字？")
        for letter in ("A", "B"):
            p = self.w.upload(p.id, p.revision, pdf_path(letter).read_bytes(), f"论文{letter}.pdf")
            paper = p.papers[-1]
            p = self.w.add_result(p.id, p.revision, paper.id,
                                {"title": "主实验", "experiment_identity": f"{letter} primary",
                                 "description": "手工从论文整理"})
            paper = p.papers[-1]
            p = self.w.add_observation(p.id, p.revision,
                {"result_id": paper.active_target_result_id, "dimension": "报告结果",
                 "value": "用户报告数字", "state": "PRESENT"})
        with self.assertRaises(ProviderFailure):
            self.w.start_run(p.id, p.revision, "analysis", "demo")
        run = wait_run(self.w, self.w.start_run(p.id, p.revision, "analysis", "manual"))
        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(run.output["findings"], [])
        self.assertEqual(len(self.repo.get(p.id).observations), 2)
        self.assertIn("manual", json.dumps(portable(self.w.view(p.id))))

    def test_manual_save_retains_existing_proposals_without_promoting_them(self):
        before = self.w.view(self.p.id)
        run = self.run_analysis("manual")
        after = self.w.view(self.p.id)
        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(before["observations"], after["observations"])
        self.assertEqual(before["findings"], after["findings"])
        self.assertEqual(self.repo.get(self.p.id).current_analysis_run_id, self.run.id)
        self.assertEqual(self.repo.get_run(self.run.id).output, self.run.output)

    def test_import_verifies_question_revision_sources_and_results(self):
        valid = self.import_document()
        provider = PrecomputedImportProvider(valid)
        provider.validate_identity(self.w.snapshot(self.p))
        for key in ("project_id", "question", "scope", "input_revision", "sources",
                    "active_target_result_ids", "schema_version"):
            bad = copy.deepcopy(valid)
            if key == "sources":
                bad[key][self.a.id]["sha256"] = "0" * 64
            elif key == "active_target_result_ids":
                bad[key][self.a.id] = self.a.results[1].id
            elif key == "input_revision":
                bad[key] += 1
            else:
                bad[key] = "mismatch"
            with self.subTest(key=key), self.assertRaises(WorkspaceError):
                PrecomputedImportProvider(bad).validate_identity(self.w.snapshot(self.p))
        run = self.run_analysis("import", provider)
        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(run.mode, Mode.IMPORT)

    def test_import_foreign_evidence_fails_and_does_not_corrupt_state(self):
        document = self.import_document()
        document["analysis"]["observations"] = [
            {"result_id": self.a.active_target_result_id, "dimension": "x", "value": "x", "state": "PRESENT",
             "evidence": [self.evidence(self.b, 1, "Evaluation split: temporal split.").model_dump()]}]
        p_before = self.repo.get(self.p.id).model_dump()
        run = self.run_analysis("import", PrecomputedImportProvider(document))
        self.assertEqual(run.status, "FAILED")
        self.assertEqual(self.repo.get(self.p.id).model_dump(), p_before)

    def test_invalid_import_locator_is_unresolved_and_reviewable(self):
        document = self.import_document()
        document["analysis"]["findings"] = [
            FindingCandidate(category=Category.BLOCKER, affected_result_ids=[self.a.active_target_result_id],
                scope=self.p.question, explanation="provider proposal",
                evidence=[self.evidence(quote="fabricated quote")]).model_dump(mode="json")]
        run = self.run_analysis("import", PrecomputedImportProvider(document))
        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(run.output["findings"][0]["category"], Category.UNRESOLVED)
        self.assertEqual(run.output["evidence"][0]["locator_status"], "INVALID")

    def test_malformed_output_and_provider_failure_are_not_findings(self):
        class Broken:
            def analyze_comparison(self, *args):
                return ProviderResult(SimpleNamespace(model_dump=lambda: {"observations": "invalid"}))
        p_before = self.repo.get(self.p.id).model_dump()
        run = self.run_analysis("import", Broken())
        self.assertEqual(run.status, "FAILED")
        self.assertEqual(self.repo.get(self.p.id).model_dump(), p_before)
        self.assertIsNone(run.output)
        class Timeout:
            def analyze_comparison(self, *args):
                raise ProviderFailure("mock timeout; no retry")
        run = self.run_analysis("import", Timeout())
        self.assertEqual(run.status, "FAILED")
        self.assertIsNone(run.output)
        self.assertEqual(self.repo.get(self.p.id).model_dump(), p_before)

    def test_exports_keep_identity_stale_corrections_and_all_provenance(self):
        obs = self.p.observations[0]
        self.w.correct(self.p.id, self.p.revision, "observation", obs.id,
                       {"value": "revised"}, "reviewed", obs.evidence_ids)
        view = self.w.view(self.p.id)
        outputs = [json.dumps(portable(view)), markdown(view), csv_report(view)]
        for output in outputs:
            self.assertIn(self.a.source.sha256, output)
            self.assertIn(self.a.active_target_result_id, output)
            self.assertIn(self.run.id, output)
            self.assertIn("revised", output)
            self.assertIn("STALE", output)
            self.assertIn("demo", output)
            self.assertIn("manual", output)
            self.assertNotIn(str(self.repo.data_dir), output)
        rows = list(csv.DictReader(io.StringIO(outputs[-1])))
        self.assertTrue(any(r["record_type"] == "corrections" for r in rows))

    def test_exports_redact_private_paths_secrets_and_csv_formulas(self):
        view = self.w.view(self.p.id)
        private = str(Path(self.temp.name) / "private.pdf")
        # Constructed test placeholders are never real credentials.
        key = "sk-" + "dummy-test-key-" * 4
        view["scope"] = private + " " + key
        view["title"] = "=SUM(1,2)"
        if os.name != "nt":
            view["scope"] = "/" + "home" + "/" + "test-person/private.pdf " + key
        for output in (json.dumps(portable(view)), markdown(view), csv_report(view)):
            self.assertNotIn(key, output)
            self.assertNotIn(view["scope"].split(" ")[0], output)
            self.assertIn("[REDACTED]", output)
        project_row = next(csv.DictReader(io.StringIO(csv_report(view))))
        self.assertEqual(project_row["value"], "")
        self.assertTrue(portable(view)["export_redactions"])

    def test_http_scoping_revision_202_exports_and_no_arbitrary_paths(self):
        app = create_app(workspace=self.w)
        with TestClient(app) as client:
            self.assertFalse(client.get("/api/capabilities").json()["api_enabled"])
            self.assertEqual(client.patch(f"/api/projects/{self.p.id}",
                json={"title": "stale", "expected_revision": 999}).status_code, 409)
            other = self.w.create("另一项目", "另一个问题")
            self.assertEqual(client.get(f"/api/projects/{other.id}/papers/{self.a.id}/source").status_code, 404)
            self.assertEqual(client.get(f"/api/projects/{self.p.id}/papers/{self.a.id}/pages/999").status_code, 404)
            self.assertEqual(client.post(f"/api/projects/{self.p.id}/papers", data={"expected_revision": 0,
                "path": "not-a-path"}).status_code, 422)
            run = client.post(f"/api/projects/{self.p.id}/analyses",
                             json={"mode": "manual", "expected_revision": self.p.revision})
            self.assertEqual(run.status_code, 202)
            wait_run(self.w, self.repo.get_run(run.json()["run_id"]))
            for extension in ("markdown", "json", "csv"):
                r = client.get(f"/api/projects/{self.p.id}/exports/{extension}")
                self.assertEqual(r.status_code, 200)
                self.assertIn("attachment", r.headers["content-disposition"])
            self.assertEqual(client.post("/api/projects",
                headers={"origin": "https://untrusted.example"},
                json={"title": "x", "question": "x"}).status_code, 403)

    def test_http_real_upload_and_import_contract(self):
        with TestClient(create_app(workspace=self.w)) as client:
            p = client.post("/api/projects", json={"title": "upload test", "question": "numbers"}).json()
            r = client.post(f"/api/projects/{p['id']}/papers", data={"expected_revision": p["revision"]},
                           files={"file": ("论文🪐.pdf", self.raw, "application/pdf")})
            self.assertEqual(r.status_code, 201)
            self.assertEqual(r.json()["papers"][0]["source"]["original_filename"], "论文🪐.pdf")
            template = client.get(f"/api/projects/{self.p.id}/import-template").json()
            r = client.post(f"/api/projects/{self.p.id}/imports",
                            json={"expected_revision": self.p.revision, "document": template})
            self.assertEqual(r.status_code, 202)
            self.assertEqual(wait_run(self.w, self.repo.get_run(r.json()["run_id"])).status, "COMPLETED")

    def test_no_key_and_offline_provider_http_never_requests(self):
        mock = Mock()
        self.w.providers["api"] = OpenAIProvider(explicit_enabled=True, model="mock-model",
                                                hard_offline=False, client=mock)
        with TestClient(create_app(workspace=self.w)) as client:
            r = client.post(f"/api/projects/{self.p.id}/analyses",
                            json={"expected_revision": self.p.revision, "mode": "api"})
            self.assertEqual(r.status_code, 422)
        mock.responses.parse.assert_not_called()

    def test_declared_input_dependency_closure(self):
        isolated = Path(self.temp.name) / "isolated"
        isolated.mkdir()
        root = Path(__file__).resolve().parents[2]
        (isolated / "src").mkdir()
        (isolated / "app").mkdir()
        for relative in ("src/__init__.py", "src/utils.py", "app/__init__.py", "app/comparison_workspace_api.py"):
            shutil.copy2(root / relative, isolated / relative)
        shutil.copytree(root / "src/comparison_workspace", isolated / "src/comparison_workspace",
                        ignore=shutil.ignore_patterns("__pycache__"))
        script = ("from pathlib import Path; from app.comparison_workspace_api import create_app; "
                  "from src.comparison_workspace.storage.repository import Repository; "
                  "from src.comparison_workspace.services.workspace import Workspace; "
                  "w=Workspace(Repository(Path('local-data'))); p,r=w.seed_demo(); w.close(); "
                  "assert len(w.view(p.id)['observations'])==21; print('closure ok')")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(isolated)
        result = subprocess.run([sys.executable, "-c", script], cwd=isolated, env=env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("closure ok", result.stdout)


class OpenAIAdapterTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {"id": "project", "revision": 0, "question": "question", "scope": "",
                         "papers": [], "observations": [], "evidence": []}
        self.client = Mock()
        usage = SimpleNamespace(model_dump=lambda **kw: {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30})
        self.client.responses.parse.return_value = SimpleNamespace(model="actual-model-snapshot",
            _request_id="req_mock", usage=usage, status="completed",
            output_parsed=AnalysisOutput(observations=[], findings=[]))
        self.env = patch.dict(os.environ, {"DISABLE_LIVE_API": "false"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.provider = OpenAIProvider(explicit_enabled=True, api_key="dummy-test-placeholder",
                                       model="requested-model", hard_offline=False, client=self.client)

    def test_explicit_configuration_and_hard_offline(self):
        for provider in (OpenAIProvider(), OpenAIProvider(api_key="dummy", model="mock", hard_offline=False),
                         OpenAIProvider(explicit_enabled=True, model="mock", hard_offline=False),
                         OpenAIProvider(explicit_enabled=True, api_key="dummy", hard_offline=True)):
            with self.subTest(provider=type(provider).__name__), self.assertRaises(ProviderFailure):
                provider.analyze_comparison(self.snapshot, [], [])
        with patch.dict(os.environ, {"DISABLE_LIVE_API": "true"}):
            with self.assertRaises(ProviderFailure):
                self.provider.analyze_comparison(self.snapshot, [], [])
        self.client.responses.parse.assert_not_called()

    def test_structured_output_metadata_store_false_and_no_secret_payload(self):
        result = self.provider.analyze_comparison(self.snapshot, [], [])
        kwargs = self.client.responses.parse.call_args.kwargs
        self.assertFalse(kwargs["store"])
        self.assertEqual(kwargs["text_format"], AnalysisOutput)
        self.assertEqual(result.model, "actual-model-snapshot")
        self.assertEqual(result.request_id, "req_mock")
        self.assertEqual(result.token_usage["total_tokens"], 30)
        self.assertNotIn("dummy-test-placeholder", kwargs["input"])
        self.client.responses.parse.assert_called_once()

    def test_sdk_is_constructed_with_zero_retries_and_timeout(self):
        with patch("openai.OpenAI", return_value=self.client) as constructor:
            provider = OpenAIProvider(explicit_enabled=True, api_key="dummy-test-placeholder",
                                       model="mock-model", hard_offline=False)
            provider.analyze_comparison(self.snapshot, [], [])
        self.assertEqual(constructor.call_args.kwargs["max_retries"], 0)
        self.assertEqual(constructor.call_args.kwargs["timeout"], 120.0)

    def test_timeout_refusal_malformed_output_never_retries(self):
        from openai import APITimeoutError
        cases = ["timeout", "refusal", "malformed", "incomplete"]
        for case in cases:
            with self.subTest(case=case):
                client = Mock()
                response = copy.copy(self.client.responses.parse.return_value)
                if case == "timeout":
                    client.responses.parse.side_effect = APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
                else:
                    if case == "refusal":
                        response.output_parsed = None
                    if case == "malformed":
                        response.output_parsed = {"observations": "invalid", "findings": []}
                    if case == "incomplete":
                        response.status = "incomplete"
                    client.responses.parse.return_value = response
                provider = OpenAIProvider(explicit_enabled=True, api_key="dummy-test-placeholder",
                                           model="mock-model", hard_offline=False, client=client)
                with self.assertRaises(ProviderFailure):
                    provider.analyze_comparison(self.snapshot, [], [])
                client.responses.parse.assert_called_once()

    def test_oversize_prompt_is_rejected_before_request_without_truncation(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["scope"] = "x" * 600001
        with self.assertRaisesRegex(ProviderFailure, "未截断"):
            self.provider.analyze_comparison(snapshot, [], [])
        self.client.responses.parse.assert_not_called()


if __name__ == "__main__":
    unittest.main()
