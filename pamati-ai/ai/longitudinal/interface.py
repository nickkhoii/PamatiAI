from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class TrackingConfig:
    baseline_days: int = 28
    minimum_baseline_interactions: int = 8
    minimum_baseline_days: int = 4
    trajectory_days: int = 7
    minimum_trajectory_days: int = 3
    change_threshold: float = .25
    persistence_days: int = 3


@dataclass(frozen=True)
class Observation:
    id: str
    session_id: str
    timestamp: datetime
    score: float
    confidence: float | None = None
    uncertainty: dict | None = None


class TrackingAlgorithm(Protocol):
    identifier: str
    version: str

    def summarize(self, observations: tuple[Observation, ...], start: datetime,
                  end: datetime, config: TrackingConfig, *, sessions: tuple = ()) -> dict: ...
