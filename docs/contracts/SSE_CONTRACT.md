# SSE Event Contract — Backend → SPA

**Status:** Authoritative (merged)
**Last updated:** 2026-06-02
**Story:** N1-S07 — Reconciled event contract

> **Placement note:** The story backlog referenced `backend/docs/SSE_CONTRACT.md`. This file lives
> at `docs/contracts/SSE_CONTRACT.md` instead, consistent with `CLAUDE.md` ("all contracts in
> `docs/contracts/`") and the fact that the FE lane codes against `docs/contracts/` as its
> integration boundary. The deviation is noted here and in the PR.

---

## 1. Purpose

This document is the single source of truth for the event mapping between OpenCode's raw SSE
stream and the backend-enriched events the SPA subscribes to via `GET /events`. It supersedes any
implicit mapping in earlier planning documents wherever they conflict with the spike data.

**Rule:** Where `docs/planning/WORKFLOW_ORCHESTRATION.md` or `docs/contracts/API_CONTRACT.html`
contradict the observed spike behaviour, **the spike wins** (per `CLAUDE.md` rule 3). Every
divergence is recorded explicitly in Section 3 of this document.

---

## 2. Backend → SPA Event Taxonomy

The backend emits enriched events on `GET /events` (standard SSE wire format:
`event: <type>\ndata: <json>\n\n`). These are derived from, filtered from, or generated
independently of OpenCode's raw stream. The SPA never reads OpenCode directly.

### 2.1 Events generated purely by the backend (no direct OpenCode source)

These events are synthesised by the orchestrator based on state transitions, not by forwarding a
raw OpenCode event.

---

#### `stage.changed`

Emitted every time `state.stage` is written.

| Field | Type | Source |
|---|---|---|
| `type` | `"stage.changed"` | constant |
| `stage` | `"profiling" \| "planning" \| "building" \| "done"` | backend state machine |
| `ts` | `number` (ms epoch) | backend wall clock |

**Trigger:** Backend orchestrator on every stage transition write to `state.json`.

---

#### `profile.ready`

Emitted after the backend parses the profiling turn's structured JSON output and writes
`profile.json` to the workspace.

| Field | Type | Source |
|---|---|---|
| `type` | `"profile.ready"` | constant |
| `profile` | `object` | parsed structured output; full schema in `API_CONTRACT.html` §3 |
| `ts` | `number` (ms epoch) | backend wall clock |

**Trigger:** Backend, after `session.idle` fires on the profiling turn and `profile.json` is
successfully written. Precedes the `stage.changed` → `"planning"` event.

---

#### `plan.ready`

Emitted after the backend parses the planning turn's structured JSON output and writes `plan.json`.

| Field | Type | Source |
|---|---|---|
| `type` | `"plan.ready"` | constant |
| `sections` | `array` | parsed plan; each item: `{ id, title, hypothesis, status: "queued" }` |
| `ts` | `number` (ms epoch) | backend wall clock |

**Trigger:** Backend, after `session.idle` on the planning turn and `plan.json` written.

---

#### `section.building`

Emitted immediately after the backend fires a section build prompt to OpenCode, before any
OpenCode events arrive.

| Field | Type | Source |
|---|---|---|
| `type` | `"section.building"` | constant |
| `section_id` | `string` | from `state.json` plan array |
| `title` | `string` | from `state.json` plan array |
| `ts` | `number` (ms epoch) | backend wall clock |

**Trigger:** Backend, immediately after `POST /session/:id/prompt_async` for a section build.

---

#### `section.proposed`

Emitted on `session.idle` after the backend verifies that all three section workspace files exist
(`analyses/*.py`, `charts/*.png`, `sections/*.md`).

| Field | Type | Source |
|---|---|---|
| `type` | `"section.proposed"` | constant |
| `section_id` | `string` | active section from state |
| `py_path` | `string` | relative workspace path, e.g. `"analyses/sec_02_churn_by_tier.py"` |
| `png_path` | `string` | relative workspace path |
| `md_path` | `string` | relative workspace path |
| `ts` | `number` (ms epoch) | backend wall clock |

**Trigger:** Backend on `session.idle` when all three files are present.

---

#### `section.failed`

Emitted on `session.idle` when expected section files are absent, or on watchdog timeout after
abort completes (or times out).

| Field | Type | Source |
|---|---|---|
| `type` | `"section.failed"` | constant |
| `section_id` | `string` | active section from state |
| `reason` | `"timeout" \| "output_error" \| "missing_files"` | backend diagnosis |
| `ts` | `number` (ms epoch) | backend wall clock |

**Trigger:** Backend on `session.idle` with missing files, or watchdog after abort.

---

#### `turn.error`

Emitted when a structured-output turn fails (exhausted retries, provider error, watchdog-triggered
abort with no recovery).

| Field | Type | Source |
|---|---|---|
| `type` | `"turn.error"` | constant |
| `stage` | `string` | current stage at time of failure |
| `reason` | `"structured_output_failed" \| "timeout" \| "provider_error"` | backend diagnosis |
| `ts` | `number` (ms epoch) | backend wall clock |

**Trigger:** Backend error handling path; not directly from any OpenCode event.

---

#### `heartbeat`

Keep-alive event; proxied from OpenCode's `server.heartbeat` but re-emitted on the backend's
own cadence (every 15 s from backend timer; OpenCode fires every ~10 s). The backend may also
emit this independently if OpenCode heartbeats stop arriving.

| Field | Type | Source |
|---|---|---|
| `type` | `"heartbeat"` | constant |
| `ts` | `number` (ms epoch) | backend wall clock at proxy time |

**OpenCode source:** `server.heartbeat` (see Section 4 — raw event shape not captured in spike;
event type name confirmed).

---

### 2.2 Events derived from OpenCode `message.part.updated` (tool parts)

OpenCode emits `message.part.updated` for every state transition of every message part. The
backend filters these to the active session and active turn, then translates tool parts into SPA
events based on `part.tool` and `part.state.status`.

#### Tool part status lifecycle (spike-confirmed)

Tool parts progress through three statuses in order:

```
pending  →  running  →  completed
```

- `pending`: `part.state.input` is populated; execution has not started.
- `running`: execution in progress; `state.input` still available, output not yet populated.
- `completed`: `part.state.output` and `part.state.metadata` are populated; `part.state.time`
  (`start` and `end` in ms epoch) is present.

The backend must handle all three states; emitting SPA events only at `running` and `completed`
is the intended pattern.

---

#### `tool.bash_running`

| Field | Type | Source (OpenCode field path) |
|---|---|---|
| `type` | `"tool.bash_running"` | constant |
| `command` | `string` | `properties.part.state.input.command` |
| `description` | `string \| null` | `properties.part.state.input.description` (optional) |
| `started_at` | `number` (ms epoch) | `properties.time` (event-level timestamp) |
| `ts` | `number` (ms epoch) | `properties.time` |

**OpenCode trigger:** `message.part.updated` where:
- `properties.part.type === "tool"`
- `properties.part.tool === "bash"`
- `properties.part.state.status === "running"`

---

#### `tool.bash_done`

| Field | Type | Source (OpenCode field path) |
|---|---|---|
| `type` | `"tool.bash_done"` | constant |
| `command` | `string` | `properties.part.state.input.command` |
| `exit_code` | `number` | `properties.part.state.metadata.exit` |
| `elapsed_ms` | `number` | `properties.part.state.time.end - properties.part.state.time.start` |
| `ts` | `number` (ms epoch) | `properties.time` |

**OpenCode trigger:** `message.part.updated` where:
- `properties.part.type === "tool"`
- `properties.part.tool === "bash"`
- `properties.part.state.status === "completed"`

---

#### `tool.file_written`

Emitted for every file entry in `state.metadata.files[]` when an `apply_patch` tool part
completes. If `apply_patch` writes multiple files, one `tool.file_written` event is emitted per
file entry.

| Field | Type | Source (OpenCode field path) |
|---|---|---|
| `type` | `"tool.file_written"` | constant |
| `file` | `string` | `properties.part.state.metadata.files[i].relativePath` |
| `op` | `"add" \| "modify" \| "delete"` | `properties.part.state.metadata.files[i].type` |
| `additions` | `number` | `properties.part.state.metadata.files[i].additions` |
| `deletions` | `number` | `properties.part.state.metadata.files[i].deletions` |
| `elapsed_ms` | `number` | `properties.part.state.time.end - properties.part.state.time.start` |
| `ts` | `number` (ms epoch) | `properties.time` |

**OpenCode trigger:** `message.part.updated` where:
- `properties.part.type === "tool"`
- `properties.part.tool === "apply_patch"` (or any file-writing tool; see divergence D1)
- `properties.part.state.status === "completed"`
- `properties.part.state.metadata.files` is a non-empty array

**Note on tool name:** Do not hardcode `"apply_patch"` as the only valid tool name. Filter on
`completed` status and the presence of `metadata.files[]`; the actual tool name is informational
only.

---

### 2.3 Events derived from OpenCode `message.part.delta`

#### `message.part`

Streaming text chunks. These arrive on a dedicated `message.part.delta` event type, not as a
field inside `message.part.updated` (see divergence D2).

| Field | Type | Source (OpenCode field path) |
|---|---|---|
| `type` | `"message.part"` | constant |
| `part_id` | `string` | `properties.partID` (if present) or `properties.part.id` |
| `content` | `string` | `properties.delta` — the incremental text chunk |
| `ts` | `number` (ms epoch) | `properties.time` or backend wall clock |

**OpenCode trigger:** `message.part.delta` event (distinct event type, not a field).

**Usage:** Optional in the SPA; used to stream agent reasoning or text output into a collapsible
pane. The backend forwards these without blocking.

---

### 2.4 Events derived from OpenCode `file.edited`

#### `file.ready`

Emitted whenever OpenCode signals that a workspace file has been written or modified, regardless
of which tool produced the write.

| Field | Type | Source (OpenCode field path) |
|---|---|---|
| `type` | `"file.ready"` | constant |
| `path` | `string` | `properties.file` (absolute path from OpenCode) |
| `ts` | `number` (ms epoch) | backend wall clock at receipt |

**OpenCode trigger:** `file.edited` event.

**Note:** `file.edited` is the canonical "a file changed" signal. The backend strips the
workspace root prefix before forwarding `path` to the SPA so paths are workspace-relative.

---

### 2.5 Events derived from OpenCode `session.idle`

OpenCode's `session.idle` event is not forwarded directly to the SPA. Instead it is consumed
internally by the backend orchestrator to:

1. Determine whether to emit `section.proposed` or `section.failed` (section build stage).
2. Determine whether to emit `profile.ready` (profiling stage).
3. Determine whether to emit `plan.ready` (planning stage).
4. Emit a `stage.changed` event when advancing.

The `session.idle` raw event also resets the watchdog timer.

**Raw shape (spike-confirmed):**
```json
{
  "id": "evt_e6373b155002w4Jvs0pYiwUbRC",
  "type": "session.idle",
  "properties": {
    "sessionID": "ses_19c8d84bcffeUjlqbSsxJ6wr2F"
  }
}
```

---

## 3. Divergence Record

Every place where the spike contradicts the spec. The spike wins in each case.

### D1 — File writes: `file.edited` event, not a tool-name filter

**Spec said:** Watch for `message.part.updated` with `part.tool === "write"` (or a named write
tool) to detect file writes.

**Spike found:** The agent used `apply_patch` (a unified-diff tool), not a dedicated `write`
tool. A `file.edited` event fires after any successful file write regardless of which tool
produced it. The correct approach is:

- Use `file.edited` as the canonical "file changed" signal (maps to `file.ready`).
- Use `apply_patch` completed parts for richer metadata (path, additions, deletions) to emit
  `tool.file_written`.
- Do not filter on tool name to detect writes. Tool name is informational only.

### D2 — Text streaming: `message.part.delta` event (not `part.delta` field)

**Spec said:** Text streaming arrives via `message.part.updated` with `part.type: "text"` and a
`delta` field on the part.

**Spike found:** Streaming text deltas arrive on a separate, dedicated event type:
`message.part.delta`. This is a different event from `message.part.updated`. The `part.delta`
field does not exist on `message.part.updated`. `message.part.updated` for text parts carries the
full accumulated `part.content`, not incremental deltas.

**Handler implication:** Subscribe to `message.part.delta` for streaming text. Subscribe to
`message.part.updated` for tool state transitions and final text content. These are separate
subscriptions.

### D3 — Tool lifecycle: three-state transitions (pending → running → completed)

**Spec said:** Tool parts arrive with a `running` or `completed` status; no mention of `pending`.

**Spike found:** Tool parts progress through three statuses: `pending` → `running` → `completed`.

- `pending`: Input is populated but execution has not begun.
- `running`: Execution in progress.
- `completed`: Output and metadata are available; `state.time.start` and `.end` are set.

**Handler implication:** The backend must handle all three statuses without erroring. Emit
`tool.bash_running` on `running`, `tool.bash_done` on `completed`. Ignore `pending` for SPA
events (or optionally emit a lower-priority activity hint).

### D4 — Extra event types to handle or ignore

The following event types appear in the OpenCode stream but were not in the spec. All are safe to
receive; none require the backend to crash or emit a `turn.error`.

| OpenCode event type | Observed in spike | Recommended handling |
|---|---|---|
| `server.heartbeat` | Yes (every ~10 s) | Proxy as `heartbeat` to SPA; reset watchdog timer |
| `session.status` | Yes (`{ type: "busy" }` / `{ type: "idle" }`) | Use as supplementary signal; `session.idle` event remains authoritative for state transitions |
| `session.diff` | Yes (fires after each turn with git diff data) | Ignore for now; no SPA consumer in scope |
| `session.next.agent.switched` | Yes | Ignore |
| `session.next.model.switched` | Yes | Ignore |
| `step-start` / `step-finish` | Yes (part types that wrap tool-use sequences) | Ignore (no SPA consumer in scope) |
| `reasoning` | Yes (model chain-of-thought part type) | Ignore unless forwarding to a reasoning pane; not required in scope |
| `server.connected` | Yes (fires once on SSE connect) | Log; no SPA event emitted |

### D5 — Session API: use v1 `/session` (not v2 `/api/session`)

**Spec said:** Use `/session` and `/prompt_async` endpoints.

**Spike found:** A newer v2 API (`/api/session`) exists alongside the v1 paths. Both are present
in v1.15.10. The v1 paths (`POST /session`, `POST /session/:id/prompt_async`,
`POST /session/:id/abort`) work as documented.

**Decision:** Stick with v1 `/session` for this prototype. The v2 API is noted but not adopted
until it stabilises.

### D6 — Stuck turn on session reuse (watchdog implication)

**Spec said:** Sessions can be reused; abort recovers a stuck turn.

**Spike found:** A second `prompt_async` to the same session hung for 7+ minutes. `POST
/session/:id/abort` returned 200 but did not unblock the turn. A fresh session with the same
prompt succeeded in ~15 s.

**Decision (from WORKFLOW_ORCHESTRATION.md §Error handling):** The watchdog fires after 60 s of
no events. Abort is attempted; if abort does not resolve within ~10 s, fall back to a fresh
OpenCode session preserving logical state from `state.json`. `section.failed` or `turn.error` is
emitted to the SPA. This behaviour is already in the spec; the spike confirms the abort
unreliability that motivates the fresh-session fallback.

---

## 4. OpenCode Raw Event Reference

Observed field shapes from the spike. These are what the backend parses; all field paths are
relative to the top-level event object.

### Top-level envelope (all events)

```json
{
  "id": "evt_<id>",
  "type": "<event-type>",
  "properties": { }
}
```

### `message.part.updated` — tool part, `apply_patch`, `completed`

```json
{
  "id": "evt_e6373abb0001kJ4qSZPampp1sf",
  "type": "message.part.updated",
  "properties": {
    "sessionID": "ses_19c8d84bcffeUjlqbSsxJ6wr2F",
    "part": {
      "type": "tool",
      "tool": "apply_patch",
      "callID": "call_MC6oU8wS2HuEJbhAEdo5sOsz",
      "state": {
        "status": "completed",
        "input": {
          "patchText": "*** Begin Patch\n*** Add File: /path/file.txt\n+content\n*** End Patch"
        },
        "output": "Success. Updated the following files:\nA path/file.txt",
        "metadata": {
          "diff": "Index: ...",
          "files": [
            {
              "filePath": "/absolute/path/file.txt",
              "relativePath": "path/file.txt",
              "type": "add",
              "patch": "Index: ...",
              "additions": 1,
              "deletions": 0
            }
          ],
          "diagnostics": {},
          "truncated": false
        },
        "title": "Success. Updated the following files:\nA path/file.txt",
        "time": {
          "start": 1779784985515,
          "end": 1779784985520
        }
      },
      "metadata": {
        "openai": { "itemId": "fc_..." }
      },
      "id": "prt_<id>",
      "sessionID": "ses_...",
      "messageID": "msg_..."
    },
    "time": 1779784985520
  }
}
```

### `message.part.updated` — tool part, `bash`, `completed`

```json
{
  "id": "evt_e63738acd0010XhIF0YFlMWxd5",
  "type": "message.part.updated",
  "properties": {
    "sessionID": "ses_...",
    "part": {
      "type": "tool",
      "tool": "bash",
      "callID": "call_SlotncEIphD827fRXD01yfsw",
      "state": {
        "status": "completed",
        "input": {
          "command": "ls",
          "timeout": 120000,
          "workdir": "/path/to/workdir",
          "description": "Lists workspace contents"
        },
        "output": "file1.txt\nfile2.txt\n",
        "metadata": {
          "output": "file1.txt\nfile2.txt\n",
          "exit": 0,
          "description": "Lists workspace contents",
          "truncated": false
        },
        "title": "Lists workspace contents",
        "time": {
          "start": 1779784977098,
          "end": 1779784977101
        }
      },
      "metadata": {
        "openai": { "itemId": "fc_..." }
      },
      "id": "prt_...",
      "sessionID": "ses_...",
      "messageID": "msg_..."
    },
    "time": 1779784977101
  }
}
```

**Key fields for `tool.bash_running` (status `running`):** `part.state.input.command`,
`part.state.input.description`, `properties.time`.

**Key fields for `tool.bash_done` (status `completed`):** same as above plus
`part.state.metadata.exit`, `part.state.time.start`, `part.state.time.end`.

### `file.edited`

```json
{
  "id": "evt_e6373abad001t9yEU7LHwxU6wa",
  "type": "file.edited",
  "properties": {
    "file": "/absolute/path/to/file.txt"
  }
}
```

**Key field:** `properties.file` — absolute path. Strip workspace root to get relative path for
the SPA.

### `session.idle`

```json
{
  "id": "evt_e6373b155002w4Jvs0pYiwUbRC",
  "type": "session.idle",
  "properties": {
    "sessionID": "ses_19c8d84bcffeUjlqbSsxJ6wr2F"
  }
}
```

### `message.part.delta` (text streaming — shape inferred from spike report; not directly captured)

```json
{
  "id": "evt_...",
  "type": "message.part.delta",
  "properties": {
    "sessionID": "ses_...",
    "partID": "prt_...",
    "delta": "<incremental text chunk>"
  }
}
```

> Note: The exact field names for `message.part.delta` were not captured verbatim in
> `SPIKE_EVENTS.txt`. The spike report confirms the event type exists and carries incremental
> text content. Implementers should log the raw shape on first receipt and update this reference
> if field names differ.

### `server.heartbeat` (shape inferred; type name confirmed)

```json
{
  "id": "evt_...",
  "type": "server.heartbeat",
  "properties": {}
}
```

> Note: Heartbeat event confirmed present (every ~10 s); exact properties not captured in spike
> artefacts. Treat `properties` as opaque; only `type` is used.

---

## 5. Event Filter Rules

The backend SSE subscription receives events for all sessions on the OpenCode server. The backend
must filter to events relevant to the active session and active turn:

1. **Session filter:** Check `properties.sessionID` (present on `message.part.updated`,
   `session.idle`, `session.status`) against the active `session_id` from `state.json`. Discard
   events for other sessions.
2. **Global events** (`server.heartbeat`, `server.connected`, `file.edited`) carry no `sessionID`;
   handle all of them (they are always relevant).
3. **Unknown event types** must be silently ignored (logged at DEBUG level), never cause a crash
   or `turn.error`.

---

## 6. Watchdog Integration

Any of the following OpenCode events resets the 60 s watchdog timer (per
`WORKFLOW_ORCHESTRATION.md` §Error handling):

- `message.part.updated` (any)
- `message.part.delta` (any)
- `server.heartbeat`
- `session.status`

An event that does NOT reset the timer: none observed — all raw OpenCode events count as
liveness signals. On watchdog expiry: attempt `POST /session/:id/abort`; if no recovery within
~10 s, create a fresh session and emit `turn.error` or `section.failed` to the SPA.
