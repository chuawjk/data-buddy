"""HTTP router — all REST endpoints.

All 10 routes from the API contract are registered here.  Routes whose real
handler logic belongs to later stories return a typed stub that satisfies the
contract's success shape with placeholder values.  No route returns 404 or 5xx
from the stub.

Route inventory (from API_CONTRACT.html):
    POST /setup
    GET  /state
    GET  /events          (real impl N1-S10)
    POST /turn
    POST /plan/update
    POST /plan/accept
    POST /section/{id}/accept
    POST /section/{id}/drop
    GET  /export
    GET  /file
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse, Response, StreamingResponse

from backend.sse_proxy import event_stream

router = APIRouter()

# ---------------------------------------------------------------------------
# GET /state
# ---------------------------------------------------------------------------

_STUB_STATE: dict[str, Any] = {
    "version": "1",
    "stage": "setup",
    "aim": None,
    "dataset_path": None,
    "last_saved": None,
    "profile": None,
    "plan": [],
}


@router.get("/state")
async def get_state() -> dict[str, Any]:
    """Return the current application state.

    Real implementation lives in N1-S03 (state_manager).  Until then, returns
    a minimal valid state object at stage ``"setup"`` so callers can confirm
    the app is healthy and the contract shape is correct.
    """
    return _STUB_STATE


# ---------------------------------------------------------------------------
# POST /setup
# ---------------------------------------------------------------------------


@router.post("/setup")
async def post_setup() -> dict[str, Any]:
    """Upload dataset and aim, start the brief.

    Real implementation: N1-S05.  Stub returns the contract success shape.
    """
    return {"ok": True, "session_id": "stub_session"}


# ---------------------------------------------------------------------------
# GET /events  (N1-S10: real SSE stream)
# ---------------------------------------------------------------------------


@router.get("/events")
async def get_events(request: Request) -> StreamingResponse:
    """Browser-facing SSE stream.

    Drains the internal EventBus (``app.state.bus``) to the browser as
    standard SSE.  Each bus event is serialised as ``data: <json>\n\n``.
    A ``": keepalive\n\n"`` SSE comment is emitted every 15 s of silence so
    proxy and CDN idle timeouts are avoided.

    Headers per the contract:
    - ``Cache-Control: no-cache`` -- prevents caching of the stream.
    - ``X-Accel-Buffering: no`` -- disables nginx response buffering so events
      reach the browser immediately.
    """
    bus = request.app.state.bus
    return StreamingResponse(
        event_stream(bus),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# POST /turn
# ---------------------------------------------------------------------------


@router.post("/turn", status_code=204)
async def post_turn() -> Response:
    """Route bottom-bar text to the agent.

    Real implementation: N1-S12.  Stub returns 204 No Content.
    """
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# POST /plan/update
# ---------------------------------------------------------------------------


@router.post("/plan/update")
async def post_plan_update() -> dict[str, Any]:
    """Inline plan edit (backend-only).

    Real implementation: N2-S04.  Stub returns the contract success shape.
    """
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /plan/accept
# ---------------------------------------------------------------------------


@router.post("/plan/accept", status_code=204)
async def post_plan_accept() -> Response:
    """Accept plan and begin section build.

    Real implementation: N2-S05.  Stub returns 204 No Content.
    """
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# POST /section/{id}/accept
# ---------------------------------------------------------------------------


@router.post("/section/{section_id}/accept", status_code=204)
async def post_section_accept(section_id: str) -> Response:
    """Accept a proposed section and trigger the next.

    Real implementation: N2-S10.  Stub returns 204 No Content.
    """
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# POST /section/{id}/drop
# ---------------------------------------------------------------------------


@router.post("/section/{section_id}/drop", status_code=204)
async def post_section_drop(section_id: str) -> Response:
    """Drop a proposed section and trigger the next.

    Real implementation: N2-S11.  Stub returns 204 No Content.
    """
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# GET /export
# ---------------------------------------------------------------------------


@router.get("/export")
async def get_export() -> PlainTextResponse:
    """Export the brief as a Markdown file.

    Real implementation: N2-S13.  Stub returns an empty Markdown document with
    the correct Content-Disposition header.
    """
    return PlainTextResponse(
        content="# Brief\n\n*(no accepted sections yet)*\n",
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="brief.md"'},
    )


# ---------------------------------------------------------------------------
# GET /file
# ---------------------------------------------------------------------------


@router.get("/file")
async def get_file(
    path: Annotated[str, Query(description="Relative path within workspace")],
) -> Response:
    """Serve a workspace file (code / chart).

    Real implementation: N2-S14.  Stub acknowledges the path parameter and
    returns 404 with the contract error envelope (file not found is a valid
    contract response, not a 5xx).
    """
    return Response(
        content=b'{"error": "missing_file", "message": "File not found (stub handler)."}',
        status_code=404,
        media_type="application/json",
    )
