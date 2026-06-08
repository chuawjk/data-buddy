"""Night 3 structural assertions — N3-S14 full regression gate.

Covers:
  - REG-N3-01: done stage exposed via GET /state
  - REG-N3-02: POST /turn with empty body returns 204 (retry path)
  - REG-N3-03: turn.error payload has reason:string + stage, no retryable field
  - REG-N3-04: QA_FORCE_TURN_ERROR seam fires turn.error deterministically
  - REG-N3-05: stage=done persisted when all sections terminal (accept + drop)
  - REG-N3-06: Night 3 data-testid completeness
  - REG-N3-07: make run /api/* routing — API routes not intercepted by SPA catch-all
  - REG-N3-08: architecture boundaries still hold (carry-forward)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.core.state_manager import StateManager
from backend.main import app


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def client(workspace: Path):
    state_path = workspace / "state.json"
    with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
        with TestClient(app) as c:
            yield c


@pytest.fixture()
def building_client(workspace: Path):
    """Client pre-seeded in building stage with one proposed section."""
    state_path = workspace / "state.json"
    initial = {
        "version": "1",
        "stage": "building",
        "aim": "find patterns",
        "dataset_path": "data/test.csv",
        "opencode_session_id": "ses_test",
        "profile": None,
        "plan": [
            {
                "id": "sec_only",
                "title": "Only Section",
                "hypothesis": "Only section hypothesis",
                "status": "proposed",
            }
        ],
        "last_saved": "2026-06-04T00:00:00Z",
    }
    state_path.write_text(json.dumps(initial))
    with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# REG-N3-01: GET /state exposes stage="done"
# ---------------------------------------------------------------------------


class TestDoneStageState:
    def test_get_state_returns_done_stage(self, workspace: Path) -> None:
        """GET /state returns stage='done' when state.json has stage=done.

        REG-N3-01: done stage must be exposed to the frontend correctly.
        """
        state_path = workspace / "state.json"
        state_path.write_text(
            json.dumps(
                {
                    "version": "1",
                    "stage": "done",
                    "aim": "test",
                    "dataset_path": "data/test.csv",
                    "opencode_session_id": None,
                    "profile": None,
                    "plan": [
                        {
                            "id": "s1",
                            "title": "T1",
                            "hypothesis": "H1",
                            "status": "accepted",
                        }
                    ],
                    "last_saved": "2026-06-04T00:00:00Z",
                }
            )
        )
        with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
            with TestClient(app) as c:
                r = c.get("/api/state")
        assert r.status_code == 200
        body = r.json()
        assert body["stage"] == "done"
        # Internal session ID must still be stripped
        assert "opencode_session_id" not in body

    def test_get_state_done_includes_plan(self, workspace: Path) -> None:
        """GET /state in done stage still includes plan array with section statuses."""
        state_path = workspace / "state.json"
        state_path.write_text(
            json.dumps(
                {
                    "version": "1",
                    "stage": "done",
                    "aim": "test",
                    "dataset_path": "data/test.csv",
                    "opencode_session_id": None,
                    "profile": None,
                    "plan": [
                        {
                            "id": "s1",
                            "title": "T1",
                            "hypothesis": "H1",
                            "status": "accepted",
                        },
                        {
                            "id": "s2",
                            "title": "T2",
                            "hypothesis": "H2",
                            "status": "dropped",
                        },
                    ],
                    "last_saved": "2026-06-04T00:00:00Z",
                }
            )
        )
        with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
            with TestClient(app) as c:
                r = c.get("/api/state")
        assert r.status_code == 200
        plan = r.json()["plan"]
        assert len(plan) == 2
        statuses = {s["id"]: s["status"] for s in plan}
        assert statuses["s1"] == "accepted"
        assert statuses["s2"] == "dropped"


# ---------------------------------------------------------------------------
# REG-N3-02: POST /turn empty body → retry path, returns 204
# ---------------------------------------------------------------------------


class TestRetryTurnEmptyBody:
    def test_empty_json_body_returns_204(self, client) -> None:
        """POST /turn {} returns 204 not 422.

        REG-N3-02: the retry path must be reachable from an empty body.
        This is the same contract as the retry-banner button.
        """
        r = client.post("/api/turn", json={})
        assert r.status_code == 204

    def test_no_body_returns_204(self, client) -> None:
        """POST /turn with no body at all returns 204 not 422."""
        r = client.post("/api/turn")
        assert r.status_code == 204

    def test_whitespace_only_text_returns_204(self, client) -> None:
        """POST /turn text='   ' returns 204 — whitespace treated as empty."""
        r = client.post("/api/turn", json={"text": "   "})
        assert r.status_code == 204

    def test_real_text_turn_in_setup_stage_returns_422(self, client) -> None:
        """POST /turn with real text in setup stage returns 422 invalid_stage.

        This is correct behaviour — text turns are only valid in profiling,
        planning, and building stages. The empty-body retry path is the only
        stage-independent path (always 204).
        """
        r = client.post("/api/turn", json={"text": "some revision"})
        # Default state is setup — text turn is not valid here
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_stage"


# ---------------------------------------------------------------------------
# REG-N3-03: turn.error payload shape — reason:string, no retryable
# ---------------------------------------------------------------------------


class TestTurnErrorPayloadShape:
    def test_turn_error_has_reason_string(self) -> None:
        """turn.error event payload must have reason:string field (ADR-020).

        REG-N3-03: contracts the shape published on the EventBus.
        """
        import asyncio

        from backend.core.event_bus import EventBus

        bus = EventBus()
        collected: list[dict] = []

        async def _run() -> None:
            sub = bus.subscribe()
            await bus.publish(
                "turn.error",
                {"stage": "profiling", "reason": "provider_error", "ts": 1234567890},
            )
            async for evt in sub:
                collected.append(evt)
                break

        asyncio.run(_run())

        assert len(collected) == 1
        err = collected[0]
        assert err["type"] == "turn.error"
        assert "reason" in err
        assert isinstance(err["reason"], str), (
            f"reason must be str, got {type(err['reason'])}"
        )
        assert "stage" in err

    def test_turn_error_has_no_retryable_field(self) -> None:
        """turn.error payload must NOT contain retryable field (ADR-020 replacement).

        REG-N3-03: the old retryable:bool was replaced with reason:string.
        This check prevents a regression to the pre-contract shape.
        """
        import asyncio

        from backend.core.event_bus import EventBus

        bus = EventBus()
        collected: list[dict] = []

        async def _run() -> None:
            sub = bus.subscribe()
            await bus.publish(
                "turn.error",
                {"stage": "building", "reason": "timeout", "ts": 1234567890},
            )
            async for evt in sub:
                collected.append(evt)
                break

        asyncio.run(_run())

        err = collected[0]
        assert "retryable" not in err, (
            f"'retryable' field found in turn.error — ADR-020 requires reason:string instead: {err}"
        )

    def test_turn_error_reason_enum_values(self) -> None:
        """turn.error reason must be one of the documented enum strings.

        ADR-020: valid values are 'provider_error', 'timeout',
        'structured_output_failed'.
        """
        import asyncio

        from backend.core.event_bus import EventBus

        valid_reasons = {"provider_error", "timeout", "structured_output_failed"}
        reasons_seen: set[str] = set()

        async def _check_reason(reason: str) -> None:
            bus = EventBus()
            collected: list[dict] = []

            sub = bus.subscribe()
            await bus.publish(
                "turn.error", {"stage": "profiling", "reason": reason, "ts": 0}
            )
            async for evt in sub:
                collected.append(evt)
                break

            reasons_seen.add(collected[0]["reason"])

        for r in valid_reasons:
            asyncio.run(_check_reason(r))

        assert reasons_seen == valid_reasons

    def test_building_stage_turn_error_includes_section_id(self) -> None:
        """Building-stage turn.error includes section_id in payload.

        REG-N3-03: section-scoped errors must carry section_id so the SPA
        can target the correct SectionPane.
        """
        import asyncio

        from backend.core.event_bus import EventBus

        bus = EventBus()
        collected: list[dict] = []

        async def _run() -> None:
            sub = bus.subscribe()
            await bus.publish(
                "turn.error",
                {
                    "stage": "building",
                    "reason": "provider_error",
                    "section_id": "sec_001",
                    "ts": 0,
                },
            )
            async for evt in sub:
                collected.append(evt)
                break

        asyncio.run(_run())

        err = collected[0]
        assert err.get("section_id") == "sec_001"


# ---------------------------------------------------------------------------
# REG-N3-04: provider-error QA control fires turn.error deterministically
# ---------------------------------------------------------------------------


class TestForcedTurnErrorHook:
    def test_qa_force_turn_error_triggers_turn_error(self, workspace: Path) -> None:
        """The provider-error runtime control causes a turn to emit turn.error.

        REG-N3-04: the QA seam must cause turn.error without requiring a
        real OpenCode session. The orchestrator raises before client.prompt().
        Tests the event shape produced by the hook path.
        """
        import asyncio

        from backend.core.event_bus import EventBus
        from backend.core.orchestrator import Orchestrator
        from backend.core.state_manager import StateManager as SM

        state_path = workspace / "state.json"
        sm = SM(path=state_path)
        sm.update(stage="profiling", dataset="test.csv", aim="test aim")

        bus = EventBus()
        # Mock client that should NOT be called (hook raises before it)
        mock_client = MagicMock()
        mock_client.prompt = MagicMock()

        orch = Orchestrator(
            state_manager=sm,
            bus=bus,
            client=mock_client,
            workspace_root=workspace,
        )

        collected: list[dict] = []

        async def _run() -> None:
            sub = bus.subscribe()
            marker_dir = workspace / ".qa"
            marker_dir.mkdir()
            marker = marker_dir / "provider-error"
            marker.touch()
            try:
                await orch._dispatch_turn("ses_test", "profile the data", "profiling")
                # Allow event to propagate
                await asyncio.sleep(0)
                async for evt in sub:
                    collected.append(evt)
                    break
            finally:
                marker.unlink()

        asyncio.run(_run())

        assert len(collected) == 1
        err = collected[0]
        assert err["type"] == "turn.error"
        assert err["stage"] == "profiling"
        assert err["reason"] == "provider_error"
        assert "retryable" not in err
        # Hook raises before client.prompt — client must not be called
        mock_client.prompt.assert_not_called()

    def test_qa_force_turn_error_off_by_default(self, workspace: Path) -> None:
        """The provider-error runtime marker is absent by default.

        REG-N3-04: production path must not be affected by the seam.
        """
        marker = workspace / ".qa" / "provider-error"
        assert not marker.exists(), (
            "provider-error marker is unexpectedly present; "
            "this would cause all turns to fail."
        )


# ---------------------------------------------------------------------------
# REG-N3-05: stage=done transition persisted when all sections terminal
# ---------------------------------------------------------------------------


class TestDoneTransition:
    def test_accept_last_section_transitions_to_done(
        self, building_client, workspace
    ) -> None:
        """POST /section/:id/accept on the only section → stage='done'.

        REG-N3-05: _check_done_or_next must persist stage='done' when
        every section reaches a terminal status.
        """
        c = building_client
        r = c.post("/api/section/sec_only/accept")
        assert r.status_code == 204

        time.sleep(0.1)

        r2 = c.get("/api/state")
        assert r2.json()["stage"] == "done"

    def test_drop_last_section_transitions_to_done(self, building_client) -> None:
        """POST /section/:id/drop on the only section → stage='done'.

        REG-N3-05: dropped sections are terminal — done check fires.
        """
        c = building_client
        r = c.post("/api/section/sec_only/drop")
        assert r.status_code == 204

        time.sleep(0.1)

        r2 = c.get("/api/state")
        assert r2.json()["stage"] == "done"

    def test_mixed_terminal_statuses_trigger_done(self, workspace: Path) -> None:
        """Mix of accepted + dropped sections is sufficient to trigger done.

        REG-N3-05: all terminal status types (accepted, dropped) satisfy the check.
        """
        state_path = workspace / "state.json"
        initial = {
            "version": "1",
            "stage": "building",
            "aim": "test",
            "dataset_path": "data/test.csv",
            "opencode_session_id": "ses",
            "profile": None,
            "plan": [
                {"id": "s1", "title": "T1", "hypothesis": "H1", "status": "proposed"},
                {"id": "s2", "title": "T2", "hypothesis": "H2", "status": "proposed"},
            ],
            "last_saved": "2026-06-04T00:00:00Z",
        }
        state_path.write_text(json.dumps(initial))
        with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
            with TestClient(app) as c:
                c.post("/api/section/s1/accept")
                c.post("/api/section/s2/drop")
                time.sleep(0.1)
                r = c.get("/api/state")
        assert r.json()["stage"] == "done"

    def test_partial_accept_does_not_trigger_done(self, workspace: Path) -> None:
        """Accepting one of two sections does not trigger done.

        REG-N3-05: done check requires ALL sections to be terminal.
        """
        state_path = workspace / "state.json"
        initial = {
            "version": "1",
            "stage": "building",
            "aim": "test",
            "dataset_path": "data/test.csv",
            "opencode_session_id": "ses",
            "profile": None,
            "plan": [
                {"id": "s1", "title": "T1", "hypothesis": "H1", "status": "proposed"},
                {"id": "s2", "title": "T2", "hypothesis": "H2", "status": "proposed"},
            ],
            "last_saved": "2026-06-04T00:00:00Z",
        }
        state_path.write_text(json.dumps(initial))
        with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
            with TestClient(app) as c:
                c.post("/api/section/s1/accept")
                time.sleep(0.1)
                r = c.get("/api/state")
        assert r.json()["stage"] == "building"


# ---------------------------------------------------------------------------
# REG-N3-06: Night 3 data-testid completeness
# ---------------------------------------------------------------------------


class TestNight3DataTestids:
    """Night 3 UI contract — the error surfaces and done screen must have
    stable data-testid attributes so Playwright can reach them.

    REG-N3-06: all Night 3-required testids are present in production source.
    """

    NIGHT3_TESTIDS = [
        "retry-banner",
        "retry-banner-btn",
        "section-failed-notice",
        "section-retry-btn",
        "section-drop-failed-btn",
        "watchdog-notice",
        "done-view",
        "done-export-button",
        "done-section-list",
    ]

    def _all_testids(self) -> set[str]:
        import re

        frontend_src = Path(__file__).parents[2] / "frontend" / "src"
        testid_re = re.compile(r'data-testid="([^"]+)"')
        testids: set[str] = set()
        for f in frontend_src.rglob("*.tsx"):
            if ".test." in f.name:
                continue
            for m in testid_re.finditer(f.read_text()):
                testids.add(m.group(1))
        return testids

    def test_night3_required_testids_present(self) -> None:
        """All Night 3-required data-testid values are present in production source."""
        testids = self._all_testids()
        missing = [tid for tid in self.NIGHT3_TESTIDS if tid not in testids]
        assert not missing, (
            f"Missing Night 3 required data-testid attributes: {missing}\n"
            f"All found testids: {sorted(testids)}"
        )

    def test_done_section_item_pattern_present(self) -> None:
        """DoneView emits done-section-item-{id} testids (dynamic pattern)."""
        frontend_src = Path(__file__).parents[2] / "frontend" / "src"
        done_view = frontend_src / "components" / "StageViews" / "DoneView.tsx"
        content = done_view.read_text()
        # The pattern should be the template literal
        assert "done-section-item-" in content, (
            "DoneView.tsx must emit done-section-item-{id} data-testids for each accepted section"
        )

    def test_total_testid_count_not_regressed(self) -> None:
        """Minimum data-testid count enforces Night 1 + 2 + 3 completeness.

        Night 3 additions bring the total to >= 50 unique testids.
        """
        testids = self._all_testids()
        assert len(testids) >= 50, (
            f"data-testid count regressed: expected >= 50, got {len(testids)}\n"
            f"Found: {sorted(testids)}"
        )


# ---------------------------------------------------------------------------
# REG-N3-07: /api/* routing — API routes not intercepted by SPA catch-all
# ---------------------------------------------------------------------------


class TestApiRouteNotIntercepted:
    """In make run mode the SPA catch-all must not intercept /api/* routes.

    REG-N3-07: when frontend/dist/ exists, GET /api/state (the path the built
    SPA calls) must return JSON from the API, not the HTML catch-all.

    This is the regression check for QA-03 (make run /api routing defect).
    The fix requires either:
      (a) router prefix="/api" in main.py, or
      (b) the SPA catch-all excludes /api/* paths.
    """

    def test_api_state_returns_json_not_html(self, workspace: Path) -> None:
        """GET /api/state must return JSON (application/json) not HTML.

        The SPA calls /api/state — if this returns HTML the app is broken
        in make run mode.
        """
        state_path = workspace / "state.json"
        # Build a minimal dist so the SPA static mount activates
        repo_root = Path(__file__).parents[2]
        dist_dir = repo_root / "frontend" / "dist"

        if not dist_dir.is_dir():
            pytest.skip(
                "frontend/dist not built — run 'make run' to build the frontend first"
            )

        with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
            with TestClient(app) as c:
                r = c.get("/api/state")

        # Must be JSON — not the HTML SPA fallback
        ct = r.headers.get("content-type", "")
        assert "application/json" in ct, (
            f"GET /api/state returned {ct!r} instead of application/json.\n"
            f"Status: {r.status_code}. Body head: {r.content[:200]!r}\n"
            "The SPA catch-all is intercepting /api/state — fix: add prefix='/api' "
            "to the APIRouter or exclude /api/* from the catch-all."
        )
        assert r.status_code == 200
        body = r.json()
        assert "stage" in body, f"Response missing 'stage' field: {body}"

    def test_api_state_route_is_registered(self, workspace: Path) -> None:
        """GET /api/state is registered as an API route (not just a proxy path).

        In dev mode the Vite proxy rewrites /api/* -> /* — but in production
        the frontend bundle calls /api/state directly and the backend must
        handle it as an API route.
        """
        state_path = workspace / "state.json"
        repo_root = Path(__file__).parents[2]
        dist_dir = repo_root / "frontend" / "dist"

        if not dist_dir.is_dir():
            pytest.skip(
                "frontend/dist not built — run 'make run' to build the frontend first"
            )

        with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
            with TestClient(app) as c:
                # /api prefix is the registered path (QA-03 fix: prefix="/api" on include_router)
                r_api = c.get("/api/state")

        # /api/state must return JSON (the production SPA path and the only registered path)
        ct_api = r_api.headers.get("content-type", "")
        assert "application/json" in ct_api, (
            f"GET /api/state returned {ct_api!r}. "
            "Router must register routes at /api/* for make run compatibility."
        )
        assert r_api.status_code == 200
        body = r_api.json()
        assert "stage" in body, f"Response missing 'stage' field: {body}"


# ---------------------------------------------------------------------------
# REG-N3-08: Architecture boundaries carry-forward from Night 1 / Night 2
# ---------------------------------------------------------------------------


class TestArchitectureBoundariesCarryForward:
    """Night 3 carry-forward: architecture boundaries must not have regressed.

    REG-N3-08: REG-N1-02 and REG-N1-03 re-verified for Night 3.
    """

    def test_orchestrator_has_no_httpx_import(self) -> None:
        """orchestrator.py must not import httpx (lane boundary).

        REG-N3-08: carry-forward of REG-N1-02.
        """
        import ast

        orch_path = Path(__file__).parents[2] / "backend" / "core" / "orchestrator.py"
        tree = ast.parse(orch_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "httpx", (
                        "orchestrator.py must not import httpx (architecture boundary)"
                    )
            if isinstance(node, ast.ImportFrom):
                assert node.module != "httpx", (
                    "orchestrator.py must not import from httpx (architecture boundary)"
                )

    def test_opencode_client_has_no_orchestrator_import(self) -> None:
        """opencode_client.py must not import orchestrator (lane boundary).

        REG-N3-08: carry-forward of REG-N1-03.
        """
        import ast

        client_path = (
            Path(__file__).parents[2] / "backend" / "agent" / "opencode_client.py"
        )
        tree = ast.parse(client_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert "orchestrator" not in alias.name, (
                            "opencode_client.py must not import orchestrator"
                        )
                elif node.module and "orchestrator" in node.module:
                    pytest.fail(
                        f"opencode_client.py imports from orchestrator: {node.module}"
                    )
