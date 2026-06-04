"""OpenCode process management, session lifecycle, and persistent event subscription.

Responsibilities:
- Resolve the ``opencode`` binary via ``shutil.which`` at startup (raises
  clearly if not found — no PATH-assumed launch).
- Launch ``opencode serve`` as a managed subprocess.
- Poll ``GET /health`` until the server is ready or the readiness timeout
  expires.
- Create a single session via the **v1 /session** API and persist the session
  ID to ``state.json`` through the ``StateManager``.
- Maintain a single persistent ``GET /event`` SSE subscription (N1-S08):
  normalise raw OpenCode events and publish them to the ``EventBus``.
  Reconnects automatically if no ``server.heartbeat`` arrives for 30s.
- Tear down the subprocess cleanly on shutdown (SIGTERM, then SIGKILL after 5 s).

Out of scope:
- Watchdog abort/recovery (N1-S11).

Hard boundary: this module never imports the orchestrator.  The orchestrator
calls this client through the narrow interface only.  ``httpx`` is imported
here; the orchestrator must not import ``httpx`` directly.

Normalisation rules (from docs/contracts/SSE_CONTRACT.md):
  raw type                        → bus event
  message.part.delta              → message.part  (text streaming)
  message.part.updated (bash, running)  → tool.bash_running
  message.part.updated (bash, completed) → tool.bash_done
  message.part.updated (*, completed, metadata.files present) → tool.file_written
  session.idle (own session)      → session.idle
  server.heartbeat                → reset timer only; nothing published
  file.edited                     → file.ready   (global — no sessionID filter)
  all others                      → drop silently

"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from backend.core.event_bus import EventBus
from backend.core.state_manager import StateManager

logger = logging.getLogger(__name__)

# Default OpenCode serve port (confirmed in spike: --port 4096).
_DEFAULT_PORT: int = 4096

# v1 session endpoint — per SSE_CONTRACT.md §D5, stick with v1 /session.
_SESSION_PATH: str = "/session"

# OpenCode OAuth provider config (spike §2: providerID "openai", modelID "gpt-5.4-mini").
_DEFAULT_PROVIDER_ID: str = "openai"
_DEFAULT_MODEL_ID: str = "gpt-5.4-mini"

# Health readiness defaults.
_READINESS_TIMEOUT_S: float = 30.0  # seconds to wait for server to accept connections
_POLL_INTERVAL_S: float = 0.5  # seconds between health polls

# Shutdown grace period before SIGKILL.
_SIGKILL_GRACE_S: float = 5.0

# Heartbeat absence threshold before reconnect (seconds).
_HEARTBEAT_TIMEOUT_S: float = 30.0

# Events that carry a sessionID in properties — must match the active session.
_SESSION_SCOPED_TYPES: frozenset[str] = frozenset(
    {
        "message.part.updated",
        "message.part.delta",
        "session.idle",
        "session.status",
        "session.diff",
        "session.next.agent.switched",
        "session.next.model.switched",
    }
)

# Events with no sessionID — always relevant (global).
_GLOBAL_TYPES: frozenset[str] = frozenset({"server.heartbeat", "server.connected", "file.edited"})


class OpenCodeClient:
    """Manages the OpenCode subprocess lifecycle and v1 session.

    Args:
        state_manager: The ``StateManager`` instance used to persist the
            session ID.  Passed in by the lifespan so the client never
            constructs its own.
        base_url: Base URL of the OpenCode HTTP server.  Defaults to
            ``http://localhost:4096``.
        readiness_timeout: Seconds to wait for the health endpoint to return
            200 before raising ``RuntimeError``.
        poll_interval: Seconds between health poll attempts.
        provider_id: OpenCode provider ID for session creation.
        model_id: OpenCode model ID for session creation.
    """

    def __init__(
        self,
        state_manager: StateManager,
        base_url: str = f"http://localhost:{_DEFAULT_PORT}",
        readiness_timeout: float = _READINESS_TIMEOUT_S,
        poll_interval: float = _POLL_INTERVAL_S,
        provider_id: str = _DEFAULT_PROVIDER_ID,
        model_id: str = _DEFAULT_MODEL_ID,
    ) -> None:
        self._state_manager = state_manager
        self._base_url = base_url.rstrip("/")
        self._readiness_timeout = readiness_timeout
        self._poll_interval = poll_interval
        self._provider_id = provider_id
        self._model_id = model_id

        self._process: asyncio.subprocess.Process | None = None
        self._session_id: str | None = None

        # Subscription state (N1-S08).
        self._subscription_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str | None:
        """The active OpenCode session ID, or ``None`` if not yet started."""
        return self._session_id

    async def prompt(
        self,
        session_id: str,
        text: str,
        schema: dict | None = None,
    ) -> None:
        """Send a prompt to an OpenCode session.

        Returns immediately; the agent's response arrives via the persistent
        SSE event subscription opened at startup.

        The endpoint used is the v1 ``POST /session/:id/prompt_async`` path
        (per SSE_CONTRACT.md §D5 and the spike).

        When ``schema`` is provided the request uses OpenCode's native
        structured-output mechanism (ADR-004 / ADR-013):
        ::

            format: {
                type: "json_schema",
                schema: <schema>,
                retryCount: 2,
            }

        Note: v1.15.13 changed the payload shape relative to v1.15.10 (spike):
          - ``text`` top-level field replaced by ``parts: [{"type": "text", "text": ...}]``
          - ``format.json_schema`` wrapper removed; schema is now ``format.schema`` directly
          - ``format.name`` field dropped (no longer part of OutputFormatJsonSchema)
        Both changes confirmed from the /doc OpenAPI spec of the running server.

        Args:
            session_id: The active OpenCode session ID.
            text: The prompt text to send.
            schema: Optional JSON Schema dict.  If ``None``, no ``format``
                block is included and the model returns free-form text.

        Raises:
            httpx.HTTPStatusError: If OpenCode returns a non-2xx response.
        """
        payload: dict = {"parts": [{"type": "text", "text": text}]}
        if schema is not None:
            payload["format"] = {
                "type": "json_schema",
                "schema": schema,
                "retryCount": 2,
            }

        url = f"{self._base_url}/session/{session_id}/prompt_async"
        logger.info("Sending prompt to session %s (schema=%s)", session_id, schema is not None)

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10.0)
            resp.raise_for_status()

        logger.debug("Prompt accepted (HTTP %s)", resp.status_code)

    async def start(self) -> None:
        """Resolve the binary, launch ``opencode serve``, wait for readiness, and create a session.

        Raises:
            RuntimeError: If the ``opencode`` binary is not found on PATH.
            RuntimeError: If the server does not become ready within
                ``readiness_timeout`` seconds.
            RuntimeError: If session creation fails.
        """
        binary = self._resolve_binary()
        await self._launch(binary)
        await self._wait_for_readiness()
        session_id = await self._create_session()
        self._session_id = session_id
        self._state_manager.update(opencode_session_id=session_id)
        logger.info("OpenCode session created: %s", session_id)

    async def abort(self, session_id: str) -> None:
        """POST /session/:id/abort -- best-effort abort (N1-S11).

        Per the spike (SPIKE_REPORT.md §5), abort returns 200 but does NOT reliably
        unblock a stuck turn.  Called as a courtesy before creating a fresh session.
        Errors are swallowed -- they must not interrupt the recovery path.

        Args:
            session_id: The OpenCode session ID to abort.
        """
        url = f"{self._base_url}/session/{session_id}/abort"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url)
            logger.info("Abort POST %s returned %d.", url, response.status_code)
        except Exception as exc:
            logger.warning("Abort POST %s failed (%s) -- continuing to fresh-session.", url, exc)

    async def create_fresh_session(self) -> str:
        """Create a new OpenCode session and return its ID (N1-S11).

        Re-uses ``_create_session()`` internally.  Does NOT update ``_session_id``
        or ``state_manager`` -- the caller (``Watchdog``) is responsible for
        persisting the new session ID via
        ``state_manager.update(opencode_session_id=new_id)``.

        Returns:
            The new session ID string.

        Raises:
            RuntimeError: If session creation fails.
        """
        return await self._create_session()

    async def stop(self) -> None:
        """Terminate the OpenCode process cleanly.

        Sends SIGTERM first.  If the process does not exit within
        ``_SIGKILL_GRACE_S`` seconds, sends SIGKILL.  Safe to call even if
        ``start()`` was never called.
        """
        if self._process is None:
            return

        process = self._process
        self._process = None

        if process.returncode is not None:
            # Already exited.
            logger.debug("OpenCode process already exited (returncode=%s)", process.returncode)
            return

        logger.info("Terminating OpenCode process (SIGTERM)...")
        process.terminate()

        try:
            await asyncio.wait_for(process.wait(), timeout=_SIGKILL_GRACE_S)
            logger.info("OpenCode process exited cleanly.")
        except asyncio.TimeoutError:
            logger.warning("OpenCode process did not exit after SIGTERM — sending SIGKILL.")
            process.kill()
            await process.wait()
            logger.info("OpenCode process killed.")

    async def start_event_subscription(
        self,
        bus: EventBus,
        heartbeat_timeout: float = _HEARTBEAT_TIMEOUT_S,
    ) -> None:
        """Open one persistent GET /event SSE connection; normalise and publish events to bus.

        Designed to run as a background asyncio Task (see ``main.py`` lifespan).
        Reconnects automatically when ``server.heartbeat`` has been absent for
        ``heartbeat_timeout`` seconds.

        Session filtering:
          Events whose ``properties.sessionID`` does not match the current active
          session are silently dropped (SSE_CONTRACT.md §5).  Global events
          (``server.heartbeat``, ``file.edited``, ``server.connected``) carry no
          sessionID and are always processed.

        Args:
            bus: The EventBus onto which normalised events are published.
            heartbeat_timeout: Seconds without a ``server.heartbeat`` before the
                client reconnects.  Defaults to 30 s.
        """
        event_url = f"{self._base_url}/event"
        logger.info("Starting persistent SSE subscription to %s", event_url)

        while True:
            try:
                await self._run_one_connection(bus, event_url, heartbeat_timeout)
                # _run_one_connection returns (rather than raising) when it
                # detects a heartbeat timeout or a clean stream end.
                logger.info("SSE connection ended -- reconnecting.")
            except asyncio.CancelledError:
                logger.info("SSE subscription cancelled -- stopping.")
                raise
            except Exception as exc:
                logger.warning("SSE subscription error (%s) -- will reconnect.", exc)
            # Brief back-off before every reconnect (normal or error) to avoid
            # a tight spin if the server closes the stream immediately.
            await asyncio.sleep(0.1)

    async def _run_one_connection(
        self,
        bus: EventBus,
        event_url: str,
        heartbeat_timeout: float,
    ) -> None:
        """Consume one SSE connection until cancelled or heartbeat timeout fires.

        Uses ``asyncio.wait_for`` on each ``__anext__`` call so that silence
        on the wire (no events arriving) is detected within ``heartbeat_timeout``
        seconds and causes this coroutine to return, prompting a reconnect.

        Args:
            bus: EventBus to publish normalised events onto.
            event_url: Full URL of the OpenCode ``/event`` endpoint.
            heartbeat_timeout: Maximum seconds to wait for the next event before
                treating the connection as stale and returning.
        """
        # N1-S20: QA_FORCE_STALL -- stop emitting after the first event to drive the
        # watchdog abort -> fresh-session path deterministically.  Off by default.
        force_stall = os.environ.get("QA_FORCE_STALL") == "1"
        stall_triggered = False

        async with httpx.AsyncClient(timeout=None) as http_client:
            async with aconnect_sse(http_client, "GET", event_url) as sse_response:
                sse_iter = sse_response.aiter_sse().__aiter__()
                last_heartbeat = asyncio.get_event_loop().time()

                while True:
                    # How long until the heartbeat window closes.
                    remaining = heartbeat_timeout - (
                        asyncio.get_event_loop().time() - last_heartbeat
                    )
                    if remaining <= 0:
                        logger.warning(
                            "No server.heartbeat for %.1fs -- reconnecting.",
                            heartbeat_timeout,
                        )
                        return  # Caller reconnects.

                    try:
                        raw_sse = await asyncio.wait_for(
                            sse_iter.__anext__(),
                            timeout=remaining,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "No server.heartbeat for %.1fs -- reconnecting.",
                            heartbeat_timeout,
                        )
                        return  # Caller reconnects.
                    except StopAsyncIteration:
                        # Stream ended cleanly (server closed it).
                        logger.info("SSE stream ended (StopAsyncIteration) -- will reconnect.")
                        return

                    try:
                        raw = json.loads(raw_sse.data)
                    except (json.JSONDecodeError, AttributeError):
                        logger.debug(
                            "Skipping non-JSON SSE data: %r",
                            getattr(raw_sse, "data", None),
                        )
                        continue

                    event_type: str = raw.get("type", "")
                    properties: dict[str, Any] = raw.get("properties", {})

                    # Heartbeat: reset timer; do NOT publish.
                    if event_type == "server.heartbeat":
                        last_heartbeat = asyncio.get_event_loop().time()
                        logger.debug("server.heartbeat received -- timer reset.")
                        continue

                    # Session filter for session-scoped events.
                    if event_type in _SESSION_SCOPED_TYPES:
                        incoming_session = properties.get("sessionID")
                        active_session = self._state_manager.get_state().get("opencode_session_id")
                        if incoming_session != active_session:
                            logger.debug(
                                "Dropping event %r: sessionID %r != active %r",
                                event_type,
                                incoming_session,
                                active_session,
                            )
                            continue

                    # N1-S20: QA_FORCE_STALL -- emit first event then suppress the rest.
                    if force_stall:
                        if stall_triggered:
                            logger.debug(
                                "QA_FORCE_STALL: suppressing event %r to simulate stall.",
                                event_type,
                            )
                            continue
                        stall_triggered = True
                        logger.info(
                            "QA_FORCE_STALL active: emitting first event %r, then stalling.",
                            event_type,
                        )

                    # Normalise and publish to the bus.
                    await self._normalise_and_publish(event_type, properties, bus)

    async def stop_event_subscription(self) -> None:
        """Cancel the background subscription task cleanly.

        Safe to call even if ``start_event_subscription`` was never scheduled
        as a Task (i.e. when the subscription is awaited directly in tests).
        This method only cancels the stored ``_subscription_task`` handle
        registered via ``_register_subscription_task``.
        """
        if self._subscription_task is not None and not self._subscription_task.done():
            self._subscription_task.cancel()
            try:
                await self._subscription_task
            except asyncio.CancelledError:
                pass
            logger.info("SSE subscription task stopped.")
        self._subscription_task = None

    def _register_subscription_task(self, task: asyncio.Task[None]) -> None:
        """Record the asyncio Task so ``stop_event_subscription`` can cancel it.

        Called from ``main.py`` after
        ``asyncio.create_task(client.start_event_subscription(bus))``.
        """
        self._subscription_task = task

    # ------------------------------------------------------------------
    # Normalisation helpers (SSE_CONTRACT.md §2)
    # ------------------------------------------------------------------

    async def _normalise_and_publish(
        self,
        event_type: str,
        properties: dict[str, Any],
        bus: EventBus,
    ) -> None:
        """Translate a raw OpenCode event into a bus event and publish it.

        Mapping (SSE_CONTRACT.md §2):
          message.part.delta               → message.part
          message.part.updated (text)      → dropped (no delta in updated; use delta event)
          message.part.updated (bash, running) → tool.bash_running
          message.part.updated (bash, completed) → tool.bash_done
          message.part.updated (*, completed, metadata.files) → tool.file_written
          message.part.updated (*, pending) → silently dropped
          session.idle                     → session.idle
          file.edited                      → file.ready
          server.connected                 → logged only
          all others                       → silently dropped (DEBUG log)
        """
        ts = properties.get("time") or int(time.time() * 1000)

        if event_type == "message.part.delta":
            part_id = properties.get("partID") or properties.get("part", {}).get("id", "")
            delta = properties.get("delta", "")
            await bus.publish(
                "message.part",
                {"part_id": part_id, "content": delta, "ts": ts},
            )
            return

        if event_type == "message.part.updated":
            part: dict[str, Any] = properties.get("part", {})
            part_type = part.get("type", "")
            state: dict[str, Any] = part.get("state", {})
            status = state.get("status", "")

            if part_type == "tool":
                tool_name = part.get("tool", "")

                if status == "running" and tool_name == "bash":
                    inp = state.get("input", {})
                    await bus.publish(
                        "tool.bash_running",
                        {
                            "command": inp.get("command", ""),
                            "description": inp.get("description"),
                            "started_at": ts,
                            "ts": ts,
                        },
                    )
                    return

                if status == "completed":
                    metadata: dict[str, Any] = state.get("metadata", {})
                    timing: dict[str, Any] = state.get("time", {})
                    elapsed_ms = timing.get("end", 0) - timing.get("start", 0)

                    # tool.file_written — filter on metadata.files presence (D1: don't
                    # hardcode tool name; any completed tool with files qualifies).
                    files: list[dict[str, Any]] = metadata.get("files") or []
                    if files:
                        for file_entry in files:
                            await bus.publish(
                                "tool.file_written",
                                {
                                    "file": file_entry.get("relativePath", ""),
                                    "op": file_entry.get("type", "modify"),
                                    "additions": file_entry.get("additions", 0),
                                    "deletions": file_entry.get("deletions", 0),
                                    "elapsed_ms": elapsed_ms,
                                    "ts": ts,
                                },
                            )
                        return

                    if tool_name == "bash":
                        inp = state.get("input", {})
                        await bus.publish(
                            "tool.bash_done",
                            {
                                "command": inp.get("command", ""),
                                "exit_code": metadata.get("exit", -1),
                                "elapsed_ms": elapsed_ms,
                                "ts": ts,
                            },
                        )
                        return

                # pending or unrecognised status — drop silently.
                logger.debug(
                    "Dropping message.part.updated: part_type=%r tool=%r status=%r",
                    part_type,
                    tool_name,
                    status,
                )
            else:
                # text or other non-tool part — no delta in updated; drop.
                logger.debug("Dropping message.part.updated: non-tool part_type=%r", part_type)
            return

        if event_type == "session.idle":
            await bus.publish("session.idle", {"ts": ts})
            return

        if event_type == "file.edited":
            path = properties.get("file", "")
            await bus.publish("file.ready", {"path": path, "ts": ts})
            return

        if event_type == "server.connected":
            logger.info("OpenCode SSE connected (server.connected received).")
            return

        # All other events (session.status, session.diff, step-start, step-finish,
        # reasoning, session.next.*) — drop silently per SSE_CONTRACT.md §2 mapping table.
        logger.debug("Dropping unhandled event type: %r", event_type)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_binary() -> str:
        """Return the full path to the ``opencode`` binary.

        Raises:
            RuntimeError: If ``shutil.which("opencode")`` returns ``None``.
        """
        path = shutil.which("opencode")
        if path is None:
            raise RuntimeError(
                "opencode binary not found on PATH.  "
                "Install opencode (https://opencode.ai/install) and ensure it is "
                "accessible in the current PATH before starting the backend."
            )
        logger.debug("Resolved opencode binary: %s", path)
        return path

    async def _launch(self, binary: str) -> None:
        """Spawn ``opencode serve`` as a background subprocess.

        Args:
            binary: Full filesystem path to the opencode binary.
        """
        logger.info("Launching OpenCode: %s serve --port %d", binary, _DEFAULT_PORT)
        self._process = await asyncio.create_subprocess_exec(
            binary,
            "serve",
            "--port",
            str(_DEFAULT_PORT),
            # Redirect streams so the subprocess doesn't inherit the parent's
            # terminal.  Errors are suppressed (not piped to avoid blocking);
            # the process logs to its own mechanism.
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        logger.debug("OpenCode process started with PID %s", self._process.pid)

    async def _wait_for_readiness(self) -> None:
        """Poll ``GET /health`` until the server responds 200 or the timeout expires.

        The spike confirmed that ``opencode serve`` listens on ``/health`` (the
        same endpoint this FastAPI app exposes).  The readiness poll uses a
        fresh ``httpx.AsyncClient`` per attempt to avoid connection-reuse
        issues during the short window when the server is not yet listening.

        Raises:
            RuntimeError: If the server does not become ready within
                ``self._readiness_timeout`` seconds.
        """
        health_url = f"{self._base_url}/health"
        deadline = asyncio.get_event_loop().time() + self._readiness_timeout

        logger.info(
            "Waiting for OpenCode readiness at %s (timeout=%ss)...",
            health_url,
            self._readiness_timeout,
        )

        async with httpx.AsyncClient(timeout=2.0) as client:
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise RuntimeError(
                        f"OpenCode server timed out waiting for readiness at {health_url} "
                        f"(timeout={self._readiness_timeout}s).  "
                        "Check that opencode serve started correctly."
                    )

                try:
                    response = await client.get(health_url)
                    if response.status_code == 200:
                        logger.info("OpenCode server is ready.")
                        return
                    logger.debug("Health check returned %d — retrying.", response.status_code)
                except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as exc:
                    logger.debug("Health check connection error (%s) — retrying.", exc)

                await asyncio.sleep(self._poll_interval)

    async def _create_session(self) -> str:
        """POST to the v1 /session endpoint and return the new session ID.

        Does NOT update ``_session_id`` or ``state_manager`` -- the caller is
        responsible for those side effects.  This makes the method reusable from
        both ``start()`` and ``create_fresh_session()``.

        Uses provider ``openai`` via OAuth (per spike §2 -- no API key env var
        needed; auth.json is read by OpenCode automatically).

        Returns:
            The new session ID string.

        Raises:
            RuntimeError: If the session create call returns a non-2xx status
                or the response JSON does not contain an ``id`` field.
        """
        session_url = f"{self._base_url}{_SESSION_PATH}"
        payload: dict[str, Any] = {
            "providerID": self._provider_id,
            "modelID": self._model_id,
        }

        logger.info(
            "Creating OpenCode session (providerID=%s, modelID=%s)...",
            self._provider_id,
            self._model_id,
        )

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(session_url, json=payload)

        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"OpenCode session creation failed: HTTP {response.status_code} "
                f"from POST {session_url}.  Body: {response.text[:200]}"
            )

        body = response.json()
        session_id: str | None = body.get("id")
        if not session_id:
            raise RuntimeError(
                f"OpenCode session create response missing 'id' field.  Body: {body}"
            )

        return session_id
