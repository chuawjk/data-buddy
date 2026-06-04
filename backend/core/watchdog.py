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
overridden in tests and tuned in production (ADR-002).  Defaults to 60 seconds.

Hard boundary: this module does not import the orchestrator.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.agent.opencode_client import OpenCodeClient
    from backend.core.event_bus import EventBus
    from backend.core.state_manager import StateManager

logger = logging.getLogger(__name__)

# Production default; overrideable via env var for tests and production tuning (ADR-002).
WATCHDOG_TIMEOUT: int = int(os.environ.get("WATCHDOG_TIMEOUT_SECONDS", "60"))

# Grace period between abort() and create_fresh_session().
_GRACE_PERIOD_S: float = 10.0


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
    ) -> None:
        self._client = client
        self._state_manager = state_manager
        self._bus = bus
        self._task: asyncio.Task[None] | None = None
        # Stores the timeout passed to the most recent start_turn() call so that
        # heartbeat() can re-arm the timer with the same per-turn budget rather than
        # reverting to the global default.
        self._current_timeout: int = WATCHDOG_TIMEOUT

    def start_turn(self, timeout: int | None = None) -> None:
        """Call when a turn begins. Cancels any existing timer and starts a fresh one.

        Stores the resolved timeout so that subsequent ``heartbeat()`` calls
        can re-arm the timer with the same per-turn budget.

        Args:
            timeout: Silence threshold in seconds before recovery fires.  Defaults
                to ``WATCHDOG_TIMEOUT`` (60 s).  Pass a larger value (e.g. 180) for
                long-running turns such as section builds.
        """
        self.cancel()
        self._current_timeout = timeout or WATCHDOG_TIMEOUT
        self._task = asyncio.create_task(self._watch(self._current_timeout))

    def heartbeat(self) -> None:
        """Call on every event received to reset the silence timer.

        Re-arms the timer using the same timeout that was passed to the most
        recent ``start_turn()`` call.  This preserves the per-turn budget
        (e.g. 180 s for section builds) instead of reverting to the global
        ``WATCHDOG_TIMEOUT`` default.
        """
        self.start_turn(getattr(self, "_current_timeout", WATCHDOG_TIMEOUT))

    def cancel(self) -> None:
        """Cancel the current watch task. Safe to call when no task is running."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _watch(self, timeout: int) -> None:
        """Wait ``timeout`` seconds; if not cancelled, handle the timeout."""
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            logger.debug("Watchdog timer cancelled before timeout.")
            return
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

            logger.info("Watchdog: waiting %ds grace period before fresh session.", _GRACE_PERIOD_S)
            await asyncio.sleep(_GRACE_PERIOD_S)

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
