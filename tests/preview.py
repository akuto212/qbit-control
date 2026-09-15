"""Local browser QA with a simulated qBittorrent; no real credentials or network calls.

Run: uv run --extra dev python -m tests.preview
"""

import httpx
import uvicorn

from app.config import Settings
from app.main import create_app
from tests.test_app import KEY, Upstream

if __name__ == "__main__":
    upstream = Upstream()
    upstream.mode = 1
    app = create_app(
        Settings(
            qbit_url="http://qbittorrent:8080",
            qbit_api_key=KEY,
            app_origin="http://127.0.0.1:8000",
        ),
        transport=httpx.MockTransport(upstream.handle),
    )
    uvicorn.run(app, host="127.0.0.1", port=8000, proxy_headers=False, access_log=False)
