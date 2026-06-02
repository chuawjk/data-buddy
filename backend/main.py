"""FastAPI application entry point.

Responsibilities:
- Create the FastAPI application instance.
- Lifespan: instantiate the EventBus, StateManager, and Orchestrator and
  attach them to ``app.state`` so every request handler (and background task)
  can access them without importing a module-level singleton.
- Mount the router that registers all 10 REST routes.
- Keep the ``/health`` liveness endpoint directly on the app (not in the
  router) so infrastructure probes work independently of business logic.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.event_bus import EventBus
from backend.orchestrator import Orchestrator
from backend.router import router
from backend.state_manager import StateManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler.

    Runs once at startup (before the first request) and once at shutdown (after
    the last request).  The EventBus, StateManager, and Orchestrator are
    created here and stored on ``app.state`` so they outlive individual
    requests and can be injected via FastAPI's dependency system.

    Startup order:
    1. EventBus -- in-process pub/sub (no external dependency).
    2. StateManager -- loads state.json from disk (or defaults if absent).
    3. Orchestrator -- minimal stub for the setup->profiling handoff (N1-S05).
       The full state machine (N1-S04) will expand this once N1-S08 is merged.
    """
    # --- startup ---
    app.state.bus = EventBus()
    app.state.state_manager = StateManager()
    # Load persisted state from disk (no-op if workspace/state.json does not
    # exist yet -- returns the default shape and leaves _state at defaults).
    app.state.state_manager.load()
    # Wire up the minimal orchestrator stub (N1-S05).
    app.state.orchestrator = Orchestrator(
        state_manager=app.state.state_manager,
        bus=app.state.bus,
    )
    yield
    # --- shutdown ---
    # Nothing to tear down for the bus, state manager, or orchestrator stub;
    # later stories (OpenCode process, watchdog) will add cleanup here.


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
