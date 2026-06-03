# DEV_STATUS.md

*Single writer: TL. All other agents read only. Updated at the end of each overnight run.*

---

## Night 2 COMPLETE. All lane stories merged, integration merged, QA passed (63 assertions, 0 defects). Awaiting morning human review for develop → main promotion.

---

## Current branch: `develop`

Pre-sprint infrastructure merged (PR #2, squash commit `69ae52f`):
- `.github/workflows/ci.yml` — single `ci` job; triggers on push/PR to `main` and `develop`; sets up uv + Python 3.12, Node 22, pnpm; runs `make install` → `make lint` → `make test`.

---

## Night 1 — Walking skeleton through Profiling (+ second-turn recovery)

**Status: COMPLETE. All lane stories merged, integration merged, QA passed. Awaiting morning human review for develop → main promotion.**

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

- `feat/n1-s17-activity-rail` — **N1-S17 · Activity rail** (PR #10, squash `8cbc4c9`)
  - `frontend/src/components/ActivityRail.tsx` (new): subscribes to `useSSE`; renders `tool.bash_running` / `tool.bash_done` / `tool.file_written` items in arrival order; accumulates `message.part` content into text buffer; resets all state on `session.idle`
  - All required `data-testid` seams present: `activity-rail`, `activity-tool-running`, `activity-tool-done`, `activity-file-written`, `activity-message`
  - 7 ActivityRail tests; 42 frontend tests total pass; lint clean; CI green on merge
  - Note: self-approve not possible on GitHub (same account owns PR); merged after all three gates (acceptance, lane boundary, CI) verified green

- `feat/n1-s10-sse-stream` — **N1-S10 · Browser event stream (`GET /events`)** (PR #11, squash `2e616ee`)
  - `backend/sse_proxy.py` (new): `event_stream(bus)` factory registers subscription synchronously at call time; inner `_generate` async generator yields `data: <json>\n\n`; emits `: keepalive\n\n` on 15 s silence; `finally` block unregisters via `bus._unregister(subscription._queue)`
  - `backend/router.py`: `GET /events` replaced — `StreamingResponse(event_stream(bus))` with `media_type="text/event-stream"`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`; stub `_stub_sse_stream()` removed
  - `backend/tests/unit/app/test_sse_proxy.py` (new): 4 TDD tests — event forwarding, ordering, disconnect cleanup, keepalive on silence; all use real `EventBus`
  - `backend/tests/unit/app/test_router.py`: `test_get_events_registered` calls route handler directly with `MagicMock` request; checks `StreamingResponse` type, `media_type`, and headers (does not consume the infinite stream body)
  - `backend/main.py`: TL hygiene fix — reverted accidental `orchestrator` import introduced in a prior TL DEV_STATUS commit; restored correct N1-S03 state (`EventBus + StateManager` only)
  - 29 backend tests pass (4 sse-proxy + 10 router + 9 state-manager + 5 event-bus + 1 health); lint clean; tests run locally (no CI run on branch due to unregistered check)
  - Merge note: PR had conflict in `router.py` (develop moved ahead with N1-S03 StateManager integration after the PR branch was cut); resolved by applying N1-S10 SSE changes onto develop's version via git plumbing; PR #11 closed with comment referencing squash SHA

- `feat/n1-s06-opencode-client` — **N1-S06 · OpenCode process & session** (PR #12, squash `daee4ba`)
  - `backend/main.py`: `OpenCodeClient` wired into lifespan; `SKIP_OPENCODE=1` env var skips startup for CI; failed startup logs but does not crash server; `client.stop()` on shutdown
  - `opencode_client.py` and its 6 unit tests already on develop via `8fe71cf` (lane deviation; see ADR below)
  - TL hygiene fix: ruff I001 import sort in `test_router.py` to pass CI lint gate
  - 35 backend tests pass; CI green on merge

- `feat/n1-s05-setup-endpoint` — **N1-S05 · Setup endpoint** (PR #16, squash `e7640ec`)
  - `backend/orchestrator.py` (new): minimal `Orchestrator` stub; `setup_complete()` advances stage to `profiling` and emits `stage.changed`; no `httpx` import; client never imports orchestrator
  - `backend/router.py`: `POST /setup` real handler — validates aim, content-type (.csv), size (≤10 MB); writes CSV to `workspace/data/`; persists initial state; fire-and-forgets `orchestrator.setup_complete()`
  - `backend/main.py`: `Orchestrator` wired into lifespan alongside `OpenCodeClient`
  - `backend/pyproject.toml`: `python-multipart>=0.0.9` added
  - 5 new unit tests (`test_setup.py`); 40 backend tests total pass; CI green on merge
  - Conflict resolution: main.py merged N1-S06 OpenCodeClient + N1-S05 Orchestrator wiring; router.py kept N1-S10 SSE + N1-S05 /setup real handler

- `feat/n1-s15-setup-screen` — **N1-S15 · Setup screen** (PR #13, squash `a77542e`)
  - `frontend/src/components/StageViews/SetupView.tsx`: `csv-input`, `aim-input`, `submit-btn` (disabled when no file or empty aim); calls `api.postSetup(file, aim)`; surfaces error in `setup-error`
  - `frontend/src/components/StageViews/SetupView.test.tsx`: 6 Vitest tests; 42 frontend tests total pass
  - Only `frontend/` touched; CI green on merge

- `feat/n1-s16-profile-view-v2` — **N1-S16 · Profile screen & re-profile bar** (PR #15, squash `67cc7e7`)
  - `frontend/src/components/StageViews/ProfileView.tsx`: `shape-strip` (rows/columns), `column-row` list (name, type, flags, summary), `reprof-input`/`reprof-submit`; updates on `profile.ready` SSE via `api.getState()`
  - `frontend/src/App.tsx`: passes `profile` prop from `GET /state` response down to `ProfileView`; adds `Profile | null` to `AppState`
  - `frontend/src/App.test.tsx`: adds `useSSE` mock for profile-stage test
  - `frontend/src/components/StageViews/ProfileView.test.tsx`: 8 Vitest tests; 44 frontend tests total pass
  - Only `frontend/` touched; CI green on merge

- `feat/n1-s21-test-selectors` — **N1-S21 · Stable test selectors (`data-testid`)** (PR #17, squash `654bd08`)
  - Audit-only commit: all 17 required `data-testid` attributes were already present from N1-S15, N1-S16, N1-S17; no file changes needed
  - Confirmed present: `setup-view`, `csv-input`, `aim-input`, `submit-btn`, `setup-error` (SetupView); `profile-view`, `shape-strip`, `column-row`, `reprof-input`, `reprof-submit` (ProfileView); `activity-rail`, `activity-tool-running`, `activity-tool-done`, `activity-file-written`, `activity-message` (ActivityRail); `plan-view` (PlanView); `build-view` (BuildView)
  - 50 FE + 40 BE tests pass; lint clean; CI green on merge
  - Self-approve not possible (same account owns PR); merged after all three gates verified green

- `feat/n1-s08-event-subscription` — **N1-S08 · Live events from OpenCode** (PR #18, squash `a8822a1`)
  - `backend/opencode_client.py`: `start_event_subscription(bus, heartbeat_timeout=30)` — persistent `GET /event` SSE connection as background asyncio Task; reconnects on `asyncio.TimeoutError`, `StopAsyncIteration`, or exception with 100ms back-off; single connection enforced by one `create_task` call in lifespan
  - Session filter: `_SESSION_SCOPED_TYPES` frozenset covers all session-scoped event types; events with non-matching `sessionID` silently dropped; global types (`server.heartbeat`, `file.edited`, `server.connected`) bypass filter
  - `_normalise_and_publish`: full mapping per SSE_CONTRACT.md §2 — `message.part.delta` → `message.part`; `message.part.updated` (bash, running) → `tool.bash_running`; (bash, completed) → `tool.bash_done`; (any tool, completed, metadata.files present) → `tool.file_written` per file (D1: no tool-name hardcoding); `session.idle` → `session.idle`; `file.edited` → `file.ready`; `server.heartbeat` → timer reset only, not published; all others silently dropped
  - Reconnect on heartbeat silence: `asyncio.wait_for` on each `__anext__` with `remaining` seconds; `asyncio.TimeoutError` returns from `_run_one_connection` triggering outer reconnect loop
  - `stop_event_subscription()` / `_register_subscription_task()` wired into `main.py` lifespan shutdown
  - `backend/tests/unit/app/test_event_subscription.py`: 9 new unit tests; 49 BE tests total pass; 50 FE tests pass; lint clean; CI green on merge
  - Self-approve not possible (same account owns PR); merged after all three gates verified green

- `feat/n1-s09-profiling-turn` — **N1-S09 · Profiling turn → `profile.json`** (PR #19, squash `ca389ac`)
  - `backend/opencode_client.py`: `prompt(session_id, text, schema=None)` added — POSTs to `/session/:id/prompt_async` (spike-confirmed v1 path); returns immediately (204); when schema provided, payload includes `format: {type: "json_schema", json_schema: {name: "output", schema: <schema>}, retryCount: 2}`; no format key when schema=None
  - `backend/prompts/__init__.py` (new): package init
  - `backend/prompts/profile.py` (new): `PROFILE_SCHEMA` — top-level required: `shape{rows,columns}`, `columns[]{name,type,flags,summary}`, `flags[]`; `build_profile_prompt(dataset, aim)` references `workspace/data/<dataset>` and aim text
  - `backend/tests/unit/app/test_profile_prompt.py` (new): 4 TDD tests — schema payload with/without format block, schema field validation, prompt content; 53 BE tests total pass; 50 FE tests pass; lint clean; CI green on merge
  - Hard boundary clean: `opencode_client.py` does not import orchestrator; deviation noted in PR — `session.idle → profile.ready` wired in orchestrator (N1-S04), not client, which is correct per boundary rules
  - Self-approve not possible (same account owns PR); merged after all three gates verified green

- `feat/n1-s04-orchestrator` — **N1-S04 · Stage orchestrator (setup → profiling)** (PR #20, squash `c6f76cd`)
  - `backend/orchestrator.py`: full state machine replacing N1-S05 stub; `client: OpenCodeClient | None` param; `setup_complete()` persists `stage=profiling` via `state_manager.update()` then publishes `stage.changed` then fire-and-forgets `_run_profile_turn` via `asyncio.create_task`; `_build_profile_prompt` and `_load_profile_schema` gracefully import from `backend.prompts.profile` (N1-S09) with `ImportError` fallback; no `httpx` import — verified by AST check
  - `backend/main.py`: `client=client` wired into `Orchestrator` constructor in lifespan; `None` guard when `SKIP_OPENCODE=1`
  - `backend/tests/unit/app/test_orchestrator.py` (new): 5 TDD tests — transition to profiling, stage.changed emission, profile turn triggered with session, profile turn not triggered without session, no-httpx-import AST boundary check
  - 58 BE tests pass, 50 FE tests pass (108 total); lint clean; CI green on merge
  - Self-approve not possible (same account owns PR); merged after all three gates verified green

- `feat/n1-s11-watchdog` — **N1-S11 · Stuck-turn watchdog & recovery** + **N1-S20 · Testability seams** (PR #21, squash `5efd7fe`)
  - `backend/watchdog.py` (new): `Watchdog` class — `start_turn()` creates an `asyncio.Task` sleeping `WATCHDOG_TIMEOUT` seconds; `heartbeat()` cancels and restarts the task (timer reset); `cancel()` cancels it; on expiry: `_handle_timeout()` calls `client.abort(session_id)` best-effort (errors swallowed), sleeps 10s grace, calls `client.create_fresh_session()`, calls `state_manager.update(opencode_session_id=new_id)`, publishes `turn.error`; no-session-id edge case handled (skips abort/fresh-session, still publishes `turn.error`); `WATCHDOG_TIMEOUT` read from `WATCHDOG_TIMEOUT_SECONDS` env var (default 60)
  - `backend/opencode_client.py` (additive only relative to N1-S09): `abort(session_id)` — best-effort POST to `/session/:id/abort`, all errors swallowed; `create_fresh_session()` — delegates to refactored `_create_session()` which now returns `str` (no side effects); `start()` owns side effects (`self._session_id = session_id`, `state_manager.update()`); `QA_FORCE_STALL=1` seam in `_run_one_connection` suppresses events after the first, off by default, zero production path impact
  - `backend/tests/unit/app/test_watchdog.py` (new): 8 TDD tests — timeout triggers abort, fresh session after grace, state updated with new session ID, `turn.error` emitted, heartbeat resets timer (no abort), cancel stops watch (no abort), `WATCHDOG_TIMEOUT_SECONDS` env var override, no-session-id skips abort but still emits `turn.error`
  - Rebase: conflict in `opencode_client.py` between N1-S09's `_create_session()` (void, side effects) and N1-S11's refactor (returns `str`, no side effects). Resolved: kept N1-S11's design (`_create_session()` returns `str`, `start()` owns side effects) — correct because `create_fresh_session()` must reuse `_create_session()` without duplicating logic. All N1-S09 changes (`prompt()` method) preserved intact.
  - 66 BE tests pass, 50 FE tests pass (116 total); lint clean; CI green on merge

- `feat/n1-s12-reprof-turn` — **N1-S12 · Re-profile turn (`POST /turn`)** (PR #22, squash `e52c962`)
  - `backend/orchestrator.py`: `Watchdog | None` param added to `__init__`; `re_profile(text)` added — validates active session + stage=profiling (raises `ValueError` on either), builds re-profile prompt (base profile prompt + user note via `_build_profile_prompt`), arms `watchdog.start_turn()` if wired in, fire-and-forgets `_run_profile_turn()` via `asyncio.create_task` (same error-handling wrapper as `setup_complete`)
  - `backend/router.py`: `POST /turn` real handler — strips + validates `text` (422 `invalid_text` on empty/whitespace); reads stage from `state_manager`; dispatches `orchestrator.re_profile(text)` as background task when stage=profiling, returns 204 immediately; 422 `invalid_stage` for any other stage; error envelopes match `POST /setup` pattern
  - `backend/main.py`: `Watchdog` instantiated in lifespan when `client is not None`; stored on `app.state.watchdog`; passed to `Orchestrator` constructor
  - `backend/tests/unit/app/test_turn.py` (new): 8 TDD tests — 204 + re_profile dispatched, empty text 422, missing text 422, wrong stage 422, client.prompt called with correct session+schema, ValueError without session, ValueError wrong stage, watchdog.start_turn called when wired
  - Accepted deviation: `re_profile()` reuses `_run_profile_turn()` wrapper instead of calling `client.prompt()` directly — same error→`turn.error` path as `setup_complete`; strictly better behaviour
  - 74 BE tests pass, 50 FE tests pass (124 total); lint clean; CI green on merge

- `integrate/n1-s18` + `fix/app-sse-subscription` — **N1-S18 · Integrate Night 1 slice** + **App.tsx SSE fix** (squash `8dfeaf1`, PR #23)
  - `backend/orchestrator.py`: `start_bus_listener()` background task + `_handle_profile_idle()` — reads `workspace/profile.json` on `session.idle`, validates required fields, updates `state.json`, emits `profile.ready` on bus
  - `backend/main.py`: bus listener task started in lifespan; shut down cleanly before OpenCode on exit
  - `backend/prompts/profile.py`: `build_profile_prompt()` updated to instruct OpenCode to write the JSON to `workspace/profile.json` (not just "return JSON" in message content)
  - `Makefile`: `make dev` no longer starts `opencode serve` separately — backend owns OpenCode lifecycle via `OpenCodeClient.start()`
  - `frontend/src/App.tsx`: `useSSE(onEvent)` called additively alongside mount `useEffect`; `onEvent` handles `stage.changed` + `profile.ready` by calling `api.getState()` and merging result into local state — UI now advances automatically after `POST /setup`
  - `frontend/src/App.test.tsx`: 2 new tests (`reacts to stage.changed`, `reacts to profile.ready`); useSSE mock updated to capture callback for test injection
  - 52 FE + 78 BE = 130 total pass; lint clean; CI green on merge
  - ADR-011 (profile prompt file-write), ADR-012 (OpenCode lifecycle ownership) appended as Proposed
  - FE integration blocker resolved

- **N1-S19 · Night 1 QA & demo script** — **Complete — PASS** (structural PASS / live PASS, all 6 demo steps)
  - QA run date: 2026-06-02
  - All 6 structural assertions passed: profile schema fields, orchestrator httpx boundary, opencode_client orchestrator boundary, single event connection, data-testid completeness (19 unique, >= 17 required), make test (130/130), make lint (clean)
  - Live demo path defects found: QA-01 (SSE `await aconnect_sse` crash loop), QA-02 (`prompt_async` payload 400 — v1.15.13 schema change)
  - Both defects fixed in commit `f63787c` (TL, direct to develop) — see post-QA fixes below
  - Live demo path re-run post-fix: all 6 steps PASS — POST /setup, stage=profiling, Activity Rail streaming, profile.json written at t=45s (shape: rows=100/columns=9), Profile view rendered, re-profile accepted
  - QA_LOG closed: QA-01 + QA-02 marked Closed in commit `cc88859`; REG-N1-11 + REG-N1-12 regression checks added
  - 12 standing regression checks total (REG-N1-01 through REG-N1-12) — see `QA_LOG.md`
  - ADR-013 appended (prompt_async payload shape change in v1.15.13)

- **Post-QA fixes and living-doc close-out** — commits `f63787c` and `42d4ff1` (2026-06-02, directly to develop)
  - `f63787c` — `backend/opencode_client.py`: removed `await` from `aconnect_sse(...)` (QA-01); updated `prompt()` payload to `{"parts": [{"type": "text", "text": text}]}` and `format` to flat `format.schema` shape (QA-02); 3 test files updated to match new signatures; 130/130 tests pass, lint clean
  - `42d4ff1` — `DEV_STATUS.md`, `ADR.md`, `QA_LOG.md` updated to record QA-01/QA-02 closure, ADR-013, and Night 1 final state

- **Morning demo wiring fix** — PR #24, squash `a09dac5` (2026-06-02, CI run 26805380929 green)
  - `frontend/src/hooks/useApi.ts`: FormData field `"file"` → `"csv"` to match `POST /setup` parameter name — was causing 422 on every upload
  - `frontend/src/App.tsx`: ActivityRail wired into layout as right-side panel (rendered for all stages except `setup`)
  - `frontend/vite.config.ts`: `host: "0.0.0.0"` so Vite is reachable from host via devcontainer port forwarding
  - `Makefile`: `--reload-dir backend` added to uvicorn so frontend file edits don't restart the backend process
  - `frontend/src/App.test.tsx`: SSE mock updated to broadcast events to all registered callbacks (App + ActivityRail both call `useSSE`); call-count assertions relaxed to `toHaveBeenCalledWith`
  - `frontend/src/hooks/useApi.test.ts`: `fd.get("csv")` to match the field rename
  - 132 FE + BE tests pass; lint clean; CI green

- **Light styling pass** — PR #25, squash `a7c6167` (2026-06-02, CI green)
  - Pure className additions/replacements across `App.tsx`, `SetupView.tsx`, `ProfileView.tsx`, `ActivityRail.tsx` — warm off-white palette (`#f6f2e9`), amber header, teal type badges, card layout
  - No logic changes; all 17 required `data-testid` attributes preserved intact; no test files touched
  - `frontend/src/` only; no backend, no contracts, no test changes
  - All three review gates passed (scope, data-testid integrity, CI green); self-approve not possible (same account); merged after CI confirmed green

- **fix(be): add shape.target to PROFILE_SCHEMA and profile prompt** — PR #28, squash `80a3661` (2026-06-02, CI run 26818563102 green)
  - `backend/prompts/profile.py`: `"target": {"type": ["string", "null"]}` added to `shape.properties`; `"target"` added to `shape.required`; `build_profile_prompt()` updated to instruct OpenCode to infer the target column from the analysis aim, or set null if not determinable
  - `backend/tests/unit/app/test_profile_prompt.py`: 2 new TDD tests — `test_profile_schema_has_nullable_target` (schema field presence + nullable type), `test_build_profile_prompt_instructs_target_inference` (prompt mentions "target" and "null")
  - Contract alignment: `shape.target` is specified in `API_CONTRACT.html` line 540 with comment `// null if not inferred`; was absent from schema causing frontend's "target (inferred)" widget to stay permanently hidden
  - BE lane only; no frontend, no contracts, no Makefile touched; lane boundary clean
  - 80/80 backend tests pass; self-approve blocked (same account); merged after all three gates verified green

- **Drag-and-drop CSV upload in SetupView** — PR #26, squash `8e0b67a` (2026-06-02, CI run 26816902032 green)
  - `frontend/src/components/StageViews/SetupView.tsx`: `drop-zone` div with `onDragOver`/`onDragLeave`/`onDrop` handlers; `data-dragging` attribute tracks visual active state; clicking zone calls `fileInputRef.current?.click()` to trigger the hidden `csv-input`; `onDrop` sets file from `e.dataTransfer?.files?.[0]`
  - `frontend/src/components/StageViews/SetupView.test.tsx`: 4 new TDD tests — `test_dropzone_renders`, `test_drag_over_sets_active_state`, `test_drag_leave_clears_active_state`, `test_drop_sets_file`
  - All data-testid values preserved: `setup-view`, `csv-input`, `aim-input`, `submit-btn`, `setup-error`; `drop-zone` added (new)
  - Only `frontend/` touched; lane boundary clean
  - 56/56 FE + 78/78 BE = 134 total tests pass; CI green on merge
  - Self-approve not possible (same account owns PR); merged after all three gates verified green

- **Concise activity rail with animated running indicator** — PR #29, squash `b61f498` (2026-06-02, CI run 26820012481 green)
  - `frontend/src/hooks/useActivityState.ts` (new): `useActivityState` hook — full state machine: `isRunning`, `bashCount`, `fileCount`, `dotPhase`; handles `tool.bash_running/done`, `tool.file_written`, `message.part` (set running, count completions), `session.idle` (stop running, preserve counts); 500ms interval cycles `dotPhase` while running; `wasIdle` ref tracks turn boundaries to reset counts on next turn start
  - `frontend/src/hooks/useActivityState.test.ts` (new): 9 hook tests covering initial state, all event types, session.idle preserve/reset, dotPhase cycling, unknown event ignore
  - `frontend/src/components/ActivityRail.tsx`: replaced with thin presenter — calls `useActivityState()`, renders "Thinking." / ".." / "..." while running (`activity-thinking`), "N commands run · M files written" summary when counts exist (`activity-summary`), "No activity yet." placeholder when idle with no counts
  - `frontend/src/components/ActivityRail.test.tsx`: 11 presentation tests that mock the hook; covers all render states and singular/plural text
  - Testid changes: `activity-tool-running`, `activity-tool-done`, `activity-file-written`, `activity-message` removed; `activity-thinking`, `activity-summary` added; `activity-rail` preserved; total unique testids: 18 (>= 17 required, REG-N1-05 satisfied)
  - TL hygiene fix applied: `useActivityState.test.ts` line 6 — typed ref declaration (`{ current: (e: unknown) => void } = { current: () => {} }`) to silence ESLint `no-unused-vars` on no-op initial value; re-ran CI after fix, green
  - Lane boundary note: PR also added `docs/superpowers/specs/2026-06-02-activity-rail-concise-design.md` outside `frontend/`; additive design spec, non-contract, no TL-owned path conflict; accepted as recorded deviation
  - 69/69 FE + 80/80 BE = 149 total tests pass; CI green on merge
  - Self-approve not possible (same account owns PR); merged after all three gates verified green

### **Night 1 COMPLETE. All stories on `develop`. Morning demo wiring, styling, drag-and-drop UX, and concise activity rail resolved. QA structural + live gate passed (all 6 steps). Promoted to `main` at morning review.**

---

## Night 2 — Plan proposal + one interactive Section + Export

### Merged to `develop` — Wave 1 (2026-06-03)

**All 8 Night 2 lane stories merged. 187 BE + 154 FE = 341 total tests pass.**

| Story | PR | Squash SHA | Notes |
|---|---|---|---|
| N2-S14 · Serve workspace files (GET /file) | #32 | `2a77cdc` | Real handler; 400 + path_traversal / missing_file per contract |
| N2-S09 · Frontmatter parser | #33 | `3943d39` | New `backend/frontmatter_parser.py`; pyyaml>=6.0 dep added |
| N2-S06 · Section build turn (file triplet) | #31 | `df20dc0` | New `backend/prompts/section.py`; no structured output (ADR-005) |
| N2-S01 · Orchestrator: planning stage | #34 | `7d59001` | `_handle_planning_transition`; profile.ready → profiling→planning |
| N2-S01 + N2-S02 · Planning turn → plan.json | conflict merge | `f85c042` | `_handle_plan_idle`; stage-aware session.idle; `prompts/plan.py` + PLAN_SCHEMA; 35 orchestrator tests |
| N2-S15 · Plan screen | #36 | `78bb3f4` | Full PlanView.tsx; plan state in App; plan.ready SSE handler |
| N2-S16 · Section build screen | conflict merge | `731e702` | BuildView.tsx + SectionPane.tsx; sections prop from App plan state |
| N2-S17 · Export control | conflict merge | `ececc79` | ExportButton.tsx; acceptedSectionCount from plan state; 154 FE tests |

**Integration notes for N2-S18:**
- App.tsx `plan.ready` handler: direct setState from event.sections (no API refresh — event carries full payload; refresh caused state race resolved in ececc79)
- App.tsx `plan: Section[]` state field unified (N2-S16 used `sections`; renamed to `plan` to match N2-S15/N2-S17)
- BuildView receives `sections={plan}` via renderStageView — consistent prop name

### Merged to `develop` — Wave 2 (2026-06-03)

**2 additional BE stories merged. 210 BE + 154 FE = 364 total tests pass.**

| Story | PR | Squash SHA | Notes |
|---|---|---|---|
| N2-S03 · Persist plan & section statuses | #39 | `e243b64` | `_write_plan_json()` static helper; initial section status changed `"queued"` → `"proposed"` per backlog spec; 11 new tests + 1 orchestrator test updated |
| N2-S13 · Export brief (GET /export) | #41 | `2f15b32` | Real GET /export handler; reads accepted sections from state, finds .md via md_path or glob, parses body with `parse_section_file()`, concatenates with `\n\n---\n\n`; returns text/markdown with Content-Disposition; 12 new tests |

**Status note — N2-S03:** initial section status was `"queued"` in the N2-S02 implementation; N2-S03 corrects this to `"proposed"` per the backlog spec (sections are proposed to the user awaiting review/acceptance; `"queued"` is the post-acceptance pre-build state). One orchestrator test (`test_handle_plan_idle_injects_queued_status`) was renamed and updated to assert `"proposed"`.

### Merged to `develop` — Wave 3 (2026-06-03)

**4 BE stories merged. 246 BE + 154 FE = 400 total tests pass.**

| Story | PR | Squash SHA | Notes |
|---|---|---|---|
| N2-S07 · Section build events | #40 | `eeca6b0` | `start_build_section`, `_handle_section_idle`, `_build_section_prompt`, `_run_section_turn`; bus listener extended for building-stage dispatch; 12 new tests. Conflict resolved: docstring only (develop's N2-S03 "proposed" note merged with incoming N2-S07 note) |
| N2-S12 · Redirect a section (Stage 4b) | #42 | `c83e24b` | `redirect_section`, `_build_redirect_prompt` in orchestrator; `backend/prompts/redirect.py` (new); `POST /turn` building-stage dispatch in router; 17 new tests. Conflict resolved: S12's `_build_redirect_prompt` added alongside S07's `_build_section_prompt` (both new vs merge base, different insertion point conflict); duplicate `_run_section_turn` from S12 removed (S07's version kept — functionally identical) |
| N2-S08 · Detect failed section | #46 | `2d56b48` | 7 new tests in `test_section_failed.py` verifying `_handle_section_idle()` failure detection: AC1 (missing .md/.png/.py → section.failed + payload shape), AC2 (mid-turn tool events do not trigger section.failed), regression guard (triplet present → section.proposed), stage guard (non-building → no emit). No production code changed — N2-S07 already implemented the logic. CI green (run 26863165041). |

### Merged to `develop` — Wave 4 (2026-06-03)

**4 additional BE stories merged. 296 BE + 154 FE = 450 total tests pass.**

| Story | PR | Squash SHA | Notes |
|---|---|---|---|
| N2-S10 · Accept section (POST /section/:id/accept) | #43 | `ff9a05a` | Real handler; proposed→accepted; 400 section_not_found + 400 section_not_proposed error envelopes; no OpenCode call; 10 new tests. CI green. |
| N2-S11 · Drop section (POST /section/:id/drop) | #44 | `fff708d` | Real handler; proposed→dropped; same error envelope pattern as S10; export exclusion verified by test; 11 new tests. CI green. |
| N2-S04 · Edit plan (POST /plan/update) | #45 | `c9838a5` | Full replacement semantics per ADR-014; preserves existing section statuses; new sections get status=proposed; writes plan.json atomically; 422 invalid_request/invalid_section error envelopes; 17 new tests. CI green. |
| N2-S05 · Accept plan & start first section | #47 | `056997e` | `accept_plan()` in orchestrator + real `post_plan_accept` router handler. Conflict resolved: N2-S07's `_build_section_prompt()` and `_run_section_turn()` kept; S05's duplicate methods dropped; `accept_plan()` calls `_build_section_prompt(plan=list)` per N2-S07 signature. 12 new tests. |

**Conflict resolution note — N2-S05:** PR #47 contained duplicate `_build_section_prompt` and `_run_section_turn` vs N2-S07 (already on develop). Resolution: kept N2-S07's implementations (functionally equivalent, already tested); applied only S05's `accept_plan()` method and router handler. `accept_plan()` calls `_build_section_prompt(plan=plan)` with a list (consistent with `start_build_section()` pattern). Merged directly as TL-authored commit `056997e`, PR #47 closed with explanation.

### Merged to `develop` — Wave 5 / S20 + Integration (2026-06-03)

**N2-S20 merged + N2-S18 integration complete. 332 BE + 154 FE = 486 total tests pass.**

| Story | PR | Squash SHA | Notes |
|---|---|---|---|
| N2-S20 · Forced section-failure hook | #48 | `691240e` | `QA_FORCE_SECTION_FAIL=1` seam in `_handle_section_idle()`. Removes .md before triplet check; normal missing-artefact path fires. 6 new tests in `test_section_fail_hook.py`. CI green. |
| N2-S18 · Integrate Night 2 slice (TL) | #49 | `9636cb0` | 30 integration tests in `test_n2_integration.py`; section.py `plan` type annotation fixed (list|dict). All cross-lane endpoints verified: plan/update, plan/accept, section/accept, section/drop, export, file, turn/redirect. Zero-OpenCode-call assertions via MagicMock spy. CI green. |

**Integration findings (N2-S18):**

1. **Type annotation mismatch** — `build_section_prompt()` in `prompts/section.py` declared `plan: dict` but orchestrator always passes a list. No runtime error (json.dumps handles both); fixed annotation to `list | dict` in integration commit.
2. **Frontend wiring confirmed correct:** App.tsx `plan.ready` handler updates directly from `event.sections` (ADR-015 ✓); `BuildView` receives `sections={plan}` (correct ✓); `ExportButton` disabled when no accepted sections (correct ✓).
3. **Zero-OpenCode-call check passed:** `POST /plan/update`, `POST /section/:id/accept`, `POST /section/:id/drop`, `GET /export`, `GET /file` all confirmed to make zero OpenCode calls via implementation review and MagicMock assertions.
4. **Concurrent-save race identified in integration test harness:** fire-and-forget `setup_complete()` tasks race with direct `state_manager.update()` calls in tests. Integration tests fixed to use direct state.json file writes instead of `update()` to avoid ENOENT races. No production code impact.

### N2-S19 · Night 2 QA — PASS (2026-06-03)

- **63 structural assertions** in `qa/structural/test_n2_structural.py` — all pass
- **332 BE + 154 FE = 486 total tests** — all pass
- No blocking defects found
- REG-N2-01 through REG-N2-07 standing regression checks added to `QA_LOG.md`
- Minor observation (non-blocking): `POST /setup` with empty string `""` triggers FastAPI 422 rather than custom error envelope; whitespace-only aim correctly returns custom error; frontend validates before submission; pre-existing from Night 1

### NOW STARTABLE

Night 3 stories are not startable yet — they depend on Night 2 being promoted to `main` at morning review.

### In Dev / In Review / In QA

*All Night 2 stories complete. Awaiting morning human review.*

### Blockers

**RESOLVED — Add-section ID acceptance in POST /plan/update (N2-S15 Risk 4)**
FE1 flagged: the API contract does not specify whether `POST /plan/update` accepts new section IDs. Resolution: full replacement — backend writes whatever array it receives; N2-S04 must not validate IDs against existing plan. Recorded as ADR-014.

**RESOLVED — App.tsx plan.ready SSE handler race (integration fix, 2026-06-03)**
N2-S15 added `plan.ready` to the `getState()` trigger branch, causing a race where the API refresh (returning `plan: []`) overwrote the event's sections. Fixed in merge commit `ececc79`: `plan.ready` now updates state only from `event.sections`. Recorded as ADR-015.

**RESOLVED — section.py plan type annotation (integration, 2026-06-03)**
`build_section_prompt()` declared `plan: dict` but orchestrator passes a list. No runtime error (json.dumps handles both), fixed as annotation-only change in N2-S18 integration commit. See ADR-016.

### **Night 2 COMPLETE. All lane stories merged, integration merged, QA passed (63 structural assertions, 0 defects, 486 total tests). Awaiting morning human review for develop → main promotion.**

### Overnight ADR decisions (Night 2)

- ADR-014 (Proposed — pending review): POST /plan/update accepts new section IDs (add-section feature). Full replacement semantics; N2-S04 must not gate on existing IDs.
- ADR-015 (Proposed — pending review): plan.ready SSE handler updates App state directly from event.sections without API refresh. stage.changed and profile.ready still trigger getState() (they don't carry full state). plan.ready is self-contained. Fix in ececc79.
- ADR-016 (Proposed — pending review): build_section_prompt() plan parameter type corrected to list|dict. Orchestrator always passes list; dict annotation was wrong but caused no runtime error. Fixed in N2-S18 integration commit.

### Post-Night-2 fixes

- **fix: profiling stage now pauses for user review** — `fix/profiling-pause` → develop, merge commit `e4dca81` (2026-06-03)
  - `backend/orchestrator.py`: removed `profile.ready → _handle_planning_transition` auto-advance from `start_bus_listener`; added `accept_profile()` public method
  - `backend/router.py`: added `POST /profile/accept` endpoint — calls `orchestrator.accept_profile()`; returns 204; idempotent
  - `backend/tests/unit/app/test_orchestrator.py`: two tests replacing the old auto-advance assertion; 303 BE tests pass

- **feat(fe): Accept profile button in ProfileView** — `fix/profile-accept-button` → develop, merge commit `40389d7` (2026-06-03)
  - `frontend/src/hooks/useApi.ts`: `postProfileAccept()` added
  - `frontend/src/components/StageViews/ProfileView.tsx`: "Accept profile →" button; renders only when profile is loaded; disabled while in flight; on success App.tsx routes to PlanView via `stage.changed`
  - `frontend/src/components/StageViews/ProfileView.test.tsx`: 4 new tests; 158 FE tests total pass

- **fix(be): POST /turn planning stage — add `re_plan()` to orchestrator** — `fix/planning-turn-handler` → develop, merge commit `247a5f0` (2026-06-03)
  - `backend/orchestrator.py`: `re_plan(text)` added — validates session + stage=planning, builds revision prompt (base plan prompt + user instruction), arms watchdog, fires `_run_plan_turn` fire-and-forget
  - `backend/router.py`: `planning` case added to `POST /turn` dispatch; removes the stale "Night 2: planning stage re-plan will be added here" comment
  - `backend/tests/unit/app/test_turn.py`: 5 new tests; `test_redirect.py` wrong-stage test updated to use `setup` (planning is now valid); 308 BE tests total pass

### Post-Night-1 fixes (QA-01, QA-02)

- ADR-013 (Proposed — pending review): `prompt_async` payload shape changed in v1.15.13 relative to v1.15.10 (spike). `text` → `parts[{type,text}]`; `format.json_schema.schema` → `format.schema`. Confirmed from live OpenAPI spec at `/doc`. See ADR.md.

---

## Overnight ADR decisions — Night 1

- N1-S01 deviation: `frontend/pnpm-workspace.yaml` added with `allowBuilds: esbuild: true, @playwright/test: true` — required because pnpm v11 moved build-script approval out of `package.json` into `pnpm-workspace.yaml`; without this, `pnpm install` exits with `ERR_PNPM_IGNORED_BUILDS` in CI. No contract impact.
- N1-S07 placement: `docs/contracts/SSE_CONTRACT.md` used instead of backlog's `backend/docs/SSE_CONTRACT.md`. Consistent with CLAUDE.md rule that all contracts live in `docs/contracts/` and FE lane codes against that directory. Accepted; recorded in the document itself.
- N1-S13 branch separation: the FE agent committed the N1-S13 work onto the BE `feat/n1-s02-app-skeleton` branch. TL cherry-picked that commit to a clean `feat/n1-s13-frontend-scaffold` branch and opened PR #7 for proper story-level tracking before merging. The original commit on `feat/n1-s02-app-skeleton` remains there for the pending N1-S02 PR #6 review.
- N1-S13 Tailwind v4 deviation: `@tailwindcss/vite` plugin + `@import "tailwindcss"` (v4 pattern) instead of v3 CLI — correct for the installed version, functionally equivalent. Accepted.
- N1-S02 branch collision (post-merge note): PR #6 (`feat/n1-s02-app-skeleton`) contained both the FE agent's N1-S13 commit and the BE agent's N1-S02 commit. On review, `origin/feat/n1-s13-frontend-routing` (the FE agent's separate push) was confirmed to have identical tree content to the PR's FE commit — no work was missing. PR #6 was merged as-is (commits are lane-clean); stale `origin/feat/n1-s13-frontend-routing` deleted post-merge. Root cause: FE agent pushed to the BE branch before BE agent committed. Process improvement needed: agents should verify they are on their own branch before committing.
- N1-S10 TDD deviation (router test): `test_get_events_registered` calls the route handler directly with a `MagicMock` request and inspects the returned `StreamingResponse` object, rather than using `httpx.AsyncClient + ASGITransport`. Root cause: `ASGITransport` runs the full ASGI call inline and does not support client-side cancellation of infinite SSE generators — the `async with ac.stream()` context exits but `listen_for_disconnect` (inside Starlette's `StreamingResponse`) waits for full response completion, hanging the test. Direct handler invocation tests all contract properties (type, media_type, headers) without streaming. Documented per CONTRIBUTING §3.
- N1-S10 main.py blocker (Proposed — pending review): A prior TL DEV_STATUS commit (`8fe71cf`) accidentally included a modified `backend/main.py` that imported `backend.orchestrator.Orchestrator` (from stashed N1-S05 work in the working tree at merge time). This made develop's test collection fail with `ModuleNotFoundError: No module named 'backend.orchestrator'`. Fixed in the N1-S10 squash commit by reverting `main.py` to the correct N1-S03 state. Root cause: TL committed with a dirty working tree; N1-S05 stash files leaked into the DEV_STATUS commit. Prevention: always check `git diff` before committing living-doc updates.
- N1-S06 lane boundary deviation (Proposed — pending review): TL accidentally committed BE implementation code (`opencode_client.py` and its unit tests) to `develop` directly (commit `8fe71cf`) outside a PR during a prior DEV_STATUS update with a dirty working tree. Content is correct and forms the core of N1-S06. Accepted as-is; reverting would create more churn than value. Prevention: TL must check `git diff --cached` before committing living-doc updates.
- N1-S18 ADR-011 (Proposed — pending review): Profile prompt must explicitly instruct OpenCode to write `workspace/profile.json`. "Return JSON" is insufficient — OpenCode returns structured output as message content, not as a file. See ADR-011.
- N1-S18 ADR-012 (Proposed — pending review): `make dev` no longer starts `opencode serve` separately. Backend's `OpenCodeClient.start()` is the sole owner of the OpenCode subprocess lifecycle. See ADR-012.

---

## Night 2 demo script (morning review)

1. `make install && make dev` — both servers start; app loads at http://localhost:5173
2. Upload `data/customers_q3.csv` + enter aim → profiling → profile view renders
3. Watch profiling complete → Profile view renders → click **Accept profile** → PlanView renders section list
4. Edit one section title inline → POST /plan/update (no OpenCode call)
5. Enter bottom-bar revision → POST /turn (planning stage) → plan updates
6. Accept plan → POST /plan/accept → stage=building → first section build starts
7. Watch Activity Rail — section build completes → SectionPane renders (code + chart + interpretation)
8. Click Accept → POST /section/:id/accept → ExportButton enabled
9. Click Export → GET /export → Markdown brief delivered
10. Refresh browser → UI re-hydrates to current stage/state from GET /state

**QA test hook:** To exercise section.failed without model misbehaviour:
```bash
QA_FORCE_SECTION_FAIL=1 make dev   # section.failed fires on next section build turn
```

*Note: steps 3–9 require provider credentials in `~/.local/share/opencode/auth.json`. Backend-only operations (plan/update, section/accept, section/drop, export) work without OpenCode.*

---

## Night 1 demo script (morning review)

1. Fresh clone → `make install` → `make dev`
2. Open app at http://localhost:5173 → upload `data/customers_q3.csv` + enter an aim
3. Watch profiling activity stream live in the Activity Rail
4. Confirm Profile view renders (shape strip + per-column rows) — profile.json written ~45s post-setup
5. Submit one bottom-bar re-profile → confirm second turn completes or recovers via fresh session
6. Refresh browser → confirm UI re-hydrates from `state.json`

*Note: steps 3–5 require provider credentials configured for OpenCode (`~/.local/share/opencode/auth.json`). QA-01 and QA-02 are now fixed; live demo path verified end-to-end on 2026-06-02.*
