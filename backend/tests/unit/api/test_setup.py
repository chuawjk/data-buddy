"""Unit tests for POST /setup endpoint -- N1-S05.

TDD: tests written before the implementation.

Acceptance criteria covered:
- Given a valid CSV + aim, when POST /setup is called, then workspace/data/<dataset>.csv
  and an initial state.json at stage "setup" are created.
- Given a non-CSV or oversize upload, when POST /setup is called, then the contract error
  envelope is returned.
- Given a successful setup, when it completes, then the orchestrator's setup->profiling
  path is triggered.
- Given an empty aim, when POST /setup is called, then 422 is returned.
- Given a file larger than 10 MB, when POST /setup is called, then 413 is returned.
"""

from __future__ import annotations

import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.router import router
from backend.core.event_bus import EventBus
from backend.core.orchestrator import Orchestrator
from backend.core.state_manager import StateManager

# ---------------------------------------------------------------------------
# Test app factory -- uses tmp_path to isolate workspace/ from the real fs.
# ---------------------------------------------------------------------------


def _make_app(tmp_path: Path) -> FastAPI:
    """Return a fresh FastAPI app wired with test-isolated state + orchestrator."""

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        app.state.bus = EventBus()
        app.state.state_manager = StateManager(path=tmp_path / "state.json")
        app.state.state_manager.load()
        app.state.orchestrator = Orchestrator(
            state_manager=app.state.state_manager,
            bus=app.state.bus,
            workspace_root=tmp_path,
        )
        yield

    test_app = FastAPI(lifespan=_lifespan)
    test_app.include_router(router)
    return test_app


# ---------------------------------------------------------------------------
# test_valid_csv_creates_files
# ---------------------------------------------------------------------------


def test_valid_csv_creates_files(tmp_path):
    """POST /setup with a valid CSV + aim creates the workspace file and state.json.

    The state stage starts at "setup" and may advance to "profiling" once the
    orchestrator's setup_complete task runs.  We verify the invariants that
    matter: the CSV file was written and state.json has the correct dataset_path
    and aim.
    """
    app = _make_app(tmp_path)
    csv_content = b"col_a,col_b\n1,2\n3,4\n"

    with TestClient(app) as client:
        r = client.post(
            "/setup",
            data={"aim": "Understand churn drivers"},
            files={"csv": ("customers.csv", io.BytesIO(csv_content), "text/csv")},
        )

    assert r.status_code == 204, f"Expected 204, got {r.status_code}: {r.text}"

    # Workspace data file must exist.
    data_file = tmp_path / "data" / "customers.csv"
    assert data_file.exists(), "workspace/data/customers.csv was not created"
    assert data_file.read_bytes() == csv_content

    # state.json must exist with correct dataset_path and aim.
    # Stage may be "setup" or "profiling" depending on whether the orchestrator
    # fire-and-forget task has completed.
    state_file = tmp_path / "state.json"
    assert state_file.exists(), "state.json was not created"
    state = json.loads(state_file.read_text())
    assert state["dataset_path"] == "data/customers.csv"
    assert state["aim"] == "Understand churn drivers"
    assert state["stage"] in ("setup", "profiling"), f"Unexpected stage: {state['stage']}"


# ---------------------------------------------------------------------------
# test_invalid_content_type_rejected
# ---------------------------------------------------------------------------


def test_invalid_content_type_rejected(tmp_path):
    """POST /setup with a non-CSV file returns 422 with the error envelope."""
    app = _make_app(tmp_path)

    with TestClient(app) as client:
        r = client.post(
            "/setup",
            data={"aim": "some aim"},
            files={"csv": ("report.txt", io.BytesIO(b"not a csv"), "text/plain")},
        )

    assert r.status_code == 422, f"Expected 422, got {r.status_code}"
    body = r.json()
    assert body.get("error") == "invalid_file"
    assert "message" in body


# ---------------------------------------------------------------------------
# test_empty_aim_rejected
# ---------------------------------------------------------------------------


def test_empty_aim_rejected(tmp_path):
    """POST /setup with a whitespace-only aim returns 422 with the error envelope.

    FastAPI passes whitespace-only form strings through to the handler, where
    our strip-and-check logic catches it and returns the custom error envelope.
    """
    app = _make_app(tmp_path)

    with TestClient(app) as client:
        r = client.post(
            "/setup",
            data={"aim": "   "},  # whitespace-only -- fails our strip+check
            files={"csv": ("data.csv", io.BytesIO(b"col_a\n1\n"), "text/csv")},
        )

    assert r.status_code == 422, f"Expected 422, got {r.status_code}"
    body = r.json()
    assert body.get("error") == "invalid_aim"
    assert "message" in body


# ---------------------------------------------------------------------------
# test_orchestrator_called
# ---------------------------------------------------------------------------


def test_orchestrator_called(tmp_path):
    """POST /setup calls orchestrator.setup_complete with the correct args."""
    app = _make_app(tmp_path)
    csv_content = b"a,b\n1,2\n"

    # Patch the orchestrator's setup_complete method before the request.
    with TestClient(app) as client:
        orchestrator = app.state.orchestrator
        orchestrator.setup_complete = AsyncMock()

        r = client.post(
            "/setup",
            data={"aim": "Test aim"},
            files={"csv": ("test.csv", io.BytesIO(csv_content), "text/csv")},
        )

    assert r.status_code == 204
    orchestrator.setup_complete.assert_awaited_once_with(dataset="test.csv", aim="Test aim")


# ---------------------------------------------------------------------------
# test_file_too_large
# ---------------------------------------------------------------------------


def test_file_too_large(tmp_path):
    """POST /setup with a file larger than 10 MB returns 413."""
    app = _make_app(tmp_path)

    # 10 MB + 1 byte exceeds the limit.
    oversized = b"x" * (10 * 1024 * 1024 + 1)

    with TestClient(app) as client:
        r = client.post(
            "/setup",
            data={"aim": "some aim"},
            files={"csv": ("big.csv", io.BytesIO(oversized), "text/csv")},
        )

    assert r.status_code == 413, f"Expected 413, got {r.status_code}"
    body = r.json()
    assert body.get("error") == "file_too_large"
    assert "message" in body
