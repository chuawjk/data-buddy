"""Profile prompt template and JSON Schema for the profiling turn.

Used by the orchestrator when it fires the profiling turn against OpenCode:
    client.prompt(session_id, build_profile_prompt(dataset, aim), schema=PROFILE_SCHEMA)

The schema is passed to OpenCode's native structured-output mechanism via:
    format: { type: "json_schema", json_schema: { name: "output", schema: PROFILE_SCHEMA },
              retryCount: 2 }

Per ADR-004: use native json_schema structured output for all turns that need
machine-parseable output; never rely on prompt-engineering JSON extraction.

Out of scope: plan / section prompts (own stories).
"""

from __future__ import annotations

from pathlib import Path

PROFILE_SCHEMA: dict = {
    "type": "object",
    "required": ["shape", "columns", "flags"],
    "properties": {
        "shape": {
            "type": "object",
            "required": ["rows", "columns", "target"],
            "properties": {
                "rows": {"type": "integer"},
                "columns": {"type": "integer"},
                "target": {"type": ["string", "null"]},
            },
        },
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "flags", "summary"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["numeric", "categorical", "datetime", "text"],
                    },
                    "flags": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                },
            },
        },
        "flags": {"type": "array", "items": {"type": "string"}},
    },
}


def build_profile_prompt(dataset: str, aim: str, workspace_root: Path | str) -> str:
    """Build the profiling turn prompt for OpenCode.

    Args:
        dataset: Filename of the uploaded dataset (e.g. ``"customers_q3.csv"``).
        aim: The user's stated analysis aim.
        workspace_root: Absolute (or resolvable) path to the workspace directory.
            Passed as an absolute path so OpenCode can locate files even when the
            workspace directory is excluded from git (and therefore invisible to
            OpenCode's glob tooling, which respects .gitignore).

    Returns:
        A fully self-contained prompt string for the profiling turn.
    """
    ws = Path(workspace_root).resolve()
    csv_path = ws / "data" / dataset
    profile_path = ws / "profile.json"
    return (
        f"You are a data analyst. Profile the CSV at {csv_path}.\n\n"
        f"Analysis aim: {aim}\n\n"
        "Read the file and analyse it. Then write a JSON object to "
        f"{profile_path} describing:\n"
        "- shape: total rows and columns, plus target: the column name most likely "
        "being predicted or explained given the analysis aim (set to null if it "
        "cannot be inferred)\n"
        "- columns: for each column, its name, inferred type "
        "(numeric/categorical/datetime/text), notable flags "
        "(nullable, low_cardinality, high_cardinality, skewed, constant, id_like), "
        "and a one-sentence summary\n"
        "- flags: dataset-level flags (e.g. small_dataset, high_dimensionality)\n\n"
        f"Write valid JSON matching the schema exactly to {profile_path}. "
        "Do not output the JSON to the console — write it directly to the file."
    )
