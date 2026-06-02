"""OpenCode process management and session lifecycle.

Responsibilities:
- Resolve the ``opencode`` binary via ``shutil.which`` at startup (raises
  clearly if not found — no PATH-assumed launch).
- Launch ``opencode serve`` as a managed subprocess.
- Poll ``GET /health`` until the server is ready or the readiness timeout
  expires.
- Create a single session via the **v1 /session** API and persist the session
  ID to ``state.json`` through the ``StateManager``.
- Tear down the subprocess cleanly on shutdown (SIGTERM, then SIGKILL after 5 s).

Out of scope (later stories):
- The persistent ``GET /event`` SSE subscription (N1-S08).
- ``prompt()`` / event iteration (N1-S08).
- Watchdog abort/recovery (N1-S11).

Hard boundary: this module never imports the orchestrator.  The orchestrator
calls this client through the narrow interface only.  ``httpx`` is imported
here; the orchestrator must not import ``httpx`` directly.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any

import httpx

from backend.state_manager import StateManager

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

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str | None:
        """The active OpenCode session ID, or ``None`` if not yet started."""
        return self._session_id

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
        await self._create_session()

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

    async def _create_session(self) -> None:
        """POST to the v1 /session endpoint and persist the session ID.

        Uses provider ``openai`` via OAuth (per spike §2 — no API key env var
        needed; auth.json is read by OpenCode automatically).

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

        self._session_id = session_id
        self._state_manager.update(opencode_session_id=session_id)
        logger.info("OpenCode session created: %s", session_id)
