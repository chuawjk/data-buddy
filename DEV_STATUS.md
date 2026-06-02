# DEV_STATUS.md

*Single writer: TL. All other agents read only. Updated at the end of each overnight run.*

---

## Current branch: `develop`

Pre-sprint infrastructure merged (PR #2, squash commit `69ae52f`):
- `.github/workflows/ci.yml` — single `ci` job; triggers on push/PR to `main` and `develop`; sets up uv + Python 3.12, Node 22, pnpm; runs `make install` → `make lint` → `make test`. CI will be red until N1-S01 lands the Makefile — expected.

---

## Night 1 — Walking skeleton through Profiling

### Merged to `develop`
- `chore/ci-workflow` — GitHub Actions CI workflow (pre-sprint infra, PR #2, `69ae52f`)

### In Dev / In Review / In QA
*(none yet — awaiting Night 1 kickoff)*

### t0 Startable set
All Night 1 stories with no dependencies, or whose dependencies are listed above as merged:

- **N1-S01** (TL) — Project scaffold & dev loop *(no deps)*
- **N1-S07** (BE) — Reconciled event contract ⛔ BLOCKING *(no deps — must merge before any SSE work)*

Unlocks after N1-S01:
- N1-S02 (BE) · N1-S13 (FE)

Unlocks after N1-S07:
- N1-S08 (BE) · N1-S14 (FE) *(both depend on N1-S07)*

### Blockers
*(none)*

### Overnight ADR decisions
*(none — see `ADR.md` for pre-existing decisions)*

### Night 1 demo script (morning review)
1. Fresh clone → `make dev`
2. Open app → upload `data/customers_q3.csv` + enter an aim
3. Watch profiling activity stream live in the Activity Rail
4. Confirm Profile view renders (shape strip + per-column rows)
5. Submit one bottom-bar re-profile → confirm second turn completes or recovers via fresh session
6. Refresh browser → confirm UI re-hydrates from `state.json`
