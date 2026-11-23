from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.db.connection import get_connection

if TYPE_CHECKING:
    from app.config import Settings

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    token_hash TEXT PRIMARY KEY,
    admin_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_admin_id
    ON admin_sessions(admin_id);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires_at
    ON admin_sessions(expires_at);

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS daily_limit_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    min_score INTEGER NOT NULL CHECK (min_score >= 0),
    note TEXT,
    changed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS tracking_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('profile', 'progression')),
    field_type TEXT NOT NULL CHECK (field_type IN ('text', 'number', 'boolean', 'select', 'date')),
    unit TEXT,
    options_json TEXT,
    is_required INTEGER NOT NULL DEFAULT 0 CHECK (is_required IN (0, 1)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_tracking_fields_scope_order
    ON tracking_fields(scope, is_active, sort_order, id);

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'left')),
    clan_rank TEXT CHECK (clan_rank IS NULL OR clan_rank IN ('R1', 'R2', 'R3', 'R4', 'R5')),
    tower_level TEXT CHECK (
        tower_level IS NULL
        OR tower_level IN ('I1', 'I2', 'I3', 'I4', 'I5', 'I6', 'I7', 'I8', 'I9', 'I10')
    ),
    joined_at TEXT,
    notes TEXT,
    profile_values_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_players_status
    ON players(status);

CREATE TABLE IF NOT EXISTS player_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    alias_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_player_aliases_player_id
    ON player_aliases(player_id);

CREATE TABLE IF NOT EXISTS progression_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    recorded_at TEXT NOT NULL,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_progression_entries_player_recorded
    ON progression_entries(player_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS duels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opponent_clan_name TEXT NOT NULL,
    title TEXT,
    start_date TEXT NOT NULL,
    end_date TEXT,
    status TEXT NOT NULL DEFAULT 'ongoing' CHECK (status IN ('ongoing', 'completed', 'cancelled')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_duels_start_date
    ON duels(start_date DESC, id DESC);

CREATE TABLE IF NOT EXISTS duel_screenshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    duel_id INTEGER NOT NULL REFERENCES duels(id) ON DELETE CASCADE,
    score_date TEXT NOT NULL,
    file_path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    raw_ocr_text TEXT,
    parsed_rows_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending_review' CHECK (status IN ('pending_review', 'committed', 'failed')),
    uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_duel_screenshots_duel_date
    ON duel_screenshots(duel_id, score_date);

CREATE TABLE IF NOT EXISTS duel_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    duel_id INTEGER NOT NULL REFERENCES duels(id) ON DELETE CASCADE,
    player_id INTEGER REFERENCES players(id) ON DELETE SET NULL,
    extracted_name TEXT NOT NULL,
    score INTEGER NOT NULL CHECK (score >= 0),
    score_date TEXT NOT NULL,
    screenshot_id INTEGER REFERENCES duel_screenshots(id) ON DELETE SET NULL,
    source TEXT NOT NULL DEFAULT 'ocr' CHECK (source IN ('ocr', 'manual')),
    calculation_meta_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_duel_scores_duel_date
    ON duel_scores(duel_id, score_date);
CREATE INDEX IF NOT EXISTS idx_duel_scores_player_date
    ON duel_scores(player_id, score_date);
"""


def _ensure_player_rank_tower_columns(conn: sqlite3.Connection) -> None:
    cols = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(players)").fetchall()
    }
    if "clan_rank" not in cols:
        conn.execute(
            "ALTER TABLE players ADD COLUMN clan_rank TEXT "
            "CHECK (clan_rank IS NULL OR clan_rank IN ('R1', 'R2', 'R3', 'R4', 'R5'))"
        )
    if "tower_level" not in cols:
        conn.execute(
            "ALTER TABLE players ADD COLUMN tower_level TEXT "
            "CHECK (tower_level IS NULL OR tower_level IN "
            "('I1', 'I2', 'I3', 'I4', 'I5', 'I6', 'I7', 'I8', 'I9', 'I10'))"
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_players_clan_rank ON players(clan_rank)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_players_tower_level ON players(tower_level)")


def _ensure_duel_score_meta_column(conn: sqlite3.Connection) -> None:
    cols = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(duel_scores)").fetchall()
    }
    if "calculation_meta_json" not in cols:
        conn.execute("ALTER TABLE duel_scores ADD COLUMN calculation_meta_json TEXT")


def run_migrations(
    conn: sqlite3.Connection,
    settings: Settings | None = None,
    password_hasher: Callable[[str], str] | None = None,
) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    _ensure_player_rank_tower_columns(conn)
    _ensure_duel_score_meta_column(conn)

    # Idempotent default settings seed
    conn.execute(
        "INSERT OR IGNORE INTO system_settings (key, value) VALUES ('daily_min_score', '0')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO system_settings (key, value) VALUES ('clan_name', 'Klanım')"
    )

    # Optional idempotent admin bootstrap from env when admin_users is empty
    if settings and settings.admin_username and settings.admin_password:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM admin_users").fetchone()
        if row is not None and row["cnt"] == 0:
            hasher = password_hasher
            if hasher is None:
                from app.services.auth_service import hash_password

                hasher = hash_password
            pw_hash = hasher(settings.admin_password)
            conn.execute(
                "INSERT OR IGNORE INTO admin_users (username, password_hash) VALUES (?, ?)",
                (settings.admin_username, pw_hash),
            )
    conn.commit()


def init_db(settings: Settings) -> None:
    with get_connection(settings.db_path) as conn:
        run_migrations(conn, settings=settings)
