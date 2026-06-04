# Architecture — Data Buddy

See [`docs/contracts/C4_ARCHITECTURE.html`](contracts/C4_ARCHITECTURE.html) for the component diagram and [`docs/contracts/API_CONTRACT.html`](contracts/API_CONTRACT.html) for the full endpoint and SSE-event reference.

---

## 1. System overview

Data Buddy is an agent-driven data-analysis tool. A user uploads a CSV and states an aim; the system profiles the data, proposes an analysis plan, and builds the brief section by section. Each section produces a Python analysis script, a chart PNG, and a Markdown write-up. The completed brief is exported as a ZIP archive containing the report, charts, and code.

User journey: **upload** → **profiling** → **planning** → **building** (one section at a time) → **done / export**.

---

## 2. Orchestration model

The backend is a Python state machine (`orchestrator.py`) that drives OpenCode through five stages: `setup → profiling → planning → building → done`. The machine decides when to prompt OpenCode and with what — OpenCode has no knowledge of which stage it is in (ADR-003).

Stage transitions are persisted atomically to `workspace/state.json` via a tmp-and-rename write before the transition is announced. The browser is notified of every transition via a `stage.changed` SSE event.

### Files as contract (ADR-005)

Every prompt is self-contained. The backend re-supplies the aim, `profile.json`, and `plan.json` on every relevant turn so that OpenCode's conversational history is never load-bearing. This means:

- A watchdog-triggered session replacement (see §5) never loses context — the next prompt re-supplies everything from workspace files.
- The backend is fully testable without a live OpenCode process: place fixture files in `workspace/` and the state machine reads them identically.
- State is always inspectable independently of OpenCode's SQLite session store.

The cost is larger prompts — roughly 2,000–4,000 extra tokens per section build turn — which is acceptable given modern 128K–200K context windows and is acknowledged as a deliberate tradeoff.

---

## 3. Backend vs agent split (ADR-003)

Roughly half of all UI actions involve no agent call at all.

**Agent-driven operations** (OpenCode is prompted; progress arrives via SSE):
- Profile the dataset (`profiling` stage)
- Propose a plan (`planning` stage)
- Build a section: write analysis script, run it, produce chart, write interpretation (`building` stage)
- Bottom-bar revisions at any stage (re-profile, re-plan, section redirect)

**Backend-only operations** (synchronous HTTP, no OpenCode call):
- Edit / reorder / drop / add plan sections (`POST /plan/update`)
- Accept the plan (`POST /plan/accept`)
- Accept or drop a proposed section (`POST /section/:id/accept`, `POST /section/:id/drop`)
- Export the brief (`GET /export`)

This split keeps the backend testable, recovery paths simple, and the demo reliable: the interactive loop never stalls on agent latency for operations that are purely structural.

---

## 4. Structured output vs the file triplet (ADR-004, ADR-005)

**Profile and plan** use OpenCode's native structured output (`format: { type: "json_schema", schema: ..., retryCount: 2 }`). The model is forced to call a hidden `StructuredOutput` tool whose output is validated against the schema and retried on failure. On final failure, `turn.error` is emitted with a retryable flag so the user can trigger a retry.

**Section builds** do not use structured output. The section's structure IS the file triplet: `analyses/sec_NN_<slug>.py`, `charts/sec_NN_<slug>.png`, `sections/sec_NN_<slug>.md`. The prompt instructs OpenCode to write these files via `apply_patch`; the backend watches for `file.edited` events and validates the triplet on `session.idle`. A missing `.md` after idle → `section.failed`; a missing chart is tolerated.

This asymmetry is deliberate. Structured output is the right tool when the output is a data structure (JSON). It is the wrong tool when the output is a set of files that must be executed and whose chart depends on runtime results.

---

## 5. Session model and recovery (ADR-002)

One OpenCode session is created at setup time. Its ID is stored in `state.json`. All turns within a brief target the same session — OpenCode's SQLite-backed session carries the conversation history, which provides useful context even though every prompt re-supplies the structural context from files.

A watchdog (`watchdog.py`) monitors the SSE stream. If 60 seconds pass with no events during an active turn, it fires an abort against the current session. If abort does not resolve within ~10 seconds, it creates a fresh OpenCode session and stores the new ID in `state.json`. The next prompt targets the new session and re-supplies full context from workspace files, so the recovery is transparent.

The spike confirmed this is necessary: a second prompt to the same session can hang indefinitely (~7+ minutes). A fresh session completes the same task in ~15 seconds. The watchdog timeout is tunable via `WATCHDOG_TIMEOUT_SECONDS` for testing and environments where the model is slower.

---

## 6. SSE event transport

The backend maintains a single persistent SSE subscription to OpenCode's `GET /event` stream (ADR-006). Events are filtered to the current session ID, normalised, and forwarded to the frontend via `GET /events`.

Events fall into two categories:

- **Domain events** — `stage.changed`, `profile.ready`, `plan.ready`, `section.building`, `section.proposed`, `section.failed`, `session.idle`, `turn.error`. These drive stage transitions and state updates.
- **Activity events** — `tool.bash_running`, `tool.bash_done`, `tool.file_written`, `message.part`. These feed the Activity Rail — the live feed of what the agent is doing.

A single persistent subscription (rather than per-turn) avoids the race window where events emitted immediately after `prompt_async` returns would be missed by a freshly-opened connection.

The frontend subscribes to `GET /events` and uses SSE events as signals: `stage.changed` triggers a `GET /state` re-fetch for ground truth rather than trusting the event payload alone. This means a dropped SSE connection never leaves the UI permanently out of sync — the next page load recovers from `state.json`.

---

## 7. Extension path

The architecture has clear seams for future work, none of which are implemented:

- **Multi-user / auth**: each user would need their own `workspace/` directory (or a namespaced path) and their own OpenCode session. The session-ID-in-state-json pattern would become session-ID-in-user-session.
- **Cross-session snapshots**: `state.json` + the workspace files are a complete snapshot of a brief. Saving and restoring a brief would be a matter of archiving and restoring those files, plus handling the stale OpenCode session gracefully (fresh session + re-supplied context from the restored files).
- **Richer export formats**: `GET /export` currently produces a ZIP with Markdown and chart PNGs. Adding PDF or HTML would be a renderer layer on top of the same accepted-sections list — no changes to the agent or state machine.

Docker / containerisation is noted as out of scope for this prototype (ADR-009). In a production deployment OpenCode would run as a sidecar container with a shared volume mount for `workspace/`.
