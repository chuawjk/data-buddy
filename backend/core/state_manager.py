"""State manager — atomic reads and writes of state.json.

Single source of truth for the entire brief session.  All reads and writes of
``state.json`` go through this module; no other component may touch that file
directly.

Design:
- **Atomic write:** ``save()`` writes to ``state.tmp.json`` then calls
  ``os.replace()`` to atomically rename it onto ``state.json``.  A process kill
  between the two steps leaves ``state.json`` at its previous valid content.
- **In-memory state:** the last persisted (or default) state is kept in
  ``_state`` so callers can read without a round-trip to disk.
- **Turn deferral:** ``save_async()`` accepts an optional ``asyncio.Lock``.
  While the lock is held (i.e. an agent turn is in progress) the save waits
  until the lock is free, then writes.  Synchronous ``save()`` does not defer.
- **No opencode_session_id in API responses:** ``get_state()`` returns the full
  internal dict; the router strips ``opencode_session_id`` before serialising.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Default state shape — matches the API contract §3 and C4 L4 state.json schema.
# ---------------------------------------------------------------------------

_DEFAULT_STATE: dict[str, Any] = {
    "version": "1",
    "stage": "setup",
    "aim": None,
    "dataset_path": None,
    "last_saved": None,
    "opencode_session_id": None,
    "profile": None,
    "plan": [],
}


class StateManager:
    """Manages all reads and writes of ``state.json``.

    Args:
        path: Path to ``state.json``.  Defaults to ``workspace/state.json``
              (relative to the working directory at import time).  Tests pass
              a ``tmp_path``-based path for isolation.
    """

    def __init__(self, path: Path = Path("workspace/state.json")) -> None:
        self._path = Path(path)
        self._tmp_path = self._path.with_name("state.tmp.json")
        # Initialise in-memory state to defaults; load() will override if the
        # file exists.
        self._state: dict[str, Any] = dict(_DEFAULT_STATE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Read ``state.json`` from disk and return its contents.

        If the file does not exist, returns a copy of the default state dict
        without writing anything to disk.  The in-memory state is NOT updated
        by this call so that callers can inspect the file without side-effects.

        Returns:
            A dict matching the state shape.  Always contains all default keys.
        """
        if not self._path.exists():
            return dict(_DEFAULT_STATE)

        raw = self._path.read_text(encoding="utf-8")
        on_disk = json.loads(raw)

        # Merge on-disk data over defaults so any newly-added default keys are
        # present even when reading an older state.json.
        merged = dict(_DEFAULT_STATE)
        merged.update(on_disk)
        self._state = merged
        return dict(merged)

    def save(self, state: dict[str, Any]) -> None:
        """Atomically persist ``state`` to ``state.json``.

        Writes to ``state.tmp.json`` first, then calls ``os.replace()`` to
        atomically swap it onto ``state.json``.  This guarantees that
        ``state.json`` is always either the previous valid content or the new
        valid content — never a partial write.

        The ``last_saved`` timestamp is set to the current UTC time before
        writing.

        Args:
            state: The full state dict to persist.
        """
        to_write = dict(state)
        to_write["last_saved"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Ensure the parent directory exists.
        self._path.parent.mkdir(parents=True, exist_ok=True)

        self._tmp_path.write_text(
            json.dumps(to_write, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(self._tmp_path, self._path)

        # Update in-memory state to reflect the persisted data.
        self._state = dict(to_write)

    async def save_async(
        self,
        state: dict[str, Any],
        lock: asyncio.Lock | None = None,
    ) -> None:
        """Async variant of ``save()`` with optional turn deferral.

        If ``lock`` is provided and currently held, waits until it is released
        before writing.  This prevents state writes from racing with an active
        agent turn.

        Args:
            state: The full state dict to persist.
            lock: An ``asyncio.Lock`` that is held while an agent turn is in
                  progress.  Pass ``None`` to skip deferral.
        """
        if lock is not None:
            async with lock:
                self.save(state)
        else:
            self.save(state)

    def get_state(self) -> dict[str, Any]:
        """Return the current in-memory state dict.

        Does not read from disk.  If ``load()`` has not been called (or if the
        file does not exist), this returns the default state.

        Returns:
            A copy of the current in-memory state dict.
        """
        return dict(self._state)

    def update(self, **kwargs: Any) -> None:
        """Merge ``kwargs`` into the current state and persist.

        Only the provided keys are changed; all other fields retain their
        current values.

        Args:
            **kwargs: Key-value pairs to merge into the state.
        """
        updated = dict(self._state)
        updated.update(kwargs)
        self.save(updated)
