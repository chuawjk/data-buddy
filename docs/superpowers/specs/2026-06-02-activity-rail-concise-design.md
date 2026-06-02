# Activity Rail — Concise Display & Running Indicator

**Date:** 2026-06-02
**Status:** Approved

---

## Problem

The activity rail is verbose and gives no clear signal that the agent is still working:

1. `message.part` events stream OpenCode's full internal reasoning text and append it cumulatively — the rail becomes a wall of model monologue.
2. Tool events (`tool.bash_running`, `tool.bash_done`, `tool.file_written`) each add a separate row; a long turn can produce dozens of rows.
3. Nothing visually indicates that the agent is actively running versus idle.

---

## Goal

- Replace cumulative raw text with a compact, animated "Thinking..." status while a turn is active.
- Replace per-event tool rows with a single incrementing summary line.
- Persist the completion summary after `session.idle` until the next turn begins.

---

## Architecture

### `useActivityState` hook  (`frontend/src/hooks/useActivityState.ts`)

Single source of truth for all activity rail state. Subscribes to the SSE stream via `useSSE`.

**State shape:**
```ts
interface ActivityState {
  isRunning: boolean;
  bashCount: number;
  fileCount: number;
  dotPhase: 0 | 1 | 2;   // cycles while isRunning
}
```

**Event handling:**
| Event | Effect |
|---|---|
| `tool.bash_running`, `tool.bash_done`, `tool.file_written`, `message.part` | If this is the first event after idle: reset counts to 0, set `isRunning = true`. Then increment the relevant counter (`bashCount` for bash events, `fileCount` for file events). |
| `session.idle` | Set `isRunning = false`. Counts are NOT reset — they persist as the completion snapshot. |

**Dot animation:**
- A `setInterval` (500 ms) runs only while `isRunning`.
- Each tick cycles `dotPhase`: 0 → 1 → 2 → 0.
- The interval is cleared in the `useEffect` cleanup and whenever `isRunning` becomes false.

**"First event after idle" detection:**
The hook tracks a `wasIdle` ref (starts `true`). On any activating event (the four above), if `wasIdle` is true, reset counts and set `wasIdle = false`. On `session.idle`, set `wasIdle = true`.

---

### `ActivityRail` component  (`frontend/src/components/ActivityRail.tsx`)

Thin presenter — calls `useActivityState()`, renders the returned values, no state of its own.

**Rendering rules:**

1. **No activity yet** (`!isRunning && bashCount === 0 && fileCount === 0`):
   Render: `"No activity yet."` (existing placeholder, italic muted text).

2. **Running** (`isRunning === true`):
   Render: `"Thinking" + [".", "..", "..."][dotPhase]` — amber colour (`text-[#b8732a]`), `data-testid="activity-thinking"`.

3. **Summary line** (shown whenever `bashCount > 0 || fileCount > 0`):
   Render: e.g. `"4 commands run · 2 files written"`, omitting a term if its count is zero.
   Muted grey (`text-[#9b9489]`), `data-testid="activity-summary"`.
   Visible both during a run and after completion.

**Example states:**

```
[idle, no counts]      → "No activity yet."
[running, 2 bash, 0 files]  → "Thinking.."
                              "2 commands run"
[idle, 4 bash, 1 file]      → "4 commands run · 1 file written"
```

---

## Data-testid QA seams

| testid | When present |
|---|---|
| `activity-rail` | Always (root wrapper) |
| `activity-thinking` | While `isRunning` |
| `activity-summary` | Whenever `bashCount > 0 \|\| fileCount > 0` |

Previous testids `activity-tool-running`, `activity-tool-done`, `activity-file-written`, `activity-message` are **removed** (replaced by the above).

---

## Testing

**`useActivityState` hook tests** (`frontend/src/hooks/useActivityState.test.ts`):
- Initial state: `isRunning=false`, counts zero, `dotPhase=0`.
- First activating event after idle resets counts and sets `isRunning`.
- `bash_running`/`bash_done` increment `bashCount`; `file_written` increments `fileCount`.
- `message.part` sets `isRunning` without touching counts.
- `session.idle` sets `isRunning=false`, preserves counts.
- Second turn after idle resets counts on first activating event.
- `dotPhase` cycles on each 500ms tick while running (mock timers).
- Interval clears on `session.idle`.

**`ActivityRail` component tests** (`frontend/src/components/ActivityRail.test.tsx`):
- Update existing tests to use new testids and mock `useActivityState`.
- Cover: idle/no-counts renders placeholder; running renders `activity-thinking`; summary renders `activity-summary` with correct text; both can coexist.

---

## Out of scope

- Showing the actual file paths or command text anywhere in the rail.
- Per-section activity (the rail is turn-scoped, not section-scoped).
- Error state display (handled by existing `turn.error` / section error flows).
- Persisting activity across page reload.
