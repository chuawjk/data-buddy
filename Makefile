.PHONY: install dev test lint format

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
	@trap 'kill 0' INT TERM; \
	( \
		uv run --project backend uvicorn backend.main:app --reload --port 8000 & \
		pnpm --prefix frontend run dev & \
		wait \
	)

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
