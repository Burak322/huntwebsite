from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "clan.db"
DEFAULT_UPLOAD_DIR = BASE_DIR / "data" / "uploads" / "screenshots"
DEFAULT_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    cleaned = raw.strip().lower()
    if cleaned == "":
        return default
    if cleaned in {"1", "true", "yes", "on"}:
        return True
    if cleaned in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean environment value: {raw!r}")


def _parse_positive_int(raw: str | None, default: int, env_name: str) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{env_name} must be > 0, got {value}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    db_path: Path = DEFAULT_DB_PATH
    upload_dir: Path = DEFAULT_UPLOAD_DIR
    static_dir: Path = DEFAULT_STATIC_DIR
    session_ttl_hours: int = 168
    admin_username: str | None = None
    admin_password: str | None = None
    cookie_secure: bool = False
    cookie_name: str = "clan_session"
    max_upload_bytes: int = 15 * 1024 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.db_path, Path):
            object.__setattr__(self, "db_path", Path(self.db_path))
        if not isinstance(self.upload_dir, Path):
            object.__setattr__(self, "upload_dir", Path(self.upload_dir))
        if not isinstance(self.static_dir, Path):
            object.__setattr__(self, "static_dir", Path(self.static_dir))
        if self.session_ttl_hours <= 0:
            raise ValueError("session_ttl_hours must be > 0")
        if self.max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be > 0")
        if self.admin_username is not None:
            stripped = self.admin_username.strip()
            object.__setattr__(self, "admin_username", stripped or None)
        if self.admin_password == "":
            object.__setattr__(self, "admin_password", None)

    @classmethod
    def from_env(cls) -> Settings:
        raw_db = os.getenv("CLAN_DB_PATH", "").strip()
        raw_upload = os.getenv("CLAN_UPLOAD_DIR", "").strip()
        raw_static = os.getenv("CLAN_STATIC_DIR", "").strip()
        raw_user = os.getenv("CLAN_ADMIN_USERNAME")
        raw_pass = os.getenv("CLAN_ADMIN_PASSWORD")

        return cls(
            db_path=Path(raw_db) if raw_db else DEFAULT_DB_PATH,
            upload_dir=Path(raw_upload) if raw_upload else DEFAULT_UPLOAD_DIR,
            static_dir=Path(raw_static) if raw_static else DEFAULT_STATIC_DIR,
            session_ttl_hours=_parse_positive_int(
                os.getenv("CLAN_SESSION_TTL_HOURS"), 168, "CLAN_SESSION_TTL_HOURS"
            ),
            admin_username=raw_user.strip() if raw_user and raw_user.strip() else None,
            admin_password=raw_pass if raw_pass else None,
            cookie_secure=_parse_bool(os.getenv("CLAN_COOKIE_SECURE"), default=False),
            max_upload_bytes=_parse_positive_int(
                os.getenv("CLAN_MAX_UPLOAD_BYTES"), 15 * 1024 * 1024, "CLAN_MAX_UPLOAD_BYTES"
            ),
        )
