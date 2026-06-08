# Submission Demo Script

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

---

## Step 2 — Upload dataset and enter aim

1. In the setup form, drag-and-drop or click to upload `workspace/data/customers_q3.csv`.
2. In the aim field, type: `Understand what drives customer churn and suggest interventions`.
3. Click Submit (or press Enter).

Expected SSE stream:
- `stage.changed` → `profiling`
- Activity Rail begins showing OpenCode activity items

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

**Provider error:**

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

**Section failure:**
```bash
make qa-section-missing-output-on
```
Upload the dataset, complete profiling and planning, then accept the plan. The first
section build fails (`section.failed` emitted). The Section Pane shows Retry / Drop
buttons. Run `make qa-section-missing-output-off` before retrying.

**Turn-stall variant:**

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
   - `Watchdog fired: no events for 8s.` (the short stall window, not the 60s budget)
   - `Watchdog: aborting stuck session …`
   - `Watchdog: creating fresh session.` followed by `fresh session created and persisted`
   - `Watchdog: published turn.error (stage=…, reason=timeout)`
4. In the browser, the **Retry Banner** appears ("Couldn't complete this step — retry").
5. Confirm a *fresh* session was created: the persisted `opencode_session_id` in
   `workspace/state.json` differs from the one before the stall.
6. Run `make qa-turn-stall-off`, then click **Retry**. The replayed turn runs on the
   fresh session and completes normally; no server restart, no lost Data Buddy state.
