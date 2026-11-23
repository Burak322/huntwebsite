from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any

from app.repositories import progression_repo
from app.services import field_validator
from app.services.auth_service import utc_now_iso

VALID_PLAYER_STATUSES = frozenset({"active", "inactive", "left"})
VALID_CLAN_RANKS = ("R1", "R2", "R3", "R4", "R5")
VALID_TOWER_LEVELS = ("I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9", "I10")
_VALID_CLAN_RANK_SET = frozenset(VALID_CLAN_RANKS)
_VALID_TOWER_LEVEL_SET = frozenset(VALID_TOWER_LEVELS)
_PLAYER_COLUMNS = (
    "id, display_name, status, clan_rank, tower_level, "
    "joined_at, notes, profile_values_json, created_at, updated_at"
)
_PLAYER_SORT_ORDER_BY: dict[str, str] = {
    "name_asc": "display_name COLLATE NOCASE ASC, id ASC",
    "name_desc": "display_name COLLATE NOCASE DESC, id DESC",
    "rank_desc": (
        "CASE WHEN clan_rank IS NULL THEN 1 ELSE 0 END ASC, "
        "CAST(SUBSTR(clan_rank, 2) AS INTEGER) DESC, "
        "CASE WHEN tower_level IS NULL THEN 1 ELSE 0 END ASC, "
        "CAST(SUBSTR(tower_level, 2) AS INTEGER) DESC, "
        "display_name COLLATE NOCASE ASC, id ASC"
    ),
    "rank_asc": (
        "CASE WHEN clan_rank IS NULL THEN 1 ELSE 0 END ASC, "
        "CAST(SUBSTR(clan_rank, 2) AS INTEGER) ASC, "
        "CASE WHEN tower_level IS NULL THEN 1 ELSE 0 END ASC, "
        "CAST(SUBSTR(tower_level, 2) AS INTEGER) ASC, "
        "display_name COLLATE NOCASE ASC, id ASC"
    ),
    "tower_desc": (
        "CASE WHEN tower_level IS NULL THEN 1 ELSE 0 END ASC, "
        "CAST(SUBSTR(tower_level, 2) AS INTEGER) DESC, "
        "CASE WHEN clan_rank IS NULL THEN 1 ELSE 0 END ASC, "
        "CAST(SUBSTR(clan_rank, 2) AS INTEGER) DESC, "
        "display_name COLLATE NOCASE ASC, id ASC"
    ),
    "tower_asc": (
        "CASE WHEN tower_level IS NULL THEN 1 ELSE 0 END ASC, "
        "CAST(SUBSTR(tower_level, 2) AS INTEGER) ASC, "
        "CASE WHEN clan_rank IS NULL THEN 1 ELSE 0 END ASC, "
        "CAST(SUBSTR(clan_rank, 2) AS INTEGER) ASC, "
        "display_name COLLATE NOCASE ASC, id ASC"
    ),
}
_JOINED_AT_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)


class PlayerError(Exception):
    """Base error for player roster and aliases domain."""


class PlayerNotFoundError(PlayerError):
    """Raised when a player is not found."""


class AliasNotFoundError(PlayerError):
    """Raised when a player alias is not found for the given player."""


class PlayerConflictError(PlayerError):
    """Raised when display_name or alias_name conflicts globally."""


class PlayerValidationError(PlayerError):
    """Raised when player or alias input is invalid."""


def _fold_tr(value: str) -> str:
    return value.replace("İ", "i").casefold()


def _parse_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _has_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 for ch in value)


def _has_multiline_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 and ch not in ("\n", "\r", "\t") for ch in value)


def _validate_display_name(value: Any) -> str:
    if not isinstance(value, str):
        raise PlayerValidationError("Oyuncu adı metin olmalıdır.")
    cleaned = value.strip()
    if not (1 <= len(cleaned) <= 100):
        raise PlayerValidationError("Oyuncu adı 1 ile 100 karakter arasında olmalıdır.")
    if _has_control_chars(cleaned):
        raise PlayerValidationError("Oyuncu adı kontrol karakterleri içeremez.")
    return cleaned


def _validate_alias_name(value: Any) -> str:
    if not isinstance(value, str):
        raise PlayerValidationError("Takma ad metin olmalıdır.")
    cleaned = value.strip()
    if not (1 <= len(cleaned) <= 100):
        raise PlayerValidationError("Takma ad 1 ile 100 karakter arasında olmalıdır.")
    if _has_control_chars(cleaned):
        raise PlayerValidationError("Takma ad kontrol karakterleri içeremez.")
    return cleaned


def _validate_status(value: Any) -> str:
    if not isinstance(value, str) or value not in VALID_PLAYER_STATUSES:
        raise PlayerValidationError("Oyuncu durumu 'active', 'inactive' veya 'left' olmalıdır.")
    return value


def _validate_clan_rank(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PlayerValidationError("Rank metin olmalıdır.")
    cleaned = value.strip().upper()
    if not cleaned:
        return None
    if cleaned not in _VALID_CLAN_RANK_SET:
        raise PlayerValidationError("Rank R1 ile R5 arasında olmalıdır (R1, R2, R3, R4, R5).")
    return cleaned


def _validate_tower_level(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PlayerValidationError("Kule seviyesi metin olmalıdır.")
    cleaned = (
        value.strip()
        .replace("\u0130", "I")
        .replace("ı", "I")
        .replace("i", "I")
        .upper()
    )
    if not cleaned:
        return None
    if cleaned not in _VALID_TOWER_LEVEL_SET:
        raise PlayerValidationError("Kule seviyesi I1 ile I10 arasında olmalıdır (I1–I10).")
    return cleaned


def _validate_joined_at(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PlayerValidationError("Katılım tarihi metin olmalıdır.")
    cleaned = value.strip()
    if not cleaned:
        return None
    if not _JOINED_AT_PATTERN.fullmatch(cleaned):
        raise PlayerValidationError("Katılım tarihi YYYY-AA-GG biçiminde olmalıdır.")
    try:
        if len(cleaned) == 10:
            datetime.strptime(cleaned, "%Y-%m-%d")
        else:
            iso_candidate = cleaned[:-1] + "+00:00" if cleaned.endswith("Z") else cleaned
            datetime.fromisoformat(iso_candidate)
    except ValueError as exc:
        raise PlayerValidationError("Katılım tarihi geçerli bir takvim tarihi olmalıdır.") from exc
    return cleaned


def _validate_notes(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PlayerValidationError("Notlar metin olmalıdır.")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > 2000:
        raise PlayerValidationError("Notlar en fazla 2000 karakter olabilir.")
    if _has_multiline_control_chars(cleaned):
        raise PlayerValidationError("Notlar geçersiz kontrol karakterleri içeremez.")
    return cleaned


def _row_to_alias(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "player_id": int(row["player_id"]),
        "alias_name": str(row["alias_name"]),
        "created_at": str(row["created_at"]),
    }


def _row_to_player(
    row: sqlite3.Row,
    *,
    aliases: list[dict[str, Any]] | None = None,
    latest_progression: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "display_name": str(row["display_name"]),
        "status": str(row["status"]),
        "clan_rank": str(row["clan_rank"]) if row["clan_rank"] is not None else None,
        "tower_level": str(row["tower_level"]) if row["tower_level"] is not None else None,
        "joined_at": str(row["joined_at"]) if row["joined_at"] is not None else None,
        "notes": str(row["notes"]) if row["notes"] is not None else None,
        "profile_values": _parse_json_dict(row["profile_values_json"]),
        "aliases": aliases if aliases is not None else [],
        "latestProgression": latest_progression,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _row_to_duel_score(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "duel_id": int(row["duel_id"]),
        "player_id": int(row["player_id"]) if row["player_id"] is not None else None,
        "extracted_name": str(row["extracted_name"]),
        "score": int(row["score"]),
        "score_date": str(row["score_date"]),
        "screenshot_id": int(row["screenshot_id"]) if row["screenshot_id"] is not None else None,
        "source": str(row["source"]),
        "opponent_clan_name": str(row["opponent_clan_name"]),
        "duel_title": str(row["duel_title"]) if row["duel_title"] is not None else None,
        "duel_status": str(row["duel_status"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _check_display_name_unique(
    conn: sqlite3.Connection,
    display_name: str,
    *,
    exclude_player_id: int | None = None,
) -> None:
    folded_target = _fold_tr(display_name)
    for row in conn.execute("SELECT id, display_name FROM players").fetchall():
        pid = int(row["id"])
        if exclude_player_id is not None and pid == exclude_player_id:
            continue
        if _fold_tr(str(row["display_name"])) == folded_target:
            raise PlayerConflictError("Bu oyuncu adı zaten kayıtlı.")

    for row in conn.execute("SELECT player_id, alias_name FROM player_aliases").fetchall():
        pid = int(row["player_id"])
        if exclude_player_id is not None and pid == exclude_player_id:
            continue
        if _fold_tr(str(row["alias_name"])) == folded_target:
            raise PlayerConflictError("Bu isim başka bir oyuncunun takma adı olarak kayıtlı.")


def _check_alias_unique(
    conn: sqlite3.Connection,
    alias_name: str,
    *,
    owning_player_id: int | None = None,
) -> None:
    folded_target = _fold_tr(alias_name)
    for row in conn.execute("SELECT alias_name FROM player_aliases").fetchall():
        if _fold_tr(str(row["alias_name"])) == folded_target:
            raise PlayerConflictError("Bu takma ad zaten başka bir kayıtta kullanılıyor.")

    for row in conn.execute("SELECT id, display_name FROM players").fetchall():
        pid = int(row["id"])
        if owning_player_id is not None and pid == owning_player_id:
            continue
        if _fold_tr(str(row["display_name"])) == folded_target:
            raise PlayerConflictError("Bu takma ad başka bir oyuncunun ana adı olarak kayıtlı.")


def _validate_sort(value: Any) -> str:
    if value is None:
        return "name_asc"
    if not isinstance(value, str):
        raise PlayerValidationError("Geçersiz sıralama seçeneği.")
    cleaned = value.strip().lower()
    if not cleaned:
        return "name_asc"
    if cleaned not in _PLAYER_SORT_ORDER_BY:
        raise PlayerValidationError("Geçersiz sıralama seçeneği.")
    return cleaned


def list_players(
    conn: sqlite3.Connection,
    *,
    search: str = "",
    status: str | None = None,
    clan_rank: str | None = None,
    tower_level: str | None = None,
    sort: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if status is not None and status.strip() != "":
        clauses.append("status = ?")
        params.append(_validate_status(status.strip()))
    if clan_rank is not None and clan_rank.strip() != "":
        clauses.append("clan_rank = ?")
        params.append(_validate_clan_rank(clan_rank))
    if tower_level is not None and tower_level.strip() != "":
        clauses.append("tower_level = ?")
        params.append(_validate_tower_level(tower_level))

    sort_key = _validate_sort(sort)
    order_sql = _PLAYER_SORT_ORDER_BY[sort_key]

    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    player_rows = conn.execute(
        f"""
        SELECT {_PLAYER_COLUMNS}
        FROM players{where_sql}
        ORDER BY {order_sql}
        """,
        tuple(params),
    ).fetchall()

    alias_rows = conn.execute(
        """
        SELECT id, player_id, alias_name, created_at
        FROM player_aliases
        ORDER BY id ASC
        """
    ).fetchall()
    aliases_by_player: dict[int, list[dict[str, Any]]] = {}
    for a_row in alias_rows:
        pid = int(a_row["player_id"])
        aliases_by_player.setdefault(pid, []).append(_row_to_alias(a_row))

    latest_by_player = progression_repo.get_latest_progression_map(conn)

    needle = _fold_tr(search.strip()) if isinstance(search, str) else ""
    players: list[dict[str, Any]] = []
    for p_row in player_rows:
        pid = int(p_row["id"])
        p_aliases = aliases_by_player.get(pid, [])
        if needle:
            matches_name = needle in _fold_tr(str(p_row["display_name"]))
            matches_alias = any(needle in _fold_tr(a["alias_name"]) for a in p_aliases)
            if not (matches_name or matches_alias):
                continue
        players.append(
            _row_to_player(
                p_row,
                aliases=p_aliases,
                latest_progression=latest_by_player.get(pid),
            )
        )
    return players


def create_player(
    conn: sqlite3.Connection,
    *,
    display_name: Any,
    status: Any = "active",
    clan_rank: Any = None,
    tower_level: Any = None,
    joined_at: Any = None,
    notes: Any = None,
    profile_values: Any = None,
    aliases: Any = None,
) -> dict[str, Any]:
    clean_name = _validate_display_name(display_name)
    clean_status = _validate_status(status)
    clean_rank = _validate_clan_rank(clan_rank)
    clean_tower = _validate_tower_level(tower_level)
    clean_joined_at = _validate_joined_at(joined_at)
    clean_notes = _validate_notes(notes)

    raw_profile = {} if profile_values is None else profile_values
    profile_fields = field_validator.list_tracking_fields(
        conn, scope="profile", active_only=False
    )
    validated_profile = field_validator.validate_field_values(
        profile_fields, raw_profile, partial=False
    )
    profile_json = json.dumps(validated_profile, ensure_ascii=False)

    raw_aliases = [] if aliases is None else aliases
    if not isinstance(raw_aliases, list):
        raise PlayerValidationError("Takma ad listesi dizi olmalıdır.")

    cleaned_aliases: list[str] = []
    seen_folded_aliases: set[str] = set()
    for item in raw_aliases:
        clean_alias = _validate_alias_name(item)
        folded = _fold_tr(clean_alias)
        if folded in seen_folded_aliases:
            raise PlayerConflictError("Aynı takma ad birden fazla kez girilemez.")
        seen_folded_aliases.add(folded)
        cleaned_aliases.append(clean_alias)

    now_iso = utc_now_iso()
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")

        _check_display_name_unique(conn, clean_name)
        for alias in cleaned_aliases:
            _check_alias_unique(conn, alias)

        cursor = conn.execute(
            """
            INSERT INTO players (
                display_name, status, clan_rank, tower_level,
                joined_at, notes, profile_values_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_name,
                clean_status,
                clean_rank,
                clean_tower,
                clean_joined_at,
                clean_notes,
                profile_json,
                now_iso,
                now_iso,
            ),
        )
        player_id = int(cursor.lastrowid)

        for alias in cleaned_aliases:
            conn.execute(
                """
                INSERT INTO player_aliases (player_id, alias_name, created_at)
                VALUES (?, ?, ?)
                """,
                (player_id, alias, now_iso),
            )
        conn.commit()
    except PlayerConflictError:
        conn.rollback()
        raise
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise PlayerConflictError("Bu oyuncu adı veya takma ad zaten kayıtlı.") from exc
    except BaseException:
        conn.rollback()
        raise

    player_row = conn.execute(
        f"""
        SELECT {_PLAYER_COLUMNS}
        FROM players
        WHERE id = ?
        """,
        (player_id,),
    ).fetchone()
    assert player_row is not None
    alias_rows = conn.execute(
        """
        SELECT id, player_id, alias_name, created_at
        FROM player_aliases
        WHERE player_id = ?
        ORDER BY id ASC
        """,
        (player_id,),
    ).fetchall()
    return _row_to_player(
        player_row,
        aliases=[_row_to_alias(r) for r in alias_rows],
        latest_progression=None,
    )


def get_player_detail(
    conn: sqlite3.Connection,
    player_id: int,
    *,
    duel_limit: int = 20,
) -> dict[str, Any]:
    player_row = conn.execute(
        f"""
        SELECT {_PLAYER_COLUMNS}
        FROM players
        WHERE id = ?
        """,
        (player_id,),
    ).fetchone()
    if player_row is None:
        raise PlayerNotFoundError("Oyuncu bulunamadı.")

    alias_rows = conn.execute(
        """
        SELECT id, player_id, alias_name, created_at
        FROM player_aliases
        WHERE player_id = ?
        ORDER BY id ASC
        """,
        (player_id,),
    ).fetchall()
    aliases = [_row_to_alias(r) for r in alias_rows]

    progression_entries = progression_repo.list_player_progression(
        conn, player_id, order="desc"
    )
    latest_progression = progression_repo.get_latest_progression_for_player(conn, player_id)

    duel_rows = conn.execute(
        """
        SELECT
            ds.id, ds.duel_id, ds.player_id, ds.extracted_name, ds.score,
            ds.score_date, ds.screenshot_id, ds.source, ds.created_at, ds.updated_at,
            d.opponent_clan_name, d.title AS duel_title, d.status AS duel_status
        FROM duel_scores ds
        JOIN duels d ON d.id = ds.duel_id
        WHERE ds.player_id = ?
        ORDER BY ds.score_date DESC, ds.id DESC
        LIMIT ?
        """,
        (player_id, duel_limit),
    ).fetchall()
    from app.repositories.limits_repo import get_active_limit
    from app.services.limit_evaluator import evaluate_score

    active_limit = get_active_limit(conn)
    recent_duel_scores = []
    for r in duel_rows:
        item = _row_to_duel_score(r)
        item.update(evaluate_score(item["score"], active_limit).to_dict())
        recent_duel_scores.append(item)

    return {
        "player": _row_to_player(
            player_row,
            aliases=aliases,
            latest_progression=latest_progression,
        ),
        "aliases": aliases,
        "progressionEntries": progression_entries,
        "recentDuelScores": recent_duel_scores,
    }


def update_player(
    conn: sqlite3.Connection,
    player_id: int,
    fields_set: set[str],
    *,
    display_name: Any = None,
    status: Any = None,
    clan_rank: Any = None,
    tower_level: Any = None,
    joined_at: Any = None,
    notes: Any = None,
    profile_values: Any = None,
) -> dict[str, Any]:
    existing_row = conn.execute(
        f"""
        SELECT {_PLAYER_COLUMNS}
        FROM players
        WHERE id = ?
        """,
        (player_id,),
    ).fetchone()
    if existing_row is None:
        raise PlayerNotFoundError("Oyuncu bulunamadı.")

    new_display_name = str(existing_row["display_name"])
    new_status = str(existing_row["status"])
    new_clan_rank = str(existing_row["clan_rank"]) if existing_row["clan_rank"] is not None else None
    new_tower_level = str(existing_row["tower_level"]) if existing_row["tower_level"] is not None else None
    new_joined_at = str(existing_row["joined_at"]) if existing_row["joined_at"] is not None else None
    new_notes = str(existing_row["notes"]) if existing_row["notes"] is not None else None
    new_profile_json = str(existing_row["profile_values_json"])

    if "display_name" in fields_set:
        if display_name is None:
            raise PlayerValidationError("Oyuncu adı boş olamaz.")
        new_display_name = _validate_display_name(display_name)

    if "status" in fields_set:
        if status is None:
            raise PlayerValidationError("Oyuncu durumu boş olamaz.")
        new_status = _validate_status(status)

    if "clan_rank" in fields_set:
        new_clan_rank = _validate_clan_rank(clan_rank)

    if "tower_level" in fields_set:
        new_tower_level = _validate_tower_level(tower_level)

    if "joined_at" in fields_set:
        new_joined_at = _validate_joined_at(joined_at)

    if "notes" in fields_set:
        new_notes = _validate_notes(notes)

    if "profile_values" in fields_set:
        if profile_values is None:
            raise PlayerValidationError("Profil alan değerleri nesne (dict) olmalıdır.")
        existing_profile = _parse_json_dict(existing_row["profile_values_json"])
        profile_fields = field_validator.list_tracking_fields(
            conn, scope="profile", active_only=False
        )
        merged_profile = field_validator.validate_field_values(
            profile_fields,
            profile_values,
            partial=True,
            existing_values=existing_profile,
        )
        new_profile_json = json.dumps(merged_profile, ensure_ascii=False)

    now_iso = utc_now_iso()
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        if "display_name" in fields_set:
            _check_display_name_unique(conn, new_display_name, exclude_player_id=player_id)

        conn.execute(
            """
            UPDATE players
            SET display_name = ?, status = ?, clan_rank = ?, tower_level = ?,
                joined_at = ?, notes = ?, profile_values_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_display_name,
                new_status,
                new_clan_rank,
                new_tower_level,
                new_joined_at,
                new_notes,
                new_profile_json,
                now_iso,
                player_id,
            ),
        )
        conn.commit()
    except PlayerConflictError:
        conn.rollback()
        raise
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise PlayerConflictError("Bu oyuncu adı zaten kullanılıyor.") from exc
    except BaseException:
        conn.rollback()
        raise

    updated_row = conn.execute(
        f"""
        SELECT {_PLAYER_COLUMNS}
        FROM players
        WHERE id = ?
        """,
        (player_id,),
    ).fetchone()
    assert updated_row is not None
    alias_rows = conn.execute(
        """
        SELECT id, player_id, alias_name, created_at
        FROM player_aliases
        WHERE player_id = ?
        ORDER BY id ASC
        """,
        (player_id,),
    ).fetchall()
    latest_progression = progression_repo.get_latest_progression_for_player(conn, player_id)
    return _row_to_player(
        updated_row,
        aliases=[_row_to_alias(r) for r in alias_rows],
        latest_progression=latest_progression,
    )


def delete_player(conn: sqlite3.Connection, player_id: int) -> None:
    cursor = conn.execute("DELETE FROM players WHERE id = ?", (player_id,))
    if cursor.rowcount == 0:
        raise PlayerNotFoundError("Oyuncu bulunamadı.")
    conn.commit()


def add_alias(conn: sqlite3.Connection, player_id: int, alias_name: Any) -> dict[str, Any]:
    player_exists = conn.execute("SELECT id FROM players WHERE id = ?", (player_id,)).fetchone()
    if player_exists is None:
        raise PlayerNotFoundError("Oyuncu bulunamadı.")

    clean_alias = _validate_alias_name(alias_name)
    now_iso = utc_now_iso()

    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        _check_alias_unique(conn, clean_alias, owning_player_id=player_id)
        cursor = conn.execute(
            """
            INSERT INTO player_aliases (player_id, alias_name, created_at)
            VALUES (?, ?, ?)
            """,
            (player_id, clean_alias, now_iso),
        )
        alias_id = int(cursor.lastrowid)
        conn.commit()
    except PlayerConflictError:
        conn.rollback()
        raise
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise PlayerConflictError("Bu takma ad zaten başka bir kayıtta kullanılıyor.") from exc
    except BaseException:
        conn.rollback()
        raise

    alias_row = conn.execute(
        """
        SELECT id, player_id, alias_name, created_at
        FROM player_aliases
        WHERE id = ?
        """,
        (alias_id,),
    ).fetchone()
    assert alias_row is not None
    return _row_to_alias(alias_row)


def delete_alias(conn: sqlite3.Connection, player_id: int, alias_id: int) -> None:
    cursor = conn.execute(
        "DELETE FROM player_aliases WHERE id = ? AND player_id = ?",
        (alias_id, player_id),
    )
    if cursor.rowcount == 0:
        raise AliasNotFoundError("Takma ad bulunamadı.")
    conn.commit()
