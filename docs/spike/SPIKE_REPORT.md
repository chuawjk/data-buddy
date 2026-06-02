# OpenCode Smoke Test Spike — Report

**Date:** 2026-05-26  
**Time budget used:** ~25 minutes

---

## 1. Version Pinned

```
opencode 1.15.10
```

Binary location: `/Users/kennychua/.opencode/bin/opencode` (not in PATH — must use full path or add to PATH).

This version is **past** the known SSE regression range (v1.14.42–v1.14.46). No downgrade needed.

---

## 2. Provider / Model Used

- **Provider:** OpenAI via OAuth (`opencode providers` shows `OpenAI oauth`)
- **Model used for spike:** `gpt-5.4-mini`
- **providerID / modelID in API calls:** `"providerID": "openai", "modelID": "gpt-5.4-mini"`
- **Setup notes:** Auth was pre-configured. No API key required — OAuth token stored at `~/.local/share/opencode/auth.json`. The OpenAPI config at `~/Library/Application Support/opencode/opencode.jsonc` is nearly empty (just `$schema`); auth is separate.

---

## 3. SSE Stream Healthy?

**YES.**

- `server.connected` event arrived immediately on connect.
- Stream stayed open indefinitely — `server.heartbeat` events fired every ~10s.
- SSE regression (issue #26697) is **not present** in v1.15.10.
- A new `server.heartbeat` event type was observed (not mentioned in the plan). Useful as a keep-alive signal for UI clients.

---

## 4. Event Shapes Captured

Full raw events saved in `/tmp/opencode-spike/spike-events.txt`.

### `message.part.updated` — ToolPart (`apply_patch`, completed)
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
          "patchText": "*** Begin Patch\n*** Add File: /private/tmp/opencode-spike/hello.txt\n+world\n*** End Patch"
        },
        "output": "Success. Updated the following files:\nA private/tmp/opencode-spike/hello.txt",
        "metadata": {
          "diff": "Index: /private/tmp/opencode-spike/hello.txt\n...",
          "files": [
            {
              "filePath": "/private/tmp/opencode-spike/hello.txt",
              "relativePath": "private/tmp/opencode-spike/hello.txt",
              "type": "add",
              "additions": 1,
              "deletions": 0
            }
          ]
        },
        "title": "Success. Updated the following files:\nA private/tmp/opencode-spike/hello.txt"
      }
    }
  }
}
```

### `message.part.updated` — TextPart
The agent did not emit a text part with content for this task (went straight to tools). Text parts are present in the stream (`type: "text"`) but with empty content when the model skips preamble. **No delta field observed** — text content is in `part.content`, not `part.delta`.

### `file.edited`
```json
{
  "id": "evt_e6373abad001t9yEU7LHwxU6wa",
  "type": "file.edited",
  "properties": {
    "file": "/private/tmp/opencode-spike/hello.txt"
  }
}
```

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

---

## 5. Session Reuse Confirmed?

**YES, with a caveat.**

- A second `prompt_async` to the same session was accepted (204) and new events started flowing.
- However, the second turn on the original session hung for 7+ minutes with no new events after the initial message receipt. `session.status: busy` persisted indefinitely.
- `POST /session/{id}/abort` returned 200 but did not unblock the turn.
- A **fresh second session** with the same prompt completed successfully in ~15s, creating `goodbye.txt` with `farewell`.
- **Verdict:** Multiple sessions work correctly. Within a single session, a stuck turn may require a new session rather than abort. See Surprises below.

---

## 6. Surprises

### API paths changed from plan
The plan's examples used `/session` and `/prompt_async` — these still exist in v1.15.10 and work as documented. However a newer `/api/session` v2 API also exists alongside. Stick with `/session` (v1) for now.

### File writes use `apply_patch`, not a `write` tool
The agent used `apply_patch` (a unified-diff tool) to create files, not a dedicated `write` tool. The `file.edited` event fires correctly either way. UI handlers should listen for `file.edited` and not assume a specific tool name.

### Tool part status lifecycle
Tool parts progress through: `pending` → `running` → `completed`. The `state.input` is populated at `pending` stage (before execution), and `state.output` + `state.metadata` arrive at `completed`. UI should handle all three states.

### New event types not in plan
Observed beyond the plan's list:
- `server.heartbeat` — fires every ~10s (keep-alive)
- `session.status` — `{type: "busy"}` / `{type: "idle"}` (precedes `session.idle`)
- `session.diff` — fires after each turn with git diff data
- `session.next.agent.switched` / `session.next.model.switched` — fires when a turn starts
- `step-start` / `step-finish` part types — wraps tool-use sequences
- `reasoning` part type — model reasoning steps (OpenAI chain-of-thought)
- `message.part.delta` — streaming deltas for text content

### Text parts have no delta field
The plan expected `message.part.updated` with `part.type: "text"` and a `delta` field. Observed behavior: text streaming arrives via a separate `message.part.delta` event type, not via `part.delta` in `message.part.updated`. UI event handlers need to subscribe to `message.part.delta` for streaming text.

### Stuck turn on second prompt (same session)
Second `prompt_async` to the same session hung indefinitely (~7+ min, no new events). Abort returned 200 but did not resolve. A fresh session completed the same task in ~15s. This may be a model API timeout or a session state issue after a long idle. Worth investigating if session reuse over long gaps is required.

---

## 7. Stop-the-Line Issues

**None.** The prototype can proceed on v1.15.10 with OpenAI.

One **watch item** (not a blocker): the stuck-turn behaviour on session reuse. If the prototype needs long-lived sessions across multiple user interactions, add a client-side timeout (e.g. 60s with no `message.part.updated` events) that aborts and retries on a fresh session.

---

## Artifacts

- `/tmp/opencode-spike/spike-events.txt` — raw event shapes for the four key types
- `/tmp/opencode-spike/events-clean.txt` — full SSE stream from the spike
- `/tmp/opencode-spike/hello.txt` — `world`
- `/tmp/opencode-spike/goodbye.txt` — `farewell`
