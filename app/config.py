import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


def validated_origin(value: str, name: str) -> str:
    """Accept an HTTP(S) origin, never credentials, query strings or subpaths."""
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "?" in value
            or "#" in value
            or "\\" in value
            or any(c.isspace() or ord(c) < 32 for c in value)
        ):
            raise ValueError
        # Accessing port validates its numeric range.
        port = parsed.port
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        if port is not None and port != {"http": 80, "https": 443}[parsed.scheme]:
            host = f"{host}:{port}"
        return f"{parsed.scheme}://{host}"
    except ValueError:
        raise ValueError(
            f"{name} must be an HTTP(S) origin without credentials or a path"
        ) from None


@dataclass(frozen=True)
class Settings:
    qbit_url: str
    qbit_api_key: str = field(repr=False)
    app_origin: str

    def __post_init__(self):
        object.__setattr__(self, "qbit_url", validated_origin(self.qbit_url, "QBIT_URL"))
        object.__setattr__(self, "app_origin", validated_origin(self.app_origin, "APP_ORIGIN"))
        if not re.fullmatch(r"qbt_[A-Za-z0-9]{28}", self.qbit_api_key):
            raise ValueError("QBIT_API_KEY must be a qBittorrent API key")

    @classmethod
    def from_env(cls):
        return cls(
            qbit_url=os.environ.get("QBIT_URL", "http://qbittorrent:8080"),
            qbit_api_key=os.environ.get("QBIT_API_KEY", ""),
            app_origin=os.environ.get("APP_ORIGIN", ""),
        )
