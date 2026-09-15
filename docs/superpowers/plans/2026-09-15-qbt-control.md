# qbt-control implementation plan

**Goal:** A small internet-facing speed-limit control page for the user's qBittorrent 5.2.3, behind existing Traefik and TinyAuth.

**Architecture:** FastAPI serves static HTML/CSS/JS and exactly three business endpoints. An asynchronous HTTP client talks to fixed qBittorrent endpoints with a server-only Bearer key. No database, login system, generic proxy, or toggle fallback.

**Tech stack:** Python 3.12+, FastAPI, httpx, uvicorn; vanilla JS; pytest; Docker Compose.

## Confirmed API contract

Checked official source at tag `release-5.2.3`:
- `transfer/info`: `dl_info_speed`, `up_info_speed` in bytes/second.
- `transfer/speedLimitsMode`: text `0` or `1`.
- `transfer/setSpeedLimitsMode`: POST form `mode=0` or `mode=1`; empty successful body. Read mode after writing to verify.
- `app/preferences`: `alt_dl_limit`, `alt_up_limit` in bytes/second. Select these two fields only; never forward preferences.
- API key authentication: `Authorization: Bearer <key>`, no cookie login.

## Implementation sequence

- [x] Create `pyproject.toml` and `tests/test_app.py`. Test read-only status, strict response validation, failures/recovery, repeated on/off requests, CSRF rejection before upstream access, static assets without credentials, and excluded API routes. Initial pytest run failed because the app did not yet exist.
- [x] Implement `app/config.py` (validated environment), `app/qbit.py` (bounded HTTP requests, selected fields, mode verification), `app/main.py` (lifespan, security headers, routes). Tests pass. Added cancellation and concurrent-write checks in `tests/test_deadlines.py` after review.
- [x] Add `app/templates/index.html`, `app/static/style.css`, `app/static/app.js`, and an SVG icon. A single large button, disabled while applying, read-only polling every three seconds, immediate refresh after mutation, and no overlapping status requests. JS syntax and browser behavior verified at desktop and mobile viewport sizes.
- [x] Add `Dockerfile`, `docker-compose.yml`, `.env.example`, ignore files and Russian `README.md`. Docker: non-root, no published ports, read-only root, dropped capabilities, healthcheck independent of upstream, two external networks. One Traefik router applies configured TinyAuth/security middleware to every path.
- [x] Run pytest, lint, browser checks and Compose validation. See `docs/verification.md`; Docker build and live server integration remain unverified because infrastructure is unavailable locally.

## Security and deployment decisions

POST requires exact configured `APP_ORIGIN` (Referer fallback only when Origin is absent) plus `X-QBT-Control: 1`. Reject cross-site Fetch Metadata. No CORS. TinyAuth remains the authentication boundary: Docker-network peers are trusted, and the app port must not be published. Do not trust arbitrary forwarded headers; CSRF uses configuration, not request Host or proxy headers. Cookies belong to TinyAuth and should be Secure, HttpOnly, and SameSite=Lax or Strict as appropriate to the existing login flow.

Keep errors generic and upstream details/key out of responses and logs. Redirects to upstream are not followed. Timeouts, malformed JSON, invalid numeric values, failed auth, and nonempty unexpected write responses fail safely. Configured limits are optional if preferences cannot be read; speeds and mode are required. An enabled scheduler or another qBittorrent client can change mode later.

Existing deployment names are unknown: require `.env` values for hostname, network names, TLS resolver and the complete existing middleware chain rather than guessing production names. No actual infrastructure changes are part of local implementation.
