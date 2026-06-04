"""Section build prompt template for the section-build turn.

Used by the orchestrator when it fires the section-build turn against OpenCode:
    client.prompt(session_id, build_section_prompt(...))
    # Note: schema=None — the default; no format block sent to OpenCode (ADR-005)

Unlike the profile and plan prompts, the section build uses NO structured output.
The section's structure is the file triplet it produces on disk (ADR-005):
  - analyses/sec_NN_<slug>.py   — Python analysis script
  - charts/sec_NN_<slug>.png    — rendered chart (matplotlib)
  - sections/sec_NN_<slug>.md   — interpretation text with YAML frontmatter

Per ADR-004: structured output (format: json_schema) is used for profile and plan
only. Forcing the section through a JSON schema is infeasible: the chart artifact
is binary, the script may be hundreds of lines, and the frontmatter is
deterministically parseable by the backend independently.

Per ADR-005: every prompt re-supplies full context (aim, profile, plan) — the
agent must not depend on its own conversational history.

Per ADR-011: all file paths in the prompt are absolute so OpenCode can locate
files even when workspace/ is gitignored and therefore invisible to glob tools.

The redirect prompt for Stage 4b bottom-bar re-runs belongs in
backend/prompts/redirect.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def _make_slug(title: str) -> str:
    """Convert a section title to a filesystem-safe slug.

    Transformation rules:
    - Non-ASCII characters are replaced with underscores.
    - Non-alphanumeric characters (after ASCII conversion) become underscores.
    - Consecutive underscores are collapsed to one.
    - Leading and trailing underscores are stripped.
    - Lowercased.
    - Truncated to 40 characters maximum.

    Args:
        title: The section title from plan.json.

    Returns:
        A filesystem-safe slug string, at most 40 characters long.
    """
    # Replace non-ASCII characters with underscores (filesystem-safe)
    ascii_safe = title.encode("ascii", errors="replace").decode("ascii")
    ascii_safe = ascii_safe.replace("?", "_")  # encode replaces non-ASCII with '?'

    # Lowercase
    lowered = ascii_safe.lower()

    # Replace non-alphanumeric characters with underscores
    slugged = re.sub(r"[^a-z0-9]+", "_", lowered)

    # Strip leading/trailing underscores
    stripped = slugged.strip("_")

    # Truncate to 40 characters
    return stripped[:40]


def build_section_prompt(
    section_id: str,
    section_index: int,
    title: str,
    hypothesis: str,
    aim: str,
    dataset: str,
    profile: dict,
    plan: dict,
    workspace_root: Path | str = Path("workspace"),
) -> str:
    """Build the section-build turn prompt for OpenCode.

    Produces a fully self-contained prompt string that instructs OpenCode to:
    1. Write a Python analysis script to analyses/sec_NN_<slug>.py via apply_patch.
    2. Execute the script via bash.
    3. Save any chart output to charts/sec_NN_<slug>.png.
    4. Write the section markdown to sections/sec_NN_<slug>.md via apply_patch,
       with a YAML frontmatter block containing section_id, title, hypothesis, chart.

    No schema= argument should be passed to client.prompt() — this is a free-form
    turn; the triplet files on disk are the structured output (ADR-005).

    Args:
        section_id: Section identifier from plan.json, e.g. "sec_01".
        section_index: 1-based positional index in plan.json's sections array.
            Used to derive the zero-padded NN in filenames (e.g. 1 → "01").
        title: Section title from plan.json.
        hypothesis: Section hypothesis from plan.json.
        aim: The user's stated analysis aim.
        dataset: Filename of the uploaded dataset, e.g. "customers_q3.csv".
        profile: Full profile dict (contents of profile.json).
        plan: Full plan dict (contents of plan.json, all sections).
        workspace_root: Absolute (or resolvable) path to the workspace directory.
            Passed as an absolute path so OpenCode can locate files even when the
            workspace directory is excluded from git (ADR-011).

    Returns:
        A fully self-contained prompt string for the section-build turn.

    Raises:
        TypeError: If workspace_root is None (propagated from Path(None)).
    """
    ws = Path(workspace_root).resolve()

    # Derive the two-digit zero-padded section number and slug
    nn = str(section_index).zfill(2)
    slug = _make_slug(title)
    base_name = f"sec_{nn}_{slug}"

    # Absolute triplet paths
    analyses_path = ws / "analyses" / f"{base_name}.py"
    charts_path = ws / "charts" / f"{base_name}.png"
    sections_path = ws / "sections" / f"{base_name}.md"
    csv_path = ws / "data" / dataset

    # Serialise profile and plan as JSON for the agent
    profile_json = json.dumps(profile, indent=2)
    plan_json = json.dumps(plan, indent=2)

    # Workspace-relative chart path for frontmatter (not absolute — so the
    # exported .md references a predictable relative path)
    chart_relative = f"charts/{base_name}.png"

    return (
        f"You are a data analyst. Build section {section_id} of the analysis brief.\n\n"
        f"Section title: {title}\n"
        f"Hypothesis: {hypothesis}\n"
        f"Analysis aim: {aim}\n"
        f"Dataset: {csv_path}\n\n"
        "Follow these steps in order. Use apply_patch for all file writes.\n\n"
        f"Step 1 — Write a Python analysis script to {analyses_path}.\n"
        "  Requirements:\n"
        f"  - Read the dataset from {csv_path}\n"
        "  - Perform analysis relevant to the hypothesis\n"
        f"  - Produce a chart saved to {charts_path} using matplotlib (savefig, not show)\n"
        "  - Include all imports; the script must be self-contained\n\n"
        f"Step 2 — Execute the script via bash: run {analyses_path}\n"
        "  If the script errors, fix it and rerun until the chart file is produced.\n\n"
        f"Step 3 — Write the section to {sections_path} using apply_patch.\n"
        "  The file must begin with a YAML frontmatter block in this exact format:\n\n"
        "  ---\n"
        f"  section_id: {section_id}\n"
        f'  title: "{title}"\n'
        f'  hypothesis: "{hypothesis}"\n'
        f"  chart: {chart_relative}\n"
        "  ---\n\n"
        "  After the closing ---, write one paragraph interpreting the chart findings\n"
        "  in the context of the hypothesis. Reference actual values from the analysis.\n\n"
        "Profile context (profile.json):\n"
        f"{profile_json}\n\n"
        "Plan context (plan.json):\n"
        f"{plan_json}\n"
    )
