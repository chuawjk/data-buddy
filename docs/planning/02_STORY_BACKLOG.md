# Story Backlog — Data Buddy

*Handover artefact 2 of 4. Companions: `01_SLICE_PLAN.md` (why the three nights), `03_OPERATING_MODEL.md` (cadence, branching, merge), `04_QA_PLAN.md` (how the structural DoD is verified).*

---

## How to read this backlog

Work is organised by **night (sprint)**. Each night opens with a header (sprint goal, blocking prerequisites, contracts in play); **stories sit directly under it** — no epic layer.

Stories are written for autonomous agents, so three fields are load-bearing — an agent cannot ask a clarifying question mid-sprint:

- **Source refs** — the exact doc + section to follow. Truth lives there, not in the prose.
- **Acceptance** — structural, checkable Given-When-Then criteria. This is the QA agent's merge gate; it asserts shape, not analysis quality. Analysis quality is the human morning-review call.
- **Out of scope** — explicit non-goals; the only reliable brake on gold-plating a 20–30h prototype.

### Roles

- **TL — Tech Lead.** Architecture, cross-lane integration, and overall technical coordination. Concretely: the repo scaffold and build tooling (`Makefile`), the nightly integration of merged lane work into a running slice, the README and architecture write-up, enforcing the internal boundaries below, and the review + merge gate. **TL does not write feature code in `backend/` or `frontend/`.**
- **BE — Backend Engineer.** All of `backend/`: the orchestrator state machine, state persistence, every REST endpoint, the OpenCode client (session lifecycle, persistent event subscription, prompts, structured-output schemas, watchdog/recovery), SSE normalisation and the SPA-facing `GET /events` transport, and the reconciled SSE-event contract.
- **FE — Frontend Engineer.** All of `frontend/`: scaffold, hooks, every stage view, the activity rail, the section pane, the error UIs, and the export control.
- **QA.** Per-night demo scripts, structural DoD verification, regression.

### Boundaries the integration owner enforces

- **Lane ownership:** BE owns `backend/`, FE owns `frontend/`, TL owns repo wiring + build tooling + docs and adjudicates any contract change. The interfaces between lanes are the contracts (`API_CONTRACT.html`, the schemas, the reconciled SSE contract) — agents code against those, not against each other's internals.
- **Internal backend rule (architecture, implemented by BE):** the orchestrator calls the OpenCode client through a narrow interface (roughly `client.prompt(session_id, text, schema=None)` plus a normalised event iterator). The state machine never imports `httpx`; the client never imports the orchestrator. Domain events (`stage.changed`, `profile.ready`, `plan.ready`, `section.*`) and activity events (`tool.*`, `message.part`) both flow through the internal bus to `GET /events`.

### Conventions

- IDs: `N{night}-S{nn}`. Dependencies reference IDs directly, across nights where needed.
- Status flow (tracked on the board, not stamped per story): Backlog → In Dev → In Review → In QA → Merged (or Blocked).
- Sizes: **S** (< ~2h agent run) · **M** (~half a night) · **L** (most of a night).
- Where spike and spec disagree on OpenCode runtime behaviour, **the spike wins** (`opencode-spike/SPIKE_REPORT.md`).
- Each night, the lane stories land first, then TL's **integration** story greens the slice end-to-end, then QA verifies.

### Contract surface (shared reference)

**REST (SPA ↔ backend):** `POST /setup` · `GET /state` · `GET /events` (SSE) · `POST /turn` · `POST /plan/update` · `POST /plan/accept` · `POST /section/:id/accept` · `POST /section/:id/drop` · `GET /export` · `GET /file`
**SSE (backend → SPA):** `stage.changed` · `profile.ready` · `plan.ready` · `section.building` · `section.proposed` · `section.failed` · `session.idle` · `turn.error` · `tool.bash_running` · `tool.bash_done` · `tool.file_written` · `message.part` · `file.ready`
**Schemas:** `profile.json` (`shape{rows,columns}`, `columns[{name,type,flags,summary}]`, `flags`) · `plan.json` (`sections[{id,title,hypothesis}]`)

### Global out of scope (every story — never build these)

Cross-cutting refinement (Stage 5) · snapshots (Stage 6) · multi-session / new-session affordance · multi-user / auth · interactive charts (matplotlib PNG only) · editable code in the UI · export formats beyond Markdown · Docker / containerisation.

---

## Night 1 — Walking skeleton through Profiling (+ second-turn recovery)

**Sprint goal (morning review):** from a clean checkout, `make dev`, upload the churn CSV with an aim, watch profiling stream live, see the profile render; submit one bottom-bar re-profile (the second turn) and confirm it completes — or recovers via a fresh session without hanging; refresh the browser and confirm re-hydration.

**Blocking prerequisite:** N1-S07 (reconciled SSE-event contract) merges before any SSE handler — BE or FE — is written.

**Contracts in play:** `API_CONTRACT.html` · `state.json` / `profile.json` schemas · the reconciled SSE contract · ADR-002 / 004 / 006 / 007.

---

### N1-S01 · Project scaffold & dev loop

**Role:** TL  ·  **Size:** S  ·  **Depends on:** —

**Intent:** Stand up the repo layout and the two dev-loop targets so all lanes have a place to land code.

**Acceptance:**
- Given a fresh clone, when `make install` runs, then backend (uv) and frontend (npm) dependencies install with no manual steps.
- Given a clean repo, when `make dev` runs, then FastAPI and the Vite dev server start on their two ports.
- Given the repo, when inspected, then it matches the expected `backend/` + `frontend/` + gitignored `workspace/` layout.

**Source refs:** `C4_ARCHITECTURE.html` (component & SPA containers) · ADR-009
**Out of scope:** `make run` / `make clean` (Night 3)
**Touches:** `Makefile`, repo root

---

### N1-S02 · FastAPI app skeleton & event bus

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N1-S01

**Intent:** An importable app with all routes registered (stubbed where not yet built) and an in-process pub/sub bus that domain and activity events publish to.

**Acceptance:**
- Given `make dev`, when the app boots, then all 10 REST routes are registered and return a typed stub or real handler.
- Given the running app, when a trivial `GET /state` is called, then it responds, confirming the app is healthy.
- Given the bus, when a component publishes an event, then every active subscriber receives it.

**Source refs:** `C4_ARCHITECTURE.html` (FastAPI container) · `API_CONTRACT.html` (route list)
**Out of scope:** real handler logic owned by later stories
**Touches:** `backend/main.py`

---

### N1-S03 · State store & `GET /state`

**Role:** BE  ·  **Size:** M  ·  **Depends on:** N1-S02

**Intent:** A crash-safe single source of truth so a refresh re-hydrates correctly (ADR-007).

**Acceptance:**
- Given any state mutation, when it is persisted, then it writes `state.tmp.json` then `os.replace()` onto `state.json`.
- Given a process kill simulated mid-write, when the file is read, then `state.json` is valid (current or prior version), never partial.
- Given a turn is in progress, when a write is attempted, then it is deferred until the session is idle.
- Given a page load, when `GET /state` is called, then it returns the persisted stage, plan, section statuses, and profile per the contract schema.

**Source refs:** ADR-007 · `C4_ARCHITECTURE.html` (`state.json` schema) · `API_CONTRACT.html` `GET /state` · `WORKFLOW_ORCHESTRATION.md` §auto-save
**Out of scope:** the periodic 30s auto-save timer (follow-up) · any SSE
**Touches:** `backend/state_manager.py`

---

### N1-S04 · Stage orchestrator (setup → profiling)

**Role:** BE  ·  **Size:** M  ·  **Depends on:** N1-S03, N1-S08

**Intent:** The state machine for the first two stages, emitting domain events on every transition.

**Acceptance:**
- Given the machine, when it runs, then states `setup` and `profiling` exist with a single legal transition between them.
- Given a state is entered, when the transition completes, then `stage.changed` is published and the transition is persisted via the state store.
- Given setup completes, when the orchestrator advances, then it auto-triggers the profiling turn via the narrow `client.prompt(...)` interface (not `httpx` directly).

**Source refs:** `C4_ARCHITECTURE.html` (orchestrator state machine) · `WORKFLOW_ORCHESTRATION.md` §Stage 1–2 · ADR-003
**Out of scope:** planning / building states (Night 2)
**Touches:** `backend/orchestrator.py`

---

### N1-S05 · Setup endpoint

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N1-S03

**Intent:** Receive the upload + aim, create the workspace tree, persist initial state, and hand off to the orchestrator.

**Acceptance:**
- Given a valid CSV + aim, when `POST /setup` is called, then `workspace/data/<dataset>.csv` and an initial `state.json` at stage `setup` are created.
- Given a non-CSV or oversize upload, when `POST /setup` is called, then the contract error envelope is returned.
- Given a successful setup, when it completes, then the orchestrator's setup→profiling path is triggered.

**Source refs:** `API_CONTRACT.html` `POST /setup` · ADR-005 (workspace layout)
**Out of scope:** starting `opencode serve` + session create (N1-S06)
**Touches:** `backend/main.py`, `backend/orchestrator.py`

---

### N1-S06 · OpenCode process & session

**Role:** BE  ·  **Size:** M  ·  **Depends on:** N1-S03

**Intent:** Launch and supervise the OpenCode process and create the single session whose ID lives in `state.json`.

**Acceptance:**
- Given the backend starts, when it launches `opencode serve` (full binary path, not PATH-assumed), then it detects readiness before proceeding.
- Given OpenCode is ready, when a session is created, then it uses the **v1 `/session`** API and persists the session ID to `state.json`.
- Given the OpenAI provider, when configured, then it authenticates via OAuth with `providerID: "openai"`.
- Given shutdown, when it occurs, then the process is torn down cleanly.

**Source refs:** ADR-001 / 002 · `opencode-spike/SPIKE_REPORT.md` (binary path, OAuth, v1 vs v2) · `opencode-spike/SPIKE_PLAN.md`
**Out of scope:** the persistent event subscription (N1-S08) · watchdog (N1-S11)
**Touches:** `backend/opencode_client.py`
**Notes:** pin OpenCode v1.15.10.

---

### N1-S07 · Reconciled event contract  ⛔ BLOCKING — first BE deliverable

**Role:** BE  ·  **Size:** S  ·  **Depends on:** —

**Intent:** Resolve the spec-vs-spike divergence and publish the corrected mapping from OpenCode raw events to the backend→SPA taxonomy, so BE handlers and FE hooks build against one truth.

**Acceptance:**
- Given the spec and the spike, when reconciled, then a committed doc maps each backend→SPA event to its OpenCode source.
- Given the known divergences, when documented, then it records: file writes keyed off `file.edited` (not a tool name); text via `message.part.delta` (not `part.delta`); tool parts pending→running→completed; extra events (`server.heartbeat`, `session.status`, `session.diff`, `step-start/finish`, `reasoning`); v1 not v2 `/session`.
- Given the dependent SSE stories, when they begin, then this doc is already merged.

**Source refs:** `WORKFLOW_ORCHESTRATION.md` §SSE events · `API_CONTRACT.html` (SSE payloads) · `opencode-spike/SPIKE_REPORT.md` §4–6 · `opencode-spike/SPIKE_EVENTS.txt`
**Out of scope:** implementation (downstream stories)
**Touches:** `backend/docs/SSE_CONTRACT.md`

---

### N1-S08 · Live events from OpenCode

**Role:** BE  ·  **Size:** M  ·  **Depends on:** N1-S06, N1-S07

**Intent:** One long-lived subscription to OpenCode's event stream, opened at startup, filtered to the current session, normalised onto the bus.

**Acceptance:**
- Given the backend has started, when idle, then exactly one `GET /event` connection to OpenCode is open.
- Given two sequential turns on one session, when the second starts, then no new subscription is opened.
- Given an event whose `sessionID` differs from the current session, when it arrives, then it is dropped.
- Given more than 30s with no `server.heartbeat`, when the gap is detected, then the backend reconnects.

**Source refs:** ADR-006 · reconciled contract (N1-S07) · `opencode-spike/SPIKE_EVENTS.txt`
**Out of scope:** SPA transport (N1-S10) · watchdog (N1-S11)
**Touches:** `backend/opencode_client.py`
**Notes:** text streams via `message.part.delta`, not `part.delta`.

---

### N1-S09 · Profiling turn → `profile.json`

**Role:** BE  ·  **Size:** M  ·  **Depends on:** N1-S08

**Intent:** The profiling turn — prompt OpenCode to profile the dataset and return JSON validated against the profile schema.

**Acceptance:**
- Given the profile prompt, when sent, then it uses native `format: { type: "json_schema", schema, retryCount: 2 }`.
- Given a real churn-CSV turn, when it completes, then `profile.json` has `shape{rows,columns}` and per-column `{name,type,flags,summary}`.
- Given valid output on `session.idle`, when detected, then BE signals so the orchestrator emits `profile.ready`.
- Given structured-output failure after retries, when it occurs, then `turn.error` is emitted (UI deferred to Night 3).

**Source refs:** `WORKFLOW_ORCHESTRATION.md` §Stage 2 (template + schema) · ADR-004
**Out of scope:** plan / section prompts
**Touches:** `backend/prompts/profile.py`, `backend/opencode_client.py`

---

### N1-S10 · Browser event stream (`GET /events`)

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N1-S02, N1-S07

**Intent:** Drain the internal bus to the browser as a clean SSE stream.

**Acceptance:**
- Given a connecting SPA, when it subscribes to `GET /events`, then it receives all bus events as SSE with contract-shaped payloads.
- Given an active turn, when events flow, then both domain and activity events reach the SPA.
- Given an idle period, when it elapses, then the connection survives via heartbeat/keepalive.
- Given a client disconnect, when it happens, then the subscription is cleaned up.

**Source refs:** `API_CONTRACT.html` `GET /events` + payloads · reconciled contract (N1-S07) · ADR-006
**Out of scope:** producing the events (other stories)
**Touches:** `backend/main.py`, transport module

---

### N1-S11 · Stuck-turn watchdog & recovery

**Role:** BE  ·  **Size:** M  ·  **Depends on:** N1-S06, N1-S08

**Intent:** Keep a stuck turn from hanging the demo; recover by replacing the session (ADR-002).

**Acceptance:**
- Given an active turn, when 60s pass with no events, then the turn is aborted.
- Given an abort, when 10s grace elapses, then a fresh session is created and its ID swapped into `state.json`.
- Given a timeout, when recovery runs, then `section.failed` / `turn.error` is emitted as appropriate.
- Given the second turn or a forced stall, when it runs, then recovery is observed end-to-end.

**Source refs:** ADR-002 · `opencode-spike/SPIKE_REPORT.md` (stuck-turn bug: 2nd prompt hangs 7min+, abort returns 200 but doesn't unblock, fresh session fixes)
**Out of scope:** the retry-banner UI (Night 3)
**Touches:** `backend/watchdog.py`, `backend/opencode_client.py`

---

### N1-S12 · Re-profile turn (`POST /turn`)

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N1-S04, N1-S09, N1-S11

**Intent:** Route the profile-stage bottom-bar text into a second agent turn, exercising recovery.

**Acceptance:**
- Given the profiling stage, when `POST /turn` is called with bottom-bar text, then a re-profile prompt is dispatched and 204 returns immediately.
- Given the dispatched turn, when it runs, then progress arrives via SSE.
- Given a second consecutive turn on the same session, when it runs, then it completes or recovers without hanging.
- Given completion, when output lands, then `profile.json` is overwritten.

**Source refs:** `API_CONTRACT.html` `POST /turn` · `WORKFLOW_ORCHESTRATION.md` §Stage 2 bottom bar
**Out of scope:** planning / section redirect paths (Night 2)
**Touches:** `backend/main.py`, `backend/opencode_client.py`

---

### N1-S13 · Frontend scaffold & stage routing

**Role:** FE  ·  **Size:** S  ·  **Depends on:** N1-S01

**Intent:** A Vite/TS/Tailwind app that renders the correct stage view for the current stage from `GET /state`.

**Acceptance:**
- Given `make dev`, when the SPA loads, then it calls `GET /state` and renders the matching stage.
- Given the SPA, when inspected, then it holds no business logic — all state is hydrated from the backend.

**Source refs:** ADR-007 · `DATA_BUDDY_MOCKUPS_STRIPPED.html` · `C4_ARCHITECTURE.html` (SPA container)
**Out of scope:** per-view internals (own stories)
**Touches:** `frontend/src/App.tsx`, `vite.config.ts`, `tsconfig.json`

---

### N1-S14 · API & event hooks

**Role:** FE  ·  **Size:** M  ·  **Depends on:** N1-S07, N1-S13

**Intent:** The two data primitives — typed REST calls and a live subscription to `GET /events`.

**Acceptance:**
- Given the REST endpoints, when `useApi` wraps them, then each has typed request/response per contract.
- Given `GET /events`, when `useSSE` subscribes, then it parses contract-shaped events and reconnects on drop.
- Given the event types, when handled, then they match the reconciled contract exactly.

**Source refs:** `API_CONTRACT.html` · reconciled contract (N1-S07)
**Out of scope:** rendering (view stories)
**Touches:** `frontend/src/hooks/useApi.ts`, `useSSE.ts`

---

### N1-S15 · Setup screen

**Role:** FE  ·  **Size:** S  ·  **Depends on:** N1-S14

**Intent:** The entry screen — collect CSV + aim, post to `/setup`.

**Acceptance:**
- Given the screen, when rendered, then it matches the mockup layout.
- Given no CSV or empty aim, when the user tries to submit, then submit is disabled.
- Given a valid CSV + aim, when submitted, then it posts to `/setup` and advances on `stage.changed`.
- Given a setup error, when returned, then it is surfaced from the error envelope.

**Source refs:** `DATA_BUDDY_MOCKUPS_STRIPPED.html` (Setup) · `API_CONTRACT.html` `POST /setup`
**Out of scope:** profiling display
**Touches:** `frontend/src/components/StageViews/SetupView.tsx`

---

### N1-S16 · Profile screen & re-profile bar

**Role:** FE  ·  **Size:** M  ·  **Depends on:** N1-S14, N1-S17

**Intent:** Render `profile.json` and provide the bottom-bar input that triggers the second turn.

**Acceptance:**
- Given `profile.json`, when rendered, then the shape strip (`rows`, `columns`) and per-column rows (`name`, `type`, `flags`, `summary`) display.
- Given a browser refresh, when the page reloads, then the profile re-hydrates correctly.
- Given bottom-bar text, when submitted, then it posts to `/turn` and shows live progress.
- Given a new `profile.ready`, when received, then the view updates.

**Source refs:** `DATA_BUDDY_MOCKUPS_STRIPPED.html` (Profiling) · `profile.json` schema · `API_CONTRACT.html` `POST /turn`
**Out of scope:** plan / section UI
**Touches:** `frontend/src/components/StageViews/ProfileView.tsx`

---

### N1-S17 · Activity rail

**Role:** FE  ·  **Size:** M  ·  **Depends on:** N1-S14

**Intent:** The live feed of what the agent is doing during a turn.

**Acceptance:**
- Given `tool.bash_running` / `tool.bash_done` / `tool.file_written`, when received, then each renders as an activity item.
- Given `message.part` deltas, when received, then they append in order.
- Given a new turn, when it starts, then the rail resets.
- Given out-of-order events, when they arrive, then the rail stays consistent.

**Source refs:** `DATA_BUDDY_MOCKUPS_STRIPPED.html` (activity rail) · reconciled contract (`tool.*`, `message.part`)
**Out of scope:** section rendering
**Touches:** `frontend/src/components/ActivityRail.tsx`

---

### N1-S18 · Integrate Night 1 slice

**Role:** TL  ·  **Size:** M  ·  **Depends on:** N1-S01–N1-S17, N1-S20, N1-S21

**Intent:** Assemble the merged lane work into a running Night-1 build, resolve any wiring or contract mismatch between backend and frontend, and hand a green end-to-end slice to QA.

**Acceptance:**
- Given all Night-1 lane stories are merged, when `make dev` runs, then the setup→profiling path runs end-to-end against real OpenCode.
- Given a mismatch between a backend event and an FE hook, when integration runs, then it is resolved or raised as a blocker rather than left for QA.
- Given the integrated slice, when handed to QA, then it starts cleanly from a fresh clone.

**Source refs:** `01_SLICE_PLAN.md` (Slice 1 DoD) · `03_OPERATING_MODEL.md` (nightly integration)
**Out of scope:** independent verification (QA owns)
**Touches:** cross-cutting wiring, `Makefile`

---

### N1-S19 · Night 1 QA & demo script

**Role:** QA  ·  **Size:** M  ·  **Depends on:** N1-S18, N1-S20, N1-S21

**Intent:** Codify the morning-review path as a repeatable check, including recovery.

**Acceptance:**
- Given the integrated slice, when the script runs, then setup → profile render → one re-profile (second turn) completes/recovers → refresh re-hydrates.
- Given the run, when assertions execute, then `profile.json` is valid against schema, stage transitions are correct, exactly one OpenCode `/event` connection exists, and the second turn does not hang.
- Given a pass/fail result, when produced, then it is unambiguous and gates merge.

**Source refs:** `01_SLICE_PLAN.md` (Slice 1 DoD) · `04_QA_PLAN.md`
**Out of scope:** plan / section coverage (Night 2)
**Touches:** `qa/`

---

### N1-S20 · Watchdog testability seams

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N1-S11

**Intent:** Make the watchdog's recovery path fast and deterministic to test — a configurable no-events timeout and an opt-in forced-stall hook — without changing production behaviour. The timeout override doubles as the production tunable for the timeout value (see ADR-002).

**Acceptance:**
- Given a timeout override (e.g. env var), when set, then the watchdog uses it; unset, it uses the production default.
- Given `QA_FORCE_STALL`, when a turn runs under it, then the client emits no further events, driving the abort → fresh-session path deterministically.
- Given neither flag, when a turn runs, then behaviour is identical to N1-S11 (no production impact).

**Source refs:** ADR-002 · `04_QA_PLAN.md` §2 · `WORKFLOW_ORCHESTRATION.md` §error handling
**Out of scope:** the failure UI; choosing the production default value (an ADR-002 decision)
**Touches:** `backend/watchdog.py`, `backend/opencode_client.py`
**Notes:** opt-in test seam, off by default.

---

### N1-S21 · Stable test selectors (`data-testid`)

**Role:** FE  ·  **Size:** S  ·  **Depends on:** N1-S15, N1-S16, N1-S17

**Intent:** Add `data-testid` attributes to the elements QA's browser tests target, so Playwright specs aren't brittle. Establishes the convention for all stage views; later FE views (Nights 2–3) adopt the same pattern as they are built.

**Acceptance:**
- Given the Night-1 views, when rendered, then the stage containers, the profile column rows, the activity-rail items, the setup controls, and the bottom-bar input carry stable `data-testid` attributes.
- Given an element's styling or copy changes, when it re-renders, then its `data-testid` is unchanged (selectors decoupled from presentation).
- Given a later FE view is built, when it ships, then it applies the same testid pattern (the convention rides with each FE view story).

**Source refs:** `04_QA_PLAN.md` §2 (FE testability) · `DATA_BUDDY_MOCKUPS_STRIPPED.html`
**Out of scope:** the Playwright specs themselves (QA owns, `N1-S19`); visual styling
**Touches:** `frontend/src/components/**`
**Notes:** the FE counterpart to the BE test seams; these ship in the real UI and are inert.

---

## Night 2 — Plan proposal + one interactive Section + Export

**Sprint goal (morning review):** accept a proposed plan (after at least one inline edit and one bottom-bar revision), watch a single section build through its full triplet, redirect it once mid-build and watch it rebuild, accept it, then export the brief-so-far to a single Markdown file.

**Contracts in play:** `plan.json` schema · the file-triplet contract (`analyses/`, `charts/`, `sections/`) · ADR-003 / 004 / 005 · `API_CONTRACT.html` plan + section + export endpoints.

---

### N2-S01 · Orchestrator: planning stage

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N1-S04

**Intent:** Extend the state machine into planning and kick the plan turn automatically.

**Acceptance:**
- Given `profile.ready` is accepted, when the orchestrator advances, then it transitions profiling→planning.
- Given the planning state is entered, when it starts, then the plan prompt is auto-triggered via the narrow interface and `stage.changed` is emitted.

**Source refs:** `C4_ARCHITECTURE.html` (state machine) · `WORKFLOW_ORCHESTRATION.md` §Stage 3
**Out of scope:** building state (N2-S05 onward)
**Touches:** `backend/orchestrator.py`

---

### N2-S02 · Planning turn → `plan.json`

**Role:** BE  ·  **Size:** M  ·  **Depends on:** N1-S09

**Intent:** The planning turn — propose 3–6 sections as validated JSON.

**Acceptance:**
- Given the plan prompt, when sent, then it uses native `json_schema` output with `retryCount: 2`.
- Given a successful turn, when it completes, then `plan.json` has `sections[{id,title,hypothesis}]`, 3–6 entries.
- Given valid output, when detected, then BE signals so the orchestrator emits `plan.ready`.
- Given structured-output failure, when it occurs, then `turn.error` is emitted.

**Source refs:** `WORKFLOW_ORCHESTRATION.md` §Stage 3 (template + schema) · ADR-004
**Out of scope:** persistence (N2-S03) · section build
**Touches:** `backend/prompts/plan.py`

---

### N2-S03 · Persist plan & section statuses

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N1-S03, N2-S02

**Intent:** Write the proposed plan and initialise per-section status in `state.json`.

**Acceptance:**
- Given `plan.ready`, when handled, then `plan.json` is written and each section is recorded with status `proposed`.
- Given the persisted plan, when `GET /state` is called, then it reflects the plan and statuses.
- Given the write, when performed, then atomic-write semantics are preserved.

**Source refs:** `C4_ARCHITECTURE.html` (`state.json` schema) · `API_CONTRACT.html` `GET /state`
**Out of scope:** edits / accept (own stories)
**Touches:** `backend/state_manager.py`, `backend/orchestrator.py`

---

### N2-S04 · Edit plan (`POST /plan/update`)

**Role:** BE  ·  **Size:** M  ·  **Depends on:** N2-S03

**Intent:** Apply user edits — edit title/hypothesis, reorder, drop, add — with no agent involvement.

**Acceptance:**
- Given an edit/reorder/drop/add, when `POST /plan/update` is called, then `plan.json` + `state.json` mutate synchronously and return immediately.
- Given any such call, when it runs, then **no** OpenCode request is made.
- Given an invalid section ID, when supplied, then the error envelope is returned.

**Source refs:** `API_CONTRACT.html` `POST /plan/update` · ADR-003 (backend-only set)
**Out of scope:** bottom-bar (agent-driven) plan revision — that goes through `/turn`
**Touches:** `backend/main.py`

---

### N2-S05 · Accept plan & start first section

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N2-S03, N2-S06

**Intent:** Accept the plan, transition planning→building, trigger the first section.

**Acceptance:**
- Given `POST /plan/accept`, when called, then the plan locks, the state transitions to building, and section 1 is auto-triggered via the narrow interface.
- Given the transition, when it occurs, then `stage.changed` is emitted.
- Given an already-accepted plan, when called again, then the operation is idempotent.

**Source refs:** `API_CONTRACT.html` `POST /plan/accept` · `WORKFLOW_ORCHESTRATION.md` §Stage 3→4
**Out of scope:** the sequential N→N+1 loop (Night 3)
**Touches:** `backend/orchestrator.py`, `backend/main.py`

---

### N2-S06 · Section build turn (the file triplet)

**Role:** BE  ·  **Size:** L  ·  **Depends on:** N1-S09

**Intent:** The section turn — write a `.py`, run it, save a `.png`, write a `.md` with frontmatter.

**Acceptance:**
- Given the section prompt, when sent, then it drives OpenCode to write `analyses/sec_NN_<slug>.py`, run it, save `charts/sec_NN_<slug>.png`, and write `sections/sec_NN_<slug>.md` with frontmatter + interpretation.
- Given the section turn, when configured, then it uses **no** structured-output format — the triplet is the structure (ADR-005).
- Given a file write, when it occurs, then it is detected via `file.edited`.

**Source refs:** `WORKFLOW_ORCHESTRATION.md` §Stage 4 (template) · ADR-005 · reconciled contract (`apply_patch`, `file.edited`)
**Out of scope:** structured output for sections (explicitly not used)
**Touches:** `backend/prompts/section.py`

---

### N2-S07 · Section build events

**Role:** BE  ·  **Size:** M  ·  **Depends on:** N1-S08, N2-S06

**Intent:** Translate the section turn's activity into domain events.

**Acceptance:**
- Given tool/file/message events during the turn, when received, then they surface as `section.building` activity.
- Given `session.idle` with the expected triplet present, when detected, then `section.proposed` is emitted.
- Given the saved chart, when written, then `file.ready` is emitted so the SPA can fetch it.

**Source refs:** reconciled contract · `API_CONTRACT.html` (`section.*`, `session.idle`, `tool.*`)
**Out of scope:** failure detection (N2-S08)
**Touches:** `backend/opencode_client.py`

---

### N2-S08 · Detect failed section

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N2-S07

**Intent:** Detect a silent build failure — the agent self-recovers most bash errors, so failure only shows as a missing artefact at idle.

**Acceptance:**
- Given `session.idle` without the expected `.md` (and/or `.png`), when detected, then `section.failed` is emitted with the section ID.
- Given transient bash errors the agent recovers from mid-turn, when they occur, then `section.failed` is **not** emitted.

**Source refs:** `WORKFLOW_ORCHESTRATION.md` §error handling
**Out of scope:** the failure UI (Night 3)
**Touches:** `backend/opencode_client.py`

---

### N2-S09 · Frontmatter parser

**Role:** BE  ·  **Size:** S  ·  **Depends on:** —

**Intent:** Deterministically parse section markdown frontmatter for rendering and export ordering.

**Acceptance:**
- Given a `sections/*.md` file, when parsed, then frontmatter and body are separated.
- Given malformed frontmatter, when encountered, then it fails safe — the section is flagged, not crashed.
- Given parsed output, when produced, then it feeds `GET /state` and export.

**Source refs:** `WORKFLOW_ORCHESTRATION.md` §Stage 4 (frontmatter) · ADR-005 · `API_CONTRACT.html` `GET /state`
**Out of scope:** writing `.md` (the agent does this)
**Touches:** `backend/state_manager.py` (or a parser module)

---

### N2-S10 · Accept section

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N2-S03

**Intent:** Commit a proposed section.

**Acceptance:**
- Given `POST /section/:id/accept`, when called, then the section is marked `accepted` and the call returns immediately.
- Given any such call, when it runs, then **no** OpenCode request is made.
- Given an unknown ID, when supplied, then the error envelope is returned.

**Source refs:** `API_CONTRACT.html` `POST /section/:id/accept` · ADR-003
**Out of scope:** triggering the next section (Night 3 loop)
**Touches:** `backend/main.py`

---

### N2-S11 · Drop section

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N2-S03

**Intent:** Drop a proposed section.

**Acceptance:**
- Given `POST /section/:id/drop`, when called, then the section is marked `dropped` and the call returns immediately.
- Given a dropped section, when export runs, then it is excluded from ordering.
- Given any such call, when it runs, then **no** OpenCode request is made.

**Source refs:** `API_CONTRACT.html` `POST /section/:id/drop` · ADR-003
**Out of scope:** next-section trigger
**Touches:** `backend/main.py`

---

### N2-S12 · Redirect a section (Stage 4b)

**Role:** BE  ·  **Size:** M  ·  **Depends on:** N2-S06, N1-S11

**Intent:** The mid-section recovery moment — the user redirects, the agent discards drafts and rebuilds the same section.

**Acceptance:**
- Given a building section, when `POST /turn` is called with redirect text, then the redirect prompt is dispatched and 204 returns.
- Given a redirect, when it runs, then prior drafts for that section are discarded before rebuild.
- Given the rebuild, when it completes, then a fresh triplet and a new `section.proposed` are produced.
- Given a stall during rebuild, when it occurs, then the watchdog recovers it.

**Source refs:** `DATA_BUDDY_MOCKUPS_STRIPPED.html` (Stage 4b) · `WORKFLOW_ORCHESTRATION.md` §Stage 4 redirect · `API_CONTRACT.html` `POST /turn` · `backend/prompts/redirect.py`
**Out of scope:** plan-stage bottom bar (the `/turn` planning path)
**Touches:** `backend/main.py`, `backend/prompts/redirect.py`, `backend/opencode_client.py`

---

### N2-S13 · Export brief (`GET /export`)

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N2-S09

**Intent:** Produce the deliverable — one Markdown file of accepted sections in plan order.

**Acceptance:**
- Given accepted sections, when `GET /export` is called, then their `.md` bodies are concatenated in `plan.json` order.
- Given dropped/proposed sections, when export runs, then they are excluded.
- Given the call, when it runs, then it is backend-only (no OpenCode) and returns valid Markdown.

**Source refs:** `API_CONTRACT.html` `GET /export` · ADR-005
**Out of scope:** non-Markdown formats (out of scope globally)
**Touches:** `backend/main.py`

---

### N2-S14 · Serve workspace files (`GET /file`)

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N1-S02

**Intent:** Let the SPA fetch chart PNGs and other workspace files for rendering.

**Acceptance:**
- Given a relative path under `workspace/`, when `GET /file` is called, then the file is served with the correct content-type.
- Given a path traversal outside `workspace/`, when attempted, then it is rejected.
- Given a missing file, when requested, then a 404 + error envelope is returned.

**Source refs:** `API_CONTRACT.html` `GET /file` · ADR-005 (workspace layout)
**Out of scope:** write access
**Touches:** `backend/main.py`

---

### N2-S15 · Plan screen

**Role:** FE  ·  **Size:** M  ·  **Depends on:** N1-S14

**Intent:** The plan-proposal screen — inline edits to `/plan/update`, bottom-bar text to `/turn`, accept to `/plan/accept`.

**Acceptance:**
- Given `plan.json`, when rendered, then `sections[{title,hypothesis}]` display.
- Given an inline edit/reorder/drop/add, when made, then it calls `/plan/update` with no agent turn.
- Given bottom-bar text, when submitted, then it calls `/turn` and shows live progress.
- Given accept, when clicked, then it calls `/plan/accept` and advances; the commit vs revise paths are visually distinct.

**Source refs:** `DATA_BUDDY_MOCKUPS_STRIPPED.html` (Plan proposal) · `API_CONTRACT.html` plan endpoints
**Out of scope:** section build UI
**Touches:** `frontend/src/components/StageViews/PlanView.tsx`

---

### N2-S16 · Section build screen

**Role:** FE  ·  **Size:** L  ·  **Depends on:** N1-S14, N1-S17

**Intent:** The section-build screen — show the building section, its artefacts, and the controls.

**Acceptance:**
- Given a building section, when it runs, then `section.building` activity shows live in the rail.
- Given `section.proposed`, when received, then the pane renders read-only code, the chart (via `GET /file`), and the interpretation.
- Given Accept/Drop, when clicked, then they call `/section/:id/accept` or `/drop` with no agent turn.
- Given bottom-bar redirect, when submitted, then it calls `/turn` and the section rebuilds.

**Source refs:** `DATA_BUDDY_MOCKUPS_STRIPPED.html` (Section build + 4b) · `API_CONTRACT.html` section endpoints + `GET /file`
**Out of scope:** sequential auto-advance (Night 3) · error UIs (Night 3) · editable code (out of scope globally)
**Touches:** `frontend/src/components/StageViews/BuildView.tsx`, `SectionPane.tsx`

---

### N2-S17 · Export control

**Role:** FE  ·  **Size:** S  ·  **Depends on:** N1-S14

**Intent:** Trigger and deliver the export.

**Acceptance:**
- Given at least one accepted section, when the export control is used, then it calls `GET /export` and delivers the `.md`.
- Given no accepted sections, when the screen renders, then the control is disabled.

**Source refs:** `DATA_BUDDY_MOCKUPS_STRIPPED.html` · `API_CONTRACT.html` `GET /export`
**Out of scope:** format choices
**Touches:** `frontend/src/components/` (export control)

---

### N2-S18 · Integrate Night 2 slice

**Role:** TL  ·  **Size:** M  ·  **Depends on:** N2-S01–N2-S17, N2-S20

**Intent:** Assemble the merged lane work into a running Night-2 build, resolve mismatches, and hand a green interaction loop to QA.

**Acceptance:**
- Given all Night-2 lane stories are merged, when `make dev` runs, then plan → one section build → accept → export runs end-to-end.
- Given a contract mismatch (plan/section/file endpoints vs FE), when integration runs, then it is resolved or raised as a blocker.
- Given the integrated slice, when handed to QA, then backend-only operations demonstrably make no OpenCode calls.

**Source refs:** `01_SLICE_PLAN.md` (Slice 2 DoD) · `03_OPERATING_MODEL.md`
**Out of scope:** independent verification (QA owns)
**Touches:** cross-cutting wiring

---

### N2-S19 · Night 2 QA & demo script

**Role:** QA  ·  **Size:** M  ·  **Depends on:** N2-S18, N2-S20

**Intent:** Codify the interaction-loop review path.

**Acceptance:**
- Given the integrated slice, when the script runs, then plan (with an inline edit + a bottom-bar revision) → accept → one section build → mid-build redirect + rebuild → accept → export.
- Given the run, when assertions execute, then `plan.json` is valid, the triplet exists and the `.py` exits 0, frontmatter is valid, statuses transition correctly, `/plan/*` and `/section/*` produce no OpenCode traffic, and the export `.md` contains the accepted section.
- Given a pass/fail result, when produced, then it gates merge.

**Source refs:** `01_SLICE_PLAN.md` (Slice 2 DoD) · `04_QA_PLAN.md`
**Out of scope:** multi-section + failure coverage (Night 3)
**Touches:** `qa/`

---

### N2-S20 · Forced section-failure test hook

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N2-S08

**Intent:** Drive the `section.failed` path deterministically for QA — force a build to idle without writing the `.md` triplet member — without relying on the model to misbehave.

**Acceptance:**
- Given a forced-failure flag on a section build, when the turn idles, then no `sections/<id>.md` is produced and `section.failed` is emitted with the section ID.
- Given the flag is off, when a build runs, then behaviour is unchanged.

**Source refs:** `WORKFLOW_ORCHESTRATION.md` §error handling · `04_QA_PLAN.md` §2
**Out of scope:** turn.error forcing (Night 3, N3-S16); the failure UI
**Touches:** `backend/opencode_client.py`
**Notes:** opt-in test seam, off by default.

---

## Night 3 — Scale, robustness, and the deliverable

**Sprint goal (morning review):** via `make run` from a clean checkout, build a full multi-section brief on the churn dataset, repeat the core path on a **second dataset** to prove generality, induce a failure and recover it via the retry banner, and export the brief — the submission state.

**Contracts in play:** the error-handling model (`WORKFLOW_ORCHESTRATION.md`) · ADR-008 / 009 · `make run`.

---

### N3-S01 · Sequential section loop & done

**Role:** BE  ·  **Size:** M  ·  **Depends on:** N2-S05, N2-S10

**Intent:** Accepting a section triggers the next until all are built, then the brief is done.

**Acceptance:**
- Given a section is accepted, when the loop runs, then the next `proposed` section in plan order is triggered.
- Given the last section is accepted, when the loop completes, then the state transitions to `done` and `stage.changed(done)` is emitted.
- Given dropped sections, when sequencing, then they are skipped.
- Given rapid accepts, when they occur, then the loop is re-entrant safe (no double-trigger).

**Source refs:** `C4_ARCHITECTURE.html` (state machine) · `WORKFLOW_ORCHESTRATION.md` §Stage 4 sequencing
**Out of scope:** error handling (own stories)
**Touches:** `backend/orchestrator.py`

---

### N3-S02 · Retry a turn

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N1-S11

**Intent:** A retry re-issues the failed turn's prompt against the (possibly fresh) session.

**Acceptance:**
- Given a failed turn, when retry is invoked, then the exact prompt for that stage/section is re-sent.
- Given a watchdog fresh-session swap, when retry runs after it, then it targets the new session.
- Given repeated failures, when they occur, then retries are bounded (no infinite auto-retry).

**Source refs:** `WORKFLOW_ORCHESTRATION.md` §error handling · ADR-002
**Out of scope:** the banner UI (N3-S05)
**Touches:** `backend/opencode_client.py`, `backend/orchestrator.py`

---

### N3-S03 · Map turn errors

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N1-S09, N2-S02

**Intent:** Map structured-output failures and provider errors to the retry-banner signal.

**Acceptance:**
- Given a structured-output failure after `retryCount`, when it occurs, then `turn.error` is emitted with a stage/section reference and a retryable flag.
- Given a provider error, when it occurs, then `turn.error` is emitted likewise.
- Given the two failure classes, when emitted, then `turn.error` (recoverable) is distinguished from `section.failed` (missing-artefact).

**Source refs:** `WORKFLOW_ORCHESTRATION.md` §error handling (failure mode 1) · `API_CONTRACT.html` `turn.error`
**Out of scope:** UI
**Touches:** `backend/opencode_client.py`

---

### N3-S04 · Harden watchdog for long runs

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N1-S11, N3-S01

**Intent:** Ensure the watchdog behaves across many turns in one brief.

**Acceptance:**
- Given a full multi-section run, when each turn runs, then watchdog timers reset correctly per turn.
- Given a stall on any section, when it occurs, then recovery via fresh session does not corrupt `state.json` or the section sequence.
- Given a session-ID swap, when it happens, then it persists.

**Source refs:** ADR-002 · `opencode-spike/SPIKE_REPORT.md`
**Out of scope:** new failure modes
**Touches:** `backend/watchdog.py`

---

### N3-S05 · Retry banner

**Role:** FE  ·  **Size:** S  ·  **Depends on:** N1-S14, N3-S02

**Intent:** The inline retry pattern on the current stage.

**Acceptance:**
- Given `turn.error`, when received, then an inline banner appears on the current stage with a Retry action.
- Given Retry, when clicked, then it calls the retry path.
- Given a subsequent success, when it lands, then the banner clears.

**Source refs:** `WORKFLOW_ORCHESTRATION.md` §error handling (UI pattern 1) · `DATA_BUDDY_MOCKUPS_STRIPPED.html`
**Out of scope:** section.failed / watchdog surfaces (own stories)
**Touches:** `frontend/src/components/`

---

### N3-S06 · Failed-section controls

**Role:** FE  ·  **Size:** S  ·  **Depends on:** N1-S14, N2-S08

**Intent:** The failure pattern for a section that produced no artefact.

**Acceptance:**
- Given `section.failed`, when received, then the section shows Retry / Drop.
- Given Retry, when clicked, then the section re-runs.
- Given Drop, when clicked, then the section is marked dropped and the loop continues.

**Source refs:** `WORKFLOW_ORCHESTRATION.md` §error handling (failure modes 2/3) · `DATA_BUDDY_MOCKUPS_STRIPPED.html`
**Out of scope:** retry-banner (N3-S05)
**Touches:** `frontend/src/components/`

---

### N3-S07 · Watchdog-timeout surface

**Role:** FE  ·  **Size:** S  ·  **Depends on:** N3-S06

**Intent:** Surface a watchdog abort to the user with recovery options.

**Acceptance:**
- Given a watchdog-driven `section.failed` / `turn.error`, when received, then it surfaces with Retry / Drop.
- Given a stall, when it happens, then the user is not left facing a silent hang.

**Source refs:** `WORKFLOW_ORCHESTRATION.md` §error handling (failure mode 3)
**Out of scope:** backend watchdog logic
**Touches:** `frontend/src/components/`

---

### N3-S08 · Done screen

**Role:** FE  ·  **Size:** S  ·  **Depends on:** N1-S14, N3-S01

**Intent:** The completed-brief state with export prominent.

**Acceptance:**
- Given `stage.changed(done)`, when received, then the SPA shows the completed brief with all accepted sections.
- Given the done state, when rendered, then a clear export action is present.

**Source refs:** `DATA_BUDDY_MOCKUPS_STRIPPED.html` · `stage.changed(done)`
**Out of scope:** snapshots (out of scope globally)
**Touches:** `frontend/src/components/`

---

### N3-S09 · `make run` (built bundle)

**Role:** TL  ·  **Size:** M  ·  **Depends on:** N1-S01

**Intent:** The single-command submission path (ADR-008).

**Acceptance:**
- Given `make run`, when invoked, then the frontend is built (`vite build`) and FastAPI serves `frontend/dist/` statically on one port.
- Given the built bundle, when the loop runs, then it works against the bundle (not the Vite dev server).
- Given the README, when followed, then `make run` is documented.

**Source refs:** ADR-008 (serving + Makefile targets)
**Out of scope:** Docker (out of scope globally)
**Touches:** `Makefile`, `backend/main.py`

---

### N3-S10 · `make clean` & gitignore

**Role:** TL  ·  **Size:** S  ·  **Depends on:** N1-S01

**Intent:** Reset to a clean state between runs.

**Acceptance:**
- Given `make clean`, when invoked, then the runtime `workspace/` and build artefacts are removed.
- Given the repo, when inspected, then `workspace/` is gitignored.
- Given a clean → `make run` cycle, when executed, then it works.

**Source refs:** ADR-009 (Makefile, tooling)
**Out of scope:** —
**Touches:** `Makefile`, `.gitignore`

---

### N3-S11 · README

**Role:** TL  ·  **Size:** S  ·  **Depends on:** N3-S09

**Intent:** The required README — prerequisites and how to run.

**Acceptance:**
- Given the README, when read, then it covers prerequisites (Python 3.12, uv, Node, OpenCode v1.15.10 + provider auth) and `make install` / `dev` / `run` / `clean`.
- Given a new reader, when they follow it, then they can run the prototype from scratch on the churn CSV.

**Source refs:** ADR-009 · ADR-008 (Makefile targets + prerequisites the README documents)
**Out of scope:** the architecture write-up (N3-S12)
**Touches:** `README.md`

---

### N3-S12 · Architecture write-up

**Role:** TL  ·  **Size:** M  ·  **Depends on:** —

**Intent:** The short architecture document the assignment asks for, landing the interview framings.

**Acceptance:**
- Given the write-up, when read, then it covers the orchestration model, files-as-contract, the backend-only vs agent-driven split, structured output (profile/plan) vs the file triplet (sections), and the single-session model + extension path.
- Given the ADRs, when referenced, then they are cited rather than restated.

**Source refs:** `C4_ARCHITECTURE.html` · `ADR.md` (framings: ADR-002, ADR-003, ADR-005)
**Out of scope:** exhaustive API docs (the contract already exists)
**Touches:** `docs/ARCHITECTURE.md` (or a README section)

---

### N3-S13 · Integrate submission build

**Role:** TL  ·  **Size:** M  ·  **Depends on:** N3-S01–N3-S12, N3-S16

**Intent:** Assemble the merged lane work into the submission build, confirm the full loop runs via `make run`, and hand it to QA.

**Acceptance:**
- Given all Night-3 lane stories are merged, when `make run` runs from a clean checkout, then the full loop (multi-section build, an error recovery, export) runs end-to-end.
- Given an integration mismatch, when found, then it is resolved or raised as a blocker.
- Given the submission build, when handed to QA, then it starts cleanly with no manual steps beyond the README prerequisites.

**Source refs:** `01_SLICE_PLAN.md` (Slice 3 DoD) · `03_OPERATING_MODEL.md`
**Out of scope:** independent verification (QA owns)
**Touches:** cross-cutting wiring, `Makefile`

---

### N3-S14 · Full regression

**Role:** QA  ·  **Size:** L  ·  **Depends on:** N3-S13, N3-S16

**Intent:** The night's verification across scale, generality, and failure.

**Acceptance:**
- Given the submission build, when regression runs, then a multi-section brief builds on the churn CSV **and** a second dataset.
- Given an induced structured-output/provider failure, when triggered, then it recovers via the retry banner.
- Given a forced stall, when triggered, then it recovers via the watchdog.
- Given a cold `make run` on a clean checkout, when executed, then the full loop completes and export produces a valid multi-section `.md`.

**Source refs:** `01_SLICE_PLAN.md` (Slice 3 DoD) · `04_QA_PLAN.md`
**Out of scope:** —
**Touches:** `qa/`

---

### N3-S15 · Submission demo script

**Role:** QA  ·  **Size:** S  ·  **Depends on:** N3-S14

**Intent:** The rehearsed end-to-end path for the interview demo.

**Acceptance:**
- Given `make run`, when the script runs, then the full loop (setup → profile → plan → multi-section build → a redirect → export) completes within a demo-sized time budget on the churn dataset.
- Given each interview framing, when reached in the script, then the point at which it is visible is noted.

**Source refs:** `ADR.md` (framings: ADR-002, ADR-003, ADR-005)
**Out of scope:** —
**Touches:** `qa/`

---

### N3-S16 · Forced turn-error test hook

**Role:** BE  ·  **Size:** S  ·  **Depends on:** N3-S03

**Intent:** Drive the `turn.error` path deterministically for QA — simulate a structured-output / provider failure — so the retry banner and retry recovery are testable without token spend.

**Acceptance:**
- Given `QA_FORCE_TURN_ERROR`, when a turn runs under it, then `turn.error` is emitted with a retryable flag.
- Given a retry after the forced error with the flag cleared, when it runs, then the turn recovers.
- Given the flag is off, when a turn runs, then behaviour is unchanged.

**Source refs:** `WORKFLOW_ORCHESTRATION.md` §error handling (failure mode 1) · `04_QA_PLAN.md` §2
**Out of scope:** the retry banner UI (N3-S05)
**Touches:** `backend/opencode_client.py`
**Notes:** opt-in test seam, off by default.

---

## Sequencing summary

- **Night 1** retires agent-runtime, SSE, and recovery risk. N1-S07 (reconciled contract) gates all SSE work; N1-S11 (watchdog) is exercised by the N1-S12 second turn; N1-S18 (TL integration) greens the slice before N1-S19 (QA).
- **Night 2** retires interaction-loop, file-triplet, and redirect risk. Depends on Night 1's client, persistent SSE, watchdog, state store, and `GET /state` being merged. Export and `GET /file` are backend-only and independent of the agent path.
- **Night 3** retires failure-mode and generality risk and produces the deliverable. The error UIs depend on Night 1's watchdog and Night 2's `section.failed` / `turn.error` signals already existing.
- Within each night the lanes run in parallel against the contracts in the header; TL integrates (the `Sxx` integration story) and QA verifies the structural DoD before merge. Mechanics in `03_OPERATING_MODEL.md`.
