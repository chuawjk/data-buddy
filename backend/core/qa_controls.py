"""Runtime QA failure controls used by the live demo and automated tests."""

from __future__ import annotations

import os
from pathlib import Path

PROVIDER_ERROR = "provider-error"
SECTION_MISSING_OUTPUT = "section-missing-output"
TURN_STALL = "turn-stall"

_LEGACY_ENV = {
    PROVIDER_ERROR: "QA_FORCE_TURN_ERROR",
    SECTION_MISSING_OUTPUT: "QA_FORCE_SECTION_FAIL",
    TURN_STALL: "QA_FORCE_STALL",
}


class QAControls:
    """Read opt-in failure modes from runtime marker files.

    Marker files live under ``workspace/.qa`` and are checked on every use, so
    they can be enabled or disabled while the server is running. Legacy
    environment-variable aliases remain supported for existing automation.
    """

    def __init__(self, workspace_root: Path) -> None:
        self._marker_dir = Path(workspace_root) / ".qa"

    def enabled(self, failure_mode: str) -> bool:
        """Return whether a named failure mode is currently enabled."""
        marker_enabled = (self._marker_dir / failure_mode).is_file()
        legacy_env = _LEGACY_ENV.get(failure_mode)
        legacy_env_enabled = legacy_env is not None and os.environ.get(legacy_env) == "1"
        return marker_enabled or legacy_env_enabled
