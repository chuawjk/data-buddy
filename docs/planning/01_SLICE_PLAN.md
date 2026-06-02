# Slice Plan — Data Buddy

*Handover artefact 1 of 4. Companions: `02_STORY_BACKLOG.md`, `03_OPERATING_MODEL.md`, `04_QA_PLAN.md`.*
*Source-of-truth inputs: `WORKFLOW_ORCHESTRATION.md`, `ADR.md`, `C4_ARCHITECTURE.html`, `API_CONTRACT.html`, the mockups, and `opencode-spike/` (spike report + captured event shapes).*

*Data Buddy is the app described as the "co-work brief" tool in the locked design docs (`C4_ARCHITECTURE.html`, `ADR.md`, the mockups); those predate the name and still use the old terminology.*

---

## Revision note (v2)

Changes from v1, following review:
- **Execution environment fixed.** The dev and QA agents are issued live OpenAI credentials and a pinned OpenCode binary, so every DoD is verified against the real agent runtime — not a mock. This is what makes "risk retired early" true rather than deferred.
- **Night 1 scope unchanged** (per direction; buffer absorbs the load), with **one addition**: a thin second profiling turn so the watchdog/fresh-session recovery is *exercised the night it is built* instead of first tested in Night 2. If you'd rather keep Night 1 to a single turn and verify recovery in Night 2, that one item reverts cleanly.
- **Spec-vs-spike reconciliation is now a blocking, early Night 1 deliverable** that republishes the SSE-event contract the frontend codes against, closing the mismatch hazard.
- **Night 3 rebalanced.** Export (trivial, backend-only) and the 4b mid-build redirect (reuses Night 2's section machinery) moved into Night 2, so the two interview-relevant interactions are de-risked earlier and Night 3 is left as scaling + failure-handling + packaging.
- **Generalization check added** to Night 3 (a second dataset), since Nights 1–2 use only the churn CSV.

---

## Purpose

This document defines **how the build is sliced across three nights** and **why those cut lines**. It is the spine the other three artefacts hang off: the backlog decomposes these slices into stories, the operating model defines the nightly cadence that delivers them, and the QA plan verifies each slice's Definition of Done.

It does **not** contain story-level acceptance criteria, branch/merge mechanics, or test cases — those live in the companion docs.

---

## Shaping principle

The build is sliced **vertically along the four-stage machine** (Setup → Profiling → Plan → Section build), not horizontally by layer. The naive horizontal cut — backend Night 1, frontend Night 2, integrate Night 3 — is rejected because nothing runs end-to-end until the last night, so misalignment surfaces too late for the daily review to catch it.

Three properties follow from vertical slicing, and they are the reason for it:

1. **Every morning review is a runnable increment.** Each night ends with something that can be driven end-to-end through one command, exercising a path that did not work the night before. The daily manual review inspects working function, not a half-built layer.
2. **Risk is front-loaded and decreases monotonically.** The first slice is a *walking skeleton* that pierces the scariest integration boundary — the OpenCode agent runtime — with the thinnest viable functionality. The spine is proven Night 1, the human-in-the-loop interaction loop Night 2, scaling and hardening Night 3.
3. **The most droppable work is last.** If time slips, it slips into Night 3 (scaling, error handling, packaging, the write-up), which protects the core loop already standing from Nights 1 and 2.

The single largest technical risk is the OpenCode boundary, and the spike confirms it: the runtime's real event semantics diverge from the spec in several places (file writes via `apply_patch` not a `write` tool; text streaming via `message.part.delta` not `part.delta`; a three-state tool lifecycle; several undocumented event types), and there is a reproduced stuck-turn bug where the second prompt to a session hangs indefinitely and only a fresh session recovers it. Slice 1 deliberately drives real prompts through this boundary — including a second turn — so the boundary, *and its recovery path*, are de-risked on Day 1.

---

## The three slices at a glance

| Night | Theme | Spine proven | Morning review (one-command demo) |
|-------|-------|--------------|-----------------------------------|
| 1 | Walking skeleton through Profiling (+ second-turn recovery check) | React → FastAPI → OpenCode → SSE → `state.json` → React, **plus** watchdog/fresh-session recovery | `make dev`, upload churn CSV + aim, watch live profiling, profile renders; submit one bottom-bar re-profile (second turn); refresh tab → re-hydrates |
| 2 | The interaction loop: Plan + one fully-interactive Section + Export | Structured plan + first file-triplet build + accept/drop + 4b redirect + export | Accept a plan, watch one section build, redirect it mid-build and watch it rebuild, accept it, export the brief-so-far |
| 3 | Scale, robustness, and the deliverable | Multi-section loop + three error surfaces + `make run` | Full multi-section brief (incl. a second dataset), an induced failure recovered, export, runs via `make run` from clean |

Roles referenced throughout: **Tech Lead** (architecture, cross-lane integration, coordination, review/merge — no feature code), **Backend Engineer** (all of `backend/` — orchestration, every endpoint, the OpenCode boundary), **Frontend Engineer** (the React SPA), **QA** (per-slice DoD verification). Story-level ownership is authoritative in `02_STORY_BACKLOG.md`.

---

## Slice 1 — Walking skeleton through Profiling

**Goal.** Prove the entire pipe end-to-end with the thinnest viable functionality: a user uploads a CSV and an aim, a genuine profile produced by OpenCode renders in the UI driven by live SSE, and a second turn exercises the recovery path.

**The path this slice lights up.** Setup (backend-only: save CSV, init `state.json`, start `opencode serve`, create session) → auto-advance → Profiling (agent turn: profile prompt → `json_schema` structured output → `profile.json` written) → SSE events forwarded to the SPA → ProfileView renders the shape strip and per-column rows; ActivityRail shows live tool activity → one bottom-bar re-profile (a **second** turn against the session) overwrites `profile.json`, exercising the watchdog/fresh-session recovery.

**Workstreams (component-level; stories in the backlog).**
- *Tech Lead:* repo scaffold and `Makefile` (`install`, `dev`); then integrate the slice end-to-end and gate the merge.
- *Backend Engineer:* **the blocking spec-reconciliation deliverable first** (see cross-slice notes) — publishes the corrected SSE-event contract before any handler is written; then the FastAPI app skeleton + internal event bus; `state_manager` with atomic writes (`state.tmp.json` → `os.replace`) + `GET /state`; orchestrator skeleton (setup → profiling); the setup endpoint; `opencode_client` (httpx + httpx-sse) with the **single persistent `GET /event` subscription** (ADR-006) filtered by session; session create (ADR-002); profile prompt + structured output (ADR-004); the SPA-facing `GET /events` transport; the re-profile turn; **the watchdog + abort + fresh-session fallback** (ADR-002).
- *Frontend Engineer:* Vite + TypeScript + Tailwind scaffold; App shell; `useApi` and `useSSE` hooks (built against the *reconciled* event contract); SetupView (upload + aim); ProfileView (renders from `profile.json`); a minimal profile bottom bar (the re-profile input); ActivityRail. Thin view, hydrates from `GET /state` (ADR-007).
- *QA:* demo script 1; DoD verification including the recovery path on the re-profile; confirm `make clean` resets between runs.

**Anchored decisions.** ADR-002 (session + watchdog), ADR-004 (structured output), ADR-006 (persistent SSE), ADR-007 (thin-view frontend). These four *are* the spine this slice proves.

**Explicitly deferred from this slice.** No plan stage, no section build, no accept/drop, no section redirect, no export, no error-banner UI. Single dataset (the churn CSV). The watchdog/recovery machinery is built and exercised, but the *user-facing* error surfaces are Night 3. `make run` (static-bundle serving) is Night 3; this slice uses `make dev` only.

**Definition of Done (demoable increment).** From a clean checkout: `make dev`, open the app, upload the churn CSV with an aim, watch profiling activity stream live, see the profile render. Submit one bottom-bar re-profile and confirm the second turn completes (and, if it stalls, recovers via a fresh session without hanging the demo). Refresh the browser and confirm the UI re-hydrates from `state.json`.

**Why the second turn is in Night 1.** The stuck-turn bug fires on the *second* prompt to a session, not the first. A single profiling turn would build the watchdog/fresh-session fallback but never test it — untested safety code sitting in the heaviest night. Adding one bottom-bar re-profile makes the recovery path verifiable the night it is written.

---

## Slice 2 — The interaction loop: Plan + one fully-interactive Section + Export

**Goal.** Extend the spine into the product's core value: the agent proposes a structured plan the user can shape, then builds one section as a real file triplet that the user can accept, drop, or redirect mid-build — and can export what exists so far.

**The path this slice lights up.** Profiling idle → auto-advance → Plan proposal (agent turn: plan prompt → `json_schema` → `plan.json`; user edits inline or via the bottom bar; accepts plan) → Section build for the first section (agent turn: writes `analyses/<id>.py`, runs it, saves `charts/<id>.png`, writes `sections/<id>.md` with frontmatter) → on `session.idle` the UI surfaces Accept / Drop / bottom-bar redirect → user may redirect (4b: agent discards drafts and rebuilds the same section) → user accepts → Export concatenates `sections/*.md` in plan order to a deliverable `.md`.

**Workstreams (component-level; stories in the backlog).**
- *Tech Lead:* integrate the slice end-to-end and gate the merge.
- *Backend Engineer:* orchestrator extends to planning → building (first section); plan prompt + schema; section-build prompt (file triplet via `apply_patch`); the 4b redirect prompt (discard drafts, rebuild same section); SSE handling for `apply_patch`, `bash`, `file.edited`, `session.idle`, keyed to the reconciled shapes; `section.failed` detection (no `.md` after idle); the backend-only endpoints (plan edit / reorder / drop / add; section accept / drop; export = ordered concatenation, no OpenCode; file serving); `plan.json` + section statuses in `state.json`; the deterministic `.md` frontmatter parser.
- *Frontend Engineer:* PlanView (inline edits → backend, bottom-bar text → agent); BuildView + SectionPane (render code, chart loaded from disk, interpretation); Accept / Drop controls; the section-stage bottom-bar redirect; Export control.
- *QA:* demo script 2; confirm backend-only operations never call OpenCode; regression on multi-turn stability (now many turns per session) — the recovery built in Slice 1 stays green.

**Anchored decisions.** ADR-003 (backend-only vs agent-driven split), ADR-004 (plan structured output), ADR-005 (file triplet as the section contract).

**Explicitly deferred from this slice.** Only **one** section is built; the sequential "accept triggers N+1 until done" loop is Night 3. No error-banner UI. No `done` state. Single dataset still.

**Definition of Done (demoable increment).** Accept a proposed plan (after at least one inline edit and one bottom-bar revision), watch a single section build through its full triplet, redirect it once mid-build and watch it rebuild, accept it, then export the brief-so-far to a single Markdown file.

**Why one section but fully interactive.** Getting the first file-triplet build working — prompt, `apply_patch` writes, run, chart on disk, frontmatter parse, render — is the hard, novel part, and the redirect reuses exactly that machinery, so building both together is coherent. Iterating section N → N+1 is mechanical by comparison and is cheaper and safer to add once one section is solid.

---

## Slice 3 — Scale, robustness, and the deliverable

**Goal.** Scale the single section to a full brief, make the agent boundary survive real failure, and produce the submittable package.

**The path this slice lights up.** Sequential multi-section build (accept triggers the next section until all done → `done` state) across more than one dataset; the three failure modes collapsed to two UI patterns (retry banner; `section.failed` retry/drop; watchdog timeout surfaced); `make run` single-command submission; README and architecture write-up.

**Workstreams (component-level; stories in the backlog).**
- *Tech Lead:* `make run` (build the frontend bundle, FastAPI serves `frontend/dist/` statically, ADR-008); `make clean` polish; README + architecture write-up (ADR-009); integrate the submission build and gate the merge.
- *Backend Engineer:* sequential section loop and `done` transition; retry semantics (re-send the same prompt); structured-output-failure and provider-error mapped to the retry-banner signal; watchdog hardening across long multi-section runs.
- *Frontend Engineer:* the three error UI surfaces (retry banner; `section.failed` retry/drop; watchdog timeout); the `done` state.
- *QA:* full regression (multi-section brief on the churn CSV **and a second dataset**, induced failures recovered, export); cold `make run` on a clean checkout; the submission demo script.

**Anchored decisions.** ADR-008 (dev vs run serving), ADR-009 (Makefile, no Docker), plus the error-handling model from `WORKFLOW_ORCHESTRATION.md`.

**Explicitly deferred — permanently out of scope.** Cross-cutting refinement (Stage 5), snapshots (Stage 6), multi-session / new-session affordance, multi-user / auth, interactive charts (matplotlib PNG only), editable code in the UI, export formats beyond Markdown, Docker / containerisation.

**Definition of Done (demoable increment).** From a clean checkout via `make run` (not `make dev`): build a full brief across multiple sections on the churn dataset, repeat the core path on a second dataset to prove generality, induce a failure and recover it via the retry banner, and export the brief to a single Markdown file. This is the submission state.

---

## Cross-slice notes

**The contracts that enable parallel work.** Three already-specified seams let the four lanes proceed concurrently each night without coding against each other's internals:
- `API_CONTRACT.html` — the frontend ↔ backend contract (8 REST endpoints, SSE event payloads forwarded to the SPA).
- The workspace file layout plus the `state.json` / `plan.json` / `profile.json` schemas — the backend ↔ agent contract.
- The SSE event list — the agent ↔ frontend contract.

The orchestrator calls the OpenCode client through a **narrow interface**; the client owns all OpenCode-specific knowledge behind it. This is what keeps the orchestration lane and the agent-integration lane independent.

**Reconciliation is a blocking Night 1 prerequisite, not a background task.** Because the spike showed the SSE event list in the spec is partly wrong, both the backend's SSE handlers and the frontend's `useSSE` would otherwise be built against divergent assumptions and mismatch at integration. So the Backend Engineer's *first* Night 1 deliverable is to reconcile `WORKFLOW_ORCHESTRATION.md` against the captured shapes and **publish a corrected SSE-event contract**; the frontend SSE work consumes that corrected contract, not the original spec. Known divergences to honour: file writes via `apply_patch` (key off `file.edited`, not a tool name); streaming text via `message.part.delta` (not `part.delta` on `message.part.updated`); tool parts pending → running → completed (input at pending, output/metadata at completed); extra event types (`server.heartbeat`, `session.status`, `session.diff`, `step-start`/`step-finish`, `reasoning`); use the v1 `/session` API, not v2 `/api/session`. Where spike and spec disagree on runtime behaviour, the spike wins.

**Execution environment.** OpenCode v1.15.10, OpenAI provider via OAuth (`providerID: "openai"`), per the spike; version stays pinned. The dev and QA agents are issued live credentials, so each DoD is verified end-to-end against the real runtime overnight — the morning review confirms working function rather than re-running integration from scratch.

**DoD has two forms.** The narratives above are the *human review demos* you run each morning. Because the agent's output is nondeterministic, the QA agent gates merges on the *structural* form of each DoD — file existence, script exit codes, valid `.md` frontmatter, `state.json` status transitions, event-stream assertions — defined in `04_QA_PLAN.md`. Semantic quality of the analysis is your eyeball call, not an automated gate.

**Risk-ordering summary.** Slice 1 retires agent-runtime, SSE, and recovery risk; Slice 2 retires the human-in-the-loop, file-triplet, and redirect risk; Slice 3 retires failure-mode and generality risk and produces the deliverable. Each slice is independently demoable, and the daily review gates promotion of each.

---

## Dependencies and sequencing

- The reconciled SSE-event contract (Slice 1, blocking) must be published before any SSE handler — integration or frontend — is written.
- Slice 2 depends on Slice 1's `opencode_client`, persistent SSE stream, watchdog/recovery, `state_manager`, and `GET /state` being merged and green. Export is backend-only and independent of the agent path. The 4b redirect reuses the Slice 2 section-build path.
- Slice 3's sequential loop depends on Slice 2's single-section build and accept-triggers-next signal; the error UI depends on Slice 1's watchdog and Slice 2's `section.failed` signal already existing as backend signals; the second-dataset check depends on the multi-section loop.
- Within each night the four lanes run in parallel against the contracts above; the Tech Lead integrates and QA verifies the structural DoD before merge. (Mechanics in `03_OPERATING_MODEL.md`.)
