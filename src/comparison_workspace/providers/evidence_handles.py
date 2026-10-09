"""Request-local page references; paper/source identities are resolved by the host."""
from copy import deepcopy
from hashlib import sha256

from pydantic import Field

from ..domain.models import (
    AnalysisOutput, Category, ConditionState, ExtractionOutput, Record,
    ValidationDiagnostic, new_id,
)
from .base import ProviderFailure


class EvidenceReference(Record):
    evidence_handle: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=10000)


class ReferencedResult(Record):
    paper_id: str
    title: str
    description: str
    experiment_identity: str
    evidence: list[EvidenceReference]


class ReferencedObservation(Record):
    result_id: str
    dimension: str
    value: str
    state: ConditionState
    evidence: list[EvidenceReference]


class ReferencedFinding(Record):
    category: Category
    affected_result_ids: list[str]
    scope: str
    explanation: str
    evidence: list[EvidenceReference]


class APIExtractionOutput(Record):
    results: list[ReferencedResult]


class APIAnalysisOutput(Record):
    observations: list[ReferencedObservation]
    findings: list[ReferencedFinding]


class EvidenceHandles:
    def __init__(self, papers):
        self.papers = deepcopy(papers)
        self._identities = {}
        paper_ids, source_ids = set(), set()
        for paper in self.papers:
            source = paper["source"]
            if paper["id"] in paper_ids or source["id"] in source_ids:
                raise ProviderFailure("输入论文或源身份重复；未发送。")
            paper_ids.add(paper["id"])
            source_ids.add(source["id"])
            if source["page_count"] != len(source["pages"]):
                raise ProviderFailure("输入源页面不完整；未发送。")
            for index, page in enumerate(source["pages"]):
                if (page["page_index"] != index or
                        sha256(page["text"].encode("utf-8")).hexdigest() != page["text_sha256"]):
                    raise ProviderFailure("输入源页面身份或文本哈希不匹配；未发送。")
                handle = new_id("page")
                page["evidence_handle"] = handle
                self._identities[handle] = {
                    "paper_id": paper["id"], "source_snapshot_id": source["id"], "page_index": index,
                }

    def sources(self):
        # Export the exact lookup used by the accepted proposal, without duplicating page text.
        return deepcopy(self._identities)

    def resolve(self, output):
        """Lookup only: never infer a source from a quote, title, ID string or similarity."""
        raw = output.model_dump(mode="json")
        groups = ("results",) if isinstance(output, APIExtractionOutput) else ("observations", "findings")
        for group in groups:
            for index, candidate in enumerate(raw[group]):
                seen = set()
                for offset, reference in enumerate(candidate["evidence"]):
                    handle = reference["evidence_handle"]
                    key = (handle, reference["quote"])
                    if handle not in self._identities or key in seen:
                        # No arbitrary model values or source text in diagnostics.
                        raise ProviderFailure(
                            "证据 handle 未在本次输入中声明或证据引用在同一候选中重复；未接受输出。",
                            validation_diagnostic=ValidationDiagnostic(
                                field_path=f"$.{group}[{index}].evidence[{offset}].evidence_handle",
                                rule="evidence_handle_identity"))
                    seen.add(key)
                    candidate["evidence"][offset] = {**self._identities[handle], "quote": reference["quote"]}
        schema = ExtractionOutput if isinstance(output, APIExtractionOutput) else AnalysisOutput
        return schema.model_validate(raw)
