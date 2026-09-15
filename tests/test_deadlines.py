import asyncio

import httpx

from app import qbit as qbit_module
from app.qbit import Qbit
from tests.test_app import KEY, Upstream


def test_slow_optional_preferences_do_not_block_required_status(monkeypatch):
    # Shorten the real deadline, not the timer implementation, to keep the test fast.
    monkeypatch.setattr(qbit_module, "PREFERENCES_TIMEOUT", 0.02, raising=False)

    class SlowPreferences(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            while True:
                yield b" "
                await asyncio.sleep(0.005)

        async def aclose(self):
            self.closed = True

    async def exercise():
        stream = SlowPreferences()
        upstream = Upstream()
        upstream.overrides["/api/v2/app/preferences"] = httpx.Response(200, stream=stream)
        async with httpx.AsyncClient(
            base_url="http://qbittorrent:8080",
            headers={"Authorization": f"Bearer {KEY}"},
            transport=httpx.MockTransport(upstream.handle),
        ) as client:
            data = await asyncio.wait_for(Qbit(client).status(), timeout=0.3)
        assert data["online"] is True
        assert data["download_speed"] == 18234567
        assert "alt_download_limit" not in data
        assert stream.closed

    asyncio.run(exercise())


def test_concurrent_writes_are_serialized_through_confirmation():
    async def exercise():
        upstream = Upstream()
        sequence = []

        async def handle(request):
            sequence.append(request.url.path.rsplit("/", 1)[-1])
            response = upstream.handle(request)
            await asyncio.sleep(0.01)
            return response

        async with httpx.AsyncClient(
            base_url="http://qbittorrent:8080",
            headers={"Authorization": f"Bearer {KEY}"},
            transport=httpx.MockTransport(handle),
        ) as client:
            qbit = Qbit(client)
            on, off = await asyncio.gather(qbit.set_limit(True), qbit.set_limit(False))
        assert on["speed_limit_enabled"] is True
        assert off["speed_limit_enabled"] is False
        assert sequence == ["setSpeedLimitsMode", "speedLimitsMode"] * 2
        assert upstream.mode == 0

    asyncio.run(exercise())
