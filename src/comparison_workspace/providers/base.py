"""Provider protocol carries only explicit immutable inputs."""
from dataclasses import dataclass
from typing import Protocol

from ..domain.models import AnalysisOutput, ExtractionOutput


@dataclass
class ProviderResult:
    output: AnalysisOutput | ExtractionOutput
    model: str | None = None
    request_id: str | None = None
    token_usage: dict | None = None


class Provider(Protocol):
    def extract_results(self, input_snapshot: dict) -> ProviderResult: ...
    def analyze_comparison(self, input_snapshot: dict, active_results: list,
                           corrections: list) -> ProviderResult: ...


class ProviderFailure(Exception):
    """Safe reason and actual response metadata only; model is never a requested fallback."""
    def __init__(self, message, *, model=None, request_id=None, token_usage=None):
        super().__init__(message)
        self.model = model
        self.request_id = request_id
        self.token_usage = token_usage
