import re
import unicodedata
from dataclasses import dataclass
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9-]+$")
    category: str = Field(pattern=r"^(self_harm_language|immediate_danger|safety_concern)$")
    priority: str = Field(pattern=r"^(urgent|prompt)$")
    phrases: list[str] = Field(min_length=1, max_length=30)

    @field_validator("phrases")
    @classmethod
    def phrases_valid(cls, values):
        if any(not 4 <= len(value.strip()) <= 160 for value in values):
            raise ValueError("Use bounded literal safety-language phrases")
        return values


DEFAULT_RULES = [
    {"id": "explicit-self-harm", "category": "self_harm_language", "priority": "urgent",
     "phrases": ["i want to kill myself", "i am going to kill myself", "i'm going to kill myself",
                 "i will kill myself", "i want to die", "i might hurt myself", "i will hurt myself",
                 "i am going to hurt myself", "i'm going to hurt myself", "i have taken an overdose",
                 "i intend to end my life", "i want to end my life", "i plan to kill myself",
                 "i am thinking about killing myself", "i'm thinking about killing myself",
                 "i have a plan to hurt myself", "i took an overdose", "i just took an overdose",
                 "my friend wants to kill themselves", "my friend is going to kill himself",
                 "my friend is going to kill herself", "i feel suicidal", "i'm feeling suicidal",
                 "i am feeling suicidal", "i am suicidal", "i have a plan to kill myself",
                 "i attempted suicide", "i tried to kill myself", "i might kill myself", "i want to hurt myself"]},
    {"id": "explicit-danger", "category": "immediate_danger", "priority": "urgent",
     "phrases": ["i am in immediate danger", "someone is attacking me", "i cannot keep myself safe",
                 "i can't keep myself safe", "i am not safe right now", "i'm not safe right now",
                 "i will hurt someone", "i am going to hurt someone"]},
    {"id": "safety-concern", "category": "safety_concern", "priority": "prompt",
     "phrases": ["i do not feel safe", "i don't feel safe"]},
]


class SafetyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(default="1", min_length=1, max_length=50)
    rules: list[Rule] = Field(default_factory=lambda: [Rule(**r) for r in DEFAULT_RULES], min_length=1, max_length=30)

    @field_validator("rules")
    @classmethod
    def distinct_rules(cls, rules):
        if len({rule.id for rule in rules}) != len(rules):
            raise ValueError("Safety rule IDs must be unique")
        return rules

    @property
    def fingerprint(self):
        return sha256(self.model_dump_json().encode()).hexdigest()


@dataclass(frozen=True)
class SafetyCandidate:
    rule_id: str
    reason_category: str
    priority: str
    confidence: float | None = None
    confidence_method: str = "unavailable_literal_rule_not_calibrated"


def normalize(text):
    value = unicodedata.normalize("NFKC", text).casefold().replace("\u2019", "'")
    return " ".join(re.findall(r"[\w']+", value))


class LiteralSafetyAnalyzer:
    version = "literal-safety-analysis-v1"

    def analyze(self, text, policy):
        value = " " + normalize(text) + " "
        # Bounded literal matching avoids user-configured regex execution. Context is not resolved.
        return tuple(SafetyCandidate(rule.id, rule.category, rule.priority)
                     for rule in policy.rules
                     if any(" " + normalize(phrase) + " " in value for phrase in rule.phrases))


def evaluate(candidates, policy):
    """Policy routing is independent of sentiment; only explicitly declared safety categories qualify."""
    permitted = {rule.id: rule for rule in policy.rules}
    result = []
    for candidate in candidates:
        rule = permitted.get(candidate.rule_id)
        if rule and candidate.reason_category == rule.category:
            # Routing priority is set by policy, not a model's diagnostic assertion.
            result.append(SafetyCandidate(rule.id, rule.category, rule.priority))
    return tuple(result)
