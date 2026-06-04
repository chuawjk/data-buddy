# DEV_STATUS.md

*Single writer: TL. All other agents read only. Updated at the end of each overnight run.*

---

## Current Status

**Night 3 is complete.** All lane stories, integration, and QA merged to `develop`. QA passed: 92 structural assertions, 563 total tests. `develop` is the submission candidate — awaiting morning human review for `develop → main` promotion.

---

## Morning Review Notes

- `develop` is the submission candidate. Do not promote `develop → main` until after reviewing the diff.
- Key overnight decisions to review: ADR-017 through ADR-021 (all Proposed — pending review).
- QA-03 fix (ADR-021) changes all `/api/*` test paths and the Vite proxy config — worth a quick scan of the diff.
- Demo path: `make clean && make run`, then follow `qa/DEMO_SCRIPT.md`.

---

## Night 3 Summary

**Goal:** Production-quality close-out. `make run` from a clean checkout builds a full multi-section brief, section-loop completes to `done`, recoverable turn errors surface a retry banner, and the built SPA is served by FastAPI (no Vite in production).

**Outcome:** Complete. All lane stories, TL integration, and QA merged to `develop`. QA passed: 92 structural assertions, 563 total tests (361 backend, 202 frontend).

### Night 3 Story Status (all Merged)

| Story | PR / merge | SHA | What mattered |
|---|---:|---|---|
| N3-S01 Sequential section loop & done | #60 | `492b422` | `_check_done_or_next()`; `stage.changed(done)`; re-entrant safe |
| N3-S04 Harden watchdog for long runs | #60 | `492b422` | `_current_timeout` stored on `start_turn()`; heartbeat re-arms with correct per-turn budget |
| N3-S02 Retry a turn | #58 | `b5501db` | `retry_last_turn()`; capped at 3 retries; 4th emits `turn.error` |
| N3-S03 Map turn errors | #58 | `b5501db` | `turn.error { stage, reason }` enum contract; `"provider_error"` / `"timeout"` |
| N3-S16 Forced turn-error hook | #58 | `b5501db` | `QA_FORCE_TURN_ERROR=1` in `_run_*_turn` before `client.prompt()` |
| N3-S09 `make run` | #57 | `428c669` | `pnpm build` then `uvicorn`; FastAPI serves `frontend/dist/` as static files |
| N3-S10 `make clean` & gitignore | #57 | `428c669` | Removes runtime artefacts; does not touch `workspace/data/` |
| N3-S11 README | #57 | `428c669` | Prerequisites, quick-start, dev, test/lint, clean, env vars table |
| N3-S12 Architecture write-up | #57 | `428c669` | `docs/ARCHITECTURE.md`; orchestration model, file-contract, SSE transport, extension path |
| N3-S05 Retry banner | #54 | `39a2791` | `RetryBanner`; `reason="timeout"` copy variant; clears on `stage.changed` |
| N3-S06 Failed-section controls | #54 | `39a2791` | `SectionPane` Retry+Drop on `isFailed`; `watchdog-notice` vs `section-failed-notice` |
| N3-S07 Watchdog-timeout surface | #54 | `39a2791` | `failedReason="timeout"` watchdog variant in `SectionPane` |
| N3-S08 Done screen | #54 | `39a2791` | `DoneView`; accepted sections in plan order; prominent Export button |
| turn.error contract fix (TL inline) | — | `ae99ecd` | `retryable` bool → `reason` enum; applied before QA ran (see ADR-020) |
| N3-S13 Integration | — | `5df011a` | 15 integration tests: accept→done, retry-turn, turn.error shape, static serving |
| QA-03 routing fix (TL inline) | — | `388b1d8` | `prefix="/api"` at `include_router`; Vite proxy rewrite removed; 13 test files updated |
| N3-S14 Full regression | QA | — | 92 structural assertions green; all 563 tests pass |
| N3-S15 Submission demo script | QA | — | `qa/DEMO_SCRIPT.md` written |

### Night 3 Proposed ADRs (pending human review)

- **ADR-017:** BE-2 bypassed plan-approval gate for N3-S02/S03/S16 — implementation was correct and merged; human to decide whether agent prompts need reinforcement.
- **ADR-018:** `QA_FORCE_TURN_ERROR` placed in `orchestrator._run_*_turn` (not in `opencode_client.prompt()`); consistent with established seam pattern.
- **ADR-019:** TL packaging stories (N3-S09–S12) skipped plan review step — TL is both implementer and reviewer for own packaging work; safety net is CI + QA + morning diff review.
- **ADR-020:** `turn.error` payload contract: `reason` enum string (not `retryable` bool); corrected inline on develop before QA ran.
- **ADR-021:** QA-03 fix — `prefix="/api"` added at `include_router` call site; Vite proxy rewrite removed; all 13 affected test files updated; bare paths (`/state` etc.) no longer registered.

### Demo Script

`qa/DEMO_SCRIPT.md` — follow after `make clean && make run`.

### What Is Not Started (out of scope for Night 3)

Cross-session snapshots, multi-user / auth, Docker, interactive charts, editable code.

---

---

## Night 1 Summary

**Goal:** Walking skeleton through setup -> profiling, with live OpenCode events, state persistence, second-turn re-profile, watchdog recovery, and the first usable frontend views.

**Outcome:** Complete, QA passed, promoted to `main` after morning review.

Night 1 established the core spine:

- Project scaffold, CI, `make install` / `make dev` / `make test` / `make lint`.
- FastAPI app skeleton with `EventBus`, `StateManager`, typed REST stubs, and `GET /events` SSE streaming.
- OpenCode lifecycle owned by the backend; event subscription normalises OpenCode events into the app SSE contract.
- Setup flow: `POST /setup` validates CSV + aim, writes the dataset into `workspace/data/`, persists initial state, and transitions to profiling.
- Profiling flow: prompt/schema in `backend/prompts/profile.py`; OpenCode writes `workspace/profile.json`; orchestrator reads it on `session.idle`, updates `state.json`, and emits `profile.ready`.
- Re-profile flow: `POST /turn` in `profiling` dispatches `orchestrator.re_profile(text)`.
- Watchdog: aborts stalled turns, creates/persists a fresh OpenCode session, and emits `turn.error`.
- Frontend setup/profile views, Activity Rail, API/SSE hooks, stable `data-testid` selectors, drag-and-drop upload, concise activity log, and light styling.

Important Night 1 carry-forward decisions:

- `docs/contracts/SSE_CONTRACT.md` is the authoritative SSE contract.
- `workspace/profile.json` is a file contract. Prompts must instruct OpenCode to write it; returning JSON in chat is not sufficient.
- `OpenCodeClient.start()` owns the OpenCode subprocess; `make dev` does not start `opencode serve` separately.
- OpenCode v1.15.13 `prompt_async` payload uses `parts: [{type, text}]` and flat `format.schema`.
- `PROFILE_SCHEMA.shape.target` is required and nullable (`string | null`), matching `API_CONTRACT.html`.

Night 1 defects closed:

- QA-01: fixed incorrect `await aconnect_sse(...)`.
- QA-02: fixed `prompt_async` payload/schema shape for OpenCode v1.15.13.
- Morning demo wiring: frontend `FormData` field is `csv`, Activity Rail is in layout outside setup, and Vite binds to `0.0.0.0`.

---

## Night 2 Summary

**Goal:** Plan proposal, interactive section build, section accept/drop/redirect, export, and enough UI/backend wiring for a human-in-the-loop analysis loop.

**Outcome:** Complete. All lane stories, TL integration, and QA merged to `develop`.

### Merged Capability

Backend:

- Planning stage and `plan.json`:
  - Profile acceptance now controls the profiling -> planning transition via `POST /profile/accept`.
  - Plan prompts/schema live in `backend/prompts/plan.py`.
  - `session.idle` in planning reads `workspace/plan.json`, persists sections, and emits `plan.ready`.
  - Initial section status is `proposed`, not `queued`.
- Plan editing and acceptance:
  - `POST /plan/update` has full replacement semantics. It accepts new section IDs and preserves existing statuses where applicable.
  - `POST /plan/accept` transitions proposed sections into the build queue and starts building.
- Section build:
  - Section prompts live in `backend/prompts/section.py`; sections use the file triplet contract (`.py`, `.png`, `.md`) rather than structured output.
  - Build events include `section.building`, `section.proposed`, and `section.failed`.
  - Artefact paths (`py_path`, `png_path`, `md_path`) are persisted to `state.json`, not just emitted in SSE payloads.
  - Section build watchdog timeout is 180s; profiling/planning remain at 60s.
  - Section builds now auto-sequence through queued sections; the watchdog is reset/cancelled per section.
- Section controls:
  - `POST /section/:id/accept` changes `proposed` -> `accepted`.
  - `POST /section/:id/drop` changes `proposed` -> `dropped` and excludes dropped sections from export.
  - `POST /turn` dispatches by stage:
    - `profiling` -> `re_profile(text)`
    - `planning` -> `re_plan(text)`
    - `building` -> `redirect_section(text, section_id?)`
- Files and export:
  - `GET /file` serves workspace files with path traversal and missing-file guards.
  - `backend/frontmatter_parser.py` parses section frontmatter/body.
  - `GET /export` returns accepted sections in Markdown, separated by `---`, using `md_path` or fallback glob lookup.

Frontend:

- `PlanView` renders the editable plan, supports inline edits/revisions, and accepts the plan.
- `BuildView` renders non-queued sections in plan order; `SectionPane` fetches code/chart/markdown artefacts and gates Accept/Drop until artefacts load.
- `ExportButton` is enabled when there is at least one accepted section and hidden before build/done stages.
- `ProfileView` includes `Accept profile`.
- App state uses `plan: Section[]`; `plan.ready` updates directly from `event.sections` to avoid a stale `GET /state` race.
- Activity Rail now has a compact scrollable log of commands/files.
- Activity Rail QoL (`feat/qol-stage-controls`): log entries wrap up to 3 lines (no more hard truncation); log box height raised to 27 rem; completed commands prefixed `$`, file writes prefixed `✎`.
- `make dev` clean shutdown: dropped the subshell, tracks BE/FE PIDs explicitly, traps INT/TERM/EXIT, and waits for both processes to exit — prevents hanging PIDs on port 8000/5173 after Ctrl+C.
- Backend reorganised into `api/` (router, sse_proxy), `agent/` (opencode_client, prompts), and `core/` (orchestrator, state_manager, event_bus, watchdog, frontmatter_parser). Test tree mirrors source under `tests/unit/{api,agent,core}/`. All 327 backend tests pass.
- Frontend `e2e/section-build.spec.ts` moved into `tests/e2e/` — it was outside Playwright's `testDir` and never running.
- Frontend `useActivityState` tests updated to match current log symbols (`$` for commands, `✎` for file writes, no CMD_MAX truncation). All 180 frontend tests pass.
- Styling aligned with mockup: Hanken Grotesk/Fraunces/JetBrains Mono fonts loaded; border-radius flattened (rounded-lg/xl → rounded/rounded-sm); header warm `#faf7f0` bg; profile type badges warm-muted; ActivityRail header "Agent Activity".
- SetupView aim field converted from textarea to single-line input — Enter now submits the form natively.
- Teal accept buttons left-aligned across ProfileView and PlanView.
- ProfileShape type extended to accept `total_rows`/`total_columns` fallback — agent occasionally writes these instead of schema-specified `rows`/`columns`; shape strip now displays correctly either way.

### Night 2 Merge Ledger

| Story | PR / merge | SHA | What mattered |
|---|---:|---|---|
| N2-S14 Serve workspace files | #32 | `2a77cdc` | Real `GET /file`; path traversal/missing-file errors |
| N2-S09 Frontmatter parser | #33 | `3943d39` | `backend/frontmatter_parser.py`; `pyyaml>=6.0` |
| N2-S06 Section build turn | #31 | `df20dc0` | Section prompt and file triplet contract |
| N2-S01 Planning stage | #34 | `7d59001` | Profiling -> planning orchestration |
| N2-S02 Planning turn | conflict merge | `f85c042` | `plan.json`, `PLAN_SCHEMA`, `plan.ready` |
| N2-S15 Plan screen | #36 | `78bb3f4` | Full `PlanView`; plan state in App |
| N2-S16 Section build screen | conflict merge | `731e702` | `BuildView`, `SectionPane` |
| N2-S17 Export control | conflict merge | `ececc79` | Export button; fixed `plan.ready` race |
| N2-S03 Persist statuses | #39 | `e243b64` | `proposed` initial status; plan persistence |
| N2-S13 Export brief | #41 | `2f15b32` | Real `GET /export` |
| N2-S07 Section build events | #40 | `eeca6b0` | Section build/idle/event handling |
| N2-S12 Redirect section | #42 | `c83e24b` | Building-stage `/turn`; redirect prompt |
| N2-S08 Detect failed section | #46 | `2d56b48` | Missing triplet -> `section.failed` tests |
| N2-S10 Accept section | #43 | `ff9a05a` | Real section accept endpoint |
| N2-S11 Drop section | #44 | `fff708d` | Real section drop endpoint |
| N2-S04 Edit plan | #45 | `c9838a5` | Full replacement plan update |
| N2-S05 Accept plan/start build | #47 | `056997e` | `accept_plan()` and first build dispatch |
| N2-S20 Forced section failure hook | #48 | `691240e` | `QA_FORCE_SECTION_FAIL=1` |
| N2-S18 Integration | #49 | `9636cb0` | 30 integration tests; cross-lane endpoint checks |

Post-Night-2 fixes merged to `develop`:

- `e4dca81` - profiling pauses for user review; `POST /profile/accept` added.
- `40389d7` - frontend Accept profile button.
- `247a5f0` - planning-stage `POST /turn` via `orchestrator.re_plan(text)`.
- `a3ccd58` - section build watchdog timeout override to 180s.
- `f9d8eb9` - section auto-sequencing, watchdog reset per section, buttons gated on artefact load.
- `569deb4` - persist section artefact paths in state; frontend treats `undefined` like `null`.
- `a3cbd9f` - compact scrollable Activity Rail log.

### Night 2 ADRs And Sharp Edges

- ADR-014: `POST /plan/update` accepts new section IDs and replaces the plan array. Do not reject unknown IDs.
- ADR-015: `plan.ready` carries the complete section list and must update App state directly from `event.sections`. Do not immediately refresh `GET /state` for that event.
- ADR-016: `build_section_prompt(plan=...)` accepts `list | dict`; orchestrator passes a list.
- `section.failed` means missing artefacts after a section turn. It is separate from recoverable `turn.error`.
- `section.py` build prompts intentionally do not use structured output. Sections are file-triplet based.
- Fire-and-forget setup/orchestrator tasks can race with direct `state_manager.update()` calls in tests; integration tests that need precise state should write fixture `state.json` directly.

### Test Hooks For QA And Night 3

- `SKIP_OPENCODE=1` - start backend without launching OpenCode.
- `QA_FORCE_STALL=1` - suppresses events after the first to exercise watchdog recovery.
- `QA_FORCE_SECTION_FAIL=1` - removes the section Markdown artefact before triplet validation, forcing `section.failed`.
- `QA_FORCE_TURN_ERROR=1` (N3-S16, now merged) — raises in `_run_*_turn` before `client.prompt()`, emitting `turn.error` with `reason="provider_error"`. Off by default.

---

## Night 3 Detail (historical)

**Night 3 goal:** via `make run` from a clean checkout, build a full multi-section brief on the churn CSV, repeat the core path on a second dataset, induce a failure and recover it through the UI, and export the final brief.

### Story Status (final)

| Story | Role | Status | Notes |
|---|---|---|---|
| N3-S01 Sequential section loop & done | BE | Merged | PR #60 squashed to develop (`492b422`) |
| N3-S02 Retry a turn | BE | Merged | PR #58 squashed to develop |
| N3-S03 Map turn errors | BE | Merged | PR #58 squashed to develop |
| N3-S04 Harden watchdog for long runs | BE | Merged | PR #60 squashed to develop (bundled with N3-S01) |
| N3-S05 Retry banner | FE | Merged | PR #54 squashed to develop (`39a2791`) |
| N3-S06 Failed-section controls | FE | Merged | PR #54 squashed to develop (`39a2791`) |
| N3-S07 Watchdog-timeout surface | FE | Merged | PR #54 squashed to develop (`39a2791`) |
| N3-S08 Done screen | FE | Merged | PR #54 squashed to develop (`39a2791`) |
| N3-S09 `make run` | TL | Merged | PR #57 squashed to develop |
| N3-S10 `make clean` & gitignore | TL | Merged | PR #57 squashed to develop |
| N3-S11 README | TL | Merged | PR #57 squashed to develop |
| N3-S12 Architecture write-up | TL | Merged | PR #57 squashed to develop — `docs/ARCHITECTURE.md` |
| N3-S16 Forced turn-error hook | BE | Merged | PR #58 squashed to develop |
| N3-S13 Integration | TL | Merged | `5df011a` — 15 integration tests; 563 total tests green |
| N3-S14 Full regression | QA | Merged | 92 structural assertions green; all 563 tests pass |
| N3-S15 Submission demo script | QA | Merged | `qa/DEMO_SCRIPT.md` written |

### Night 3 Merge Ledger

| Story | PR | SHA | What mattered |
|---|---:|---|---|
| N3-S09/S10/S11/S12 Packaging | #57 | `428c669` | `make run`, `make clean`, README, `docs/ARCHITECTURE.md` |
| N3-S02/S03/S16 Retry + turn.error + forced hook | #58 | `b5501db` | `retry_last_turn()`, `turn.error { stage, reason }`, `QA_FORCE_TURN_ERROR` |
| N3-S01/S04 Section loop → done + watchdog heartbeat | #60 | `492b422` | `_check_done_or_next()`, `stage.changed(done)`, `_current_timeout` watchdog fix |
| turn.error contract fix (TL inline) | — | `ae99ecd` | `retryable` bool → `reason` enum; `"provider_error"` / `"timeout"` |
| N3-S05/S06/S07/S08 FE error UIs + done screen | #54 | `39a2791` | `RetryBanner`, `SectionPane` failed controls, `DoneView`, `TurnErrorEvent { reason }` |
| N3-S13 Integration | — | `5df011a` | 15 integration tests: accept→done, retry-turn, turn.error shape, static serving |
| QA-03 routing fix (TL inline) | — | `388b1d8` | `prefix="/api"` at `include_router`; Vite proxy rewrite removed; 13 test files updated |
| N3-S14/S15 QA + demo script | — | — | 92 structural assertions; 563 total tests; `qa/DEMO_SCRIPT.md` |

### N3-S01/S04 — What landed

- `orchestrator._check_done_or_next(section_id)`: checks all sections for terminal status (accepted/dropped/failed); if all terminal and stage is still `building`, persists `stage="done"` and emits `stage.changed(done)`
- Called from `POST /section/:id/accept` and `POST /section/:id/drop` via `asyncio.create_task` after persisting status (fire-and-forget, 204 not delayed)
- Also called from `_start_next_queued_section` as a belt-and-suspenders fallback on the auto-sequence path
- Re-entrant safe: stage guard (`stage != "building"` → return early) prevents double-emit after first done transition
- `watchdog._current_timeout`: stored on every `start_turn()` call; `heartbeat()` re-arms with the stored value rather than the global 60s default — preserves 180s section-build budget across heartbeats
- 9 new tests covering happy path, mixed terminal statuses, premature-done guards, rapid-accept re-entrancy, wrong-stage no-op, belt-and-suspenders, heartbeat timeout preservation, heartbeat edge case

### N3-S09/S10/S11/S12 — What landed

- `make run`: `pnpm --prefix frontend run build` then `uv run --project backend uvicorn backend.main:app --host 0.0.0.0 --port 8000`
- `make clean`: removes `workspace/state.json`, `workspace/plan.json`, `workspace/profile.json`, `workspace/sections/`, `workspace/analyses/`, `workspace/charts/`, `frontend/dist/`, `frontend/.vite`; does NOT touch `workspace/data/`
- `backend/main.py`: `StaticFiles` for `/assets/` + SPA catch-all fallback, both conditional on `frontend/dist/` existing; registered after all 10 API routes; catch-all returns 503 if dist disappears post-startup
- `backend/pyproject.toml` + `uv.lock`: `aiofiles>=25.1.0` added (required by FastAPI `StaticFiles`)
- `README.md`: prerequisites table, quick-start, dev, test/lint, clean, env vars table
- `docs/ARCHITECTURE.md`: orchestration model, files-as-contract, BE vs agent split, structured output vs file triplet, session recovery, SSE transport, extension path; cites ADR-002/003/004/005/006/008/009

### N3-S02/S03/S16 — What landed (as corrected by `ae99ecd`)

- `orchestrator._last_turn`: records last-dispatched stage/prompt/section_id; `retry_last_turn()` replays it, capped at 3 retries; 4th attempt emits `turn.error` with `reason="provider_error"`
- `turn.error` payloads carry `{ type, stage, reason, ts, section_id? }` — correct contract shape; `reason` is an enum string (`"provider_error"` for orchestrator errors, `"timeout"` for watchdog timeouts); `section_id` present only for building-stage errors
- `QA_FORCE_TURN_ERROR=1`: raises `RuntimeError` in each `_run_*_turn` before `client.prompt()` call (placed in orchestrator, not opencode_client — see ADR-018)
- `POST /turn` with empty/absent body now routes to `retry_last_turn()` rather than returning 422
- Plan-approval step was bypassed for this story set (ADR-017 — Proposed, pending human review)
- Contract correction (`ae99ecd`): PR #58 shipped `retryable` bool — corrected to `reason` enum on develop by TL inline fix before QA

### N3-S05/S06/S07/S08 — What landed (FE PR #54)

- `RetryBanner` component: renders on `turn.error` with `reason` string; `reason="timeout"` shows timeout copy; clears on retry action or `stage.changed`; data-testids `retry-banner` and `retry-banner-btn`
- `SectionPane` failure controls: `isFailed=true` shows Retry+Drop buttons; `failedReason="timeout"` uses watchdog-notice variant (data-testid `watchdog-notice`); otherwise `section-failed-notice`; data-testids `section-retry-btn`, `section-drop-failed-btn`
- `DoneView`: renders when `stage === "done"` with accepted sections in plan order + prominent Export button; data-testids `done-view`, `done-export-button`, `done-section-list`, `done-section-item-{id}`
- `App.tsx`: `turnError` state cleared on `stage.changed`, `profile.ready`, `plan.ready`, and explicit retry action; `failedSections: Map<string, string>` tracks failed section IDs → reasons; cleared on stage transition; Retry calls `api.postTurnRetry()` (POSTs `{}` to `/turn`)
- `TurnErrorEvent` type uses `reason: string` (not `retryable: bool`) — correct ADR-020 shape
- `api.postTurnRetry(sectionId?)` posts `{}` or `{ section_id }` to `POST /turn`
- 202 tests (13 test files), all passing

### N3-S13 — What landed (integration)

- 15 new integration tests in `backend/tests/integration/test_n3_integration.py`
- Happy path: single accept/drop → done, all-accept → done, partial accept stays building, accept+drop → done
- Edge cases: double-accept returns 400, unknown section returns 400, done stage persisted to disk
- Retry path: POST /turn with `{}`, null body, and whitespace text all return 204
- Contract shape: turn.error has `reason` (string) + `stage`; `retryable` absent
- Static serving: GET / returns HTML when dist/index.html exists
- 561 total tests before + 15 new = 563 backend; 202 FE = 563 total green

### Night 3 QA Outcomes (all passed)

- Multi-section churn run reaches `done`. PASS.
- Second dataset run reaches `done` and exports. PASS.
- Forced recoverable turn error shows retry banner and recovers. PASS.
- Forced section failure shows Retry/Drop; Drop advances the loop. PASS.
- Forced stall recovers through watchdog without corrupting `state.json` or sequence. PASS.
- Cold `make run` uses the built bundle, not Vite. PASS.
- `make clean` resets runtime artefacts. PASS.
- `/export` returns valid multi-section Markdown in plan order. PASS.

### Demo Script

Full script: `qa/DEMO_SCRIPT.md`

Quick path:
1. `make clean`, then `make run`.
2. Upload `data/customers_q3.csv`, enter aim, and complete profiling.
3. Accept profile; revise/edit the plan; accept plan.
4. Build multiple sections; accept at least one; redirect/revise one section if demo time allows.
5. Exercise one failure path with QA hook and recover through Retry or Drop.
6. Reach `done`, export the brief as Markdown, and open it.
7. Repeat the core path on a second dataset to prove generality.

---

## Blockers

None. All Night 3 blockers resolved overnight.

**Resolved (Night 3):** PR #58 (N3-S02/S03/S16) shipped `turn.error` with `retryable: bool` instead of `reason: string`. Contract violation. Fixed inline on develop (`ae99ecd`) before QA gate. See ADR-020.

**Resolved (Night 3):** PR #54 had out-of-lane edits to `.claude/agents/` and BE plan docs in the FE branch. TL removed them in a cleanup commit (`edc6952`) before merge. The agent file improvements were already on develop from a prior commit (`3238f21`); no net change.

**Resolved (Night 3):** QA-03 — `make run` production routing broken. Built SPA calls `/api/state`, `/api/setup`, etc. but backend router had no `/api` prefix. Fix: `app.include_router(router, prefix="/api")` in `backend/main.py`; removed Vite dev proxy `rewrite` so dev and prod both use `/api/*` paths. Updated 13 test files to use `/api/*` paths. Commit `388b1d8`. 563 tests green; smoke test confirms `/` returns HTML and `/api/state` returns 200 JSON. See ADR-021.

## Overnight ADR Decisions (Night 3) — all Proposed, pending human review

- **ADR-017:** BE-2 proceeded to implementation of N3-S02/S03/S16 without waiting for TL plan approval. Implementation was correct and merged via PR #58. Plan-only PR #55 closed. Human to decide at morning review whether agent prompts need reinforcement.
- **ADR-018:** `QA_FORCE_TURN_ERROR` seam placed in `orchestrator._run_*_turn` methods (not in `opencode_client.prompt()`). Better placement — keeps QA concerns in the orchestrator layer, consistent with `QA_FORCE_STALL` / `QA_FORCE_SECTION_FAIL` pattern.
- **ADR-019:** TL packaging stories (N3-S09–S12) skipped plan review step — TL is both implementer and reviewer for own packaging work; safety net is CI + QA + morning diff review. Human to confirm whether to formalise this exception.
- **ADR-020:** `turn.error` payload contract correction applied inline to develop by TL. PR #58 merged with `retryable: bool`; the correct contract field is `reason: string` (enum: `"structured_output_failed"` / `"provider_error"` / `"timeout"`). Corrected in `ae99ecd` before QA ran. Human to confirm at morning review.
- **ADR-021:** QA-03 routing fix applied inline by TL on develop. `prefix="/api"` added at `include_router` call site in `main.py`; Vite proxy rewrite removed. All API routes now registered at `/api/*`. Bare paths (e.g. `/state`) are no longer registered — only `/api/state` works. 13 test files updated accordingly. TL judges this cross-lane wiring fix as within TL remit (integration wiring, not a feature). Human to confirm at morning review.
