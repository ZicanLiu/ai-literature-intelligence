"""Precomputed JSON uses the same candidates and verifies the entire input identity."""
from pydantic import ValidationError

from ..domain.models import ImportEnvelope, WorkspaceError
from .base import ProviderFailure, ProviderResult


class PrecomputedImportProvider:
    def __init__(self, document: dict):
        try:
            self.document = ImportEnvelope.model_validate(document)
        except ValidationError:
            raise WorkspaceError("导入结构无效或 schema_version 不兼容。") from None

    def validate_identity(self, snapshot):
        d = self.document
        sources = {p["id"]: {"source_snapshot_id": p["source"]["id"], "sha256": p["source"]["sha256"]}
                   for p in snapshot["papers"]}
        active = {p["id"]: p["active_target_result_id"] for p in snapshot["papers"]}
        if (d.project_id != snapshot["id"] or d.question != snapshot["question"]
                or d.scope != snapshot["scope"] or d.input_revision != snapshot["revision"]
                or d.sources != sources or d.active_target_result_ids != active):
            raise WorkspaceError("导入的问题、Revision、源 SHA256 / ID 或活动目标与当前项目不匹配。")

    def extract_results(self, input_snapshot):
        raise ProviderFailure("v0.1 导入支持比较分析；结果候选请手工创建或使用已配置 API。")

    def analyze_comparison(self, input_snapshot, active_results, corrections):
        self.validate_identity(input_snapshot)
        return ProviderResult(self.document.analysis)
