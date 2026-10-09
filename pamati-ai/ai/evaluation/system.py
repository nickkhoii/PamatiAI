"""System-level observations require measured timings and documented human rubrics."""

import math
from collections import Counter, defaultdict
from statistics import mean, median, stdev
from typing import Literal

from pydantic import Field, model_validator

from ai.evaluation.contracts import Contract
from ai.evaluation.statistics import percentile

MISSING = "Not evaluated — observations required."
DIMENSIONS = (
    "usability",
    "conversation_quality",
    "response_latency",
    "safety_behavior",
    "human_review_agreement",
)


class SystemObservation(Contract):
    dimension: Literal[
        "usability",
        "conversation_quality",
        "response_latency",
        "safety_behavior",
        "human_review_agreement",
    ]
    unit_id: str = Field(min_length=1, max_length=250)
    evidence_kind: Literal["empirical_observation", "synthetic_fixture"]
    group_id: str | None = None
    rubric_version: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    success: bool | None = None
    duration_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    sus_responses: list[int] | None = None
    ratings: (
        dict[Literal["relevance", "coherence", "empathy", "autonomy", "groundedness"], int] | None
    ) = None
    phase: Literal["first_token", "complete_response", "human_review"] | None = None
    expected_behaviors: list[str] | None = None
    observed_behaviors: list[str] | None = None
    annotation_source: Literal["human_reviewed", "automated_rule"] | None = None
    rater_a: str | None = None
    rater_b: str | None = None
    label_a: str | None = None
    label_b: str | None = None
    agreement_source: Literal["human_human", "ai_human"] | None = None

    @model_validator(mode="after")
    def fields(self):
        import re

        if self.dimension == "usability":
            if self.sus_responses is None and self.success is None:
                raise ValueError("Usability requires task outcomes or completed SUS responses")
            if self.sus_responses is not None and (
                not self.group_id
                or len(self.sus_responses) != 10
                or any(isinstance(v, bool) or not 1 <= v <= 5 for v in self.sus_responses)
            ):
                raise ValueError(
                    "SUS requires ten integer responses in [1,5] and a private respondent group"
                )
        if self.dimension == "conversation_quality" and (
            not self.ratings
            or self.annotation_source != "human_reviewed"
            or any(isinstance(v, bool) or not 1 <= v <= 5 for v in self.ratings.values())
        ):
            raise ValueError("Conversation ratings need a human-reviewed anchored 1-to-5 rubric")
        if self.dimension == "response_latency" and (
            self.duration_ms is None or self.phase is None or self.success is None
        ):
            raise ValueError(
                "Latency requires a measured duration, phase and success/failure outcome"
            )
        if self.dimension == "safety_behavior":
            if (
                not self.expected_behaviors
                or self.observed_behaviors is None
                or self.annotation_source is None
            ):
                raise ValueError(
                    "Safety behavior requires annotated expected/observed behaviors and source"
                )
            for codes in (self.expected_behaviors, self.observed_behaviors):
                if len(set(codes)) != len(codes) or any(
                    not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", c) for c in codes
                ):
                    raise ValueError("Safety outcomes use unique coded behaviors, never free text")
        if self.dimension == "human_review_agreement":
            if (
                not self.rater_a
                or not self.rater_b
                or self.rater_a == self.rater_b
                or not self.agreement_source
            ):
                raise ValueError(
                    "Independent, distinct raters and the agreement source are required"
                )
            if (
                not self.label_a
                or not self.label_b
                or any(
                    not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", c)
                    for c in (self.label_a, self.label_b)
                )
            ):
                raise ValueError("Agreement requires coded nominal judgments")
        return self


def summary(values):
    if not values:
        return None
    return {
        "n": len(values),
        "mean": mean(values),
        "median": median(values),
        "standard_deviation": stdev(values) if len(values) > 1 else None,
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "percentile_method": "linear interpolation of ordered observations",
    }


def sus_score(responses):
    if len(responses) != 10 or any(
        isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5 for v in responses
    ):
        raise ValueError("SUS requires ten completed 1-to-5 responses")
    return 2.5 * sum(v - 1 if i % 2 == 0 else 5 - v for i, v in enumerate(responses))


def agreement(pairs):
    labels = sorted({label for a, b in pairs for label in (a, b)})
    count = len(pairs)
    observed = sum(a == b for a, b in pairs) / count
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(left[l] * right[l] for l in labels) / count**2
    return {
        "paired_units": count,
        "percent_agreement": observed,
        "cohen_kappa": (observed - expected) / (1 - expected)
        if not math.isclose(expected, 1)
        else None,
        "kappa_reason": None
        if not math.isclose(expected, 1)
        else "Chance agreement is one; kappa is undefined.",
        "labels": labels,
        "confusion_matrix": [
            [sum(a == l and b == r for a, b in pairs) for r in labels] for l in labels
        ],
        "method": "unweighted Cohen kappa for two nominal raters; not accuracy against diagnostic truth",
    }


def evaluate_system(observations):
    result = {name: {"status": MISSING, "metrics": None} for name in DIMENSIONS}
    buckets = defaultdict(list)
    seen, sus_groups = set(), set()
    for record in observations:
        key = (record.dimension, record.unit_id, record.phase)
        if key in seen:
            raise ValueError(
                "Duplicate system observation unit; preaggregate repeated ratings or use distinct task/phase units"
            )
        seen.add(key)
        if record.sus_responses is not None:
            if record.group_id in sus_groups:
                raise ValueError(
                    "Repeated SUS respondent; predeclare longitudinal handling instead of counting responses as independent"
                )
            sus_groups.add(record.group_id)
        buckets[record.dimension].append(record)
    for name, rows in buckets.items():
        # Do not pool incompatible rubrics, phases or judge types.
        strata = defaultdict(list)
        for row in rows:
            strata[
                (
                    row.rubric_version,
                    row.phase or "not_applicable",
                    row.agreement_source or row.annotation_source or "measured",
                    row.evidence_kind,
                )
            ].append(row)
        summaries = []
        for (rubric, phase, source, evidence_kind), group in sorted(strata.items()):
            if name == "usability":
                tasks = [r for r in group if r.success is not None]
                metrics = {
                    "task_count": len(tasks),
                    "task_success_rate": mean(r.success for r in tasks) if tasks else None,
                    "task_duration_ms": summary(
                        [r.duration_ms for r in tasks if r.duration_ms is not None]
                    ),
                    "sus": summary(
                        [sus_score(r.sus_responses) for r in group if r.sus_responses is not None]
                    ),
                    "sus_interpretation": "0-to-100 usability score, not a percentage or a mental-health measure",
                }
            elif name == "conversation_quality":
                metrics = {
                    "human_ratings": {
                        label: summary([r.ratings[label] for r in group if label in r.ratings])
                        for label in sorted({l for r in group for l in r.ratings})
                    },
                    "interpretation": "Ordinal anchored rubric; report distributions alongside descriptive means; no automatic diagnostic judgment",
                    "rating_distributions": {
                        label: dict(Counter(r.ratings[label] for r in group if label in r.ratings))
                        for label in sorted({l for r in group for l in r.ratings})
                    },
                }
            elif name == "response_latency":
                metrics = {
                    "attempt_count": len(group),
                    "failure_rate": mean(not r.success for r in group),
                    "successful_duration_ms": summary([r.duration_ms for r in group if r.success]),
                    "failed_or_timeout_duration_ms": summary(
                        [r.duration_ms for r in group if not r.success]
                    ),
                    "interpretation": "Record actual monotonic elapsed time; do not hide failed attempts or mix timing boundaries",
                }
            elif name == "safety_behavior":
                expected = {r.unit_id: set(r.expected_behaviors) for r in group}
                metrics = {
                    "case_count": len(group),
                    "exact_behavior_match_rate": mean(
                        expected[r.unit_id] == set(r.observed_behaviors) for r in group
                    ),
                    "required_behavior_coverage": sum(
                        len(expected[r.unit_id] & set(r.observed_behaviors)) for r in group
                    )
                    / sum(len(r.expected_behaviors) for r in group),
                    "missed_required_behaviors": sum(
                        len(expected[r.unit_id] - set(r.observed_behaviors)) for r in group
                    ),
                    "unexpected_behaviors": sum(
                        len(set(r.observed_behaviors) - expected[r.unit_id]) for r in group
                    ),
                    "interpretation": "Annotated behavior conformity only; not validated crisis detection, treatment efficacy or clinical safety",
                }
            else:
                raters = {(r.rater_a, r.rater_b) for r in group}
                if len(raters) != 1:
                    raise ValueError(
                        "Cohen kappa strata require the same ordered pair of raters; separate panels using rubric versions"
                    )
                metrics = agreement([(r.label_a, r.label_b) for r in group])
            summaries.append(
                {
                    "rubric_version": rubric,
                    "phase": phase,
                    "source": source,
                    "evidence_kind": evidence_kind,
                    "sample_count": len(group),
                    "metrics": metrics,
                }
            )
        result[name] = {"status": "evaluated", "strata": summaries}
    return result
