from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Verdict = Literal["PASS", "FAIL"]

_RUBRIC_KEYS: tuple[str, ...] = (
    "relevant",
    "uses_reasonable_fields",
    "claims_supported_by_script",
    "claims_consistent_with_golden_brief",
    "writeup_is_descriptive",
)


@dataclass
class GoldBrief:
    target: str
    relevant_fields: list[str]
    irrelevant_fields: list[str]
    known_patterns: list[str]
    forbidden_claims: list[str]


@dataclass
class TestCase:
    id: str
    dataset: Path
    aim: str
    golden_brief: GoldBrief
    workspace: Path = field(default_factory=Path)  # set by runner; not read from test_cases.json


@dataclass
class SectionArtifacts:
    section_id: str
    title: str
    hypothesis: str
    script: str
    writeup: str


@dataclass
class RubricResult:
    section_id: str
    relevant: Verdict
    uses_reasonable_fields: Verdict
    claims_supported_by_script: Verdict
    claims_consistent_with_golden_brief: Verdict
    writeup_is_descriptive: Verdict
    reasoning: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(getattr(self, k) == "PASS" for k in _RUBRIC_KEYS)


@dataclass
class CaseReport:
    case_name: str
    sections: list[RubricResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.sections) and all(s.passed for s in self.sections)


@dataclass
class SuiteReport:
    cases: list[CaseReport] = field(default_factory=list)

    @property
    def total_cases(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> bool:
        return bool(self.cases) and all(c.passed for c in self.cases)

    @property
    def rubric_summary(self) -> dict[str, dict[str, int]]:
        all_sections = [s for c in self.cases for s in c.sections]
        total = len(all_sections)
        result = {}
        for key in _RUBRIC_KEYS:
            passed = sum(1 for s in all_sections if getattr(s, key) == "PASS")
            result[key] = {
                "pass": passed,
                "total": total,
                "pct": round(passed / total * 100) if total else 0,
            }
        return result
