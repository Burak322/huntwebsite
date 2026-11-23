from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.repositories import auth_repo

SCRYPT_N = 2**14  # 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_MAXMEM = 32 * 1024 * 1024  # 32 MiB


class AuthError(Exception):
    """Base authentication domain error."""


class AdminAlreadyExistsError(AuthError):
    """Raised when attempting initial setup after an admin already exists."""


class InvalidCredentialsError(AuthError):
    """Raised on invalid login or current password mismatch."""


class ValidationError(AuthError):
    """Raised on invalid user input."""


@dataclass(frozen=True, slots=True)
class AdminIdentity:
    id: int
    username: str


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    admin: AdminIdentity
    token_hash: str
    expires_at: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_iso() -> str:
    return format_utc(utc_now())


def parse_utc(ts: str) -> datetime:
    cleaned = ts.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        maxmem=SCRYPT_MAXMEM,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


_DUMMY_PASSWORD_HASH = hash_password("timing-protection-dummy-secret")


def verify_password(password: str, stored_hash: str) -> bool:
    if not isinstance(password, str) or not isinstance(stored_hash, str):
        return False
    parts = stored_hash.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n = int(parts[1])
        r = int(parts[2])
        p = int(parts[3])
        salt = bytes.fromhex(parts[4])
        expected = bytes.fromhex(parts[5])
        if n <= 1 or r <= 0 or p <= 0 or not salt or not expected:
            return False
        maxmem = max(SCRYPT_MAXMEM, 128 * n * r * p + 1024 * 1024)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            maxmem=maxmem,
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def validate_username(username: str) -> str:
    if not isinstance(username, str):
        raise ValidationError("Kullanıcı adı metin olmalıdır.")
    cleaned = username.strip()
    if not (1 <= len(cleaned) <= 64):
        raise ValidationError("Kullanıcı adı 1 ile 64 karakter arasında olmalıdır.")
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValidationError("Kullanıcı adı geçersiz kontrol karakterleri içeremez.")
    return cleaned


def validate_password(password: str) -> str:
    if not isinstance(password, str):
        raise ValidationError("Şifre metin olmalıdır.")
    if len(password) < 6 or len(password) > 256:
        raise ValidationError("Şifre en az 6, en fazla 256 karakter olmalıdır.")
    return password


def validate_clan_name(clan_name: str) -> str:
    if not isinstance(clan_name, str):
        raise ValidationError("Klan adı metin olmalıdır.")
    cleaned = clan_name.strip()
    if not (1 <= len(cleaned) <= 80):
        raise ValidationError("Klan adı 1 ile 80 karakter arasında olmalıdır.")
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValidationError("Klan adı geçersiz kontrol karakterleri içeremez.")
    return cleaned


def create_session_for_admin(
    conn: sqlite3.Connection,
    admin_id: int,
    ttl_hours: int,
) -> tuple[str, str]:
    now = utc_now()
    now_iso = format_utc(now)
    auth_repo.delete_expired_sessions(conn, now_iso)

    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(raw_token)
    expires_at_iso = format_utc(now + timedelta(hours=ttl_hours))
    auth_repo.create_session(conn, token_hash, admin_id, expires_at_iso, now_iso)
    conn.commit()
    return raw_token, expires_at_iso


def authenticate_session(
    conn: sqlite3.Connection,
    raw_token: str | None,
) -> AuthenticatedSession | None:
    if not raw_token or not isinstance(raw_token, str):
        return None
    token_hash = hash_session_token(raw_token)
    row = auth_repo.get_session_with_admin(conn, token_hash)
    if row is None:
        return None
    if parse_utc(row["expires_at"]) <= utc_now():
        auth_repo.delete_session(conn, token_hash)
        conn.commit()
        return None
    return AuthenticatedSession(
        admin=AdminIdentity(id=int(row["admin_id"]), username=str(row["username"])),
        token_hash=str(row["token_hash"]),
        expires_at=str(row["expires_at"]),
    )


def get_clan_name(conn: sqlite3.Connection) -> str:
    value = auth_repo.get_setting(conn, "clan_name", "Klanım")
    return value if value else "Klanım"


def update_clan_name(conn: sqlite3.Connection, clan_name: str) -> str:
    cleaned = validate_clan_name(clan_name)
    auth_repo.upsert_setting(conn, "clan_name", cleaned, utc_now_iso())
    conn.commit()
    return cleaned


def setup_initial_admin(
    conn: sqlite3.Connection,
    username: str,
    password: str,
    clan_name: str | None = None,
    ttl_hours: int = 168,
) -> tuple[AdminIdentity, str, str]:
    clean_username = validate_username(username)
    clean_password = validate_password(password)

    clean_clan_name: str | None = None
    if clan_name is not None:
        stripped_clan = clan_name.strip()
        if stripped_clan:
            clean_clan_name = validate_clan_name(stripped_clan)

    now_iso = utc_now_iso()
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        if auth_repo.count_admins(conn) > 0:
            conn.rollback()
            raise AdminAlreadyExistsError("Yönetici hesabı zaten oluşturulmuş.")

        pw_hash = hash_password(clean_password)
        admin_row = auth_repo.create_admin(conn, clean_username, pw_hash, now_iso)
        if clean_clan_name is not None:
            auth_repo.upsert_setting(conn, "clan_name", clean_clan_name, now_iso)
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise AdminAlreadyExistsError("Yönetici hesabı zaten oluşturulmuş.") from exc

    admin = AdminIdentity(id=int(admin_row["id"]), username=str(admin_row["username"]))
    raw_token, _ = create_session_for_admin(conn, admin.id, ttl_hours)
    effective_clan_name = get_clan_name(conn)
    return admin, effective_clan_name, raw_token


def login_admin(
    conn: sqlite3.Connection,
    username: str,
    password: str,
    ttl_hours: int = 168,
) -> tuple[AdminIdentity, str, str]:
    clean_username = username.strip() if isinstance(username, str) else ""
    if not clean_username or not isinstance(password, str) or not password:
        verify_password("invalid", _DUMMY_PASSWORD_HASH)
        raise InvalidCredentialsError("Kullanıcı adı veya şifre hatalı.")

    row = auth_repo.get_admin_by_username(conn, clean_username)
    if row is None:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise InvalidCredentialsError("Kullanıcı adı veya şifre hatalı.")

    if not verify_password(password, str(row["password_hash"])):
        raise InvalidCredentialsError("Kullanıcı adı veya şifre hatalı.")

    admin = AdminIdentity(id=int(row["id"]), username=str(row["username"]))
    raw_token, _ = create_session_for_admin(conn, admin.id, ttl_hours)
    clan_name = get_clan_name(conn)
    return admin, clan_name, raw_token


def logout_session(conn: sqlite3.Connection, token_hash: str) -> None:
    auth_repo.delete_session(conn, token_hash)
    conn.commit()


def change_password(
    conn: sqlite3.Connection,
    admin_id: int,
    current_password: str,
    new_password: str,
    current_token_hash: str | None = None,
) -> None:
    validate_password(new_password)
    admin_row = auth_repo.get_admin_by_id(conn, admin_id)
    if admin_row is None or not verify_password(current_password, str(admin_row["password_hash"])):
        raise InvalidCredentialsError("Mevcut şifre hatalı.")

    new_hash = hash_password(new_password)
    auth_repo.update_admin_password(conn, admin_id, new_hash, utc_now_iso())
    if current_token_hash:
        auth_repo.delete_other_sessions(conn, admin_id, current_token_hash)
    conn.commit()


def get_auth_status(conn: sqlite3.Connection, raw_token: str | None) -> dict:
    needs_setup = auth_repo.count_admins(conn) == 0
    clan_name = get_clan_name(conn)
    session = None if needs_setup else authenticate_session(conn, raw_token)
    return {
        "needsSetup": needs_setup,
        "authenticated": session is not None,
        "admin": {"id": session.admin.id, "username": session.admin.username}
        if session is not None
        else None,
        "clanName": clan_name,
    }
