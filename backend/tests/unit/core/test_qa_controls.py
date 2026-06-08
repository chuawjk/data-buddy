"""Unit tests for marker-backed runtime QA controls."""

from __future__ import annotations

from backend.core.qa_controls import (
    PROVIDER_ERROR,
    SECTION_MISSING_OUTPUT,
    TURN_STALL,
    QAControls,
)


def test_controls_are_off_by_default(tmp_path):
    controls = QAControls(tmp_path)

    assert not controls.enabled(PROVIDER_ERROR)
    assert not controls.enabled(SECTION_MISSING_OUTPUT)
    assert not controls.enabled(TURN_STALL)


def test_marker_changes_are_observed_at_runtime(tmp_path):
    controls = QAControls(tmp_path)
    marker_dir = tmp_path / ".qa"
    marker_dir.mkdir()
    marker = marker_dir / PROVIDER_ERROR

    marker.touch()
    assert controls.enabled(PROVIDER_ERROR)

    marker.unlink()
    assert not controls.enabled(PROVIDER_ERROR)


def test_legacy_environment_alias_remains_supported(tmp_path, monkeypatch):
    controls = QAControls(tmp_path)
    monkeypatch.setenv("QA_FORCE_SECTION_FAIL", "1")

    assert controls.enabled(SECTION_MISSING_OUTPUT)
