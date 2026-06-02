"""Stage orchestrator -- N1-S05 minimal stub.

This module contains just enough for the N1-S05 setup-endpoint handoff.  The
full state machine (N1-S04, which depends on N1-S08 not yet built) will expand
this module significantly.

Architecture boundary (from backlog):
- The orchestrator calls the OpenCode client through the narrow interface only.
- The state machine never imports ``httpx``.
- The client never imports the orchestrator.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.event_bus import EventBus
    from backend.state_manager import StateManager


class Orchestrator:
    """Minimal orchestrator stub -- setup to profiling handoff.

    Only the ``setup_complete`` method is implemented here.  The full
    profiling/planning/building state machine will be added in N1-S04 once
    N1-S08 (OpenCode client + event subscription) is available.

    Args:
        state_manager: The application's ``StateManager`` instance.
        bus: The application's ``EventBus`` instance.
        workspace_root: Root of the workspace directory.  Defaults to
            ``workspace/`` relative to the working directory.  Tests pass
            a ``tmp_path``-based path for isolation.
    """

    def __init__(
        self,
        state_manager: "StateManager",
        bus: "EventBus",
        workspace_root: Path = Path("workspace"),
    ) -> None:
        self._state_manager = state_manager
        self._bus = bus
        self._workspace_root = Path(workspace_root)

    async def setup_complete(self, dataset: str, aim: str) -> None:
        """Advance from setup to profiling and emit ``stage.changed``.

        Called by ``POST /setup`` after the CSV file and initial state are
        written.  Transitions the stage to ``"profiling"`` and publishes
        ``stage.changed`` on the event bus.

        The full profiling turn (firing an OpenCode prompt) will be triggered
        here once N1-S06/S08 are available.

        Args:
            dataset: The filename of the uploaded dataset (e.g. ``"data.csv"``).
            aim: The user's stated aim of investigation.
        """
        self._state_manager.update(stage="profiling", dataset=dataset, aim=aim)
        await self._bus.publish("stage.changed", {"stage": "profiling"})
        # Full profiling turn will be triggered here once N1-S06/S08 exist.
