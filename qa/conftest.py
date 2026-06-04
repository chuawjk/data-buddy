"""QA suite conftest.

Sets up sys.path so that 'backend' is importable when running
``pytest qa/`` from the repo root (outside the backend/ uv project).

Provides a module-scoped app fixture that starts the FastAPI backend (and
OpenCode) once per test module and shares it across all tests in that module.
This means OpenCode launches twice across the whole ``pytest qa`` run (once
for each structural test module) instead of once per test function — cutting
the ~10 s startup penalty from O(n_tests) to O(n_modules).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add backend/ to sys.path so `import backend` works.
_BACKEND_DIR = Path(__file__).parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


@pytest.fixture(scope="module")
def qa_app(tmp_path_factory):
    """Module-scoped TestClient with a live OpenCode connection.

    Starts the FastAPI backend (including OpenCode) once per test module.
    All tests in the same module that request this fixture share a single
    running backend instance.

    Yields ``(client, app, workspace)`` where ``workspace`` is a temporary
    directory the app's StateManager is configured to use.  Tests that need
    specific state should write to ``workspace / "state.json"`` and call
    ``app.state.state_manager.load()`` for per-test isolation.
    """
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend.core.state_manager import StateManager
    from backend.main import app

    workspace = tmp_path_factory.mktemp("qa_workspace")
    state_path = workspace / "state.json"
    with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
        with TestClient(app) as client:
            yield client, app, workspace
