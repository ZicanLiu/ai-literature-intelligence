"""Request-local source spans. The host owns quote, identity, hash and offsets."""
from copy import deepcopy
from hashlib import sha256

from pydantic import Field

from ..domain.models import (
    AnalysisOutput, Category, ConditionState, ExtractionOutput, Record,
    ValidationDiagnostic, new_id,
)
from .base import ProviderFailure


class EvidenceReference(Record):
    evidence_handle: str = Field(min_length=1, description=
        "Copy one declared non-null evidence_handle exactly; use each handle at most once per candidate.")


class ReferencedResult(Record):
    paper_id: str
    title: str
    description: str
    experiment_identity: str
    evidence: list[EvidenceReference] = Field(min_length=1)


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
    PROTOCOL = "source-span/v0"
    BLOCK_CHARACTERS = 3000
    MAX_QUOTE_CHARACTERS = 10000

    def __init__(self, papers):
        self.papers = deepcopy(papers)
        self._identities = {}
        self._quotes = {}
        paper_ids, source_ids = set(), set()
        for paper in self.papers:
            source = paper["source"]
            if paper["id"] in paper_ids or source["id"] in source_ids:
                raise ProviderFailure("输入论文或源身份重复；未发送。")
            paper_ids.add(paper["id"])
            source_ids.add(source["id"])
            if source["page_count"] != len(source["pages"]):
                raise ProviderFailure("输入源页面不完整；未发送。")
            citable = False
            for index, page in enumerate(source["pages"]):
                if (page["page_index"] != index or
                        sha256(page["text"].encode("utf-8")).hexdigest() != page["text_sha256"]):
                    raise ProviderFailure("输入源页面身份或文本哈希不匹配；未发送。")
                text = page.pop("text")
                if page.get("error") or not text.strip():
                    page.update(text=text, evidence_handle=None, evidence_spans=[],
                                evidence_unavailable_reason="page_not_citable_within_quote_limit")
                    continue
                context = new_id("span") if len(text) <= self.MAX_QUOTE_CHARACTERS else None
                identity = {
                    "paper_id": paper["id"], "source_snapshot_id": source["id"], "page_index": index,
                    "page_text_sha256": page["text_sha256"],
                }
                if context is not None:
                    self._add(context, identity, text, 0, len(text), context)
                else:
                    # Only the full-page quote is too long; short exact blocks remain eligible.
                    page["evidence_unavailable_reason"] = "whole_page_quote_exceeds_limit"
                spans = []
                start = 0
                while start < len(text):
                    end = min(start + self.BLOCK_CHARACTERS, len(text))
                    if end < len(text):
                        boundary = text.rfind("\n", start, end)
                        if boundary > start:
                            end = boundary + 1
                    quote = text[start:end]
                    handle = None
                    if (not (start == 0 and end == len(text) and context is not None)
                            and quote.strip() and text.find(quote) == start and text.find(quote, start + 1) < 0):
                        # A single-block page is already citable via its full-page handle.
                        # Do not declare that same handle a second time on the text block.
                        handle = new_id("span")
                        self._add(handle, identity, text, start, end, context)
                        citable = True
                    # Non-overlapping blocks preserve every character exactly once in the input.
                    # A repeated block remains visible as context but has no citable handle.
                    spans.append({"evidence_handle": handle, "text": quote})
                    start = end
                page.update(evidence_handle=context, evidence_spans=spans)
                citable = citable or context is not None
            if not citable:
                raise ProviderFailure("该论文没有可在原引文上限内唯一定位的来源 span；未发送。")

    def _add(self, handle, identity, text, start, end, context):
        self._identities[handle] = {**identity, "start": start, "end": end, "context_handle": context}
        self._quotes[handle] = text[start:end]

    def sources(self):
        # The immutable Run snapshot plus these offsets reconstructs every accepted quote.
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
                    if handle not in self._identities or handle in seen:
                        # No arbitrary model values or source text in diagnostics.
                        issue = "UNKNOWN_HANDLE" if handle not in self._identities else "DUPLICATE_HANDLE"
                        raise ProviderFailure(
                            ("证据 handle 未在本次输入中声明；未接受输出。" if issue == "UNKNOWN_HANDLE"
                             else "同一候选重复引用了证据 handle；未接受输出。"),
                            validation_diagnostic=ValidationDiagnostic(
                                field_path=f"$.{group}[{index}].evidence[{offset}].evidence_handle",
                                rule="evidence_handle_identity", handle_issue=issue))
                    seen.add(handle)
                    identity = self._identities[handle]
                    candidate["evidence"][offset] = {
                        **{key: identity[key] for key in ("paper_id", "source_snapshot_id", "page_index")},
                        "quote": self._quotes[handle],
                    }
        schema = ExtractionOutput if isinstance(output, APIExtractionOutput) else AnalysisOutput
        return schema.model_validate(raw)
