"""Unit tests for router.py — all 10 REST routes registered and returning typed stubs.

TDD: these were written before the implementation.
Acceptance criteria:
- All 10 routes are registered and return a typed stub (not 404/500).
- GET /state returns a minimal valid state object.
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture()
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# All 10 routes: assert no 404 or 5xx
# ---------------------------------------------------------------------------


def test_get_state(client):
    """GET /state responds 200 with the required top-level fields."""
    r = client.get("/state")
    assert r.status_code == 200
    body = r.json()
    # Must include the mandatory fields from the contract.
    assert "version" in body
    assert "stage" in body
    assert body["stage"] == "setup"
    assert "plan" in body
    # profile may be null at setup stage — just check key presence.
    assert "profile" in body


def test_post_setup(client):
    """POST /setup is registered and returns a valid stub (not 404/500)."""
    # Stub: send minimal multipart; handler is not yet real so a stub response is acceptable.
    r = client.post(
        "/setup",
        data={"aim": "test aim"},
        files={"file": ("test.csv", b"col_a,col_b\n1,2\n", "text/csv")},
    )
    # Accept 200 (stub ok) or 422 (validation) but never 404 or 5xx.
    assert r.status_code not in (404, 500, 501, 502, 503)


def test_get_events_registered(client):
    """GET /events is registered (SSE stub — must not 404)."""
    # We cannot hold open an SSE stream in a unit test; just confirm the route exists.
    # stream=True avoids blocking on the streaming response.
    with client.stream("GET", "/events") as r:
        assert r.status_code != 404
        assert r.status_code < 500


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
    # Route must be registered: no 5xx from an unregistered route.
    assert r.status_code < 500
    # Contract allows 404 with error envelope for missing files.
    if r.status_code == 404:
        body = r.json()
        assert body.get("error") == "missing_file"
