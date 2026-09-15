# qbt-control

A lightweight web interface for controlling qBittorrent's alternative speed limits.

Built with FastAPI and vanilla JavaScript. No database or frontend build step required. Targets qBittorrent 5.2.3.

## Features

- Live download and upload speeds.
- Alternative speed limits status and configured values.
- One-click enable/disable with safe, repeatable actions.
- Automatic refresh and recovery after connection failures.
- Responsive dark interface for desktop and mobile.
- Server-side API key storage.

## Docker

Images: `ghcr.io/akuto212/qbit-control` — available for `linux/amd64` and `linux/arm64`.

Create a private `.env` file:

```dotenv
QBIT_URL=http://qbittorrent:8080
QBIT_API_KEY=replace_with_your_api_key
APP_ORIGIN=http://localhost:8000
```

Generate an API key in qBittorrent under **Settings → Web UI → API Key**. Connect both containers to the same Docker network; replace `media` below with its name.

```bash
docker run -d \
  --name qbt-control \
  --restart unless-stopped \
  --network media \
  --env-file .env \
  -p 127.0.0.1:8000:8000 \
  ghcr.io/akuto212/qbit-control:latest
```

Open **http://localhost:8000**. Set `APP_ORIGIN` to the exact browser-facing origin (scheme, hostname and optional port) when using a different address.

The application has no built-in authentication. For remote access, place it behind an HTTPS reverse proxy with authentication covering all routes. Keep qBittorrent's Web API private and the API key on the server.

## API

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/api/status` | Current speeds and alternative limits |
| POST | `/api/limit/on` | Enable alternative limits |
| POST | `/api/limit/off` | Disable alternative limits |
| GET | `/healthz` | Application health |

POST requests require `X-QBT-Control: 1` and a matching `Origin` (or same-origin `Referer` when Origin is absent). Disabling alternative limits restores qBittorrent's normal limits.

## Development

Requires Python 3.12+ and uv.

```bash
uv sync --frozen --extra dev
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --env-file .env uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

GitHub Actions runs checks and publishes images after successful builds. `latest` tracks the default branch; `v*` and `sha-<commit>` tags identify release and commit builds.
