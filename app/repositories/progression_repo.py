from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import datetime
from typing import Any

from app.services import field_validator
from app.services.auth_service import utc_now_iso

_RECORDED_AT_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)


class ProgressionError(Exception):
    """Base error for progression domain."""


class ProgressionNotFoundError(ProgressionError):
    """Raised when a progression entry or owning player is not found."""


class ProgressionValidationError(ProgressionError):
    """Raised when progression input is invalid."""


def _parse_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _has_multiline_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 and ch not in ("\n", "\r", "\t") for ch in value)


def validate_recorded_at(value: Any) -> str:
    if not isinstance(value, str):
        raise ProgressionValidationError("Kayıt tarihi metin olmalıdır.")
    cleaned = value.strip()
    if not cleaned or not _RECORDED_AT_PATTERN.fullmatch(cleaned):
        raise ProgressionValidationError(
            "Kayıt tarihi geçerli bir ISO-8601 tarih (YYYY-AA-GG) veya tarih-saat olmalıdır."
        )
    try:
        if len(cleaned) == 10:
            datetime.strptime(cleaned, "%Y-%m-%d")
        else:
            iso_candidate = cleaned[:-1] + "+00:00" if cleaned.endswith("Z") else cleaned
            datetime.fromisoformat(iso_candidate)
    except ValueError as exc:
        raise ProgressionValidationError("Kayıt tarihi geçerli bir takvim tarihi olmalıdır.") from exc
    return cleaned


def _validate_note(note: Any) -> str | None:
    if note is None:
        return None
    if not isinstance(note, str):
        raise ProgressionValidationError("Not metin olmalıdır.")
    cleaned = note.strip()
    if not cleaned:
        return None
    if len(cleaned) > 2000:
        raise ProgressionValidationError("Not en fazla 2000 karakter olabilir.")
    if _has_multiline_control_chars(cleaned):
        raise ProgressionValidationError("Not geçersiz kontrol karakterleri içeremez.")
    return cleaned


def _is_real_number(val: Any) -> bool:
    # CRITICAL: bool is a subclass of int in Python.
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val)


def _compute_deltas(
    prev_metrics: dict[str, Any],
    curr_metrics: dict[str, Any],
) -> dict[str, int | float]:
    deltas: dict[str, int | float] = {}
    for key, curr_val in curr_metrics.items():
        if not _is_real_number(curr_val):
            continue
        prev_val = prev_metrics.get(key)
        if not _is_real_number(prev_val):
            continue
        diff = curr_val - prev_val
        if isinstance(curr_val, int) and isinstance(prev_val, int):
            deltas[key] = diff
        else:
            deltas[key] = round(float(diff), 6)
    return deltas


def _row_to_entry(
    row: sqlite3.Row,
    *,
    metrics: dict[str, Any] | None = None,
    deltas: dict[str, int | float] | None = None,
) -> dict[str, Any]:
    resolved_metrics = metrics if metrics is not None else _parse_json_dict(row["metrics_json"])
    entry: dict[str, Any] = {
        "id": int(row["id"]),
        "player_id": int(row["player_id"]),
        "recorded_at": str(row["recorded_at"]),
        "metrics": resolved_metrics,
        "note": str(row["note"]) if row["note"] is not None else None,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }
    if deltas is not None:
        entry["deltas"] = deltas
    return entry


def _player_exists(conn: sqlite3.Connection, player_id: int) -> bool:
    row = conn.execute("SELECT id FROM players WHERE id = ?", (player_id,)).fetchone()
    return row is not None


def get_latest_progression_map(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, player_id, recorded_at, metrics_json, note, created_at, updated_at
        FROM (
            SELECT
                id, player_id, recorded_at, metrics_json, note, created_at, updated_at,
                ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY recorded_at DESC, id DESC) AS rn
            FROM progression_entries
        )
        WHERE rn = 1
        """
    ).fetchall()
    return {int(row["player_id"]): _row_to_entry(row) for row in rows}


def get_latest_progression_for_player(
    conn: sqlite3.Connection,
    player_id: int,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, player_id, recorded_at, metrics_json, note, created_at, updated_at
        FROM progression_entries
        WHERE player_id = ?
        ORDER BY recorded_at DESC, id DESC
        LIMIT 1
        """,
        (player_id,),
    ).fetchone()
    return _row_to_entry(row) if row is not None else None


def list_player_progression(
    conn: sqlite3.Connection,
    player_id: int,
    *,
    order: str = "desc",
) -> list[dict[str, Any]]:
    if order not in ("asc", "desc"):
        raise ProgressionValidationError("Sıralama yönü 'asc' veya 'desc' olmalıdır.")
    if not _player_exists(conn, player_id):
        raise ProgressionNotFoundError("Oyuncu bulunamadı.")

    rows = conn.execute(
        """
        SELECT id, player_id, recorded_at, metrics_json, note, created_at, updated_at
        FROM progression_entries
        WHERE player_id = ?
        ORDER BY recorded_at ASC, id ASC
        """,
        (player_id,),
    ).fetchall()

    entries: list[dict[str, Any]] = []
    prev_metrics: dict[str, Any] | None = None
    for row in rows:
        curr_metrics = _parse_json_dict(row["metrics_json"])
        deltas = {} if prev_metrics is None else _compute_deltas(prev_metrics, curr_metrics)
        entries.append(_row_to_entry(row, metrics=curr_metrics, deltas=deltas))
        prev_metrics = curr_metrics

    if order == "desc":
        entries.reverse()
    return entries


def create_progression_entry(
    conn: sqlite3.Connection,
    player_id: int,
    *,
    recorded_at: Any,
    metrics: Any,
    note: Any = None,
) -> dict[str, Any]:
    if not _player_exists(conn, player_id):
        raise ProgressionNotFoundError("Oyuncu bulunamadı.")

    clean_recorded_at = validate_recorded_at(recorded_at)
    clean_note = _validate_note(note)

    prog_fields = field_validator.list_tracking_fields(
        conn, scope="progression", active_only=False
    )
    validated_metrics = field_validator.validate_field_values(
        prog_fields, metrics, partial=False
    )
    metrics_json = json.dumps(validated_metrics, ensure_ascii=False)
    now_iso = utc_now_iso()

    cursor = conn.execute(
        """
        INSERT INTO progression_entries (player_id, recorded_at, metrics_json, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (player_id, clean_recorded_at, metrics_json, clean_note, now_iso, now_iso),
    )
    entry_id = int(cursor.lastrowid)
    conn.commit()

    entries = list_player_progression(conn, player_id, order="asc")
    for item in entries:
        if item["id"] == entry_id:
            return item
    raise ProgressionNotFoundError("Gelişim kaydı bulunamadı.")


def update_progression_entry(
    conn: sqlite3.Connection,
    entry_id: int,
    fields_set: set[str],
    *,
    recorded_at: Any = None,
    metrics: Any = None,
    note: Any = None,
) -> dict[str, Any]:
    existing_row = conn.execute(
        """
        SELECT id, player_id, recorded_at, metrics_json, note, created_at, updated_at
        FROM progression_entries
        WHERE id = ?
        """,
        (entry_id,),
    ).fetchone()
    if existing_row is None:
        raise ProgressionNotFoundError("Gelişim kaydı bulunamadı.")

    player_id = int(existing_row["player_id"])
    new_recorded_at = str(existing_row["recorded_at"])
    new_metrics_json = str(existing_row["metrics_json"])
    new_note = str(existing_row["note"]) if existing_row["note"] is not None else None

    if "recorded_at" in fields_set:
        if recorded_at is None:
            raise ProgressionValidationError("Kayıt tarihi boş olamaz.")
        new_recorded_at = validate_recorded_at(recorded_at)

    if "metrics" in fields_set:
        if metrics is None:
            raise ProgressionValidationError("Metrik değerleri nesne (dict) olmalıdır.")
        existing_metrics = _parse_json_dict(existing_row["metrics_json"])
        prog_fields = field_validator.list_tracking_fields(
            conn, scope="progression", active_only=False
        )
        merged_metrics = field_validator.validate_field_values(
            prog_fields,
            metrics,
            partial=True,
            existing_values=existing_metrics,
        )
        new_metrics_json = json.dumps(merged_metrics, ensure_ascii=False)

    if "note" in fields_set:
        new_note = _validate_note(note)

    now_iso = utc_now_iso()
    conn.execute(
        """
        UPDATE progression_entries
        SET recorded_at = ?, metrics_json = ?, note = ?, updated_at = ?
        WHERE id = ?
        """,
        (new_recorded_at, new_metrics_json, new_note, now_iso, entry_id),
    )
    conn.commit()

    entries = list_player_progression(conn, player_id, order="asc")
    for item in entries:
        if item["id"] == entry_id:
            return item
    raise ProgressionNotFoundError("Gelişim kaydı bulunamadı.")


def delete_progression_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    cursor = conn.execute("DELETE FROM progression_entries WHERE id = ?", (entry_id,))
    if cursor.rowcount == 0:
        raise ProgressionNotFoundError("Gelişim kaydı bulunamadı.")
    conn.commit()
