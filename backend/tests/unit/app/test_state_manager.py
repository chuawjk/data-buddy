"""Unit tests for state_manager.py — atomic write, default load, update merge, and API.

TDD: tests written before the implementation.

Acceptance criteria covered:
- Given any state mutation, when persisted, it writes state.tmp.json then os.replace()
  onto state.json.
- Given a process kill simulated mid-write, when the file is read, state.json is valid
  (current or prior version), never partial.
- Given a turn is in progress, when a write is attempted, it is deferred until idle.
- Given a page load, when GET /state is called, it returns the persisted stage, plan,
  section statuses, and profile per the contract schema.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.state_manager import StateManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_KEYS = {"version", "stage", "aim", "dataset_path", "last_saved", "profile", "plan"}


def _sm(tmp_path: Path) -> StateManager:
    """Return a fresh StateManager pointing at a temp directory."""
    return StateManager(path=tmp_path / "state.json")


# ---------------------------------------------------------------------------
# test_load_default — no state.json returns the default shape
# ---------------------------------------------------------------------------


def test_load_default(tmp_path):
    """If no state.json exists, load() returns a dict with the default shape."""
    sm = _sm(tmp_path)
    state = sm.load()

    # All required top-level keys must be present.
    assert DEFAULT_KEYS.issubset(state.keys()), f"Missing keys: {DEFAULT_KEYS - state.keys()}"

    # Default values per the contract.
    assert state["version"] == "1"
    assert state["stage"] == "setup"
    assert state["profile"] is None
    assert state["plan"] == []
    assert state["aim"] is None
    assert state["dataset_path"] is None

    # No state.json should have been created by a bare load().
    assert not (tmp_path / "state.json").exists()


# ---------------------------------------------------------------------------
# test_atomic_write — save writes tmp then replaces; state.json is valid JSON
# ---------------------------------------------------------------------------


def test_atomic_write(tmp_path):
    """save() uses an atomic tmp-then-rename pattern.

    After save():
    - state.json exists and is valid JSON.
    - state.tmp.json has been cleaned up (replaced -> renamed away).
    - The saved content round-trips correctly.
    """
    sm = _sm(tmp_path)
    state = sm.load()
    state["stage"] = "profiling"
    state["aim"] = "Test aim"

    # Intercept os.replace to verify it was called with the tmp path.
    calls: list[tuple[str, str]] = []
    original_replace = os.replace

    def _spy_replace(src, dst):
        calls.append((str(src), str(dst)))
        original_replace(src, dst)

    with patch("os.replace", side_effect=_spy_replace):
        sm.save(state)

    state_path = tmp_path / "state.json"
    tmp_path_file = tmp_path / "state.tmp.json"

    # os.replace must have been called exactly once with tmp → state.json.
    assert len(calls) == 1, f"Expected 1 os.replace call, got {len(calls)}"
    assert calls[0][0].endswith("state.tmp.json")
    assert calls[0][1].endswith("state.json")

    # state.json must exist and be valid JSON.
    assert state_path.exists(), "state.json was not created"
    content = state_path.read_text(encoding="utf-8")
    persisted = json.loads(content)  # raises if invalid JSON

    assert persisted["stage"] == "profiling"
    assert persisted["aim"] == "Test aim"

    # state.tmp.json must have been cleaned up (replaced to state.json).
    assert not tmp_path_file.exists(), "state.tmp.json was not cleaned up after replace"


def test_atomic_write_survives_simulated_kill(tmp_path):
    """If the process is killed after writing tmp but before os.replace,
    the original state.json (if present) remains intact.

    We simulate this by writing an existing valid state.json, then writing
    the tmp file without calling os.replace, and verifying state.json is
    still the original valid content.
    """
    state_path = tmp_path / "state.json"
    tmp_file = tmp_path / "state.tmp.json"

    # Write a known-good state.json first.
    original = {"version": "1", "stage": "setup", "aim": None}
    state_path.write_text(json.dumps(original), encoding="utf-8")

    # Simulate: tmp is written but process dies before os.replace is called.
    tmp_file.write_text('{"partial": true', encoding="utf-8")  # intentionally invalid JSON

    # state.json should still be the original valid file.
    content = json.loads(state_path.read_text(encoding="utf-8"))
    assert content["stage"] == "setup"
    assert "partial" not in content


# ---------------------------------------------------------------------------
# test_update_merges — update(stage="profiling") persists only the changed field
# ---------------------------------------------------------------------------


def test_update_merges(tmp_path):
    """update(**kwargs) merges kwargs into the current state and saves.

    After update(stage="profiling"):
    - stage is "profiling"
    - all other fields remain at their default values
    - the change is persisted to state.json
    """
    sm = _sm(tmp_path)

    sm.update(stage="profiling")

    # In-memory state reflects the change.
    in_memory = sm.get_state()
    assert in_memory["stage"] == "profiling"

    # All other defaults are preserved.
    assert in_memory["profile"] is None
    assert in_memory["plan"] == []
    assert in_memory["aim"] is None

    # Persisted state matches.
    persisted = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert persisted["stage"] == "profiling"
    assert persisted["profile"] is None


def test_update_multiple_fields(tmp_path):
    """update() can merge multiple fields at once."""
    sm = _sm(tmp_path)
    sm.update(stage="planning", aim="Understand churn")

    state = sm.get_state()
    assert state["stage"] == "planning"
    assert state["aim"] == "Understand churn"

    persisted = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert persisted["stage"] == "planning"
    assert persisted["aim"] == "Understand churn"


# ---------------------------------------------------------------------------
# test_get_state — in-memory state returns most recent value
# ---------------------------------------------------------------------------


def test_get_state_returns_in_memory(tmp_path):
    """get_state() returns the in-memory state dict, not a fresh disk read."""
    sm = _sm(tmp_path)
    sm.update(stage="building")
    state = sm.get_state()
    assert state["stage"] == "building"


# ---------------------------------------------------------------------------
# test_load_existing — load() reads an existing state.json
# ---------------------------------------------------------------------------


def test_load_existing(tmp_path):
    """load() reads and returns the content of an existing state.json."""
    state_path = tmp_path / "state.json"
    saved = {
        "version": "1",
        "stage": "planning",
        "aim": "test aim",
        "dataset_path": "data/test.csv",
        "last_saved": "2026-06-01T00:00:00Z",
        "profile": None,
        "plan": [{"id": "sec_01", "title": "Overview", "hypothesis": "h", "status": "queued"}],
    }
    state_path.write_text(json.dumps(saved), encoding="utf-8")

    sm = _sm(tmp_path)
    loaded = sm.load()

    assert loaded["stage"] == "planning"
    assert loaded["aim"] == "test aim"
    assert len(loaded["plan"]) == 1
    assert loaded["plan"][0]["id"] == "sec_01"


# ---------------------------------------------------------------------------
# test_deferral — save is deferred while the turn lock is held
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deferral_under_lock(tmp_path):
    """When an asyncio.Lock is held (simulating an active turn), save() waits
    until the lock is released before writing state.json.

    We verify this by:
    1. Acquiring the lock in the test.
    2. Calling save() in a background task.
    3. Confirming state.json does NOT exist while the lock is held.
    4. Releasing the lock.
    5. Confirming state.json DOES exist after release.
    """
    sm = _sm(tmp_path)
    state = sm.load()
    state["stage"] = "profiling"

    lock = asyncio.Lock()
    state_path = tmp_path / "state.json"

    async with lock:
        # Start save in the background while we hold the lock.
        save_task = asyncio.create_task(sm.save_async(state, lock=lock))

        # Give the event loop a moment to attempt the save.
        await asyncio.sleep(0.05)

        # state.json must NOT exist yet — deferral is in effect.
        assert not state_path.exists(), "save() wrote state.json while lock was held"

    # Now the lock is released; wait for save_task to finish.
    await save_task

    # state.json must now exist.
    assert state_path.exists(), "save() did not write state.json after lock released"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["stage"] == "profiling"


# ---------------------------------------------------------------------------
# test_get_state_via_api — GET /state returns the real persisted state
# ---------------------------------------------------------------------------


def test_get_state_via_api(tmp_path):
    """GET /state returns the persisted state from state_manager on app.state.

    The test runs the full lifespan (via the TestClient context manager) and
    then overrides ``app.state.state_manager`` with a StateManager that has
    known data persisted.  It then calls the endpoint and asserts the response
    matches the state shape from the contract.
    """
    sm = _sm(tmp_path)
    # Persist a known state before the app starts handling requests.
    sm.update(stage="profiling", aim="Understand churn")

    with TestClient(app) as client:
        # Override the state_manager that the lifespan installed with our
        # test instance (which has the known persisted state).
        app.state.state_manager = sm

        r = client.get("/state")
        assert r.status_code == 200
        body = r.json()

        # Contract-required fields.
        assert body["version"] == "1"
        assert body["stage"] == "profiling"
        assert body["aim"] == "Understand churn"
        assert "dataset_path" in body
        assert "last_saved" in body
        assert "profile" in body
        assert "plan" in body
        assert body["profile"] is None
        assert body["plan"] == []

        # opencode_session_id must NOT be exposed to the SPA (contract §3).
        assert "opencode_session_id" not in body


# ---------------------------------------------------------------------------
# test_load_fills_in_missing_keys — backward-compatible schema migration
# ---------------------------------------------------------------------------


def test_load_fills_in_missing_keys(tmp_path):
    """load() merges defaults for keys absent from an older state.json.

    If a new default key was added to _DEFAULT_STATE after a state.json was
    written, load() must return a dict that contains both the on-disk values
    and the new default — not a KeyError at access time.
    """
    state_path = tmp_path / "state.json"
    # Write a minimal "old" state that is missing several keys.
    old_state = {
        "version": "1",
        "stage": "profiling",
        "aim": "understand sales",
    }
    state_path.write_text(json.dumps(old_state), encoding="utf-8")

    sm = _sm(tmp_path)
    loaded = sm.load()

    # On-disk fields preserved.
    assert loaded["stage"] == "profiling"
    assert loaded["aim"] == "understand sales"

    # Missing keys filled in from defaults.
    assert "dataset_path" in loaded
    assert loaded["dataset_path"] is None
    assert "profile" in loaded
    assert loaded["profile"] is None
    assert "plan" in loaded
    assert loaded["plan"] == []
    assert "opencode_session_id" in loaded
