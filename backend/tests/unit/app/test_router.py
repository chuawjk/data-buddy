"""Unit tests for router.py — all 10 REST routes registered and returning typed stubs.

TDD: these were written before the implementation.
Acceptance criteria:
- All 10 routes are registered and return a typed stub (not 404/500).
- GET /state returns a minimal valid state object.
"""

import threading

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture()
def client():
    # Use the context-manager form so the lifespan runs (EventBus +
    # StateManager are initialised on app.state before requests are sent).
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
    """GET /events is registered, returns 200 text/event-stream with the correct headers.

    The real implementation (N1-S10) is an infinite SSE stream backed by the
    EventBus.  TestClient's ASGI transport runs the generator synchronously so
    we cannot consume it directly without blocking forever.  Instead we run the
    stream in a daemon thread and join with a short timeout; the thread is
    interrupted by the daemon flag when the test exits.

    We assert:
    - Status 200 (not 404 or 5xx).
    - Content-Type includes ``text/event-stream``.
    - ``Cache-Control: no-cache`` is set (contract requirement).
    - ``X-Accel-Buffering: no`` is set (contract requirement).
    """
    result: dict = {}
    event = threading.Event()

    def _stream():
        try:
            with client.stream("GET", "/events") as r:
                result["status"] = r.status_code
                result["content_type"] = r.headers.get("content-type", "")
                result["cache_control"] = r.headers.get("cache-control", "")
                result["x_accel"] = r.headers.get("x-accel-buffering", "")
                event.set()
                # Block in the stream until the daemon thread is killed.
                for _ in r.iter_bytes():
                    pass
        except Exception as exc:
            result["error"] = str(exc)
            event.set()

    t = threading.Thread(target=_stream, daemon=True)
    t.start()

    # Wait up to 5 s for the response headers to arrive.
    assert event.wait(timeout=5), "GET /events did not respond within 5 s"

    assert "error" not in result, f"stream thread raised: {result.get('error')}"
    assert result["status"] == 200
    assert "text/event-stream" in result["content_type"]
    assert result["cache_control"] == "no-cache"
    assert result["x_accel"] == "no"


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
