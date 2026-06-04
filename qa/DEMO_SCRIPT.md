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
make clean && make run
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

**ADR-002 framing (if a section stalls):** the watchdog fires after 180s of silence.
It aborts the stalled OpenCode session, creates a fresh session, and emits `turn.error`.
The UI shows the retry banner or section-failed notice with Retry/Drop options.

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

Open a second terminal. Stop `make run` (Ctrl+C), then:

```bash
make clean
QA_FORCE_TURN_ERROR=1 make run
```

1. Upload the dataset again and enter an aim.
2. The profiling turn immediately emits `turn.error` (no OpenCode call, no token spend).
3. The **Retry Banner** appears at the top of the Profile View: "Couldn't complete this
   step — retry."
4. Click Retry.
5. The turn fires again — with `QA_FORCE_TURN_ERROR=1` it fails again; click Retry
   up to 3 times. On the 4th attempt, `turn.error` with `reason="provider_error"` fires
   (max retries exceeded).

Unset the env var and restart to confirm normal recovery:
```bash
make clean && make run
```

**ADR-002 framing:** session recovery is deterministic. `QA_FORCE_TURN_ERROR` exercises
the retry banner path without model misbehaviour or token spend. The session ID is
refreshed from state on each retry so a watchdog swap is picked up automatically.

**Section failure variant (optional):**
```bash
make clean
QA_FORCE_SECTION_FAIL=1 make run
```
Upload the dataset, complete profiling and planning, then accept the plan. The first
section build fails (`section.failed` emitted). The Section Pane shows Retry / Drop
buttons. Click Drop to advance the loop.

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
| 7 | ADR-002 | QA_FORCE_TURN_ERROR seam — deterministic failure without token spend |
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

