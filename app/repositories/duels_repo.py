from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from typing import Any

from app.repositories import limits_repo
from app.services import limit_evaluator
from app.services.auth_service import utc_now_iso

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DUEL_STATUSES = ("ongoing", "completed", "cancelled")
MAX_SCORE = 2_000_000_000


class DuelError(Exception):
    pass


class DuelNotFoundError(DuelError):
    pass


class DuelValidationError(DuelError):
    pass


# ---------------------------------------------------------------- validators

def validate_date(value: Any, label: str = "Tarih", *, required: bool = True) -> str | None:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        if required:
            raise DuelValidationError(f"{label} zorunludur.")
        return None
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value.strip()):
        raise DuelValidationError(f"{label} YYYY-AA-GG biçiminde olmalıdır.")
    cleaned = value.strip()
    try:
        date.fromisoformat(cleaned)
    except ValueError as exc:
        raise DuelValidationError(f"{label} geçerli bir takvim tarihi olmalıdır.") from exc
    return cleaned


def _validate_text(value: Any, label: str, *, max_len: int, required: bool) -> str | None:
    if value is None:
        if required:
            raise DuelValidationError(f"{label} zorunludur.")
        return None
    if not isinstance(value, str):
        raise DuelValidationError(f"{label} metin olmalıdır.")
    cleaned = value.strip()
    if not cleaned:
        if required:
            raise DuelValidationError(f"{label} boş olamaz.")
        return None
    if len(cleaned) > max_len:
        raise DuelValidationError(f"{label} en fazla {max_len} karakter olabilir.")
    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in cleaned):
        raise DuelValidationError(f"{label} geçersiz karakter içeriyor.")
    return cleaned


def validate_score(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DuelValidationError("Puan tam sayı olmalıdır.")
    if value < 0:
        raise DuelValidationError("Puan negatif olamaz.")
    if value > MAX_SCORE:
        raise DuelValidationError("Puan çok büyük.")
    return value


def _validate_status(value: Any) -> str:
    if value not in DUEL_STATUSES:
        raise DuelValidationError("Düello durumu geçersiz.")
    return str(value)


def _player_exists(conn: sqlite3.Connection, player_id: int) -> bool:
    return conn.execute("SELECT 1 FROM players WHERE id = ?", (player_id,)).fetchone() is not None


# ---------------------------------------------------------------- row mapping

def _row_to_duel(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "opponent_clan_name": str(row["opponent_clan_name"]),
        "title": row["title"],
        "start_date": str(row["start_date"]),
        "end_date": row["end_date"],
        "status": str(row["status"]),
        "notes": row["notes"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


_SCORE_SELECT = """
    SELECT ds.id, ds.duel_id, ds.player_id, ds.extracted_name, ds.score, ds.score_date,
           ds.screenshot_id, ds.source, ds.calculation_meta_json, ds.created_at, ds.updated_at,
           p.display_name AS player_name
    FROM duel_scores ds
    LEFT JOIN players p ON p.id = ds.player_id
"""


def _parse_calc_meta(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _row_to_score(row: sqlite3.Row, active_limit: int) -> dict[str, Any]:
    score = int(row["score"])
    base = {
        "id": int(row["id"]),
        "duel_id": int(row["duel_id"]),
        "player_id": int(row["player_id"]) if row["player_id"] is not None else None,
        "player_name": row["player_name"],
        "extracted_name": str(row["extracted_name"]),
        "score": score,
        "score_date": str(row["score_date"]),
        "screenshot_id": int(row["screenshot_id"]) if row["screenshot_id"] is not None else None,
        "source": str(row["source"]),
        "calculationMeta": _parse_calc_meta(row["calculation_meta_json"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }
    base.update(limit_evaluator.evaluate_score(score, active_limit).to_dict())
    return base


def _row_to_screenshot(row: sqlite3.Row) -> dict[str, Any]:
    try:
        parsed = json.loads(row["parsed_rows_json"] or "[]")
    except json.JSONDecodeError:
        parsed = []
    return {
        "id": int(row["id"]),
        "duel_id": int(row["duel_id"]),
        "score_date": str(row["score_date"]),
        "original_filename": str(row["original_filename"]),
        "status": str(row["status"]),
        "uploaded_at": str(row["uploaded_at"]),
        "row_count": len(parsed) if isinstance(parsed, list) else 0,
        "imageUrl": f"/api/duels/{int(row['duel_id'])}/screenshots/{int(row['id'])}/image",
    }


def _score_records_for_eval(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [
        {
            "player_id": r["player_id"],
            "player_name": r["player_name"] or r["extracted_name"],
            "extracted_name": r["extracted_name"],
            "score": int(r["score"]),
            "score_date": str(r["score_date"]),
        }
        for r in rows
    ]


# ---------------------------------------------------------------- duels CRUD

def _get_duel_row(conn: sqlite3.Connection, duel_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM duels WHERE id = ?", (duel_id,)).fetchone()
    if row is None:
        raise DuelNotFoundError("Düello bulunamadı.")
    return row


def list_duels(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    active = limits_repo.get_active_limit(conn)
    duel_rows = conn.execute(
        "SELECT * FROM duels ORDER BY start_date DESC, id DESC"
    ).fetchall()
    score_rows = conn.execute(_SCORE_SELECT + " ORDER BY ds.score_date").fetchall()
    by_duel: dict[int, list[sqlite3.Row]] = {}
    for r in score_rows:
        by_duel.setdefault(int(r["duel_id"]), []).append(r)

    duels: list[dict[str, Any]] = []
    for d in duel_rows:
        duel = _row_to_duel(d)
        rows = by_duel.get(duel["id"], [])
        evals = limit_evaluator.evaluate_daily_scores(_score_records_for_eval(rows), active)
        latest_date = evals[0]["scoreDate"] if evals else None
        latest = [e for e in evals if e["scoreDate"] == latest_date]
        duel["scoreCount"] = len(rows)
        duel["totalScore"] = sum(int(r["score"]) for r in rows)
        duel["participantCount"] = len({(e["playerId"], e["playerName"]) for e in evals})
        duel["latestScoreDate"] = latest_date
        duel["latestDayCompliance"] = limit_evaluator.summarize_compliance(latest)
        duels.append(duel)
    return duels


def create_duel(
    conn: sqlite3.Connection,
    *,
    opponent_clan_name: Any,
    title: Any = None,
    start_date: Any,
    end_date: Any = None,
    status: Any = "ongoing",
    notes: Any = None,
) -> dict[str, Any]:
    opp = _validate_text(opponent_clan_name, "Rakip klan adı", max_len=100, required=True)
    clean_title = _validate_text(title, "Başlık", max_len=150, required=False)
    sd = validate_date(start_date, "Başlangıç tarihi")
    ed = validate_date(end_date, "Bitiş tarihi", required=False)
    if ed is not None and sd is not None and ed < sd:
        raise DuelValidationError("Bitiş tarihi başlangıç tarihinden önce olamaz.")
    st = _validate_status(status)
    clean_notes = _validate_text(notes, "Notlar", max_len=2000, required=False)
    now = utc_now_iso()
    cur = conn.execute(
        """
        INSERT INTO duels (opponent_clan_name, title, start_date, end_date, status, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (opp, clean_title, sd, ed, st, clean_notes, now, now),
    )
    conn.commit()
    return _row_to_duel(_get_duel_row(conn, int(cur.lastrowid)))


def update_duel(conn: sqlite3.Connection, duel_id: int, fields: set[str], **values: Any) -> dict[str, Any]:
    current = _row_to_duel(_get_duel_row(conn, duel_id))
    updates: dict[str, Any] = {}
    if "opponent_clan_name" in fields:
        updates["opponent_clan_name"] = _validate_text(
            values.get("opponent_clan_name"), "Rakip klan adı", max_len=100, required=True
        )
    if "title" in fields:
        updates["title"] = _validate_text(values.get("title"), "Başlık", max_len=150, required=False)
    if "start_date" in fields:
        updates["start_date"] = validate_date(values.get("start_date"), "Başlangıç tarihi")
    if "end_date" in fields:
        updates["end_date"] = validate_date(values.get("end_date"), "Bitiş tarihi", required=False)
    if "status" in fields:
        updates["status"] = _validate_status(values.get("status"))
    if "notes" in fields:
        updates["notes"] = _validate_text(values.get("notes"), "Notlar", max_len=2000, required=False)

    sd = updates.get("start_date", current["start_date"])
    ed = updates.get("end_date", current["end_date"])
    if ed is not None and ed < sd:
        raise DuelValidationError("Bitiş tarihi başlangıç tarihinden önce olamaz.")
    if updates:
        updates["updated_at"] = utc_now_iso()
        cols = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE duels SET {cols} WHERE id = ?", (*updates.values(), duel_id))
        conn.commit()
    return _row_to_duel(_get_duel_row(conn, duel_id))


def delete_duel(conn: sqlite3.Connection, duel_id: int) -> list[str]:
    """Delete duel and return stored screenshot file names for cleanup."""
    _get_duel_row(conn, duel_id)
    files = [
        str(r["file_path"])
        for r in conn.execute("SELECT file_path FROM duel_screenshots WHERE duel_id = ?", (duel_id,))
    ]
    conn.execute("DELETE FROM duels WHERE id = ?", (duel_id,))
    conn.commit()
    return files


def get_duel_detail(conn: sqlite3.Connection, duel_id: int) -> dict[str, Any]:
    duel = _row_to_duel(_get_duel_row(conn, duel_id))
    active = limits_repo.get_active_limit(conn)
    rows = conn.execute(
        _SCORE_SELECT + " WHERE ds.duel_id = ? ORDER BY ds.score_date DESC, ds.score DESC, ds.id",
        (duel_id,),
    ).fetchall()
    shots = conn.execute(
        "SELECT * FROM duel_screenshots WHERE duel_id = ? ORDER BY uploaded_at DESC, id DESC",
        (duel_id,),
    ).fetchall()
    summaries = limit_evaluator.evaluate_daily_scores(_score_records_for_eval(rows), active)
    return {
        "duel": duel,
        "activeDailyMinScore": active,
        "dailySummaries": summaries,
        "compliance": limit_evaluator.summarize_compliance(summaries),
        "scores": [_row_to_score(r, active) for r in rows],
        "screenshots": [_row_to_screenshot(s) for s in shots],
        "recordedDates": get_duel_recorded_dates(conn, duel_id),
    }


def get_duel_recorded_dates(conn: sqlite3.Connection, duel_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT score_date, COUNT(*) AS entry_count, COALESCE(SUM(score), 0) AS total_score
        FROM duel_scores
        WHERE duel_id = ?
        GROUP BY score_date
        ORDER BY score_date ASC
        """,
        (duel_id,),
    ).fetchall()
    return [
        {
            "scoreDate": str(r["score_date"]),
            "entryCount": int(r["entry_count"]),
            "totalScore": int(r["total_score"]),
        }
        for r in rows
    ]


def get_duel_daily_sums_by_dates(
    conn: sqlite3.Connection,
    duel_id: int,
    included_dates: list[str],
) -> tuple[dict[int, int], dict[str, int]]:
    if not included_dates:
        return {}, {}
    placeholders = ", ".join("?" for _ in included_dates)
    rows = conn.execute(
        f"""
        SELECT player_id, extracted_name, score
        FROM duel_scores
        WHERE duel_id = ? AND score_date IN ({placeholders})
        """,
        (duel_id, *included_dates),
    ).fetchall()
    by_player: dict[int, int] = {}
    by_name: dict[str, int] = {}
    for r in rows:
        val = int(r["score"])
        if r["player_id"] is not None:
            pid = int(r["player_id"])
            by_player[pid] = by_player.get(pid, 0) + val
        else:
            folded = str(r["extracted_name"] or "").strip().replace("İ", "i").replace("I", "ı").casefold()
            if folded:
                by_name[folded] = by_name.get(folded, 0) + val
    return by_player, by_name


# ---------------------------------------------------------------- screenshots

def create_screenshot(
    conn: sqlite3.Connection,
    *,
    duel_id: int,
    score_date: str,
    file_path: str,
    original_filename: str,
    raw_text: str,
    parsed_rows: list[dict[str, Any]],
) -> int:
    _get_duel_row(conn, duel_id)
    cur = conn.execute(
        """
        INSERT INTO duel_screenshots (duel_id, score_date, file_path, original_filename,
                                      raw_ocr_text, parsed_rows_json, status, uploaded_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending_review', ?)
        """,
        (
            duel_id,
            score_date,
            file_path,
            original_filename[:255],
            raw_text,
            json.dumps(parsed_rows, ensure_ascii=False),
            utc_now_iso(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_screenshot_row(conn: sqlite3.Connection, duel_id: int, screenshot_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM duel_screenshots WHERE id = ? AND duel_id = ?",
        (screenshot_id, duel_id),
    ).fetchone()
    if row is None:
        raise DuelNotFoundError("Ekran görüntüsü bulunamadı.")
    return row


# ---------------------------------------------------------------- scores

def _get_score_row(conn: sqlite3.Connection, score_id: int) -> sqlite3.Row:
    row = conn.execute(_SCORE_SELECT + " WHERE ds.id = ?", (score_id,)).fetchone()
    if row is None:
        raise DuelNotFoundError("Puan kaydı bulunamadı.")
    return row


def _find_existing_score(
    conn: sqlite3.Connection,
    duel_id: int,
    score_date: str,
    player_id: int | None,
    extracted_name: str,
) -> sqlite3.Row | None:
    if player_id is not None:
        return conn.execute(
            "SELECT id FROM duel_scores WHERE duel_id = ? AND score_date = ? AND player_id = ?",
            (duel_id, score_date, player_id),
        ).fetchone()
    for r in conn.execute(
        "SELECT id, extracted_name FROM duel_scores WHERE duel_id = ? AND score_date = ? AND player_id IS NULL",
        (duel_id, score_date),
    ):
        if str(r["extracted_name"]).casefold() == extracted_name.casefold():
            return r
    return None


def upsert_score(
    conn: sqlite3.Connection,
    *,
    duel_id: int,
    player_id: int | None,
    extracted_name: str,
    score: int,
    score_date: str,
    source: str,
    screenshot_id: int | None = None,
    calculation_meta: dict[str, Any] | None = None,
    commit: bool = True,
) -> int:
    """Insert, or update the existing record for the same duel/day/player."""
    now = utc_now_iso()
    meta_json = json.dumps(calculation_meta, ensure_ascii=False) if calculation_meta is not None else None
    existing = _find_existing_score(conn, duel_id, score_date, player_id, extracted_name)
    if existing is not None:
        sid = int(existing["id"])
        conn.execute(
            """
            UPDATE duel_scores
            SET extracted_name = ?, score = ?, source = ?,
                screenshot_id = COALESCE(?, screenshot_id),
                calculation_meta_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (extracted_name, score, source, screenshot_id, meta_json, now, sid),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO duel_scores (duel_id, player_id, extracted_name, score, score_date,
                                     screenshot_id, source, calculation_meta_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                duel_id,
                player_id,
                extracted_name,
                score,
                score_date,
                screenshot_id,
                source,
                meta_json,
                now,
                now,
            ),
        )
        sid = int(cur.lastrowid)
    if commit:
        conn.commit()
    return sid


def add_manual_score(
    conn: sqlite3.Connection,
    duel_id: int,
    *,
    player_id: Any,
    extracted_name: Any,
    score: Any,
    score_date: Any,
) -> dict[str, Any]:
    _get_duel_row(conn, duel_id)
    clean_score = validate_score(score)
    sd = validate_date(score_date, "Puan tarihi")
    pid = _resolve_player_id(conn, player_id)
    name = _validate_text(extracted_name, "Oyuncu adı", max_len=100, required=pid is None)
    if name is None:
        name = str(conn.execute("SELECT display_name FROM players WHERE id = ?", (pid,)).fetchone()[0])
    score_id = upsert_score(
        conn,
        duel_id=duel_id,
        player_id=pid,
        extracted_name=name,
        score=clean_score,
        score_date=sd,
        source="manual",
    )
    return _row_to_score(_get_score_row(conn, score_id), limits_repo.get_active_limit(conn))


def _resolve_player_id(conn: sqlite3.Connection, player_id: Any) -> int | None:
    if player_id is None:
        return None
    if isinstance(player_id, bool) or not isinstance(player_id, int):
        raise DuelValidationError("Oyuncu kimliği geçersiz.")
    if not _player_exists(conn, player_id):
        raise DuelValidationError("Seçilen oyuncu bulunamadı.")
    return player_id


def update_score(conn: sqlite3.Connection, score_id: int, fields: set[str], **values: Any) -> dict[str, Any]:
    row = _get_score_row(conn, score_id)
    updates: dict[str, Any] = {}
    if "score" in fields:
        updates["score"] = validate_score(values.get("score"))
    if "score_date" in fields:
        updates["score_date"] = validate_date(values.get("score_date"), "Puan tarihi")
    if "player_id" in fields:
        updates["player_id"] = _resolve_player_id(conn, values.get("player_id"))
    if "extracted_name" in fields:
        updates["extracted_name"] = _validate_text(
            values.get("extracted_name"), "Oyuncu adı", max_len=100, required=True
        )
    if updates:
        new_pid = updates.get("player_id", row["player_id"])
        new_date = updates.get("score_date", row["score_date"])
        if new_pid is not None:
            clash = conn.execute(
                "SELECT id FROM duel_scores WHERE duel_id = ? AND score_date = ? AND player_id = ? AND id != ?",
                (row["duel_id"], new_date, new_pid, score_id),
            ).fetchone()
            if clash is not None:
                raise DuelValidationError("Bu oyuncunun o gün için zaten bir puan kaydı var.")
        updates["updated_at"] = utc_now_iso()
        cols = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE duel_scores SET {cols} WHERE id = ?", (*updates.values(), score_id))
        conn.commit()
    return _row_to_score(_get_score_row(conn, score_id), limits_repo.get_active_limit(conn))


def delete_score(conn: sqlite3.Connection, score_id: int) -> None:
    _get_score_row(conn, score_id)
    conn.execute("DELETE FROM duel_scores WHERE id = ?", (score_id,))
    conn.commit()


def get_scores_by_ids(conn: sqlite3.Connection, ids: list[int]) -> list[dict[str, Any]]:
    active = limits_repo.get_active_limit(conn)
    return [_row_to_score(_get_score_row(conn, i), active) for i in ids]


# ---------------------------------------------------------------- evaluation

def evaluate(
    conn: sqlite3.Connection,
    *,
    score_date: str | None = None,
    duel_id: int | None = None,
    player_id: int | None = None,
) -> dict[str, Any]:
    active = limits_repo.get_active_limit(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if score_date is not None:
        clauses.append("ds.score_date = ?")
        params.append(score_date)
    if duel_id is not None:
        clauses.append("ds.duel_id = ?")
        params.append(duel_id)
    if player_id is not None:
        clauses.append("ds.player_id = ?")
        params.append(player_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(_SCORE_SELECT + where, params).fetchall()
    evals = limit_evaluator.evaluate_daily_scores(_score_records_for_eval(rows), active)
    return {
        "activeMinScore": active,
        "evaluations": evals,
        "compliance": limit_evaluator.summarize_compliance(evals),
    }
