"""Unit tests for router.py -- all 10 REST routes registered and returning typed stubs.

TDD: these were written before the implementation.
Acceptance criteria:
- All 10 routes are registered and return a typed stub (not 404/500).
- GET /state returns a minimal valid state object.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from backend.api.router import get_events
from backend.core.state_manager import StateManager
from backend.main import app


@pytest.fixture()
def client(tmp_path: Path):
    # Isolate from the real workspace/state.json so tests are not affected by
    # state left on disk from a prior live run (QA-01/QA-02 regression fix).
    # Patch StateManager's default path to a fresh temp directory so the
    # lifespan StateManager.load() sees no prior state.
    clean_state_path = tmp_path / "state.json"
    with patch("backend.main.StateManager", lambda: StateManager(path=clean_state_path)):
        # Use the context-manager form so the lifespan runs (EventBus +
        # StateManager are initialised on app.state before requests are sent).
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# All 10 routes: assert no 404 or 5xx
# ---------------------------------------------------------------------------


def test_get_state(client):
    """GET /state responds 200 with the required top-level fields."""
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    # Must include the mandatory fields from the contract.
    assert "version" in body
    assert "stage" in body
    assert body["stage"] == "setup"
    assert "plan" in body
    # profile may be null at setup stage -- just check key presence.
    assert "profile" in body


def test_post_setup(client):
    """POST /setup is registered and returns a valid stub (not 404/500)."""
    # Stub: send minimal multipart; handler is not yet real so a stub response is acceptable.
    r = client.post(
        "/api/setup",
        data={"aim": "test aim"},
        files={"file": ("test.csv", b"col_a,col_b\n1,2\n", "text/csv")},
    )
    # Accept 200 (stub ok) or 422 (validation) but never 404 or 5xx.
    assert r.status_code not in (404, 500, 501, 502, 503)


@pytest.mark.asyncio
async def test_get_events_registered(client):
    """GET /events route returns StreamingResponse with the correct SSE headers.

    Calls the route handler directly with a mocked request so we can inspect
    the returned StreamingResponse metadata without consuming the infinite
    stream body.  The client fixture ensures app.state.bus is initialised
    via the lifespan before this test runs.

    We assert:
    - The handler returns a StreamingResponse (route is registered and wired).
    - media_type is ``text/event-stream``.
    - ``Cache-Control: no-cache`` is set (contract requirement).
    - ``X-Accel-Buffering: no`` is set (contract requirement).

    TDD deviation note: direct handler invocation instead of HTTP-level
    streaming -- necessary because TestClient.stream() blocks forever on an
    infinite SSE generator and ASGITransport does not support client-side
    stream cancellation.  Documented per CONTRIBUTING §3.
    """
    mock_request = MagicMock()
    mock_request.app.state.bus = client.app.state.bus

    response = await get_events(mock_request)

    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"
    assert response.headers.get("cache-control") == "no-cache"
    assert response.headers.get("x-accel-buffering") == "no"


def test_post_turn(client):
    """POST /turn is registered and returns a non-error stub."""
    r = client.post("/api/turn", json={"text": "hello"})
    assert r.status_code not in (404, 500, 501, 502, 503)


def test_post_plan_update(client):
    """POST /plan/update is registered and returns a non-error stub."""
    r = client.post("/api/plan/update", json={"sections": []})
    assert r.status_code not in (404, 500, 501, 502, 503)


def test_post_plan_accept(client):
    """POST /plan/accept is registered and returns a non-error stub."""
    r = client.post("/api/plan/accept")
    assert r.status_code not in (404, 500, 501, 502, 503)


def test_post_section_accept(client):
    """POST /section/{id}/accept is registered."""
    r = client.post("/api/section/sec_01/accept")
    assert r.status_code not in (404, 500, 501, 502, 503)


def test_post_section_drop(client):
    """POST /section/{id}/drop is registered."""
    r = client.post("/api/section/sec_01/drop")
    assert r.status_code not in (404, 500, 501, 502, 503)


def test_get_export(client):
    """GET /export is registered and returns a non-error stub."""
    r = client.get("/api/export")
    assert r.status_code not in (404, 500, 501, 502, 503)


def test_get_file(client):
    """GET /file is registered and returns a contract-compliant response.

    The stub returns 404 with a ``missing_file`` error envelope -- that is a
    valid contract response for a file that does not exist.  The important
    check here is that the route is registered (no routing-level 404) and that
    it does not 5xx.  We verify by checking status < 500 and by inspecting the
    error envelope shape.
    """
    r = client.get("/api/file", params={"path": "data/test.csv"})
    # Route must be registered: no 5xx from an unregistered route.
    assert r.status_code < 500
    # Contract allows 404 with error envelope for missing files.
    if r.status_code == 404:
        body = r.json()
        assert body.get("error") == "missing_file"
