from contextlib import contextmanager
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

KEY = "qbt_" + "a" * 28
ORIGIN = "https://qbt-control.example.com"
POST_HEADERS = {"Origin": ORIGIN, "X-QBT-Control": "1"}


class Upstream:
    def __init__(self):
        self.mode = 0
        self.requests = []
        self.failure = None
        self.overrides = {}

    def handle(self, request):
        self.requests.append(request)
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert "cookie" not in request.headers
        if self.failure:
            if isinstance(self.failure, Exception):
                raise self.failure
            return httpx.Response(self.failure, text=f"upstream secret {KEY}")
        path = request.url.path
        if path in self.overrides:
            return self.overrides[path]
        if path == "/api/v2/transfer/info":
            return httpx.Response(200, json={"dl_info_speed": 18234567, "up_info_speed": 1845223})
        if path == "/api/v2/transfer/speedLimitsMode":
            return httpx.Response(200, text=str(self.mode))
        if path == "/api/v2/app/preferences":
            return httpx.Response(
                200,
                json={
                    "alt_dl_limit": 20971520,
                    "alt_up_limit": 2097152,
                    "web_ui_password": KEY,
                    "proxy_password": "private",
                },
            )
        if path == "/api/v2/transfer/setSpeedLimitsMode":
            assert request.method == "POST"
            assert request.headers["content-type"] == "application/x-www-form-urlencoded"
            self.mode = int(parse_qs(request.content.decode())["mode"][0])
            return httpx.Response(200, text="")
        raise AssertionError(f"Unexpected upstream endpoint: {path}")


@contextmanager
def running(upstream=None):
    upstream = upstream or Upstream()
    settings = Settings(qbit_url="http://qbittorrent:8080", qbit_api_key=KEY, app_origin=ORIGIN)
    app = create_app(settings, transport=httpx.MockTransport(upstream.handle))
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, upstream


def test_status_is_read_only_and_selects_only_public_fields():
    with running() as (client, upstream):
        response = client.get("/api/status")
        assert response.status_code == 200
        assert response.json() == {
            "online": True,
            "speed_limit_enabled": False,
            "download_speed": 18234567,
            "upload_speed": 1845223,
            "download_speed_formatted": "17.4 MiB/s",
            "upload_speed_formatted": "1.8 MiB/s",
            "alt_download_limit": 20971520,
            "alt_upload_limit": 2097152,
            "alt_download_limit_formatted": "20 MiB/s",
            "alt_upload_limit_formatted": "2 MiB/s",
        }
        assert all(r.method == "GET" for r in upstream.requests)
        assert KEY not in response.text
        assert "private" not in response.text
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("action,mode", [("on", 1), ("off", 0)])
def test_explicit_actions_are_idempotent_and_confirmed(action, mode):
    with running() as (client, upstream):
        upstream.mode = 1 - mode
        for _ in range(2):
            response = client.post(f"/api/limit/{action}", headers=POST_HEADERS)
            assert response.status_code == 200
            assert response.json() == {"online": True, "speed_limit_enabled": bool(mode)}
            assert upstream.mode == mode
        writes = [r for r in upstream.requests if r.method == "POST"]
        assert len(writes) == 2
        assert all(r.url.path == "/api/v2/transfer/setSpeedLimitsMode" for r in writes)
        assert all(r.content == f"mode={mode}".encode() for r in writes)


@pytest.mark.parametrize(
    "failure",
    [
        401,
        403,
        404,
        500,
        302,
        httpx.ReadTimeout("contains " + KEY),
        httpx.ConnectError("contains " + KEY),
    ],
)
def test_upstream_failures_are_generic_and_recoverable(failure, caplog):
    with running() as (client, upstream):
        upstream.failure = failure
        for method, path, headers in [
            ("GET", "/api/status", {}),
            ("POST", "/api/limit/on", POST_HEADERS),
        ]:
            response = client.request(method, path, headers=headers)
            assert response.status_code == 503
            assert response.json() == {"online": False, "error": "qBittorrent unavailable"}
            assert KEY not in response.text
        upstream.failure = None
        assert client.get("/api/status").json()["online"] is True
        assert KEY not in caplog.text


@pytest.mark.parametrize(
    "path,response",
    [
        ("transfer/info", httpx.Response(200, text="not json")),
        ("transfer/info", httpx.Response(200, json=[])),
        ("transfer/info", httpx.Response(200, json={"dl_info_speed": -1, "up_info_speed": 1})),
        ("transfer/info", httpx.Response(200, json={"dl_info_speed": True, "up_info_speed": 1})),
        ("transfer/info", httpx.Response(200, json={"dl_info_speed": "12", "up_info_speed": 1})),
        ("transfer/info", httpx.Response(200, json={"dl_info_speed": 12})),
        ("transfer/info", httpx.Response(200, text="x" * (1024 * 1024 + 1))),
        ("transfer/speedLimitsMode", httpx.Response(200, text="2")),
        ("transfer/speedLimitsMode", httpx.Response(200, text="<html>login</html>")),
    ],
)
def test_malformed_required_responses_fail_closed(path, response):
    with running() as (client, upstream):
        upstream.overrides[f"/api/v2/{path}"] = response
        result = client.get("/api/status")
        assert result.status_code == 503
        assert result.json()["online"] is False


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"alt_dl_limit": "bad"}),
    ],
)
def test_optional_preferences_failure_does_not_hide_status(response):
    with running() as (client, upstream):
        upstream.overrides["/api/v2/app/preferences"] = response
        result = client.get("/api/status")
        assert result.status_code == 200
        assert "alt_download_limit" not in result.json()


def test_zero_and_negative_one_configured_limits_mean_unlimited():
    with running() as (client, upstream):
        upstream.overrides["/api/v2/app/preferences"] = httpx.Response(
            200, json={"alt_dl_limit": 0, "alt_up_limit": -1}
        )
        data = client.get("/api/status").json()
        assert data["alt_download_limit_formatted"] == "Unlimited"
        assert data["alt_upload_limit_formatted"] == "Unlimited"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": ORIGIN},
        {"X-QBT-Control": "1"},
        {"Origin": "https://evil.example", "X-QBT-Control": "1"},
        {"Origin": "null", "Referer": ORIGIN + "/", "X-QBT-Control": "1"},
        {"Origin": ORIGIN + ".evil.example", "X-QBT-Control": "1"},
        {"Origin": ORIGIN + "/unexpected", "X-QBT-Control": "1"},
        {"Referer": ORIGIN + "@evil.example/", "X-QBT-Control": "1"},
        {**POST_HEADERS, "Sec-Fetch-Site": "cross-site"},
        {
            "Origin": "https://evil.example",
            "X-QBT-Control": "1",
            "X-Forwarded-Host": "evil.example",
            "X-Forwarded-Proto": "https",
        },
    ],
)
def test_csrf_is_rejected_before_any_upstream_request(headers):
    with running() as (client, upstream):
        assert client.post("/api/limit/on", headers=headers).status_code == 403
        assert not upstream.requests


def test_referer_fallback_for_same_origin():
    with running() as (client, _):
        response = client.post(
            "/api/limit/on",
            headers={
                "Referer": ORIGIN + "/?home=1",
                "X-QBT-Control": "1",
            },
        )
        assert response.status_code == 200


def test_unconfirmed_or_html_write_is_not_reported_as_success():
    with running() as (client, upstream):
        for body in ["", "<html>Login</html>"]:
            upstream.overrides["/api/v2/transfer/setSpeedLimitsMode"] = httpx.Response(
                200, text=body
            )
            assert client.post("/api/limit/on", headers=POST_HEADERS).status_code == 503


def test_page_health_and_assets_do_not_contact_upstream_or_expose_key():
    with running() as (client, upstream):
        for path in ["/", "/static/style.css", "/static/app.js", "/static/icon.svg", "/healthz"]:
            response = client.get(path)
            assert response.status_code == 200
            assert KEY not in response.text
            assert "access-control-allow-origin" not in response.headers
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert not upstream.requests


def test_no_generic_proxy_docs_or_get_mutations():
    with running() as (client, upstream):
        for path in ["/api/v2/app/preferences", "/api/limit/toggle", "/docs", "/openapi.json"]:
            assert client.get(path).status_code == 404
        for path in ["/api/limit/on", "/api/limit/off"]:
            assert client.get(path).status_code == 405
        response = client.options(
            "/api/limit/on",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in response.headers
        assert not upstream.requests


@pytest.mark.parametrize(
    "field,value",
    [
        ("qbit_api_key", ""),
        ("qbit_api_key", "secret\nvalue"),
        ("qbit_url", "http://user:secret@qbittorrent:8080"),
        ("qbit_url", "file:///secret"),
        ("qbit_url", "http://qbittorrent:8080/?key=secret"),
        ("app_origin", "https://qbt.example/path"),
        ("app_origin", "https://qbt.example/#secret"),
    ],
)
def test_invalid_config_errors_do_not_include_values(field, value):
    values = {"qbit_url": "http://qbittorrent:8080", "qbit_api_key": KEY, "app_origin": ORIGIN}
    values[field] = value
    with pytest.raises(ValueError) as error:
        Settings(**values)
    assert "secret" not in str(error.value)


def test_settings_repr_does_not_expose_key():
    settings = Settings(qbit_url="http://qbittorrent:8080", qbit_api_key=KEY, app_origin=ORIGIN)
    assert KEY not in repr(settings)
