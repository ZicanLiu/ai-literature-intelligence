"""Offline SDK double: consumes actual adapter requests; never opens a network socket."""
import json
from types import SimpleNamespace

from src.comparison_workspace.domain.models import AnalysisOutput, ExtractionOutput


class MockRawResponse:
    """SDK raw wrapper double, with response metadata available before local parsing."""
    def __init__(self, response):
        self.response = response
        self.headers = {"x-request-id": response._request_id}
        self.http_response = SimpleNamespace(json=self.json)

    def json(self):
        return {"model": self.response.model,
                "usage": self.response.usage.model_dump() if self.response.usage else None}

    def parse(self):
        return self.response


def response_for(**options):
    inputs = json.loads(options["input"])
    papers = inputs["papers"]
    def evidence(paper):
        page = paper["source"]["pages"][0]
        quote = next(line for line in page["text"].splitlines() if line.strip())
        return {"paper_id": paper["id"], "source_snapshot_id": paper["source"]["id"],
                "page_index": page["page_index"], "quote": quote}
    if inputs["stage"] == "extraction":
        output = ExtractionOutput(results=[
            {"paper_id": paper["id"], "title": "Mock main experiment", "description": "Mock extraction",
             "experiment_identity": "mock-primary", "evidence": [evidence(paper)]} for paper in papers])
    else:
        output = AnalysisOutput(observations=[
            {"result_id": paper["active_target_result_id"], "dimension": "原文依据", "value": "Mock text evidence",
             "state": "PRESENT", "evidence": [evidence(paper)]} for paper in papers], findings=[
            {"category": "SUPPORTED_PREREQUISITE", "affected_result_ids": [p["active_target_result_id"] for p in papers],
             "scope": inputs["question"], "explanation": "Mock comparison proposal; review required.",
             "evidence": [evidence(paper) for paper in papers]}])
    return SimpleNamespace(status="completed", model=options["model"]+"-reported", _request_id="req_mock_live",
                           output_parsed=output, output_text=output.model_dump_json(),
                           usage=SimpleNamespace(model_dump=lambda **kw: {"input_tokens": 20, "output_tokens": 10,
                                                                         "total_tokens": 30}))
