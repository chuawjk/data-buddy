"""Unit tests for router.py — all 10 REST routes registered and returning typed stubs.

TDD: these were written before the implementation.
Acceptance criteria:
- All 10 routes are registered and return a typed stub (not 404/500).
- GET /state returns a minimal valid state object.
"""

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from backend.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# All 10 routes: assert no 404 or 5xx
# ---------------------------------------------------------------------------


def test_get_state(client):
    """GET /state responds 200 with the required top-level fields."""
    r = client.get("/state")
    assert r.status_code == 200
    body = r.json()
    assert "version" in body
    assert "stage" in body
    assert body["stage"] == "setup"
    assert "plan" in body
    assert "profile" in body


def test_post_setup(client):
    """POST /setup is registered and returns a valid stub (not 404/500)."""
    r = client.post(
        "/setup",
        data={"aim": "test aim"},
        files={"file": ("test.csv", b"col_a,col_b\n1,2\n", "text/csv")},
    )
    assert r.status_code not in (404, 500, 501, 502, 503)


@pytest.mark.asyncio
async def test_get_events_registered():
    """GET /events is registered, returns 200 text/event-stream with the correct headers.

    The real implementation (N1-S10) is an infinite SSE stream backed by the
    EventBus.  We use httpx.AsyncClient with ASGITransport to send the request
    asynchronously and cancel the stream after reading the response headers.
    This avoids blocking on the infinite generator.

    We assert:
    - Status 200 (not 404 or 5xx).
    - Content-Type includes ``text/event-stream``.
    - ``Cache-Control: no-cache`` is set (contract requirement).
    - ``X-Accel-Buffering: no`` is set (contract requirement).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        async with ac.stream("GET", "/events") as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            assert r.headers.get("cache-control") == "no-cache"
            assert r.headers.get("x-accel-buffering") == "no"


def test_post_turn(client):
    """POST /turn is registered and returns a non-error stub."""
    r = client.post("/turn", json={"text": "hello"})
    assert r.status_code not in (404, 500, 501, 502, 503)


def test_post_plan_update(client):
    """POST /plan/update is registered and returns a non-error stub."""
    r = client.post("/plan/update", json={"sections": []})
    assert r.status_code not in (404, 500, 501, 502, 503)


def test_post_plan_accept(client):
    """POST /plan/accept is registered and returns a non-error stub."""
    r = client.post("/plan/accept")
    assert r.status_code not in (404, 500, 501, 502, 503)


def test_post_section_accept(client):
    """POST /section/{id}/accept is registered."""
    r = client.post("/section/sec_01/accept")
    assert r.status_code not in (404, 500, 501, 502, 503)


def test_post_section_drop(client):
    """POST /section/{id}/drop is registered."""
    r = client.post("/section/sec_01/drop")
    assert r.status_code not in (404, 500, 501, 502, 503)


def test_get_export(client):
    """GET /export is registered and returns a non-error stub."""
    r = client.get("/export")
    assert r.status_code not in (404, 500, 501, 502, 503)


def test_get_file(client):
    """GET /file is registered and returns a contract-compliant response.

    The stub returns 404 with a ``missing_file`` error envelope — that is a
    valid contract response for a file that does not exist.  The important
    check here is that the route is registered (no routing-level 404) and that
    it does not 5xx.  We verify by checking status < 500 and by inspecting the
    error envelope shape.
    """
    r = client.get("/file", params={"path": "data/test.csv"})
    assert r.status_code < 500
    if r.status_code == 404:
        body = r.json()
        assert body.get("error") == "missing_file"
