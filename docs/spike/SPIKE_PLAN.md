# OpenCode Smoke Test Spike — Handoff Plan

## Objective

Verify that OpenCode's HTTP server and SSE event stream work end-to-end on a pinned version, before any prototype work begins. Output a short go/no-go note that the prototype build can rely on.

**Time budget:** 60–90 minutes. If it takes more than 2 hours, stop and report the blocker.

## Context

We're building a co-work UI prototype with OpenCode (sst/anomalyco) as the agent backend, driven by a backend service over HTTP. The architecture depends on three things working reliably:

1. `opencode serve` runs as a long-lived HTTP server.
2. Sessions can be created and prompted programmatically.
3. The `/event` SSE stream emits tool/file/message events as the agent works.

There is a known regression in versions v1.14.42–v1.14.46 where the SSE stream closes immediately after the initial `server.connected` event (GitHub issue #26697). v1.14.41 is reported as the last known-good before the regression. This spike confirms which currently-installable version is safe to build on.

## Setup

1. Install OpenCode using the official install script:
   ```
   curl -fsSL https://opencode.ai/install | bash
   ```
2. Check the installed version: `opencode --version`.
3. Configure one model provider. OpenCode Zen's free tier is fine for this spike — run `opencode auth login` and pick a Zen free model (e.g., one of the free MiniMax/Mimo options). If Zen auth is awkward, an Anthropic API key works: `export ANTHROPIC_API_KEY=...`.
4. Create a clean test workspace:
   ```
   mkdir /tmp/opencode-spike && cd /tmp/opencode-spike
   ```

## Steps

### 1. Start the server

In one terminal, from inside `/tmp/opencode-spike`:
```
opencode serve --port 4096
```

Confirm it starts without errors and stays running. Note the version it reports.

### 2. Check OpenAPI spec is reachable

In a second terminal:
```
curl http://localhost:4096/doc | head -50
```

Confirm an OpenAPI 3.1 spec returns. Note the paths under `/session` and `/event` exist.

### 3. Subscribe to the event stream

In a third terminal:
```
curl -N http://localhost:4096/event
```

You should see at minimum a `server.connected` event. **Leave this terminal open for the rest of the spike.** Every action below should produce more events in this stream.

**Critical check:** if the stream closes immediately after `server.connected` and nothing else ever arrives even when you do step 5 below, you've hit issue #26697. Stop the server, uninstall, and reinstall pinning to v1.14.41 (check release notes for the install method — likely `npm install -g opencode-ai@1.14.41` or downloading a specific binary from GitHub releases). Retry from step 1.

### 4. Create a session

In the second terminal:
```
curl -X POST http://localhost:4096/session \
  -H 'Content-Type: application/json' \
  -d '{"title": "spike test"}'
```

Confirm a JSON response with a session `id`. Save the ID. Confirm a `session.created` event appears in the event stream terminal.

### 5. Send a prompt that exercises a file write

Using the session ID from step 4 — substitute it for `<SESSION_ID>`:
```
curl -X POST http://localhost:4096/session/<SESSION_ID>/prompt_async \
  -H 'Content-Type: application/json' \
  -d '{
    "agent": "build",
    "model": {"providerID": "<PROVIDER>", "modelID": "<MODEL>"},
    "parts": [{"type": "text", "text": "Create a file called hello.txt containing the single word: world"}]
  }'
```

Fill in `<PROVIDER>` and `<MODEL>` based on what you authenticated. The endpoint should return `204 No Content` immediately.

Now watch the event stream terminal. Within 5–30 seconds you should see a sequence including at minimum:
- `message.updated` (assistant message created)
- One or more `message.part.updated` events with `part.type: "tool"` (the agent calling the `write` tool)
- A `file.edited` event
- `session.idle` (the turn finishing)

Confirm `/tmp/opencode-spike/hello.txt` exists with the expected content.

### 6. Capture event shapes

Copy the raw event stream output for the turn into a file. We need to see the actual JSON shapes of these event types to design the UI's event handlers later:

- `message.part.updated` with a `ToolPart` (specifically with `state.input` containing the file content)
- `message.part.updated` with a `TextPart` and a non-empty `delta`
- `file.edited`
- `session.idle`

Save this as `spike-events.txt` in the workspace. It's the most valuable artifact of the spike.

### 7. Quick second turn

Send one more prompt against the same session to confirm sessions are reusable:
```
curl -X POST http://localhost:4096/session/<SESSION_ID>/prompt_async \
  -H 'Content-Type: application/json' \
  -d '{
    "agent": "build",
    "model": {"providerID": "<PROVIDER>", "modelID": "<MODEL>"},
    "parts": [{"type": "text", "text": "Now create goodbye.txt with the word: farewell"}]
  }'
```

Confirm events flow and the second file is created.

## Deliverable

A short note covering:

1. **Version pinned** — the exact `opencode --version` output that the spike succeeded on. This is what the prototype will pin to.
2. **Provider/model used** — what was configured and any setup gotchas.
3. **SSE stream healthy?** — yes/no. If no, what was tried (downgrade attempts, versions tested).
4. **Event shapes captured** — the `spike-events.txt` file, or inline excerpts of the four critical event types listed in step 6.
5. **Session reuse confirmed?** — yes/no.
6. **Any surprises** — anything in the event stream, API responses, or setup that wasn't predicted by the research report. Especially: missing event types, unexpected error events, auth flow weirdness, timing issues.
7. **Stop-the-line issues** — anything that would block prototype build (e.g., can't get any working version, no model provider works, file writes don't fire `file.edited` events).

## Out of scope for this spike

Don't test these — they're being deferred to in-flight discovery:
- Structured output via `format: json_schema`
- Abort / cancel behavior
- Backend restart / session resume after crash
- Sub-agent invocation via the Task tool
- Long sessions or context compaction
- Plugin / custom tool development

If you find yourself going down any of these paths, stop and flag it.

## Failure modes

- **SSE closes immediately:** downgrade to v1.14.41 as described in step 3.
- **No provider works:** try at least two — Zen free and Anthropic. If both fail, flag the auth issue; this is a setup problem, not an OpenCode problem.
- **File write doesn't trigger events:** capture the actual events that did fire, and the assistant's text response. This would be a more serious finding than the SSE bug — flag it loudly.
- **Server hangs or crashes:** capture stderr, the version, and the command that triggered it. Don't try to debug — just report.