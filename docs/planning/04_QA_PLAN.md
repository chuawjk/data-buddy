# QA Plan — Data Buddy

*Handover artefact 4 of 4. Companions: `01_SLICE_PLAN.md` (the three nights), `02_STORY_BACKLOG.md` (the stories + structural acceptance), `03_OPERATING_MODEL.md` (cadence, the QA gate, `QA_LOG.md`).*

This document defines **what QA verifies, how it verifies output that is nondeterministic by construction, the per-night merge gate, and how a defect becomes a permanent regression check.** QA owns the gate: nothing merges to `develop` over a failing QA check.

---

## 1. What QA verifies — and what it doesn't

The agent's output is nondeterministic — the Python it writes, the chart it renders, and the interpretation it drafts vary run to run, even on the same dataset. So QA **cannot** assert that an analysis is *correct* or an interpretation is *good*. That judgment is the human morning review (`03_OPERATING_MODEL.md` §6).

What QA asserts instead is **shape, contract, and behaviour** — the invariants that must hold regardless of what the model produced. The DoD therefore has two forms, and both must pass each night:

- **Human review demo** (operating model §6) — the eyeball walk-through; judges analysis quality and scope.
- **Structural gate** (this document) — automatable assertions; gates the merge.

### The line between structural and semantic

| QA asserts (structural — gates merge) | QA does **not** assert (semantic — human's call) |
|---|---|
| `profile.json` validates against the profile schema | whether the profile's flags are insightful |
| the section's `.py` exists and exits 0 | whether the analysis is the *right* analysis |
| `charts/<id>.png` exists, is non-empty, is a valid PNG | whether the chart is well-chosen or readable |
| `sections/<id>.md` has valid frontmatter + a non-empty interpretation | whether the interpretation is *true* or *well-argued* |
| `state.json` transitioned `proposed → accepted` on accept | whether accepting was the right call |
| a backend-only endpoint made **zero** OpenCode calls | — |
| the UI renders one row per column in `profile.json`; a clicked control changes the rendered state | whether the layout, spacing, or visual design is good |
| the retry banner appears in the DOM on `turn.error` | whether the error copy is well-worded |

### Structural proxies for semantic adequacy

Where a minimum semantic floor matters, QA uses **structural proxies** that don't require judging quality: the `.md` interpretation is non-empty and above a token floor; the `.py` actually references real column names drawn from `profile.json` (not invented ones); the chart file exceeds a trivial size threshold. These catch an empty or hallucinated section without grading the analysis.

---

## 2. Verifying nondeterministic output

**No golden outputs.** QA never diffs agent output against a fixed expected file. The input is pinned (the churn CSV) so runs are comparable, but the output is expected to vary; QA asserts **invariants that hold for any valid output**, grouped into seven categories:

1. **Contract & schema** — `profile.json` / `plan.json` validate against their JSON schemas; REST responses match `API_CONTRACT.html`; SSE events match the reconciled contract (`SSE_CONTRACT.md`) shapes.
2. **State machine** — legal stage transitions only; `state.json` written atomically (`state.tmp.json` → `os.replace`); a refresh re-hydrates to the same stage; writes never occur mid-turn.
3. **Filesystem / triplet** — for a built section, all three of `analyses/<id>.py`, `charts/<id>.png`, `sections/<id>.md` exist; the `.py` exits 0; the `.png` is a valid non-empty image; the `.md` frontmatter parses and names the chart file.
4. **Boundary (ADR-003)** — backend-only operations (`/plan/update`, `/plan/accept`, `/section/:id/accept`, `/section/:id/drop`, `/export`, `/file`) make **zero** OpenCode calls and return synchronously; agent-driven operations (`/setup`→profiling, planning, section build, `/turn`) return `204` immediately and progress via SSE.
5. **Recovery (ADR-002)** — a second turn against a session completes; a forced stall aborts, falls back to a fresh session, and does not hang; the new session ID is persisted.
6. **Failure injection** — a section that produces no `.md` emits `section.failed`; a structured-output/provider failure emits `turn.error`; a retry recovers.
7. **UI rendering & interaction (browser)** — the rendered DOM reflects backend state (the correct stage view, data-driven content, live activity), user actions wire to the right endpoints, and the error UIs appear on their matching events. Asserted with Playwright against the running app. As everywhere else, QA asserts that the UI *correctly reflects state and wires actions* — never that it looks good; visual design is the human morning review. Because the FE consumes the same contracts, these assertions are data-driven and deterministic (e.g. "renders N column rows where N = columns in `profile.json`") even though the content varies.

**Cheap vs expensive checks.** Most assertions (categories 1–3) run against artefacts *already produced* by a single live turn — they are cheap and fully deterministic to check. Only a few assertions need to *drive* fresh turns. So a QA run does one real profiling/build pass on the small churn CSV, then asserts heavily against the resulting artefacts, rather than driving many turns.

### Test seams QA needs (now backlog stories N1-S20, N2-S20, N3-S16)

Failure and recovery paths can't be triggered reliably by hoping the model misbehaves, and waiting for a real watchdog timeout is too slow for a per-night suite. Three small, opt-in seams make categories 5–6 deterministic and fast:

- **Configurable watchdog timeout** — an override (e.g. env var) so QA can set the no-events timeout to ~2s in tests; production stays at 60s.
- **Forced-failure hooks** — opt-in flags on the OpenCode client (e.g. `QA_FORCE_STALL`, `QA_FORCE_TURN_ERROR`) that drive the abort / `turn.error` branches without depending on model behaviour or spending tokens.

The **OpenCode-call spy** — a counter/log on the client's request path — is how category 4 asserts "zero agent calls": exercise a backend-only endpoint, assert the spy count is unchanged.

**FE testability (the parallel seam):** browser assertions need stable selectors, so the FE adds `data-testid` attributes to the elements QA targets — stage containers, the profile column rows, the section pane's code/chart/interpretation parts, the action buttons (accept/drop/export), the bottom-bar input, and each error surface (retry banner, failed-section controls, watchdog notice). This is the FE counterpart to the BE hooks above; treat it as a lane convention, or track it as a small FE story if you want it explicit in the backlog.

---

## 3. The structural gate, per night

Each night's gate corresponds to the QA story in the backlog (`N1-S19`, `N2-S19`, `N3-S14`/`N3-S15`) and runs against the integrated slice after TL's integration story. All assertions use the fixed churn CSV unless noted.

### Night 1 — walking skeleton + recovery

- Given a clean checkout, when `make install && make dev` runs, then both servers start and the app loads with no manual steps.
- Given a churn-CSV upload + aim, when setup completes, then `workspace/data/<dataset>.csv` and an initial `state.json` exist, and stage is `setup` then auto-advances to `profiling`.
- Given the profiling turn completes, when `profile.json` is read, then it validates against the profile schema (`shape{rows,columns}`, `columns[{name,type,flags,summary}]`).
- Given the SSE stream, when a turn runs, then exactly **one** OpenCode `/event` connection is open, and events for a non-current `sessionID` are not forwarded.
- Given a `GET /state` after profiling, when the response is read, then it matches `API_CONTRACT.html` and reflects the persisted profile.
- Given a browser refresh (simulated by a fresh `GET /state`), when re-hydrated, then the stage and profile are unchanged.
- Given a second profiling turn (re-profile), when it runs, then it completes; and given `QA_FORCE_STALL`, when the turn stalls, then the watchdog aborts, a fresh session is created, the new ID is persisted, and no call hangs past the test timeout.

**Browser (Playwright):**
- Given the app at `setup`, when rendered, then the upload control and aim field are present and submit is disabled until both are provided.
- Given a profiling turn, when events stream, then the activity rail shows activity items in the DOM (not empty).
- Given `profile.ready`, when received, then the profile view renders one row per column in `profile.json` and the shape strip shows the row/column counts.
- Given a real browser reload after profiling, when the page re-renders, then the DOM shows the profiling stage with the profile populated — the live hydration test for ADR-007 (stronger than the `GET /state` check above).

### Night 2 — interaction loop + one section + export

- Given profiling accepted, when planning runs, then `plan.json` validates against the plan schema (`sections[{id,title,hypothesis}]`, 3–6 entries) and each section is recorded `proposed`.
- Given an inline plan edit / reorder / drop / add (`/plan/update`), when it runs, then `plan.json` + `state.json` change synchronously **and the OpenCode-call spy count is unchanged**.
- Given `/plan/accept`, when called, then stage transitions `planning → building` and section 1 is triggered.
- Given a section build completes, when the workspace is inspected, then `analyses/sec_01_*.py` exists and exits 0, `charts/sec_01_*.png` is a valid non-empty PNG, and `sections/sec_01_*.md` has valid frontmatter naming the chart and a non-empty interpretation (proxy: references ≥1 real column from `profile.json`).
- Given the build idles without an `.md`, when detected, then `section.failed` is emitted (use a forced-failure fixture); given transient bash errors the agent recovers, then `section.failed` is **not** emitted.
- Given a mid-build redirect (`/turn`), when it runs, then prior drafts are discarded, a fresh triplet is produced, and a new `section.proposed` is emitted.
- Given `/section/:id/accept` and `/section/:id/drop`, when called, then status transitions correctly **with zero OpenCode calls**.
- Given `/export` after one accepted section, when called, then it returns valid Markdown containing that section and excluding dropped/proposed ones, **with zero OpenCode calls**.

**Browser (Playwright):**
- Given a proposed plan, when rendered, then the plan view shows one row per section with its title and hypothesis.
- Given an inline edit or drop performed in the UI, when actioned, then it calls `/plan/update` and the OpenCode-call spy is unchanged (Playwright + spy together).
- Given `section.proposed`, when rendered, then the section pane shows the code, an `<img>` whose `src` resolves via `GET /file`, and a non-empty interpretation.
- Given Accept or Drop clicked in the UI, when actioned, then the rendered section status changes and the spy shows no OpenCode call.
- Given a bottom-bar redirect submitted in the UI, when it runs, then live activity reappears in the rail and the section re-renders on the new `section.proposed`.
- Given ≥1 accepted section, when Export is clicked, then a `.md` is delivered; with none accepted, the control is disabled.

### Night 3 — scale, robustness, deliverable

- Given an accepted section, when the loop runs, then the next `proposed` section triggers; after the last, stage transitions to `done` and `stage.changed(done)` is emitted; dropped sections are skipped.
- Given `QA_FORCE_TURN_ERROR`, when a turn fails, then `turn.error` is emitted with a retryable flag, the retry banner path is reachable, and a retry recovers.
- Given a forced stall mid multi-section run, when the watchdog fires, then recovery occurs without corrupting `state.json` or the section sequence.
- Given a **second dataset** (a different CSV + aim), when the full loop runs, then it reaches `done` and exports — proving generality beyond the churn CSV.
- Given a cold `make run` on a clean checkout, when the loop runs end-to-end, then it works against the built bundle (not the dev server) and `make clean` resets the workspace.
- Given the full brief, when `/export` is called, then it returns a valid multi-section Markdown document in plan order.

**Browser (Playwright):**
- Given `QA_FORCE_TURN_ERROR`, when the turn fails, then the retry banner appears in the DOM and clicking Retry triggers a retry that recovers.
- Given a forced section failure, when `section.failed` arrives, then the Retry / Drop controls appear; clicking Drop advances the loop.
- Given a watchdog timeout, when it fires, then the timeout surface appears with recovery options (no silent hang in the UI).
- Given `stage.changed(done)`, when received, then the done view renders all accepted sections with the export action present.
- Given the second dataset, when the loop runs in the browser, then the same views render correctly — generality at the UI level, not just the backend.

---

## 4. Regression: from defect to standing check

The defect ledger (`QA_LOG.md`, QA-owned) is not a diary — it is the **seed of the regression suite**. The rule that prevents recurrence:

> **A defect is not closed until a regression check exists that would have caught it.** (Test-first on bugs.)

### `QA_LOG.md` entry schema

Each entry: an **ID** (`QA-NN`), the **night** found, **symptom** (observed behaviour), **area / story** (e.g. `N2-S08`), **root cause** (once known), **fix reference** (PR/commit), **regression check added** (the named assertion), and **state**.

### Graduation states

- **Open** — reproduced and logged; symptom + area recorded.
- **Fixed** — fix merged *and* a regression check written that fails without the fix and passes with it.
- **Closed** — the check is green in the standing suite.

A defect cannot reach **Closed** while only **Fixed**; the check must be in the suite and passing. The suite **re-runs every night before merge** (`03_OPERATING_MODEL.md` step 5), so a bug fixed Night 1 is guarded through Nights 2–3.

---

## 5. The regression set (cumulative)

The suite grows each night and always runs in full. By end of night it contains, cumulatively:

**After Night 1 (the spine + recovery):**
- one and only one OpenCode `/event` subscription open during a turn;
- `profile.json` schema-valid;
- `state.json` atomic-write integrity (no partial file under a simulated mid-write kill);
- refresh re-hydration is lossless;
- second-turn completion; watchdog stall → fresh-session recovery with persisted ID;
- *browser:* profile view renders one row per column; a real reload shows the correct stage with data (DOM hydration).

**After Night 2 (adds the loop):**
- `plan.json` schema-valid, 3–6 sections;
- backend-only ops (`/plan/*`, `/section/*`, `/export`, `/file`) make zero OpenCode calls (the spy invariant);
- full section triplet present, `.py` exits 0, `.png` valid, `.md` frontmatter valid + non-empty + references real columns;
- `section.failed` fires on a missing triplet and **not** on recovered transient errors;
- redirect discards drafts and rebuilds;
- export ordering correct, dropped sections excluded;
- *browser:* section pane renders code + chart (via `GET /file`) + interpretation; backend-only UI actions change rendered state with zero OpenCode calls.

**After Night 3 (adds scale + robustness):**
- sequential loop reaches `done`, skips dropped;
- `turn.error` emitted + retry recovers;
- watchdog recovery across a long multi-section run leaves state uncorrupted;
- generality: the full loop succeeds on a second dataset;
- cold `make run` from clean completes; `make clean` resets;
- *browser:* the three error UIs (retry banner, failed-section controls, watchdog notice) appear on their events and recover; the done view renders;
- plus every defect-derived check graduated from `QA_LOG.md`.

This cumulative set **is** the Night-3 full regression (`N3-S14`).

---

## 6. Datasets and fixtures

- **Churn CSV** — the primary fixture; small, fast, used for routine verification every night.
- **Second dataset** — a structurally different CSV (different columns, types, size) used only for the Night-3 generality check, so the pipeline isn't overfit to churn.
- **Broken fixtures** — a malformed/empty CSV and a forced-failure path (via the test hooks in §2) to drive the `section.failed` / `turn.error` branches deterministically without relying on the model.

---

## 7. Tooling and runtime

- **Backend / contract assertions:** a `pytest` suite under `qa/` — schema validation with `jsonschema`, REST shape checks against `API_CONTRACT.html`, the OpenCode-call spy, `state.json` integrity, SSE-shape assertions against `SSE_CONTRACT.md`.
- **Browser end-to-end (FE):** **Playwright** drives the app under `make dev` (plus a smoke pass under `make run`), asserting DOM rendering, state reflection, action wiring, and error-UI appearance — structure and behaviour, never visual design. It runs against the **live** app so DOM assertions sit on real data (they're data-driven, so deterministic despite varying content); error-state UIs are driven into view by the BE forced-failure hooks (`N2-S20`, `N3-S16`), and backend-only UI actions are cross-checked with the OpenCode-call spy. Selectors target the `data-testid` attributes (the FE seam in §2) to stay robust.
- **Failure / recovery:** driven by the configurable watchdog timeout and the forced-failure hooks (§2) — fast and token-free.
- **Suite layout:** `qa/structural/` (per-night backend gate), `qa/e2e/` (Playwright specs), `qa/regression/` (the cumulative standing set), `qa/fixtures/` (datasets + broken inputs), `qa/demo/` (the human demo scripts from operating model §6).
- **Runtime / cost:** keep one real live turn per check group and assert against its artefacts; reserve the second dataset for Night 3; keep auto-retries bounded so a flaky turn can't run up token spend overnight.

---

## 8. The gate, in a sentence

QA asserts shape, contract, and behaviour — never analysis quality — runs the per-night structural gate plus the full accumulated regression suite against the integrated slice, and every defect it finds becomes a standing check before it is allowed to close.
