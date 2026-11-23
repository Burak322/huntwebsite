from __future__ import annotations

import sqlite3
from typing import Any

from app.services.auth_service import utc_now_iso

MAX_DAILY_LIMIT = 2_000_000_000


class LimitValidationError(ValueError):
    pass


def _validate_min_score(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LimitValidationError("Günlük limit tam sayı olmalıdır.")
    if value < 0:
        raise LimitValidationError("Günlük limit negatif olamaz.")
    if value > MAX_DAILY_LIMIT:
        raise LimitValidationError("Günlük limit çok büyük.")
    return value


def get_active_limit(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT value FROM system_settings WHERE key = 'daily_min_score'"
    ).fetchone()
    if row is None:
        return 0
    try:
        return max(0, int(row["value"]))
    except (TypeError, ValueError):
        return 0


def _get_updated_at(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT updated_at FROM system_settings WHERE key = 'daily_min_score'"
    ).fetchone()
    return str(row["updated_at"]) if row is not None else None


def list_history(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, min_score, note, changed_at
        FROM daily_limit_history
        ORDER BY changed_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "minScore": int(r["min_score"]),
            "note": r["note"],
            "changedAt": str(r["changed_at"]),
        }
        for r in rows
    ]


def get_limit_state(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "activeMinScore": get_active_limit(conn),
        "updatedAt": _get_updated_at(conn),
        "history": list_history(conn),
    }


def set_daily_limit(conn: sqlite3.Connection, min_score: Any, note: Any = None) -> dict[str, Any]:
    clean_score = _validate_min_score(min_score)
    clean_note: str | None = None
    if note is not None:
        if not isinstance(note, str):
            raise LimitValidationError("Not metin olmalıdır.")
        clean_note = note.strip()[:500] or None

    now_iso = utc_now_iso()
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO system_settings (key, value, updated_at)
            VALUES ('daily_min_score', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (str(clean_score), now_iso),
        )
        conn.execute(
            "INSERT INTO daily_limit_history (min_score, note, changed_at) VALUES (?, ?, ?)",
            (clean_score, clean_note, now_iso),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return get_limit_state(conn)
