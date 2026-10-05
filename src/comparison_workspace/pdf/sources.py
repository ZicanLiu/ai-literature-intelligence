"""Bounded PDF extraction and exact Unicode code-point locators."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pypdf
from pypdf import PdfReader
from ..domain.models import EvidenceCandidate, EvidenceSpan, PageText, Paper, SourceSnapshot, WorkspaceError

MAX_BYTES = 25 * 1024 * 1024
MAX_PAGES = 100


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_pdf(data: bytes, filename: str, *, max_bytes=MAX_BYTES, max_pages=MAX_PAGES) -> SourceSnapshot:
    if len(data) > max_bytes:
        raise WorkspaceError("PDF 超过 25 MiB 限制；未截断。", 413)
    if not data.startswith(b"%PDF-"):
        raise WorkspaceError("文件不是有效 PDF。")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise WorkspaceError("v0.1 不支持加密 PDF，请先提供未加密副本。")
        count = len(reader.pages)
        if count > max_pages:
            raise WorkspaceError("PDF 超过 100 页限制；未截断。", 413)
        if count == 0:
            raise WorkspaceError("PDF 没有页面。")
    except WorkspaceError:
        raise
    except Exception:
        raise WorkspaceError("PDF 损坏或无法读取。") from None
    pages, errors = [], []
    for i, page in enumerate(reader.pages):
        error = None
        try:
            text = page.extract_text() or ""
        except Exception:
            text, error = "", "页面文本提取失败；不能推断论文未报告。"
            errors.append(f"第 {i + 1} 页：{error}")
        pages.append(PageText(page_index=i, text=text, text_sha256=sha256(text.encode("utf-8")), error=error))
    nonempty = sum(bool(p.text.strip()) for p in pages)
    status = "TEXT_EXTRACTED"
    if errors:
        status = "PARTIAL" if nonempty else "EXTRACTION_FAILED"
    elif not nonempty:
        status = "NO_TEXT"
        errors.append("未提取到文本，可能是扫描 PDF；v0.1 未提供 OCR。")
    elif nonempty != count:
        status = "PARTIAL"
        errors.append("部分页面无可提取文本，请阅读原始 PDF。")
    # Only display basename; client paths never become storage paths.
    name = filename.replace("\\", "/").split("/")[-1]
    return SourceSnapshot(sha256=sha256(data), original_filename=name,
                          parser=f"pypdf/{pypdf.__version__}", page_count=count,
                          pages=pages, parse_status=status, errors=errors)


def store_raw(directory: Path, snapshot: SourceSnapshot, data: bytes):
    path = directory / f"{snapshot.id}.pdf"
    with path.open("xb") as handle:
        handle.write(data)
    return path


def locate(candidate: EvidenceCandidate, paper: Paper) -> EvidenceSpan:
    if candidate.paper_id != paper.id or candidate.source_snapshot_id != paper.source.id:
        raise WorkspaceError("证据属于另一论文或源快照。")
    span = EvidenceSpan(paper_id=paper.id, source_snapshot_id=paper.source.id,
                        page_index=candidate.page_index, quote=candidate.quote)
    if not 0 <= candidate.page_index < paper.source.page_count:
        span.review_reason = "页码越界，待复核。"
        return span
    page = paper.source.pages[candidate.page_index]
    span.page_text_sha256 = page.text_sha256
    if page.error or not page.text.strip():
        span.review_reason = "该页文本不可用，不能判定论文未报告。"
        return span
    # Python indexes Unicode code points, including non-BMP characters.
    positions = []
    start = page.text.find(candidate.quote)
    while start >= 0:
        positions.append(start)
        start = page.text.find(candidate.quote, start + 1)
    if not positions:
        span.review_reason = "引文与本页提取文本不匹配，待复核。"
    elif len(positions) > 1:
        span.review_reason = "引文在本页重复，定位有歧义；请扩大引文。"
    else:
        span.start = positions[0]
        span.end = span.start + len(candidate.quote)
        span.locator_status = "LOCATED"
    return span
