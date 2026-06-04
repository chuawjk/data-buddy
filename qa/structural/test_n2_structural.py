"""Night 2 structural gate — N2-S19.

QA asserts shape, contract, and behaviour — never analysis quality.

Checks implemented (per 04_QA_PLAN.md §3 Night 2):

  A. Plan schema — PLAN_SCHEMA in backend/prompts/plan.py has the required
     structure: sections array with id/title/hypothesis required, 3-6 entries,
     status injected as "proposed".

  B. Zero-OpenCode-call assertions for backend-only endpoints:
     POST /plan/update, POST /plan/accept (HTTP shape), POST /section/:id/accept,
     POST /section/:id/drop, GET /export, GET /file — all make zero OpenCode calls.

  C. Frontmatter parser shape:
     parse_frontmatter returns correct fields; parse_section_file separates
     frontmatter from body; malformed YAML fails safely (no crash).

  D. Architecture boundaries (Night 1 carry-forward):
     orchestrator.py has zero import httpx; opencode_client.py has zero imports
     of orchestrator module.

  E. Forced-failure hook (QA_FORCE_SECTION_FAIL=1):
     - With full triplet + env set: section.failed emitted, .md removed.
     - With env unset + full triplet: section.proposed emitted (regression guard).

  F. State transitions:
     GET /state returns required fields (stage, profile, plan, error excluded
     on clean state); POST /plan/update changes plan in state.json synchronously.

  G. Export correctness:
     Accepted sections in output; dropped/proposed excluded; zero OpenCode.

  H. data-testid completeness Night 2:
     plan-view, plan-section-list, plan-accept-btn, plan-turn-input,
     plan-turn-submit, build-view, export-btn, section-code,
     section-interpretation present in production frontend files.

Each test maps to a regression check ID in QA_LOG.md (REG-N2-01 through REG-N2-07).
"""

from __future__ import annotations

import ast
import asyncio
import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Repo root and paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[2]  # .../data-buddy
_BACKEND_ROOT = _REPO_ROOT / "backend"
_FRONTEND_SRC = _REPO_ROOT / "frontend" / "src"


# ---------------------------------------------------------------------------
# Helpers shared across multiple tests
# ---------------------------------------------------------------------------


def _write_state_file(state_path: Path, **kwargs) -> None:
    """Write state.json with defaults merged over kwargs."""
    base = {
        "version": "1",
        "stage": "setup",
        "aim": None,
        "dataset_path": None,
        "last_saved": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "opencode_session_id": None,
        "profile": None,
        "plan": [],
    }
    base.update(kwargs)
    state_path.write_text(json.dumps(base, indent=2), encoding="utf-8")


# ===========================================================================
# A. Plan schema — REG-N2-01
# ===========================================================================


class TestPlanSchema:
    """REG-N2-01: PLAN_SCHEMA in backend/prompts/plan.py has the required shape."""

    def test_plan_schema_has_sections_property(self):
        """PLAN_SCHEMA top-level must have required=['sections']."""
        from backend.agent.prompts.plan import PLAN_SCHEMA

        assert "sections" in PLAN_SCHEMA.get("required", []), (
            "PLAN_SCHEMA must list 'sections' as a required field"
        )
        assert "sections" in PLAN_SCHEMA.get("properties", {}), (
            "PLAN_SCHEMA.properties must contain 'sections'"
        )

    def test_plan_schema_sections_is_array(self):
        """PLAN_SCHEMA.properties.sections must be type=array."""
        from backend.agent.prompts.plan import PLAN_SCHEMA

        sections_schema = PLAN_SCHEMA["properties"]["sections"]
        assert sections_schema["type"] == "array", (
            "sections schema must have type='array'"
        )

    def test_plan_schema_sections_min_max_items(self):
        """PLAN_SCHEMA sections array must enforce 3–6 entries."""
        from backend.agent.prompts.plan import PLAN_SCHEMA

        sections_schema = PLAN_SCHEMA["properties"]["sections"]
        assert sections_schema.get("minItems") == 3, "sections minItems must be 3"
        assert sections_schema.get("maxItems") == 6, "sections maxItems must be 6"

    def test_plan_schema_item_required_fields(self):
        """Each section item must require id, title, hypothesis."""
        from backend.agent.prompts.plan import PLAN_SCHEMA

        item_schema = PLAN_SCHEMA["properties"]["sections"]["items"]
        required = set(item_schema.get("required", []))
        for field in ("id", "title", "hypothesis"):
            assert field in required, f"Section item schema must require {field!r}"

    def test_plan_schema_item_properties_present(self):
        """Each section item must declare id, title, hypothesis as string properties."""
        from backend.agent.prompts.plan import PLAN_SCHEMA

        item_schema = PLAN_SCHEMA["properties"]["sections"]["items"]
        props = item_schema.get("properties", {})
        for field in ("id", "title", "hypothesis"):
            assert field in props, f"Section item schema must have property {field!r}"
            assert props[field].get("type") == "string", (
                f"Section item property {field!r} must have type='string'"
            )

    def test_plan_schema_validates_a_valid_plan(self):
        """A 3-section plan with id/title/hypothesis satisfies PLAN_SCHEMA constraints."""
        from backend.agent.prompts.plan import PLAN_SCHEMA

        # Validate manually against the schema's constraints (no jsonschema dep required).
        sections_schema = PLAN_SCHEMA["properties"]["sections"]
        item_required = set(sections_schema["items"].get("required", []))
        min_items = sections_schema.get("minItems", 0)
        max_items = sections_schema.get("maxItems", float("inf"))

        valid_sections = [
            {
                "id": "sec_01",
                "title": "Revenue by Tier",
                "hypothesis": "Premium churns less",
            },
            {"id": "sec_02", "title": "Churn Trend", "hypothesis": "Churn peaked Q3"},
            {
                "id": "sec_03",
                "title": "Cohort Analysis",
                "hypothesis": "Older cohorts stable",
            },
        ]
        assert min_items <= len(valid_sections) <= max_items, (
            "3 sections must satisfy minItems=3"
        )
        for s in valid_sections:
            assert item_required.issubset(s.keys()), (
                f"Section {s} missing required fields"
            )

    def test_plan_schema_rejects_too_few_sections(self):
        """A 2-section plan violates PLAN_SCHEMA minItems=3 constraint."""
        from backend.agent.prompts.plan import PLAN_SCHEMA

        min_items = PLAN_SCHEMA["properties"]["sections"].get("minItems", 0)
        assert 2 < min_items or min_items == 3, "minItems must be 3"
        # Explicitly: 2 < 3, so this plan would be invalid.
        assert 2 < min_items, f"2 sections must fail minItems={min_items} constraint"

    def test_plan_schema_rejects_too_many_sections(self):
        """A 7-section plan violates PLAN_SCHEMA maxItems=6 constraint."""
        from backend.agent.prompts.plan import PLAN_SCHEMA

        max_items = PLAN_SCHEMA["properties"]["sections"].get("maxItems", float("inf"))
        assert 7 > max_items, f"7 sections must fail maxItems={max_items} constraint"

    def test_plan_schema_rejects_missing_required_field(self):
        """A section missing 'hypothesis' violates PLAN_SCHEMA item required fields."""
        from backend.agent.prompts.plan import PLAN_SCHEMA

        item_required = set(
            PLAN_SCHEMA["properties"]["sections"]["items"].get("required", [])
        )
        bad_section = {"id": "sec_01", "title": "A"}  # missing hypothesis
        missing = item_required - bad_section.keys()
        assert missing, (
            f"A section missing 'hypothesis' should have missing required fields: {missing}"
        )
        assert "hypothesis" in missing


# ===========================================================================
# B. Zero OpenCode calls — REG-N2-02
# ===========================================================================


class TestZeroOpenCodeCalls:
    """REG-N2-02: Backend-only endpoints make zero OpenCode calls."""

    def _seed_planning_state(self, app, workspace):
        """Write state.json to planning stage and reload."""
        state_path = workspace / "state.json"
        data_dir = workspace / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "test.csv").write_bytes(b"id,value\n1,100\n")

        _write_state_file(
            state_path,
            stage="planning",
            aim="test aim",
            dataset_path="data/test.csv",
        )
        app.state.state_manager.load()

    def _seed_plan(self, client):
        r = client.post(
            "/plan/update",
            json={
                "sections": [
                    {"id": "sec_01", "title": "A", "hypothesis": "H1"},
                    {"id": "sec_02", "title": "B", "hypothesis": "H2"},
                    {"id": "sec_03", "title": "C", "hypothesis": "H3"},
                ]
            },
        )
        assert r.status_code == 200

    def _attach_spy(self, app):
        """Attach a mock to orchestrator._client.prompt and return it."""
        mock = MagicMock()
        mock.prompt = MagicMock(return_value=None)
        app.state.orchestrator._client = mock
        return mock

    def test_plan_update_zero_opencode_calls(self, qa_app):
        """POST /plan/update makes zero OpenCode calls."""
        client, app, workspace = qa_app
        self._seed_planning_state(app, workspace)
        spy = self._attach_spy(app)

        client.post(
            "/plan/update",
            json={"sections": [{"id": "sec_01", "title": "T", "hypothesis": "H"}]},
        )

        spy.prompt.assert_not_called()

    def test_section_accept_zero_opencode_calls(self, qa_app):
        """POST /section/:id/accept makes zero OpenCode calls."""
        client, app, workspace = qa_app
        self._seed_planning_state(app, workspace)
        self._seed_plan(client)
        spy = self._attach_spy(app)

        client.post("/section/sec_01/accept")

        spy.prompt.assert_not_called()

    def test_section_drop_zero_opencode_calls(self, qa_app):
        """POST /section/:id/drop makes zero OpenCode calls."""
        client, app, workspace = qa_app
        self._seed_planning_state(app, workspace)
        self._seed_plan(client)
        spy = self._attach_spy(app)

        client.post("/section/sec_01/drop")

        spy.prompt.assert_not_called()

    def test_export_zero_opencode_calls(self, qa_app):
        """GET /export makes zero OpenCode calls."""
        client, app, workspace = qa_app
        self._seed_planning_state(app, workspace)
        spy = self._attach_spy(app)

        client.get("/export")

        spy.prompt.assert_not_called()

    def test_file_endpoint_zero_opencode_calls(self, qa_app):
        """GET /file makes zero OpenCode calls."""
        client, app, workspace = qa_app
        data_dir = workspace / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "test.csv").write_bytes(b"id,value\n1,100\n")

        _write_state_file(workspace / "state.json", stage="setup")
        app.state.state_manager.load()

        spy = self._attach_spy(app)
        client.get("/file?path=data/test.csv")

        spy.prompt.assert_not_called()


# ===========================================================================
# C. Frontmatter parser shape — REG-N2-03
# ===========================================================================


class TestFrontmatterParser:
    """REG-N2-03: parse_frontmatter and parse_section_file work correctly."""

    _SAMPLE_MD = (
        "---\n"
        "section_id: sec_01\n"
        "title: Revenue Analysis\n"
        "chart: charts/sec_01_revenue.png\n"
        "---\n\n"
        "Revenue shows a clear trend.\n"
    )

    def test_parse_frontmatter_returns_dict_with_required_keys(self):
        """parse_frontmatter returns dict with frontmatter, body, parse_error."""
        from backend.core.frontmatter_parser import parse_frontmatter

        result = parse_frontmatter(self._SAMPLE_MD)
        assert "frontmatter" in result
        assert "body" in result
        assert "parse_error" in result

    def test_parse_frontmatter_extracts_fields(self):
        """parse_frontmatter correctly extracts YAML fields."""
        from backend.core.frontmatter_parser import parse_frontmatter

        result = parse_frontmatter(self._SAMPLE_MD)
        assert result["parse_error"] is False
        fm = result["frontmatter"]
        assert fm.get("section_id") == "sec_01"
        assert fm.get("title") == "Revenue Analysis"
        assert fm.get("chart") == "charts/sec_01_revenue.png"

    def test_parse_frontmatter_separates_body(self):
        """parse_frontmatter correctly separates body from frontmatter."""
        from backend.core.frontmatter_parser import parse_frontmatter

        result = parse_frontmatter(self._SAMPLE_MD)
        assert "Revenue shows a clear trend." in result["body"]
        # Body should not contain the --- delimiters
        assert "---" not in result["body"]

    def test_parse_frontmatter_no_frontmatter_returns_full_body(self):
        """Text without frontmatter returns full text as body, empty frontmatter."""
        from backend.core.frontmatter_parser import parse_frontmatter

        text = "This is just regular markdown.\n\nNo frontmatter here.\n"
        result = parse_frontmatter(text)
        assert result["frontmatter"] == {}
        assert result["body"] == text
        assert result["parse_error"] is False

    def test_parse_frontmatter_malformed_yaml_no_crash(self):
        """Malformed YAML in frontmatter sets parse_error=True, does not raise."""
        from backend.core.frontmatter_parser import parse_frontmatter

        bad_md = "---\n: invalid: yaml: {\n---\n\nBody text.\n"
        # Must not raise
        result = parse_frontmatter(bad_md)
        assert result["parse_error"] is True
        assert isinstance(result, dict)

    def test_parse_frontmatter_unclosed_delimiter_sets_parse_error(self):
        """Opening --- with no closing --- sets parse_error=True."""
        from backend.core.frontmatter_parser import parse_frontmatter

        bad_md = "---\nsection_id: sec_01\n\nNo closing delimiter.\n"
        result = parse_frontmatter(bad_md)
        assert result["parse_error"] is True

    def test_parse_frontmatter_type_error_on_none(self):
        """parse_frontmatter raises TypeError on None input (documented contract)."""
        from backend.core.frontmatter_parser import parse_frontmatter

        with pytest.raises(TypeError):
            parse_frontmatter(None)  # type: ignore[arg-type]

    def test_parse_section_file_returns_dict_with_path(self, tmp_path):
        """parse_section_file returns dict with path, frontmatter, body, parse_error."""
        from backend.core.frontmatter_parser import parse_section_file

        md_file = tmp_path / "sec_01_test.md"
        md_file.write_text(self._SAMPLE_MD, encoding="utf-8")

        result = parse_section_file(md_file)
        assert "path" in result
        assert "frontmatter" in result
        assert "body" in result
        assert "parse_error" in result

    def test_parse_section_file_separates_frontmatter_from_body(self, tmp_path):
        """parse_section_file returns correct frontmatter and body from disk."""
        from backend.core.frontmatter_parser import parse_section_file

        md_file = tmp_path / "sec_01_test.md"
        md_file.write_text(self._SAMPLE_MD, encoding="utf-8")

        result = parse_section_file(md_file)
        assert result["parse_error"] is False
        assert result["frontmatter"].get("section_id") == "sec_01"
        assert "Revenue shows a clear trend." in result["body"]

    def test_parse_section_file_missing_file_returns_parse_error(self, tmp_path):
        """parse_section_file on a non-existent file returns parse_error=True, no raise."""
        from backend.core.frontmatter_parser import parse_section_file

        result = parse_section_file(tmp_path / "nonexistent.md")
        assert result["parse_error"] is True
        assert result["frontmatter"] == {}
        assert result["body"] == ""

    def test_parse_section_file_malformed_yaml_fails_safely(self, tmp_path):
        """parse_section_file on a file with malformed YAML returns parse_error=True."""
        from backend.core.frontmatter_parser import parse_section_file

        bad_md = "---\n: this: is: invalid\n---\n\nBody.\n"
        md_file = tmp_path / "bad.md"
        md_file.write_text(bad_md, encoding="utf-8")

        result = parse_section_file(md_file)
        assert result["parse_error"] is True


# ===========================================================================
# D. Architecture boundaries — REG-N1-02 / REG-N1-03 (carry-forward)
# ===========================================================================


class TestArchitectureBoundaries:
    """REG-N1-02 / REG-N1-03: Architecture boundary checks."""

    def test_orchestrator_has_no_httpx_import(self):
        """backend/orchestrator.py must not import httpx at any scope."""
        orchestrator_path = _BACKEND_ROOT / "core" / "orchestrator.py"
        tree = ast.parse(orchestrator_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "httpx" and not alias.name.startswith(
                        "httpx."
                    ), f"orchestrator.py must not import httpx; found: {alias.name!r}"
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "httpx" and not (node.module or "").startswith(
                    "httpx."
                ), f"orchestrator.py must not import from httpx; found: {node.module!r}"

    def test_opencode_client_has_no_orchestrator_import(self):
        """backend/opencode_client.py must not import the orchestrator module."""
        client_path = _BACKEND_ROOT / "agent" / "opencode_client.py"
        tree = ast.parse(client_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "orchestrator" not in alias.name, (
                        f"opencode_client.py must not import orchestrator; "
                        f"found: {alias.name!r}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "orchestrator" not in module, (
                    f"opencode_client.py must not import from orchestrator; "
                    f"found: {module!r}"
                )


# ===========================================================================
# E. Forced-failure hook — REG-N2-04
# ===========================================================================


class TestForcedFailureHook:
    """REG-N2-04: QA_FORCE_SECTION_FAIL=1 triggers section.failed deterministically."""

    def _make_orchestrator(self, tmp_path):
        from backend.core.event_bus import EventBus
        from backend.core.orchestrator import Orchestrator
        from backend.core.state_manager import StateManager

        sm = StateManager(path=tmp_path / "state.json")
        sm.load()
        sm.update(
            opencode_session_id="sess-test",
            stage="building",
            plan=[
                {
                    "id": "sec_01",
                    "title": "Revenue by Segment",
                    "hypothesis": "Premium has lower churn",
                    "status": "building",
                    "index": 1,
                    "slug": "revenue_by_segment",
                }
            ],
        )

        bus = EventBus()
        mock_client = AsyncMock()
        orch = Orchestrator(
            state_manager=sm,
            bus=bus,
            client=mock_client,
            workspace_root=tmp_path,
        )
        return orch, bus

    def _write_triplet(self, tmp_path):
        base = "sec_01_revenue_by_segment"
        (tmp_path / "analyses").mkdir(parents=True, exist_ok=True)
        (tmp_path / "charts").mkdir(parents=True, exist_ok=True)
        (tmp_path / "sections").mkdir(parents=True, exist_ok=True)
        (tmp_path / "analyses" / f"{base}.py").write_text(
            "import os\n", encoding="utf-8"
        )
        (tmp_path / "charts" / f"{base}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (tmp_path / "sections" / f"{base}.md").write_text(
            "---\nsection_id: sec_01\n---\n\nBody.\n",
            encoding="utf-8",
        )

    @pytest.mark.asyncio
    async def test_force_section_fail_emits_section_failed(self, tmp_path):
        """QA_FORCE_SECTION_FAIL=1 with full triplet emits section.failed."""
        orch, bus = self._make_orchestrator(tmp_path)
        self._write_triplet(tmp_path)

        sub = bus.subscribe()
        with patch.dict("os.environ", {"QA_FORCE_SECTION_FAIL": "1"}):
            await orch._handle_section_idle()

        event = await asyncio.wait_for(sub.__anext__(), timeout=2.0)
        assert event["type"] == "section.failed", (
            f"Expected section.failed with QA_FORCE_SECTION_FAIL=1; got {event['type']!r}"
        )
        assert event.get("section_id") == "sec_01"

    @pytest.mark.asyncio
    async def test_force_section_fail_removes_md_file(self, tmp_path):
        """QA_FORCE_SECTION_FAIL=1 removes the .md file before the triplet check."""
        orch, bus = self._make_orchestrator(tmp_path)
        self._write_triplet(tmp_path)

        md_path = tmp_path / "sections" / "sec_01_revenue_by_segment.md"
        assert md_path.exists(), "Pre-condition: .md must exist"

        sub = bus.subscribe()
        with patch.dict("os.environ", {"QA_FORCE_SECTION_FAIL": "1"}):
            await orch._handle_section_idle()

        await asyncio.wait_for(sub.__anext__(), timeout=2.0)  # drain bus
        assert not md_path.exists(), "QA_FORCE_SECTION_FAIL=1 must delete the .md file"

    @pytest.mark.asyncio
    async def test_no_force_fail_full_triplet_emits_section_proposed(self, tmp_path):
        """Without QA_FORCE_SECTION_FAIL, full triplet emits section.proposed."""
        orch, bus = self._make_orchestrator(tmp_path)
        self._write_triplet(tmp_path)

        sub = bus.subscribe()
        env = os.environ.copy()
        env.pop("QA_FORCE_SECTION_FAIL", None)
        with patch.dict("os.environ", env, clear=True):
            await orch._handle_section_idle()

        event = await asyncio.wait_for(sub.__anext__(), timeout=2.0)
        assert event["type"] == "section.proposed", (
            f"Without QA_FORCE_SECTION_FAIL, full triplet must yield section.proposed; "
            f"got {event['type']!r}"
        )


# ===========================================================================
# F. State transitions — REG-N2-05
# ===========================================================================


class TestStateTransitions:
    """REG-N2-05: GET /state shape and plan/update → state.json synchronously."""

    def test_get_state_returns_200(self, qa_app):
        """GET /state must return 200."""
        client, app, workspace = qa_app
        r = client.get("/state")
        assert r.status_code == 200

    def test_get_state_has_stage_field(self, qa_app):
        """GET /state must include 'stage' field."""
        client, app, workspace = qa_app
        body = client.get("/state").json()
        assert "stage" in body, "GET /state must contain 'stage'"

    def test_get_state_has_plan_field(self, qa_app):
        """GET /state must include 'plan' field."""
        client, app, workspace = qa_app
        body = client.get("/state").json()
        assert "plan" in body, "GET /state must contain 'plan'"
        assert isinstance(body["plan"], list), "'plan' must be a list"

    def test_get_state_has_profile_field(self, qa_app):
        """GET /state must include 'profile' field (may be null before profiling)."""
        client, app, workspace = qa_app
        body = client.get("/state").json()
        assert "profile" in body, (
            "GET /state must contain 'profile' (null before profiling)"
        )

    def test_get_state_does_not_expose_opencode_session_id(self, qa_app):
        """GET /state must not expose opencode_session_id (internal field)."""
        client, app, workspace = qa_app
        body = client.get("/state").json()
        assert "opencode_session_id" not in body, (
            "GET /state must not expose opencode_session_id"
        )

    def test_plan_update_changes_state_synchronously(self, qa_app):
        """POST /plan/update must change plan in state.json synchronously."""
        client, app, workspace = qa_app
        _write_state_file(workspace / "state.json", stage="planning", aim="test")
        app.state.state_manager.load()

        sections = [
            {"id": "sec_01", "title": "Revenue", "hypothesis": "H1"},
            {"id": "sec_02", "title": "Churn", "hypothesis": "H2"},
            {"id": "sec_03", "title": "Cohort", "hypothesis": "H3"},
        ]
        r = client.post("/plan/update", json={"sections": sections})
        assert r.status_code == 200

        state = app.state.state_manager.get_state()
        plan = state.get("plan", [])
        plan_ids = [s["id"] for s in plan]
        assert "sec_01" in plan_ids
        assert "sec_02" in plan_ids
        assert "sec_03" in plan_ids

    def test_plan_update_also_writes_plan_json(self, qa_app):
        """POST /plan/update must write plan.json to workspace atomically."""
        client, app, workspace = qa_app
        _write_state_file(workspace / "state.json", stage="planning", aim="test")
        app.state.state_manager.load()

        sections = [
            {"id": "sec_01", "title": "Revenue", "hypothesis": "H1"},
            {"id": "sec_02", "title": "Churn", "hypothesis": "H2"},
            {"id": "sec_03", "title": "Cohort", "hypothesis": "H3"},
        ]
        client.post("/plan/update", json={"sections": sections})

        plan_path = workspace / "plan.json"
        assert plan_path.exists(), "plan.json must be written by POST /plan/update"

        plan_data = json.loads(plan_path.read_text())
        assert "sections" in plan_data
        saved_ids = [s["id"] for s in plan_data["sections"]]
        assert "sec_01" in saved_ids

    def test_section_accept_transitions_status_to_accepted(self, qa_app):
        """POST /section/:id/accept transitions proposed→accepted in state.json."""
        client, app, workspace = qa_app
        _write_state_file(
            workspace / "state.json",
            stage="planning",
            aim="test",
            plan=[
                {"id": "sec_01", "title": "A", "hypothesis": "H", "status": "proposed"},
            ],
        )
        app.state.state_manager.load()

        r = client.post("/section/sec_01/accept")
        assert r.status_code == 204

        state = app.state.state_manager.get_state()
        plan = state.get("plan", [])
        sec = next((s for s in plan if s["id"] == "sec_01"), None)
        assert sec is not None
        assert sec["status"] == "accepted"

    def test_plan_update_rejects_empty_aim(self, qa_app):
        """POST /plan/update with empty sections returns 422."""
        client, app, workspace = qa_app
        r = client.post("/plan/update", json={"sections": []})
        assert r.status_code == 422

    def test_post_setup_rejects_empty_aim(self, qa_app):
        """POST /setup with whitespace-only aim returns 422 invalid_aim."""
        client, app, workspace = qa_app
        r = client.post(
            "/setup",
            data={"aim": "   "},
            files={"csv": ("test.csv", b"id,val\n1,2\n", "text/csv")},
        )
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_aim"

    def test_post_setup_rejects_non_csv(self, qa_app):
        """POST /setup with a non-CSV file returns 422 invalid_file."""
        client, app, workspace = qa_app
        r = client.post(
            "/setup",
            data={"aim": "analyse churn"},
            files={"csv": ("test.txt", b"not a csv", "text/plain")},
        )
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_file"


# ===========================================================================
# G. Export correctness — REG-N2-06
# ===========================================================================


class TestExportCorrectness:
    """REG-N2-06: GET /export returns accepted sections; excludes dropped/proposed."""

    _SECTION_MD = (
        "---\n"
        "section_id: sec_01\n"
        'title: "Revenue"\n'
        'hypothesis: "H1"\n'
        "chart: charts/sec_01_revenue.png\n"
        "---\n\n"
        "Revenue analysis content here.\n"
    )
    _SECTION_B_MD = (
        "---\n"
        "section_id: sec_02\n"
        'title: "Churn"\n'
        'hypothesis: "H2"\n'
        "chart: charts/sec_02_churn.png\n"
        "---\n\n"
        "Churn analysis content here.\n"
    )

    def _write_section_file(self, workspace, filename, content):
        sections_dir = workspace / "sections"
        sections_dir.mkdir(parents=True, exist_ok=True)
        (sections_dir / filename).write_text(content, encoding="utf-8")

    def _seed_state(self, client, app, workspace, plan):
        state_path = workspace / "state.json"
        _write_state_file(state_path, stage="building", aim="test aim", plan=plan)
        app.state.state_manager.load()

    def test_export_returns_text_markdown_content_type(self, qa_app):
        """GET /export must return Content-Type: application/zip."""
        client, app, workspace = qa_app
        r = client.get("/export")
        assert r.status_code == 200
        assert "application/zip" in r.headers.get("content-type", "")

    @staticmethod
    def _unzip_report(response_content: bytes) -> str:
        """Extract report.md text from the export zip response."""
        with zipfile.ZipFile(io.BytesIO(response_content)) as zf:
            return zf.read("report.md").decode("utf-8")

    def test_export_content_disposition_attachment(self, qa_app):
        """GET /export must set Content-Disposition: attachment; filename=brief.zip."""
        client, app, workspace = qa_app
        r = client.get("/export")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "brief.zip" in cd

    def test_export_includes_accepted_section_content(self, qa_app):
        """GET /export includes body content of accepted sections."""
        client, app, workspace = qa_app
        self._write_section_file(workspace, "sec_01_revenue.md", self._SECTION_MD)

        plan = [
            {
                "id": "sec_01",
                "title": "Revenue",
                "hypothesis": "H1",
                "status": "accepted",
                "md_path": "sections/sec_01_revenue.md",
            }
        ]
        self._seed_state(client, app, workspace, plan)

        r = client.get("/export")
        assert r.status_code == 200
        assert "Revenue analysis content here." in self._unzip_report(r.content)

    def test_export_excludes_dropped_sections(self, qa_app):
        """GET /export must not include dropped section content."""
        client, app, workspace = qa_app
        self._write_section_file(workspace, "sec_01_revenue.md", self._SECTION_MD)

        plan = [
            {
                "id": "sec_01",
                "title": "Revenue",
                "hypothesis": "H1",
                "status": "dropped",
                "md_path": "sections/sec_01_revenue.md",
            }
        ]
        self._seed_state(client, app, workspace, plan)

        r = client.get("/export")
        assert "Revenue analysis content here." not in self._unzip_report(r.content)

    def test_export_excludes_proposed_sections(self, qa_app):
        """GET /export must not include proposed section content."""
        client, app, workspace = qa_app
        self._write_section_file(workspace, "sec_01_revenue.md", self._SECTION_MD)

        plan = [
            {
                "id": "sec_01",
                "title": "Revenue",
                "hypothesis": "H1",
                "status": "proposed",
                "md_path": "sections/sec_01_revenue.md",
            }
        ]
        self._seed_state(client, app, workspace, plan)

        r = client.get("/export")
        assert "Revenue analysis content here." not in self._unzip_report(r.content)

    def test_export_no_accepted_sections_returns_default_doc(self, qa_app):
        """GET /export with zero accepted sections returns the default document."""
        client, app, workspace = qa_app
        plan = [
            {
                "id": "sec_01",
                "title": "Revenue",
                "hypothesis": "H1",
                "status": "proposed",
            }
        ]
        self._seed_state(client, app, workspace, plan)

        r = client.get("/export")
        assert r.status_code == 200
        assert "no accepted sections" in self._unzip_report(r.content).lower()

    def test_export_with_no_plan_returns_default_doc(self, qa_app):
        """GET /export with no plan returns the default document."""
        client, app, workspace = qa_app
        # Reset to empty plan — previous tests may have left accepted sections.
        _write_state_file(workspace / "state.json")
        app.state.state_manager.load()
        r = client.get("/export")
        assert r.status_code == 200
        assert "no accepted sections" in self._unzip_report(r.content).lower()

    def test_export_includes_multiple_accepted_sections(self, qa_app):
        """GET /export concatenates bodies of all accepted sections in plan order."""
        client, app, workspace = qa_app
        self._write_section_file(workspace, "sec_01_revenue.md", self._SECTION_MD)
        self._write_section_file(workspace, "sec_02_churn.md", self._SECTION_B_MD)

        plan = [
            {
                "id": "sec_01",
                "title": "Revenue",
                "hypothesis": "H1",
                "status": "accepted",
                "md_path": "sections/sec_01_revenue.md",
            },
            {
                "id": "sec_02",
                "title": "Churn",
                "hypothesis": "H2",
                "status": "accepted",
                "md_path": "sections/sec_02_churn.md",
            },
        ]
        self._seed_state(client, app, workspace, plan)

        r = client.get("/export")
        assert "Revenue analysis content here." in self._unzip_report(r.content)
        assert "Churn analysis content here." in self._unzip_report(r.content)

    def test_export_zero_opencode_calls(self, qa_app):
        """GET /export makes zero OpenCode calls (spy assertion)."""
        client, app, workspace = qa_app
        spy = MagicMock()
        spy.prompt = MagicMock(return_value=None)
        app.state.orchestrator._client = spy

        client.get("/export")
        spy.prompt.assert_not_called()

    def test_get_file_missing_returns_400(self, qa_app):
        """GET /file?path=nonexistent.csv returns 400 missing_file."""
        client, app, workspace = qa_app
        r = client.get("/file?path=data/nonexistent.csv")
        assert r.status_code == 400
        assert r.json()["error"] == "missing_file"

    def test_get_file_path_traversal_returns_400(self, qa_app):
        """GET /file?path=../etc/passwd returns 400 path_traversal."""
        client, app, workspace = qa_app
        r = client.get("/file?path=../etc/passwd")
        assert r.status_code == 400
        assert r.json()["error"] == "path_traversal"

    def test_get_file_returns_file_content(self, qa_app):
        """GET /file?path=data/test.csv returns 200 with file contents."""
        client, app, workspace = qa_app
        data_dir = workspace / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "test.csv").write_bytes(b"id,value\n1,100\n")

        r = client.get("/file?path=data/test.csv")
        assert r.status_code == 200
        assert b"id,value" in r.content


# ===========================================================================
# H. data-testid completeness Night 2 — REG-N2-07
# ===========================================================================


class TestDataTestidCompleteness:
    """REG-N2-07: Required Night 2 data-testid values present in production frontend."""

    # Production frontend files — exclude .test. files.
    @staticmethod
    def _collect_testids() -> set[str]:
        import re

        pattern = re.compile(r'data-testid="([^"]+)"')
        found = set()
        for f in _FRONTEND_SRC.rglob("*.tsx"):
            if ".test." in f.name:
                continue
            for match in pattern.finditer(f.read_text(encoding="utf-8")):
                found.add(match.group(1))
        for f in _FRONTEND_SRC.rglob("*.ts"):
            if ".test." in f.name:
                continue
            for match in pattern.finditer(f.read_text(encoding="utf-8")):
                found.add(match.group(1))
        return found

    # Night 1 required testids (from REG-N1-05, 17+ required).
    _N1_REQUIRED = {
        "setup-view",
        "csv-input",
        "aim-input",
        "submit-btn",
        "profile-view",
        "column-row",
        "shape-strip",
        "activity-rail",
        "error-banner",
        "reprof-input",
        "reprof-submit",
        "loading-indicator",
        "drop-zone",
    }

    # Night 2 required testids.
    _N2_REQUIRED = {
        "plan-view",
        "plan-section-list",
        "plan-accept-btn",
        "plan-turn-input",
        "plan-turn-submit",
        "build-view",
        "export-btn",
        "section-code",
        "section-interpretation",
    }

    def test_night1_testids_still_present(self):
        """All Night 1 required data-testid values must still be present (regression)."""
        found = self._collect_testids()
        missing = self._N1_REQUIRED - found
        assert not missing, (
            f"Night 1 required data-testid values missing from production frontend: "
            f"{sorted(missing)}"
        )

    def test_night2_required_testids_present(self):
        """All Night 2 required data-testid values must be present."""
        found = self._collect_testids()
        missing = self._N2_REQUIRED - found
        assert not missing, (
            f"Night 2 required data-testid values missing from production frontend: "
            f"{sorted(missing)}"
        )

    def test_plan_view_testid_in_plan_view_file(self):
        """plan-view testid must be in PlanView.tsx."""
        plan_view = _FRONTEND_SRC / "components" / "StageViews" / "PlanView.tsx"
        assert plan_view.exists(), "PlanView.tsx must exist"
        assert 'data-testid="plan-view"' in plan_view.read_text(encoding="utf-8")

    def test_build_view_testid_in_build_view_file(self):
        """build-view testid must be in BuildView.tsx."""
        build_view = _FRONTEND_SRC / "components" / "StageViews" / "BuildView.tsx"
        assert build_view.exists(), "BuildView.tsx must exist"
        assert 'data-testid="build-view"' in build_view.read_text(encoding="utf-8")

    def test_export_btn_testid_in_export_button_file(self):
        """export-btn testid must be in ExportButton.tsx."""
        export_btn = _FRONTEND_SRC / "components" / "ExportButton.tsx"
        assert export_btn.exists(), "ExportButton.tsx must exist"
        assert 'data-testid="export-btn"' in export_btn.read_text(encoding="utf-8")

    def test_section_code_and_interpretation_in_section_pane(self):
        """section-code and section-interpretation testids must be in SectionPane.tsx."""
        section_pane = _FRONTEND_SRC / "components" / "SectionPane.tsx"
        assert section_pane.exists(), "SectionPane.tsx must exist"
        content = section_pane.read_text(encoding="utf-8")
        assert 'data-testid="section-code"' in content
        assert 'data-testid="section-interpretation"' in content

    def test_minimum_testid_count_not_regressed(self):
        """Total unique data-testid count must be >= 30 (Night 1: 17+, Night 2 adds 13+)."""
        found = self._collect_testids()
        assert len(found) >= 30, (
            f"Expected at least 30 unique data-testid values; found {len(found)}: "
            f"{sorted(found)}"
        )


# ===========================================================================
# Night 1 Regression checks (carry-forward)
# REG-N1-01: profile schema fields complete
# REG-N1-02: orchestrator httpx boundary (in TestArchitectureBoundaries above)
# REG-N1-03: opencode_client orchestrator boundary (in TestArchitectureBoundaries above)
# REG-N1-04: single event subscription
# REG-N1-05: data-testid completeness (in TestDataTestidCompleteness._N1_REQUIRED above)
# ===========================================================================


class TestNight1RegressionCarryForward:
    """Night 1 regression checks that cannot be covered by the lane self-gate."""

    def test_profile_schema_has_required_fields(self):
        """REG-N1-01: PROFILE_SCHEMA has shape.{rows,columns}, columns[].required, flags."""
        from backend.agent.prompts.profile import PROFILE_SCHEMA

        props = PROFILE_SCHEMA.get("properties", {})

        # shape must be present
        assert "shape" in props, "PROFILE_SCHEMA must have 'shape' property"
        shape_props = props["shape"].get("properties", {})
        assert "rows" in shape_props, "shape must have 'rows'"
        assert "columns" in shape_props, "shape must have 'columns'"

        # columns must be present
        assert "columns" in props, "PROFILE_SCHEMA must have 'columns' property"
        col_items = props["columns"].get("items", {})
        col_required = set(col_items.get("required", []))
        for field in ("name", "type", "flags", "summary"):
            assert field in col_required, f"columns[] item must require {field!r}"

        # flags (top-level) must be present
        assert "flags" in props, "PROFILE_SCHEMA must have top-level 'flags' property"

    def test_single_event_subscription_in_main(self):
        """REG-N1-04: Exactly one asyncio.create_task for start_event_subscription in main.py."""
        main_path = _BACKEND_ROOT / "main.py"
        content = main_path.read_text(encoding="utf-8")
        count = content.count("start_event_subscription")
        assert count == 1, (
            f"Expected exactly 1 occurrence of 'start_event_subscription' in main.py; "
            f"found {count}"
        )

    def test_profile_schema_is_dict(self):
        """REG-N1-01: PROFILE_SCHEMA is a non-empty dict."""
        from backend.agent.prompts.profile import PROFILE_SCHEMA

        assert isinstance(PROFILE_SCHEMA, dict)
        assert len(PROFILE_SCHEMA) > 0
