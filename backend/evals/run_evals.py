"""Eval runner — CLI entry point for the e2e eval suite.

Each invocation creates an isolated run directory under backend/evals/runs/:

    backend/evals/runs/
    └── 20260605_143022/
        ├── eval_report.json
        └── cases/
            └── customers_churn/
                └── workspace/

Usage:
    python -m backend.evals.run_evals
    python -m backend.evals.run_evals --skip-build                 # re-judge latest run
    python -m backend.evals.run_evals --skip-build --run-id 20260605_143022
    python -m backend.evals.run_evals --max-sections 1
    python -m backend.evals.run_evals --case tc001

Exit code: 0 if every case passes every rubric, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import replace as dc_replace
from datetime import datetime
from pathlib import Path

from backend.evals.judge import judge_section
from backend.evals.loader import load_artifacts, load_suite
from backend.evals.models import CaseReport, RubricResult, SuiteReport, TestCase
from backend.evals.pipeline_driver import build_case

logger = logging.getLogger(__name__)

_DEFAULT_SUITE = Path("backend/evals/test_cases.json")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Data Buddy e2e eval runner")
    p.add_argument(
        "--suite",
        type=Path,
        default=_DEFAULT_SUITE,
        help="Path to test_cases.json (default: %(default)s)",
    )
    p.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip pipeline build; judge artefacts from an existing run",
    )
    p.add_argument(
        "--run-id",
        default=None,
        metavar="ID",
        help="Re-use a specific run directory (e.g. 20260605_143022). "
        "Defaults to latest when --skip-build is set.",
    )
    p.add_argument(
        "--max-sections",
        type=int,
        default=None,
        metavar="N",
        help="Truncate each case plan to N sections (faster dev loops)",
    )
    p.add_argument(
        "--case",
        default=None,
        metavar="ID",
        help="Run only the case with this id (matches TestCase.id, e.g. tc001)",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Run directory management
# ---------------------------------------------------------------------------


def _resolve_run_dir(suite_path: Path, run_id: str | None, skip_build: bool) -> tuple[str, Path]:
    """Return (run_id, run_dir), creating the directory if needed.

    - New build (no --run-id, no --skip-build): generates a timestamp ID.
    - --skip-build without --run-id: picks the most recent existing run.
    - --run-id always wins, whether building or skipping.
    """
    runs_root = suite_path.parent / "runs"

    if run_id is None and skip_build:
        if not runs_root.exists():
            raise SystemExit(
                "--skip-build: no runs directory found. Run without --skip-build first."
            )  # noqa: E501
        existing = sorted(d.name for d in runs_root.iterdir() if d.is_dir())
        if not existing:
            raise SystemExit(
                "--skip-build: no existing runs found. Run without --skip-build first."
            )  # noqa: E501
        run_id = existing[-1]
        logger.info("--skip-build: using latest run %s", run_id)

    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_id, run_dir


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


async def run_suite(
    suite_path: Path,
    run_dir: Path,
    skip_build: bool = False,
    max_sections: int | None = None,
    case_filter: str | None = None,
) -> SuiteReport:
    cases = load_suite(suite_path)

    if case_filter:
        cases = [c for c in cases if c.id == case_filter]
        if not cases:
            raise SystemExit(f"No case with id {case_filter!r} in {suite_path}")

    # Bind each case's workspace to this run's directory.
    cases = [dc_replace(c, workspace=run_dir / "cases" / c.id / "workspace") for c in cases]

    report = SuiteReport()
    for case in cases:
        case_report = await _run_case(case, skip_build=skip_build, max_sections=max_sections)
        report.cases.append(case_report)
        _print_case_summary(case_report)
        _write_report(report, run_dir)

    return report


async def _run_case(
    case: TestCase,
    skip_build: bool,
    max_sections: int | None,
) -> CaseReport:
    if not skip_build:
        logger.info("runner: building case %r", case.id)
        await build_case(case, max_sections=max_sections)

    brief = case.golden_brief
    artifacts = load_artifacts(case)

    if not artifacts:
        logger.warning("runner: no built sections for case %r — skipping judge", case.id)
        return CaseReport(case_name=case.id)

    sections: list[RubricResult] = [judge_section(a, brief, case.aim) for a in artifacts]
    return CaseReport(case_name=case.id, sections=sections)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _print_case_summary(report: CaseReport) -> None:
    print(f"\n{'=' * 60}")
    print(f"Case: {report.case_name}")
    print(f"{'=' * 60}")
    for s in report.sections:
        print(f"  {s.section_id}")
        for rubric in (
            "relevant",
            "uses_reasonable_fields",
            "claims_supported_by_script",
            "claims_consistent_with_golden_brief",
            "writeup_is_descriptive",
        ):
            verdict = getattr(s, rubric)
            reason = s.reasoning.get(rubric, "")
            mark = "✓" if verdict == "PASS" else "✗"
            print(f"       {mark} {rubric}: {verdict}")
            if verdict == "FAIL":
                print(f"         → {reason}")


def _print_suite_summary(report: SuiteReport, run_id: str, run_dir: Path) -> None:
    n_sections = sum(len(c.sections) for c in report.cases)
    print(f"\n{'=' * 60}")
    print(f"Suite summary  ({report.total_cases} cases, {n_sections} sections)")
    for key, stats in report.rubric_summary.items():
        mark = "✓" if stats["pct"] == 100 else "✗" if stats["pct"] == 0 else "~"
        print(f"  {mark} {key}: {stats['pct']}% ({stats['pass']}/{stats['total']})")
    print(f"Run ID  : {run_id}")
    print(f"Report  : {run_dir / 'eval_report.json'}")
    print(f"{'=' * 60}\n")


def _write_report(report: SuiteReport, run_dir: Path) -> Path:
    out_path = run_dir / "eval_report.json"
    out_path.write_text(
        json.dumps(_serialise_suite(report), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return out_path


# ---------------------------------------------------------------------------
# Serialisation (properties aren't picked up by dataclasses.asdict)
# ---------------------------------------------------------------------------


def _serialise_rubric(r: RubricResult) -> dict:
    return {
        "section_id": r.section_id,
        "relevant": r.relevant,
        "uses_reasonable_fields": r.uses_reasonable_fields,
        "claims_supported_by_script": r.claims_supported_by_script,
        "claims_consistent_with_golden_brief": r.claims_consistent_with_golden_brief,
        "writeup_is_descriptive": r.writeup_is_descriptive,
        "reasoning": r.reasoning,
    }


def _serialise_case(c: CaseReport) -> dict:
    return {
        "case_name": c.case_name,
        "sections": [_serialise_rubric(s) for s in c.sections],
    }


def _serialise_suite(s: SuiteReport) -> dict:
    return {
        "total_cases": s.total_cases,
        "rubric_summary": s.rubric_summary,
        "cases": [_serialise_case(c) for c in s.cases],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args()

    run_id, run_dir = _resolve_run_dir(args.suite, args.run_id, args.skip_build)
    print(f"\nRun ID: {run_id}  →  {run_dir}\n")

    report = asyncio.run(
        run_suite(
            suite_path=args.suite,
            run_dir=run_dir,
            skip_build=args.skip_build,
            max_sections=args.max_sections,
            case_filter=args.case,
        )
    )

    _print_suite_summary(report, run_id, run_dir)
    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
