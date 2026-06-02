# Operating Model — Data Buddy

*Handover artefact 3 of 4. Companions: `01_SLICE_PLAN.md` (the three nights and why), `02_STORY_BACKLOG.md` (the stories), `04_QA_PLAN.md` (structural verification).*

This document defines **how the agents work each night** — the cadence, the branching and merge rules, how the lanes run in parallel, what the human review gates, and what happens when something isn't green. It assumes the roles and lane ownership from the backlog header.

---

## 1. The operating principle

Three nights, each a sprint. Every night ends with a **runnable, demoable increment** (the sprint goal from `01_SLICE_PLAN.md`). The agents run development, review, integration, QA, and merge to `develop` overnight; **the human runs a manual code review each morning and that review is the only gate that promotes `develop` → `main`.** `main` is therefore always demoable, and the daily review catches drift while two nights of runway remain.

What makes parallel work safe is the contract discipline: lanes own disjoint parts of the tree (BE → `backend/`, FE → `frontend/`, TL → repo wiring + build tooling + docs), and they integrate only through the published interfaces (`API_CONTRACT.html`, the schemas, the reconciled SSE contract). An agent codes against the contract, not against another agent's in-progress code.

---

## 2. Roles and the merge authority

- **TL** — architecture, cross-lane integration, coordination, and the **review + merge authority** into `develop`. Owns the nightly integration story and adjudicates any contract change. Writes no feature code in `backend/` or `frontend/`.
- **BE** — all of `backend/`.
- **FE** — all of `frontend/`.
- **QA** — the structural DoD gate; nothing merges to `develop` over a failing QA check.

**Internal backend rule (architecture, enforced by TL):** the orchestrator calls the OpenCode client through a narrow interface (`client.prompt(...)` + a normalised event iterator); the state machine never imports `httpx`; the client never imports the orchestrator. This keeps the two BE tracks (orchestration vs OpenCode boundary) independently mergeable.

### Responsibility boundaries (tests · review · the gate)

Writing tests, reviewing PRs, and the QA gate overlap unless two lines are drawn: **altitude** (does this concern one unit, or units meeting?) and **modality** (reading code, vs. running the thing).

| | FE / BE (implementers) | TL | QA |
|---|---|---|---|
| **Tests** | own unit/component tests, ship *with* the story | — (checks they exist + pass) | contract, boundary, recovery, e2e, regression |
| **PR review** | respond to review | **owns** code review + merge to `develop` | — |
| **Integration** | — | **owns** (wire the lanes, smoke that it runs) | — |
| **The gate** | — | — | **owns** structural DoD + regression (gates merge) |
| **Testability seams** | **build** (BE hooks `N1-S20`/`N2-S20`/`N3-S16`, FE `data-testid` `N1-S21`) | — | **consume** to write the gate |

Three principles resolve the overlaps:

- **Tests split by altitude.** The implementer writes tests of their *own unit in isolation* (BE pytest over orchestrator/watchdog/state against the contract; FE component tests that a view renders and wires correctly against fixture data) — these ship with the story and are part of its "done." QA writes everything spanning *more than one lane* — the contract/boundary/recovery assertions, the Playwright e2e, the regression suite. Tie-breaker when unclear: *does it need more than one lane's code running together?* Yes → QA; one lane's internal logic → the author.
- **Review and the gate are the same question, two ways.** TL is the single review-and-merge authority and *reads code* per PR (acceptance met, lane boundaries respected, contract/architecture conformance, author's unit tests present + green). QA isn't a line reviewer; it *runs the thing* after integration (the structural gate + e2e + regression against the assembled slice). Same acceptance criteria, but TL at the PR (static, code-level) and QA at the slice (dynamic, runtime-level). A PR can pass TL review and still fail QA — that is the system working; integration surfaced what no single unit could.
- **Integration sits between them.** TL's nightly integration story is "make the merged lanes run and smoke the path," not the formal verification; QA then proves the DoD. The full chain is the cadence in Section 3.

Overlaps, resolved: **FE ↔ BE** never share files — they meet only at the contract, each tests *its own side*, and QA tests that the two sides meet. **TL ↔ QA** both verify acceptance, but TL by reading code before merge and QA by running behaviour after integration — different modality, different point in the cycle.

---

## 3. The nightly cadence

Each night runs the same loop:

1. **Kick-off (human, start of night).** Release the night's stories (already scoped in the backlog) plus any carry-over notes. Read `DEV_STATUS.md` for where the last night left off, and confirm the night's **t0 startable set** (Section 5) so every agent can pick up work immediately.
2. **Develop (agents, parallel).** Each agent takes startable stories on a short-lived feature branch, working its lane against the contracts. As dependencies clear, the next stories in each track unlock. Agents consult `DEV_STATUS.md` to see what is merged, in flight, blocked, or free to grab.
3. **Review (TL/reviewer, continuous).** As a story opens a PR into `develop`, it is reviewed against its **acceptance criteria** and the **lane boundaries** (no out-of-lane file edits, no scope creep beyond the story's "out of scope"). Approve or request changes.
4. **Integrate (TL).** Once a night's lane stories are merged to `develop`, TL runs that night's **integration story** (`N1-S18` / `N2-S18` / `N3-S13`): assemble the slice, resolve wiring/contract mismatches, and get the end-to-end path running.
5. **QA (QA).** Run the night's **structural DoD** (`04_QA_PLAN.md`) against the integrated slice, and re-run the accumulated regression checks. Log any defect to `QA_LOG.md` with a regression check added (Section 8). A green check is the precondition for the slice being considered done.
6. **Merge to `develop`.** Reviewed + QA-green work lands on `develop`. Agents never touch `main`. TL updates `DEV_STATUS.md` as part of merge/integration.
7. **Morning review (human, the gate).** Review the diff on `develop`, run the **morning demo script** (Section 6), and read the three living docs — `DEV_STATUS.md`, `QA_LOG.md`, and any `Proposed` ADR entries from overnight. Accept or reverse each pending ADR decision. If satisfied, promote `develop` → `main` and tag the sprint. If not, the issues become carry-over for the next night.

Two review layers, deliberately: the **overnight agent review** (step 3) keeps lane discipline and acceptance; the **morning human review** (step 7) is the judgment gate — analysis quality, scope, and the decision to promote.

---

## 4. Branching and merge model

- **`main`** — always demoable/submittable. **Only the human promotes to it**, once per morning, after review.
- **`develop`** — the nightly integration branch. Agents merge here after review + QA.
- **Feature branches** — one per story, short-lived, named `feat/<story-id>-<slug>` (e.g. `feat/N1-S08-live-events`). Branch from `develop`, merge back to `develop`.

**A story may merge to `develop` only when:** its acceptance criteria are met · it stayed within its lane (disjoint files) · it was reviewed · it doesn't break the build · its declared dependencies are already on `develop`.

**Conflict ownership.** Because lanes own disjoint directories, cross-lane merge conflicts should be rare by construction. The shared touch-points are the contracts and the `Makefile`; **any change to a contract is a TL decision**, published before dependents build against it (this is exactly why `N1-S07`, the reconciled SSE contract, is a blocking first deliverable). TL adjudicates any conflict that does arise.

---

## 5. Parallelisation and scheduling

Night 1 is the only night with a long serial spine; Nights 2 and 3 are wide-and-shallow and parallelise well — which is what makes the BE-heavy load tractable. For each night: the **t0 set** (startable the moment the night opens), the **parallel tracks**, the **critical path**, and the **agent allocation** that pays off.

### Night 1 — critical-path-bound

- **t0 set:** `N1-S01` scaffold (TL) and `N1-S07` reconciled contract (BE). Doing `S07` first is the highest-leverage move of the night — it gates all SSE work (`S08`, `S10`, `S14`).
- **Tracks (once `S01` lands):**
  - *BE spine (serial — the long pole):* `S02 → S03 → S06 → S08 → {S09 ∥ S11} → S12`. Irreducibly sequential.
  - *BE side-branches (parallel to the spine):* `S05` (after `S03`) and `S10` (after `S02`+`S07`), plus `S07` itself — a second BE agent's work.
  - *FE lane (parallel to all backend):* `S13 → S14 → {S15 ∥ S17 → S16}`. The whole UI builds against the contract while the real backend is built; they meet at integration.
- **Critical path:** `S01 → S02 → S03 → S06 → S08 → S09/S11 → S12 → S18 → S19`.
- **Agent allocation:** 1 TL · **2 BE** (spine + contract/branches) · 1–2 FE · QA light. More than 2 BE gains nothing against the serial spine. TL is idle mid-night — spend it on review (step 3).

### Night 2 — wide and shallow

- **t0 set (Night 1 merged):** `S01`, `S02`, `S06`, `S09`, `S14` (BE) and all three FE screens `S15`, `S16`, `S17`. The section-build path (`S06`) is independent of the plan path (`S02`/`S03`) — two parallel BE tracks that join only at `S05`.
- **Tracks:**
  - *Plan track:* `S02 → S03 →` then backend-only endpoints `S04 ∥ S10 ∥ S11` fan out (each needs only `S03`).
  - *Section track:* `S06 → S07 → S08`, plus `S12` (redirect) off `S06`.
  - *Independent leaves at t0:* `S09` (frontmatter), `S14` (file serving).
  - *FE:* all three screens start at t0 against the contract; two FE agents split them.
- **Critical path:** `S02 → S03 → S05 → S18 → S19` (≈ half Night 1's depth).
- **Agent allocation:** this is where **more BE agents genuinely help** — the plan track, the section track, and the three backend-only endpoints are mutually independent. 1 TL (integration, back-loaded) · **2–3 BE** · 2 FE · QA.

### Night 3 — wide and shallow, TL busy early

- **t0 set (Nights 1–2 merged):** `S01`, `S02`, `S03` (BE) · `S06` (FE) · `S09`, `S10`, `S12` (TL) — seven independent starts across all four roles.
- **Tracks:**
  - *BE robustness:* `S02`, `S03` independent at t0; `S01 → S04` the only short chain.
  - *FE error/done UIs:* `S05` (needs `S02`), `S06 → S07`, `S08` (needs `S01`) — largely mutually independent.
  - *TL packaging:* `S09 ∥ S10 ∥ S12` at t0, then `S11` after `S09`. The one night TL has parallel work up front.
- **Critical path:** `S01 → S04/S08 → S13 → S14 → S15`.
- **Agent allocation:** 1 TL (busy early) · 2 BE · 2 FE · QA.

### The pattern across nights

Every night has the same shape — an early gate, a convergence, a verification. Night 1's early gate is `S07`; Nights 2–3 have no single gate because so much is startable at t0. The **convergence is always the TL integration story**, where every lane meets — the one place a single slow story stalls everyone, so protect it. QA always trails integration.

The **cross-night gate** is the real schedule risk: Night 2's plan track needs Night 1's `S04`/`S09` merged; the section track needs `S09`. A slipped Night-1 spine delays Night 2's t0, not just Night 1. The backend spine is the true critical path across all three nights — which is why it is front-loaded.

---

## 6. Morning demo scripts (the human review walk-through)

These are the **human** verification each morning — the eyeball demo. QA's automated structural assertions for the same DoD live in `04_QA_PLAN.md`; both forms must pass.

### Night 1
1. From a clean clone: `make install`, then `make dev`.
2. Open the app, upload the churn CSV, enter an aim.
3. Watch the activity rail stream the profiling turn; confirm the profile renders (shape strip + per-column rows).
4. Submit one re-profile via the bottom bar (the second turn); confirm it completes — or recovers via a fresh session without hanging.
5. Refresh the browser; confirm the UI re-hydrates to the same state.
*Pass:* the spine runs end-to-end and a second turn recovers.

### Night 2
1. `make dev`; reach the plan stage.
2. Inline-edit a section's title/hypothesis and reorder or drop one — confirm it is instant with no agent activity.
3. Revise the plan via the bottom bar (an agent turn); then accept the plan.
4. Watch one section build: a script is written and run, a chart appears, an interpretation renders.
5. Redirect the section via the bottom bar; watch it discard and rebuild.
6. Accept the section; export the brief-so-far; open the `.md`.
*Pass:* the interaction loop, the redirect, and export all work.

### Night 3
1. `make clean`, then `make run` from a clean checkout.
2. Build a full multi-section brief on the churn CSV — accept each section, confirm the next triggers, reach `done`.
3. Repeat the core path on a **second dataset** (any CSV + aim) to confirm generality.
4. Induce a failure (e.g. a section that errors) and recover it via the retry banner / Retry–Drop.
5. Export the full brief; open the multi-section `.md`.
*Pass:* a complete, robust, submittable prototype.

---

## 7. Blockers and the buffer

- **A single story isn't green.** It does not merge; it carries over. The integration story integrates what *is* green, and the slice DoD may be partially met for that morning — noted for the next kick-off.
- **A whole night's DoD slips.** The buffer absorbs it. Drop order, most-droppable first, so the core loop is never sacrificed: Night-3 polish → the 4b redirect (`N2-S12`, reuses Night-2 machinery) → second-dataset generality (`N3-S14` step 3) → **never** the core build loop.
- **An agent hits something it cannot resolve** — a contract ambiguity, a blocked dependency, or a new OpenCode runtime surprise not covered by the spike. It escalates to **TL, who owns unblocking**: the priority is to keep moving, not to stall for the morning. TL chooses the **spec-closest** workaround, records it as a new **ADR entry marked `Proposed — pending review`** (decision + rationale), and flags it for the morning. The human accepts or reverses it at review; keeping deviations minimal and spec-anchored makes a reversal cheap.
  - **Blast radius matters.** A local guess (an ambiguous field, a minor event quirk) is decided and documented, full stop. A guess that changes a **shared contract** (the SSE mapping, API shapes, schemas) is still decided now — but TL must **republish the change to dependent lanes immediately** (update the reconciled contract / `API_CONTRACT` and ping FE/BE), or one blocker becomes three as other agents keep building against the old shape.
  - **Only a genuinely irreversible, high-blast-radius call with no spec-preserving path** waits as a hard Blocker for the morning. That is the exception, not the default.
- **Cross-night dependency missed.** If a Night-N story didn't merge, the dependent Night-N+1 stories simply aren't in that night's t0 set; agents work the still-startable subset and the dependency is first priority at kick-off.

---

## 8. Living documents (state, decisions, defects)

The backlog is the static plan — *what to build*. Three living documents carry the *dynamic* state the overnight process generates. Each has a **single writer** to prevent drift, and each is a projection of ground truth (git, QA runs), not a competing source of it.

### `DEV_STATUS.md` — owner: TL

The progress board. The backlog says what to build; this says where we are. TL updates it as part of the review/merge/integrate cycle (it already knows the truth at each step), so it stays in sync with `develop`. Agents read it, never write it.

It holds, per night: each story's status (Backlog → In Dev → In Review → In QA → Merged / Blocked), what is currently on `develop`, the **set of stories free to grab right now**, active blockers, and a short list of the overnight **ADR decisions** (from Section 7) so an agent sees "decision X was made — build accordingly" without reading the full ADR.

### `ADR.md` — owner: TL

The decision record. Pre-existing accepted ADRs plus any **overnight unblocking decisions**, each appended as `Proposed — pending review` with decision + rationale. The human flips each to `Accepted` or `Superseded` at the morning review. This is the audit trail for everything that deviated from spec and why.

### `QA_LOG.md` — owner: QA

The defect ledger, and the seed of the regression suite. Every QA failure is logged with: symptom, the story/area, root cause or fix, and — critically — **the regression check added** so the bug cannot silently return. A defect found Night 1 becomes a permanent assertion guarding Nights 2–3. The mechanics of how a logged issue graduates into the formal regression set live in `04_QA_PLAN.md`; this file is the running record that feeds it.

Together these close the regression loop: TL's overnight decisions are visible to every agent and to the morning review; QA's defects become standing checks rather than one-off fixes.

---

## 9. Operational notes

- **Runtime.** Agents have live OpenAI credentials and pinned OpenCode **v1.15.10** (OAuth, `providerID: "openai"`), so every DoD is verified against the real runtime overnight, not a mock. The version stays pinned.
- **Cost and rate limits.** Section builds run real model turns and can consume tokens or hit provider rate limits over a long night. Keep auto-retries bounded (`N3-S02`), and use the small churn CSV for routine verification — reserve the second dataset for the Night-3 generality check.
- **Spike wins.** Where the spike and the spec disagree on OpenCode behaviour, the spike is authoritative (`opencode-spike/SPIKE_REPORT.md`); the resolution is captured in the reconciled contract and, if it was an overnight call, recorded in the ADR.
- **Scope guardrail.** The global out-of-scope list in the backlog header travels with every story. Out-of-scope work is a review rejection, not a nice-to-have.

---

## 10. One cycle, in a sentence

Kick off with the t0 set → agents build their lanes in parallel against the contracts → TL reviews and integrates → QA gates on the structural DoD → merge to `develop` → the morning human review runs the demo script and promotes to `main`.
