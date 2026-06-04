"""Unit tests for N2-S06 — section build turn: section prompt builder.

TDD: tests written before implementation.

Acceptance criteria covered:
- build_section_prompt() embeds absolute file paths for all three triplet files.
- build_section_prompt() instructs the agent to write frontmatter with required fields.
- build_section_prompt() does NOT contain a format/json_schema block (no structured output).
- Slug generation handles spaces, special characters, long titles, Unicode, and edge cases.
- File naming convention produces zero-padded section indices (sec_01, sec_02, ...).

Test categories:
- Happy path: required fields, absolute paths, profile/plan serialised in prompt.
- Error paths: empty title, missing workspace_root.
- Edge cases: single-column profile, max plan sections, Unicode title, boundary index values.
- Null/missing inputs: None workspace_root raises TypeError.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.agent.prompts.section import _make_slug, build_section_prompt

# ---------------------------------------------------------------------------
# Fixtures / shared helpers
# ---------------------------------------------------------------------------

_MINIMAL_PROFILE: dict = {
    "shape": {"rows": 500, "columns": 3, "target": "churn"},
    "columns": [
        {"name": "customer_id", "type": "numeric", "flags": ["id_like"], "summary": "row ID"},
        {"name": "tier", "type": "categorical", "flags": [], "summary": "subscription tier"},
        {"name": "churn", "type": "categorical", "flags": [], "summary": "binary churn label"},
    ],
    "flags": [],
}

_MINIMAL_PLAN: dict = {
    "sections": [
        {
            "id": "sec_01",
            "title": "Customer Churn by Tier",
            "hypothesis": "Higher-tier customers churn at lower rates.",
        },
        {
            "id": "sec_02",
            "title": "Revenue Impact",
            "hypothesis": "Churn disproportionately affects high-revenue segments.",
        },
    ]
}


def _call(
    tmp_path: Path,
    *,
    section_id: str = "sec_01",
    section_index: int = 1,
    title: str = "Customer Churn by Tier",
    hypothesis: str = "Higher-tier customers churn at lower rates.",
    aim: str = "Understand churn drivers",
    dataset: str = "customers_q3.csv",
    profile: dict | None = None,
    plan: dict | None = None,
) -> str:
    return build_section_prompt(
        section_id=section_id,
        section_index=section_index,
        title=title,
        hypothesis=hypothesis,
        aim=aim,
        dataset=dataset,
        profile=profile if profile is not None else _MINIMAL_PROFILE,
        plan=plan if plan is not None else _MINIMAL_PLAN,
        workspace_root=tmp_path / "workspace",
    )


# ---------------------------------------------------------------------------
# Happy path — required content in prompt
# ---------------------------------------------------------------------------


def test_section_prompt_contains_file_paths(tmp_path: Path) -> None:
    """Prompt must reference absolute paths for all three triplet files."""
    ws = tmp_path / "workspace"
    prompt = _call(tmp_path, section_index=1, title="Customer Churn by Tier")

    slug = "customer_churn_by_tier"
    analyses_path = str(ws.resolve() / "analyses" / f"sec_01_{slug}.py")
    charts_path = str(ws.resolve() / "charts" / f"sec_01_{slug}.png")
    sections_path = str(ws.resolve() / "sections" / f"sec_01_{slug}.md")

    assert analyses_path in prompt, (
        f"Expected absolute analyses path '{analyses_path}' in prompt.\nPrompt:\n{prompt}"
    )
    assert charts_path in prompt, (
        f"Expected absolute charts path '{charts_path}' in prompt.\nPrompt:\n{prompt}"
    )
    assert sections_path in prompt, (
        f"Expected absolute sections path '{sections_path}' in prompt.\nPrompt:\n{prompt}"
    )


def test_section_prompt_uses_absolute_paths(tmp_path: Path) -> None:
    """Absolute workspace path must appear; bare relative 'workspace/' prefix must not."""
    ws = tmp_path / "workspace"
    prompt = _call(tmp_path)

    assert str(ws.resolve()) in prompt, (
        f"Expected absolute workspace path '{ws.resolve()}' in prompt.\nPrompt:\n{prompt}"
    )
    # Must not leak a bare relative prefix (same guard as profile.py)
    assert " workspace/analyses/" not in prompt, (
        "Prompt must not contain bare relative 'workspace/analyses/' path."
    )
    assert " workspace/charts/" not in prompt, (
        "Prompt must not contain bare relative 'workspace/charts/' path."
    )
    assert " workspace/sections/" not in prompt, (
        "Prompt must not contain bare relative 'workspace/sections/' path."
    )


def test_section_prompt_contains_frontmatter_instruction(tmp_path: Path) -> None:
    """Prompt must instruct the agent to write all four required frontmatter fields."""
    prompt = _call(tmp_path, section_id="sec_01", title="Customer Churn by Tier")

    # All four frontmatter fields must be mentioned
    assert "section_id" in prompt, "Prompt must mention 'section_id' frontmatter field."
    assert "title" in prompt, "Prompt must mention 'title' frontmatter field."
    assert "hypothesis" in prompt, "Prompt must mention 'hypothesis' frontmatter field."
    assert "chart" in prompt, "Prompt must mention 'chart' frontmatter field."

    # The YAML delimiter syntax must be present
    assert "---" in prompt, "Prompt must include '---' frontmatter delimiters."


def test_section_prompt_no_schema(tmp_path: Path) -> None:
    """Prompt must not contain any structured-output instruction (ADR-005)."""
    prompt = _call(tmp_path)

    assert "json_schema" not in prompt, (
        "Prompt must not mention 'json_schema' — section build uses no structured output."
    )
    assert '"format"' not in prompt, (
        "Prompt must not contain a format block — section build uses no structured output."
    )
    assert "format: json" not in prompt, (
        "Prompt must not contain 'format: json' — no structured output."
    )
    assert "ReturnType" not in prompt, (
        "Prompt must not contain 'ReturnType' — section build uses no structured output."
    )


def test_section_prompt_mentions_apply_patch(tmp_path: Path) -> None:
    """Prompt must explicitly instruct use of apply_patch for file writes (ADR-011)."""
    prompt = _call(tmp_path)
    assert "apply_patch" in prompt, (
        "Prompt must instruct the agent to use apply_patch for all file writes."
    )


def test_section_prompt_includes_profile_and_plan(tmp_path: Path) -> None:
    """Profile and plan dicts must be serialised and embedded in the prompt."""
    profile = {
        "shape": {"rows": 100, "columns": 1, "target": "revenue"},
        "columns": [
            {
                "name": "unique_revenue_column_xyz",
                "type": "numeric",
                "flags": [],
                "summary": "sum",
            }
        ],
        "flags": [],
    }
    plan = {
        "sections": [
            {
                "id": "sec_01",
                "title": "Identifiable Plan Title ABC",
                "hypothesis": "h",
            }
        ]
    }
    prompt = build_section_prompt(
        section_id="sec_01",
        section_index=1,
        title="Test",
        hypothesis="h",
        aim="aim",
        dataset="data.csv",
        profile=profile,
        plan=plan,
        workspace_root=tmp_path / "workspace",
    )

    assert "unique_revenue_column_xyz" in prompt, (
        "Serialised profile column name must appear in prompt."
    )
    assert "Identifiable Plan Title ABC" in prompt, (
        "Serialised plan section title must appear in prompt."
    )


def test_section_prompt_includes_section_id_title_hypothesis_aim(tmp_path: Path) -> None:
    """Prompt must include the section_id, title, hypothesis, and aim."""
    prompt = _call(
        tmp_path,
        section_id="sec_03",
        title="Revenue Impact Analysis",
        hypothesis="Revenue impact is concentrated in top quartile.",
        aim="Find revenue drivers",
    )

    assert "sec_03" in prompt
    assert "Revenue Impact Analysis" in prompt
    assert "Revenue impact is concentrated in top quartile." in prompt
    assert "Find revenue drivers" in prompt


def test_section_prompt_includes_dataset_path(tmp_path: Path) -> None:
    """Prompt must include the dataset filename / path so the agent can load it."""
    prompt = _call(tmp_path, dataset="sales_2025.csv")
    assert "sales_2025.csv" in prompt, (
        "Prompt must reference the dataset filename so the agent can read it."
    )


# ---------------------------------------------------------------------------
# Slug generation — _make_slug helper
# ---------------------------------------------------------------------------


def test_slug_generation_basic() -> None:
    """Standard title slug: lowercase, spaces become underscores."""
    assert _make_slug("Customer Churn by Tier") == "customer_churn_by_tier"


def test_slug_generation_special_characters() -> None:
    """Non-alphanumeric characters collapse to single underscores; no leading/trailing."""
    assert _make_slug("Revenue & Margin (Q3)") == "revenue_margin_q3"


def test_slug_generation_consecutive_separators() -> None:
    """Consecutive non-alphanumeric characters collapse to a single underscore."""
    assert _make_slug("Hello---World") == "hello_world"


def test_slug_generation_leading_trailing_stripped() -> None:
    """Leading and trailing underscores are stripped."""
    slug = _make_slug("  --Leading and Trailing--  ")
    assert not slug.startswith("_"), f"Slug must not start with '_', got: '{slug}'"
    assert not slug.endswith("_"), f"Slug must not end with '_', got: '{slug}'"


def test_slug_generation_truncation() -> None:
    """Titles longer than 40 chars produce a slug of at most 40 characters."""
    long_title = "A Very Long Section Title That Exceeds The Maximum Slug Length Limit"
    slug = _make_slug(long_title)
    assert len(slug) <= 40, f"Slug must be <= 40 chars, got {len(slug)}: '{slug}'"


def test_slug_generation_unicode() -> None:
    """Non-ASCII characters are replaced by underscores (filesystem-safe)."""
    slug = _make_slug("Analyse données géographiques")
    # Result must be ASCII-safe (no non-ASCII characters)
    slug.encode("ascii")  # raises UnicodeEncodeError if non-ASCII chars remain
    assert len(slug) > 0, "Slug must not be empty after Unicode replacement."


def test_slug_generation_all_special_chars() -> None:
    """A title of only special characters should produce a non-crashing result."""
    slug = _make_slug("!@#$%^&*()")
    # Should be empty string or underscore-only — not raise
    assert isinstance(slug, str)


# ---------------------------------------------------------------------------
# File naming convention — zero-padded index
# ---------------------------------------------------------------------------


def test_file_naming_convention_index_1(tmp_path: Path) -> None:
    """section_index=1 produces 'sec_01_' prefix in all three triplet paths."""
    prompt = _call(tmp_path, section_index=1, title="Churn Analysis")
    assert "sec_01_churn_analysis" in prompt, (
        "Expected 'sec_01_churn_analysis' in prompt for section_index=1."
    )


def test_file_naming_convention_index_10(tmp_path: Path) -> None:
    """section_index=10 produces 'sec_10_' prefix in all three triplet paths."""
    ws = tmp_path / "workspace"
    prompt = build_section_prompt(
        section_id="sec_10",
        section_index=10,
        title="Final Summary",
        hypothesis="h",
        aim="aim",
        dataset="data.csv",
        profile=_MINIMAL_PROFILE,
        plan=_MINIMAL_PLAN,
        workspace_root=ws,
    )
    assert "sec_10_final_summary" in prompt, (
        "Expected 'sec_10_final_summary' in prompt for section_index=10."
    )


def test_file_naming_convention_index_2(tmp_path: Path) -> None:
    """section_index=2 produces zero-padded 'sec_02_' prefix."""
    ws = tmp_path / "workspace"
    prompt = build_section_prompt(
        section_id="sec_02",
        section_index=2,
        title="Revenue Breakdown",
        hypothesis="h",
        aim="aim",
        dataset="data.csv",
        profile=_MINIMAL_PROFILE,
        plan=_MINIMAL_PLAN,
        workspace_root=ws,
    )
    assert "sec_02_revenue_breakdown" in prompt, (
        "Expected 'sec_02_revenue_breakdown' in prompt for section_index=2."
    )


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_section_prompt_missing_workspace_root() -> None:
    """workspace_root=None raises TypeError (Path(None) contract)."""
    with pytest.raises(TypeError):
        build_section_prompt(
            section_id="sec_01",
            section_index=1,
            title="Title",
            hypothesis="h",
            aim="aim",
            dataset="data.csv",
            profile=_MINIMAL_PROFILE,
            plan=_MINIMAL_PLAN,
            workspace_root=None,  # type: ignore[arg-type]
        )


def test_section_prompt_empty_title(tmp_path: Path) -> None:
    """An empty title either raises ValueError or produces a non-crashing result."""
    # Per plan: either ValueError or a minimal-but-valid slug. Test both paths.
    try:
        prompt = build_section_prompt(
            section_id="sec_01",
            section_index=1,
            title="",
            hypothesis="h",
            aim="aim",
            dataset="data.csv",
            profile=_MINIMAL_PROFILE,
            plan=_MINIMAL_PLAN,
            workspace_root=tmp_path / "workspace",
        )
        # If it does not raise, the prompt must still be a non-empty string
        assert isinstance(prompt, str) and len(prompt) > 0
    except ValueError:
        pass  # Acceptable — documented in the implementation


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_section_prompt_single_column_profile(tmp_path: Path) -> None:
    """A profile with exactly one column does not crash."""
    single_col_profile = {
        "shape": {"rows": 100, "columns": 1, "target": None},
        "columns": [{"name": "value", "type": "numeric", "flags": [], "summary": "single column"}],
        "flags": ["small_dataset"],
    }
    prompt = build_section_prompt(
        section_id="sec_01",
        section_index=1,
        title="Single Column Analysis",
        hypothesis="h",
        aim="aim",
        dataset="data.csv",
        profile=single_col_profile,
        plan=_MINIMAL_PLAN,
        workspace_root=tmp_path / "workspace",
    )
    assert "single column" in prompt
    assert isinstance(prompt, str) and len(prompt) > 0


def test_section_prompt_max_plan_sections(tmp_path: Path) -> None:
    """A plan with 6 sections (stated maximum) does not cause truncation or error."""
    max_plan = {
        "sections": [
            {
                "id": f"sec_0{i}",
                "title": f"Section {i}",
                "hypothesis": f"Hypothesis {i}",
            }
            for i in range(1, 7)
        ]
    }
    prompt = build_section_prompt(
        section_id="sec_01",
        section_index=1,
        title="Section 1",
        hypothesis="h",
        aim="aim",
        dataset="data.csv",
        profile=_MINIMAL_PROFILE,
        plan=max_plan,
        workspace_root=tmp_path / "workspace",
    )
    # All six section titles must appear in the serialised plan
    for i in range(1, 7):
        assert f"Section {i}" in prompt, f"Section {i} title not found in prompt."


def test_section_prompt_unicode_title(tmp_path: Path) -> None:
    """A title with non-ASCII characters produces an ASCII-safe slug in file paths."""
    ws = tmp_path / "workspace"
    prompt = build_section_prompt(
        section_id="sec_01",
        section_index=1,
        title="Données géographiques",
        hypothesis="h",
        aim="aim",
        dataset="data.csv",
        profile=_MINIMAL_PROFILE,
        plan=_MINIMAL_PLAN,
        workspace_root=ws,
    )
    # Prompt must not crash; the sec_01_ prefix must appear (slug was generated)
    assert "analyses" in prompt
    assert "sec_01_" in prompt
    # Extract the slug from the analyses path (text after the last '/')
    # and verify it is ASCII-safe. The prompt lines may contain non-ASCII
    # punctuation in the instruction text (e.g. em-dash in "Step 1 —"), so we
    # only check the slug portion of the file path itself, not the whole line.
    import re as _re

    match = _re.search(r"analyses/(sec_01_[^\s.]+)", prompt)
    assert match, "Could not find analyses path in prompt."
    slug_part = match.group(1)
    slug_part.encode("ascii")  # raises if non-ASCII characters slipped into the slug


def test_section_prompt_instructs_execute_script(tmp_path: Path) -> None:
    """Prompt must instruct the agent to execute the analysis script via bash."""
    prompt = _call(tmp_path)
    # The prompt should mention running/executing the script
    prompt_lower = prompt.lower()
    assert any(word in prompt_lower for word in ("run", "execute", "bash")), (
        "Prompt must instruct the agent to execute the analysis script."
    )
