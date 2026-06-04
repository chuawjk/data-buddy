# Data Buddy

Data Buddy is an agent-driven data analysis tool. Upload a CSV, state what you want to learn, and the system profiles your data, drafts a structured analysis plan, and builds it section by section — each section producing a Python analysis script, a chart, and a written interpretation.

The analysis is done by [OpenCode](https://opencode.ai), an AI coding agent. The backend orchestrates what OpenCode does and when; the frontend shows it happening in real time.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12 | Required by the backend |
| [uv](https://docs.astral.sh/uv/) | latest | Python package manager |
| Node.js | ≥ 18 | Required by the frontend |
| [pnpm](https://pnpm.io) | ≥ 8 | Frontend package manager |
| [OpenCode CLI](https://opencode.ai) | v1.15.10 | The AI agent runtime |
| OpenAI API key | — | Provider authentication for OpenCode |

**OpenCode authentication:** after installing OpenCode, run `opencode auth login openai` and follow the OAuth prompts. Your API key must be accessible to the OpenCode process — the simplest path is setting `OPENAI_API_KEY` in your shell environment before running `make run` or `make dev`.

---

## Quick start

```bash
# 1. Install all dependencies
make install

# 2. Set required environment variables
export OPENAI_API_KEY=sk-...

# 3. Build and run (single port: http://localhost:8000)
make run
```

Open `http://localhost:8000` in your browser, upload a CSV, type an aim, and follow the workflow.

---

## Development

```bash
make dev
```

Runs two servers in parallel:

- **FastAPI** on `http://localhost:8000` — the backend API (with hot-reload)
- **Vite** on `http://localhost:5173` — the frontend (with HMR)

OpenCode is spawned automatically by the FastAPI backend on startup. Open `http://localhost:5173` during development. The Vite dev server proxies all `/api` requests to `:8000`.

---

## Workflow

1. **Upload** a CSV file and type an aim — what you want to learn from the data.
2. **Profile** — the agent reads the dataset and summarises each column: type, statistics, and flags like `nullable` or `high_cardinality`. Review the profile, then click Accept.
3. **Plan** — the agent proposes 3–6 analysis sections. Edit titles, reorder, or drop sections before accepting.
4. **Build** — the agent writes and runs a Python analysis for each section, producing a chart and a written interpretation. Accept, drop, or redirect each section.
5. **Export** — download the completed brief as a Markdown document containing the accepted sections in plan order.

---

## Testing and linting

```bash
make test    # runs pytest (backend) and Vitest (frontend)
make lint    # runs ruff (backend) and ESLint (frontend)
```

---

## Resetting between runs

```bash
make clean
```

Removes `workspace/state.json`, `workspace/plan.json`, `workspace/profile.json`, `workspace/sections/`, `workspace/analyses/`, `workspace/charts/`, and `frontend/dist/`. Does NOT remove uploaded CSVs in `workspace/data/`. Run `make clean` before a fresh demo run.

---

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key; passed to OpenCode for provider authentication |
| `WATCHDOG_TIMEOUT_SECONDS` | No | `60` | Seconds without an SSE event before a stuck turn is aborted and a fresh session is created |
| `SKIP_OPENCODE` | No | unset | Set to `1` to start the backend without launching OpenCode (useful for UI development and CI) |
| `QA_FORCE_STALL` | No | unset | Set to `1` to simulate a stuck turn after the first event, for testing watchdog recovery |
| `QA_FORCE_SECTION_FAIL` | No | unset | Set to `1` to force a section build to fail (for testing the retry/drop flow) |

---

## Repository layout

```
data-buddy/
├── backend/               Python backend — FastAPI app, orchestrator, OpenCode client
├── frontend/              React SPA — stage views, hooks, types
├── workspace/             Runtime artefacts written by OpenCode (gitignored)
├── docs/                  Architecture, contracts, planning docs
│   ├── ARCHITECTURE.md    Architecture overview and key design decisions
│   ├── contracts/         API and SSE contracts the backend and frontend integrate through
│   └── planning/          Story backlog and operating model (static spec)
├── Makefile               install / dev / run / test / lint / format / clean
├── CLAUDE.md              Auto-loaded into every dev agent session — codebase orientation
├── ADR.md                 Architecture decisions
└── DEV_STATUS.md          Live progress board
```

---

## How it works

The **backend** is the orchestrator — it decides when to prompt the AI and what to say. The **frontend** never talks to OpenCode directly. The **workspace** is the durable record of everything the AI produces.

```
Browser  <──REST + SSE──>  Backend (FastAPI)  <──HTTP──>  OpenCode
                                 │
                           reads/writes
                                 │
                           workspace/ (files on disk)
```

For the full architecture including the state machine, session recovery model, and the backend-vs-agent split, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

### Note on Docker

Docker is not used for this prototype. OpenCode's filesystem coupling (it writes session state to `~/.local/share/opencode/`) makes containerisation awkward without bind-mounts and additional setup steps. `make run` gives a clean single-command path without that complexity. See ADR-009 for the rationale.
