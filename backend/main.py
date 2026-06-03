"""FastAPI application entry point.

Responsibilities:
- Create the FastAPI application instance.
- Lifespan: instantiate the EventBus, StateManager, OpenCodeClient, and Orchestrator and
  attach them to ``app.state`` so every request handler (and background task)
  can access them without importing a module-level singleton.
- Mount the router that registers all 10 REST routes.
- Keep the ``/health`` liveness endpoint directly on the app (not in the
  router) so infrastructure probes work independently of business logic.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.event_bus import EventBus
from backend.opencode_client import OpenCodeClient
from backend.orchestrator import Orchestrator
from backend.router import router
from backend.state_manager import StateManager
from backend.watchdog import Watchdog

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler.

    Runs once at startup (before the first request) and once at shutdown (after
    the last request).

    Startup order:
    1. EventBus -- in-process pub/sub (no external dependency).
    2. StateManager -- loads state.json from disk (or defaults if absent).
    3. OpenCodeClient -- resolves the binary, launches ``opencode serve``,
       waits for readiness, and creates the v1 session.  Skipped when the
       ``SKIP_OPENCODE`` environment variable is set to a truthy value
       (``1``, ``true``, or ``yes``) -- for CI and environments without the
       binary installed.
    4. Orchestrator -- full setup→profiling state machine (N1-S04).
       Holds a reference to the OpenCodeClient for the narrow prompt interface.

    Shutdown order (reverse):
    3. OpenCodeClient.stop() -- SIGTERM then SIGKILL after 5 s.
    """
    # --- startup ---
    app.state.bus = EventBus()

    state_manager = StateManager()
    # Load persisted state from disk (no-op if workspace/state.json does not
    # exist yet -- returns the default shape and leaves _state at defaults).
    state_manager.load()
    app.state.state_manager = state_manager

    skip_opencode = os.environ.get("SKIP_OPENCODE", "").strip().lower() in ("1", "true", "yes")

    client: OpenCodeClient | None = None
    if not skip_opencode:
        client = OpenCodeClient(state_manager=state_manager)
        try:
            await client.start()
        except RuntimeError as exc:
            # Log prominently but do not crash the server -- development
            # environments without opencode installed should still start.
            logger.error(
                "OpenCode client failed to start: %s.  "
                "Agent-driven features will not work.  "
                "Set SKIP_OPENCODE=1 to suppress this error.",
                exc,
            )
            client = None

        if client is not None:
            # Start the persistent SSE subscription as a background task (N1-S08).
            # One connection, running for the lifetime of the server.
            subscription_task = asyncio.create_task(client.start_event_subscription(app.state.bus))
            client._register_subscription_task(subscription_task)
            logger.info("OpenCode event subscription task started.")

    app.state.opencode_client = client

    # Wire up the watchdog (N1-S11 / N1-S12).  Only created when OpenCode is running;
    # Watchdog requires a live client reference so it can call abort() and
    # create_fresh_session().  When SKIP_OPENCODE=1, watchdog is omitted and the
    # orchestrator guards internally (no-op start_turn path).
    watchdog: Watchdog | None = None
    if client is not None:
        watchdog = Watchdog(client=client, state_manager=state_manager, bus=app.state.bus)
        app.state.watchdog = watchdog

    # Wire up the stage orchestrator (N1-S04: setup→profiling state machine).
    orchestrator = Orchestrator(
        state_manager=state_manager,
        bus=app.state.bus,
        client=client,  # None when SKIP_OPENCODE=1; orchestrator guards internally.
        watchdog=watchdog,  # None when SKIP_OPENCODE=1; orchestrator guards internally.
    )
    app.state.orchestrator = orchestrator

    # Start the orchestrator's bus listener as a background task (N1-S18 integration).
    # This consumes session.idle events and drives stage-output handling
    # (profile.ready, plan.ready, section.proposed/failed).
    bus_listener_task = asyncio.create_task(
        orchestrator.start_bus_listener(), name="orchestrator-bus-listener"
    )
    app.state.bus_listener_task = bus_listener_task
    logger.info("Orchestrator bus listener task started.")

    yield

    # --- shutdown ---
    # Cancel the orchestrator bus listener first (it holds an EventBus subscription).
    if not bus_listener_task.done():
        bus_listener_task.cancel()
        try:
            await bus_listener_task
        except asyncio.CancelledError:
            pass
        logger.info("Orchestrator bus listener task stopped.")

    if client is not None:
        await client.stop_event_subscription()
        await client.stop()


app = FastAPI(
    title="Data Buddy API",
    description="Backend for the Data Buddy agent-driven data-analysis tool.",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount all REST routes (10 routes from the API contract).
app.include_router(router)


# ---------------------------------------------------------------------------
# Liveness probe -- kept directly on the app, independent of business routes.
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Simple liveness check.

    Returns ``{"status": "ok"}`` so infrastructure probes and ``make dev``
    startup checks can confirm the process is alive.
    """
    return {"status": "ok"}
