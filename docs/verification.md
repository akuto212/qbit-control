# Verification — 2026-09-15

## Passed

- `uv run --extra dev pytest -q`: 47 tests. Covers read-only status, selected response fields, strict numeric parsing, generic upstream errors, recovery, repeated explicit writes, confirmation, CSRF checks, absence of generic proxy/docs, private configuration, optional-preferences cancellation and concurrent write serialization.
- `uv run --extra dev ruff check .`: passed.
- `uv run --extra dev ruff format --check .`: passed.
- `node --check app/static/app.js`: passed.
- `docker compose config --quiet` with test environment values: passed; no real API key used.
- Playwright CLI running `tests/browser-check.js` against `tests.preview`: passed. Browser reload/polling generates GET only; off/on actions, disabled Applying state, double-click protection, POST failure, offline recovery and an HTML login response all behave correctly. All requests stay on the page origin; none carries Authorization.
- Layout checked at 1440×960, 390×844 and 320×568; no horizontal overflow and button touch target ≥44px. Screenshots visually inspected in `output/playwright/`. This is viewport testing, not physical iPhone/Safari testing.
- Independent code review found no blocking security/correctness issue. One slow optional-preferences edge case was reproduced with a failing test, fixed using a separate four-second deadline, and verified.

## Limits

- Docker daemon socket is absent locally. The image was not built or run; Compose configuration validation does not prove a successful image build.
- The actual qBittorrent instance, existing Traefik network, TinyAuth settings and TLS resolver were not available. Official source for qBittorrent `release-5.2.3` was checked; integration tests used an HTTP transport simulation.
- Pytest emits two deprecation warnings from the installed Starlette TestClient dependencies (`httpx` compatibility and an AnyIO alias). There are no failing tests. Production does not import TestClient.
- Two expected browser console network errors came from deliberately injected HTTP 503 responses. No page JavaScript exceptions occurred in the completed browser test.

Deployment checklist and exact environment variables are in `README.md` and `.env.example`.
