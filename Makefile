.PHONY: install dev test lint format clean very-clean run \
	qa-provider-error-on qa-provider-error-off \
	qa-section-missing-output-on qa-section-missing-output-off \
	qa-turn-stall-on qa-turn-stall-off

# ── install ────────────────────────────────────────────────────────────────────
install:
	@echo "==> Installing backend dependencies (uv)"
	uv sync --project backend
	@echo "==> Installing frontend dependencies (pnpm)"
	pnpm --prefix frontend install
	@echo "==> Installing pre-commit"
	uv tool install pre-commit
	pre-commit install
	@echo "==> Installing Playwright browsers"
	pnpm --prefix frontend exec playwright install --with-deps || echo "WARN: playwright install skipped"
	@if ! command -v opencode >/dev/null 2>&1; then \
		echo ""; \
		echo "WARNING: 'opencode' binary not found on PATH."; \
		echo "  Install it from https://opencode.ai and ensure it is on your PATH."; \
		echo "  'make dev' will start without it but agent-driven features will not work."; \
		echo ""; \
	fi

# ── dev ───────────────────────────────────────────────────────────────────────
dev:
	@echo "==> Starting dev servers (FastAPI :8000, Vite :5173)"
	@echo "    NOTE: OpenCode is managed by the FastAPI backend (not started separately here)."
	@echo "    Set SKIP_OPENCODE=1 to disable OpenCode (CI / no-agent mode)."
	@uv run --project backend uvicorn backend.main:app --reload --reload-dir backend --port 8000 & \
	BE_PID=$$!; \
	pnpm --prefix frontend run dev & \
	FE_PID=$$!; \
	trap 'kill "$$BE_PID" "$$FE_PID" 2>/dev/null; wait "$$BE_PID" "$$FE_PID" 2>/dev/null' INT TERM EXIT; \
	wait "$$BE_PID" "$$FE_PID"

# ── run (production: build frontend bundle, serve from FastAPI on :8000) ───────
run:
	@echo "==> Building frontend bundle"
	pnpm --prefix frontend run build
	@echo "==> Starting FastAPI (serving built bundle on http://localhost:8000)"
	@uv run --project backend uvicorn backend.main:app --host 0.0.0.0 --port 8000 & \
	BE_PID=$$!; \
	trap 'kill "$$BE_PID" 2>/dev/null; wait "$$BE_PID" 2>/dev/null' INT TERM EXIT; \
	wait "$$BE_PID"

# ── test ──────────────────────────────────────────────────────────────────────
test:
	uv run --project backend pytest backend/tests
	pnpm --prefix frontend run test

# ── lint ──────────────────────────────────────────────────────────────────────
lint:
	uv run --project backend ruff check backend
	pnpm --prefix frontend run lint

# ── format ────────────────────────────────────────────────────────────────────
format:
	uv run --project backend ruff format backend
	pnpm --prefix frontend run format

# ── clean ─────────────────────────────────────────────────────────────────────
clean:
	rm -rf workspace/state.json workspace/plan.json workspace/profile.json \
	       workspace/sections workspace/analyses workspace/charts workspace/.qa \
	       frontend/dist frontend/.vite
	@echo "Workspace and build artefacts removed."

# ── very-clean ────────────────────────────────────────────────────────────────
very-clean:
	@if pgrep -f '[o]pencode serve' >/dev/null 2>&1; then \
		echo "ERROR: OpenCode is running. Stop Data Buddy/OpenCode before make very-clean."; \
		exit 1; \
	fi
	@$(MAKE) clean
	rm -f "$${XDG_DATA_HOME:-$$HOME/.local/share}/opencode/opencode.db" \
	      "$${XDG_DATA_HOME:-$$HOME/.local/share}/opencode/opencode.db-shm" \
	      "$${XDG_DATA_HOME:-$$HOME/.local/share}/opencode/opencode.db-wal"
	@echo "OpenCode session database removed. Authentication and configuration preserved."

# ── runtime QA controls ───────────────────────────────────────────────────────
qa-provider-error-on:
	@mkdir -p workspace/.qa
	@touch workspace/.qa/provider-error
	@echo "QA provider-error enabled."

qa-provider-error-off:
	@rm -f workspace/.qa/provider-error
	@echo "QA provider-error disabled."

qa-section-missing-output-on:
	@mkdir -p workspace/.qa
	@touch workspace/.qa/section-missing-output
	@echo "QA section-missing-output enabled."

qa-section-missing-output-off:
	@rm -f workspace/.qa/section-missing-output
	@echo "QA section-missing-output disabled."

qa-turn-stall-on:
	@mkdir -p workspace/.qa
	@touch workspace/.qa/turn-stall
	@echo "QA turn-stall enabled."

qa-turn-stall-off:
	@rm -f workspace/.qa/turn-stall
	@echo "QA turn-stall disabled."
