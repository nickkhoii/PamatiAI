"""Contracts for future adapters. No inference or automatic model downloads."""
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class AnalysisInput:
    pseudonymous_job_id: str
    consent_receipt_id: str
    modality: Literal["text", "speech", "visual"]
    payload_reference: str


@dataclass(frozen=True)
class AnalysisResult:
    model_revision: str
    preprocessing_revision: str
    labels: dict[str, float]
    abstained: bool
    limitations: tuple[str, ...]


class AnalysisAdapter(Protocol):
    def analyze(self, sample: AnalysisInput) -> AnalysisResult: ...
