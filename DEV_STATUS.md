# DEV_STATUS.md

*Single writer: TL. All other agents read only. Updated at the end of each overnight run.*

---

## Current Status

**Branch:** `develop`

**Night 3 is in progress.** Night 2 is complete and merged. All BE stories are now merged to `develop`. The `turn.error` contract violation (retryable bool → reason enum) has been corrected on develop (SHA `ae99ecd`). The FE lane (N3-S05/S06/S07/S08) is in development and is the remaining blocker before integration (N3-S13).

**What is on `develop` from Night 3:**
- `ae99ecd` — turn.error payload contract fix: `retryable` bool replaced with `reason` enum string (`"provider_error"` / `"timeout"`) across orchestrator + watchdog
- N3-S01, N3-S04 (section loop → done, watchdog heartbeat fix) — merged via PR #60 (SHA `492b422`)
- N3-S02, N3-S03, N3-S16 (retry, turn.error mapping, QA_FORCE_TURN_ERROR) — merged via PR #58
- N3-S09, N3-S10, N3-S11, N3-S12 (make run, make clean, README, architecture doc) — merged via PR #57

**Active implementation branches:**
- `feat/n3-fe-error-done` (PR #54, draft) — FE: N3-S05/S06/S07/S08 (retry banner, failed-section, watchdog surface, done screen)

**Startable now:**
- N3-S05 Retry banner (FE) — was blocked on N3-S02, now merged. Covered under PR #54.
- N3-S06 Failed-section controls (FE) — in dev under PR #54.
- N3-S07 Watchdog-timeout surface (FE) — depends on N3-S06, covered under PR #54.
- N3-S08 Done screen (FE) — was blocked on N3-S01, now merged. Covered under PR #54.

PR #55 (plan-only draft for N3-S02/S03/S16) has been closed as redundant. See ADR-017.
PR #53 (original BE-1 branch) closed; content committed directly to develop (`d3c7754`) and also via PR #60 rebase (`492b422`).
PR #59 (TL packaging re-PR) closed as redundant — all content already on develop via PR #57.

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
- Night 3 still needs `QA_FORCE_TURN_ERROR` (N3-S16) to drive recoverable `turn.error` deterministically.

---

## Night 3 Handoff

Night 3 is startable only after morning promotion of Night 2 to `main`.

**Night 3 goal:** via `make run` from a clean checkout, build a full multi-section brief on the churn CSV, repeat the core path on a second dataset, induce a failure and recover it through the UI, and export the final brief.

### Story Status

| Story | Role | Status | Notes |
|---|---|---|---|
| N3-S01 Sequential section loop & done | BE | Merged | PR #60 squashed to develop (`492b422`) |
| N3-S02 Retry a turn | BE | Merged | PR #58 squashed to develop |
| N3-S03 Map turn errors | BE | Merged | PR #58 squashed to develop |
| N3-S04 Harden watchdog for long runs | BE | Merged | PR #60 squashed to develop (bundled with N3-S01) |
| N3-S05 Retry banner | FE | In Dev — plan approved | PR #54 draft; unblocked (N3-S02 merged) |
| N3-S06 Failed-section controls | FE | In Dev — plan approved | PR #54 draft; plan approved |
| N3-S07 Watchdog-timeout surface | FE | In Dev — plan approved | PR #54 draft; plan approved |
| N3-S08 Done screen | FE | In Dev — plan approved | PR #54 draft; unblocked (N3-S01 merged) |
| N3-S09 `make run` | TL | Merged | PR #57 squashed to develop |
| N3-S10 `make clean` & gitignore | TL | Merged | PR #57 squashed to develop |
| N3-S11 README | TL | Merged | PR #57 squashed to develop |
| N3-S12 Architecture write-up | TL | Merged | PR #57 squashed to develop — `docs/ARCHITECTURE.md` |
| N3-S16 Forced turn-error hook | BE | Merged | PR #58 squashed to develop |
| N3-S13 Integration | TL | Backlog | Blocked on N3-S05–S08 (all BE stories now merged) |
| N3-S14 Full regression | QA | Backlog | Depends on N3-S13 |
| N3-S15 Submission demo script | QA | Backlog | Depends on N3-S14 |

### Night 3 Merge Ledger (in-progress)

| Story | PR | SHA | What mattered |
|---|---:|---|---|
| N3-S09/S10/S11/S12 Packaging | #57 | `428c669` | `make run`, `make clean`, README, `docs/ARCHITECTURE.md` |
| N3-S02/S03/S16 Retry + turn.error + forced hook | #58 | `b5501db` | `retry_last_turn()`, `turn.error { stage, reason }`, `QA_FORCE_TURN_ERROR` |
| N3-S01/S04 Section loop → done + watchdog heartbeat | #60 | `492b422` | `_check_done_or_next()`, `stage.changed(done)`, `_current_timeout` watchdog fix |
| turn.error contract fix (TL inline) | — | `ae99ecd` | `retryable` bool → `reason` enum; `"provider_error"` / `"timeout"` |

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

### Night 3 QA Expectations

- Multi-section churn run reaches `done`.
- Second dataset run reaches `done` and exports.
- Forced recoverable turn error shows retry banner and recovers.
- Forced section failure shows Retry/Drop; Drop advances the loop.
- Forced stall recovers through watchdog without corrupting `state.json` or sequence.
- Cold `make run` uses the built bundle, not Vite.
- `make clean` resets runtime artefacts.
- `/export` returns valid multi-section Markdown in plan order.

### Demo Script Baseline

1. `make clean`, then `make run`.
2. Upload `data/customers_q3.csv`, enter aim, and complete profiling.
3. Accept profile; revise/edit the plan; accept plan.
4. Build multiple sections; accept at least one; redirect/revise one section if demo time allows.
5. Exercise one failure path with QA hook and recover through Retry or Drop.
6. Reach `done`, export the brief as Markdown, and open it.
7. Repeat the core path on a second dataset to prove generality.

---

## Blockers

**Resolved (this run):** PR #58 (N3-S02/S03/S16) shipped `turn.error` with `retryable: bool` instead of `reason: string`. Contract violation. Fixed inline on develop (`ae99ecd`) before QA gate. See Overnight ADR Decisions below.

No other blockers. FE lane (PR #54) is the last pending work before N3-S13 integration.

## Overnight ADR Decisions (Night 3)

- **ADR-017 (Proposed):** BE-2 proceeded to implementation of N3-S02/S03/S16 without waiting for TL plan approval. Implementation was correct and merged via PR #58. Plan-only PR #55 closed. Human to decide at morning review whether agent prompts need reinforcement.
- **ADR-018 (Proposed):** `QA_FORCE_TURN_ERROR` seam placed in `orchestrator._run_*_turn` methods (not in `opencode_client.prompt()`). Better placement — keeps QA concerns in the orchestrator layer, consistent with `QA_FORCE_STALL` / `QA_FORCE_SECTION_FAIL` pattern.
- **ADR-020 (Proposed):** `turn.error` payload contract correction applied inline to develop by TL. PR #58 merged with `retryable: bool`; the correct contract field is `reason: string` (enum: `"structured_output_failed"` / `"provider_error"` / `"timeout"`). Corrected in `ae99ecd` before QA ran. TL may make this class of contract-correctness fix directly on develop (not a feature change, zero behaviour change observable to the user, all tests green). Human to confirm at morning review.
