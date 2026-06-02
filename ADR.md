# Architecture Decision Record
## Data Buddy prototype

*Single running document. Each decision is recorded when made and never deleted — superseded decisions are marked as such and linked to their replacement.*

---

## Index

| ID | Title | Status |
|----|-------|--------|
| ADR-001 | OpenCode integration mode | Accepted |
| ADR-002 | Session lifecycle strategy | Accepted |
| ADR-003 | Orchestration model | Accepted |
| ADR-004 | Structured output mechanism | Accepted |
| ADR-005 | File workspace as agent contract | Accepted |
| ADR-006 | SSE subscription lifetime | Accepted |
| ADR-007 | Frontend state ownership | Accepted |
| ADR-008 | Frontend serving strategy | Accepted |
| ADR-009 | Local development and deployment tooling | Accepted |
| ADR-010 | N1-S06 opencode_client.py committed directly to develop outside a PR | Proposed — pending review |
| ADR-011 | N1-S18: profile prompt must write workspace/profile.json explicitly | Proposed — pending review |
| ADR-012 | N1-S18: OpenCode lifecycle owned by backend; make dev does not start opencode | Proposed — pending review |

---

## ADR-001 · OpenCode integration mode

**Status:** Accepted
**Date:** 2026-05-26

### Decision
Integrate with OpenCode via `opencode serve` (HTTP server mode) and talk to it over HTTP using raw `fetch` calls or the `@opencode-ai/sdk`. Do not shell out to the CLI as a subprocess.

### Context
OpenCode supports three integration modes: HTTP server (`opencode serve`), JS/TS SDK wrapper, and CLI subprocess. The CLI mode is one-shot per invocation and re-pays MCP cold-start cost on every call. The HTTP server mode is the officially blessed programmatic surface — it's what the TUI, desktop app, and IDE plugins all use internally.

### Consequences
- Backend spawns `opencode serve --port <port>` on startup (or expects it to be running).
- All communication is over localhost HTTP — REST for commands, SSE for the event stream.
- The backend does not need to manage OpenCode process stdin/stdout.
- Version must be pinned; confirmed working on v1.15.10 (spike result).

---

## ADR-002 · Session lifecycle strategy

**Status:** Accepted
**Date:** 2026-05-26

### Decision
Create one OpenCode session per brief at setup time. Hold the session ID in `state.json`. Drive all turns against that single session ID for the lifetime of the brief. If a turn gets stuck and abort does not resolve within ~10s, fall back to creating a fresh OpenCode session and storing the new ID in `state.json` — the logical session continues even if the underlying OpenCode session is replaced.

### Context
OpenCode sessions are persistent entities stored in SQLite. A session created via `POST /session` survives server restarts and can receive new turns at any time. The spike confirmed that multiple turns against the same session work correctly under normal conditions, but also surfaced a stuck-turn bug where a second prompt to the same session hung indefinitely (~7+ minutes). A fresh session completed the same task in ~15s.

### Consequences
- `state.json` always holds the current active OpenCode session ID.
- A watchdog monitors for 60s without SSE events and triggers abort.
- If abort does not resolve in ~10s, backend creates a new session and updates `state.json`.
- The agent's conversational memory is effectively reset on session replacement, but this is acceptable because all context is re-supplied in every prompt (aim, profile, plan, prior section files).

---

## ADR-003 · Orchestration model

**Status:** Accepted
**Date:** 2026-05-26

### Decision
Backend-orchestrated, not agent-driven. The backend decides when to prompt OpenCode and with what. OpenCode has no knowledge of which stage the user is in. Roughly half of all UI button actions are backend-only operations (accept section, drop section, reorder plan, export) that never involve the agent.

### Context
The alternative was to give OpenCode a long system prompt describing all stages and let it self-direct. This was rejected because it makes the recovery moment harder to control, makes structured output less reliable, and would make the backend's job harder to reason about and test.

### Consequences
- Each stage has an explicit prompt template in `backend/prompts/`.
- The backend is responsible for knowing which stage is active and what to send next.
- Backend-only operations are simple synchronous HTTP endpoints — no SSE subscription needed.
- Agent-driven operations (profiling, plan generation, section build, bottom-bar revision) open an SSE subscription and wait for `session.idle`.

---

## ADR-004 · Structured output mechanism

**Status:** Accepted
**Date:** 2026-05-26

### Decision
Use OpenCode's native `format: { type: "json_schema", schema: {...}, retryCount: 2 }` parameter on `POST /session/:id/prompt_async` for all turns that need machine-parseable output (profile, plan). Do not use prompt-engineering hacks to extract JSON from free-form text.

### Context
OpenCode implements structured output via a hidden `StructuredOutput` tool — the model is forced to call this tool to return JSON matching the schema, and the runtime validates and retries on failure. This is more reliable than asking the model to "return JSON" in a text response and then parsing it. Section builds (Stage 4) do not use structured output because the section's structure is the file triplet itself.

### Consequences
- Profile and plan prompts must include a `format` field with a well-defined JSON Schema.
- `retryCount: 2` is the default; may need increasing for complex schemas.
- The watchdog must count all SSE events (including reasoning deltas during retries) as activity — not just tool events — to avoid false-positive timeouts during structured output retries.
- On `StructuredOutputError` after retries, surface a retry banner to the user.

---

## ADR-005 · File workspace as agent contract

**Status:** Accepted
**Date:** 2026-05-26

### Decision
Files in the workspace directory are the contract between the backend and OpenCode. The backend reads agent output from files on disk (and from SSE event payloads where richer), not from the agent's conversational memory. Every prompt re-supplies full context from files, not from session history.

### Context
Two approaches were considered for how state is communicated to the OpenCode agent across turns.

**Option A — Files as memory (chosen)**
Every prompt is fully self-contained. The backend re-supplies the aim, `profile.json`, and `plan.json` on every relevant turn. The agent has no dependency on its own conversational history to do its job.

**Option B — Session as memory**
The aim, profile, and plan are supplied once at the start of the session. Subsequent prompts are lean ("build section 3"). The agent carries context across turns in its own SQLite-backed conversation history.

### Tradeoffs

**Option A — Files as memory**
- Resilient to session replacement (watchdog fallback creates a fresh session; next prompt re-supplies everything).
- Resilient to OpenCode context compaction (compaction is lossy — the agent gets a summary, not full history; re-supplied context sidesteps this entirely).
- State is always inspectable independently of OpenCode — read `state.json` and workspace files at any point.
- Backend is fully testable without a live OpenCode session.
- Cost: larger prompts. Re-supplying profile and plan on every section build turn costs 2,000–4,000 tokens per turn depending on dataset width and plan size. Real but not prohibitive on modern 128K–200K context window models.

**Option B — Session as memory**
- Leaner prompts — state is supplied once, subsequent turns are minimal.
- More fragile: OpenCode compacts at ~75% context window. A 6-section brief with multiple bottom-bar revisions could hit compaction before completion, and the compacted summary may lose precision.
- Watchdog fallback (fresh session) becomes much harder — requires replaying the full conversation history into the new session, which is complex and error-prone under the 20–30 hour budget.
- State is opaque — if something goes wrong, you cannot inspect what the agent "knows" independently of its session.

### Why Option A is correct for this prototype
The stuck-turn bug found in the spike (second prompt to the same session hung for 7+ minutes) makes session-as-memory genuinely risky. The watchdog already has to handle session replacement; if state lives in the session, that recovery path becomes substantially harder to implement correctly. The token cost of re-supplying context is real but manageable given modern context window sizes.

### Future direction
For a production system with longer briefs and a more stable agent runtime, a hybrid approach would be appropriate: supply profile and plan into the session once (lean prompts), but maintain `state.json` as a durable backup that can reconstruct context if the session needs replacing. This preserves the resilience of Option A without paying the token cost on every turn.

### Consequences
- Workspace layout: `data/`, `analyses/`, `charts/`, `sections/`, `profile.json`, `plan.json`, `state.json`.
- Every section build prompt includes the full `profile.json` and `plan.json` contents.
- Prompts must be written as independently comprehensible — the agent should not need to remember what happened in a prior turn.
- Backend writes to the workspace only when the session is idle (to avoid races with in-flight agent tool calls).
- On snapshot revert, the OpenCode session is kept as-is — the agent's memory disagrees with the workspace, but the next prompt re-supplies all context from files, so this is acceptable.

### Known inefficiency: deliberate redundancy
Re-supplying context on every prompt creates redundancy: OpenCode's SQLite session already holds the conversation history (prior prompts, tool calls, outputs), so the agent sees the profile and plan both from its own history *and* from the re-supplied context in the current prompt. This duplication costs tokens on every turn — estimated 2,000–4,000 tokens per section build turn depending on profile width and plan size.

This is a conscious choice, not an oversight. The history in SQLite cannot be relied upon unconditionally: it may be compacted (lossy), the session may be replaced by the watchdog, or the history may diverge from workspace state after a user revert. Re-supplying context is cheap insurance against these failure modes during a live demo.

A leaner alternative would be to re-supply only the structural context (aim, plan) and trust the agent to recall the derived context (profile) from its history, only re-supplying the profile on session replacement. This would reduce redundancy while preserving the recovery path. Deferred as a known optimisation — for the prototype budget, the simple redundant approach is preferred and the inefficiency should be acknowledged in the architecture write-up.

---

## ADR-006 · SSE subscription lifetime

**Status:** Accepted
**Date:** 2026-05-26

### Question
Should the backend maintain a **single persistent SSE subscription** to OpenCode's `/event` stream for the lifetime of the server, or open a **fresh subscription per agent turn** (from `prompt_async` to `session.idle`)?

### Options

**Option A — Single persistent subscription**
The backend connects to `GET /event` once at startup and keeps it open indefinitely. All events from all turns flow through this one connection, demuxed by `sessionID` on each event. The backend forwards relevant events to the frontend via its own SSE endpoint.

- Simpler to reason about — one connection, one stream, no setup/teardown logic per turn.
- Heartbeat (`server.heartbeat` every ~10s) gives a natural health signal; if it stops, reconnect.
- The known SSE regression (issue #26697) would affect all turns equally — easier to detect and handle with a single watchdog.
- Slight risk: if a stale event from a previous turn arrives late, the backend must filter by current session ID.

**Option B — Per-turn subscription**
The backend opens a fresh `GET /event` connection after each `prompt_async` call and closes it when `session.idle` is received.

- Clean isolation between turns — no cross-turn event leakage.
- Easier to implement a per-turn timeout without a separate watchdog.
- More connection churn; each new subscription may miss events that fired between `prompt_async` returning and the subscription opening (race window).
- The race window is the critical flaw: `prompt_async` returns 204 immediately, but the agent may emit its first events within milliseconds. A fresh subscription opened after the 204 could miss them.

### Recommendation
Option A — single persistent subscription. The race window in Option B is a silent data-loss bug with no clean fix. Option A is also simpler to implement: one connection opened at startup, one `if sessionID == current` filter on every event.

### Decision
**Option A — single persistent SSE subscription.**
The backend opens `GET /event` once at server startup and keeps it open for the lifetime of the process. Events are filtered by `sessionID` to the current active session and forwarded to the frontend. If the heartbeat stops (no `server.heartbeat` for >30s), the backend reconnects. The watchdog (ADR-002) operates on this same stream.

---

## ADR-007 · Frontend state ownership

**Status:** Accepted
**Date:** 2026-05-26

### Question
Does the React SPA maintain its own meaningful client-side state, or does it treat the backend as the single source of truth and re-hydrate fully from the backend on every page load?

### Options

**Option A — Backend is source of truth; SPA is a thin view**
All durable state lives in `state.json` on the backend. On page load, the SPA calls `GET /state` and gets back everything it needs to render the current stage: stage name, plan, section statuses, profile, any in-progress section content. The SPA holds only transient UI state (which pane is active, whether a dropdown is open).

- Simple mental model: one source of truth, no sync problems.
- Page refresh always works correctly — the SPA re-hydrates from the backend.
- Suitable for a Python backend developer more comfortable with server-side state.
- Slight latency on page load while `GET /state` resolves, but negligible on localhost.

**Option B — SPA holds a local copy of state, synced from backend**
The SPA maintains a local state store (e.g. React context or Zustand) that mirrors backend state. On page load it hydrates from `GET /state`, then keeps local state updated via the SSE stream without further REST calls for reads.

- More responsive UI — no round-trip for reads after initial hydration.
- More complex — risk of local state diverging from backend state if an event is missed or mishandled.
- Adds a meaningful state management layer to the SPA component diagram.
- Overkill for a localhost prototype where latency is near-zero.

### Recommendation
Option A — backend as source of truth. Option B introduces a two-copy state sync problem that is unnecessary complexity for a localhost prototype. Option A maps naturally to a Python backend developer's mental model: the server owns state, the frontend renders it.

### Decision
**Option A — backend is source of truth; SPA is a thin view.**
All durable state lives in `state.json` on the backend. On page load (and on refresh), the SPA calls `GET /state` and receives everything needed to render the current stage. The SPA holds only transient UI state (active pane, input focus, etc.) in React local state — nothing that needs to survive a refresh. The SSE stream is used only for live updates during active agent turns; it does not replace `GET /state` as the hydration mechanism.

---

## ADR-008 · Frontend serving strategy

**Status:** Accepted
**Date:** 2026-05-30

### Decision
Hybrid: develop with a separate Vite dev server (hot-reload, two ports), submit with FastAPI serving the built React bundle as static files (one process, one port, one command).

### Context
Two options were considered. Option A (FastAPI serves built bundle) gives a clean single-command submission but costs hot-reload during development. Option B (separate Vite dev server) gives hot-reload but requires CORS configuration and a two-terminal README — friction for the reviewer. The hybrid approach gets the development experience of Option B and the submission cleanliness of Option A at no real cost.

### Consequences
- Makefile has two targets: `make dev` (starts both FastAPI and Vite dev server) and `make run` (builds frontend bundle then starts FastAPI only).
- FastAPI mounts `frontend/dist/` as static files at `/` in production mode.
- Vite dev server proxies API calls to `localhost:8000` during development — no CORS configuration needed on FastAPI.
- Submission README instructs reviewers to use `make run` only. `make dev` is documented as the development workflow.

---

## ADR-009 · Local development and deployment tooling

**Status:** Accepted
**Date:** 2026-05-30

### Decision
Makefile only. No Docker or Docker Compose.

### Context
Docker was considered for submission cleanliness and to signal production-awareness. However OpenCode's filesystem coupling makes containerisation awkward for a local prototype: the workspace directory needs a bind-mount, OpenCode writes session state to `~/.local/share/opencode/` (a second mount), and it needs outbound network access to the model provider. Each of these is solvable but adds setup steps that can fail silently on a reviewer's machine. The JD explicitly states "working prototype preferred over production polish." A Makefile is more transparent, easier to debug, and appropriate for the scope.

### Consequences
- `make install` — creates Python venv, installs dependencies via `uv`, checks for OpenCode binary (prompts to install if missing).
- `make run` — builds frontend bundle, starts `opencode serve`, starts FastAPI. Both processes managed by the Makefile (or a simple process manager like `honcho`).
- `make dev` — starts `opencode serve`, FastAPI, and Vite dev server as three concurrent processes.
- `make clean` — removes workspace files, resets `state.json` to empty. Used between demo runs.
- Docker is noted in the README as a known limitation with a clear path: "In a production deployment, OpenCode would run as a sidecar container with a shared volume mount for the workspace directory."

---

## ADR-010 · N1-S06 opencode_client.py committed directly to develop outside a PR

**Status:** Proposed — pending review
**Date:** 2026-06-02

### Decision
Accept `opencode_client.py` and its unit tests as they were committed directly to `develop` (commit `8fe71cf`) outside the PR flow. PR #12 (N1-S06) is treated as having satisfied all acceptance criteria, with the module's content already landed and the PR delivering only the `main.py` lifespan wiring.

### Context
During a TL DEV_STATUS update, `backend/opencode_client.py` and `backend/tests/unit/app/test_opencode_client.py` were accidentally staged (from in-progress N1-S05/S06 work in the working tree) and committed directly to `develop` as part of commit `8fe71cf`. This is a lane boundary violation: TL should not commit BE feature code, and all lane work should arrive via PR.

### Rationale for accepting rather than reverting
- The content is correct — it implements the N1-S06 acceptance criteria faithfully and was later reviewed as part of the PR #12 diff.
- Reverting `8fe71cf` would rewrite shared history on `develop`, which is irreversible and prohibited by CONTRIBUTING §7.
- The PR #12 review gate did inspect the full `opencode_client.py` source (it was visible in the `8fe71cf` commit on the base branch) and found it satisfactory.
- No security, contract, or architectural concerns were found in the content.

### Prevention
TL must run `git diff --cached` and `git status` before every living-doc commit to ensure no unintended files are staged. The pre-commit hook does not catch out-of-lane file additions.

---

## ADR-011 · N1-S18: profile prompt must write workspace/profile.json explicitly

**Status:** Proposed — pending review
**Date:** 2026-06-02

### Decision
The profiling turn prompt must explicitly instruct OpenCode to **write** the JSON output to `workspace/profile.json` (via `apply_patch` or equivalent). It is insufficient to ask OpenCode to "return JSON" as message content.

### Context
N1-S09's `build_profile_prompt()` asked OpenCode to "return valid JSON matching the schema exactly." This is correct for OpenCode's structured output mechanism (which enforces the schema and returns the JSON as the model's response), but the orchestrator reads `workspace/profile.json` on `session.idle` — a file that only exists if OpenCode writes it. Without an explicit write instruction, the profiling turn completes and `session.idle` fires, but `profile.json` is absent, so `profile.ready` is never emitted.

### Rationale
OpenCode's structured output (`format: { type: "json_schema", ... }`) causes the model to call a hidden `StructuredOutput` tool and return JSON. This JSON appears in the SSE stream as message content. It does NOT automatically write to a file. Writing to `workspace/profile.json` requires an explicit file-write instruction in the prompt ("write the JSON to workspace/profile.json"), which causes OpenCode to use `apply_patch` to create the file.

### Consequences
- `build_profile_prompt()` updated to say "write valid JSON matching the schema exactly to workspace/profile.json."
- The orchestrator's `_handle_profile_idle()` reads the file on `session.idle` — this is the correct pattern.
- The `file.edited` event (which fires on `apply_patch`) may arrive before `session.idle`; orchestrator waits for `session.idle` as the canonical "turn complete" signal before reading the file (avoids reading a partial write).

---

## ADR-012 · N1-S18: OpenCode lifecycle owned by backend; make dev does not start opencode

**Status:** Proposed — pending review
**Date:** 2026-06-02

### Decision
`make dev` does NOT start `opencode serve` separately. The backend's `OpenCodeClient.start()` is the sole owner of the `opencode serve` subprocess lifecycle.

### Context
The original `make dev` started `opencode serve &` alongside `uvicorn` and `vite`. The backend's `OpenCodeClient.start()` also calls `opencode serve --port 4096`. This created two competing `opencode serve` processes: the first (Makefile-started) bound to port 4096; the second (backend-started) failed silently to bind, leaving `self._process` pointing to a dead process. The backend communicated with the Makefile-started instance (health check passed against it), but shutdown was unreliable (SIGTERM hit the dead process, leaving the Makefile process running).

### Rationale
Having two components own the same process lifecycle is a violation of single-owner responsibility. `OpenCodeClient` already implements readiness polling, SIGTERM/SIGKILL shutdown, and has a `SKIP_OPENCODE=1` escape hatch for CI. Removing the Makefile-level start makes the lifecycle unambiguous and eliminates the race.

### Consequences
- `make dev` starts uvicorn and vite only; opencode is started by FastAPI lifespan.
- `make dev` no longer checks for opencode on PATH (the backend already does this and logs a clear error if missing).
- `SKIP_OPENCODE=1` continues to suppress opencode entirely for CI.
- `make run` (production mode) is unaffected — it started uvicorn only (the backend manages opencode there already).

