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

### In Dev / In Review / In QA

*(none yet — N1-S01 just landed; dependent stories now startable)*

### t0 Startable set

All Night 1 stories with no dependencies, or whose dependencies are now merged:

- **N1-S07** (BE) — Reconciled event contract ⛔ BLOCKING *(no deps — must merge before any SSE work)*

Unlocked by N1-S01 (now merged):
- **N1-S02** (BE) — FastAPI app skeleton & event bus
- **N1-S13** (FE) — Frontend scaffold & routing

Unlocks after N1-S07:
- N1-S08 (BE) · N1-S14 (FE) *(both depend on N1-S07)*

### Blockers

*(none)*

### Overnight ADR decisions

- N1-S01 deviation: `frontend/pnpm-workspace.yaml` added with `allowBuilds: esbuild: true, @playwright/test: true` — required because pnpm v11 moved build-script approval out of `package.json` into `pnpm-workspace.yaml`; without this, `pnpm install` exits with `ERR_PNPM_IGNORED_BUILDS` in CI. No contract impact.

### Night 1 demo script (morning review)

1. Fresh clone → `make install` → `make dev`
2. Open app at http://localhost:5173 → upload `data/customers_q3.csv` + enter an aim
3. Watch profiling activity stream live in the Activity Rail
4. Confirm Profile view renders (shape strip + per-column rows)
5. Submit one bottom-bar re-profile → confirm second turn completes or recovers via fresh session
6. Refresh browser → confirm UI re-hydrates from `state.json`
