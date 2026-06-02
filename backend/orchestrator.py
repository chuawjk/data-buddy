"""Stage orchestrator -- setup → profiling state machine.

This module implements the first two stages of the Data Buddy state machine:
``setup`` and ``profiling``.  The planning and building stages (Night 2) will
extend this module further.

Architecture boundaries (from backlog):
- The orchestrator calls the OpenCode client through the narrow interface only:
  ``client.prompt(session_id, text, schema=None)``.
- The state machine never imports ``httpx``.
- The client never imports the orchestrator.
- Domain events (``stage.changed``) flow through the bus.

State transitions implemented here:
  setup → profiling   (via ``setup_complete``)

Night 2 will add:
  profiling → planning
  planning → building
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.event_bus import EventBus
    from backend.opencode_client import OpenCodeClient
    from backend.state_manager import StateManager

logger = logging.getLogger(__name__)


class Orchestrator:
    """Stage orchestrator for the Data Buddy pipeline.

    Coordinates state transitions, event publication, and OpenCode prompt
    dispatch across the pipeline stages.  Holds references to the
    ``StateManager``, the ``EventBus``, and the ``OpenCodeClient`` (the
    narrow interface only -- never ``httpx`` directly).

    Args:
        state_manager: Reads current state and persists mutations.
        bus: In-process pub/sub bus for domain and activity events.
        client: OpenCode client -- called only via ``client.prompt()``.
            May be ``None`` when OpenCode is disabled (e.g. in CI).
        workspace_root: Root of the workspace directory.  Defaults to
            ``workspace/`` relative to the working directory.  Tests pass
            a ``tmp_path``-based path for isolation.
    """

    def __init__(
        self,
        state_manager: "StateManager",
        bus: "EventBus",
        client: "OpenCodeClient | None" = None,
        workspace_root: Path = Path("workspace"),
    ) -> None:
        self._state_manager = state_manager
        self._bus = bus
        self._client = client
        self._workspace_root = Path(workspace_root)

    # ------------------------------------------------------------------
    # Stage transitions
    # ------------------------------------------------------------------

    async def setup_complete(self, dataset: str, aim: str) -> None:
        """Transition from setup → profiling and trigger the profile turn.

        Called by ``POST /setup`` after the CSV file and initial state are
        written to disk.  Performs two synchronous operations then fires the
        profile prompt as a background task so the HTTP response is not
        blocked on the OpenCode round-trip.

        Steps:
        1. Persist ``stage=profiling``, ``dataset``, and ``aim`` via the
           state manager (atomic write).
        2. Publish ``stage.changed`` on the event bus.
        3. If a session ID is stored, schedule ``_run_profile_turn`` as a
           fire-and-forget ``asyncio.Task``.

        Args:
            dataset: The filename of the uploaded dataset (e.g. ``"data.csv"``).
            aim: The user's stated aim of investigation.
        """
        # 1. Persist the transition.
        self._state_manager.update(stage="profiling", dataset=dataset, aim=aim)

        # 2. Emit the domain event.
        await self._bus.publish("stage.changed", {"stage": "profiling"})

        # 3. Fire the profiling turn (if we have a session to send it to).
        session_id = self._state_manager.get_state().get("opencode_session_id")
        if session_id and self._client is not None:
            prompt_text = self._build_profile_prompt(dataset, aim)
            asyncio.create_task(
                self._run_profile_turn(session_id, prompt_text),
                name="profile-turn",
            )
        else:
            logger.debug(
                "setup_complete: skipping profile turn (session_id=%r, client=%r)",
                session_id,
                self._client,
            )

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_profile_prompt(self, dataset: str, aim: str) -> str:
        """Return the text to send to OpenCode for the profiling turn.

        Tries to import ``build_profile_prompt`` from ``backend.prompts.profile``
        (added by N1-S09).  Falls back to a minimal placeholder so this story
        (N1-S04) is independently deliverable.

        Args:
            dataset: Dataset filename (e.g. ``"data.csv"``).
            aim: The user's stated aim of investigation.

        Returns:
            A non-empty prompt string.
        """
        try:
            from backend.prompts.profile import build_profile_prompt  # noqa: PLC0415

            return build_profile_prompt(dataset, aim)
        except ImportError:
            logger.debug(
                "_build_profile_prompt: backend.prompts.profile not yet available "
                "(N1-S09 not merged); using placeholder."
            )
            return f"Profile the dataset at workspace/data/{dataset} with aim: {aim}"

    # ------------------------------------------------------------------
    # Fire-and-forget helpers
    # ------------------------------------------------------------------

    async def _run_profile_turn(self, session_id: str, prompt: str) -> None:
        """Send the profiling prompt to OpenCode and handle errors.

        This coroutine is scheduled as a fire-and-forget ``asyncio.Task``
        by ``setup_complete``.  Any exception (e.g. the client is unavailable)
        is caught here and converted into a ``turn.error`` bus event so the
        frontend is notified rather than the error silently disappearing.

        The JSON schema for structured output is sourced from
        ``backend.prompts.profile.PROFILE_SCHEMA`` when available (N1-S09).
        If that import fails, no schema is passed (``schema=None``).

        Args:
            session_id: The active OpenCode session ID.
            prompt: The profile prompt text to send.
        """
        schema: Any = self._load_profile_schema()

        assert self._client is not None  # guarded by caller
        try:
            await self._client.prompt(session_id, prompt, schema=schema)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Profile turn failed: %s", exc)
            await self._bus.publish("turn.error", {"message": str(exc)})

    @staticmethod
    def _load_profile_schema() -> Any:
        """Return the profile JSON schema for structured output, or ``None``.

        Attempts to import ``PROFILE_SCHEMA`` from ``backend.prompts.profile``
        (N1-S09).  Returns ``None`` if the module is not yet available so that
        N1-S04 remains independently deliverable.
        """
        try:
            from backend.prompts.profile import PROFILE_SCHEMA  # noqa: PLC0415

            return PROFILE_SCHEMA
        except ImportError:
            return None
