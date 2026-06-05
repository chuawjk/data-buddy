"""LLM judge — evaluates one built section against a gold brief.

A single litellm call per section returns binary PASS/FAIL verdicts for
all five rubrics plus a one-line reasoning string per rubric.

Public API:
    judge_section(section, brief) -> RubricResult
"""

from __future__ import annotations

import json
import logging

import litellm

from backend.evals.models import GoldBrief, RubricResult, SectionArtifacts

logger = logging.getLogger(__name__)

_MODEL = "gpt-5.4-mini"

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "string", "enum": ["PASS", "FAIL"]},
        "uses_reasonable_fields": {"type": "string", "enum": ["PASS", "FAIL"]},
        "claims_supported_by_script": {"type": "string", "enum": ["PASS", "FAIL"]},
        "claims_consistent_with_golden_brief": {"type": "string", "enum": ["PASS", "FAIL"]},
        "writeup_is_descriptive": {"type": "string", "enum": ["PASS", "FAIL"]},
        "reasoning": {
            "type": "object",
            "properties": {
                "relevant": {"type": "string"},
                "uses_reasonable_fields": {"type": "string"},
                "claims_supported_by_script": {"type": "string"},
                "claims_consistent_with_golden_brief": {"type": "string"},
                "writeup_is_descriptive": {"type": "string"},
            },
            "required": [
                "relevant",
                "uses_reasonable_fields",
                "claims_supported_by_script",
                "claims_consistent_with_golden_brief",
                "writeup_is_descriptive",
            ],
            "additionalProperties": False,
        },
    },
    "required": [
        "relevant",
        "uses_reasonable_fields",
        "claims_supported_by_script",
        "claims_consistent_with_golden_brief",
        "writeup_is_descriptive",
        "reasoning",
    ],
    "additionalProperties": False,
}


def judge_section(section: SectionArtifacts, brief: GoldBrief) -> RubricResult:
    """Evaluate one section against the gold brief and return a RubricResult.

    Makes a single litellm completion call with structured output.  The model
    is asked to score five binary rubrics and provide a one-line reason for
    each verdict.

    Args:
        section: The built section artifacts (script + writeup + metadata).
        brief: The gold brief for this test case.

    Returns:
        A RubricResult with PASS/FAIL verdicts and per-rubric reasoning.
    """
    prompt = _build_prompt(section, brief)
    logger.info("judge_section: evaluating %s (%s)", section.section_id, section.title)

    response = litellm.completion(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "rubric_result",
                "schema": _RESPONSE_SCHEMA,
                "strict": True,
            },
        },
    )

    content = response.choices[0].message.content  # type: ignore[union-attr]
    if not content:
        raise RuntimeError(f"judge_section: empty response from model for {section.section_id}")
    raw: dict = json.loads(content)
    logger.info(
        "judge_section: %s — %s",
        section.section_id,
        {k: raw[k] for k in _RESPONSE_SCHEMA["required"] if k != "reasoning"},
    )

    return RubricResult(
        section_id=section.section_id,
        relevant=raw["relevant"],
        uses_reasonable_fields=raw["uses_reasonable_fields"],
        claims_supported_by_script=raw["claims_supported_by_script"],
        claims_consistent_with_golden_brief=raw["claims_consistent_with_golden_brief"],
        writeup_is_descriptive=raw["writeup_is_descriptive"],
        reasoning=raw.get("reasoning", {}),
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def _build_prompt(section: SectionArtifacts, brief: GoldBrief) -> str:
    known = "\n".join(f"  - {p}" for p in brief.known_patterns)
    forbidden = "\n".join(f"  - {c}" for c in brief.forbidden_claims)
    relevant = ", ".join(brief.relevant_fields)
    irrelevant = ", ".join(brief.irrelevant_fields)

    return f"""\
You are a data-analysis quality judge. Evaluate the section below against \
the gold brief and return a JSON object with binary PASS/FAIL verdicts for \
each rubric plus a one-line reason per rubric.

=== USER AIM ===
{brief.user_aim}

=== GOLD BRIEF ===
Target variable : {brief.target}
Relevant fields : {relevant}
Irrelevant fields: {irrelevant}
Known patterns:
{known}
Forbidden claims:
{forbidden}

=== SECTION ===
Title     : {section.title}
Hypothesis: {section.hypothesis}

--- Python script ---
{section.script}

--- Markdown writeup ---
{section.writeup}

=== RUBRICS ===
Score each rubric PASS or FAIL.

relevant
  PASS if the section directly addresses the user aim.
  FAIL if it analyses aspects unrelated to the aim.

uses_reasonable_fields
  PASS if the script uses fields from the relevant list and does not treat
  irrelevant fields (e.g. ID columns) as meaningful variables.
  FAIL otherwise.

claims_supported_by_script
  PASS if every numerical claim or conclusion in the writeup is actually
  computed or surfaced by the script.
  FAIL if the writeup states facts the script does not produce.

claims_consistent_with_golden_brief
  PASS if the writeup's claims are consistent with the known patterns and
  contain none of the forbidden claims.
  FAIL if it contradicts a known pattern or makes a forbidden claim.

writeup_is_descriptive
  PASS if the writeup contains substantive findings beyond restating the
  hypothesis.
  FAIL if it is empty, a one-liner stub, or purely generic.
"""
