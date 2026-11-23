from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.services import auth_service
from app.services.auth_service import (
    AdminAlreadyExistsError,
    InvalidCredentialsError,
    ValidationError,
)


def test_scrypt_hash_format_and_verify() -> None:
    stored = auth_service.hash_password("GizliSifre123!")
    assert stored.startswith("scrypt$16384$8$1$")
    assert len(stored.split("$")) == 6

    assert auth_service.verify_password("GizliSifre123!", stored) is True
    assert auth_service.verify_password("YanlisSifre", stored) is False
    assert auth_service.verify_password("", stored) is False
    assert auth_service.verify_password("GizliSifre123!", "invalid$hash") is False
    assert auth_service.verify_password("GizliSifre123!", "scrypt$abc$8$1$00$00") is False


def test_scrypt_salt_uniqueness() -> None:
    h1 = auth_service.hash_password("AyniSifre99")
    h2 = auth_service.hash_password("AyniSifre99")
    assert h1 != h2
    assert auth_service.verify_password("AyniSifre99", h1) is True
    assert auth_service.verify_password("AyniSifre99", h2) is True


def test_session_token_hashed_in_sqlite(db_conn: sqlite3.Connection) -> None:
    admin, _, raw_token = auth_service.setup_initial_admin(
        db_conn,
        username="klanlideri",
        password="Password123!",
        clan_name="Bozkurtlar",
        ttl_hours=24,
    )
    assert admin.username == "klanlideri"
    assert len(raw_token) >= 32

    rows = db_conn.execute("SELECT token_hash, admin_id FROM admin_sessions").fetchall()
    assert len(rows) == 1
    expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    assert rows[0]["token_hash"] == expected_hash
    assert rows[0]["token_hash"] != raw_token
    assert rows[0]["admin_id"] == admin.id


def test_session_lookup_and_expiry_pruning(db_conn: sqlite3.Connection) -> None:
    admin, _, valid_token = auth_service.setup_initial_admin(
        db_conn,
        username="admin1",
        password="Password123!",
        ttl_hours=24,
    )
    session = auth_service.authenticate_session(db_conn, valid_token)
    assert session is not None
    assert session.admin.id == admin.id
    assert session.admin.username == "admin1"

    expired_token, _ = auth_service.create_session_for_admin(db_conn, admin.id, ttl_hours=24)
    expired_hash = auth_service.hash_session_token(expired_token)
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db_conn.execute(
        "UPDATE admin_sessions SET expires_at = ? WHERE token_hash = ?",
        (past_iso, expired_hash),
    )
    db_conn.commit()

    assert auth_service.authenticate_session(db_conn, expired_token) is None
    remaining = db_conn.execute(
        "SELECT 1 FROM admin_sessions WHERE token_hash = ?",
        (expired_hash,),
    ).fetchone()
    assert remaining is None


def test_setup_validation_and_duplicate_conflict(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValidationError):
        auth_service.setup_initial_admin(db_conn, username="   ", password="Password123!")

    with pytest.raises(ValidationError):
        auth_service.setup_initial_admin(db_conn, username="lider", password="12345")

    admin, clan_name, _ = auth_service.setup_initial_admin(
        db_conn, username="lider", password="Password123!"
    )
    assert admin.username == "lider"
    assert clan_name == "Klanım"

    with pytest.raises(AdminAlreadyExistsError):
        auth_service.setup_initial_admin(db_conn, username="lider2", password="Password123!")


def test_login_success_trimmed_username_and_failure(db_conn: sqlite3.Connection) -> None:
    auth_service.setup_initial_admin(
        db_conn,
        username="komutan",
        password="SecretPass!1",
        clan_name="Anka",
    )

    admin, clan_name, raw_token = auth_service.login_admin(
        db_conn,
        username="  komutan  ",
        password="SecretPass!1",
        ttl_hours=24,
    )
    assert admin.username == "komutan"
    assert clan_name == "Anka"
    assert len(raw_token) >= 32

    with pytest.raises(InvalidCredentialsError):
        auth_service.login_admin(db_conn, username="komutan", password="WrongPassword")

    with pytest.raises(InvalidCredentialsError):
        auth_service.login_admin(db_conn, username="yok", password="SecretPass!1")


def test_change_password_invalidates_other_sessions(db_conn: sqlite3.Connection) -> None:
    admin, _, primary_token = auth_service.setup_initial_admin(
        db_conn,
        username="lider",
        password="OldPassword1!",
        ttl_hours=24,
    )
    secondary_token, _ = auth_service.create_session_for_admin(db_conn, admin.id, ttl_hours=24)
    primary_hash = auth_service.hash_session_token(primary_token)

    with pytest.raises(InvalidCredentialsError):
        auth_service.change_password(
            db_conn,
            admin_id=admin.id,
            current_password="WrongOldPassword",
            new_password="NewPassword2!",
            current_token_hash=primary_hash,
        )

    auth_service.change_password(
        db_conn,
        admin_id=admin.id,
        current_password="OldPassword1!",
        new_password="NewPassword2!",
        current_token_hash=primary_hash,
    )

    # Current session remains valid; other sessions are invalidated
    assert auth_service.authenticate_session(db_conn, primary_token) is not None
    assert auth_service.authenticate_session(db_conn, secondary_token) is None

    # Old password fails; new password succeeds
    with pytest.raises(InvalidCredentialsError):
        auth_service.login_admin(db_conn, username="lider", password="OldPassword1!")
    logged_in, _, _ = auth_service.login_admin(
        db_conn, username="lider", password="NewPassword2!"
    )
    assert logged_in.id == admin.id
