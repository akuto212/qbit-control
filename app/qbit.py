import asyncio
import json

import httpx

PREFERENCES_TIMEOUT = 4.0


class QbitUnavailable(Exception):
    """An upstream error whose details must never reach the browser or logs."""


def integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise QbitUnavailable
    return value


def format_speed(value: int) -> str:
    amount = float(value)
    for unit in ("B/s", "KiB/s", "MiB/s", "GiB/s", "TiB/s", "PiB/s", "EiB/s"):
        if amount < 1024 or unit == "EiB/s":
            return f"{amount:.1f}".removesuffix(".0") + f" {unit}"
        amount /= 1024
    raise AssertionError("unreachable")


class Qbit:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.write_lock = asyncio.Lock()

    async def _request(self, method: str, path: str, *, data=None) -> bytes:
        try:
            async with self.client.stream(method, path, data=data) as response:
                if response.status_code != 200:
                    raise QbitUnavailable
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 1024 * 1024:
                        raise QbitUnavailable
                return bytes(content)
        except httpx.HTTPError:
            raise QbitUnavailable from None

    async def _object(self, path: str) -> dict:
        try:
            result = json.loads(await self._request("GET", path))
        except (ValueError, UnicodeError, RecursionError):
            raise QbitUnavailable from None
        if not isinstance(result, dict):
            raise QbitUnavailable
        return result

    async def mode(self) -> bool:
        mode = (await self._request("GET", "/api/v2/transfer/speedLimitsMode")).strip()
        if mode not in {b"0", b"1"}:
            raise QbitUnavailable
        return mode == b"1"

    async def _limits(self) -> dict:
        try:
            # Optional data must not consume the deadline for required status fields.
            async with asyncio.timeout(PREFERENCES_TIMEOUT):
                prefs = await self._object("/api/v2/app/preferences")
            download = integer(prefs.get("alt_dl_limit"), minimum=-1)
            upload = integer(prefs.get("alt_up_limit"), minimum=-1)
        except (QbitUnavailable, TimeoutError):
            return {}
        return {
            "alt_download_limit": download,
            "alt_upload_limit": upload,
            "alt_download_limit_formatted": format_speed(download) if download > 0 else "Unlimited",
            "alt_upload_limit_formatted": format_speed(upload) if upload > 0 else "Unlimited",
        }

    async def status(self) -> dict:
        # return_exceptions waits for all reads, so a failed request leaves no orphan task.
        info, mode, limits = await asyncio.gather(
            self._object("/api/v2/transfer/info"),
            self.mode(),
            self._limits(),
            return_exceptions=True,
        )
        if any(isinstance(result, BaseException) for result in (info, mode, limits)):
            raise QbitUnavailable
        download = integer(info.get("dl_info_speed"))
        upload = integer(info.get("up_info_speed"))
        return {
            "online": True,
            "speed_limit_enabled": mode,
            "download_speed": download,
            "upload_speed": upload,
            "download_speed_formatted": format_speed(download),
            "upload_speed_formatted": format_speed(upload),
            **limits,
        }

    async def set_limit(self, enabled: bool) -> dict:
        async with self.write_lock:
            body = await self._request(
                "POST",
                "/api/v2/transfer/setSpeedLimitsMode",
                data={"mode": "1" if enabled else "0"},
            )
            if body.strip() or await self.mode() != enabled:
                raise QbitUnavailable
        return {"online": True, "speed_limit_enabled": enabled}
