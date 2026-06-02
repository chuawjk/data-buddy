"""FastAPI application entry point.

Responsibilities:
- Create the FastAPI application instance.
- Lifespan: instantiate the EventBus and attach it to ``app.state.bus`` so
  every request handler (and background task) can publish/subscribe without
  importing a module-level singleton.
- Mount the router that registers all 10 REST routes.
- Keep the ``/health`` liveness endpoint directly on the app (not in the
  router) so infrastructure probes work independently of business logic.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.event_bus import EventBus
from backend.router import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler.

    Runs once at startup (before the first request) and once at shutdown (after
    the last request).  The EventBus is created here and stored on
    ``app.state.bus`` so it outlives individual requests and can be injected
    via FastAPI's dependency system in later stories.
    """
    # --- startup ---
    app.state.bus = EventBus()
    yield
    # --- shutdown ---
    # Nothing to tear down for the bus itself; later stories (OpenCode process,
    # watchdog) will add cleanup here inside the lifespan.


app = FastAPI(
    title="Data Buddy API",
    description="Backend for the Data Buddy agent-driven data-analysis tool.",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount all REST routes (10 routes from the API contract).
app.include_router(router)


# ---------------------------------------------------------------------------
# Liveness probe — kept directly on the app, independent of business routes.
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Simple liveness check.

    Returns ``{"status": "ok"}`` so infrastructure probes and ``make dev``
    startup checks can confirm the process is alive.
    """
    return {"status": "ok"}
