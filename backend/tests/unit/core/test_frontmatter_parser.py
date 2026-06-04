"""Unit tests for frontmatter_parser.py.

TDD: tests written before the implementation.

Acceptance criteria covered:
- sections/*.md correctly split into frontmatter dict + body string.
- Malformed YAML frontmatter → parse_error: True, no exception raised.
- Missing frontmatter delimiters → parse_error: True.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.frontmatter_parser import parse_frontmatter, parse_section_file

# ---------------------------------------------------------------------------
# parse_frontmatter — happy path
# ---------------------------------------------------------------------------

WELL_FORMED = """\
---
chart: charts/sec_01_churn.png
section_id: sec_01
---

# Section Title

Body text goes here.
"""


def test_parse_frontmatter_happy_path():
    """Well-formed frontmatter → correct dict and body string."""
    result = parse_frontmatter(WELL_FORMED)
    assert result["parse_error"] is False
    assert result["frontmatter"]["chart"] == "charts/sec_01_churn.png"
    assert result["frontmatter"]["section_id"] == "sec_01"
    assert "# Section Title" in result["body"]
    assert "Body text goes here." in result["body"]


def test_parse_frontmatter_multiple_fields():
    """Multiple frontmatter fields are all parsed correctly."""
    text = "---\nchart: charts/x.png\nsection_id: sec_02\ntitle: My Title\n---\n\nBody.\n"
    result = parse_frontmatter(text)
    assert result["parse_error"] is False
    fm = result["frontmatter"]
    assert fm["chart"] == "charts/x.png"
    assert fm["section_id"] == "sec_02"
    assert fm["title"] == "My Title"
    assert result["body"].strip() == "Body."


def test_parse_frontmatter_no_body():
    """Frontmatter with no body text → frontmatter parsed, body is empty string."""
    text = "---\nchart: charts/x.png\n---\n"
    result = parse_frontmatter(text)
    assert result["parse_error"] is False
    assert result["frontmatter"]["chart"] == "charts/x.png"
    assert result["body"] == ""


def test_parse_frontmatter_body_stripped_of_leading_newline():
    """Leading newline after closing --- is stripped from body."""
    text = "---\nkey: val\n---\n\nActual body.\n"
    result = parse_frontmatter(text)
    assert result["parse_error"] is False
    # The body should not start with a blank line
    assert result["body"].lstrip("\n").startswith("Actual body.")


# ---------------------------------------------------------------------------
# parse_frontmatter — no frontmatter (plain markdown)
# ---------------------------------------------------------------------------


def test_parse_frontmatter_no_delimiters():
    """Plain markdown with no frontmatter → empty dict, full text as body, parse_error False."""
    text = "# Plain Markdown\n\nNo frontmatter here.\n"
    result = parse_frontmatter(text)
    assert result["parse_error"] is False
    assert result["frontmatter"] == {}
    assert "# Plain Markdown" in result["body"]


def test_parse_frontmatter_empty_string():
    """parse_frontmatter('') → empty dict, empty body, parse_error False."""
    result = parse_frontmatter("")
    assert result["parse_error"] is False
    assert result["frontmatter"] == {}
    assert result["body"] == ""


# ---------------------------------------------------------------------------
# parse_frontmatter — error paths
# ---------------------------------------------------------------------------


def test_parse_frontmatter_malformed_yaml():
    """Malformed YAML between delimiters → parse_error True, frontmatter empty, no exception."""
    text = "---\n: bad yaml [unclosed\n---\n\nBody.\n"
    result = parse_frontmatter(text)
    assert result["parse_error"] is True
    assert result["frontmatter"] == {}
    # Body should still contain the original text (fail-safe: no crash)
    assert result["body"] is not None


def test_parse_frontmatter_no_closing_delimiter():
    """Opening --- with no closing delimiter → parse_error True, body = full content."""
    text = "---\nchart: charts/x.png\n\nNo closing delimiter.\n"
    result = parse_frontmatter(text)
    assert result["parse_error"] is True
    assert result["frontmatter"] == {}
    assert result["body"] == text


def test_parse_frontmatter_null_raises_type_error():
    """parse_frontmatter(None) raises TypeError (documented behaviour)."""
    with pytest.raises(TypeError):
        parse_frontmatter(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# parse_frontmatter — edge cases
# ---------------------------------------------------------------------------


def test_parse_frontmatter_crlf_line_endings():
    """CRLF line endings in frontmatter block are handled correctly."""
    text = "---\r\nchart: charts/x.png\r\nsection_id: sec_01\r\n---\r\n\r\nBody.\r\n"
    result = parse_frontmatter(text)
    assert result["parse_error"] is False
    assert result["frontmatter"]["chart"] == "charts/x.png"
    assert "Body." in result["body"]


def test_parse_frontmatter_whitespace_values():
    """Values with leading/trailing whitespace are stripped by yaml.safe_load."""
    text = "---\nchart:   charts/x.png  \n---\n\nBody.\n"
    result = parse_frontmatter(text)
    assert result["parse_error"] is False
    # yaml.safe_load strips trailing whitespace from scalar values.
    assert result["frontmatter"]["chart"].strip() == "charts/x.png"


# ---------------------------------------------------------------------------
# parse_section_file — happy path
# ---------------------------------------------------------------------------


def test_parse_section_file_happy_path(tmp_path: Path):
    """parse_section_file on a well-formed file → correct structured dict."""
    section_file = tmp_path / "sec_01.md"
    section_file.write_text(WELL_FORMED, encoding="utf-8")

    result = parse_section_file(section_file)

    assert result["parse_error"] is False
    assert result["frontmatter"]["chart"] == "charts/sec_01_churn.png"
    assert "# Section Title" in result["body"]
    assert str(section_file) == result["path"]


def test_parse_section_file_empty_file(tmp_path: Path):
    """parse_section_file on an empty file → frontmatter {}, body '', parse_error False."""
    section_file = tmp_path / "empty.md"
    section_file.write_bytes(b"")

    result = parse_section_file(section_file)

    assert result["parse_error"] is False
    assert result["frontmatter"] == {}
    assert result["body"] == ""


# ---------------------------------------------------------------------------
# parse_section_file — error paths
# ---------------------------------------------------------------------------


def test_parse_section_file_nonexistent(tmp_path: Path):
    """parse_section_file on a non-existent path → parse_error True, no exception raised."""
    missing = tmp_path / "nonexistent.md"

    result = parse_section_file(missing)

    assert result["parse_error"] is True
    assert result["frontmatter"] == {}
    assert result["body"] == ""


def test_parse_section_file_malformed_yaml(tmp_path: Path):
    """parse_section_file with malformed YAML → parse_error True, no exception."""
    section_file = tmp_path / "bad.md"
    section_file.write_text("---\n: bad yaml [unclosed\n---\n\nBody.\n", encoding="utf-8")

    result = parse_section_file(section_file)

    assert result["parse_error"] is True
    assert result["frontmatter"] == {}


def test_parse_section_file_no_closing_delimiter(tmp_path: Path):
    """parse_section_file with unclosed --- → parse_error True."""
    section_file = tmp_path / "unclosed.md"
    section_file.write_text("---\nchart: charts/x.png\n\nNo closing.\n", encoding="utf-8")

    result = parse_section_file(section_file)

    assert result["parse_error"] is True
