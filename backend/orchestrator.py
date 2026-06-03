"""Stage orchestrator -- setup → profiling → planning state machine.

This module implements the first three stages of the Data Buddy state machine:
``setup``, ``profiling``, and ``planning``.  The building stage (Night 2/3)
will extend this module further.

Architecture boundaries (from backlog):
- The orchestrator calls the OpenCode client through the narrow interface only:
  ``client.prompt(session_id, text, schema=None)``.
- The state machine never imports ``httpx``.
- The client never imports the orchestrator.
- Domain events (``stage.changed``) flow through the bus.

State transitions implemented here:
  setup → profiling   (via ``setup_complete``)
  profiling → planning  (N2-S01/N2-S02: via ``session.idle`` → plan.json read)

N2-S02: ``session.idle`` during planning stage reads ``plan.json`` from disk,
validates it, injects ``status: "queued"`` on each section, persists to state,
and emits ``plan.ready``.  ``session.idle`` dispatch is now stage-aware.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.event_bus import EventBus
    from backend.opencode_client import OpenCodeClient
    from backend.state_manager import StateManager
    from backend.watchdog import Watchdog

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
        watchdog: Optional Watchdog instance.  When provided, ``start_turn()``
            is called at the start of every agent-driven turn so the watchdog
            can abort and recover a stalled turn.  May be ``None`` (e.g. in
            CI or when OpenCode is disabled).
    """

    def __init__(
        self,
        state_manager: "StateManager",
        bus: "EventBus",
        client: "OpenCodeClient | None" = None,
        workspace_root: Path = Path("workspace"),
        watchdog: "Watchdog | None" = None,
    ) -> None:
        self._state_manager = state_manager
        self._bus = bus
        self._client = client
        self._workspace_root = Path(workspace_root)
        self._watchdog = watchdog

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

    async def re_profile(self, text: str) -> None:
        """Called by POST /turn during the profiling stage.

        Fires a new profiling turn with a re-profile prompt that incorporates
        the user's bottom-bar text.  Returns immediately; the turn runs as a
        fire-and-forget asyncio task so ``POST /turn`` can respond with 204
        without waiting for OpenCode.

        The watchdog (if wired in via ``__init__``) is armed before the turn
        fires so recovery can trigger if the turn stalls.

        Args:
            text: The user's bottom-bar input (already stripped by the router).

        Raises:
            ValueError: If no session ID is stored in state (OpenCode not started).
            ValueError: If the current stage is not ``"profiling"`` (wrong stage).
        """
        state = self._state_manager.get_state()
        session_id: str | None = state.get("opencode_session_id")
        if not session_id:
            raise ValueError("No active session")

        current_stage: str = state.get("stage", "")
        if current_stage != "profiling":
            raise ValueError(
                f"re_profile only valid in profiling stage; current stage: {current_stage!r}"
            )

        dataset: str = state.get("dataset") or ""
        aim: str = state.get("aim") or ""
        user_note = f"\n\nUser re-profile note: {text}" if text else ""
        prompt = self._build_profile_prompt(dataset, aim + user_note)

        # Arm the watchdog before firing the turn (N1-S11 / N1-S20).
        if self._watchdog is not None:
            self._watchdog.start_turn()

        # fire-and-forget; watchdog handles timeout / recovery.
        # _run_profile_turn loads the schema internally via _load_profile_schema().
        assert self._client is not None  # noqa: S101  # guarded by session check above
        asyncio.create_task(
            self._run_profile_turn(session_id, prompt),
            name="re-profile-turn",
        )

    # ------------------------------------------------------------------
    # Bus listener — session.idle → stage output handling
    # ------------------------------------------------------------------

    async def start_bus_listener(self) -> None:
        """Subscribe to the EventBus and handle internal events.

        This coroutine runs as a fire-and-forget asyncio Task in the lifespan
        (``main.py``).  It consumes every bus event and routes stage-completion
        signals to the appropriate handler.

        Currently handled:
          - ``session.idle`` in profiling stage → ``_handle_profile_idle``
          - ``session.idle`` in planning stage → ``_handle_plan_idle``  (N2-S02)
        """
        subscription = self._bus.subscribe()
        try:
            async for envelope in subscription:
                event_type: str = envelope.get("type", "")
                if event_type == "session.idle":
                    stage = self._state_manager.get_state().get("stage", "")
                    if stage == "profiling":
                        await self._handle_profile_idle()
                    elif stage == "planning":
                        await self._handle_plan_idle()
                    else:
                        logger.debug("session.idle: no handler for stage=%r", stage)
        except asyncio.CancelledError:
            logger.info("Orchestrator bus listener cancelled.")
            raise

    async def _handle_profile_idle(self) -> None:
        """Called when ``session.idle`` fires during the profiling stage.

        Reads ``workspace/profile.json``, validates it against ``PROFILE_SCHEMA``,
        updates ``state.json`` with the parsed profile, and emits ``profile.ready``
        on the bus.  If the file is absent or invalid, logs a warning and returns
        without emitting (the watchdog will handle timeout recovery if needed).
        """
        state = self._state_manager.get_state()
        current_stage: str = state.get("stage", "")
        if current_stage != "profiling":
            # session.idle fires for every turn, not just profiling; ignore others.
            logger.debug("_handle_profile_idle: ignoring (stage=%r)", current_stage)
            return

        profile_path = self._workspace_root / "profile.json"
        if not profile_path.exists():
            logger.warning(
                "_handle_profile_idle: %s not found; profiling output may be missing.",
                profile_path,
            )
            return

        try:
            raw = profile_path.read_text(encoding="utf-8")
            profile: dict[str, Any] = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("_handle_profile_idle: failed to read/parse profile.json: %s", exc)
            return

        # Validate required top-level fields (soft validation — emit even if extra
        # fields are present; hard-fail only if required keys are missing).
        required = {"shape", "columns", "flags"}
        if not required.issubset(profile.keys()):
            missing = required - profile.keys()
            logger.error(
                "_handle_profile_idle: profile.json missing required fields: %s",
                missing,
            )
            return

        # Persist the profile into state.json so GET /state returns it.
        self._state_manager.update(profile=profile)

        ts = int(time.time() * 1000)
        await self._bus.publish("profile.ready", {"profile": profile, "ts": ts})
        logger.info("profile.ready emitted (ts=%d)", ts)

    async def _handle_plan_idle(self) -> None:
        """Called when ``session.idle`` fires during the planning stage.

        Reads ``workspace/plan.json``, validates it has ``sections`` (3–6 entries,
        each with ``id``, ``title``, ``hypothesis``), injects ``status: "queued"``
        on each section, updates ``state.json``, and emits ``plan.ready``.

        If the file is absent or the output is invalid, emits ``turn.error``
        with ``stage="planning"`` and ``reason="structured_output_failed"``.

        N2-S02.
        """
        state = self._state_manager.get_state()
        current_stage: str = state.get("stage", "")
        if current_stage != "planning":
            logger.debug("_handle_plan_idle: ignoring (stage=%r)", current_stage)
            return

        plan_path = self._workspace_root / "plan.json"

        async def _emit_error(reason: str) -> None:
            ts = int(time.time() * 1000)
            await self._bus.publish(
                "turn.error",
                {"stage": "planning", "reason": reason, "ts": ts},
            )

        # Read and parse plan.json.
        if not plan_path.exists():
            logger.warning("_handle_plan_idle: %s not found.", plan_path)
            await _emit_error("structured_output_failed")
            return

        try:
            raw = plan_path.read_text(encoding="utf-8")
            plan_data: dict[str, Any] = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("_handle_plan_idle: failed to read/parse plan.json: %s", exc)
            await _emit_error("structured_output_failed")
            return

        # Validate sections field.
        sections = plan_data.get("sections")
        if not isinstance(sections, list):
            logger.error("_handle_plan_idle: sections is not a list (got %r)", type(sections))
            await _emit_error("structured_output_failed")
            return

        if not (3 <= len(sections) <= 6):
            logger.error("_handle_plan_idle: sections count %d outside [3, 6]", len(sections))
            await _emit_error("structured_output_failed")
            return

        # Validate each section has required fields.
        required_fields = {"id", "title", "hypothesis"}
        for section in sections:
            if not isinstance(section, dict) or not required_fields.issubset(section.keys()):
                missing = required_fields - set(section.keys() if isinstance(section, dict) else [])
                logger.error("_handle_plan_idle: section missing required fields: %s", missing)
                await _emit_error("structured_output_failed")
                return

        # Inject status: "queued" on each section (schema does not include status;
        # orchestrator injects it per TL note N2-S02).
        sections_with_status = [{**s, "status": "queued"} for s in sections]

        # Persist to state.json.
        self._state_manager.update(plan=sections_with_status)

        # Emit plan.ready.
        ts = int(time.time() * 1000)
        await self._bus.publish(
            "plan.ready",
            {"sections": sections_with_status, "ts": ts},
        )
        logger.info("plan.ready emitted (%d sections, ts=%d)", len(sections_with_status), ts)

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

            return build_profile_prompt(dataset, aim, self._workspace_root.resolve())
        except ImportError:
            logger.debug(
                "_build_profile_prompt: backend.prompts.profile not yet available "
                "(N1-S09 not merged); using placeholder."
            )
            ws = self._workspace_root.resolve()
            return f"Profile the dataset at {ws / 'data' / dataset} with aim: {aim}"

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
