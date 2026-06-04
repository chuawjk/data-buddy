# Plan: N3-FE Error UIs & Done Screen (N3-S05, N3-S06, N3-S07, N3-S08)

**Date:** 2026-06-04
**Stories:**
- N3-S05 · Retry banner (Size: S)
- N3-S06 · Failed-section controls (Size: S)
- N3-S07 · Watchdog-timeout surface (Size: S)
- N3-S08 · Done screen (Size: S)

**Branch:** `feat/n3-fe-error-done`
**Depends on:** N1-S14 (hooks — on develop), N2-S08 (section.failed BE — on develop), N3-S02 (retry BE — on develop), N3-S01 (done BE — on develop)

---

## What these stories do

Four related Night-3 FE deliverables that handle the two error surfaces and the completed-brief state:

- **N3-S05 (Retry banner):** When `turn.error` arrives, show an inline banner on the active stage view with a Retry button. Clicking Retry calls `POST /turn` with an empty body to re-fire the last prompt. The banner clears on the next success event (`profile.ready`, `plan.ready`, or `section.proposed`).
- **N3-S06 (Failed-section controls):** When `section.failed` arrives (missing artefact after idle), the section pane for that section shows Retry and Drop buttons. Retry re-runs the section; Drop marks it dropped and lets the loop continue.
- **N3-S07 (Watchdog-timeout surface):** Watchdog-driven failures emit `section.failed` (with `reason: "timeout"`) or `turn.error` (with `reason: "timeout"`). N3-S06/N3-S05 already handle these events; N3-S07 ensures the timeout case is visually distinguishable (shows a "timed out" notice) so the user is never left facing a silent hang.
- **N3-S08 (Done screen):** On `stage.changed(done)`, the SPA renders all accepted sections in plan order, with a prominent Export button. This is the completed-brief view.

---

## Files to create / modify

| File | Action | Stories |
|---|---|---|
| `frontend/src/components/RetryBanner.tsx` | New component | N3-S05 |
| `frontend/src/components/RetryBanner.test.tsx` | New Vitest tests | N3-S05 |
| `frontend/src/components/StageViews/BuildView.tsx` | Add failed-section Retry/Drop, watchdog notice | N3-S06, N3-S07 |
| `frontend/src/components/SectionPane.tsx` | Add `failed` state: Retry/Drop controls + timeout notice | N3-S06, N3-S07 |
| `frontend/src/components/SectionPane.test.tsx` | Extend with failed-state tests | N3-S06, N3-S07 |
| `frontend/src/components/StageViews/ProfileView.tsx` | Wire `turn.error` → show RetryBanner | N3-S05 |
| `frontend/src/components/StageViews/PlanView.tsx` | Wire `turn.error` → show RetryBanner | N3-S05 |
| `frontend/src/components/StageViews/DoneView.tsx` | New component | N3-S08 |
| `frontend/src/components/StageViews/DoneView.test.tsx` | New Vitest tests | N3-S08 |
| `frontend/src/App.tsx` | Route `done` stage to `DoneView`; propagate `turn.error` to current stage view | N3-S05, N3-S08 |
| `frontend/src/hooks/useApi.ts` | Add `postRetry()` — `POST /turn` with empty body | N3-S05 |
| `frontend/tests/e2e/error-done.spec.ts` | New Playwright structural spec (tagged @N3-S05 @N3-S06 @N3-S07 @N3-S08) | all |

---

## Component hierarchy additions

### RetryBanner (N3-S05)

```
RetryBanner  [data-testid="retry-banner"]
├── message text
└── Retry button  [data-testid="retry-banner-btn"]
```

Rendered inside the active stage view (ProfileView / PlanView / BuildView) when `turnError !== null`.

### SectionPane — failed state extension (N3-S06 + N3-S07)

```
SectionPane  [data-testid="section-pane"]
├── (existing building spinner, artefacts, accept/drop)
├── [NEW] failed notice  [data-testid="section-failed-notice"]   (when status === "failed")
│   ├── message (varies by reason: "missing_files" vs "timeout")
│   ├── Retry button  [data-testid="section-retry-btn"]
│   └── Drop button   [data-testid="section-drop-failed-btn"]
```

The `reason` field from the `section.failed` SSE event is stored alongside status so the
notice copy can distinguish a silent-failure from a watchdog timeout.

### DoneView (N3-S08)

```
DoneView  [data-testid="done-view"]
├── heading
├── accepted sections list
│   └── accepted-section-{id}  [data-testid="done-section-{id}"]  per accepted section
└── ExportButton (prominent, always enabled in done stage)
```

---

## State management

### `turn.error` routing (N3-S05)

The `turn.error` event carries a `stage` field. `App.tsx` already subscribes to SSE via
`useSSE`. New approach: add `turnError: TurnErrorEvent | null` to `AppState`. On `turn.error`,
set it. On `profile.ready`, `plan.ready`, `section.proposed` or `stage.changed`, clear it.

Pass `turnError` as a prop to the active stage view. Each view that can fail (ProfileView,
PlanView, BuildView) renders `<RetryBanner>` when `turnError !== null`.

Retry calls `api.postRetry()` → `POST /turn {}` → clears `turnError` optimistically.

### `section.failed` routing (N3-S06 + N3-S07)

`BuildView` already handles `section.failed` and sets `status: "failed"` on the section.
Extension: also store the `reason` field. Pass `failedReason` to `SectionPane`.

`SectionPane` already receives `section: Section`. Extend to accept `failedReason?: "timeout" | "output_error" | "missing_files"`.

Retry: calls `api.postRetry()` with the section's ID — i.e. `POST /turn { section_id }` (same
as redirect but empty text). Per the API contract, `POST /turn` with empty body re-fires the
last prompt. For section retry, pass `section_id` so the backend knows which section to re-run.

Drop: calls existing `api.postSectionDrop(id)`.

### Done stage (N3-S08)

`App.tsx` already routes `stage === "done"` to `BuildView`. Replace that with `DoneView`
(pass accepted sections from plan state). `DoneView` shows accepted sections in plan order
and the ExportButton. The ExportButton component is already built (N2-S17).

---

## `data-testid` list (QA seam additions)

| testid | Element | Story |
|---|---|---|
| `retry-banner` | RetryBanner root div | N3-S05 |
| `retry-banner-btn` | Retry button inside banner | N3-S05 |
| `section-failed-notice` | Failed-state notice in SectionPane | N3-S06 |
| `section-retry-btn` | Retry button in failed-section pane | N3-S06 |
| `section-drop-failed-btn` | Drop button in failed-section pane | N3-S06 |
| `watchdog-notice` | Distinct notice when reason="timeout" | N3-S07 |
| `done-view` | DoneView root div | N3-S08 |
| `done-section-{id}` | Per accepted section row in DoneView | N3-S08 |

---

## API additions

### `api.postRetry(sectionId?: string): Promise<void>`

Calls `POST /api/turn` with an empty body (to re-fire last stage prompt) or with
`{ section_id }` to retry a specific failed section. This maps directly to the existing
`postTurn` signature — `postRetry` is a thin wrapper for clarity:

```ts
postRetry(sectionId?: string): Promise<void> {
  return this.postTurn("", sectionId);
}
```

Per the API contract: "Retry button calls `POST /turn` with an empty body (re-fires the last prompt)."

---

## Implementation approach

1. **TDD:** Write failing Vitest tests for each component first, then implement to make them pass.
2. **RetryBanner:** Small stateless component. Takes `message: string` and `onRetry: () => void` props. Renders `data-testid="retry-banner"` and `data-testid="retry-banner-btn"`.
3. **SectionPane failed state:** Add conditional branch in existing `SectionPane` for `status === "failed"`. Show notice + Retry/Drop. The `failedReason` prop controls the notice copy.
4. **DoneView:** Renders accepted sections in plan order (filter `plan.filter(s => s.status === "accepted")`). Shows the ExportButton prominently. Does not need to fetch any data — receives `sections` prop from App.
5. **App.tsx wiring:** Manage `turnError` state; pass to views; clear on success events; route `done` to `DoneView`.
6. **Playwright spec:** Single spec file tagged per story; mocks GET /state and SSE via Playwright's `page.route`. Asserts `data-testid` presence for structural gate.

---

## Test plan

### Vitest — RetryBanner.test.tsx (N3-S05)

- Happy path: renders banner with message and Retry button when rendered
- Error path: `onRetry` callback fires on Retry button click
- Null/missing: does not crash when `message` is empty string
- Edge: banner message changes when `message` prop changes

### Vitest — SectionPane.test.tsx additions (N3-S06 + N3-S07)

- Happy path: renders `section-failed-notice` and `section-retry-btn` when `status === "failed"`
- Happy path: renders `watchdog-notice` (distinct copy) when `failedReason === "timeout"`
- Error path: Retry click calls `onRetry` prop with section id
- Drop click calls `onDrop` prop from failed state
- Null/missing: renders normal building/proposed state when no failure (regression guard)

### Vitest — DoneView.test.tsx (N3-S08)

- Happy path: renders `done-view` root with accepted sections in plan order
- Happy path: ExportButton present and enabled
- Edge: empty sections list renders `done-view` without crashing
- Edge: only accepted sections rendered (dropped/proposed excluded)
- Null/missing: `sections` prop is empty array → renders gracefully

### Playwright — error-done.spec.ts

- `@N3-S05`: `retry-banner` and `retry-banner-btn` present in DOM when state has `turn.error` active
- `@N3-S06`: `section-failed-notice`, `section-retry-btn`, `section-drop-failed-btn` present in section pane when section status is `failed`
- `@N3-S07`: `watchdog-notice` present when `section.failed` reason is `timeout`
- `@N3-S08`: `done-view` and `done-section-{id}` present when stage is `done` with accepted sections; ExportButton present

---

## Risks and open questions

1. **Retry API shape:** The contract says "Retry button calls `POST /turn` with an empty body." The existing `postTurn` function requires a `text` argument. Confirm that `POST /turn` with `text: ""` is accepted by the backend as a valid retry signal (same as no-op re-fire). If the backend needs a distinct `POST /retry` endpoint, that is a contract ambiguity blocker. Based on `API_CONTRACT.html` routing note, the existing `/turn` with empty body is the intended path.

2. **Section retry vs turn retry:** For N3-S06, section retry needs to re-run a specific section. `POST /turn` with `{ section_id }` is the mechanism (per the existing `postTurn` signature that already accepts `sectionId`). Confirm this is what the BE N3-S02 story wires up on the backend side.

3. **`turn.error` in BuildView:** The `turn.error` event has a `stage` field but no `section_id`. For the building stage, a `turn.error` is a stage-level turn failure (distinct from `section.failed`). The RetryBanner in BuildView covers this case; `section.failed` covers the artefact-missing case. These are two separate error surfaces — they must not conflict.

4. **`DoneView` vs `BuildView` for `done` stage:** Currently `App.tsx` routes both `building` and `done` to `BuildView`. The `done` stage should route to `DoneView` instead. The `BuildView` sections state is passed to `DoneView` via `App`. Ensure `onSectionsChange` is not needed by `DoneView` (it doesn't accept/drop).

5. **`stage.changed(done)` hydration:** When `stage.changed(done)` arrives, `App.tsx` currently calls `GET /state` to refresh. Sections may have `accepted` status from prior events. Verify the `plan` state in `App` is up-to-date when `done` renders — if not, a `GET /state` call in the `stage.changed` handler ensures it.
