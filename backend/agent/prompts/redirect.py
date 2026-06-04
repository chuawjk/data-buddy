"""Redirect prompt template for Stage 4b section rebuild.

Used by the orchestrator when the user submits bottom-bar text while a section
is building.  Instructs OpenCode to discard any draft artefacts and rebuild
the section from scratch applying the user's redirect instruction.

Like the section build prompt, the redirect uses NO structured output
(schema=None).  The rebuilt section's structure is the file triplet on disk
(ADR-005):
  - analyses/sec_NN_<slug>.py   — Python analysis script
  - charts/sec_NN_<slug>.png    — rendered chart (matplotlib)
  - sections/sec_NN_<slug>.md   — interpretation text with YAML frontmatter

Per ADR-011: all file paths in the prompt are absolute so OpenCode can locate
files even when workspace/ is gitignored.

Per ADR-005: every prompt re-supplies full context (aim, profile, plan) — the
agent must not depend on its own conversational history.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def _make_slug(title: str) -> str:
    """Convert a section title to a filesystem-safe slug.

    Identical to the slug function in backend.prompts.section — duplicated here
    to keep this module independently importable without a circular dependency.

    Args:
        title: The section title from plan.json.

    Returns:
        A filesystem-safe slug string, at most 40 characters long.
    """
    ascii_safe = title.encode("ascii", errors="replace").decode("ascii")
    ascii_safe = ascii_safe.replace("?", "_")
    lowered = ascii_safe.lower()
    slugged = re.sub(r"[^a-z0-9]+", "_", lowered)
    stripped = slugged.strip("_")
    return stripped[:40]


def build_redirect_prompt(
    section_id: str,
    section_index: int,
    title: str,
    hypothesis: str,
    aim: str,
    dataset: str,
    profile: dict,
    plan: list,
    redirect_text: str,
    workspace_root: Path | str = Path("workspace"),
) -> str:
    """Build the redirect turn prompt for OpenCode.

    Produces a fully self-contained prompt string that instructs OpenCode to:
    1. Discard (overwrite/delete) the current draft artefacts for this section.
    2. Rebuild from scratch, applying the user's redirect instruction.
    3. Write the same file triplet as the original section build:
       analyses/sec_NN_<slug>.py, charts/sec_NN_<slug>.png,
       sections/sec_NN_<slug>.md with YAML frontmatter.

    No schema= argument should be passed to client.prompt() — this is a free-form
    turn; the triplet files on disk are the structured output (ADR-005).

    Args:
        section_id: Section identifier from plan.json, e.g. "sec_01".
        section_index: 1-based positional index in plan.json's sections array.
        title: Section title from plan.json.
        hypothesis: Section hypothesis from plan.json.
        aim: The user's stated analysis aim.
        dataset: Filename of the uploaded dataset, e.g. "customers_q3.csv".
        profile: Full profile dict (contents of profile.json).
        plan: Full plan list (contents of plan.json, all sections).
        redirect_text: The user's redirect instruction (bottom-bar text).
        workspace_root: Absolute (or resolvable) path to the workspace directory.

    Returns:
        A fully self-contained redirect prompt string.

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

    # Workspace-relative chart path for frontmatter
    chart_relative = f"charts/{base_name}.png"

    return (
        f"You are a data analyst. The user has redirected section {section_id} "
        f"while it was building.\n\n"
        f"User's redirect instruction: {redirect_text}\n\n"
        f"Section title: {title}\n"
        f"Hypothesis: {hypothesis}\n"
        f"Analysis aim: {aim}\n"
        f"Dataset: {csv_path}\n\n"
        "Discard any prior draft artefacts for this section and rebuild from "
        "scratch applying the user's instruction above.\n\n"
        "Follow these steps in order. Use apply_patch for all file writes.\n\n"
        f"Step 0 — Delete any existing draft files for this section:\n"
        f"  - If {analyses_path} exists, overwrite it with the new script.\n"
        f"  - If {charts_path} exists, it will be replaced by the new chart.\n"
        f"  - If {sections_path} exists, overwrite it with the new section text.\n\n"
        f"Step 1 — Write a Python analysis script to {analyses_path}.\n"
        "  Requirements:\n"
        f"  - Read the dataset from {csv_path}\n"
        "  - Perform analysis relevant to the hypothesis\n"
        f"  - Apply the user's redirect instruction: {redirect_text}\n"
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
        "  in the context of the hypothesis, incorporating the redirect instruction.\n"
        "  Reference actual values from the analysis.\n\n"
        "Profile context (profile.json):\n"
        f"{profile_json}\n\n"
        "Plan context (plan.json):\n"
        f"{plan_json}\n"
    )
