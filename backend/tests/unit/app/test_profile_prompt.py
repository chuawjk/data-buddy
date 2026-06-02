"""Unit tests for N1-S09 — profiling turn: profile prompt and prompt() method.

TDD: tests written before implementation.

Acceptance criteria covered:
- prompt() sends format.type == "json_schema" and retryCount == 2 when schema is provided.
- prompt() omits the "format" key entirely when no schema is given.
- prompt() uses parts: [{"type": "text", "text": ...}] payload (v1.15.13 schema, QA-02 fix).
- PROFILE_SCHEMA is a valid JSON Schema (required top-level fields present).
- build_profile_prompt() references the dataset filename in the returned string.

Mock strategy: httpx.AsyncClient is mocked; no real OpenCode server is contacted.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.opencode_client import OpenCodeClient
from backend.prompts.profile import PROFILE_SCHEMA, build_profile_prompt
from backend.state_manager import StateManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state_manager(tmp_path: Path) -> StateManager:
    """Return a StateManager pointing at a temp directory."""
    sm = StateManager(path=tmp_path / "state.json")
    sm.update(opencode_session_id="ses_test_session")
    return sm


def _make_client(tmp_path: Path) -> OpenCodeClient:
    return OpenCodeClient(state_manager=_make_state_manager(tmp_path))


def _make_mock_response(status_code: int = 204) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# test_prompt_payload_with_schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_payload_with_schema(tmp_path: Path) -> None:
    """prompt(session_id, text, schema=PROFILE_SCHEMA) sends format.type=='json_schema'
    and retryCount==2 in the POST body."""
    client = _make_client(tmp_path)
    session_id = "ses_test_session"
    text = "Profile the dataset."

    posted_json: list[dict] = []

    mock_resp = _make_mock_response(204)

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)

    async def _capture_post(url, *, json=None, timeout=None, **kwargs):
        posted_json.append(json)
        return mock_resp

    mock_http.post = AsyncMock(side_effect=_capture_post)

    with patch("backend.opencode_client.httpx.AsyncClient", return_value=mock_http):
        await client.prompt(session_id, text, schema=PROFILE_SCHEMA)

    assert len(posted_json) == 1, "Expected exactly one POST call"
    body = posted_json[0]

    # v1.15.13: payload uses parts array, not top-level text
    assert "parts" in body, f"Expected 'parts' key in POST body, got: {body}"
    assert len(body["parts"]) == 1
    assert body["parts"][0]["type"] == "text"
    assert body["parts"][0]["text"] == text

    # format block must be present
    assert "format" in body, f"Expected 'format' key in POST body, got: {body}"
    fmt = body["format"]

    # type must be "json_schema"
    assert fmt["type"] == "json_schema", (
        f"Expected format.type == 'json_schema', got: {fmt['type']}"
    )

    # retryCount must be 2
    assert fmt["retryCount"] == 2, f"Expected retryCount == 2, got: {fmt['retryCount']}"

    # v1.15.13: schema is directly at format.schema (no json_schema wrapper, no name field)
    assert "schema" in fmt, f"Expected 'schema' key directly in format, got: {fmt}"
    assert fmt["schema"] == PROFILE_SCHEMA
    assert "json_schema" not in fmt, (
        f"v1.15.13 dropped the json_schema wrapper — must not be present, got: {fmt}"
    )


# ---------------------------------------------------------------------------
# test_prompt_payload_without_schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_payload_without_schema(tmp_path: Path) -> None:
    """prompt(session_id, text) with no schema → POST body must NOT contain 'format' key."""
    client = _make_client(tmp_path)
    session_id = "ses_test_session"
    text = "Profile the dataset."

    posted_json: list[dict] = []

    mock_resp = _make_mock_response(204)

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)

    async def _capture_post(url, *, json=None, timeout=None, **kwargs):
        posted_json.append(json)
        return mock_resp

    mock_http.post = AsyncMock(side_effect=_capture_post)

    with patch("backend.opencode_client.httpx.AsyncClient", return_value=mock_http):
        await client.prompt(session_id, text)  # no schema

    assert len(posted_json) == 1, "Expected exactly one POST call"
    body = posted_json[0]

    assert "format" not in body, (
        f"Expected no 'format' key in POST body when schema is None, got: {body}"
    )
    # v1.15.13: text is inside parts array, not at top level
    assert "parts" in body, f"Expected 'parts' key in POST body, got: {body}"
    assert body["parts"][0]["type"] == "text"
    assert body["parts"][0]["text"] == text
    assert "text" not in body, (
        f"v1.15.13 dropped top-level 'text' field — must not be present, got: {body}"
    )


# ---------------------------------------------------------------------------
# test_profile_schema_valid
# ---------------------------------------------------------------------------


def test_profile_schema_valid() -> None:
    """PROFILE_SCHEMA is a valid JSON Schema — required top-level fields present."""
    # Must be serialisable to JSON
    dumped = json.dumps(PROFILE_SCHEMA)
    schema = json.loads(dumped)

    assert schema.get("type") == "object", "Top-level type must be 'object'"

    required = schema.get("required", [])
    assert "shape" in required, "'shape' must be in top-level required"
    assert "columns" in required, "'columns' must be in top-level required"
    assert "flags" in required, "'flags' must be in top-level required"

    properties = schema.get("properties", {})

    # shape sub-schema
    shape = properties.get("shape", {})
    assert shape.get("type") == "object"
    shape_required = shape.get("required", [])
    assert "rows" in shape_required
    assert "columns" in shape_required

    # columns sub-schema
    columns = properties.get("columns", {})
    assert columns.get("type") == "array"
    items = columns.get("items", {})
    items_required = items.get("required", [])
    assert "name" in items_required
    assert "type" in items_required
    assert "flags" in items_required
    assert "summary" in items_required

    # flags sub-schema
    flags = properties.get("flags", {})
    assert flags.get("type") == "array"


# ---------------------------------------------------------------------------
# test_build_profile_prompt_contains_dataset
# ---------------------------------------------------------------------------


def test_build_profile_prompt_contains_dataset() -> None:
    """build_profile_prompt() includes the dataset filename in the returned prompt."""
    dataset = "customers_q3.csv"
    aim = "Understand churn drivers"
    prompt = build_profile_prompt(dataset, aim)

    assert dataset in prompt, (
        f"Expected dataset '{dataset}' to appear in prompt.\nPrompt:\n{prompt}"
    )
    assert aim in prompt, f"Expected aim '{aim}' to appear in prompt.\nPrompt:\n{prompt}"
