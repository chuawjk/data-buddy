"""Frontmatter parser for section markdown files.

Parses YAML frontmatter from ``sections/*.md`` files written by OpenCode.

The expected format is::

    ---
    chart: charts/sec_01_churn_by_tier.png
    section_id: sec_01
    ---

    # Section Title

    Body text...

The leading ``---`` must appear on the first line of the file.  Content
between the two delimiters is parsed as YAML using ``yaml.safe_load``.
Fail-safe semantics: any parsing problem sets ``parse_error: True`` and
returns an empty frontmatter dict — the function never raises.

Public API:
    ``parse_frontmatter(text: str) -> dict``
        Split frontmatter + body from a string.  Raises ``TypeError`` if
        ``text`` is ``None`` (documented; callers must pass a string).

    ``parse_section_file(path: Path) -> dict``
        Read a file from disk, call ``parse_frontmatter``, and return a
        structured dict with ``path``, ``frontmatter``, ``body``, and
        ``parse_error``.  Any I/O or encoding error sets ``parse_error: True``
        and returns empty frontmatter + empty body; never raises.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# The frontmatter delimiter (must appear alone on its own line).
_DELIM = "---"


def parse_frontmatter(text: str) -> dict:
    """Split YAML frontmatter from the body of a markdown string.

    Args:
        text: Markdown text to parse.  Must be a ``str``; passing ``None``
            raises ``TypeError`` (callers are responsible for reading the file
            before calling this function).

    Returns:
        A dict with keys:
        - ``frontmatter`` (dict): Parsed YAML key-value pairs; ``{}`` if
          absent or malformed.
        - ``body`` (str): Markdown body text after the frontmatter block;
          the full text if no frontmatter is present.
        - ``parse_error`` (bool): ``True`` if frontmatter delimiters were
          found but the YAML between them could not be parsed, or if an
          opening delimiter was found with no closing delimiter.

    Raises:
        TypeError: If ``text`` is not a ``str`` (e.g. ``None``).
    """
    # TypeError is intentional: callers must pass a str.
    if not isinstance(text, str):
        raise TypeError(f"parse_frontmatter() expects a str, got {type(text).__name__!r}")

    # Quick path: no frontmatter delimiter at all.
    # Handle both LF and CRLF line endings.
    normalized = text.replace("\r\n", "\n")

    if not (normalized == _DELIM or normalized.startswith(_DELIM + "\n")):
        # No opening delimiter — treat entire text as body.
        return {"frontmatter": {}, "body": text, "parse_error": False}

    # Find the closing delimiter.
    # Skip the first "---\n" (4 chars) and look for the next "---" on its own line.
    after_open = normalized[len(_DELIM) + 1 :]  # text after the opening ---\n

    # Search for closing delimiter as a line starting with "---".
    close_idx = _find_closing_delimiter(after_open)
    if close_idx is None:
        # Opening delimiter found but no closing delimiter → parse_error.
        return {"frontmatter": {}, "body": text, "parse_error": True}

    raw_yaml = after_open[:close_idx]
    remainder = after_open[close_idx + len(_DELIM) :]

    # Strip the leading newline from the body (content after "---\n").
    body = remainder.lstrip("\n")

    # Parse the YAML between the delimiters.
    try:
        parsed = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        logger.debug("frontmatter YAML parse error: %s", exc)
        return {"frontmatter": {}, "body": body, "parse_error": True}

    # yaml.safe_load returns None for an empty block (e.g. "---\n---\n").
    if parsed is None:
        parsed = {}

    # If yaml.safe_load returns a non-dict (e.g. a bare scalar), treat as error.
    if not isinstance(parsed, dict):
        logger.debug("frontmatter parsed to non-dict type: %r", type(parsed))
        return {"frontmatter": {}, "body": body, "parse_error": True}

    return {"frontmatter": parsed, "body": body, "parse_error": False}


def parse_section_file(path: Path) -> dict:
    """Read and parse a ``sections/*.md`` file from disk.

    Reads the file as UTF-8, then delegates to ``parse_frontmatter``.  Any
    I/O or encoding error is caught and mapped to a fail-safe result with
    ``parse_error: True``.

    Args:
        path: Path to the section markdown file.

    Returns:
        A dict with keys:
        - ``path`` (str): String representation of ``path``.
        - ``frontmatter`` (dict): Parsed YAML key-value pairs; ``{}`` if
          absent or malformed.
        - ``body`` (str): Markdown body text; ``""`` on I/O error.
        - ``parse_error`` (bool): ``True`` if the file could not be read or
          if frontmatter parsing failed.
    """
    path = Path(path)
    _fail_result = {"path": str(path), "frontmatter": {}, "body": "", "parse_error": True}

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("parse_section_file: could not read %s: %s", path, exc)
        return _fail_result

    parsed = parse_frontmatter(text)
    return {
        "path": str(path),
        "frontmatter": parsed["frontmatter"],
        "body": parsed["body"],
        "parse_error": parsed["parse_error"],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_closing_delimiter(text: str) -> int | None:
    """Return the character index of the closing ``---`` delimiter in ``text``.

    ``text`` is the content *after* the opening ``---\\n`` has been consumed.
    The function looks for a line that is exactly ``---`` (with an optional
    trailing newline or at end-of-string).

    Returns:
        The index of the start of the ``---`` line, or ``None`` if not found.
    """
    pos = 0
    while pos < len(text):
        # Find the next newline (or end of string).
        nl = text.find("\n", pos)
        if nl == -1:
            line = text[pos:]
            end = len(text)
        else:
            line = text[pos:nl]
            end = nl + 1  # include the \n in the consumed region

        if line.rstrip("\r") == _DELIM:
            return pos

        pos = end

    return None
