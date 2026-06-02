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
- `feat/n1-s13-frontend-scaffold` — **N1-S13 · Frontend scaffold & stage routing** (PR #7, squash `fae8303`)
  - `App.tsx`: calls `GET /api/state` on mount, routes on `stage`, no business logic
  - Four StageView stubs at `frontend/src/components/StageViews/` with `data-testid` attributes
  - Vite `/api` proxy to `:8000` in `vite.config.ts`
  - Tailwind v4 via `@tailwindcss/vite` plugin + `@import "tailwindcss"` in `index.css`
  - 8 Vitest tests pass, lint clean; CI green on merge
  - Note: N1-S13 commit was originally on `feat/n1-s02-app-skeleton`; separated to a clean branch before merge for story-level tracking
- `feat/n1-s02-app-skeleton` — **N1-S02 · FastAPI app skeleton & event bus** (PR #6, squash `0da0543`)
  - `backend/event_bus.py`: `EventBus` fan-out pub/sub; one `asyncio.Queue` per subscriber; independent envelope copy per subscriber; no replay for late subscribers
  - `backend/router.py`: all 10 REST routes from `API_CONTRACT.html` registered with typed stubs; no route returns 404 or 5xx
  - `backend/main.py`: `lifespan` wires `EventBus` to `app.state.bus`; router mounted
  - 16 backend tests pass (5 event-bus + 10 router + 1 health); lint clean
  - Hard boundary respected: no `httpx` in router/orchestrator; no orchestrator import in client code
  - Process note: PR #6 branch also contained the original N1-S13 FE commit (branch collision); FE work was lane-clean (touches `frontend/` only). Stale remote branch `origin/feat/n1-s13-frontend-routing` confirmed identical to PR #6's FE commit and deleted post-merge.

- `feat/n1-s14-api-sse-hooks` — **N1-S14 · API & event hooks** (PR #8, squash `008a6ba`)
  - `frontend/src/hooks/useApi.ts`: `api` object with 9 typed async functions covering all REST endpoints; FormData for `/setup`; query-param encoding for `/file`; `ApiError` thrown on non-2xx
  - `frontend/src/hooks/useSSE.ts`: `useSSE(onEvent)` React hook; `EventSource("/api/events")`; 2 s reconnect on error; cleans up on unmount; returns `{ connected: boolean }`
  - `frontend/src/types/events.ts`: `SSEEvent` discriminated union over all 13 types from `SSE_CONTRACT.md §2`; field shapes match contract exactly
  - `frontend/src/types/api.ts`: `Stage`, `SectionStatus`, `ColumnType`, `ColumnProfile`, `Profile`, `Section`, `StateResponse`, `SetupResponse`, `PlanUpdateRequest`, `PlanUpdateResponse`, `ApiError` — all derived from `API_CONTRACT.html`
  - 29 tests pass (13 useApi + 8 useSSE + 8 App.test); lint clean; CI green on merge

- `feat/n1-s03-state-store` — **N1-S03 · State store & `GET /state`** (PR #9, squash `2c64c43`)
  - `backend/state_manager.py` (new): `StateManager` class; atomic write via `state.tmp.json` + `os.replace()`; `save()` / `save_async(lock)` (deferred write while turn lock held) / `update(**kwargs)` / `get_state()` / `load()`; `opencode_session_id` held internally, stripped at router boundary
  - `backend/main.py`: `StateManager()` instantiated on `app.state.state_manager` in lifespan; `load()` called at startup to re-hydrate from disk
  - `backend/router.py`: `GET /state` reads from `app.state.state_manager`; strips `opencode_session_id` before returning
  - 29 backend tests pass (9 state-manager + 10 router + 5 event-bus + 1 health + 4 sse-proxy); lint clean; CI green on merge

### In Dev / In Review / In QA

*(see startable set below)*

### Startable set (post N1-S03 merge)

All of N1-S01, N1-S07, N1-S02, N1-S13, N1-S14, and N1-S03 are now on `develop`:

- **N1-S15** (FE) — Setup screen *(fully unblocked: N1-S13 ✅ + N1-S14 ✅)*
- **N1-S17** (FE) — Activity rail *(fully unblocked: N1-S13 ✅ + N1-S14 ✅)*
- **N1-S05** (BE) — Setup endpoint *(fully unblocked: N1-S03 ✅)*
- **N1-S06** (BE) — OpenCode process & session *(fully unblocked: N1-S03 ✅)*
- **N1-S10** (BE) — SSE proxy / event streaming *(fully unblocked: N1-S02 ✅ + N1-S07 ✅)*

N1-S08 (BE) — OpenCode client & SSE normalisation: blocked on N1-S06 (which now has its prerequisite N1-S03 ✅). NOT yet startable — N1-S06 must merge first.
N1-S16 (FE) — Section view: still blocked on N1-S17.

### Blockers

*(none)*

### Overnight ADR decisions

- N1-S01 deviation: `frontend/pnpm-workspace.yaml` added with `allowBuilds: esbuild: true, @playwright/test: true` — required because pnpm v11 moved build-script approval out of `package.json` into `pnpm-workspace.yaml`; without this, `pnpm install` exits with `ERR_PNPM_IGNORED_BUILDS` in CI. No contract impact.
- N1-S07 placement: `docs/contracts/SSE_CONTRACT.md` used instead of backlog's `backend/docs/SSE_CONTRACT.md`. Consistent with CLAUDE.md rule that all contracts live in `docs/contracts/` and FE lane codes against that directory. Accepted; recorded in the document itself.
- N1-S13 branch separation: the FE agent committed the N1-S13 work onto the BE `feat/n1-s02-app-skeleton` branch. TL cherry-picked that commit to a clean `feat/n1-s13-frontend-scaffold` branch and opened PR #7 for proper story-level tracking before merging. The original commit on `feat/n1-s02-app-skeleton` remains there for the pending N1-S02 PR #6 review.
- N1-S13 Tailwind v4 deviation: `@tailwindcss/vite` plugin + `@import "tailwindcss"` (v4 pattern) instead of v3 CLI — correct for the installed version, functionally equivalent. Accepted.
- N1-S02 branch collision (post-merge note): PR #6 (`feat/n1-s02-app-skeleton`) contained both the FE agent's N1-S13 commit and the BE agent's N1-S02 commit. On review, `origin/feat/n1-s13-frontend-routing` (the FE agent's separate push) was confirmed to have identical tree content to the PR's FE commit — no work was missing. PR #6 was merged as-is (commits are lane-clean); stale `origin/feat/n1-s13-frontend-routing` deleted post-merge. Root cause: FE agent pushed to the BE branch before BE agent committed. Process improvement needed: agents should verify they are on their own branch before committing.

### Night 1 demo script (morning review)

1. Fresh clone → `make install` → `make dev`
2. Open app at http://localhost:5173 → upload `data/customers_q3.csv` + enter an aim
3. Watch profiling activity stream live in the Activity Rail
4. Confirm Profile view renders (shape strip + per-column rows)
5. Submit one bottom-bar re-profile → confirm second turn completes or recovers via fresh session
6. Refresh browser → confirm UI re-hydrates from `state.json`
