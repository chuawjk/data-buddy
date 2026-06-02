# DEV_STATUS.md

*Single writer: TL. All other agents read only. Updated at the end of each overnight run.*

---

## Current branch: `develop`

Pre-sprint infrastructure merged (PR #2, squash commit `69ae52f`):
- `.github/workflows/ci.yml` — single `ci` job; triggers on push/PR to `main` and `develop`; sets up uv + Python 3.12, Node 22, pnpm; runs `make install` → `make lint` → `make test`.

---

## Night 1 — Walking skeleton through Profiling

### Merged to `develop`

- `chore/ci-workflow` — GitHub Actions CI workflow (pre-sprint infra, PR #2, `69ae52f`)
- `feat/n1-s01-scaffold` — **N1-S01 · Project scaffold & dev loop** (PR #3, squash `77c8550`)
  - `Makefile`: `install`, `dev`, `test`, `lint`, `format` targets
  - `backend/`: `main.py` stub, `pyproject.toml` (FastAPI/uvicorn/httpx/httpx-sse + ruff/pytest), `uv.lock`, `tests/{unit,integration}/` skeleton
  - `frontend/`: Vite+React+TS scaffold, ESLint, Prettier, Vitest, Playwright, `pnpm-workspace.yaml`
  - `.pre-commit-config.yaml`: ruff hooks
  - `CLAUDE.md`: frontend module map updated
  - CI green on merge
- `feat/n1-s07-sse-contract` — **N1-S07 · Reconciled SSE event contract** (PR #5, squash `117dfc1`)
  - `docs/contracts/SSE_CONTRACT.md`: authoritative mapping of all 13 backend→SPA event types
  - All 6 divergences (D1–D6) documented with handler-actionable detail
  - Placement at `docs/contracts/` (not `backend/docs/`) accepted; rationale recorded in the doc
  - CI pending at merge time (pre-N1-S01 state; expected); merged with `--admin`

### In Dev / In Review / In QA

*(see startable set below)*

### Startable set (post N1-S07 merge)

N1-S07 was the blocking prerequisite for all SSE handler work. With it merged:

- **N1-S02** (BE) — FastAPI app skeleton & event bus *(depends on N1-S01 — now unblocked)*
- **N1-S13** (FE) — Frontend scaffold & routing *(depends on N1-S01 — now unblocked)*
- **N1-S08** (BE) — OpenCode client & SSE normalisation *(depends on N1-S07 + N1-S02; partially unblocked — needs N1-S02 first)*
- **N1-S10** (BE) — Watchdog & session recovery *(depends on N1-S07 + N1-S02; partially unblocked — needs N1-S02 first)*
- **N1-S14** (FE) — SSE hook & activity rail *(depends on N1-S07 + N1-S13; partially unblocked — needs N1-S13 first)*

### Blockers

*(none)*

### Overnight ADR decisions

- N1-S01 deviation: `frontend/pnpm-workspace.yaml` added with `allowBuilds: esbuild: true, @playwright/test: true` — required because pnpm v11 moved build-script approval out of `package.json` into `pnpm-workspace.yaml`; without this, `pnpm install` exits with `ERR_PNPM_IGNORED_BUILDS` in CI. No contract impact.
- N1-S07 placement: `docs/contracts/SSE_CONTRACT.md` used instead of backlog's `backend/docs/SSE_CONTRACT.md`. Consistent with CLAUDE.md rule that all contracts live in `docs/contracts/` and FE lane codes against that directory. Accepted; recorded in the document itself.

### Night 1 demo script (morning review)

1. Fresh clone → `make install` → `make dev`
2. Open app at http://localhost:5173 → upload `data/customers_q3.csv` + enter an aim
3. Watch profiling activity stream live in the Activity Rail
4. Confirm Profile view renders (shape strip + per-column rows)
5. Submit one bottom-bar re-profile → confirm second turn completes or recovers via fresh session
6. Refresh browser → confirm UI re-hydrates from `state.json`
