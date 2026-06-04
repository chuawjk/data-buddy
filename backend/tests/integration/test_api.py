"""Integration tests: full HTTP request/response cycles with real file I/O.

Unlike the unit tests (which only assert "not 404/5xx"), these tests verify
actual behaviour: files land on disk, state is persisted correctly, error
envelopes match the contract, and stage-routing works.

OpenCode is skipped via SKIP_OPENCODE=1 (set in conftest.py).
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
# Shared fixture data
# ---------------------------------------------------------------------------

_CSV = b"col_a,col_b\n1,2\n3,4\n"


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


# ---------------------------------------------------------------------------
# 1. POST /setup — happy path: file written + state persisted
# ---------------------------------------------------------------------------


def test_setup_writes_csv_to_workspace(client, workspace):
    """Uploaded CSV must be written to workspace/data/<filename>."""
    r = client.post(
        "/setup",
        data={"aim": "find patterns"},
        files={"csv": ("customers.csv", _CSV, "text/csv")},
    )
    assert r.status_code == 204

    csv_path = workspace / "data" / "customers.csv"
    assert csv_path.exists()
    assert csv_path.read_bytes() == _CSV


def test_setup_persists_state_to_disk(client, workspace):
    """POST /setup must write dataset_path and aim to state.json on disk."""
    client.post(
        "/setup",
        data={"aim": "find patterns"},
        files={"csv": ("customers.csv", _CSV, "text/csv")},
    )

    state_path = workspace / "state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["aim"] == "find patterns"
    assert state["dataset_path"] == "data/customers.csv"


def test_get_state_reflects_upload(client):
    """GET /state after POST /setup must return aim and dataset_path."""
    client.post(
        "/setup",
        data={"aim": "find patterns"},
        files={"csv": ("customers.csv", _CSV, "text/csv")},
    )

    r = client.get("/state")
    assert r.status_code == 200
    body = r.json()
    assert body["aim"] == "find patterns"
    assert body["dataset_path"] == "data/customers.csv"


def test_get_state_strips_internal_field(client):
    """GET /state must never expose opencode_session_id to the SPA."""
    r = client.get("/state")
    assert r.status_code == 200
    assert "opencode_session_id" not in r.json()


# ---------------------------------------------------------------------------
# 2. POST /setup — error envelopes (contract §4)
# ---------------------------------------------------------------------------


def test_setup_rejects_empty_aim(client):
    r = client.post(
        "/setup",
        data={"aim": "   "},
        files={"csv": ("data.csv", _CSV, "text/csv")},
    )
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_aim"


def test_setup_rejects_non_csv_content_type(client):
    r = client.post(
        "/setup",
        data={"aim": "find patterns"},
        files={"csv": ("data.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_file"


def test_setup_rejects_oversized_file(client):
    big = b"x" * (10 * 1024 * 1024 + 1)
    r = client.post(
        "/setup",
        data={"aim": "find patterns"},
        files={"csv": ("big.csv", big, "text/csv")},
    )
    assert r.status_code == 413
    assert r.json()["error"] == "file_too_large"


# ---------------------------------------------------------------------------
# 3. State persistence across app restarts
# ---------------------------------------------------------------------------


def test_state_loaded_from_disk_on_startup(tmp_path):
    """State written by a prior session is visible to a new app instance."""
    state_path = tmp_path / "state.json"
    prior_state = {
        "version": "1",
        "stage": "profiling",
        "aim": "predict churn",
        "dataset_path": "data/churn.csv",
        "last_saved": "2026-06-02T10:00:00Z",
        "opencode_session_id": "ses_abc123",
        "profile": None,
        "plan": [],
    }
    state_path.write_text(json.dumps(prior_state))

    with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
        with TestClient(app) as c:
            r = c.get("/state")

    assert r.status_code == 200
    body = r.json()
    assert body["stage"] == "profiling"
    assert body["aim"] == "predict churn"
    assert body["dataset_path"] == "data/churn.csv"
    assert "opencode_session_id" not in body


# ---------------------------------------------------------------------------
# 4. POST /turn — stage routing and validation
# ---------------------------------------------------------------------------


def test_turn_empty_text_triggers_retry(client):
    """POST /turn with whitespace-only or absent text triggers retry (N3-S02).

    Empty/absent text now calls retry_last_turn() instead of returning 422.
    Returns 204; retry logs a warning when there is no prior turn.
    """
    r = client.post("/turn", json={"text": "   "})
    assert r.status_code == 204


def test_turn_missing_text_field_triggers_retry(client):
    """POST /turn with no text field triggers retry (N3-S02)."""
    r = client.post("/turn", json={})
    assert r.status_code == 204


def test_turn_rejected_in_setup_stage(client):
    """POST /turn is not valid in the default setup stage."""
    r = client.post("/turn", json={"text": "look at the age column"})
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_stage"


def test_turn_accepted_in_profiling_stage(client):
    """POST /turn returns 204 when stage is profiling."""
    client.app.state.state_manager.update(stage="profiling")

    r = client.post("/turn", json={"text": "look at the age column"})
    assert r.status_code == 204
