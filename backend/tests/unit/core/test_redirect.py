"""Unit tests for section redirect (Stage 4b).

TDD: tests written before implementation.

Acceptance criteria covered:
- Building section + POST /turn with redirect text → redirect prompt dispatched,
  204 returned.
- Prior drafts for that section discarded before rebuild.
- Watchdog armed during rebuild.
- Wrong stage → 422.

Architecture constraints:
- orchestrator.py does not import httpx.
- client never imports orchestrator.
- schema=None for section redirect (ADR-005: no structured output).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.core.event_bus import EventBus
from backend.core.orchestrator import Orchestrator
from backend.core.state_manager import StateManager

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_state_manager(
    tmp_path: Path,
    *,
    session_id: str | None = "sess-abc",
    stage: str = "building",
) -> StateManager:
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    if session_id is not None:
        sm.update(opencode_session_id=session_id)
    sm.update(stage=stage)
    return sm


def _make_orchestrator(
    tmp_path: Path,
    *,
    session_id: str | None = "sess-abc",
    stage: str = "building",
) -> tuple[Orchestrator, StateManager, EventBus, AsyncMock]:
    sm = _make_state_manager(tmp_path, session_id=session_id, stage=stage)
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    orch = Orchestrator(
        state_manager=sm,
        bus=bus,
        client=mock_client,
        workspace_root=tmp_path,
    )
    return orch, sm, bus, mock_client


def _set_building_section(
    sm: StateManager,
    section_id: str = "sec_01",
    nn: str = "01",
    slug: str = "churn_by_tier",
) -> None:
    """Add a section with status 'building' to state.json plan."""
    plan = [
        {
            "id": section_id,
            "title": "Churn by Tier",
            "hypothesis": "Higher tiers churn less",
            "status": "building",
            "index": int(nn),
            "slug": slug,
        }
    ]
    sm.update(plan=plan, dataset="customers_q3.csv", aim="Analyse churn")


def _set_proposed_section(
    sm: StateManager,
    section_id: str = "sec_01",
    nn: str = "01",
    slug: str = "churn_by_tier",
) -> None:
    """Add a generated section with status 'proposed' to state.json plan."""
    plan = [
        {
            "id": section_id,
            "title": "Churn by Tier",
            "hypothesis": "Higher tiers churn less",
            "status": "proposed",
            "index": int(nn),
            "slug": slug,
            "py_path": f"analyses/sec_{nn}_{slug}.py",
            "png_path": f"charts/sec_{nn}_{slug}.png",
            "md_path": f"sections/sec_{nn}_{slug}.md",
        }
    ]
    sm.update(plan=plan, dataset="customers_q3.csv", aim="Analyse churn")


def _write_draft_files(
    tmp_path: Path,
    nn: str = "01",
    slug: str = "churn_by_tier",
) -> dict[str, Path]:
    """Write mock draft artefacts for a section."""
    base = f"sec_{nn}_{slug}"
    py_path = tmp_path / "analyses" / f"{base}.py"
    png_path = tmp_path / "charts" / f"{base}.png"
    md_path = tmp_path / "sections" / f"{base}.md"

    (tmp_path / "analyses").mkdir(parents=True, exist_ok=True)
    (tmp_path / "charts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sections").mkdir(parents=True, exist_ok=True)

    py_path.write_text("# draft\n", encoding="utf-8")
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    md_path.write_text(
        "---\nsection_id: sec_01\ntitle: t\nhypothesis: h\nchart: x.png\n---\n\ndraft\n",
        encoding="utf-8",
    )
    return {"py": py_path, "png": png_path, "md": md_path}


# ---------------------------------------------------------------------------
# Part A: redirect prompt tests
# ---------------------------------------------------------------------------


def test_redirect_prompt_contains_redirect_text() -> None:
    """build_redirect_prompt() includes the user's redirect instruction."""
    from backend.agent.prompts.redirect import build_redirect_prompt

    prompt = build_redirect_prompt(
        section_id="sec_01",
        section_index=1,
        title="Churn by Tier",
        hypothesis="Higher tiers churn less",
        aim="Analyse churn",
        dataset="customers_q3.csv",
        profile={"shape": {"rows": 100, "columns": 5}, "columns": [], "flags": []},
        plan=[],
        redirect_text="Use a grouped bar chart with 95% CIs instead",
        workspace_root=Path("/tmp/workspace"),
    )

    assert "Use a grouped bar chart with 95% CIs instead" in prompt
    assert "sec_01" in prompt


def test_redirect_prompt_contains_section_context() -> None:
    """build_redirect_prompt() includes section id, title, hypothesis."""
    from backend.agent.prompts.redirect import build_redirect_prompt

    prompt = build_redirect_prompt(
        section_id="sec_02",
        section_index=2,
        title="Revenue Impact",
        hypothesis="Churn reduces revenue",
        aim="Analyse churn",
        dataset="customers_q3.csv",
        profile={},
        plan=[],
        redirect_text="show trend lines",
        workspace_root=Path("/tmp/workspace"),
    )

    assert "Revenue Impact" in prompt
    assert "sec_02" in prompt
    assert "Churn reduces revenue" in prompt


def test_redirect_prompt_instructs_discard() -> None:
    """build_redirect_prompt() instructs the agent to discard prior artefacts."""
    from backend.agent.prompts.redirect import build_redirect_prompt

    prompt = build_redirect_prompt(
        section_id="sec_01",
        section_index=1,
        title="Churn by Tier",
        hypothesis="Higher tiers churn less",
        aim="Analyse churn",
        dataset="customers_q3.csv",
        profile={},
        plan=[],
        redirect_text="different chart type",
        workspace_root=Path("/tmp/workspace"),
    )

    # Should mention discarding / replacing the prior files
    prompt_lower = prompt.lower()
    assert any(
        word in prompt_lower for word in ["discard", "replace", "rebuild", "overwrite", "delete"]
    ), f"Redirect prompt should instruct discard/replace; got: {prompt[:200]}"


def test_redirect_prompt_targets_correct_file_paths(tmp_path: Path) -> None:
    """build_redirect_prompt() uses the correct sec_NN_slug file paths."""
    from backend.agent.prompts.redirect import build_redirect_prompt

    prompt = build_redirect_prompt(
        section_id="sec_01",
        section_index=1,
        title="Churn by Tier",
        hypothesis="Higher tiers churn less",
        aim="Analyse churn",
        dataset="customers_q3.csv",
        profile={},
        plan=[],
        redirect_text="different approach",
        workspace_root=tmp_path,
    )

    assert "sec_01_churn_by_tier.py" in prompt
    assert "sec_01_churn_by_tier.png" in prompt
    assert "sec_01_churn_by_tier.md" in prompt


def test_redirect_prompt_no_schema_instruction() -> None:
    """build_redirect_prompt() must not include json_schema/format instruction.

    Section redirect uses no structured output (ADR-005).
    """
    from backend.agent.prompts.redirect import build_redirect_prompt

    prompt = build_redirect_prompt(
        section_id="sec_01",
        section_index=1,
        title="Churn by Tier",
        hypothesis="Higher tiers churn less",
        aim="Analyse churn",
        dataset="customers_q3.csv",
        profile={},
        plan=[],
        redirect_text="different approach",
        workspace_root=Path("/tmp/workspace"),
    )

    assert "json_schema" not in prompt
    assert '"type": "json_schema"' not in prompt


# ---------------------------------------------------------------------------
# Part B: orchestrator.redirect_section tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redirect_section_calls_prompt(tmp_path: Path) -> None:
    """redirect_section() dispatches client.prompt with session_id and non-empty text."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    _set_building_section(sm)
    _write_draft_files(tmp_path)

    await orch.redirect_section("use a bar chart instead")
    await asyncio.sleep(0)

    client.prompt.assert_awaited_once()
    args, kwargs = client.prompt.call_args
    assert args[0] == "sess-abc"
    assert isinstance(args[1], str) and len(args[1]) > 0
    # No schema for section redirect (ADR-005)
    schema_arg = kwargs.get("schema", args[2] if len(args) > 2 else None)
    assert schema_arg is None, f"schema must be None for redirect (ADR-005); got {schema_arg!r}"


@pytest.mark.asyncio
async def test_redirect_section_deletes_draft_files(tmp_path: Path) -> None:
    """redirect_section() deletes draft .py, .png, .md before dispatching prompt."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    _set_building_section(sm)
    paths = _write_draft_files(tmp_path)

    # All three files exist before redirect.
    assert paths["py"].exists()
    assert paths["png"].exists()
    assert paths["md"].exists()

    await orch.redirect_section("use a bar chart instead")

    # All three should be deleted after redirect_section runs.
    assert not paths["py"].exists(), "Draft .py should be deleted before rebuild"
    assert not paths["png"].exists(), "Draft .png should be deleted before rebuild"
    assert not paths["md"].exists(), "Draft .md should be deleted before rebuild"


@pytest.mark.asyncio
async def test_redirect_section_partial_drafts_deleted(tmp_path: Path) -> None:
    """redirect_section() deletes whichever draft files exist (partial is OK)."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    _set_building_section(sm)

    # Write only .py (partial draft — section started but not finished)
    (tmp_path / "analyses").mkdir(parents=True, exist_ok=True)
    py_path = tmp_path / "analyses" / "sec_01_churn_by_tier.py"
    py_path.write_text("# partial\n", encoding="utf-8")

    await orch.redirect_section("different approach")

    # The .py that existed should be deleted; no crash for missing .png/.md.
    assert not py_path.exists(), "Existing draft .py should be deleted"


@pytest.mark.asyncio
async def test_redirect_section_rebuilds_proposed_section(tmp_path: Path) -> None:
    """redirect_section() rebuilds a generated section awaiting review."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    _set_proposed_section(sm)
    paths = _write_draft_files(tmp_path)

    subscription = bus.subscribe()

    await orch.redirect_section("make the chart grouped")
    await asyncio.sleep(0)

    client.prompt.assert_awaited_once()
    assert not paths["py"].exists()
    assert not paths["png"].exists()
    assert not paths["md"].exists()

    state = sm.get_state()
    section = state["plan"][0]
    assert section["status"] == "building"
    assert section["py_path"] is None
    assert section["png_path"] is None
    assert section["md_path"] is None

    event = await asyncio.wait_for(subscription.__anext__(), timeout=1)
    assert event["type"] == "section.building"
    assert event["section_id"] == "sec_01"


@pytest.mark.asyncio
async def test_redirect_section_targets_explicit_section_id(tmp_path: Path) -> None:
    """section_id targets that section directly; natural-language text passes through."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    sm.update(
        plan=[
            {
                "id": "sec_01",
                "title": "Cohort Overview",
                "hypothesis": "H1",
                "status": "proposed",
                "index": 1,
                "slug": "cohort_overview",
                "py_path": "analyses/sec_01_cohort_overview.py",
                "png_path": "charts/sec_01_cohort_overview.png",
                "md_path": "sections/sec_01_cohort_overview.md",
            },
            {
                "id": "sec_02",
                "title": "Churn by Tier",
                "hypothesis": "H2",
                "status": "proposed",
                "index": 2,
                "slug": "churn_by_tier",
                "py_path": "analyses/sec_02_churn_by_tier.py",
                "png_path": "charts/sec_02_churn_by_tier.png",
                "md_path": "sections/sec_02_churn_by_tier.md",
            },
        ],
        dataset="customers_q3.csv",
        aim="Analyse churn",
    )
    _write_draft_files(tmp_path, nn="01", slug="cohort_overview")
    sec2_paths = _write_draft_files(tmp_path, nn="02", slug="churn_by_tier")

    subscription = bus.subscribe()

    await orch.redirect_section("use a grouped chart", section_id="sec_02")
    await asyncio.sleep(0)

    client.prompt.assert_awaited_once()
    prompt = client.prompt.call_args.args[1]
    assert "section sec_02" in prompt
    assert not sec2_paths["py"].exists()
    assert not sec2_paths["png"].exists()
    assert not sec2_paths["md"].exists()

    state = sm.get_state()
    sec1, sec2 = state["plan"]
    assert sec1["status"] == "proposed"
    assert sec2["status"] == "building"

    event = await asyncio.wait_for(subscription.__anext__(), timeout=1)
    assert event["type"] == "section.building"
    assert event["section_id"] == "sec_02"


@pytest.mark.asyncio
async def test_redirect_section_unknown_section_id_returns_early(tmp_path: Path) -> None:
    """Unknown section_id is a no-op instead of falling back to the first section."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    sm.update(
        plan=[
            {
                "id": "sec_01",
                "title": "Cohort Overview",
                "hypothesis": "H1",
                "status": "proposed",
                "index": 1,
                "slug": "cohort_overview",
            },
            {
                "id": "sec_02",
                "title": "Churn by Tier",
                "hypothesis": "H2",
                "status": "proposed",
                "index": 2,
                "slug": "churn_by_tier",
            },
        ],
        dataset="customers_q3.csv",
        aim="Analyse churn",
    )

    await orch.redirect_section("use confidence intervals", section_id="sec_99")
    await asyncio.sleep(0)

    client.prompt.assert_not_awaited()
    state = sm.get_state()
    assert state["plan"][0]["status"] == "proposed"
    assert state["plan"][1]["status"] == "proposed"


@pytest.mark.asyncio
async def test_redirect_section_arms_watchdog(tmp_path: Path) -> None:
    """redirect_section() calls watchdog.start_turn() when watchdog is wired."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc", stage="building")
    _set_building_section(sm)
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    watchdog = MagicMock()
    watchdog.start_turn = MagicMock()

    orch = Orchestrator(
        state_manager=sm,
        bus=bus,
        client=mock_client,
        workspace_root=tmp_path,
        watchdog=watchdog,
    )

    await orch.redirect_section("use a bar chart")
    await asyncio.sleep(0)

    watchdog.start_turn.assert_called_once()


@pytest.mark.asyncio
async def test_redirect_section_raises_without_session(tmp_path: Path) -> None:
    """redirect_section() raises ValueError when no session_id is stored."""
    sm = _make_state_manager(tmp_path, session_id=None, stage="building")
    _set_building_section(sm)
    bus = EventBus()
    orch = Orchestrator(state_manager=sm, bus=bus, client=AsyncMock(), workspace_root=tmp_path)

    with pytest.raises(ValueError, match="No active session"):
        await orch.redirect_section("some redirect text")


@pytest.mark.asyncio
async def test_redirect_section_raises_wrong_stage(tmp_path: Path) -> None:
    """redirect_section() raises ValueError when stage != building."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc", stage="planning")
    bus = EventBus()
    orch = Orchestrator(state_manager=sm, bus=bus, client=AsyncMock(), workspace_root=tmp_path)

    with pytest.raises(ValueError, match="building"):
        await orch.redirect_section("some redirect text")


@pytest.mark.asyncio
async def test_redirect_section_no_redirectable_section_returns_early(tmp_path: Path) -> None:
    """redirect_section() is a no-op when no section has status=proposed/building."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    # Plan has no building section
    sm.update(
        plan=[
            {
                "id": "sec_01",
                "title": "Churn by Tier",
                "hypothesis": "H",
                "status": "queued",
            }
        ],
        dataset="customers_q3.csv",
        aim="Analyse churn",
    )

    # Should not raise, should not call prompt
    await orch.redirect_section("some redirect text")
    await asyncio.sleep(0)

    client.prompt.assert_not_awaited()


# ---------------------------------------------------------------------------
# Part C: router POST /turn building-stage tests
# ---------------------------------------------------------------------------


def _make_app(tmp_path: Path, *, stage: str = "building") -> TestClient:
    """Create a test app with mock orchestrator wired in."""
    from unittest.mock import AsyncMock

    from fastapi import FastAPI

    from backend.api.router import router
    from backend.core.event_bus import EventBus
    from backend.core.state_manager import StateManager

    app = FastAPI()
    app.include_router(router)

    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    sm.update(stage=stage, opencode_session_id="sess-abc")

    bus = EventBus()
    mock_orch = MagicMock()
    mock_orch.redirect_section = AsyncMock(return_value=None)
    mock_orch.re_profile = AsyncMock(return_value=None)
    mock_orch.retry_last_turn = AsyncMock(return_value=None)

    app.state.state_manager = sm
    app.state.orchestrator = mock_orch
    app.state.bus = bus

    return TestClient(app), mock_orch


def test_post_turn_building_returns_204(tmp_path: Path) -> None:
    """POST /turn in building stage returns 204 and dispatches redirect_section."""
    client_and_orch = _make_app(tmp_path, stage="building")
    test_client, mock_orch = client_and_orch

    resp = test_client.post("/turn", json={"text": "use a bar chart instead"})
    assert resp.status_code == 204, f"Expected 204; got {resp.status_code}: {resp.text}"


def test_post_turn_building_calls_redirect_section(tmp_path: Path) -> None:
    """POST /turn in building stage passes text and optional section_id."""
    test_client, mock_orch = _make_app(tmp_path, stage="building")

    test_client.post("/turn", json={"text": "use a bar chart instead", "section_id": "sec_02"})

    # Allow any scheduled coroutines to run (TestClient is sync but asyncio tasks
    # created by create_task in the router handler don't run in sync context).
    # We verify the orchestrator method was called, not the task result.
    mock_orch.redirect_section.assert_called_once_with("use a bar chart instead", "sec_02")


def test_post_turn_wrong_stage_returns_422(tmp_path: Path) -> None:
    """POST /turn with stage=setup (no handler) → 422 invalid_stage."""
    test_client, _ = _make_app(tmp_path, stage="setup")

    resp = test_client.post("/turn", json={"text": "some text"})
    assert resp.status_code == 422, f"Expected 422; got {resp.status_code}"
    body = resp.json()
    assert body.get("error") == "invalid_stage"


def test_post_turn_empty_text_triggers_retry_building(tmp_path: Path) -> None:
    """POST /turn with empty text in building stage triggers retry.

    Empty/absent text now calls retry_last_turn() instead of returning 422.
    Returns 204; retry is a no-op when there is no prior turn.
    """
    test_client, _ = _make_app(tmp_path, stage="building")

    resp = test_client.post("/turn", json={"text": "   "})
    assert resp.status_code == 204, f"Expected 204 (retry path); got {resp.status_code}"


def test_post_turn_missing_text_triggers_retry_building(tmp_path: Path) -> None:
    """POST /turn with missing text field in building stage triggers retry."""
    test_client, _ = _make_app(tmp_path, stage="building")

    resp = test_client.post("/turn", json={})
    assert resp.status_code == 204, f"Expected 204 (retry path); got {resp.status_code}"
