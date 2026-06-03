"""Unit tests for GET /export endpoint (N2-S13).

TDD: tests written before the real implementation.

Acceptance criteria covered:
- Accepted sections concatenated in plan order.
- Dropped sections excluded.
- Proposed sections excluded.
- No accepted sections → default markdown returned.
- Body extracted from frontmatter (body after --- block).
- Zero OpenCode calls.
- Content-Disposition: attachment; filename="brief.md" header.
- Content-Type: text/markdown.

Tests mirror ``backend/router.py`` → ``backend/tests/unit/app/test_export.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.state_manager import StateManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Return a temporary workspace directory with sections/ sub-dir."""
    (tmp_path / "sections").mkdir(parents=True)
    return tmp_path


def _make_section_file(workspace: Path, section_id: str, slug: str, body: str) -> Path:
    """Write a section .md file with frontmatter to workspace/sections/."""
    content = f"---\nsection_id: {section_id}\n---\n\n{body}"
    path = workspace / "sections" / f"{section_id}_{slug}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _make_client_with_plan(workspace: Path, plan_sections: list[dict]) -> TestClient:
    """Return a TestClient whose state_manager has the given plan."""
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(plan=plan_sections, stage="building")
    return TestClient(app), sm


@pytest.fixture()
def client(workspace: Path):
    """TestClient with isolated state manager and workspace."""
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            yield c, workspace, sm


# ---------------------------------------------------------------------------
# Happy path: accepted sections concatenated in plan order
# ---------------------------------------------------------------------------


def test_export_accepted_sections_concatenated(workspace):
    """Accepted sections are concatenated in plan order with separator.

    Acceptance: Given accepted sections, GET /export concatenates their .md
    bodies in plan.json order.
    """
    _make_section_file(workspace, "sec_01", "overview", "## Overview\n\nSome text.")
    _make_section_file(workspace, "sec_02", "churn", "## Churn\n\nMore text.")

    plan = [
        {"id": "sec_01", "title": "Overview", "hypothesis": "H1", "status": "accepted"},
        {"id": "sec_02", "title": "Churn", "hypothesis": "H2", "status": "accepted"},
    ]
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(plan=plan, stage="building")

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")

    assert r.status_code == 200
    body = r.text
    assert "## Overview" in body
    assert "## Churn" in body
    # Separator between sections.
    assert "---" in body
    # Order: sec_01 before sec_02.
    assert body.index("## Overview") < body.index("## Churn")


def test_export_content_disposition_header(workspace):
    """GET /export returns Content-Disposition: attachment; filename="brief.md".

    Acceptance: Content-Disposition header present.
    """
    _make_section_file(workspace, "sec_01", "intro", "# Intro\n\nBody.")
    plan = [{"id": "sec_01", "title": "Intro", "hypothesis": "H1", "status": "accepted"}]
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(plan=plan, stage="building")

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")

    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert 'filename="brief.md"' in cd


def test_export_media_type_text_markdown(workspace):
    """GET /export returns Content-Type: text/markdown."""
    plan = []  # No accepted sections is fine — still returns text/markdown.
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(plan=plan, stage="building")

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")

    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "text/markdown" in ct


# ---------------------------------------------------------------------------
# Filtering: dropped / proposed sections excluded
# ---------------------------------------------------------------------------


def test_export_dropped_sections_excluded(workspace):
    """Dropped sections are excluded from the export.

    Acceptance: Given dropped/proposed sections, when export runs, then they
    are excluded.
    """
    _make_section_file(workspace, "sec_01", "kept", "Kept section body.")
    _make_section_file(workspace, "sec_02", "dropped", "Dropped section body.")

    plan = [
        {"id": "sec_01", "title": "Kept", "hypothesis": "H1", "status": "accepted"},
        {"id": "sec_02", "title": "Dropped", "hypothesis": "H2", "status": "dropped"},
    ]
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(plan=plan, stage="building")

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")

    assert r.status_code == 200
    body = r.text
    assert "Kept section body." in body
    assert "Dropped section body." not in body


def test_export_proposed_sections_excluded(workspace):
    """Proposed (not yet accepted) sections are excluded from the export."""
    _make_section_file(workspace, "sec_01", "accepted", "Accepted body.")
    _make_section_file(workspace, "sec_02", "proposed", "Proposed body.")
    _make_section_file(workspace, "sec_03", "building", "Building body.")

    plan = [
        {"id": "sec_01", "title": "S1", "hypothesis": "H1", "status": "accepted"},
        {"id": "sec_02", "title": "S2", "hypothesis": "H2", "status": "proposed"},
        {"id": "sec_03", "title": "S3", "hypothesis": "H3", "status": "building"},
    ]
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(plan=plan, stage="building")

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")

    assert r.status_code == 200
    body = r.text
    assert "Accepted body." in body
    assert "Proposed body." not in body
    assert "Building body." not in body


# ---------------------------------------------------------------------------
# No accepted sections → default markdown
# ---------------------------------------------------------------------------


def test_export_no_accepted_sections_default_markdown(workspace):
    """When no sections are accepted, default markdown is returned.

    Acceptance: No accepted sections → returns default Markdown.
    """
    plan = [
        {"id": "sec_01", "title": "S1", "hypothesis": "H1", "status": "proposed"},
        {"id": "sec_02", "title": "S2", "hypothesis": "H2", "status": "dropped"},
    ]
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(plan=plan, stage="building")

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")

    assert r.status_code == 200
    body = r.text
    # Default content for empty export.
    assert "no accepted sections" in body.lower()


def test_export_empty_plan_default_markdown(workspace):
    """When plan is empty, default markdown is returned."""
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    # Default plan is []; no update needed.

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")

    assert r.status_code == 200
    body = r.text
    assert "no accepted sections" in body.lower()


# ---------------------------------------------------------------------------
# Plan order preserved
# ---------------------------------------------------------------------------


def test_export_plan_order_preserved(workspace):
    """Sections appear in plan order, not file-system order."""
    # Write sections in reverse order — the export must follow plan.json order.
    _make_section_file(workspace, "sec_01", "first", "First section.")
    _make_section_file(workspace, "sec_02", "second", "Second section.")
    _make_section_file(workspace, "sec_03", "third", "Third section.")

    # Plan has sec_03 first, then sec_01, then sec_02.
    plan = [
        {"id": "sec_03", "title": "Third", "hypothesis": "H3", "status": "accepted"},
        {"id": "sec_01", "title": "First", "hypothesis": "H1", "status": "accepted"},
        {"id": "sec_02", "title": "Second", "hypothesis": "H2", "status": "accepted"},
    ]
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(plan=plan, stage="building")

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")

    assert r.status_code == 200
    body = r.text
    # sec_03 body appears before sec_01, which appears before sec_02.
    assert body.index("Third section.") < body.index("First section.")
    assert body.index("First section.") < body.index("Second section.")


# ---------------------------------------------------------------------------
# Frontmatter parser: body extracted after --- block
# ---------------------------------------------------------------------------


def test_export_uses_frontmatter_parser_body(workspace):
    """The exported content is the body after frontmatter, not raw file content.

    Acceptance: File read uses frontmatter parser (body extracted).
    """
    # File has frontmatter that should NOT appear in the export.
    content_with_fm = (
        "---\n"
        "section_id: sec_01\n"
        "chart: charts/sec_01_foo.png\n"
        "---\n\n"
        "# Analysis Result\n\n"
        "The body content.\n"
    )
    (workspace / "sections" / "sec_01_analysis.md").write_text(content_with_fm, encoding="utf-8")

    plan = [{"id": "sec_01", "title": "Analysis", "hypothesis": "H1", "status": "accepted"}]
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(plan=plan, stage="building")

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")

    assert r.status_code == 200
    body = r.text
    # Body after frontmatter should appear.
    assert "# Analysis Result" in body
    assert "The body content." in body
    # Raw frontmatter YAML should NOT appear.
    assert "section_id: sec_01" not in body
    assert "chart: charts" not in body


# ---------------------------------------------------------------------------
# Zero OpenCode calls
# ---------------------------------------------------------------------------


def test_export_zero_opencode_calls(workspace):
    """GET /export makes no OpenCode calls.

    Acceptance: The call runs backend-only (no OpenCode).
    """
    _make_section_file(workspace, "sec_01", "test", "Test body.")
    plan = [{"id": "sec_01", "title": "Test", "hypothesis": "H1", "status": "accepted"}]
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(plan=plan, stage="building")

    # Patch httpx to raise if called — export must not touch OpenCode.
    with patch("backend.main.StateManager", lambda: sm):
        with patch("httpx.AsyncClient") as mock_httpx:
            with TestClient(app) as c:
                r = c.get("/export")

    assert r.status_code == 200
    mock_httpx.assert_not_called()


# ---------------------------------------------------------------------------
# Edge cases: missing .md file for accepted section → skip gracefully
# ---------------------------------------------------------------------------


def test_export_missing_md_file_skipped(workspace):
    """If the .md file for an accepted section cannot be found, it is skipped.

    Acceptance: Graceful handling of missing files.
    """
    # Only write sec_02's file — sec_01 is missing.
    _make_section_file(workspace, "sec_02", "present", "Present body.")

    plan = [
        {"id": "sec_01", "title": "Missing", "hypothesis": "H1", "status": "accepted"},
        {"id": "sec_02", "title": "Present", "hypothesis": "H2", "status": "accepted"},
    ]
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(plan=plan, stage="building")

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")

    assert r.status_code == 200
    body = r.text
    # sec_02 should still appear.
    assert "Present body." in body


def test_export_md_path_in_state_used_when_present(workspace):
    """If section has md_path stored in state (set by N2-S07), use it directly."""
    md_path = workspace / "sections" / "sec_01_custom_name.md"
    md_content = "---\nsection_id: sec_01\n---\n\nCustom body via md_path."
    md_path.write_text(md_content, encoding="utf-8")

    plan = [
        {
            "id": "sec_01",
            "title": "Custom",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": "sections/sec_01_custom_name.md",
        }
    ]
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(plan=plan, stage="building")

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")

    assert r.status_code == 200
    assert "Custom body via md_path." in r.text
