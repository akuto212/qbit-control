import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, validated_origin
from app.qbit import Qbit, QbitUnavailable

ROOT = Path(__file__).resolve().parent
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "connect-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def same_origin_post(request: Request, expected: str) -> bool:
    if request.headers.get("x-qbt-control") != "1":
        return False
    if request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}:
        return False
    if "origin" in request.headers:
        # Origin is authoritative even if it is null, empty or malformed.
        return request.headers["origin"] == expected
    try:
        referer = urlsplit(request.headers.get("referer", ""))
        if referer.username is not None or referer.password is not None:
            return False
        actual = validated_origin(f"{referer.scheme}://{referer.netloc}", "Referer")
        return actual == expected
    except ValueError:
        return False


def create_app(settings: Settings | None = None, *, transport=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings or Settings.from_env()
        async with httpx.AsyncClient(
            base_url=config.qbit_url,
            headers={"Authorization": f"Bearer {config.qbit_api_key}"},
            timeout=httpx.Timeout(4.0, connect=2.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            app.state.qbit = Qbit(client)
            app.state.origin = config.app_origin
            yield

    app = FastAPI(
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
    )

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.method == "POST" and not same_origin_post(request, app.state.origin):
            response = JSONResponse({"error": "Request origin rejected"}, status_code=403)
        else:
            response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "templates" / "index.html")

    @app.get("/healthz")
    async def health():
        # Liveness must not restart the service when qBittorrent is offline.
        return {"status": "ok"}

    async def perform(operation):
        try:
            # Absolute deadline also bounds lock waits and slow streaming responses.
            async with asyncio.timeout(8):
                return await operation
        except (QbitUnavailable, TimeoutError):
            return JSONResponse(
                {"online": False, "error": "qBittorrent unavailable"},
                status_code=503,
            )

    @app.get("/api/status")
    async def status():
        return await perform(app.state.qbit.status())

    @app.post("/api/limit/on")
    async def limit_on():
        return await perform(app.state.qbit.set_limit(True))

    @app.post("/api/limit/off")
    async def limit_off():
        return await perform(app.state.qbit.set_limit(False))

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app
