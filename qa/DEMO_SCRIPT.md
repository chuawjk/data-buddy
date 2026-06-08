# N3-S15 — Submission Demo Script

Night 3 rehearsed interview path. Each step annotates which ADR it demonstrates.

---

## Prerequisites check

```
opencode --version     # must show v1.15.x or later
python --version       # must show 3.12.x
uv --version           # must show 0.x.y
pnpm --version         # must show 11.x or later
node --version         # must show 20.x or later
```

OpenCode OAuth credentials must be present at `~/.local/share/opencode/auth.json`.
If absent, run `opencode login` once before the demo.

**ADR-008 framing:** the system ships as a single command (`make run`) that builds
the frontend and starts a single server on port 8000. No separate processes to
manage; no dev tooling required at demo time.

---

## Step 1 — Clean start

```bash
make very-clean && make run
```

Expected output:
1. `==> Building frontend bundle` — Vite compiles the SPA into `frontend/dist/`.
2. `==> Starting FastAPI (serving built bundle on http://localhost:8000)` — uvicorn starts.
3. `Application startup complete.` — OpenCode is launched as a subprocess.

Open `http://localhost:8000` in the browser. The setup form loads immediately.

**ADR-008 framing:** `make run` is the single entry point for the demo. No Vite dev
server, no hot-reload, no two-terminal setup.

**Negative check (optional):** run `make clean` first and verify it removes
`workspace/state.json`, `workspace/plan.json`, `workspace/profile.json`,
`workspace/sections/`, `workspace/charts/`, `workspace/analyses/`, and
`frontend/dist/` — but does NOT remove `workspace/data/` (the churn CSV).

`make very-clean` additionally removes only OpenCode's SQLite session database
(`~/.local/share/opencode/opencode.db` and its `-shm` / `-wal` sidecars), preventing
stale schema state from surviving an OpenCode upgrade. It preserves
`~/.local/share/opencode/auth.json`. Stop Data Buddy/OpenCode before running it.

---

## Step 2 — Upload dataset and enter aim

1. In the setup form, drag-and-drop or click to upload `workspace/data/customers_q3.csv`.
2. In the aim field, type: `Understand what drives customer churn and suggest interventions`.
3. Click Submit (or press Enter).

Expected SSE stream:
- `stage.changed` → `profiling`
- Activity Rail begins showing OpenCode activity items

**ADR-003 framing:** the backend orchestrates OpenCode as a subprocess. The frontend
never knows about OpenCode — it only receives enriched SSE events from the backend.
The backend → OpenCode split is invisible from the UI.

**ADR-005 framing:** the profiling turn instructs OpenCode to write `workspace/profile.json`
to disk. The backend reads it on `session.idle`, not from the agent's conversational
memory. Files-as-contract.

---

## Step 3 — Watch profiling stream; accept profile

While profiling runs (~45s):
- Activity Rail logs file writes and tool calls as they happen.
- When `profile.ready` fires, the Profile View renders:
  - Shape strip: rows, columns, inferred target column
  - Column list with types and flags

Point out: "This profile was extracted from the file OpenCode wrote — not parsed
from the model's chat response."

Click **Accept profile**.

**ADR-005 framing:** `workspace/profile.json` is the file contract. The prompts
instruct OpenCode to write it; the backend validates it on `session.idle`.

---

## Step 4 — Review and edit the plan; accept plan

After `stage.changed → planning` and the plan renders:
1. Read through the proposed sections (3–6 entries, each with title and hypothesis).
2. Make one inline edit: click a section, change its hypothesis text or reorder sections.
3. Click **Accept plan** to enter the building stage.

Expected:
- `POST /plan/update` fires with zero OpenCode calls (the spy invariant holds).
- `stage.changed → building`
- First section starts building immediately

**ADR-003 framing:** `/plan/update` is backend-only — no token spend for a human
editing their own plan. The "zero OpenCode calls" invariant is the line between the
backend state machine (free operations) and the agent (paid, async operations).

---

## Step 5 — Watch sections build sequentially

For each section as it builds:
- Activity Rail shows file writes (`.py`, `.png`, `.md`)
- When `section.proposed` fires, the Section Pane renders:
  - Code block (expandable)
  - Chart image (served via `GET /file`)
  - Interpretation text

For each section, choose one of:
- **Accept** — moves to next section automatically
- **Drop** — skips and advances the loop

Optional redirect demo: click the revision input, type a change request, press Enter.
The section rebuilds with the redirect instruction.

**ADR-005 framing:** each section produces three files (`.py`, `.png`, `.md`).
The `section.proposed` event carries the paths; the frontend fetches content via
`GET /file`. The backend validated the complete file triplet before emitting the event.

**ADR-002 framing (if a section stalls):** the watchdog fires after a window of
*silence* — no OpenCode activity event for the per-turn budget (180s for a section
build in production). Every activity event (`message.part`, `tool.*`, `file.ready`)
re-arms the timer via `watchdog.heartbeat()`, so a turn that is genuinely working is
never aborted; only true silence trips it. On firing it aborts the stalled session,
creates a fresh session, and emits `turn.error`. The UI shows the retry banner.
For a live, deterministic version of this in seconds rather than minutes, see the
**Turn-stall variant** in Step 7.

---

## Step 6 — Reach done screen; export

When the last section is accepted or dropped:
- `stage.changed → done`
- **Done View** renders: "Brief complete" heading, list of accepted sections in plan
  order, prominent Export button.

Click **Export brief as Markdown**.
- Browser downloads `data-buddy-export.zip` (or `brief.md` depending on export format)
- Open the file and confirm:
  - Accepted sections are included in plan order
  - Dropped and queued sections are excluded
  - Each section has its title, code, chart path reference, and interpretation

**ADR-003 framing:** `GET /export` is backend-only — zero OpenCode calls. The export
assembles Markdown from the files OpenCode wrote during building.

---

## Step 7 — Error recovery demo path (QA seam)

Open a second terminal while `make run` remains active:

```bash
make qa-provider-error-on
```

1. Start a profiling turn.
2. The profiling turn immediately emits `turn.error` (no OpenCode call, no token spend).
3. The **Retry Banner** appears at the top of the Profile View: "Couldn't complete this
   step — retry."
4. Run `make qa-provider-error-off`, then click Retry. The turn now reaches OpenCode
   without restarting the server or losing Data Buddy state.
5. Re-enable `qa-provider-error` and retry again if desired. Manual retries have no
   fixed limit; duplicate clicks during an active retry are ignored.

**ADR-002 framing:** session recovery is deterministic. `qa-provider-error` exercises
the retry banner path without model misbehaviour or token spend. Each retry creates
and persists a fresh OpenCode session before replaying the failed turn.

**Section failure variant (optional):**
```bash
make qa-section-missing-output-on
```
Upload the dataset, complete profiling and planning, then accept the plan. The first
section build fails (`section.failed` emitted). The Section Pane shows Retry / Drop
buttons. Run `make qa-section-missing-output-off` before retrying.

**Turn-stall variant (watchdog recovery — reliable live flow):**

This exercises the stuck-turn watchdog end-to-end without waiting out the full
production budget. With the control on, OpenCode emits its first activity event for a
turn and then goes silent; because the watchdog only re-arms on activity, the silence
window elapses and recovery fires. Under this control both the silence window (~8s) and
the post-abort grace (~2s) collapse to short, deterministic values, so the whole
recovery surfaces in roughly ten seconds.

```bash
make qa-turn-stall-on
```

1. Start any agent turn — the simplest is the **profiling** turn right after uploading
   the dataset and submitting an aim.
2. The Activity Rail shows the turn's first event, then nothing further — the turn has
   gone silent.
3. Within ~10s the watchdog fires. Watch the server log for, in order:
   - `Watchdog fired: no events for 8s.` (the short stall window, not 60/180s)
   - `Watchdog: aborting stuck session …`
   - `Watchdog: creating fresh session.` followed by `fresh session created and persisted`
   - `Watchdog: published turn.error (stage=…, reason=timeout)`
4. In the browser, the **Retry Banner** appears ("Couldn't complete this step — retry").
5. Confirm a *fresh* session was created: the persisted `opencode_session_id` in
   `workspace/state.json` differs from the one before the stall.
6. Run `make qa-turn-stall-off`, then click **Retry**. The replayed turn runs on the
   fresh session and completes normally; no server restart, no lost Data Buddy state.

**ADR-002 framing:** the watchdog detects *silence*, not wall-clock turn length —
activity heartbeats keep a working turn alive, and only genuine silence triggers abort
+ fresh-session recovery. `qa-turn-stall` makes that recovery observable in seconds.

---

## Step 8 — Second dataset path

Stop `make run`, run `make clean`, then restart:

```bash
make clean && make run
```

1. Upload any structurally different CSV (different columns, different schema).
2. Enter a new aim.
3. Complete the full profiling → planning → building → done path.
4. Confirm the profile shape strip shows the new dataset's dimensions.
5. Export and confirm the brief reflects the new dataset.

This step proves the pipeline is not hardcoded to the churn CSV.

**Generality framing:** the three-file contract (profile.json → plan.json → sections/*.md)
is the same regardless of the dataset. OpenCode reads the file path from the prompt; it
never hardcodes dataset assumptions.

---

## Interview framing summary

| Step | ADR | Talking point |
|------|-----|---------------|
| 1 | ADR-008 | Single `make run` command; no dev tooling at demo time |
| 2–3 | ADR-005 | File triplet contract — agent writes files; backend reads them |
| 2–3 | ADR-003 | Backend vs agent split — setup, plan edit, export are free operations |
| 4–5 | ADR-003 | Zero OpenCode calls for backend-only ops; spy invariant holds |
| 6 | ADR-003 | Export is purely backend-side; model never runs again after building |
| 7 | ADR-002 | Session recovery — watchdog fires, fresh session, retry banner |
| 7 | ADR-002 | Runtime QA controls — deterministic failure without token spend |
| 8 | — | Generality — same pipeline on any CSV, not overfit to churn |

---

## Known gate status at submission

- Night 3 defect **QA-03** (blocking): `make run` production serving is broken.
  The SPA calls `/api/state` but the backend router registers at `/state` — the SPA
  catch-all intercepts `/api/*` calls and returns HTML instead of JSON. All API calls
  from the built bundle fail in production mode.
  **Fix**: add `prefix="/api"` to the `APIRouter` in `backend/api/router.py` and update
  the `include_router` call in `backend/main.py`.
  **Impact on demo**: use `make dev` (not `make run`) to serve the app during the demo
  until this defect is fixed and QA re-gates.
