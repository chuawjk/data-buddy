# DEV_STATUS.md

*Single writer: TL. All other agents read only. Updated at the end of each overnight run.*

---

## Current Status

**Branch:** `develop`

**Night 2 is complete.** All lane stories, integration, and QA are merged. QA passed with 63 structural assertions, 0 blocking defects, and 486 total tests at the Night 2 gate. The branch is awaiting morning human review for `develop` -> `main` promotion before Night 3 starts.

**Post-Night-2 UX fixes are recorded and should be treated as current handoff context:**

- Building-stage revision is section-targeted: `POST /turn` accepts optional `section_id`; `orchestrator.redirect_section(text, section_id)` rebuilds only that section, clears stale artefact paths, and emits `section.building`.
- The building-stage global bottom bar was removed; each proposed section owns its own revision input/button.
- Profiling and planning now show loading spinners while initial/revision turns are in flight.
- `Accept profile` and `Accept plan & start building` sit below their revision controls and use the teal primary action style.
- Header `Export` is hidden until `building` / `done`.
- Frontend SSE types include `session.idle`; Vite config uses Vitest's typed `defineConfig`.
- Latest recorded verification:
  - Targeted section revision branch: `make test` passed (327 backend + 175 frontend tests); `make lint` passed.
  - Stage controls branch: `pnpm --prefix frontend run lint`, `pnpm --prefix frontend run test` (180 tests), and `pnpm --prefix frontend run build` passed.

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

### Startable Story Map

| Story | Role | Depends on | Notes for agents |
|---|---|---|---|
| N3-S01 Sequential section loop & done | BE | N2-S05, N2-S10 | Partially de-risked by post-N2 auto-sequencing; still verify last accept -> `done`, `stage.changed(done)`, dropped-section skip, rapid-accept safety |
| N3-S02 Retry a turn | BE | N1-S11 | Retry should resend exact failed prompt against current/fresh session; retries bounded |
| N3-S03 Map turn errors | BE | N1-S09, N2-S02 | Emit recoverable `turn.error` for structured/provider errors; distinguish from `section.failed` |
| N3-S04 Harden watchdog for long runs | BE | N1-S11, N3-S01 | Verify multi-section timer reset and fresh-session persistence |
| N3-S05 Retry banner | FE | N1-S14, N3-S02 | Inline banner on `turn.error`; Retry action; clear on success |
| N3-S06 Failed-section controls | FE | N1-S14, N2-S08 | Section-level Retry/Drop on `section.failed`; Drop continues loop |
| N3-S07 Watchdog-timeout surface | FE | N3-S06 | No silent hangs; surface watchdog-driven failure/recovery options |
| N3-S08 Done screen | FE | N1-S14, N3-S01 | Render accepted sections and prominent export action on `done` |
| N3-S09 `make run` | TL | N1-S01 | Build Vite bundle and serve from FastAPI on one port |
| N3-S10 `make clean` & gitignore | TL | N1-S01 | Reset runtime workspace/build artefacts; verify clean -> run |
| N3-S11 README | TL | N3-S09 | Document install/dev/run/clean and prerequisites |
| N3-S12 Architecture write-up | TL | none | `docs/ARCHITECTURE.md` or README section; cite ADRs |
| N3-S16 Forced turn-error hook | BE | N3-S03 | Opt-in `QA_FORCE_TURN_ERROR`; off by default |
| N3-S13 Integration | TL | N3-S01-S12, N3-S16 | Full submission build handoff to QA |
| N3-S14 Full regression | QA | N3-S13, N3-S16 | Multi-section churn + second dataset + forced failure/stall + cold `make run` |
| N3-S15 Submission demo script | QA | N3-S14 | Rehearsed interview path |

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
6. Reach `done`, export zip, and open the brief.
7. Repeat the core path on a second dataset to prove generality.

---

## Blockers

None recorded. Night 3 should not begin until Night 2 is promoted to `main` at morning review.
