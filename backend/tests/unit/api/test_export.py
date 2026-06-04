"""Unit tests for GET /export endpoint — ZIP format.

Acceptance criteria:
- Returns application/zip with Content-Disposition: attachment; filename="brief.zip".
- ZIP contains report.md with accepted sections in plan order.
- Each accepted section with a PNG gets its chart in charts/ and a reference in report.md.
- Each accepted section with a .py file gets it in code/.
- Dropped / proposed / building sections are excluded.
- Missing .md file for a section: section skipped gracefully.
- No accepted sections → report.md contains default "no accepted sections" message.
- Zero OpenCode calls.
"""

from __future__ import annotations

import io
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.core.state_manager import StateManager
from backend.main import app

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Temporary workspace with sections/, charts/, analyses/ sub-dirs."""
    (tmp_path / "sections").mkdir(parents=True)
    (tmp_path / "charts").mkdir(parents=True)
    (tmp_path / "analyses").mkdir(parents=True)
    return tmp_path


def _make_md(workspace: Path, section_id: str, slug: str, body: str) -> str:
    """Write a section .md file; return its workspace-relative path."""
    content = f"---\nsection_id: {section_id}\n---\n\n{body}"
    rel = f"sections/{section_id}_{slug}.md"
    (workspace / rel).write_text(content, encoding="utf-8")
    return rel


def _make_png(workspace: Path, section_id: str) -> str:
    """Write a tiny placeholder PNG; return its workspace-relative path."""
    rel = f"charts/{section_id}_chart.png"
    (workspace / rel).write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG header bytes
    return rel


def _make_py(workspace: Path, section_id: str) -> str:
    """Write a placeholder .py file; return its workspace-relative path."""
    rel = f"analyses/{section_id}_analysis.py"
    (workspace / rel).write_text(f"# {section_id}\nimport pandas as pd\n", encoding="utf-8")
    return rel


@contextmanager
def _client_with_plan(workspace: Path, plan: list[dict]) -> Generator[TestClient, None, None]:
    """Context manager: TestClient whose state_manager has the given plan."""
    state_path = workspace / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(plan=plan, stage="building")
    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            yield c


def _read_zip(response_content: bytes) -> dict[str, bytes]:
    """Return {filename: content} dict from raw zip bytes."""
    buf = io.BytesIO(response_content)
    with zipfile.ZipFile(buf) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


# ---------------------------------------------------------------------------
# Content-type and headers
# ---------------------------------------------------------------------------


def test_export_returns_zip_content_type(workspace):
    """GET /export returns application/zip."""
    sm = StateManager(path=workspace / "state.json")
    sm.load()
    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")
    assert r.status_code == 200
    assert "application/zip" in r.headers.get("content-type", "")


def test_export_content_disposition_brief_zip(workspace):
    """Content-Disposition header names the file brief.zip."""
    sm = StateManager(path=workspace / "state.json")
    sm.load()
    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert 'filename="brief.zip"' in cd


# ---------------------------------------------------------------------------
# ZIP contains report.md
# ---------------------------------------------------------------------------


def test_export_zip_always_contains_report_md(workspace):
    """ZIP always contains report.md, even with no accepted sections."""
    sm = StateManager(path=workspace / "state.json")
    sm.load()
    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")
    files = _read_zip(r.content)
    assert "report.md" in files


def test_export_no_accepted_sections_default_message(workspace):
    """report.md contains default message when no sections are accepted."""
    plan = [{"id": "sec_01", "title": "S1", "hypothesis": "H1", "status": "proposed"}]
    sm = StateManager(path=workspace / "state.json")
    sm.load()
    sm.update(plan=plan, stage="building")
    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            r = c.get("/export")
    report = _read_zip(r.content)["report.md"].decode()
    assert "no accepted sections" in report.lower()


# ---------------------------------------------------------------------------
# Section bodies included in plan order
# ---------------------------------------------------------------------------


def test_export_accepted_section_body_in_report(workspace):
    """Accepted section body appears in report.md."""
    md_path = _make_md(workspace, "sec_01", "overview", "## Overview\n\nSome analysis.")
    plan = [
        {
            "id": "sec_01",
            "title": "Overview",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": md_path,
            "py_path": None,
            "png_path": None,
        }
    ]
    with _client_with_plan(workspace, plan) as c:
        r = c.get("/export")
    report = _read_zip(r.content)["report.md"].decode()
    assert "Some analysis." in report


def test_export_plan_order_preserved(workspace):
    """Sections appear in plan order in report.md."""
    _make_md(workspace, "sec_01", "first", "First section.")
    _make_md(workspace, "sec_02", "second", "Second section.")
    _make_md(workspace, "sec_03", "third", "Third section.")
    plan = [
        {
            "id": "sec_03",
            "title": "Third",
            "hypothesis": "H3",
            "status": "accepted",
            "md_path": None,
            "py_path": None,
            "png_path": None,
        },
        {
            "id": "sec_01",
            "title": "First",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": None,
            "py_path": None,
            "png_path": None,
        },
        {
            "id": "sec_02",
            "title": "Second",
            "hypothesis": "H2",
            "status": "accepted",
            "md_path": None,
            "py_path": None,
            "png_path": None,
        },
    ]
    with _client_with_plan(workspace, plan) as c:
        r = c.get("/export")
    report = _read_zip(r.content)["report.md"].decode()
    assert report.index("Third section.") < report.index("First section.")
    assert report.index("First section.") < report.index("Second section.")


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def test_export_dropped_sections_excluded(workspace):
    """Dropped sections are not in report.md."""
    _make_md(workspace, "sec_01", "kept", "Kept body.")
    _make_md(workspace, "sec_02", "dropped", "Dropped body.")
    plan = [
        {
            "id": "sec_01",
            "title": "Kept",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": None,
            "py_path": None,
            "png_path": None,
        },
        {
            "id": "sec_02",
            "title": "Dropped",
            "hypothesis": "H2",
            "status": "dropped",
            "md_path": None,
            "py_path": None,
            "png_path": None,
        },
    ]
    with _client_with_plan(workspace, plan) as c:
        r = c.get("/export")
    report = _read_zip(r.content)["report.md"].decode()
    assert "Kept body." in report
    assert "Dropped body." not in report


def test_export_proposed_and_building_sections_excluded(workspace):
    """Proposed and building sections are excluded."""
    _make_md(workspace, "sec_01", "accepted", "Accepted body.")
    _make_md(workspace, "sec_02", "proposed", "Proposed body.")
    _make_md(workspace, "sec_03", "building", "Building body.")
    plan = [
        {
            "id": "sec_01",
            "title": "S1",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": None,
            "py_path": None,
            "png_path": None,
        },
        {
            "id": "sec_02",
            "title": "S2",
            "hypothesis": "H2",
            "status": "proposed",
            "md_path": None,
            "py_path": None,
            "png_path": None,
        },
        {
            "id": "sec_03",
            "title": "S3",
            "hypothesis": "H3",
            "status": "building",
            "md_path": None,
            "py_path": None,
            "png_path": None,
        },
    ]
    with _client_with_plan(workspace, plan) as c:
        r = c.get("/export")
    report = _read_zip(r.content)["report.md"].decode()
    assert "Accepted body." in report
    assert "Proposed body." not in report
    assert "Building body." not in report


# ---------------------------------------------------------------------------
# Chart files included in charts/
# ---------------------------------------------------------------------------


def test_export_chart_included_in_zip(workspace):
    """PNG chart appears in charts/ inside the ZIP."""
    _make_md(workspace, "sec_01", "chart_section", "Analysis with chart.")
    png_path = _make_png(workspace, "sec_01")
    plan = [
        {
            "id": "sec_01",
            "title": "Chart Section",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": None,
            "py_path": None,
            "png_path": png_path,
        }
    ]
    with _client_with_plan(workspace, plan) as c:
        r = c.get("/export")
    files = _read_zip(r.content)
    chart_files = [f for f in files if f.startswith("charts/")]
    assert len(chart_files) == 1
    assert chart_files[0].endswith(".png")


def test_export_report_md_references_chart(workspace):
    """report.md contains an image reference to the chart file."""
    _make_md(workspace, "sec_01", "chart_section", "Analysis with chart.")
    png_path = _make_png(workspace, "sec_01")
    plan = [
        {
            "id": "sec_01",
            "title": "Chart Section",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": None,
            "py_path": None,
            "png_path": png_path,
        }
    ]
    with _client_with_plan(workspace, plan) as c:
        r = c.get("/export")
    report = _read_zip(r.content)["report.md"].decode()
    # Image reference uses relative path into charts/ folder.
    assert "![Chart Section](charts/" in report


# ---------------------------------------------------------------------------
# Python files included in code/
# ---------------------------------------------------------------------------


def test_export_py_file_included_in_zip(workspace):
    """Python file appears in code/ inside the ZIP."""
    _make_md(workspace, "sec_01", "code_section", "Section with code.")
    py_path = _make_py(workspace, "sec_01")
    plan = [
        {
            "id": "sec_01",
            "title": "Code Section",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": None,
            "py_path": py_path,
            "png_path": None,
        }
    ]
    with _client_with_plan(workspace, plan) as c:
        r = c.get("/export")
    files = _read_zip(r.content)
    code_files = [f for f in files if f.startswith("code/")]
    assert len(code_files) == 1
    assert code_files[0].endswith(".py")


def test_export_py_file_content_intact(workspace):
    """The .py file in the ZIP has the same content as the source file."""
    _make_md(workspace, "sec_01", "code_section", "Body.")
    py_path = _make_py(workspace, "sec_01")
    plan = [
        {
            "id": "sec_01",
            "title": "Code Section",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": None,
            "py_path": py_path,
            "png_path": None,
        }
    ]
    with _client_with_plan(workspace, plan) as c:
        r = c.get("/export")
    files = _read_zip(r.content)
    code_files = [f for f in files if f.startswith("code/")]
    code_content = files[code_files[0]].decode()
    assert "import pandas" in code_content


# ---------------------------------------------------------------------------
# Graceful handling of missing files
# ---------------------------------------------------------------------------


def test_export_missing_md_skipped_gracefully(workspace):
    """If a section's .md file is missing, it is skipped; others still export."""
    _make_md(workspace, "sec_02", "present", "Present body.")
    plan = [
        {
            "id": "sec_01",
            "title": "Missing",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": None,
            "py_path": None,
            "png_path": None,
        },
        {
            "id": "sec_02",
            "title": "Present",
            "hypothesis": "H2",
            "status": "accepted",
            "md_path": None,
            "py_path": None,
            "png_path": None,
        },
    ]
    with _client_with_plan(workspace, plan) as c:
        r = c.get("/export")
    assert r.status_code == 200
    report = _read_zip(r.content)["report.md"].decode()
    assert "Present body." in report


def test_export_missing_png_does_not_error(workspace):
    """If a section's PNG is missing from disk, no chart reference is added."""
    _make_md(workspace, "sec_01", "no_chart", "No chart body.")
    plan = [
        {
            "id": "sec_01",
            "title": "No Chart",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": None,
            "py_path": None,
            "png_path": "charts/sec_01_missing.png",
        }
    ]
    with _client_with_plan(workspace, plan) as c:
        r = c.get("/export")
    assert r.status_code == 200
    files = _read_zip(r.content)
    assert not any(f.startswith("charts/") for f in files)


def test_export_md_path_in_state_used_when_present(workspace):
    """If section has md_path in state, use it directly."""
    md_path = _make_md(workspace, "sec_01", "custom", "Custom body via md_path.")
    plan = [
        {
            "id": "sec_01",
            "title": "Custom",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": md_path,
            "py_path": None,
            "png_path": None,
        }
    ]
    with _client_with_plan(workspace, plan) as c:
        r = c.get("/export")
    report = _read_zip(r.content)["report.md"].decode()
    assert "Custom body via md_path." in report


# ---------------------------------------------------------------------------
# Frontmatter stripped from section .md files
# ---------------------------------------------------------------------------


def test_export_frontmatter_stripped_from_body(workspace):
    """YAML frontmatter is stripped; only body content appears in report.md."""
    content = "---\nsection_id: sec_01\nchart: charts/x.png\n---\n\nBody content only.\n"
    (workspace / "sections" / "sec_01_analysis.md").write_text(content, encoding="utf-8")
    plan = [
        {
            "id": "sec_01",
            "title": "Analysis",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": None,
            "py_path": None,
            "png_path": None,
        }
    ]
    with _client_with_plan(workspace, plan) as c:
        r = c.get("/export")
    report = _read_zip(r.content)["report.md"].decode()
    assert "Body content only." in report
    assert "section_id: sec_01" not in report


# ---------------------------------------------------------------------------
# Zero OpenCode calls
# ---------------------------------------------------------------------------


def test_export_zero_opencode_calls(workspace):
    """GET /export makes no OpenCode calls."""
    _make_md(workspace, "sec_01", "test", "Test body.")
    plan = [
        {
            "id": "sec_01",
            "title": "Test",
            "hypothesis": "H1",
            "status": "accepted",
            "md_path": None,
            "py_path": None,
            "png_path": None,
        }
    ]
    sm = StateManager(path=workspace / "state.json")
    sm.load()
    sm.update(plan=plan, stage="building")
    with patch("backend.main.StateManager", lambda: sm):
        with patch("httpx.AsyncClient") as mock_httpx:
            with TestClient(app) as c:
                r = c.get("/export")
    assert r.status_code == 200
    mock_httpx.assert_not_called()
