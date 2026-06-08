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
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.agent.opencode_client import OpenCodeClient
from backend.api.router import router
from backend.core.event_bus import EventBus
from backend.core.orchestrator import Orchestrator
from backend.core.qa_controls import QAControls
from backend.core.state_manager import StateManager
from backend.core.watchdog import Watchdog

# Absolute path to the compiled Vite bundle.  Resolved at module load time so
# it is consistent regardless of the working directory uvicorn is invoked from.
_REPO_ROOT = Path(__file__).parent.parent
FRONTEND_DIST = _REPO_ROOT / "frontend" / "dist"

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
    4. Orchestrator -- full setup→profiling state machine.
       Holds a reference to the OpenCodeClient for the narrow prompt interface.

    Shutdown order (reverse):
    3. OpenCodeClient.stop() -- SIGTERM then SIGKILL after 5 s.
    """
    # --- startup ---
    app.state.bus = EventBus()

    # WORKSPACE_ROOT lets QA and tests point the backend at a fixture workspace
    # without touching the real workspace/ directory. StateManager reads it
    # internally; Orchestrator receives it explicitly for file I/O paths.
    workspace_root = Path(os.environ.get("WORKSPACE_ROOT", "workspace"))
    qa_controls = QAControls(workspace_root)
    app.state.qa_controls = qa_controls
    state_manager = StateManager()
    # Load persisted state from disk (no-op if workspace/state.json does not
    # exist yet -- returns the default shape and leaves _state at defaults).
    state_manager.load()
    app.state.state_manager = state_manager

    skip_opencode = os.environ.get("SKIP_OPENCODE", "").strip().lower() in ("1", "true", "yes")

    client: OpenCodeClient | None = None
    if not skip_opencode:
        client = OpenCodeClient(state_manager=state_manager, qa_controls=qa_controls)
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
            # Start the persistent SSE subscription as a background task.
            # One connection, running for the lifetime of the server.
            subscription_task = asyncio.create_task(client.start_event_subscription(app.state.bus))
            client._register_subscription_task(subscription_task)
            logger.info("OpenCode event subscription task started.")

    app.state.opencode_client = client

    # Wire up the watchdog.  Only created when OpenCode is running; Watchdog requires
    # a live client reference so it can call abort() and create_fresh_session().
    # When SKIP_OPENCODE=1, watchdog is omitted and the orchestrator guards internally.
    watchdog: Watchdog | None = None
    if client is not None:
        watchdog = Watchdog(client=client, state_manager=state_manager, bus=app.state.bus)
        app.state.watchdog = watchdog

    # Wire up the stage orchestrator.
    orchestrator = Orchestrator(
        state_manager=state_manager,
        bus=app.state.bus,
        client=client,  # None when SKIP_OPENCODE=1; orchestrator guards internally.
        watchdog=watchdog,  # None when SKIP_OPENCODE=1; orchestrator guards internally.
        workspace_root=workspace_root,
        qa_controls=qa_controls,
    )
    app.state.orchestrator = orchestrator

    # Start the orchestrator's bus listener as a background task.
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
# The /api prefix is added here (at mount time) so the built Vite bundle's
# /api/* calls reach the backend without the dev-proxy rewrite.  The router
# itself stays prefix-free so its path strings remain readable.
app.include_router(router, prefix="/api")


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


# ---------------------------------------------------------------------------
# Static file serving for the built Vite bundle (ADR-008).
#
# Only mounted when ``frontend/dist/`` exists -- i.e. after ``make run`` has
# built the bundle.  In ``make dev`` mode the dist directory is absent and
# FastAPI never mounts static files, so the Vite dev server on :5173 handles
# the SPA without interference.
#
# Ordering is critical:
#   1. API routes (registered above via include_router) are matched first.
#   2. /assets/ static mount handles Vite's hashed JS/CSS/image files.
#   3. The catch-all SPA fallback is registered last so it only fires for
#      paths that didn't match any API route.  This prevents the fallback from
#      swallowing /api/* calls, /health, or any SSE stream.
# ---------------------------------------------------------------------------

if FRONTEND_DIST.exists():
    _assets_dir = FRONTEND_DIST / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    async def spa_fallback(full_path: str) -> FileResponse | JSONResponse:
        """Serve index.html for all non-API paths (client-side routing).

        This catch-all is registered after all API routes so it never
        intercepts ``/api/*``, ``/health``, ``/events``, ``/state``, etc.
        If the dist directory somehow disappears between startup and the
        request, return a 503 rather than a hard crash.
        """
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse(
            {"error": "frontend not built", "message": "Run 'make run' to build the frontend."},
            status_code=503,
        )
