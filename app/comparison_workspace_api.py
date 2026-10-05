"""HTTP adapter; reusable product services live in src/comparison_workspace."""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.comparison_workspace.domain.models import EvidenceCandidate, Record, WorkspaceError
from src.comparison_workspace.export.reports import csv_report, markdown, portable
from src.comparison_workspace.pdf.sources import MAX_BYTES
from src.comparison_workspace.providers.base import ProviderFailure
from src.comparison_workspace.services.workspace import Workspace
from src.comparison_workspace.storage.repository import Repository

ROOT = Path(__file__).resolve().parents[1]


class RevisionBody(Record):
    expected_revision: int = Field(ge=0)


class CreateBody(Record):
    expected_revision: Literal[0] = 0
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=4000)
    scope: str = Field(default="", max_length=4000)


class PatchBody(RevisionBody):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    question: str | None = Field(default=None, min_length=1, max_length=4000)
    scope: str | None = Field(default=None, max_length=4000)
    demo_question: Literal["reported", "protocol", "efficiency"] | None = None


class DemoBody(Record):
    expected_revision: Literal[0] = 0
    question_key: Literal["reported", "protocol", "efficiency"] = "reported"


class ResultBody(RevisionBody):
    title: str
    description: str = ""
    experiment_identity: str
    evidence_ids: list[str] = Field(default_factory=list)


class SelectBody(RevisionBody):
    result_id: str | None


class ObservationBody(RevisionBody):
    result_id: str
    dimension: str
    value: str = ""
    state: Literal["PRESENT", "NOT_LOCATED", "AMBIGUOUS", "NOT_APPLICABLE"]
    evidence_ids: list[str] = Field(default_factory=list)


class FindingBody(RevisionBody):
    category: Literal["SUPPORTED_PREREQUISITE", "BLOCKER", "UNRESOLVED", "ALLOWED_HETEROGENEITY"]
    affected_result_ids: list[str]
    scope: str
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceBody(RevisionBody):
    candidate: EvidenceCandidate


class CorrectionBody(RevisionBody):
    target_kind: Literal["result", "observation", "finding", "identity"]
    target_id: str
    after: dict[str, Any]
    rationale: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class RunBody(RevisionBody):
    mode: Literal["demo", "manual", "api"]


class ImportBody(RevisionBody):
    document: dict[str, Any]


def default_data_dir() -> Path:
    configured = os.getenv("COMPARISON_WORKSPACE_DATA_DIR")
    if configured:
        directory = Path(configured).expanduser().resolve()
    elif os.name == "nt":
        directory = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData/Local")) / "SRTP/ComparisonWorkspace"
    else:
        directory = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share")) / "srtp/comparison-workspace"
    return directory


def create_app(data_dir: Path | None = None, *, workspace: Workspace | None = None,
               frontend_dir: Path | None = None) -> FastAPI:
    service = workspace or Workspace(Repository(data_dir or default_data_dir()))
    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()

    app = FastAPI(title="SRTP Scientific Comparison Workspace", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"], www_redirect=False)
    app.state.workspace = service

    @app.middleware("http")
    async def local_headers(request, call_next):
        # Prevent a remote website from submitting multipart writes to the local server.
        origin = request.headers.get("origin")
        if request.method in {"POST", "PATCH", "PUT", "DELETE"} and origin:
            from urllib.parse import urlsplit
            if urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse(status_code=403, content={"detail": "仅允许本地工作台同源写入。"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; worker-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
        return response

    @app.exception_handler(WorkspaceError)
    async def handle_workspace_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(ProviderFailure)
    async def handle_provider_error(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    # Parse validation errors at the domain boundary without printing source content.
    from pydantic import ValidationError
    @app.exception_handler(ValidationError)
    async def handle_contract_error(request, exc):
        return JSONResponse(status_code=422, content={"detail": "字段结构或取值无效，请检查输入。"})

    @app.get("/api/capabilities")
    def capabilities():
        provider = service.providers.get("api")
        enabled = bool(provider and provider.enabled)
        return {"schema_version": "comparison-workspace/v0.1", "offline": not enabled,
                "api_enabled": enabled, "api_model": getattr(provider, "model", None),
                "modes": ["manual", "demo", "import"] + (["api"] if enabled else []),
                "max_pdf_bytes": MAX_BYTES, "max_pdf_pages": 100, "max_papers": 10,
                "pdf_support": "text-extractable; no OCR",
                "notice": "合成演示不是真实研究证据；AI 草稿需人工复核。"}

    @app.get("/api/projects")
    def projects():
        return service.repo.list()

    @app.post("/api/projects", status_code=201)
    def create(body: CreateBody):
        p = service.create(body.title, body.question, body.scope)
        return service.view(p.id)

    @app.post("/api/demo", status_code=201)
    def demo(body: DemoBody):
        p, run = service.seed_demo(body.question_key)
        return {"project_id": p.id, "run_id": run.id}

    @app.get("/api/projects/{project_id}")
    def get(project_id: str):
        return service.view(project_id)

    @app.patch("/api/projects/{project_id}")
    def patch(project_id: str, body: PatchBody):
        service.patch(project_id, body.expected_revision,
                      body.model_dump(exclude={"expected_revision"}, exclude_none=True))
        return service.view(project_id)

    @app.post("/api/projects/{project_id}/papers", status_code=201)
    async def upload(project_id: str, expected_revision: int = Form(...), file: UploadFile = File(...)):
        data = await file.read(MAX_BYTES + 1)
        await file.close()
        service.upload(project_id, expected_revision, data, file.filename or "paper.pdf")
        return service.view(project_id)

    def scoped_paper(project_id, paper_id):
        return service.paper(service.repo.get(project_id), paper_id)

    @app.get("/api/projects/{project_id}/papers/{paper_id}/source")
    def source(project_id: str, paper_id: str):
        paper = scoped_paper(project_id, paper_id)
        return FileResponse(service.repo.sources_dir / f"{paper.source.id}.pdf",
                            media_type="application/pdf",
                            headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"})

    @app.get("/api/projects/{project_id}/papers/{paper_id}/pages/{page_index}")
    def page(project_id: str, paper_id: str, page_index: int):
        paper = scoped_paper(project_id, paper_id)
        if not 0 <= page_index < paper.source.page_count:
            raise WorkspaceError("PDF 页码越界。", 404)
        return paper.source.pages[page_index].model_dump()

    @app.post("/api/projects/{project_id}/papers/{paper_id}/results", status_code=201)
    def result(project_id: str, paper_id: str, body: ResultBody):
        service.add_result(project_id, body.expected_revision, paper_id,
                           body.model_dump(exclude={"expected_revision"}))
        return service.view(project_id)

    @app.patch("/api/projects/{project_id}/papers/{paper_id}/active-result")
    def select(project_id: str, paper_id: str, body: SelectBody):
        service.select(project_id, body.expected_revision, paper_id, body.result_id)
        return service.view(project_id)

    @app.post("/api/projects/{project_id}/evidence", status_code=201)
    def evidence(project_id: str, body: EvidenceBody):
        service.add_evidence(project_id, body.expected_revision, body.candidate)
        return service.view(project_id)

    @app.post("/api/projects/{project_id}/observations", status_code=201)
    def observation(project_id: str, body: ObservationBody):
        service.add_observation(project_id, body.expected_revision,
                                body.model_dump(exclude={"expected_revision"}))
        return service.view(project_id)

    @app.post("/api/projects/{project_id}/findings", status_code=201)
    def finding(project_id: str, body: FindingBody):
        service.add_finding(project_id, body.expected_revision,
                            body.model_dump(exclude={"expected_revision"}))
        return service.view(project_id)

    @app.post("/api/projects/{project_id}/corrections", status_code=201)
    def correction(project_id: str, body: CorrectionBody):
        service.correct(project_id, body.expected_revision, body.target_kind, body.target_id,
                        body.after, body.rationale, body.evidence_ids)
        return service.view(project_id)

    def start(project_id, body, stage):
        run = service.start_run(project_id, body.expected_revision, stage, body.mode)
        return {"run_id": run.id}

    @app.post("/api/projects/{project_id}/extractions", status_code=202)
    def extract(project_id: str, body: RunBody):
        return start(project_id, body, "extraction")

    @app.post("/api/projects/{project_id}/analyses", status_code=202)
    def analyze(project_id: str, body: RunBody):
        return start(project_id, body, "analysis")

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        r = service.repo.get_run(run_id)
        if r.stage == "analysis" and r.status == "COMPLETED" and service.repo.get(r.project_id).revision != r.input_revision:
            r.status = "STALE"
        return r.model_dump(mode="json")

    @app.post("/api/projects/{project_id}/imports", status_code=202)
    def import_analysis(project_id: str, body: ImportBody):
        from src.comparison_workspace.providers.imported import PrecomputedImportProvider
        provider = PrecomputedImportProvider(body.document)
        p = service.repo.get(project_id)
        service.repo.expect(p, body.expected_revision)
        provider.validate_identity(service.snapshot(p))
        run = service.start_run(project_id, body.expected_revision, "analysis", "import", provider=provider)
        return {"run_id": run.id}

    @app.get("/api/projects/{project_id}/import-template")
    def import_template(project_id: str):
        p = service.repo.get(project_id)
        return {"schema_version": p.schema_version, "project_id": p.id, "input_revision": p.revision,
                "question": p.question, "scope": p.scope,
                "sources": {paper.id: {"source_snapshot_id": paper.source.id, "sha256": paper.source.sha256} for paper in p.papers},
                "active_target_result_ids": {paper.id: paper.active_target_result_id for paper in p.papers},
                "analysis": {"observations": [], "findings": []}}

    @app.get("/api/projects/{project_id}/exports/{format}")
    def export(project_id: str, format: Literal["markdown", "json", "csv"]):
        view = service.view(project_id)
        if format == "markdown":
            text, mime, ext = markdown(view), "text/markdown", "md"
        elif format == "csv":
            text, mime, ext = "\ufeff" + csv_report(view), "text/csv", "csv"
        else:
            text, mime, ext = json.dumps(portable(view), ensure_ascii=False, indent=2), "application/json", "json"
        return Response(text, media_type=mime,
                        headers={"Content-Disposition": f'attachment; filename="comparison-report.{ext}"'})

    frontend = frontend_dir or ROOT / "web/comparison-workspace/dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    else:
        @app.get("/")
        def missing_build():
            return JSONResponse(status_code=503, content={"detail": "前端未构建，请运行启动命令以自动构建。"})
    return app
