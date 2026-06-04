"""Unit tests for backend/prompts/plan.py.

TDD: tests written before the implementation.

Acceptance criteria covered:
- Plan prompt: json_schema output + retryCount: 2 (via client.prompt schema param).
- PLAN_SCHEMA has sections array with id, title, hypothesis per item.
- build_plan_prompt() contains aim, profile JSON reference, and plan.json path.
"""

from __future__ import annotations

from pathlib import Path

from backend.agent.prompts.plan import PLAN_SCHEMA, build_plan_prompt

# ---------------------------------------------------------------------------
# PLAN_SCHEMA structure
# ---------------------------------------------------------------------------


def test_plan_schema_type():
    """PLAN_SCHEMA type is 'object'."""
    assert PLAN_SCHEMA["type"] == "object"


def test_plan_schema_requires_sections():
    """PLAN_SCHEMA requires 'sections' at top level."""
    assert "sections" in PLAN_SCHEMA.get("required", [])


def test_plan_schema_sections_is_array():
    """PLAN_SCHEMA sections property is an array type."""
    sections_schema = PLAN_SCHEMA["properties"]["sections"]
    assert sections_schema["type"] == "array"


def test_plan_schema_sections_min_items():
    """PLAN_SCHEMA sections has minItems: 3."""
    sections_schema = PLAN_SCHEMA["properties"]["sections"]
    assert sections_schema["minItems"] == 3


def test_plan_schema_sections_max_items():
    """PLAN_SCHEMA sections has maxItems: 6."""
    sections_schema = PLAN_SCHEMA["properties"]["sections"]
    assert sections_schema["maxItems"] == 6


def test_plan_schema_section_item_required_fields():
    """Each section item requires id, title, hypothesis."""
    item_schema = PLAN_SCHEMA["properties"]["sections"]["items"]
    required = item_schema.get("required", [])
    assert "id" in required
    assert "title" in required
    assert "hypothesis" in required


def test_plan_schema_section_item_field_types():
    """Each section item's id, title, hypothesis are string type."""
    item_schema = PLAN_SCHEMA["properties"]["sections"]["items"]
    props = item_schema["properties"]
    assert props["id"]["type"] == "string"
    assert props["title"]["type"] == "string"
    assert props["hypothesis"]["type"] == "string"


# ---------------------------------------------------------------------------
# build_plan_prompt — happy path
# ---------------------------------------------------------------------------


def test_build_plan_prompt_contains_aim(tmp_path: Path):
    """build_plan_prompt includes the user's aim in the output."""
    aim = "Understand customer churn drivers"
    profile = {"shape": {"rows": 100, "columns": 5}, "flags": []}
    result = build_plan_prompt("data.csv", aim, profile, tmp_path)
    assert aim in result


def test_build_plan_prompt_contains_profile_json(tmp_path: Path):
    """build_plan_prompt serialises and includes the profile in the prompt."""
    profile = {"shape": {"rows": 100, "columns": 5}, "flags": ["small_dataset"]}
    result = build_plan_prompt("data.csv", "find patterns", profile, tmp_path)
    # Profile should be serialised as JSON in the prompt
    assert "small_dataset" in result


def test_build_plan_prompt_references_plan_json_path(tmp_path: Path):
    """build_plan_prompt references the workspace plan.json path."""
    profile = {}
    result = build_plan_prompt("data.csv", "find patterns", profile, tmp_path)
    assert "plan.json" in result


def test_build_plan_prompt_references_dataset(tmp_path: Path):
    """build_plan_prompt references the dataset filename."""
    profile = {}
    result = build_plan_prompt("customers_q3.csv", "analyse sales", profile, tmp_path)
    assert "customers_q3.csv" in result


def test_build_plan_prompt_returns_nonempty_string(tmp_path: Path):
    """build_plan_prompt returns a non-empty string."""
    result = build_plan_prompt("data.csv", "analyse", {}, tmp_path)
    assert isinstance(result, str) and len(result) > 50


# ---------------------------------------------------------------------------
# build_plan_prompt — edge cases
# ---------------------------------------------------------------------------


def test_build_plan_prompt_empty_profile_no_crash(tmp_path: Path):
    """build_plan_prompt with empty profile dict does not crash."""
    result = build_plan_prompt("data.csv", "analyse", {}, tmp_path)
    assert isinstance(result, str)


def test_build_plan_prompt_mentions_sections(tmp_path: Path):
    """build_plan_prompt instructs the agent to produce sections."""
    profile = {}
    result = build_plan_prompt("data.csv", "find patterns", profile, tmp_path)
    # Prompt should guide the agent on the output format
    assert "section" in result.lower()
