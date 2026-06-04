"""Stage orchestrator -- setup → profiling → planning → building state machine.

This module implements all four stages of the Data Buddy state machine:
``setup``, ``profiling``, ``planning``, and ``building``.

Architecture boundaries (from backlog):
- The orchestrator calls the OpenCode client through the narrow interface only:
  ``client.prompt(session_id, text, schema=None)``.
- The state machine never imports ``httpx``.
- The client never imports the orchestrator.
- Domain events (``stage.changed``) flow through the bus.

State transitions implemented here:
  setup → profiling   (via ``setup_complete``)
  profiling → planning  (via ``_handle_planning_transition``, triggered on ``profile.ready``)

N2-S02: ``session.idle`` during planning stage reads ``plan.json`` from disk,
validates it, injects ``status: "proposed"`` on each section, persists to
state, and emits ``plan.ready``.  ``session.idle`` dispatch is now stage-aware.

N2-S03: ``_handle_plan_idle`` now also writes the canonical ``plan.json`` to
the workspace using atomic tmp+rename semantics, and uses status ``"proposed"``
(sections are proposed to the user, awaiting plan acceptance).

N2-S07: ``session.idle`` during building stage checks for the section file
triplet (``analyses/*.py``, ``charts/*.png``, ``sections/*.md``) and emits
either ``section.proposed`` (triplet present) or ``section.failed`` (files
missing).  ``start_build_section`` emits ``section.building`` immediately
after dispatching the section prompt and arms the watchdog.

N2-S20: ``QA_FORCE_SECTION_FAIL=1`` env-var seam in ``_handle_section_idle``.
When set, the ``.md`` artefact is removed before the triplet check so that
``section.failed`` fires deterministically for QA without model misbehaviour.
Off by default; zero production-path impact.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.agent.opencode_client import OpenCodeClient
    from backend.core.event_bus import EventBus
    from backend.core.state_manager import StateManager
    from backend.core.watchdog import Watchdog

logger = logging.getLogger(__name__)

# Section builds write three files and run arbitrary analysis code — they take
# significantly longer than profiling or planning turns.  Give them 3× the
# default 60 s watchdog budget.
_SECTION_WATCHDOG_TIMEOUT: int = 180


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

    async def accept_plan(self) -> None:
        """Transition from planning → building and trigger the first section turn.

        Called by ``POST /plan/accept``.  Returns immediately; section build
        runs as a fire-and-forget asyncio Task.

        Steps:
        1. Guard: if stage is already ``"building"`` return silently (idempotent).
        2. Guard: if stage is not ``"planning"`` log and return.
        3. Persist ``stage=building`` via state manager.
        4. Emit ``stage.changed`` with ``{"stage": "building"}``.
        5. Find the first section in the plan with ``status="proposed"``.
        6. If none, log and return (degenerate empty/all-accepted plan).
        7. Build the section prompt via ``_build_section_prompt()``.
        8. Arm the watchdog if wired.
        9. Schedule ``_run_section_turn`` as a fire-and-forget task.

        N2-S05.
        """
        state = self._state_manager.get_state()
        current_stage: str = state.get("stage", "")

        # Idempotent: already in building stage.
        if current_stage == "building":
            logger.debug("accept_plan: already in building stage — no-op (idempotent)")
            return

        if current_stage != "planning":
            logger.warning(
                "accept_plan: called in unexpected stage %r (expected planning)", current_stage
            )
            return

        # 1. Persist the transition.
        self._state_manager.update(stage="building")

        # 2. Emit the domain event.
        ts = int(time.time() * 1000)
        await self._bus.publish("stage.changed", {"stage": "building", "ts": ts})
        logger.info("accept_plan: stage.changed → building (ts=%d)", ts)

        # 3. Transition all "proposed" plan sections → "queued" (accepted into
        #    the build queue but not yet built; "proposed" will be reused to
        #    mean "artefacts ready for user review" after each section completes).
        plan: list[dict[str, Any]] = state.get("plan", [])
        queued_plan = [
            {**s, "status": "queued"} if s.get("status") == "proposed" else s for s in plan
        ]
        self._state_manager.update(plan=queued_plan)
        plan = queued_plan

        # 4. Find the first queued section to build.
        first_section: dict[str, Any] | None = next(
            (s for s in plan if s.get("status") == "queued"),
            None,
        )
        if first_section is None:
            logger.warning("accept_plan: no queued sections in plan — no section turn fired")
            return

        # 5. Guard: need an active session to fire a turn.
        session_id: str | None = self._state_manager.get_state().get("opencode_session_id")
        if not session_id or self._client is None:
            logger.debug(
                "accept_plan: skipping section turn (session_id=%r, client=%r)",
                session_id,
                self._client,
            )
            return

        # 6. Delegate to start_build_section — it emits section.building, persists
        #    status="building" to state.json, arms the watchdog, and fires the task.
        #    Doing it inline here would bypass that state write, causing _handle_section_idle
        #    to find no "building" section and silently skip proposal + sequencing.
        section_index = plan.index(first_section) + 1  # 1-based index
        profile: dict[str, Any] = state.get("profile") or {}
        await self.start_build_section(
            section_id=first_section["id"],
            section_index=section_index,
            title=first_section["title"],
            hypothesis=first_section.get("hypothesis", ""),
            profile=profile,
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

    async def re_plan(self, text: str) -> None:
        """Called by POST /turn during the planning stage.

        Fires a new planning turn with a revision prompt that incorporates the
        user's bottom-bar text.  Returns immediately; the turn runs as a
        fire-and-forget asyncio task so ``POST /turn`` can respond with 204
        without waiting for OpenCode.

        The watchdog (if wired in via ``__init__``) is armed before the turn
        fires so recovery can trigger if the turn stalls.

        Args:
            text: The user's bottom-bar revision instruction (already stripped
                by the router).

        Raises:
            ValueError: If no session ID is stored in state (OpenCode not started).
            ValueError: If the current stage is not ``"planning"`` (wrong stage).
        """
        state = self._state_manager.get_state()
        session_id: str | None = state.get("opencode_session_id")
        if not session_id:
            raise ValueError("No active session")

        current_stage: str = state.get("stage", "")
        if current_stage != "planning":
            raise ValueError(
                f"re_plan only valid in planning stage; current stage: {current_stage!r}"
            )

        dataset: str = state.get("dataset") or ""
        aim: str = state.get("aim") or ""
        profile: dict[str, Any] = state.get("profile") or {}
        base_prompt = self._build_plan_prompt(dataset, aim, profile)
        prompt = (
            f"{base_prompt}\n\n"
            f"The user has reviewed the current draft plan and requests the following revision: "
            f"{text}\n\n"
            "Revise the plan accordingly and overwrite plan.json with the updated sections."
        )

        if self._watchdog is not None:
            self._watchdog.start_turn()

        assert self._client is not None  # noqa: S101  # guarded by session check above
        asyncio.create_task(
            self._run_plan_turn(session_id, prompt),
            name="re-plan-turn",
        )

    async def redirect_section(self, text: str, section_id: str | None = None) -> None:
        """Called by POST /turn during the building stage (Stage 4b).

        Fires a redirect turn for a specific section.  The user's natural-language
        instruction is incorporated into a redirect prompt that tells OpenCode
        to discard any draft artefacts and rebuild from scratch.

        Steps:
        1. Validate: session ID must be set and stage must be ``"building"``.
        2. Find the requested section, or fall back to the active building section.
        3. Delete any draft files for that section from disk.
        4. Build the redirect prompt via ``build_redirect_prompt()``.
        5. Arm the watchdog.
        6. Fire-and-forget ``_run_section_turn()``.

        Args:
            text: The user's redirect instruction (already stripped
                by the router).
            section_id: Optional exact section ID supplied by the UI.

        Raises:
            ValueError: If no session ID is stored in state.
            ValueError: If the current stage is not ``"building"``.

        N2-S12.
        """
        state = self._state_manager.get_state()
        session_id: str | None = state.get("opencode_session_id")
        if not session_id:
            raise ValueError("No active session")

        current_stage: str = state.get("stage", "")
        if current_stage != "building":
            raise ValueError(
                f"redirect_section only valid in building stage; current stage: {current_stage!r}"
            )

        plan: list[dict[str, Any]] = state.get("plan") or []
        target_section = self._select_redirect_target(plan, section_id)
        if target_section is None:
            logger.debug(
                "redirect_section: no redirectable section matched section_id=%r; no-op",
                section_id,
            )
            return

        section_id: str = target_section.get("id", "")
        title: str = target_section.get("title", "")
        hypothesis: str = target_section.get("hypothesis", "")
        section_index: int = target_section.get("index") or next(
            (i + 1 for i, s in enumerate(plan) if s.get("id") == section_id),
            1,
        )
        slug: str = target_section.get("slug", "")

        if not slug:
            from backend.agent.prompts.section import _make_slug  # noqa: PLC0415

            slug = _make_slug(title)

        dataset: str = state.get("dataset") or ""
        aim: str = state.get("aim") or ""
        profile: dict[str, Any] = state.get("profile") or {}

        # Delete prior draft files before dispatching the redirect prompt.
        # This guarantees clean state even if OpenCode partially wrote them.
        nn = str(section_index).zfill(2)
        base_name = f"sec_{nn}_{slug}"
        draft_paths = {
            self._workspace_root / sub_dir / f"{base_name}{ext}"
            for sub_dir, ext in [("analyses", ".py"), ("charts", ".png"), ("sections", ".md")]
        }
        for key in ("py_path", "png_path", "md_path"):
            rel_path = target_section.get(key)
            if rel_path:
                draft_paths.add(self._workspace_root / rel_path)

        for draft_path in draft_paths:
            if draft_path.exists() and draft_path.is_file():
                try:
                    draft_path.unlink()
                    logger.debug("redirect_section: deleted draft %s", draft_path)
                except OSError as exc:
                    logger.warning(
                        "redirect_section: could not delete %s: %s",
                        draft_path,
                        exc,
                    )

        # Move the section back into the active build state before dispatching
        # the prompt, so GET /state and the session.idle handler agree on which
        # section is being rebuilt.
        updated_plan = [
            {
                **s,
                "status": "building",
                "index": section_index,
                "slug": slug,
                "py_path": None,
                "png_path": None,
                "md_path": None,
            }
            if s.get("id") == section_id
            else s
            for s in plan
        ]
        self._state_manager.update(plan=updated_plan)

        ts = int(time.time() * 1000)
        await self._bus.publish(
            "section.building",
            {"section_id": section_id, "title": title, "ts": ts},
        )

        # Build the redirect prompt.
        prompt_text = self._build_redirect_prompt(
            section_id=section_id,
            section_index=section_index,
            title=title,
            hypothesis=hypothesis,
            aim=aim,
            dataset=dataset,
            profile=profile,
            plan=plan,
            redirect_text=text,
        )

        # Arm the watchdog with extended timeout for section builds.
        if self._watchdog is not None:
            self._watchdog.start_turn(timeout=_SECTION_WATCHDOG_TIMEOUT)

        # Fire-and-forget.
        assert self._client is not None  # noqa: S101  # guarded by session check above
        asyncio.create_task(
            self._run_section_turn(session_id, prompt_text),
            name=f"redirect-turn-{section_id}",
        )

    # ------------------------------------------------------------------
    # Bus listener — session.idle / profile.ready → stage output handling
    # ------------------------------------------------------------------

    async def accept_profile(self) -> None:
        """Transition from profiling → planning and trigger the plan turn.

        Called by ``POST /profile/accept`` after the user reviews the profile
        and explicitly accepts it.  Returns immediately; the plan turn runs as
        a fire-and-forget asyncio Task.

        Delegates to ``_handle_planning_transition`` which handles the stage
        guard, state persistence, event emission, and plan turn dispatch.
        """
        await self._handle_planning_transition()

    async def start_bus_listener(self) -> None:
        """Subscribe to the EventBus and handle internal events.

        This coroutine runs as a fire-and-forget asyncio Task in the lifespan
        (``main.py``).  It consumes every bus event and routes stage-completion
        signals to the appropriate handler.

        Currently handled:
          - ``session.idle`` in profiling stage → ``_handle_profile_idle``
          - ``session.idle`` in planning stage → ``_handle_plan_idle``  (N2-S02)
          - ``session.idle`` in building stage → ``_handle_section_idle``  (N2-S07)

        Note: ``profile.ready`` no longer auto-advances to planning.  The user
        must explicitly call ``POST /profile/accept`` to trigger the transition.
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
                    elif stage == "building":
                        await self._handle_section_idle()
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

    async def _handle_planning_transition(self) -> None:
        """Called when ``profile.ready`` fires — transitions profiling → planning.

        Steps:
        1. Guard: if current stage is not ``profiling``, return early (idempotent).
        2. Persist ``stage=planning`` via state manager.
        3. Emit ``stage.changed`` with ``{"stage": "planning"}``.
        4. If client and session ID are present, arm the watchdog and schedule
           ``_run_plan_turn`` as a fire-and-forget task.

        N2-S01.
        """
        state = self._state_manager.get_state()
        current_stage: str = state.get("stage", "")
        if current_stage != "profiling":
            logger.debug(
                "_handle_planning_transition: ignoring (stage=%r, expected profiling)",
                current_stage,
            )
            return

        # 1. Persist the transition.
        self._state_manager.update(stage="planning")

        # 2. Emit the domain event.
        ts = int(time.time() * 1000)
        await self._bus.publish("stage.changed", {"stage": "planning", "ts": ts})
        logger.info("stage.changed: planning (ts=%d)", ts)

        # 3. Fire the plan turn if we have a session.
        session_id = self._state_manager.get_state().get("opencode_session_id")
        if session_id and self._client is not None:
            dataset: str = state.get("dataset") or ""
            aim: str = state.get("aim") or ""
            profile: dict[str, Any] = state.get("profile") or {}
            prompt_text = self._build_plan_prompt(dataset, aim, profile)

            # Arm the watchdog before firing the turn (same pattern as profiling).
            if self._watchdog is not None:
                self._watchdog.start_turn()

            asyncio.create_task(
                self._run_plan_turn(session_id, prompt_text),
                name="plan-turn",
            )
        else:
            logger.debug(
                "_handle_planning_transition: skipping plan turn (session_id=%r, client=%r)",
                session_id,
                self._client,
            )

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

        # Inject status: "proposed" on each section (N2-S03: the plan has been
        # proposed to the user and is awaiting their review / acceptance).
        # Status lives in state.json only; the canonical plan.json on disk stores
        # raw sections without status.
        sections_with_status = [
            {**s, "status": "proposed", "py_path": None, "png_path": None, "md_path": None}
            for s in sections
        ]

        # Persist to state.json (sections carry the status).
        self._state_manager.update(plan=sections_with_status)

        # Write canonical plan.json to workspace (raw sections, no status).
        # Uses atomic tmp+rename so a mid-write kill never corrupts the file.
        # N2-S03.
        self._write_plan_json(plan_path, sections)

        # Emit plan.ready.
        ts = int(time.time() * 1000)
        await self._bus.publish(
            "plan.ready",
            {"sections": sections_with_status, "ts": ts},
        )
        logger.info("plan.ready emitted (%d sections, ts=%d)", len(sections_with_status), ts)

    async def start_build_section(
        self,
        section_id: str,
        section_index: int,
        title: str,
        hypothesis: str,
        profile: dict[str, Any],
    ) -> None:
        """Dispatch the section build prompt and emit ``section.building``.

        Called by the accept-plan flow (N2-S05) or the sequential section loop
        (N3-S01) when the next section should be built.  Returns immediately;
        the turn runs as a fire-and-forget ``asyncio.Task``.

        Steps:
        1. Validate: session ID must be set.
        2. Emit ``section.building`` domain event (before the OpenCode round-trip).
        3. Arm the watchdog (if wired).
        4. Fire-and-forget ``_run_section_turn``.

        Args:
            section_id: Section identifier (e.g. ``"sec_01"``).
            section_index: 1-based ordinal position in the plan array.
            title: Section title from plan.
            hypothesis: Section hypothesis from plan.
            profile: Full parsed profile dict.

        Raises:
            ValueError: If no session ID is stored (OpenCode not started).

        N2-S07.
        """
        state = self._state_manager.get_state()
        session_id: str | None = state.get("opencode_session_id")
        if not session_id:
            raise ValueError("No active session")

        dataset: str = state.get("dataset") or ""
        aim: str = state.get("aim") or ""
        plan: list[Any] = state.get("plan") or []

        # 1. Emit section.building BEFORE the OpenCode round-trip so the SPA
        #    gets the signal immediately (SSE_CONTRACT.md §2.1).
        ts = int(time.time() * 1000)
        await self._bus.publish(
            "section.building",
            {"section_id": section_id, "title": title, "ts": ts},
        )
        logger.info("section.building emitted: %s (ts=%d)", section_id, ts)

        # Persist status=building (and index) so GET /state reflects live build state
        # and _handle_section_idle can derive the artefact filename reliably.
        updated_plan = [
            {**s, "status": "building", "index": section_index} if s.get("id") == section_id else s
            for s in plan
        ]
        self._state_manager.update(plan=updated_plan)

        # 2. Build the section prompt.
        prompt_text = self._build_section_prompt(
            section_id=section_id,
            section_index=section_index,
            title=title,
            hypothesis=hypothesis,
            aim=aim,
            dataset=dataset,
            profile=profile,
            plan=plan,
        )

        # 3. Arm the watchdog with extended timeout for section builds.
        if self._watchdog is not None:
            self._watchdog.start_turn(timeout=_SECTION_WATCHDOG_TIMEOUT)

        # 4. Fire-and-forget the turn.
        assert self._client is not None  # noqa: S101  # guarded by session check above
        asyncio.create_task(
            self._run_section_turn(session_id, prompt_text),
            name=f"section-turn-{section_id}",
        )

    async def _handle_section_idle(self) -> None:
        """Called when ``session.idle`` fires during the building stage.

        Looks for the active section (first section with ``status="building"``
        in ``state.json``'s plan array).  Then checks for all three artefact
        files on disk:
          - ``analyses/sec_NN_<slug>.py``
          - ``charts/sec_NN_<slug>.png``
          - ``sections/sec_NN_<slug>.md``

        If all three exist: emits ``section.proposed`` with the section ID and
        relative paths.

        If any file is missing: emits ``section.failed`` with
        ``reason="missing_files"``.

        If there is no section with ``status="building"``: logs and returns
        without emitting.  If the current stage is not ``building``: returns
        immediately (idempotent guard).

        When ``QA_FORCE_SECTION_FAIL=1`` is set, the ``.md`` file is removed
        before the check so that the normal missing-artefact path fires and
        ``section.failed`` is emitted deterministically (N2-S20 test seam).

        N2-S07, N2-S20.
        """
        state = self._state_manager.get_state()
        current_stage: str = state.get("stage", "")
        if current_stage != "building":
            logger.debug("_handle_section_idle: ignoring (stage=%r)", current_stage)
            return

        # Find the active section (first with status="building").
        plan: list[dict[str, Any]] = state.get("plan") or []
        building_section: dict[str, Any] | None = next(
            (s for s in plan if s.get("status") == "building"),
            None,
        )
        if building_section is None:
            logger.debug("_handle_section_idle: no section with status=building in plan")
            return

        section_id: str = building_section.get("id", "")
        title: str = building_section.get("title", "")
        section_index: int = building_section.get("index", 1)
        slug: str = building_section.get("slug", "")

        # Derive file base name from section_index and slug.
        # If slug is missing from state (older state format), derive from title.
        if not slug:
            from backend.agent.prompts.section import _make_slug  # noqa: PLC0415

            slug = _make_slug(title)

        nn = str(section_index).zfill(2)
        base_name = f"sec_{nn}_{slug}"

        # N2-S20: QA_FORCE_SECTION_FAIL -- delete the .md before the triplet check
        # so the normal missing-artefact path fires and section.failed is emitted
        # deterministically.  Off by default; zero production-path impact.
        if os.environ.get("QA_FORCE_SECTION_FAIL") == "1":
            md_to_remove = self._workspace_root / "sections" / f"{base_name}.md"
            if md_to_remove.exists():
                try:
                    md_to_remove.unlink()
                    logger.info(
                        "QA_FORCE_SECTION_FAIL: removed %s to force section.failed",
                        md_to_remove,
                    )
                except OSError as exc:
                    logger.warning(
                        "QA_FORCE_SECTION_FAIL: could not remove %s: %s",
                        md_to_remove,
                        exc,
                    )

        py_path_abs = self._workspace_root / "analyses" / f"{base_name}.py"
        png_path_abs = self._workspace_root / "charts" / f"{base_name}.png"
        md_path_abs = self._workspace_root / "sections" / f"{base_name}.md"

        ts = int(time.time() * 1000)

        # Section is done (one way or another) — cancel the watchdog immediately
        # so it doesn't fire during the gap between sections.  start_build_section
        # will re-arm it for the next section if there is one.
        if self._watchdog is not None:
            self._watchdog.cancel()

        # Check all three artefacts.
        missing = []
        if not py_path_abs.exists():
            missing.append("py")
        if not png_path_abs.exists():
            missing.append("png")
        if not md_path_abs.exists():
            missing.append("md")

        if missing:
            logger.warning(
                "_handle_section_idle: section %r missing files: %s",
                section_id,
                missing,
            )
            await self._bus.publish(
                "section.failed",
                {
                    "section_id": section_id,
                    "reason": "missing_files",
                    "ts": ts,
                },
            )
            # Persist status=failed so GET /state reflects the failure.
            updated_plan = [
                {**s, "status": "failed"} if s.get("id") == section_id else s for s in plan
            ]
            self._state_manager.update(plan=updated_plan)
            await self._start_next_queued_section()
            return

        # All three present — emit section.proposed.
        py_path_rel = f"analyses/{base_name}.py"
        png_path_rel = f"charts/{base_name}.png"
        md_path_rel = f"sections/{base_name}.md"

        await self._bus.publish(
            "section.proposed",
            {
                "section_id": section_id,
                "title": title,
                "py_path": py_path_rel,
                "png_path": png_path_rel,
                "md_path": md_path_rel,
                "ts": ts,
            },
        )
        # Persist paths + status=proposed to state.json so GET /state is the
        # source of truth for section artefact paths (not just the SSE event).
        updated_plan = [
            {
                **s,
                "status": "proposed",
                "py_path": py_path_rel,
                "png_path": png_path_rel,
                "md_path": md_path_rel,
            }
            if s.get("id") == section_id
            else s
            for s in plan
        ]
        self._state_manager.update(plan=updated_plan)
        logger.info("section.proposed emitted: %s (ts=%d)", section_id, ts)
        await self._start_next_queued_section()

    async def _check_done_or_next(self, section_id: str) -> None:
        """Check whether all sections are terminal and transition to done if so.

        Called by:
        - ``POST /section/:id/accept`` and ``POST /section/:id/drop`` after the
          status is persisted (direct user interaction path).
        - ``_start_next_queued_section`` when it finds no more queued sections
          (belt-and-suspenders for the auto-sequence path).

        Terminal statuses are ``"accepted"``, ``"dropped"``, and ``"failed"``.
        Non-terminal statuses (``"queued"``, ``"building"``) mean the loop is
        still running and we must not fire ``done`` yet.

        Re-entrant safety: the stage guard (``stage == "building"``) prevents
        double-emission — after the first call persists ``stage="done"``, every
        subsequent call returns early on the guard check.

        Args:
            section_id: The ID of the section that triggered this check
                (informational; used only for logging).

        N3-S01.
        """
        state = self._state_manager.get_state()
        if state.get("stage") != "building":
            logger.debug(
                "_check_done_or_next: ignoring (stage=%r, expected building)",
                state.get("stage"),
            )
            return

        plan: list[dict[str, Any]] = state.get("plan") or []
        _terminal = {"accepted", "dropped", "failed"}
        non_terminal = [s.get("status") for s in plan if s.get("status") not in _terminal]
        if non_terminal:
            logger.debug(
                "_check_done_or_next: %d section(s) still in non-terminal state %r — "
                "auto-sequence is still running, deferring done check",
                len(non_terminal),
                non_terminal,
            )
            return

        # All sections are terminal and we are still in the building stage.
        logger.info(
            "_check_done_or_next: all %d section(s) terminal after %r — "
            "transitioning stage to done",
            len(plan),
            section_id,
        )
        self._state_manager.update(stage="done")
        ts = int(time.time() * 1000)
        await self._bus.publish("stage.changed", {"stage": "done", "ts": ts})
        logger.info("stage.changed → done (ts=%d)", ts)

    async def _start_next_queued_section(self) -> None:
        """Find the next queued section and start its build turn.

        Called by ``_handle_section_idle`` after each section completes (success
        or failure).  Reads the current plan, finds the first section with
        ``status="queued"``, and delegates to ``start_build_section``.  If no
        queued sections remain, delegates to ``_check_done_or_next`` (N3-S01
        belt-and-suspenders: the auto-sequence path must also reach done when
        all sections are terminal).
        """
        state = self._state_manager.get_state()
        plan: list[dict[str, Any]] = state.get("plan") or []
        next_section: dict[str, Any] | None = next(
            (s for s in plan if s.get("status") == "queued"),
            None,
        )
        if next_section is None:
            logger.info("_start_next_queued_section: no queued sections remain.")
            # Belt-and-suspenders: check if all sections are now terminal and
            # transition to done if so (N3-S01).
            await self._check_done_or_next("")
            return

        session_id: str | None = state.get("opencode_session_id")
        if not session_id or self._client is None:
            logger.debug(
                "_start_next_queued_section: no session/client — cannot start next section"
            )
            return

        section_index = next(
            (i + 1 for i, s in enumerate(plan) if s.get("id") == next_section["id"]),
            1,
        )
        await self.start_build_section(
            section_id=next_section["id"],
            section_index=section_index,
            title=next_section["title"],
            hypothesis=next_section.get("hypothesis", ""),
            profile=state.get("profile") or {},
        )

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_section_prompt(
        self,
        section_id: str,
        section_index: int,
        title: str,
        hypothesis: str,
        aim: str,
        dataset: str,
        profile: dict[str, Any],
        plan: list[Any],
    ) -> str:
        """Return the text to send to OpenCode for the section build turn.

        Tries to import ``build_section_prompt`` from ``backend.prompts.section``
        (added by N2-S06).  Falls back to a minimal placeholder.

        Args:
            section_id: Section identifier (e.g. ``"sec_01"``).
            section_index: 1-based ordinal in the plan.
            title: Section title.
            hypothesis: Section hypothesis.
            aim: The user's stated aim.
            dataset: Dataset filename.
            profile: Full parsed profile dict.
            plan: Full plan list.

        Returns:
            A non-empty prompt string.
        """
        try:
            from backend.agent.prompts.section import build_section_prompt  # noqa: PLC0415

            return build_section_prompt(
                section_id=section_id,
                section_index=section_index,
                title=title,
                hypothesis=hypothesis,
                aim=aim,
                dataset=dataset,
                profile=profile,
                plan=plan,
                workspace_root=self._workspace_root.resolve(),
            )
        except ImportError:
            logger.debug(
                "_build_section_prompt: backend.prompts.section not yet available; "
                "using placeholder."
            )
            ws = self._workspace_root.resolve()
            nn = str(section_index).zfill(2)
            return (
                f"Build section {section_id} ({title}) of the brief. "
                f"Aim: {aim}. Dataset: {ws / 'data' / dataset}. "
                f"Write analyses/sec_{nn}_*.py, charts/sec_{nn}_*.png, "
                f"sections/sec_{nn}_*.md with YAML frontmatter."
            )

    @staticmethod
    def _select_redirect_target(
        plan: list[dict[str, Any]],
        section_id: str | None,
    ) -> dict[str, Any] | None:
        """Select which section a building-stage turn should revise.

        The UI passes ``section_id`` for proposed-section revisions. If absent,
        preserve the existing active-build behavior for older callers.
        """
        redirectable_statuses = {"building", "proposed", "accepted", "failed"}
        if section_id:
            return next(
                (
                    s
                    for s in plan
                    if s.get("id") == section_id and s.get("status") in redirectable_statuses
                ),
                None,
            )

        return next(
            (s for s in plan if s.get("status") == "building"),
            next((s for s in plan if s.get("status") == "proposed"), None),
        )

    def _build_redirect_prompt(
        self,
        section_id: str,
        section_index: int,
        title: str,
        hypothesis: str,
        aim: str,
        dataset: str,
        profile: dict[str, Any],
        plan: list[Any],
        redirect_text: str,
    ) -> str:
        """Return the text to send to OpenCode for the section redirect turn.

        Tries to import ``build_redirect_prompt`` from ``backend.prompts.redirect``
        (added by N2-S12).  Falls back to a minimal placeholder.

        N2-S12.
        """
        try:
            from backend.agent.prompts.redirect import build_redirect_prompt  # noqa: PLC0415

            return build_redirect_prompt(
                section_id=section_id,
                section_index=section_index,
                title=title,
                hypothesis=hypothesis,
                aim=aim,
                dataset=dataset,
                profile=profile,
                plan=plan,
                redirect_text=redirect_text,
                workspace_root=self._workspace_root.resolve(),
            )
        except ImportError:
            logger.debug(
                "_build_redirect_prompt: backend.prompts.redirect not yet available; "
                "using placeholder."
            )
            ws = self._workspace_root.resolve()
            nn = str(section_index).zfill(2)
            return (
                f"Redirect section {section_id} ({title}): {redirect_text}. "
                f"Aim: {aim}. Dataset: {ws / 'data' / dataset}. "
                f"Rebuild analyses/sec_{nn}_*.py, charts/sec_{nn}_*.png, "
                f"sections/sec_{nn}_*.md."
            )

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
            from backend.agent.prompts.profile import build_profile_prompt  # noqa: PLC0415

            return build_profile_prompt(dataset, aim, self._workspace_root.resolve())
        except ImportError:
            logger.debug(
                "_build_profile_prompt: backend.prompts.profile not yet available "
                "(N1-S09 not merged); using placeholder."
            )
            ws = self._workspace_root.resolve()
            return f"Profile the dataset at {ws / 'data' / dataset} with aim: {aim}"

    def _build_plan_prompt(self, dataset: str, aim: str, profile: dict[str, Any]) -> str:
        """Return the text to send to OpenCode for the planning turn.

        Tries to import ``build_plan_prompt`` from ``backend.prompts.plan``
        (added by N2-S02).  Falls back to a minimal placeholder so this story
        (N2-S01) is independently deliverable.

        Args:
            dataset: Dataset filename (e.g. ``"data.csv"``).
            aim: The user's stated aim of investigation.
            profile: The parsed profile dict from state (may be empty).

        Returns:
            A non-empty prompt string.
        """
        try:
            from backend.agent.prompts.plan import build_plan_prompt  # noqa: PLC0415

            return build_plan_prompt(dataset, aim, profile, self._workspace_root.resolve())
        except ImportError:
            logger.debug(
                "_build_plan_prompt: backend.prompts.plan not yet available "
                "(N2-S02 not merged); using placeholder."
            )
            ws = self._workspace_root.resolve()
            return (
                f"Draft an analysis plan for {ws / 'data' / dataset} with aim: {aim}. "
                "Return as JSON with a 'sections' array."
            )

    @staticmethod
    def _load_plan_schema() -> Any:
        """Return the plan JSON schema for structured output, or ``None``.

        Attempts to import ``PLAN_SCHEMA`` from ``backend.prompts.plan``
        (N2-S02).  Returns ``None`` if the module is not yet available so that
        N2-S01 remains independently deliverable.
        """
        try:
            from backend.agent.prompts.plan import PLAN_SCHEMA  # noqa: PLC0415

            return PLAN_SCHEMA
        except ImportError:
            return None

    # ------------------------------------------------------------------
    # Workspace file helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _write_plan_json(plan_path: Path, sections: list[dict[str, Any]]) -> None:
        """Atomically write canonical plan.json to workspace.

        Writes the raw sections (id, title, hypothesis — no status field) to
        disk using the same tmp+rename pattern as StateManager.save() so that
        a mid-write process kill never leaves a partial file.

        Status is the responsibility of state.json; plan.json stores only the
        schema-conformant section data.

        Args:
            plan_path: Absolute path to ``workspace/plan.json``.
            sections: List of section dicts with ``id``, ``title``,
                ``hypothesis``.  Any ``status`` field is stripped before
                writing.

        N2-S03.
        """
        # Strip status from sections — plan.json stores raw schema only.
        raw_sections = [{k: v for k, v in s.items() if k != "status"} for s in sections]
        payload = json.dumps({"sections": raw_sections}, indent=2, ensure_ascii=False)

        tmp_path = plan_path.with_name("plan.tmp.json")
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, plan_path)
        logger.debug("plan.json written atomically (%d sections)", len(raw_sections))

    # ------------------------------------------------------------------
    # Fire-and-forget helpers
    # ------------------------------------------------------------------

    async def _run_plan_turn(self, session_id: str, prompt: str) -> None:
        """Send the planning prompt to OpenCode and handle errors.

        This coroutine is scheduled as a fire-and-forget ``asyncio.Task``
        by ``_handle_planning_transition``.  Any exception is caught here and
        converted into a ``turn.error`` bus event.

        The JSON schema for structured output is sourced from
        ``backend.prompts.plan.PLAN_SCHEMA`` when available (N2-S02).
        If that import fails, no schema is passed (``schema=None``).

        Args:
            session_id: The active OpenCode session ID.
            prompt: The plan prompt text to send.

        N2-S01.
        """
        schema: Any = self._load_plan_schema()

        assert self._client is not None  # guarded by caller  # noqa: S101
        try:
            await self._client.prompt(session_id, prompt, schema=schema)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Plan turn failed: %s", exc)
            await self._bus.publish("turn.error", {"message": str(exc)})

    async def _run_section_turn(self, session_id: str, prompt: str) -> None:
        """Send the section build prompt to OpenCode and handle errors.

        Scheduled as a fire-and-forget ``asyncio.Task`` by ``start_build_section``.
        Any exception is caught here and converted into a ``turn.error`` bus event.

        No ``schema`` is passed (``schema=None``) — section build uses the file
        triplet as structured output, not OpenCode's native JSON schema mechanism
        (ADR-005).

        Args:
            session_id: The active OpenCode session ID.
            prompt: The section build prompt text.

        N2-S07.
        """
        assert self._client is not None  # noqa: S101  # guarded by caller
        try:
            # schema=None — no structured output for section build (ADR-005).
            await self._client.prompt(session_id, prompt)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Section turn failed: %s", exc)
            await self._bus.publish("turn.error", {"message": str(exc)})

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
            from backend.agent.prompts.profile import PROFILE_SCHEMA  # noqa: PLC0415

            return PROFILE_SCHEMA
        except ImportError:
            return None
