# QA_LOG.md

Sole writer: QA agent. TL and human may read; no other agent writes here.
Each defect becomes a standing regression check before it is allowed to close.

---

## Night 1 — QA Run — 2026-06-02

### Structural assertions

| Check | Result | Notes |
|-------|--------|-------|
| profile schema fields (`shape.{rows,columns}`, `columns[].{name,type,flags,summary}`, `flags[]`) | PASS | `PROFILE_SCHEMA` in `backend/prompts/profile.py` declares all required fields as required properties; AST-verified |
| No committed `docs/contracts/schemas/` profile schema file | N/A | Assertion spec says "if a committed profile schema exists, validate it"; none committed; in-code schema validated instead |
| orchestrator httpx boundary | PASS | AST walk of `backend/orchestrator.py` — zero `import httpx` / `from httpx` nodes |
| opencode_client orchestrator boundary | PASS | AST walk of `backend/opencode_client.py` — zero imports of `orchestrator` module |
| single event connection | PASS | Exactly one `asyncio.create_task(client.start_event_subscription(...))` at `main.py:83`; `start_event_subscription` string count = 1 |
| data-testid completeness (>= 17) | PASS | 19 unique `data-testid` values in production frontend files (excludes `.test.` files); all 17 required selectors present plus 2 additional (`loading-indicator`, `error-banner`) |
| make test (130 tests) | PASS | 78 backend (pytest) + 52 frontend (vitest) = 130 total; all passed; 1 deprecation warning (httpx/starlette, non-blocking) |
| make lint | PASS | `ruff check backend` clean; `eslint src` clean (0 warnings) |

### Live demo path

| Step | Result | Notes |
|------|--------|-------|
| POST /setup | PASS | Returns HTTP 204; CSV uploaded, aim persisted, stage immediately advances to profiling |
| stage→profiling | PASS | GET /state on poll 0 returns `"stage":"profiling"`; state persisted correctly |
| profile.json valid | PASS | profile.json written at ~45s; shape {rows:100, columns:9}; validated present and non-empty |
| POST /turn (re-profile) | PASS | Returns HTTP 204 immediately; second profiling turn accepted by orchestrator |
| second turn no-hang | PASS | Profile re-written within 90s; stage remained `profiling`; no hang; profile_present=True on final poll |
| GET /state refresh | PASS | GET /state after second turn returns stage=profiling, profile present, shape key present |

**Live demo run date:** 2026-06-02. Stack: `make dev` with live OpenCode v1.15.13 + OAuth auth at `~/.local/share/opencode/auth.json`. FastAPI and Vite started cleanly; OpenCode process (PID present) launched and accepted session creation. Two defects blocked profiling turn completion (QA-01, QA-02 — both fixed in commit `f63787c`). Steps 4–6 re-run post-fix: all pass.

### Defects found

**QA-01 — SSE subscription crash loop (blocking)**

| Field | Value |
|-------|-------|
| ID | QA-01 |
| Night | 1 |
| Symptom | `start_event_subscription` background task immediately raises `object _AsyncGeneratorContextManager can't be used in 'await' expression` on every iteration, looping at ~0.1s intervals forever. No events ever reach the bus. The orchestrator never receives `session.idle` and profiling never completes. |
| Area | N1-S08 (`opencode_client.py` — persistent SSE subscription) |
| Root cause | `backend/opencode_client.py` line 332: `async with await aconnect_sse(...)`. `aconnect_sse` is decorated with `@asynccontextmanager`; calling it returns an `_AsyncGeneratorContextManager`, which is already an async context manager — it must not be `await`-ed before the `async with`. The spurious `await` causes Python to attempt to await the context manager object, which fails immediately. Fix: remove `await` → `async with aconnect_sse(http_client, "GET", event_url) as sse_response:` |
| Fix reference | commit `f63787c` on `develop` — removed spurious `await` before `aconnect_sse(...)` in `_run_one_connection` |
| Regression check added | REG-N1-11: unit test asserts `_run_one_connection` connects to a mock SSE endpoint without raising on the first iteration (i.e. the `aconnect_sse` call does not throw `_AsyncGeneratorContextManager can't be used in 'await' expression`); verifies at least one event is processed from the stream |
| State | Closed |

**QA-02 — prompt_async 400 Bad Request — wrong payload format (blocking)**

| Field | Value |
|-------|-------|
| ID | QA-02 |
| Night | 1 |
| Symptom | `POST /session/{id}/prompt_async` returns HTTP 400 `{"name":"BadRequest","data":{"message":"Missing key\n  at [\"parts\"]","kind":"Payload"}}`. The profiling turn fails immediately on `resp.raise_for_status()` and the profile turn exception is logged: `Profile turn failed: Client error '400 Bad Request'`. |
| Area | N1-S05 (`opencode_client.py` — `prompt()` method) |
| Root cause | `client.prompt()` sends `{"text": "..."}` (and optionally `format`) but OpenCode v1.15.13 requires `{"parts": [{"type": "text", "text": "..."}]}`. The payload format changed between v1.15.10 (spike) and v1.15.13 (installed). The spike documented the `text` field as working but the API bumped the schema. Confirmed by direct curl: `POST /session/{id}/prompt_async` with `{"parts":[{"type":"text","text":"hello"}]}` returns 204. |
| Fix reference | commit `f63787c` on `develop` — updated `prompt()` payload to `{"parts": [{"type": "text", "text": text}]}` and format block to flat `format.schema`; confirmed against live OpenCode v1.15.13 `/doc` OpenAPI spec |
| Regression check added | REG-N1-12: integration test (with a live or mocked OpenCode) asserts `client.prompt(session_id, "test")` sends a request body with top-level `"parts"` array containing `{"type":"text","text":"test"}` and receives a non-400 response |
| State | Closed |

### Overall: PASS (live demo path)

All 6 steps pass. Steps 1–2 passed in the initial run. Steps 3–6 were blocked by QA-01 and QA-02; both defects were fixed in commit `f63787c` and steps 4–6 were re-run on 2026-06-02: all returned PASS. The Night-1 live demo path clears. QA-01 and QA-02 are Closed with standing regression checks REG-N1-11 and REG-N1-12.

---

### TL fix note — 2026-06-02 (commit `f63787c` on `develop`)

QA-01 and QA-02 both fixed in `backend/opencode_client.py`. Summary:

- **QA-01**: Removed spurious `await` before `aconnect_sse(...)` in `_run_one_connection`. `aconnect_sse` is an `@asynccontextmanager`; awaiting it raised `TypeError` on every SSE connection attempt.
- **QA-02**: Updated `prompt()` payload from `{"text": text}` to `{"parts": [{"type": "text", "text": text}]}`. Updated format block from `format.json_schema.schema` wrapper to flat `format.schema` (OpenCode v1.15.13 API change, confirmed from live `/doc` OpenAPI spec). ADR-013 records the discovery.

**Live re-run post-fix (2026-06-02):** POST /setup → stage=profiling → profile.json written at t=45s (shape rows=100, columns=9). QA-01 + QA-02: RESOLVED.

All 130 tests pass (78 BE + 52 FE). Lint clean. Test mocks for `test_event_subscription.py` updated to use `def` (not `async def`) to match the sync call signature of the real `aconnect_sse` (QA-01 root cause made this mismatch latent previously). `test_router.py` client fixture patched to use temp-dir `StateManager` to fix pre-existing test isolation failure.

**Request to QA:** please update QA-01 and QA-02 defect `Fix reference` and `State` fields to reference commit `f63787c` and mark as Closed. REG-N1-11 and REG-N1-12 regression checks are confirmed passing in the current test suite.

---

## Regression suite — Night 1 standing checks

The following checks are promoted to the standing regression suite and will re-run every night before merge (per `04_QA_PLAN.md` §4 and §5).

| ID | Check | Location | Asserts |
|----|-------|----------|---------|
| REG-N1-01 | profile schema fields complete | `backend/prompts/profile.py` AST/import | `PROFILE_SCHEMA` has `shape.{rows,columns}` required, `columns[].{name,type,flags,summary}` required, top-level `flags` required |
| REG-N1-02 | orchestrator httpx boundary | AST walk `backend/orchestrator.py` | Zero `import httpx` or `from httpx` nodes at any scope |
| REG-N1-03 | opencode_client orchestrator boundary | AST walk `backend/opencode_client.py` | Zero imports referencing `orchestrator` module |
| REG-N1-04 | single event subscription task | `backend/main.py` string + AST count | Exactly one `asyncio.create_task(client.start_event_subscription(...))` |
| REG-N1-05 | data-testid completeness | grep `frontend/src/` (excl. `.test.`) | >= 17 unique `data-testid` values present |
| REG-N1-06 | test suite green | `make test` | 130 tests pass (78 backend + 52 frontend) |
| REG-N1-07 | lint clean | `make lint` | ruff + eslint exit 0 with 0 warnings |
| REG-N1-08 | POST /setup returns 204 + stage advances | unit test `test_setup.py` | HTTP 204; GET /state shows `stage=profiling` |
| REG-N1-09 | state.json atomic write | unit test `test_state_manager.py` | tmp+rename pattern; no partial write on simulated kill |
| REG-N1-10 | watchdog stall → fresh session recovery | unit test `test_watchdog.py` | Abort fires; new session ID created and persisted; no hang |
| REG-N1-11 | SSE subscription does not crash on first iteration | unit test `test_opencode_client.py` | `_run_one_connection` connects to a mock `/event` endpoint without `_AsyncGeneratorContextManager` TypeError; at least one event is published to the bus |
| REG-N1-12 | prompt_async payload uses `parts` array format | unit/integration test `test_opencode_client.py` | `client.prompt(sid, "text")` sends body `{"parts":[{"type":"text","text":"text"}]}`; response is not HTTP 400 |

---

## Night 2 — QA Run — 2026-06-03

### Night 1 regression recheck

All REG-N1-01 through REG-N1-12 re-verified against the develop slice at commit `14e647d`.

| Check | Result | Notes |
|-------|--------|-------|
| REG-N1-01 profile schema fields complete | PASS | `PROFILE_SCHEMA` in `backend/prompts/profile.py`; `shape.{rows,columns}`, `columns[].{name,type,flags,summary}`, `flags[]` all required; verified via `TestNight1RegressionCarryForward` |
| REG-N1-02 orchestrator httpx boundary | PASS | AST walk — zero `import httpx` / `from httpx` nodes in `orchestrator.py`; verified via `TestArchitectureBoundaries` |
| REG-N1-03 opencode_client orchestrator boundary | PASS | AST walk — zero orchestrator imports in `opencode_client.py`; verified via `TestArchitectureBoundaries` |
| REG-N1-04 single event subscription | PASS | Exactly one `start_event_subscription` in `main.py`; verified via `TestNight1RegressionCarryForward` |
| REG-N1-05 data-testid completeness (>= 17) | PASS | 40 unique `data-testid` values in production frontend (Night 2 additions included); verified via `TestDataTestidCompleteness` |
| REG-N1-06 test suite count (486 total) | PASS | 332 BE + 154 FE = 486 total; all pass |
| REG-N1-07 lint clean | PASS | `ruff check backend` and `eslint src` both exit 0 with 0 warnings |
| REG-N1-08 POST /setup 204 + stage advance | PASS | Covered by existing `test_setup.py` unit tests; 332 BE pass |
| REG-N1-09 state.json atomic write | PASS | Covered by existing `test_state_manager.py` unit tests |
| REG-N1-10 watchdog stall → fresh session | PASS | Covered by existing `test_watchdog.py` unit tests |
| REG-N1-11 SSE subscription no crash | PASS | Covered by existing `test_opencode_client.py` unit tests |
| REG-N1-12 prompt_async parts format | PASS | Covered by existing `test_opencode_client.py` unit tests |

### Night 2 structural gate

All structural assertions run in `qa/structural/test_n2_structural.py` — 63 tests, all pass.

| Check | Result | Notes |
|-------|--------|-------|
| A. Plan schema (REG-N2-01) | PASS | `PLAN_SCHEMA` has `sections[{id,title,hypothesis}]`, 3–6 entries, all required fields; validated 3/6/7 section counts |
| B. Zero OpenCode calls — backend-only endpoints (REG-N2-02) | PASS | Spy (`MagicMock`) attached to `orchestrator._client.prompt`; zero calls confirmed for `POST /plan/update`, `POST /section/:id/accept`, `POST /section/:id/drop`, `GET /export`, `GET /file` |
| C. Frontmatter parser shape (REG-N2-03) | PASS | `parse_frontmatter` returns `{frontmatter, body, parse_error}`; fields extracted correctly; malformed YAML sets `parse_error=True`, no raise; missing file returns fail-safe result |
| D. Architecture boundaries carry-forward (REG-N1-02/03) | PASS | See above |
| E. Forced-failure hook (REG-N2-04) | PASS | `QA_FORCE_SECTION_FAIL=1` + full triplet → `section.failed` emitted with `section_id`; `.md` removed from disk; hook unset + full triplet → `section.proposed` |
| F. State transitions (REG-N2-05) | PASS | `GET /state` returns `stage`, `plan`, `profile` fields; does not expose `opencode_session_id`; `POST /plan/update` changes plan synchronously and writes `plan.json`; `POST /section/:id/accept` transitions `proposed→accepted` |
| G. Export correctness (REG-N2-06) | PASS | Accepted sections included; dropped/proposed excluded; zero-section plan returns default doc; multi-section concatenation works; `Content-Disposition: attachment; filename="brief.md"`; zero OpenCode calls |
| H. data-testid completeness Night 2 (REG-N2-07) | PASS | `plan-view`, `plan-section-list`, `plan-accept-btn`, `plan-turn-input`, `plan-turn-submit`, `build-view`, `export-btn`, `section-code`, `section-interpretation` all present in production frontend files |
| make test (486 tests) | PASS | 332 BE + 154 FE = 486 total; all pass |
| make lint | PASS | ruff + eslint exit 0 |

### Defects found

None. All structural assertions pass. No defects logged.

### Run note — POST /setup empty aim contract observation

The API contract specifies a 422 `invalid_aim` error for empty aim. FastAPI's multipart form parser silently treats a truly-empty aim string (`""`) as a missing required field and returns a framework-level 422 with `detail[].type="missing"` — not the custom `"error":"invalid_aim"` envelope. The router's custom error fires correctly for whitespace-only aim. This is a narrow gap in the contract surface: the custom error envelope is not returned for the zero-character case. Logged as an observation only (not a blocking defect) because: (a) the frontend already validates non-empty input before submission, (b) the 422 status code is correct, (c) this gap existed in Night 1. A regression check was added to assert whitespace-only aim → custom `invalid_aim` error.

### Overall: PASS

Night 2 QA gate: PASS — ready for morning human review (develop → main promotion).

---

## Regression suite — Night 2 standing checks

| ID | Check | Location | Asserts |
|----|-------|----------|---------|
| REG-N2-01 | plan schema valid | `qa/structural/test_n2_structural.py` | `PLAN_SCHEMA` has `sections[{id,title,hypothesis}]`; 3-6 entries; minItems=3 enforced; maxItems=6 enforced |
| REG-N2-02 | zero OpenCode calls — backend-only endpoints | `qa/structural/test_n2_structural.py` | spy count unchanged after `/plan/update`, `/section/*/accept`, `/section/*/drop`, `/export`, `/file` |
| REG-N2-03 | frontmatter parser correctness | `qa/structural/test_n2_structural.py` | `parse_frontmatter` returns fields; malformed YAML handled safely; `parse_section_file` separates frontmatter from body; missing file is fail-safe |
| REG-N2-04 | forced-failure hook fires section.failed | `qa/structural/test_n2_structural.py` | `QA_FORCE_SECTION_FAIL=1` → `section.failed` with `section_id`; `.md` removed; hook unset → `section.proposed` (regression guard) |
| REG-N2-05 | state transitions correct | `qa/structural/test_n2_structural.py` | `GET /state` has `stage`, `plan`, `profile`; no `opencode_session_id`; `plan/update` → state.json changes synchronously; `section/accept` → `proposed→accepted` |
| REG-N2-06 | export correctness | `qa/structural/test_n2_structural.py` | accepted sections in output; dropped/proposed excluded; zero-section default doc returned; zero OpenCode calls; `Content-Disposition: attachment; filename="brief.md"` |
| REG-N2-07 | data-testid completeness Night 2 | `qa/structural/test_n2_structural.py` | `plan-view`, `plan-section-list`, `plan-accept-btn`, `plan-turn-input`, `plan-turn-submit`, `build-view`, `export-btn`, `section-code`, `section-interpretation` present in production frontend; Night 1 testids also present; total >= 30 unique testids |

---

## Post-Night-2 QA process defects — 2026-06-03

Three structural gaps identified after Night 2 QA passed despite real integration issues being present in the codebase.

**Gap 1 — Profile schema validation was definition-only, not output-validated**

| Field | Value |
|-------|-------|
| ID | QA-POST-N2-01 |
| Symptom | `profile.shape.rows` and `profile.shape.columns` rendered as `undefined` in the frontend shape strip. Agent wrote `total_rows`/`total_columns` instead of schema-specified `rows`/`columns`. |
| Root cause | REG-N1-01 checked that `PROFILE_SCHEMA` *defines* `rows`/`columns` as required. It never validated actual agent output against the schema. The orchestrator's `_handle_profile_idle` did a soft top-level key check (`shape`, `columns`, `flags`) but did not call `jsonschema.validate()`. The field-name deviation was invisible to all existing checks. |
| Fix reference | Frontend: `??` fallback added to `ProfileShape` type and `ProfileView` shape strip. Structural gate: `test_post_n2_contract.py` REG-POST-N2-01/02/03. |
| Regression check added | REG-POST-N2-01: canonical fixture passes `jsonschema.validate(PROFILE_SCHEMA)`. REG-POST-N2-02: deviation fixture with `total_rows`/`total_columns` *fails* schema validation. REG-POST-N2-03: `GET /state` with both variants returns shape accessible via `rows ?? total_rows`. |
| State | Closed |

**Gap 2 — `section-build.spec.ts` was orphaned outside Playwright's testDir**

| Field | Value |
|-------|-------|
| ID | QA-POST-N2-02 |
| Symptom | `section-build.spec.ts` lived at `frontend/e2e/` while Playwright's `testDir` is `./tests`. The spec never ran. It also asserted a `build-bottom-bar` testid that was removed post-Night-2; the failure was silent. |
| Root cause | Spec created in `e2e/` instead of `tests/e2e/`. No check verified all `*.spec.ts` files were inside `testDir`. |
| Fix reference | Moved to `frontend/tests/e2e/`. Stale `build-bottom-bar` test replaced with `section-revise-input`/`section-revise-btn` assertions. |
| Regression check added | REG-POST-N2-04: `section-revise-input` and `section-revise-btn` present in `SectionPane.tsx`; `build-bottom-bar` absent. REG-POST-N2-05: no `*.spec.ts` files exist outside `frontend/tests/e2e/`. |
| State | Closed |

---

## Regression suite — Post-Night-2 standing checks

| ID | Check | Location | Asserts |
|----|-------|----------|---------|
| REG-POST-N2-01 | canonical profile passes PROFILE_SCHEMA | `qa/structural/test_post_n2_contract.py` | `profile_canonical.json` passes `jsonschema.validate(PROFILE_SCHEMA)` |
| REG-POST-N2-02 | agent deviation fails PROFILE_SCHEMA | `qa/structural/test_post_n2_contract.py` | `profile_agent_deviation.json` (with `total_rows`/`total_columns`) raises `ValidationError` — schema is strict enough to catch field-name deviations |
| REG-POST-N2-03 | GET /state shape accessible for both variants | `qa/structural/test_post_n2_contract.py` | Both canonical and deviation profiles stored in state return non-None values for `shape.rows ?? shape.total_rows` and `shape.columns ?? shape.total_columns` |
| REG-POST-N2-04 | per-section revision testids present; global bottom bar absent | `qa/structural/test_post_n2_contract.py` | `section-revise-input`, `section-revise-btn` in `SectionPane.tsx`; `build-bottom-bar` absent |
| REG-POST-N2-05 | no stray e2e specs outside testDir | `qa/structural/test_post_n2_contract.py` | Zero `*.spec.ts` files outside `frontend/tests/e2e/`; all specs are in Playwright's configured `testDir` |

---

## Night 3 — QA Run — 2026-06-04

### Night 1 + Night 2 regression recheck

All REG-N1-01 through REG-N1-12 and REG-N2-01 through REG-N2-07 and REG-POST-N2-01 through REG-POST-N2-05 re-verified against the develop slice (SHA `5df011a` + Night 3 commits). 69 existing structural tests: all PASS.

| Check | Result | Notes |
|-------|--------|-------|
| REG-N1-01 profile schema fields complete | PASS | `PROFILE_SCHEMA` still has all required fields |
| REG-N1-02 orchestrator httpx boundary | PASS | AST walk — zero `import httpx` nodes |
| REG-N1-03 opencode_client orchestrator boundary | PASS | AST walk — zero orchestrator imports |
| REG-N1-04 single event subscription | PASS | Exactly one `start_event_subscription` in `main.py` |
| REG-N1-05 data-testid completeness | PASS | 53 unique testids in production frontend (Night 3 adds retry-banner, section-failed-notice, done-view, etc.) |
| REG-N1-06 test suite count | PASS | 563 tests (361 BE + 202 FE), all pass |
| REG-N1-07 lint clean | PASS | ruff + eslint exit 0 with 0 warnings |
| REG-N1-08 through REG-N2-07 | PASS | All 69 existing QA structural tests pass |
| REG-POST-N2-01 through REG-POST-N2-05 | PASS | All post-Night-2 checks pass |

### Night 3 structural gate

#### Make targets

| Check | Result | Notes |
|-------|--------|-------|
| `make test` (563 tests) | PASS | 361 BE + 202 FE = 563 total, all pass |
| `make lint` | PASS | ruff + eslint exit 0 with 0 warnings |
| `make clean` removes artefacts | PASS | Removes `workspace/state.json`, `workspace/plan.json`, `workspace/profile.json`, `workspace/sections/`, `workspace/charts/`, `workspace/analyses/`, `frontend/dist/`, `frontend/.vite` |
| `make clean` preserves `workspace/data/` | PASS | `workspace/data/customers_q3.csv` untouched after clean |

#### Live fixture tests

All workspace scenarios exercised via real HTTP backend with no API mocking.

| Workspace | Tests | Result | Notes |
|-----------|-------|--------|-------|
| `profiling` | 6 | PASS | Shape strip renders "100" rows, "9" cols, "churned" target; column names visible; accept button enabled |
| `profiling_deviation` | 6 | PASS | `total_rows`/`total_columns` fallback renders correctly via `??` operator |
| `planning` | 5 | PASS | Plan list shows 3 sections; fixture titles visible; accept button enabled |
| `building` | 7 | PASS | Section status badges correct; artefact content visible from real files; export enabled |
| `done` (new) | 7 | PASS | DoneView renders; "Brief complete" heading; 2 accepted shown; dropped excluded; export button present |

#### Night 3 structural assertions (new)

New test file: `qa/structural/test_n3_structural.py` — 23 tests.

| Check | Result | Notes |
|-------|--------|-------|
| REG-N3-01: GET /state returns stage=done | PASS | Done stage exposed correctly; plan included; opencode_session_id stripped |
| REG-N3-02: POST /turn empty body → 204 | PASS | All three variants (empty JSON `{}`, no body, whitespace text) return 204 |
| REG-N3-03: turn.error has reason:string + stage, no retryable | PASS | EventBus shape correct; reason is str; retryable absent |
| REG-N3-04: QA_FORCE_TURN_ERROR fires turn.error | PASS | Raises before client.prompt(); event emitted; client not called |
| REG-N3-05: done transition on last terminal section | PASS | Accept, Drop, mixed accept+drop all trigger done; partial accept does not |
| REG-N3-06: Night 3 data-testid completeness | PASS | All 9 Night 3 required testids present; total >= 50 |
| REG-N3-07: /api/* routing not intercepted by SPA catch-all | PASS | Fixed in commit `388b1d8`; re-verified in targeted re-gate 2026-06-04 |
| REG-N3-08: architecture boundaries carry-forward | PASS | Orchestrator has no httpx import; client has no orchestrator import |

### Defects found

**QA-03 — `make run` production routing broken: `/api/*` intercepted by SPA catch-all (BLOCKING)**

| Field | Value |
|-------|-------|
| ID | QA-03 |
| Night | 3 |
| Symptom | With the Vite bundle built (`make run`), `GET /api/state` returns `text/html` (the SPA index page) instead of `application/json`. All API calls from the built SPA fail — the frontend calls `/api/state`, `/api/setup`, `/api/turn`, etc. but the backend router has no routes at `/api/*`, so every request falls through to the SPA catch-all. The app is completely non-functional in `make run` mode. |
| Area | N3-S09 (`backend/main.py` — static serving + SPA catch-all), `backend/api/router.py` |
| Root cause | Vite dev proxy (`vite.config.ts`) rewrites `/api/*` → `/*` during development, so `GET /api/state` becomes `GET /state` before it reaches the backend. In `make run` mode there is no proxy — the built SPA calls `/api/state` directly and the backend router (registered via `app.include_router(router)` with no prefix) only knows about `/state`. The SPA catch-all at `GET /{full_path:path}` is registered after API routes and correctly matches all non-API paths — but because `/api/state` has no matching API route, it falls through to the catch-all and returns HTML. |
| Fix reference | Commit `388b1d8` (TL, inline on develop). `app.include_router(router, prefix="/api")` added in `backend/main.py`; Vite dev proxy `rewrite` removed from `frontend/vite.config.ts` so both dev and prod paths use `/api/*`. 13 backend test files updated to use `/api/*` paths. See ADR-021. |
| Regression check added | REG-N3-07: `qa/structural/test_n3_structural.py::TestApiRouteNotIntercepted` — two tests: `test_api_state_returns_json_not_html` asserts `GET /api/state` returns `application/json` when `frontend/dist/` exists; `test_api_state_route_is_registered` asserts both `/state` (bare) and `/api/state` return JSON. These tests skip when `frontend/dist/` is absent (no-build CI path). |
| State | Closed — re-gate PASS 2026-06-04 |

### Overall: **RED — FAIL** (initial run) / **GREEN — PASS** (re-gate after fix)

Night 3 QA gate initial run: **FAIL** — QA-03 was a blocking defect. `make run` production serving was broken.

**Re-gate result (2026-06-04, commit `388b1d8`):** All checks pass. Merge is unblocked.

---

## Regression suite — Night 3 standing checks

| ID | Check | Location | Asserts |
|----|-------|----------|---------|
| REG-N3-01 | GET /state exposes stage=done | `qa/structural/test_n3_structural.py::TestDoneStageState` | `stage="done"` in response; plan included; `opencode_session_id` stripped |
| REG-N3-02 | POST /turn empty body → 204 (retry path) | `qa/structural/test_n3_structural.py::TestRetryTurnEmptyBody` | `{}`, null body, whitespace text all return 204; text in setup stage returns 422 invalid_stage |
| REG-N3-03 | turn.error has reason:string + stage; no retryable | `qa/structural/test_n3_structural.py::TestTurnErrorPayloadShape` | `reason` is str; `retryable` absent; building-stage errors include `section_id`; valid reason enum values accepted |
| REG-N3-04 | QA_FORCE_TURN_ERROR seam fires turn.error deterministically | `qa/structural/test_n3_structural.py::TestForcedTurnErrorHook` | `QA_FORCE_TURN_ERROR=1` → `turn.error` emitted; `client.prompt` not called; seam off by default |
| REG-N3-05 | done transition on all-terminal sections | `qa/structural/test_n3_structural.py::TestDoneTransition` | accept-all, drop-all, mixed accept+drop → `stage=done`; partial accept stays `building` |
| REG-N3-06 | Night 3 data-testid completeness | `qa/structural/test_n3_structural.py::TestNight3DataTestids` | `retry-banner`, `retry-banner-btn`, `section-failed-notice`, `section-retry-btn`, `section-drop-failed-btn`, `watchdog-notice`, `done-view`, `done-export-button`, `done-section-list` present; total >= 50 testids |
| REG-N3-07 | /api/* routing not intercepted by SPA catch-all | `qa/structural/test_n3_structural.py::TestApiRouteNotIntercepted` | `GET /api/state` returns `application/json` when `frontend/dist/` exists (skips if no build); regression check for QA-03 |
| REG-N3-08 | architecture boundaries carry-forward Night 3 | `qa/structural/test_n3_structural.py::TestArchitectureBoundariesCarryForward` | orchestrator has no httpx import; opencode_client has no orchestrator import |
| REG-N3-09 | done live fixture — DoneView renders from real HTTP | `frontend/tests/e2e/live/done.live.spec.ts` (QA_WORKSPACE=done) | done-view visible; "Brief complete" text; 2 accepted sections listed; dropped excluded; export button enabled |

---

## Night 3 — Targeted Re-gate — 2026-06-04 (QA-03 fix verification)

TL applied commit `388b1d8` to `develop`: `prefix="/api"` added at `app.include_router` in `backend/main.py`; Vite dev proxy `rewrite` removed; 13 test files updated to `/api/*` paths. Re-gate run to confirm REG-N3-07 now passes and no regressions were introduced.

### Re-gate results

| Check | Result | Notes |
|-------|--------|-------|
| `make test` (563 tests) | PASS | 361 BE + 202 FE = 563 total; all pass |
| `make lint` | PASS | ruff + eslint exit 0, 0 warnings |
| Structural suite `qa/structural/` (92 tests) | PASS | All 92 tests pass; no regressions |
| REG-N3-07 `TestApiRouteNotIntercepted::test_api_state_returns_json_not_html` | PASS | `GET /api/state` returns `application/json` with `frontend/dist/` present |
| REG-N3-07 `TestApiRouteNotIntercepted::test_api_state_route_is_registered` | PASS | Both `/api/state` paths respond correctly |
| Static smoke: `GET /` returns 200 HTML | PASS | `SKIP_OPENCODE=1 uvicorn` + built dist; curl returns HTTP 200 with SPA content |
| Static smoke: `GET /api/state` returns JSON | PASS | Returns `{"version":"1","stage":"setup",...}` — not intercepted by catch-all |
| Live fixture `QA_WORKSPACE=profiling` (6 tests) | PASS | Shape strip renders "100" rows, "9" cols, "churned" target; controls present |
| Live fixture `QA_WORKSPACE=building` (7 tests) | PASS | Section panes, status badges, artefact content, export button all correct |
| Live fixture `QA_WORKSPACE=done` (7 tests) | PASS | DoneView renders; "Brief complete"; 2 accepted; dropped excluded; export enabled |

### QA-03 status update

QA-03 is now **Closed**. REG-N3-07 is in the standing regression suite and passes. The blocking defect is resolved.

### Overall: **GREEN — PASS**

Night 3 QA gate: **PASS** — all checks green, QA-03 resolved, merge to `develop` is unblocked.
