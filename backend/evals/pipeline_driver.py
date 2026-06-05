"""Pipeline driver — runs the full Data Buddy pipeline for one eval test case.

Wires StateManager, EventBus, OpenCodeClient, and Orchestrator in-process
(no HTTP layer).  Auto-accepts the profile and plan so the pipeline runs
end-to-end without human interaction, producing workspace artefacts that
the judge can then evaluate.

The driver subscribes to the EventBus and drives stage transitions:
  profile.ready  → accept_profile()
  plan.ready     → accept_plan()
  stage.changed{done} → pipeline complete

Any turn.error event is treated as a fatal case failure.
"""

from __future__ import annotations

import asyncio
import logging
import shutil

from backend.agent.opencode_client import OpenCodeClient
from backend.core.event_bus import EventBus
from backend.core.orchestrator import Orchestrator
from backend.core.state_manager import StateManager
from backend.evals.models import TestCase

logger = logging.getLogger(__name__)

_PIPELINE_TIMEOUT_S: float = 600.0  # 10 min ceiling per case


async def build_case(case: TestCase, max_sections: int | None = None) -> None:
    """Run the full pipeline for one test case and populate its workspace.

    Creates the workspace directory tree, copies the dataset, then drives
    the orchestrator from setup → profiling → planning → building → done.
    Raises on timeout or any turn.error event.

    Args:
        case: The test case to build.  ``case.workspace`` is created (or
            clobbered) and populated by this call.
        max_sections: If set, truncate the plan to this many sections after
            planning completes.  Useful for fast dev loops.

    Raises:
        RuntimeError: If a turn.error event fires during the run.
        asyncio.TimeoutError: If the pipeline exceeds ``_PIPELINE_TIMEOUT_S``.
    """
    _prepare_workspace(case)

    state_mgr = StateManager(case.workspace / "state.json")
    bus = EventBus()
    client = OpenCodeClient(state_mgr)
    orchestrator = Orchestrator(state_mgr, bus, client, workspace_root=case.workspace)

    await client.start()
    logger.info("build_case[%s]: OpenCode started, session=%s", case.name, client.session_id)

    listener = asyncio.create_task(
        orchestrator.start_bus_listener(), name=f"bus-listener-{case.name}"
    )
    subscription = asyncio.create_task(
        client.start_event_subscription(bus), name=f"sse-sub-{case.name}"
    )

    try:
        await asyncio.wait_for(
            _drive(case, orchestrator, state_mgr, bus, max_sections=max_sections),
            timeout=_PIPELINE_TIMEOUT_S,
        )
        logger.info("build_case[%s]: pipeline complete (stage=done)", case.name)
    finally:
        listener.cancel()
        subscription.cancel()
        await client.stop()
        logger.info("build_case[%s]: OpenCode stopped", case.name)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _prepare_workspace(case: TestCase) -> None:
    """Create (or clobber) the workspace directory and copy the dataset in."""
    if case.workspace.exists():
        shutil.rmtree(case.workspace)
    (case.workspace / "data").mkdir(parents=True)
    shutil.copy2(case.dataset, case.workspace / "data" / case.dataset.name)
    logger.info("build_case[%s]: workspace prepared at %s", case.name, case.workspace)


async def _drive(
    case: TestCase,
    orchestrator: Orchestrator,
    state_mgr: StateManager,
    bus: EventBus,
    max_sections: int | None = None,
) -> None:
    """Subscribe to the EventBus and advance stage transitions automatically.

    Kicks off setup_complete() then loops over bus events, calling the
    appropriate orchestrator method at each stage boundary.  Returns when
    stage=done is observed.  Raises RuntimeError on any turn.error.

    Section acceptance is handled here rather than waiting for user input —
    the eval driver auto-accepts every proposed section so the pipeline runs
    fully unattended.  This replicates what POST /section/:id/accept does:
    flip status → "accepted" in state, then call _check_done_or_next so the
    orchestrator can transition to done once all sections are terminal.
    """
    done = asyncio.Event()
    sub = bus.subscribe()

    async def _listen() -> None:
        async for envelope in sub:
            event_type: str = envelope.get("type", "")

            if event_type == "profile.ready":
                logger.info("build_case[%s]: profile.ready → accepting profile", case.name)
                await orchestrator.accept_profile()

            elif event_type == "plan.ready":
                if max_sections is not None:
                    state = state_mgr.get_state()
                    state_mgr.update(plan=state.get("plan", [])[:max_sections])
                    logger.info(
                        "build_case[%s]: plan truncated to %d section(s)", case.name, max_sections
                    )
                logger.info("build_case[%s]: plan.ready → accepting plan", case.name)
                await orchestrator.accept_plan()

            elif event_type == "section.proposed":
                section_id: str = envelope.get("section_id", "")
                logger.info(
                    "build_case[%s]: section.proposed %r → accepting", case.name, section_id
                )
                _accept_section(state_mgr, section_id)
                await orchestrator._check_done_or_next(section_id)  # noqa: SLF001

            elif event_type == "stage.changed" and envelope.get("stage") == "done":
                logger.info("build_case[%s]: stage.changed → done", case.name)
                done.set()
                return

            elif event_type == "turn.error":
                raise RuntimeError(
                    f"build_case[{case.name}]: turn.error — "
                    f"stage={envelope.get('stage')!r}, reason={envelope.get('reason')!r}"
                )

    listener_task = asyncio.create_task(_listen(), name=f"driver-{case.name}")

    await orchestrator.setup_complete(case.dataset.name, case.aim)

    await done.wait()
    listener_task.cancel()


def _accept_section(state_mgr: StateManager, section_id: str) -> None:
    """Flip a section's status to 'accepted' in state.json."""
    state = state_mgr.get_state()
    updated_plan = [
        {**s, "status": "accepted"} if s.get("id") == section_id else s
        for s in state.get("plan", [])
    ]
    state_mgr.update(plan=updated_plan)
