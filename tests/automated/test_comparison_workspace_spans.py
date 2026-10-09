"""Source-span v0: deterministic text binding, strict guards, no science certification."""
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from src.comparison_workspace.domain.models import (
    AnalysisOutput, EvidenceCandidate, ExtractionOutput, IdentityField, OutputValidationFailure,
    PageText, Paper, Project, Result, Run, SourceSnapshot, WorkspaceError,
)
from src.comparison_workspace.pdf.sources import locate
from src.comparison_workspace.providers.base import ProviderFailure, ProviderResult
from src.comparison_workspace.providers.evidence_handles import APIAnalysisOutput, APIExtractionOutput, EvidenceHandles
from src.comparison_workspace.services.workspace import Workspace
from src.comparison_workspace.storage.repository import Repository


def paper_with_text(texts):
    source = SourceSnapshot(sha256=hashlib.sha256("".join(texts).encode()).hexdigest(),
        original_filename="synthetic-review-fixture.pdf", parser="synthetic-fixture-not-research-evidence",
        page_count=len(texts), parse_status="TEXT_EXTRACTED",
        pages=[PageText(page_index=i, text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest())
               for i, text in enumerate(texts)])
    paper = Paper(identity={"title": IdentityField(value="SYNTHETIC NOT RESEARCH EVIDENCE", source="synthetic-fixture")}, source=source)
    result = Result(paper_id=paper.id, title="External comparison", experiment_identity="synthetic-target")
    paper.results = [result]
    paper.active_target_result_id = result.id
    return paper


def extraction(paper_id, handles):
    return APIExtractionOutput(results=[dict(paper_id=paper_id, title="Synthetic result", description="review required",
        experiment_identity="synthetic-target", evidence=[{"evidence_handle": h} for h in handles])])


class SpanProtocolTests(unittest.TestCase):
    def setUp(self):
        for name in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, name, side_effect=AssertionError("Network forbidden"))
            guard.start()
            self.addCleanup(guard.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Workspace(Repository(Path(temp.name)))
        self.addCleanup(self.workspace.close)

    def validate(self, papers, handles, wire, stage="extraction"):
        project = Project(title="Synthetic review", question="External comparison only", papers=papers)
        run = Run(project_id=project.id, input_revision=project.revision, input_snapshot=project.model_dump(mode="json"),
                  mode="api", stage=stage, provider="offline-mock")
        response = ProviderResult(handles.resolve(wire), provider_output=wire.model_dump(mode="json"),
                                  evidence_handle_sources=handles.sources(), evidence_protocol=handles.PROTOCOL)
        return self.workspace.validate_output(project, run, response)

    def test_all_identity_hash_offset_quote_fields_match_canonical_source(self):
        text = "Table X: mean [dex], columns A and B\n" + "".join(f"row {i}: {i}.01\n" for i in range(400)) + "Footnote: A minus B.\n"
        paper = paper_with_text([text])
        before = paper.model_dump(mode="json")
        handles = EvidenceHandles([before])
        mapping = handles.sources()
        self.assertGreater(len(mapping), 2)
        for handle, identity in mapping.items():
            with self.subTest(handle=handle):
                output = self.validate([paper], handles, extraction(paper.id, [handle]))
                span = output["evidence"][0]
                for key in ("paper_id", "source_snapshot_id", "page_index", "page_text_sha256", "start", "end"):
                    self.assertEqual(span[key], identity[key])
                self.assertEqual(span["quote"], text[identity["start"]:identity["end"]])
                self.assertEqual(span["locator_status"], "LOCATED")
        self.assertEqual(paper.model_dump(mode="json"), before)

    def test_table_context_keeps_headers_units_and_footnotes_without_input_duplication(self):
        text = "Table Q: Survey A | Survey B; mean [dex]\n" + "".join(f"cell_{i} A={i} B={i+1}\n" for i in range(180)) + "Footnote: same sample, A-B; quality cuts.\n"
        paper = paper_with_text([text])
        handles = EvidenceHandles([paper.model_dump(mode="json")])
        page = handles.papers[0]["source"]["pages"][0]
        self.assertNotIn("text", page)
        self.assertEqual("".join(part["text"] for part in page["evidence_spans"]), text)
        output = self.validate([paper], handles, extraction(paper.id, [page["evidence_handle"]]))
        self.assertEqual(output["evidence"][0]["quote"], text)
        self.assertIn("mean [dex]", output["evidence"][0]["quote"])
        self.assertIn("Footnote:", output["evidence"][0]["quote"])
        for part in page["evidence_spans"]:
            if part["evidence_handle"]:
                self.assertEqual(handles.sources()[part["evidence_handle"]]["context_handle"], page["evidence_handle"])

    def test_repeated_blocks_are_context_only_and_original_ambiguity_rule_stays(self):
        text = "REPEATED\n" * 500
        paper = paper_with_text([text])
        handles = EvidenceHandles([paper.model_dump(mode="json")])
        page = handles.papers[0]["source"]["pages"][0]
        self.assertTrue(all(part["evidence_handle"] is None for part in page["evidence_spans"]))
        candidate = EvidenceCandidate(paper_id=paper.id, source_snapshot_id=paper.source.id, page_index=0, quote="REPEATED")
        self.assertEqual(locate(candidate, paper).locator_status, "INVALID")
        self.assertEqual(len(handles.sources()), 1)  # The complete page is unique, unlike its repeated blocks.

    def test_long_repeated_page_remains_uncitable_without_truncation(self):
        text = "L" * 10001
        paper = paper_with_text([text, "A unique citable page"])
        handles = EvidenceHandles([paper.model_dump(mode="json")])
        page = handles.papers[0]["source"]["pages"][0]
        self.assertNotIn("text", page)
        self.assertEqual("".join(s["text"] for s in page["evidence_spans"]), text)
        self.assertIsNone(page["evidence_handle"])
        self.assertTrue(all(s["evidence_handle"] is None for s in page["evidence_spans"]))
        self.assertTrue(all(identity["page_index"] == 1 for identity in handles.sources().values()))
        with self.assertRaises(ProviderFailure):
            EvidenceHandles([paper_with_text([text]).model_dump(mode="json")])

    def test_quote_limit_boundary_allows_unique_short_blocks_from_long_pages(self):
        for length in (10000, 10001, 30001):
            with self.subTest(length=length):
                text = "".join(f"unique source row {i:05d}\n" for i in range(2000))[:length]
                paper = paper_with_text([text])
                handles = EvidenceHandles([paper.model_dump(mode="json")])
                page = handles.papers[0]["source"]["pages"][0]
                self.assertEqual("".join(s["text"] for s in page["evidence_spans"]), text)
                self.assertEqual(page["evidence_handle"] is None, length > 10000)
                for handle, identity in handles.sources().items():
                    span = self.validate([paper], handles, extraction(paper.id, [handle]))["evidence"][0]
                    self.assertEqual(span["locator_status"], "LOCATED")
                    self.assertEqual(span["quote"], text[identity["start"]:identity["end"]])
                    for key in ("paper_id", "source_snapshot_id", "page_index", "page_text_sha256", "start", "end"):
                        self.assertEqual(span[key], identity[key])
                    self.assertLessEqual(len(span["quote"]), 10000)
                    if length > 10000:
                        self.assertIsNone(identity["context_handle"])
                        self.assertLessEqual(len(span["quote"]), 3000)
                if length > 10000:
                    with self.assertRaises(ValidationError):
                        EvidenceCandidate(paper_id=paper.id, source_snapshot_id=paper.source.id, page_index=0, quote=text)

    def test_long_table_keeps_all_context_but_never_creates_an_oversized_quote(self):
        text = "Table: A minus B; unit [dex]; N is filtered sample.\n" + "".join(
            f"unique table row {i:04d}: A={i}.1 B={i}.2\n" for i in range(500)) + "Footnote: excludes BAD flags in A only.\n"
        paper = paper_with_text([text])
        handles = EvidenceHandles([paper.model_dump(mode="json")])
        page = handles.papers[0]["source"]["pages"][0]
        self.assertGreater(len(text), 10000)
        self.assertIsNone(page["evidence_handle"])
        self.assertEqual("".join(s["text"] for s in page["evidence_spans"]), text)
        output = self.validate([paper], handles, extraction(paper.id, list(handles.sources())))
        self.assertTrue(all(e["locator_status"] == "LOCATED" for e in output["evidence"]))
        self.assertTrue(any("unit [dex]" in e["quote"] for e in output["evidence"]))
        self.assertTrue(any("Footnote:" in e["quote"] for e in output["evidence"]))
        self.assertTrue(all(len(e["quote"]) <= 3000 for e in output["evidence"]))
        self.assertFalse(any("Table:" in e["quote"] and "Footnote:" in e["quote"] for e in output["evidence"]))
        self.assertNotIn("HUMAN_VERIFIED", json.dumps(output))
        # All context is visible, but no composite quote or scientific approval is manufactured.
        with self.assertRaises(ProviderFailure):
            handles.resolve(extraction(paper.id, ["+".join(handles.sources())]))

    def test_long_page_hash_request_and_ownership_guards_remain_strict(self):
        a = paper_with_text(["".join(f"unique line {i:05d}\n" for i in range(1000))])
        b = paper_with_text(["Other paper evidence"])
        papers = [a.model_dump(mode="json"), b.model_dump(mode="json")]
        tampered = copy.deepcopy(papers)
        tampered[0]["source"]["pages"][0]["text"] += "changed"
        with self.assertRaises(ProviderFailure):
            EvidenceHandles(tampered)
        handles = EvidenceHandles(papers)
        handle = next(h for h,v in handles.sources().items() if v["paper_id"] == a.id)
        other_request = next(h for h,v in EvidenceHandles(papers).sources().items() if v["paper_id"] == a.id)
        for refs in ([other_request], [handle+"-forged"], [handle, handle]):
            with self.assertRaises(ProviderFailure):
                handles.resolve(extraction(a.id, refs))
        with self.assertRaises(OutputValidationFailure):
            self.validate([a,b], handles, extraction(b.id, [handle]))
        wire = APIAnalysisOutput(observations=[dict(result_id=b.active_target_result_id, dimension="x", value="x", state="PRESENT",
            evidence=[{"evidence_handle":handle}])], findings=[])
        with self.assertRaises(OutputValidationFailure):
            self.validate([a,b], handles, wire, "analysis")
        wire.observations[0].result_id = "not-active"
        with self.assertRaises(WorkspaceError):
            self.validate([a,b], handles, wire, "analysis")

    def test_line_break_ligature_glyph_and_unicode_offsets_are_not_normalized(self):
        text = "😀 We ﬁnd di ﬀerences; di ffer-\nence. ∆rM{Hsc 0.023˘0.105.\n"
        paper = paper_with_text([text])
        handles = EvidenceHandles([paper.model_dump(mode="json")])
        handle = handles.papers[0]["source"]["pages"][0]["evidence_handle"]
        span = self.validate([paper], handles, extraction(paper.id, [handle]))["evidence"][0]
        self.assertEqual((span["start"], span["end"], span["quote"]), (0, len(text), text))

    def test_no_model_supplied_quote_identity_hash_or_offsets_are_accepted(self):
        paper = paper_with_text(["Unique evidence"])
        handles = EvidenceHandles([paper.model_dump(mode="json")])
        handle = next(iter(handles.sources()))
        for field, value in (("quote", "replacement"), ("start", 0), ("end", 3),
                             ("page_text_sha256", "forged"), ("source_snapshot_id", "forged")):
            raw = extraction(paper.id, [handle]).model_dump(mode="json")
            raw["results"][0]["evidence"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                APIExtractionOutput.model_validate(raw)
        raw = extraction(paper.id, [handle]).model_dump(mode="json")
        raw["results"][0]["evidence"] = []
        with self.assertRaises(ValidationError):
            APIExtractionOutput.model_validate(raw)

    def test_unknown_forged_other_request_and_duplicate_handles_rejected(self):
        paper = paper_with_text(["Unique evidence"])
        handles = EvidenceHandles([paper.model_dump(mode="json")])
        good = next(iter(handles.sources()))
        other = next(iter(EvidenceHandles([paper.model_dump(mode="json")]).sources()))
        for references in (["unknown"], [good+"-forged"], [other], [good, good]):
            with self.subTest(references=references), self.assertRaises(ProviderFailure):
                handles.resolve(extraction(paper.id, references))

    def test_foreign_paper_and_wrong_result_ownership_still_fail(self):
        a, b = paper_with_text(["Unique A"]), paper_with_text(["Unique B"])
        handles = EvidenceHandles([a.model_dump(mode="json"), b.model_dump(mode="json")])
        foreign = handles.papers[1]["source"]["pages"][0]["evidence_handle"]
        with self.assertRaises(OutputValidationFailure):
            self.validate([a, b], handles, extraction(a.id, [foreign]))
        wire = APIAnalysisOutput(observations=[dict(result_id=a.active_target_result_id, dimension="x", value="x", state="PRESENT",
                                evidence=[{"evidence_handle": foreign}])], findings=[])
        with self.assertRaises(OutputValidationFailure):
            self.validate([a, b], handles, wire, "analysis")
        wire.observations[0].result_id = "non-active-result"
        with self.assertRaises(WorkspaceError):
            self.validate([a, b], handles, wire, "analysis")

    def test_exported_source_map_cannot_mutate_trusted_binding(self):
        paper = paper_with_text(["Unique evidence"])
        handles = EvidenceHandles([paper.model_dump(mode="json")])
        handle = next(iter(handles.sources()))
        exported = handles.sources()
        exported[handle]["start"] = 4
        exported[handle]["page_text_sha256"] = "forged"
        self.assertEqual(self.validate([paper], handles, extraction(paper.id, [handle]))["evidence"][0]["start"], 0)

    def test_semantic_negative_fixtures_remain_unconfirmed_even_when_located(self):
        path = Path(__file__).parents[1] / "fixtures/comparison_workspace/span_semantic_review.json"
        fixture = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("NOT_HUMAN_GOLD", fixture["provenance"])
        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                paper = paper_with_text([case["source_text"]])
                handles = EvidenceHandles([paper.model_dump(mode="json")])
                handle = next(iter(handles.sources()))
                wire = APIAnalysisOutput(observations=[], findings=[dict(category="UNRESOLVED",
                    affected_result_ids=[paper.active_target_result_id], scope=case["claim"],
                    explanation="Independent review required: "+case["review_issue"], evidence=[{"evidence_handle":handle}])])
                output = self.validate([paper], handles, wire, "analysis")
                self.assertEqual(output["evidence"][0]["locator_status"], case["source_locator_expected"])
                self.assertEqual(output["findings"][0]["category"], "UNRESOLVED")
                self.assertEqual(output["findings"][0]["provenance"]["mode"], "api")
                self.assertEqual(case["scientific_support_status"], "UNCONFIRMED")
                self.assertFalse(case["human_verified"])
                self.assertNotIn("HUMAN_VERIFIED", json.dumps(output))
                self.assertNotIn("SCIENTIFICALLY_SUPPORTED", json.dumps(output))
                # Even an overconfident model category remains an API proposal, not approved science.
                raw = wire.model_dump(mode="json")
                raw["findings"][0]["category"] = "SUPPORTED_PREREQUISITE"
                proposed = self.validate([paper], handles, APIAnalysisOutput.model_validate(raw), "analysis")
                self.assertEqual(proposed["findings"][0]["provenance"]["mode"], "api")
                self.assertNotIn("human_verified", proposed["findings"][0])
                self.assertEqual(case["scientific_support_status"], "UNCONFIRMED")


@unittest.skipUnless(os.getenv("COMPARISON_SPAN_REPLAY_ROOT"), "Optional external S1-B captures not configured")
class CapturedSpanTests(unittest.TestCase):
    def test_original_s1b_quotes_stay_invalid_and_new_spans_are_separate_host_controls(self):
        root = Path(os.environ["COMPARISON_SPAN_REPLAY_ROOT"])
        files = [p for p in root.rglob("*") if p.is_file()]
        before = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        conn = sqlite3.connect((root/"runtime/workspace.sqlite3").as_uri()+"?mode=ro&immutable=1", uri=True)
        run = Run.model_validate_json(conn.execute("select state from runs").fetchone()[0]); conn.close()
        self.assertEqual(run.id, "run_e5e33714b9f04d128e4ed2bd06de6c51")
        project = Project.model_validate(run.input_snapshot)
        originals = run.output["evidence"]
        by_id = {item["id"]:item for item in originals}
        raw_results = [{**{k:r[k] for k in ("paper_id", "title", "description", "experiment_identity")},
                        "evidence":[{k:by_id[eid][k] for k in ("paper_id", "source_snapshot_id", "page_index", "quote")}
                                    for eid in r["evidence_ids"]]} for r in run.output["results"]]
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Repository(Path(temp)))
            try:
                replay = workspace.validate_output(project, run, ProviderResult(ExtractionOutput(results=raw_results)))
                self.assertEqual([e["locator_status"] for e in replay["evidence"]], ["LOCATED","INVALID","INVALID","INVALID","LOCATED","INVALID"])
                self.assertEqual([e["quote"] for e in replay["evidence"]], [e["quote"] for e in originals])
                self.assertIn("median di fferent", originals[5]["quote"])
                handles = EvidenceHandles(run.input_snapshot["papers"])
                with self.assertRaises(ValidationError):
                    APIExtractionOutput.model_validate(run.output["provider_output"])
                for old in (run.output["provider_output"]["results"][0]["evidence"][2],
                            run.output["provider_output"]["results"][1]["evidence"][2]):
                    with self.assertRaises(ProviderFailure):
                        handles.resolve(extraction(project.papers[0].id, [old["evidence_handle"]]))
                # Every new reference is a host control, not a reconstructed model decision.
                for paper in project.papers:
                    selected = [h for h,v in handles.sources().items() if v["paper_id"]==paper.id and v["start"]==0]
                    control = handles.resolve(extraction(paper.id, selected[:1]))
                    new_run = run.model_copy(update={"id":"host-control-not-historical-run", "provider":"offline-host-control"})
                    result = workspace.validate_output(project, new_run, ProviderResult(control))
                    self.assertTrue(all(e["locator_status"]=="LOCATED" for e in result["evidence"]))
                    self.assertTrue(all(e["provenance"]["run_id"] != run.id for e in result["results"]))
            finally:
                workspace.close()
        self.assertEqual(before, {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})

    @unittest.skipUnless(os.getenv("COMPARISON_SPAN_AUDIT_ROOT"), "Optional source counterparts not configured")
    def test_generic_producer_covers_key_sources_and_preserves_table_context(self):
        root = Path(os.environ["COMPARISON_SPAN_REPLAY_ROOT"])
        audit = Path(os.environ["COMPARISON_SPAN_AUDIT_ROOT"])
        conn = sqlite3.connect((root/"runtime/workspace.sqlite3").as_uri()+"?mode=ro&immutable=1", uri=True)
        run = Run.model_validate_json(conn.execute("select state from runs").fetchone()[0]); conn.close()
        inventory = json.loads((audit/"evidence_inventory.json").read_text(encoding="utf-8"))
        counterparts = json.loads((audit/"source_counterparts.json").read_text(encoding="utf-8"))
        handles = EvidenceHandles(run.input_snapshot["papers"])
        for case, counterpart in zip(inventory, counterparts):
            with self.subTest(case=case["audit_id"]):
                source_page = counterpart["source_page_index"]
                candidates = [(h,v) for h,v in handles.sources().items()
                    if v["paper_id"]==case["paper_id"] and v["page_index"]==source_page
                    and v["start"]<=counterpart["source_start"] and v["end"]>=counterpart["source_end"]]
                self.assertTrue(candidates)
                h, identity = min(candidates, key=lambda pair:pair[1]["end"]-pair[1]["start"])
                resolved = handles.resolve(extraction(case["paper_id"], [h]))
                paper = next(p for p in run.input_snapshot["papers"] if p["id"]==case["paper_id"])
                text = paper["source"]["pages"][source_page]["text"]
                self.assertEqual(resolved.results[0].evidence[0].quote, text[identity["start"]:identity["end"]])
                self.assertIn(counterpart["source_text"], resolved.results[0].evidence[0].quote)
                parent = handles.sources()[identity["context_handle"]]
                self.assertEqual((parent["start"],parent["end"]), (0,len(text)))
                if case["audit_id"] in {"E1","E3","E5"}:
                    context = handles.resolve(extraction(case["paper_id"], [identity["context_handle"]])).results[0].evidence[0].quote
                    self.assertEqual(context, text)  # Caption, headers, units and footnotes remain together.
        # A prospective selection of the old wrong page returns that page's text, never the old footnote quote.
        old = run.output["evidence"][2]
        wrong = next(h for h,v in handles.sources().items() if v["paper_id"]==old["paper_id"]
                     and v["page_index"]==old["page_index"] and v["start"]==0)
        returned = handles.resolve(extraction(old["paper_id"], [wrong])).results[0].evidence[0]
        self.assertEqual(returned.page_index, old["page_index"])
        self.assertNotIn(old["quote"], returned.quote)
        self.assertEqual(old["locator_status"], "INVALID")


@unittest.skipUnless(os.getenv("COMPARISON_SPAN_LIVE_REPLAY_ROOT"), "Optional span v0 live Run not configured")
class LongPageCapturedTests(unittest.TestCase):
    def test_real_calibration_block_is_new_host_control_and_historical_run_stays_unchanged(self):
        root = Path(os.environ["COMPARISON_SPAN_LIVE_REPLAY_ROOT"])
        files = [p for p in root.rglob("*") if p.is_file()]
        before = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        conn = sqlite3.connect((root/"runtime/workspace.sqlite3").as_uri()+"?mode=ro&immutable=1", uri=True)
        raw = conn.execute("select state from runs where id=?", ("run_4dddc42080ea4168a41eb9bad15166bd",)).fetchone()[0]
        conn.close()
        run = Run.model_validate_json(raw)
        project = Project.model_validate(run.input_snapshot)
        paper = next(p for p in project.papers if p.source.original_filename == "2506.07845.pdf")
        text = paper.source.pages[5].text
        self.assertEqual(len(text), 11444)
        self.assertFalse(any(e["paper_id"] == paper.id and e["page_index"] == 5 for e in run.output["evidence"]))
        handles = EvidenceHandles(run.input_snapshot["papers"])
        page = next(p for p in handles.papers if p["id"] == paper.id)["source"]["pages"][5]
        self.assertIsNone(page["evidence_handle"])
        self.assertEqual("".join(s["text"] for s in page["evidence_spans"]), text)
        start = text.index("calibrated to independent measurements")
        end = text.index("Section 4 for details).", start)+len("Section 4 for details).")
        handle = next(h for h,v in handles.sources().items() if v["paper_id"] == paper.id and v["page_index"] == 5
                      and v["start"] <= start and v["end"] >= end)
        control = handles.resolve(extraction(paper.id, [handle]))
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Repository(Path(temp)))
            try:
                observed = run.model_copy(update={"id":"offline-long-page-control", "provider":"offline-host-control"})
                output = workspace.validate_output(project, observed, ProviderResult(control))
                e = output["evidence"][0]
                self.assertEqual(e["locator_status"], "LOCATED")
                self.assertEqual((e["start"],e["end"]), (8812,11444))
                self.assertEqual(e["page_text_sha256"], paper.source.pages[5].text_sha256)
                self.assertIn(text[start:end], e["quote"])
                self.assertIn("Metallicity is\nnot calibrated in DR19", e["quote"])
                self.assertEqual(output["results"][0]["provenance"]["actor"], "offline-host-control")
                originals = {e["id"]:e for e in run.output["evidence"]}
                canonical = ExtractionOutput(results=[{**{k:r[k] for k in ("paper_id","title","description","experiment_identity")},
                    "evidence":[{k:originals[eid][k] for k in ("paper_id","source_snapshot_id","page_index","quote")}
                                for eid in r["evidence_ids"]]} for r in run.output["results"]])
                replay = workspace.validate_output(project, run, ProviderResult(canonical, model=run.provider_reported_model))
                self.assertEqual([e["locator_status"] for e in replay["evidence"]], ["LOCATED"]*5)
                self.assertEqual([e["quote"] for e in replay["evidence"]], [e["quote"] for e in run.output["evidence"]])
                self.assertFalse(any(e["paper_id"] == paper.id and e["page_index"] == 5 for e in replay["evidence"]))
            finally:
                workspace.close()
        self.assertEqual(before, {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


if __name__ == "__main__":
    unittest.main()
