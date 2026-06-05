from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.core.frontmatter_parser import parse_section_file
from backend.evals.models import GoldBrief, SectionArtifacts, TestCase

logger = logging.getLogger(__name__)


def load_suite(path: Path) -> list[TestCase]:
    """Parse test_cases.json and return all declared test cases.

    All relative paths in the JSON are resolved against the manifest's
    parent directory so the file can live anywhere in the tree.
    """
    path = Path(path).resolve()
    base = path.parent
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        TestCase(
            id=item["id"],
            dataset=(base / item["dataset"]).resolve(),
            aim=item["aim"],
            golden_brief=_parse_golden_brief(item["golden_brief"]),
        )
        for item in raw["cases"]
    ]


def _parse_golden_brief(raw: dict) -> GoldBrief:
    return GoldBrief(
        target=raw["target"],
        relevant_fields=raw["relevant_fields"],
        irrelevant_fields=raw["irrelevant_fields"],
        known_patterns=raw["known_patterns"],
        forbidden_claims=raw["forbidden_claims"],
    )


def load_artifacts(case: TestCase) -> list[SectionArtifacts]:
    """Load built section artifacts from a case workspace.

    Reads state.json, then for every section whose py_path and md_path
    are both set and exist on disk, returns a SectionArtifacts.  Sections
    with missing files are skipped with a warning rather than hard-failing
    so a partially-built workspace still produces a partial report.
    """
    state = json.loads((case.workspace / "state.json").read_text(encoding="utf-8"))

    artifacts: list[SectionArtifacts] = []
    for section in state.get("plan", []):
        py_rel = section.get("py_path")
        md_rel = section.get("md_path")
        if not py_rel or not md_rel:
            continue

        py_path = case.workspace / py_rel
        md_path = case.workspace / md_rel

        if not py_path.exists():
            logger.warning("script missing for %s: %s", section["id"], py_path)
            continue
        if not md_path.exists():
            logger.warning("writeup missing for %s: %s", section["id"], md_path)
            continue

        script = py_path.read_text(encoding="utf-8")
        parsed = parse_section_file(md_path)
        if parsed["parse_error"]:
            writeup = md_path.read_text(encoding="utf-8")
        else:
            writeup = parsed["body"]

        artifacts.append(
            SectionArtifacts(
                section_id=section["id"],
                title=section["title"],
                hypothesis=section["hypothesis"],
                script=script,
                writeup=writeup,
            )
        )

    return artifacts
