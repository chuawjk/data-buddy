"""Stuck-turn watchdog and session recovery.

Per-turn async timer: if WATCHDOG_TIMEOUT seconds pass with no event, the watchdog:
  1. Calls client.abort(session_id) -- best-effort; the spike confirms abort does NOT
     reliably unblock a stuck turn.  We attempt it anyway as a courtesy.
  2. Waits 10 seconds of grace to let any in-flight I/O settle.
  3. Calls client.create_fresh_session() -- the confirmed recovery path.
  4. Calls state_manager.update(opencode_session_id=new_id) to swap in the new session.
  5. Publishes turn.error on the bus so the orchestrator / SPA knows the turn timed out.

Usage (called by the orchestrator around every agent turn):

    watchdog.start_turn()     # resets the timer at the start of each turn
    watchdog.heartbeat()      # called on every incoming event to keep the timer alive
    watchdog.cancel()         # called when a turn completes normally

WATCHDOG_TIMEOUT is read from the WATCHDOG_TIMEOUT_SECONDS environment variable so it can be
overridden in tests and tuned in production (ADR-002).  Defaults to 60 seconds.  It is a
single silence budget for every stage: because every activity event re-arms the timer via
heartbeat(), a turn is aborted only after a full budget with no agent activity — never for
simply running long.  The per-stage "section build needs longer" distinction is therefore
obsolete; if a real dataset ever produces a legitimate silent step beyond the budget, raise
WATCHDOG_TIMEOUT_SECONDS rather than reintroducing per-call timeouts.

Hard boundary: this module does not import the orchestrator.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING

from backend.core.qa_controls import TURN_STALL

if TYPE_CHECKING:
    from backend.agent.opencode_client import OpenCodeClient
    from backend.core.event_bus import EventBus
    from backend.core.qa_controls import QAControls
    from backend.core.state_manager import StateManager

logger = logging.getLogger(__name__)

# Production default; overrideable via env var for tests and production tuning (ADR-002).
WATCHDOG_TIMEOUT: int = int(os.environ.get("WATCHDOG_TIMEOUT_SECONDS", "60"))

# Grace period between abort() and create_fresh_session().
_GRACE_PERIOD_S: float = 10.0

# Live-demo stall timing.  When the ``turn-stall`` QA control is active the
# operator wants the recovery to surface within seconds, not after the full
# production budget (which is 180 s for a section build).  Both the silence
# window and the post-abort grace collapse to short, deterministic values so the
# demo is snappy and repeatable.
_STALL_DEMO_TIMEOUT_S: int = 8
_STALL_GRACE_PERIOD_S: float = 2.0


class Watchdog:
    """Per-turn timer that fires abort + fresh-session recovery on silence.

    Args:
        client: The OpenCodeClient -- used to call abort() and create_fresh_session().
        state_manager: The StateManager -- used to read the current session ID and
            to persist the replacement session ID after recovery.
        bus: The EventBus -- used to publish turn.error after recovery.
    """

    def __init__(
        self,
        client: "OpenCodeClient",
        state_manager: "StateManager",
        bus: "EventBus",
        qa_controls: "QAControls | None" = None,
    ) -> None:
        self._client = client
        self._state_manager = state_manager
        self._bus = bus
        self._qa_controls = qa_controls
        self._task: asyncio.Task[None] | None = None
        # True only between start_turn() and the turn ending (cancel, or the timer
        # firing).  heartbeat() is a no-op unless a turn is armed, so stray
        # activity events between turns can never arm the watchdog.
        self._armed: bool = False

    def start_turn(self) -> None:
        """Call when a turn begins. Cancels any existing timer and starts a fresh one.

        The silence budget is the single ``WATCHDOG_TIMEOUT`` (env-overridable),
        or the short stall-demo window when the ``turn-stall`` QA control is
        active.  There is no per-stage budget: heartbeats keep long-but-active
        turns alive on their own.
        """
        self.cancel()
        timeout = self._stall_demo_timeout() or WATCHDOG_TIMEOUT
        self._armed = True
        self._task = asyncio.create_task(self._watch(timeout))

    def heartbeat(self) -> None:
        """Call on every activity event to reset the silence timer.

        No-op unless a turn is currently armed: activity that arrives between
        turns must never start the watchdog by itself.  While armed, it simply
        re-starts the same budget (re-reading the stall-demo override each time).
        """
        if not self._armed:
            return
        self.start_turn()

    def cancel(self) -> None:
        """Cancel the current watch task. Safe to call when no task is running."""
        self._armed = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def _stall_demo_timeout(self) -> int | None:
        """Return the short stall-demo timeout when the QA control is active, else None."""
        if self._qa_controls is not None and self._qa_controls.enabled(TURN_STALL):
            return _STALL_DEMO_TIMEOUT_S
        return None

    async def _watch(self, timeout: int) -> None:
        """Wait ``timeout`` seconds; if not cancelled, handle the timeout."""
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            logger.debug("Watchdog timer cancelled before timeout.")
            return
        # The turn has now timed out — it is no longer armed.  Clearing the flag
        # before recovery means any late activity event cannot re-arm a dead turn.
        self._armed = False
        logger.warning(
            "Watchdog fired: no events for %ds.  Initiating abort + fresh-session recovery.",
            timeout,
        )
        await self._handle_timeout()

    async def _handle_timeout(self) -> None:
        """Abort the stuck turn and recover with a fresh session."""
        state = self._state_manager.get_state()
        session_id: str | None = state.get("opencode_session_id")
        stage: str = state.get("stage", "")

        if session_id:
            logger.info("Watchdog: aborting stuck session %s (best-effort).", session_id)
            await self._client.abort(session_id)

            grace = _STALL_GRACE_PERIOD_S if self._stall_demo_timeout() else _GRACE_PERIOD_S
            logger.info("Watchdog: waiting %ss grace period before fresh session.", grace)
            await asyncio.sleep(grace)

            logger.info("Watchdog: creating fresh session.")
            new_session_id: str = await self._client.create_fresh_session()
            self._state_manager.update(opencode_session_id=new_session_id)
            logger.info("Watchdog: fresh session created and persisted: %s.", new_session_id)
        else:
            logger.warning(
                "Watchdog: no active session ID in state -- cannot abort or replace.  "
                "Emitting turn.error without session recovery."
            )

        await self._bus.publish(
            "turn.error",
            {
                "stage": stage,
                "reason": "timeout",
                "ts": int(time.time() * 1000),
            },
        )
        logger.info("Watchdog: published turn.error (stage=%r, reason=timeout).", stage)
