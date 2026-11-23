from __future__ import annotations

import json
import sqlite3
from typing import Any

_ALLOWED_UPDATE_COLUMNS = frozenset(
    {"label", "unit", "options_json", "is_required", "is_active", "sort_order"}
)


def row_to_field_dict(row: sqlite3.Row) -> dict[str, Any]:
    raw_options = row["options_json"]
    options: list[str] | None = None
    if raw_options is not None:
        parsed = json.loads(raw_options)
        if isinstance(parsed, list):
            options = [str(item) for item in parsed]

    return {
        "id": int(row["id"]),
        "field_key": str(row["field_key"]),
        "label": str(row["label"]),
        "scope": str(row["scope"]),
        "field_type": str(row["field_type"]),
        "unit": str(row["unit"]) if row["unit"] is not None else None,
        "options": options,
        "is_required": bool(row["is_required"]),
        "is_active": bool(row["is_active"]),
        "sort_order": int(row["sort_order"]),
        "created_at": str(row["created_at"]),
    }


def list_fields(
    conn: sqlite3.Connection,
    *,
    scope: str | None = None,
    active_only: bool = False,
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, field_key, label, scope, field_type, unit, options_json,
               is_required, is_active, sort_order, created_at
        FROM tracking_fields
        WHERE (? IS NULL OR scope = ?)
          AND (? = 0 OR is_active = 1)
        ORDER BY sort_order ASC, id ASC
        """,
        (scope, scope, 1 if active_only else 0),
    ).fetchall()


def get_field_by_id(conn: sqlite3.Connection, field_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, field_key, label, scope, field_type, unit, options_json,
               is_required, is_active, sort_order, created_at
        FROM tracking_fields
        WHERE id = ?
        """,
        (field_id,),
    ).fetchone()


def get_field_by_key(conn: sqlite3.Connection, field_key: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, field_key, label, scope, field_type, unit, options_json,
               is_required, is_active, sort_order, created_at
        FROM tracking_fields
        WHERE field_key = ?
        """,
        (field_key,),
    ).fetchone()


def list_all_field_keys(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT field_key FROM tracking_fields").fetchall()
    return {str(row["field_key"]) for row in rows}


def create_field(
    conn: sqlite3.Connection,
    *,
    field_key: str,
    label: str,
    scope: str,
    field_type: str,
    unit: str | None,
    options_json: str | None,
    is_required: int,
    is_active: int,
    sort_order: int,
    created_at: str,
) -> sqlite3.Row:
    cursor = conn.execute(
        """
        INSERT INTO tracking_fields (
            field_key, label, scope, field_type, unit, options_json,
            is_required, is_active, sort_order, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            field_key,
            label,
            scope,
            field_type,
            unit,
            options_json,
            is_required,
            is_active,
            sort_order,
            created_at,
        ),
    )
    row = get_field_by_id(conn, int(cursor.lastrowid))
    assert row is not None
    return row


def update_field(
    conn: sqlite3.Connection,
    field_id: int,
    updates: dict[str, Any],
) -> sqlite3.Row | None:
    if not updates:
        return get_field_by_id(conn, field_id)

    invalid_cols = set(updates.keys()) - _ALLOWED_UPDATE_COLUMNS
    if invalid_cols:
        raise ValueError(f"Unsupported tracking_fields update columns: {sorted(invalid_cols)}")

    assignments = [f"{col} = ?" for col in updates.keys()]
    params = list(updates.values())
    params.append(field_id)
    conn.execute(
        f"UPDATE tracking_fields SET {', '.join(assignments)} WHERE id = ?",
        params,
    )
    return get_field_by_id(conn, field_id)


def is_field_referenced(conn: sqlite3.Connection, field_key: str) -> bool:
    row = conn.execute(
        """
        SELECT (
            EXISTS(
                SELECT 1
                FROM players, json_each(players.profile_values_json) AS j
                WHERE json_valid(players.profile_values_json)
                  AND j.key = ?
                  AND j.type != 'null'
                  AND NOT (j.type = 'text' AND j.value = '')
            )
            OR EXISTS(
                SELECT 1
                FROM progression_entries, json_each(progression_entries.metrics_json) AS j
                WHERE json_valid(progression_entries.metrics_json)
                  AND j.key = ?
                  AND j.type != 'null'
                  AND NOT (j.type = 'text' AND j.value = '')
            )
        ) AS is_referenced
        """,
        (field_key, field_key),
    ).fetchone()
    return bool(row is not None and row["is_referenced"])


def archive_field(conn: sqlite3.Connection, field_id: int) -> sqlite3.Row | None:
    conn.execute("UPDATE tracking_fields SET is_active = 0 WHERE id = ?", (field_id,))
    return get_field_by_id(conn, field_id)


def delete_field(conn: sqlite3.Connection, field_id: int) -> bool:
    cursor = conn.execute("DELETE FROM tracking_fields WHERE id = ?", (field_id,))
    return cursor.rowcount > 0
