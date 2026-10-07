"""Versioned product contracts. Located text is evidence of occurrence only."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from src.utils import current_timestamp

SCHEMA_VERSION = "comparison-workspace/v0.1"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Mode(str, Enum):
    MANUAL = "manual"
    DEMO = "demo"
    IMPORT = "import"
    API = "api"


class Provenance(Record):
    mode: Mode = Mode.MANUAL
    actor: str = "local-user"
    model: str | None = None
    run_id: str | None = None
    timestamp: str = Field(default_factory=current_timestamp)


class ConditionState(str, Enum):
    PRESENT = "PRESENT"
    NOT_LOCATED = "NOT_LOCATED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Category(str, Enum):
    SUPPORTED = "SUPPORTED_PREREQUISITE"
    BLOCKER = "BLOCKER"
    UNRESOLVED = "UNRESOLVED"
    ALLOWED = "ALLOWED_HETEROGENEITY"


class PageText(Record):
    page_index: int = Field(ge=0)
    text: str
    text_sha256: str
    error: str | None = None


class SourceSnapshot(Record):
    id: str = Field(default_factory=lambda: new_id("src"))
    sha256: str
    original_filename: str
    parser: str
    page_count: int = Field(ge=1)
    pages: list[PageText]
    parse_status: Literal["TEXT_EXTRACTED", "PARTIAL", "NO_TEXT", "EXTRACTION_FAILED"]
    errors: list[str] = Field(default_factory=list)


class EvidenceSpan(Record):
    id: str = Field(default_factory=lambda: new_id("ev"))
    paper_id: str
    source_snapshot_id: str
    page_index: int
    page_text_sha256: str | None = None
    start: int | None = None
    end: int | None = None
    quote: str = Field(min_length=1, max_length=10000)
    locator_status: Literal["LOCATED", "INVALID"] = "INVALID"
    review_reason: str | None = None


class Result(Record):
    id: str = Field(default_factory=lambda: new_id("res"))
    paper_id: str
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=6000)
    experiment_identity: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)


class Observation(Record):
    id: str = Field(default_factory=lambda: new_id("obs"))
    result_id: str
    dimension: str = Field(min_length=1, max_length=120)
    value: str = Field(default="", max_length=6000)
    state: ConditionState
    evidence_ids: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)

    @model_validator(mode="after")
    def validate_present(self):
        if self.state == ConditionState.PRESENT and not self.value.strip():
            raise ValueError("PRESENT observation needs a value")
        return self


class IdentityField(Record):
    value: str = Field(max_length=1000)
    source: str = Field(max_length=120)


class Paper(Record):
    id: str = Field(default_factory=lambda: new_id("paper"))
    identity: dict[str, IdentityField]
    source: SourceSnapshot
    results: list[Result] = Field(default_factory=list)
    active_target_result_id: str | None = None
    synthetic: bool = False


class Finding(Record):
    id: str = Field(default_factory=lambda: new_id("finding"))
    category: Category
    affected_result_ids: list[str] = Field(min_length=1)
    scope: str = Field(min_length=1, max_length=2000)
    explanation: str = Field(min_length=1, max_length=6000)
    evidence_ids: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)
    # Legacy manual records have no trustworthy current-context binding.
    # Provider findings derive this flag from their immutable Run revision.
    stale: bool = True


class Correction(Record):
    id: str = Field(default_factory=lambda: new_id("correction"))
    target_kind: Literal["result", "observation", "finding", "identity"]
    target_id: str
    before: dict[str, Any]
    after: dict[str, Any]
    rationale: str = Field(min_length=1, max_length=3000)
    evidence_ids: list[str] = Field(default_factory=list)
    operator: str = "local-user"
    timestamp: str = Field(default_factory=current_timestamp)


class Project(Record):
    schema_version: Literal["comparison-workspace/v0.1"] = SCHEMA_VERSION
    id: str = Field(default_factory=lambda: new_id("project"))
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=4000)
    scope: str = Field(default="", max_length=4000)
    revision: int = Field(default=0, ge=0)
    created_at: str = Field(default_factory=current_timestamp)
    updated_at: str = Field(default_factory=current_timestamp)
    papers: list[Paper] = Field(default_factory=list, max_length=10)
    evidence: list[EvidenceSpan] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    manual_findings: list[Finding] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)
    current_analysis_run_id: str | None = None
    demo_question: str | None = None


class EvidenceIdentity(Record):
    # Only identities matched against the immutable project snapshot are retained.
    paper_id: str | None = None
    source_snapshot_id: str | None = None


class ValidationDiagnostic(Record):
    field_path: str
    rule: Literal["structured_output_schema", "evidence_paper_ownership", "evidence_source_identity"]
    expected: list[EvidenceIdentity] = Field(default_factory=list)
    returned: EvidenceIdentity | None = None


class Run(Record):
    id: str = Field(default_factory=lambda: new_id("run"))
    project_id: str
    input_revision: int
    input_snapshot: dict[str, Any]
    mode: Mode
    stage: Literal["extraction", "analysis"]
    provider: str
    # Legacy raw value is kept for read compatibility; never infer either explicit field from it.
    model: str | None = None
    requested_model: str | None = None
    provider_reported_model: str | None = None
    reasoning_effort: str | None = None
    input_modality: Literal["EXTRACTED_TEXT"] | None = None
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "STALE", "FAILED", "INTERRUPTED"] = "QUEUED"
    output: dict[str, Any] | None = None
    started_at: str = Field(default_factory=current_timestamp)
    finished_at: str | None = None
    elapsed_seconds: float | None = None
    request_id: str | None = None
    token_usage: dict[str, Any] | None = None
    provider_status: str | None = None
    incomplete_details: dict[str, str | None] | None = None
    validation_diagnostic: ValidationDiagnostic | None = None
    failure_reason: str | None = None
    cost: str = "unknown"


class EvidenceCandidate(Record):
    paper_id: str
    source_snapshot_id: str
    page_index: int
    quote: str = Field(min_length=1, max_length=10000)


class ResultCandidate(Record):
    paper_id: str
    title: str
    description: str
    experiment_identity: str
    evidence: list[EvidenceCandidate]


class ObservationCandidate(Record):
    result_id: str
    dimension: str
    value: str
    state: ConditionState
    evidence: list[EvidenceCandidate]


class FindingCandidate(Record):
    category: Category
    affected_result_ids: list[str]
    scope: str
    explanation: str
    evidence: list[EvidenceCandidate]


class ExtractionOutput(Record):
    results: list[ResultCandidate]


class AnalysisOutput(Record):
    observations: list[ObservationCandidate]
    findings: list[FindingCandidate]


class ImportEnvelope(Record):
    schema_version: Literal["comparison-workspace/v0.1"]
    project_id: str
    input_revision: int
    question: str
    scope: str
    sources: dict[str, dict[str, str]]
    active_target_result_ids: dict[str, str]
    analysis: AnalysisOutput


class WorkspaceError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


class OutputValidationFailure(WorkspaceError):
    def __init__(self, message: str, diagnostic: ValidationDiagnostic):
        super().__init__(message)
        self.diagnostic = diagnostic
