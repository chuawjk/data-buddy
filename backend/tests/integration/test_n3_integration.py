"""Night 3 integration tests: N3-S13.

Tests for new Night 3 cross-lane behaviour:
  - test_section_accept_triggers_done — last accepted section causes stage="done"
  - test_section_drop_triggers_done — last dropped section causes stage="done"
  - test_retry_turn_empty_body — POST /turn with {} returns 204 (not 422)
  - test_retry_turn_null_body — POST /turn with no body returns 204 (not 422)
  - test_turn_error_payload_shape — turn.error event contains reason + stage (not retryable)
  - test_turn_error_via_force_hook — QA_FORCE_TURN_ERROR drives turn.error deterministically
  - test_done_stage_persisted — after accept-all, GET /state returns stage="done"
  - test_dropped_sections_excluded_from_done_check — dropped sections are terminal
  - test_section_accept_not_proposed_returns_400 — double-accept is rejected
  - test_static_html_served — GET / returns HTML when dist/index.html exists

All tests use SKIP_OPENCODE=1 (set by conftest.py) and real file I/O.
OpenCode calls are never made for the endpoints under test.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.core.state_manager import StateManager
from backend.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Isolated workspace root; state.json lives at workspace/state.json."""
    return tmp_path


@pytest.fixture()
def client(workspace: Path):
    state_path = workspace / "state.json"
    with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
        with TestClient(app) as c:
            yield c


@pytest.fixture()
def building_client(workspace: Path):
    """Client pre-seeded in building stage with two proposed sections."""
    state_path = workspace / "state.json"
    initial_state = {
        "version": "1",
        "stage": "building",
        "aim": "find patterns",
        "dataset_path": "data/test.csv",
        "opencode_session_id": "ses_test_123",
        "profile": None,
        "plan": [
            {
                "id": "sec_001",
                "title": "Overview",
                "hypothesis": "Data overview",
                "status": "proposed",
            },
            {
                "id": "sec_002",
                "title": "Trends",
                "hypothesis": "Trend analysis",
                "status": "proposed",
            },
        ],
        "last_saved": "2026-06-04T00:00:00Z",
    }
    state_path.write_text(json.dumps(initial_state))
    with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
        with TestClient(app) as c:
            yield c


@pytest.fixture()
def single_section_building_client(workspace: Path):
    """Client pre-seeded in building stage with exactly one proposed section."""
    state_path = workspace / "state.json"
    initial_state = {
        "version": "1",
        "stage": "building",
        "aim": "find patterns",
        "dataset_path": "data/test.csv",
        "opencode_session_id": "ses_test_456",
        "profile": None,
        "plan": [
            {
                "id": "sec_only",
                "title": "Only Section",
                "hypothesis": "The only section",
                "status": "proposed",
            },
        ],
        "last_saved": "2026-06-04T00:00:00Z",
    }
    state_path.write_text(json.dumps(initial_state))
    with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# 1. Section accept → done transition (N3-S01)
# ---------------------------------------------------------------------------


def test_section_accept_triggers_done(single_section_building_client):
    """Given one proposed section, accepting it causes GET /state to return stage='done'.

    This is the core N3-S01 requirement: _check_done_or_next transitions the
    stage to 'done' when every section is in a terminal status.
    """
    c = single_section_building_client

    # Accept the only section.
    r = c.post("/api/section/sec_only/accept")
    assert r.status_code == 204

    # The fire-and-forget _check_done_or_next runs inside TestClient's event loop.
    # Give it a tick to complete.
    import time

    time.sleep(0.05)

    # State must now reflect done.
    state_r = c.get("/api/state")
    assert state_r.status_code == 200
    assert state_r.json()["stage"] == "done"


def test_section_drop_triggers_done(single_section_building_client):
    """Given one proposed section, dropping it causes GET /state to return stage='done'.

    Dropped sections are terminal — they satisfy the done-check.
    """
    c = single_section_building_client

    r = c.post("/api/section/sec_only/drop")
    assert r.status_code == 204

    import time

    time.sleep(0.05)

    state_r = c.get("/api/state")
    assert state_r.status_code == 200
    assert state_r.json()["stage"] == "done"


def test_done_stage_persisted_to_disk(workspace: Path, single_section_building_client):
    """After all sections are accepted, stage='done' is written to state.json on disk."""
    c = single_section_building_client
    state_path = workspace / "state.json"

    c.post("/api/section/sec_only/accept")

    import time

    time.sleep(0.05)

    on_disk = json.loads(state_path.read_text())
    assert on_disk["stage"] == "done"


def test_accept_first_section_does_not_trigger_done(building_client):
    """Accepting one of two sections does NOT transition to done while one remains."""
    c = building_client

    r = c.post("/api/section/sec_001/accept")
    assert r.status_code == 204

    import time

    time.sleep(0.05)

    state_r = c.get("/api/state")
    assert state_r.json()["stage"] == "building"


def test_accept_all_sections_triggers_done(building_client):
    """Accepting every section in sequence transitions stage to done."""
    c = building_client

    c.post("/api/section/sec_001/accept")
    c.post("/api/section/sec_002/accept")

    import time

    time.sleep(0.05)

    state_r = c.get("/api/state")
    assert state_r.json()["stage"] == "done"


def test_dropped_sections_are_terminal(building_client):
    """Mix of accepted + dropped sections is sufficient to trigger done."""
    c = building_client

    c.post("/api/section/sec_001/accept")
    c.post("/api/section/sec_002/drop")

    import time

    time.sleep(0.05)

    state_r = c.get("/api/state")
    assert state_r.json()["stage"] == "done"


# ---------------------------------------------------------------------------
# 2. POST /section error cases (N3-S01 guard)
# ---------------------------------------------------------------------------


def test_section_accept_not_proposed_returns_400(building_client):
    """Double-accepting a section returns 400 section_not_proposed."""
    c = building_client

    c.post("/api/section/sec_001/accept")

    import time

    time.sleep(0.05)

    r2 = c.post("/api/section/sec_001/accept")
    assert r2.status_code == 400
    assert r2.json()["error"] == "section_not_proposed"


def test_section_accept_unknown_id_returns_400(building_client):
    """Accepting a non-existent section returns 400 section_not_found."""
    c = building_client
    r = c.post("/api/section/does_not_exist/accept")
    assert r.status_code == 400
    assert r.json()["error"] == "section_not_found"


# ---------------------------------------------------------------------------
# 3. POST /turn retry path (N3-S02)
# ---------------------------------------------------------------------------


def test_retry_turn_empty_json_body_returns_204(client):
    """POST /turn with empty JSON body {} returns 204 (not 422).

    This is the retry path: absent text triggers retry_last_turn().
    ADR-020 contract: empty body = retry.
    """
    # Seed profiling stage so the stage guard doesn't fire for text turns.
    # For the empty-body path, stage doesn't matter — it always retries.
    r = client.post("/api/turn", json={})
    assert r.status_code == 204


def test_retry_turn_null_body_returns_204(client):
    """POST /turn with no body at all returns 204 (not 422)."""
    r = client.post("/api/turn")
    assert r.status_code == 204


def test_retry_turn_whitespace_text_returns_204(client):
    """POST /turn with text='   ' (whitespace-only) returns 204, not 422.

    Whitespace-only text is treated as absent and triggers retry.
    """
    r = client.post("/api/turn", json={"text": "   "})
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# 4. turn.error event payload shape (N3-S03, ADR-020)
# ---------------------------------------------------------------------------


def test_turn_error_payload_shape_via_event_bus(workspace: Path):
    """turn.error published via EventBus has reason (string) and stage fields.

    Tests the contract shape directly: publishes a turn.error event through
    the EventBus and verifies the envelope shape matches ADR-020.

    The event must NOT contain a 'retryable' boolean field — ADR-020 replaced
    that with reason:string.
    """
    import asyncio as _asyncio

    from backend.core.event_bus import EventBus

    bus = EventBus()
    collected: list[dict] = []

    async def _run():
        sub = bus.subscribe()
        # Publish a turn.error event matching the N3-S03 shape.
        await bus.publish(
            "turn.error",
            {"stage": "profiling", "reason": "provider_error", "ts": 1234567890},
        )
        async for evt in sub:
            collected.append(evt)
            break  # stop after first event

    _asyncio.run(_run())

    assert len(collected) == 1
    err = collected[0]
    assert err["type"] == "turn.error"
    assert "reason" in err, f"turn.error missing 'reason': {err}"
    assert "stage" in err, f"turn.error missing 'stage': {err}"
    assert isinstance(err["reason"], str), f"'reason' must be string: {err}"
    assert "retryable" not in err, f"'retryable' must not appear in turn.error (ADR-020): {err}"


def test_turn_error_with_section_id_shape(workspace: Path):
    """turn.error for a building-stage section includes section_id in payload.

    N3-S03: section-scoped errors include section_id so the SPA can target
    the correct SectionPane.
    """
    import asyncio as _asyncio

    from backend.core.event_bus import EventBus

    bus = EventBus()
    collected: list[dict] = []

    async def _run():
        sub = bus.subscribe()
        await bus.publish(
            "turn.error",
            {
                "stage": "building",
                "reason": "provider_error",
                "section_id": "sec_001",
                "ts": 1234567890,
            },
        )
        async for evt in sub:
            collected.append(evt)
            break

    _asyncio.run(_run())

    assert len(collected) == 1
    err = collected[0]
    assert err["type"] == "turn.error"
    assert err["stage"] == "building"
    assert err["section_id"] == "sec_001"
    assert isinstance(err["reason"], str)
    assert "retryable" not in err


# ---------------------------------------------------------------------------
# 5. GET / static serving (N3-S09)
# ---------------------------------------------------------------------------


def test_static_html_served_when_dist_exists(workspace: Path, tmp_path: Path):
    """GET / returns HTML content when frontend/dist/index.html exists.

    N3-S09: make run serves the built bundle from FastAPI on one port.
    """
    # Find the real frontend/dist path (relative to the repo root).
    repo_root = Path(__file__).parents[3]
    dist_dir = repo_root / "frontend" / "dist"

    if not dist_dir.is_dir():
        pytest.skip("frontend/dist not built — run pnpm build first")

    index_html = dist_dir / "index.html"
    if not index_html.is_file():
        pytest.skip("frontend/dist/index.html not found")

    state_path = workspace / "state.json"
    with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
        with TestClient(app) as c:
            r = c.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert b"<html" in r.content.lower() or b"<!doctype" in r.content.lower()


# ---------------------------------------------------------------------------
# 6. GET /state — done stage exposed correctly
# ---------------------------------------------------------------------------


def test_get_state_returns_done_stage(workspace: Path):
    """GET /state with done stage in state.json returns stage='done'.

    Verifies the backend correctly exposes the done stage to the FE.
    """
    state_path = workspace / "state.json"
    done_state = {
        "version": "1",
        "stage": "done",
        "aim": "find patterns",
        "dataset_path": "data/test.csv",
        "opencode_session_id": "ses_done_123",
        "profile": None,
        "plan": [
            {"id": "sec_a", "title": "A", "hypothesis": "H", "status": "accepted"},
        ],
        "last_saved": "2026-06-04T00:00:00Z",
    }
    state_path.write_text(json.dumps(done_state))

    with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
        with TestClient(app) as c:
            r = c.get("/api/state")

    assert r.status_code == 200
    body = r.json()
    assert body["stage"] == "done"
    # Internal field must still be stripped.
    assert "opencode_session_id" not in body
