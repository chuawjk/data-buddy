"""Plan prompt template and JSON Schema for the planning turn.

Used by the orchestrator when it fires the planning turn against OpenCode:
    client.prompt(session_id, build_plan_prompt(dataset, aim, profile, workspace_root),
                  schema=PLAN_SCHEMA)

The schema is passed to OpenCode's native structured-output mechanism via:
    format: { type: "json_schema", schema: PLAN_SCHEMA, retryCount: 2 }

Per ADR-004: use native json_schema structured output for all turns that need
machine-parseable output; never rely on prompt-engineering JSON extraction.

Per ADR-011: the prompt also explicitly instructs OpenCode to write the JSON
to workspace/plan.json (belt-and-suspenders — structured output is passed via
the format param, but the agent is also asked to write the file directly).

Out of scope: profile / section prompts (own stories).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PLAN_SCHEMA: dict = {
    "type": "object",
    "required": ["sections"],
    "properties": {
        "sections": {
            "type": "array",
            "minItems": 3,
            "maxItems": 6,
            "items": {
                "type": "object",
                "required": ["id", "title", "hypothesis"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "hypothesis": {"type": "string"},
                },
            },
        }
    },
}


def build_plan_prompt(
    dataset: str,
    aim: str,
    profile: dict[str, Any],
    workspace_root: Path | str,
) -> str:
    """Build the planning turn prompt for OpenCode.

    Args:
        dataset: Filename of the uploaded dataset (e.g. ``"customers_q3.csv"``).
        aim: The user's stated analysis aim.
        profile: The parsed profile dict (from state.json / profile.json).  May
            be an empty dict if profiling produced no output.
        workspace_root: Absolute (or resolvable) path to the workspace directory.
            Passed as an absolute path so OpenCode can locate and write files.

    Returns:
        A fully self-contained prompt string for the planning turn.
    """
    ws = Path(workspace_root).resolve()
    csv_path = ws / "data" / dataset
    plan_path = ws / "plan.json"
    profile_json = json.dumps(profile, indent=2, ensure_ascii=False)

    return (
        f"You are a data analyst. Draft a structured analysis plan for the following brief.\n\n"
        f"Analysis aim: {aim}\n\n"
        f"Dataset: {csv_path}\n\n"
        f"Data profile:\n{profile_json}\n\n"
        "Based on the aim and profile above, propose 3–6 analysis sections.\n"
        "Each section must have:\n"
        "  - id: a short unique identifier (e.g. 'sec_01', 'sec_02', ...)\n"
        "  - title: a concise section title\n"
        "  - hypothesis: a testable hypothesis or question the section will answer\n\n"
        f"Write the plan as a JSON object to {plan_path} with this structure:\n"
        '  {"sections": [{"id": "sec_01", "title": "...", "hypothesis": "..."}, ...]}\n\n'
        "Do not output the JSON to the console — write it directly to the file.\n"
        "Return between 3 and 6 sections."
    )
