from __future__ import annotations

import sqlite3


def count_admins(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS cnt FROM admin_users").fetchone()
    return int(row["cnt"]) if row is not None else 0


def get_admin_by_id(conn: sqlite3.Connection, admin_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, username, password_hash, created_at, updated_at FROM admin_users WHERE id = ?",
        (admin_id,),
    ).fetchone()


def get_admin_by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, username, password_hash, created_at, updated_at FROM admin_users WHERE username = ?",
        (username,),
    ).fetchone()


def create_admin(
    conn: sqlite3.Connection,
    username: str,
    password_hash: str,
    now_iso: str,
) -> sqlite3.Row:
    cursor = conn.execute(
        """
        INSERT INTO admin_users (username, password_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (username, password_hash, now_iso, now_iso),
    )
    admin_id = cursor.lastrowid
    row = get_admin_by_id(conn, int(admin_id))
    assert row is not None
    return row


def update_admin_password(
    conn: sqlite3.Connection,
    admin_id: int,
    password_hash: str,
    now_iso: str,
) -> None:
    conn.execute(
        """
        UPDATE admin_users
        SET password_hash = ?, updated_at = ?
        WHERE id = ?
        """,
        (password_hash, now_iso, admin_id),
    )


def create_session(
    conn: sqlite3.Connection,
    token_hash: str,
    admin_id: int,
    expires_at_iso: str,
    now_iso: str,
) -> None:
    conn.execute(
        """
        INSERT INTO admin_sessions (token_hash, admin_id, expires_at, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (token_hash, admin_id, expires_at_iso, now_iso),
    )


def get_session_with_admin(
    conn: sqlite3.Connection,
    token_hash: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT s.token_hash, s.admin_id, s.expires_at, s.created_at, u.username
        FROM admin_sessions s
        JOIN admin_users u ON u.id = s.admin_id
        WHERE s.token_hash = ?
        """,
        (token_hash,),
    ).fetchone()


def delete_session(conn: sqlite3.Connection, token_hash: str) -> None:
    conn.execute(
        "DELETE FROM admin_sessions WHERE token_hash = ?",
        (token_hash,),
    )


def delete_other_sessions(
    conn: sqlite3.Connection,
    admin_id: int,
    keep_token_hash: str,
) -> None:
    conn.execute(
        "DELETE FROM admin_sessions WHERE admin_id = ? AND token_hash != ?",
        (admin_id, keep_token_hash),
    )


def delete_expired_sessions(conn: sqlite3.Connection, now_iso: str) -> int:
    cursor = conn.execute(
        "DELETE FROM admin_sessions WHERE expires_at <= ?",
        (now_iso,),
    )
    return cursor.rowcount


def get_setting(
    conn: sqlite3.Connection,
    key: str,
    default: str | None = None,
) -> str | None:
    row = conn.execute(
        "SELECT value FROM system_settings WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return default
    return str(row["value"])


def upsert_setting(
    conn: sqlite3.Connection,
    key: str,
    value: str,
    now_iso: str,
) -> None:
    conn.execute(
        """
        INSERT INTO system_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, value, now_iso),
    )
