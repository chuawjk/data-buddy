"""HTTP router -- all REST endpoints.

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

import asyncio
import mimetypes
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, File, Form, Query, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)

from backend.sse_proxy import event_stream

router = APIRouter()

# ---------------------------------------------------------------------------
# GET /state
# ---------------------------------------------------------------------------

# Fields that are internal to the backend and must NOT be exposed to the SPA
# (API contract §3: "Mirrors state.json exactly, minus the internal
# opencode_session_id field").
_INTERNAL_FIELDS = {"opencode_session_id"}


@router.get("/state")
async def get_state(request: Request) -> dict[str, Any]:
    """Return the current application state.

    Reads from the StateManager on ``app.state.state_manager`` (set in the
    lifespan in ``main.py``).  Internal fields (``opencode_session_id``) are
    stripped before returning so they are never exposed to the SPA.
    """
    state_manager = request.app.state.state_manager
    state = state_manager.get_state()

    # Strip internal-only fields per the contract (§3).
    return {k: v for k, v in state.items() if k not in _INTERNAL_FIELDS}


# ---------------------------------------------------------------------------
# POST /setup
# ---------------------------------------------------------------------------

# 10 MB size limit (10 * 1024 * 1024 bytes).
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/setup", status_code=204)
async def post_setup(
    request: Request,
    csv: UploadFile = File(...),
    aim: str = Form(...),
) -> Response:
    """Upload dataset and aim, start the brief.

    Steps (N1-S05):
    1. Validate aim is non-empty.
    2. Validate content-type (must be text/csv or filename ends .csv).
    3. Read file and validate size limit (10 MB).
    4. Create workspace/data/ directory.
    5. Write uploaded file to workspace/data/<filename>.
    6. Persist initial state via state_manager.update().
    7. Fire-and-forget orchestrator.setup_complete() as a background task.
    8. Return 204 No Content.

    Error envelopes (API contract S4):
    - 422 invalid_aim -- empty aim string.
    - 422 invalid_file -- not a CSV.
    - 413 file_too_large -- exceeds 10 MB.
    """
    # -- Validate aim --------------------------------------------------------
    aim_stripped = aim.strip()
    if not aim_stripped:
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_aim",
                "message": "The 'aim' field must not be empty.",
            },
        )

    # -- Validate content type -----------------------------------------------
    filename = csv.filename or ""
    content_type = csv.content_type or ""
    is_csv = content_type == "text/csv" or filename.lower().endswith(".csv")
    if not is_csv:
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_file",
                "message": (
                    f"Uploaded file must be a CSV (content-type text/csv or filename ending "
                    f"in .csv). Got content-type '{content_type}' for file '{filename}'."
                ),
            },
        )

    # -- Read and size-check file content ------------------------------------
    content = await csv.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "error": "file_too_large",
                "message": (
                    f"Uploaded file exceeds the 10 MB limit ({len(content)} bytes received)."
                ),
            },
        )

    # -- Write file to workspace/data/ ----------------------------------------
    state_manager = request.app.state.state_manager
    orchestrator = request.app.state.orchestrator

    # Determine workspace root from the state_manager's path parent.
    workspace_root: Path = state_manager._path.parent
    data_dir = workspace_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    dest_path = data_dir / filename
    dest_path.write_bytes(content)

    # -- Persist initial state ------------------------------------------------
    dataset_path = f"data/{filename}"
    state_manager.update(stage="setup", dataset_path=dataset_path, aim=aim_stripped)

    # -- Hand off to orchestrator (fire-and-forget) ---------------------------
    # Schedule setup_complete to run without blocking the response.
    asyncio.create_task(orchestrator.setup_complete(dataset=filename, aim=aim_stripped))

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# GET /events  (N1-S10: real SSE stream)
# ---------------------------------------------------------------------------


@router.get("/events")
async def get_events(request: Request) -> StreamingResponse:
    """Browser-facing SSE stream.

    Drains the internal EventBus (``app.state.bus``) to the browser as
    standard SSE.  Each bus event is serialised as ``data: <json>\\n\\n``.
    A ``": keepalive\\n\\n"`` SSE comment is emitted every 15 s of silence so
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
async def post_turn(request: Request, body: dict = Body(...)) -> Response:
    """Route bottom-bar text to the agent.

    Context-aware: dispatches to the appropriate orchestrator method based on
    the current stage.  Returns 204 immediately; agent progress arrives via SSE.

    Currently implemented stages (N1-S12):
    - ``profiling``: calls ``orchestrator.re_profile(text)``

    Night 2 will add:
    - ``planning``: calls ``orchestrator.re_plan(text)``
    - ``building``: calls ``orchestrator.redirect_section(text)``

    Error envelopes (API contract S4):
    - 422 invalid_text -- text field missing or empty/whitespace-only.
    - 422 invalid_stage -- POST /turn is not valid in the current stage.
    """
    text: str = (body.get("text") or "").strip()
    if not text:
        return JSONResponse(
            status_code=422,
            content={"error": "invalid_text", "message": "text is required and must not be empty"},
        )

    stage: str = request.app.state.state_manager.get_state().get("stage", "")
    if stage == "profiling":
        asyncio.create_task(request.app.state.orchestrator.re_profile(text))
        return Response(status_code=204)

    # Night 2: planning and building stages will be added here.
    return JSONResponse(
        status_code=422,
        content={"error": "invalid_stage", "message": f"POST /turn not valid in stage {stage!r}"},
    )


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

# Explicit content-type overrides per the contract (TL note: N2-S14).
_CONTENT_TYPE_OVERRIDES: dict[str, str] = {
    ".png": "image/png",
    ".py": "text/plain",
    ".md": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
}


@router.get("/file")
async def get_file(
    request: Request,
    path: Annotated[str, Query(description="Relative path within workspace")],
) -> Response:
    """Serve a workspace file (code / chart).

    N2-S14 real implementation.

    Path validation:
    - Resolves the candidate path within ``workspace/`` and verifies it does not
      escape the workspace root.  Any path that resolves outside returns HTTP 400
      with ``{"error": "path_traversal"}``.

    File serving:
    - If the file does not exist, returns HTTP 400 with ``{"error": "missing_file"}``.
    - Content-type is determined first from an explicit override table, then from
      ``mimetypes.guess_type()``, falling back to ``application/octet-stream``.

    Zero OpenCode calls: this endpoint reads from disk only.
    """
    state_manager = request.app.state.state_manager
    workspace_root: Path = state_manager._path.parent.resolve()

    # Resolve the candidate path.  Using workspace_root / path handles both
    # relative paths and absolute paths: if path is absolute (e.g. "/etc/passwd"),
    # Path(workspace_root) / "/etc/passwd" == Path("/etc/passwd"), so the
    # containment check below will catch it.
    candidate = (workspace_root / path).resolve()

    # Path traversal check: candidate must be equal to or inside workspace_root.
    # Use str comparison after resolve() to handle symlinks correctly.
    workspace_str = str(workspace_root)
    candidate_str = str(candidate)
    if not (candidate_str == workspace_str or candidate_str.startswith(workspace_str + "/")):
        return JSONResponse(
            status_code=400,
            content={
                "error": "path_traversal",
                "message": (
                    f"Path {path!r} resolves outside the workspace directory and is not allowed."
                ),
            },
        )

    # File existence check.
    if not candidate.exists() or not candidate.is_file():
        return JSONResponse(
            status_code=400,
            content={
                "error": "missing_file",
                "message": f"File {path!r} not found in the workspace.",
            },
        )

    # Determine content-type: explicit override → mimetypes → octet-stream.
    suffix = candidate.suffix.lower()
    if suffix in _CONTENT_TYPE_OVERRIDES:
        content_type = _CONTENT_TYPE_OVERRIDES[suffix]
    else:
        guessed, _encoding = mimetypes.guess_type(str(candidate))
        content_type = guessed or "application/octet-stream"

    return FileResponse(path=str(candidate), media_type=content_type)
