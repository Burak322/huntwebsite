"""Build the self-contained GitHub Pages static bundle in docs/ from app/static/ and data/clan.db."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_SRC = PROJECT_ROOT / "app" / "static"
DB_PATH = PROJECT_ROOT / "data" / "clan.db"
DOCS_DIR = PROJECT_ROOT / "docs"

STATIC_INDEX_HTML = """<!doctype html>
<html lang="tr" dir="ltr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="clan-static-mode" content="true">
  <title>Klan Yönetim Sistemi</title>
  <link rel="stylesheet" href="./css/styles.css">
</head>
<body>
  <div id="app">
    <div class="loading-screen">Yükleniyor...</div>
  </div>
  <script type="module" src="./js/router.js"></script>
</body>
</html>
"""

REDIRECT_404_HTML = """<!doctype html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="0; url=./">
  <title>Yönlendiriliyor...</title>
  <script>
    window.location.replace("./" + (window.location.hash || "#/"));
  </script>
</head>
<body>
  <p>Yönlendiriliyor... <a href="./">Ana sayfaya dön</a></p>
</body>
</html>
"""


def _parse_json_obj(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _parse_json_list(raw: str | None) -> list[Any] | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        return None


def export_seed_from_db(db_path: Path) -> dict[str, Any]:
    """Export clan roster, duels, limit, and fields without secrets or local filesystem paths."""
    seed: dict[str, Any] = {
        "version": 1,
        "auth": {
            "authenticated": True,
            "username": "Admin",
            "clanName": "Hunt",
            "passwordHash": None,
        },
        "activeDailyMinScore": 0,
        "dailyLimitUpdatedAt": None,
        "dailyLimitHistory": [],
        "trackingFields": [],
        "players": [],
        "playerAliases": [],
        "progressionEntries": [],
        "duels": [],
        "duelScreenshots": [],
        "duelScores": [],
    }
    if not db_path.is_file():
        return seed

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        settings_rows = conn.execute(
            "SELECT key, value, updated_at FROM system_settings"
        ).fetchall()
        for row in settings_rows:
            k = str(row["key"])
            if k == "clan_name" and str(row["value"]).strip():
                seed["auth"]["clanName"] = str(row["value"]).strip()
            elif k == "daily_min_score":
                try:
                    seed["activeDailyMinScore"] = max(0, int(row["value"]))
                except (TypeError, ValueError):
                    seed["activeDailyMinScore"] = 0
                seed["dailyLimitUpdatedAt"] = row["updated_at"]

        seed["dailyLimitHistory"] = [
            {
                "id": int(r["id"]),
                "minScore": int(r["min_score"]),
                "note": r["note"],
                "changedAt": str(r["changed_at"]),
            }
            for r in conn.execute(
                "SELECT id, min_score, note, changed_at FROM daily_limit_history ORDER BY changed_at DESC, id DESC"
            ).fetchall()
        ]

        seed["trackingFields"] = [
            {
                "id": int(r["id"]),
                "field_key": str(r["field_key"]),
                "label": str(r["label"]),
                "scope": str(r["scope"]),
                "field_type": str(r["field_type"]),
                "unit": r["unit"],
                "options": _parse_json_list(r["options_json"]),
                "is_required": bool(r["is_required"]),
                "is_active": bool(r["is_active"]),
                "sort_order": int(r["sort_order"]),
                "created_at": str(r["created_at"]),
            }
            for r in conn.execute(
                """
                SELECT id, field_key, label, scope, field_type, unit, options_json,
                       is_required, is_active, sort_order, created_at
                FROM tracking_fields
                ORDER BY sort_order ASC, id ASC
                """
            ).fetchall()
        ]

        seed["players"] = [
            {
                "id": int(r["id"]),
                "display_name": str(r["display_name"]),
                "status": str(r["status"]),
                "clan_rank": r["clan_rank"],
                "tower_level": r["tower_level"],
                "joined_at": r["joined_at"],
                "notes": r["notes"],
                "profile_values": _parse_json_obj(r["profile_values_json"]),
                "created_at": str(r["created_at"]),
                "updated_at": str(r["updated_at"]),
            }
            for r in conn.execute(
                """
                SELECT id, display_name, status, clan_rank, tower_level,
                       joined_at, notes, profile_values_json, created_at, updated_at
                FROM players
                ORDER BY id ASC
                """
            ).fetchall()
        ]

        seed["playerAliases"] = [
            {
                "id": int(r["id"]),
                "player_id": int(r["player_id"]),
                "alias_name": str(r["alias_name"]),
                "created_at": str(r["created_at"]),
            }
            for r in conn.execute(
                "SELECT id, player_id, alias_name, created_at FROM player_aliases ORDER BY id ASC"
            ).fetchall()
        ]

        seed["progressionEntries"] = [
            {
                "id": int(r["id"]),
                "player_id": int(r["player_id"]),
                "recorded_at": str(r["recorded_at"]),
                "metrics": _parse_json_obj(r["metrics_json"]),
                "note": r["note"],
                "created_at": str(r["created_at"]),
                "updated_at": str(r["updated_at"]),
            }
            for r in conn.execute(
                """
                SELECT id, player_id, recorded_at, metrics_json, note, created_at, updated_at
                FROM progression_entries
                ORDER BY id ASC
                """
            ).fetchall()
        ]

        seed["duels"] = [
            {
                "id": int(r["id"]),
                "opponent_clan_name": str(r["opponent_clan_name"]),
                "title": r["title"],
                "start_date": str(r["start_date"]),
                "end_date": r["end_date"],
                "status": str(r["status"]),
                "notes": r["notes"],
                "created_at": str(r["created_at"]),
                "updated_at": str(r["updated_at"]),
            }
            for r in conn.execute(
                """
                SELECT id, opponent_clan_name, title, start_date, end_date,
                       status, notes, created_at, updated_at
                FROM duels
                ORDER BY id ASC
                """
            ).fetchall()
        ]

        seed["duelScores"] = [
            {
                "id": int(r["id"]),
                "duel_id": int(r["duel_id"]),
                "player_id": int(r["player_id"]) if r["player_id"] is not None else None,
                "extracted_name": str(r["extracted_name"]),
                "score": int(r["score"]),
                "score_date": str(r["score_date"]),
                "screenshot_id": None,
                "source": str(r["source"]),
                "created_at": str(r["created_at"]),
                "updated_at": str(r["updated_at"]),
            }
            for r in conn.execute(
                """
                SELECT id, duel_id, player_id, extracted_name, score,
                       score_date, source, created_at, updated_at
                FROM duel_scores
                ORDER BY id ASC
                """
            ).fetchall()
        ]
    finally:
        conn.close()

    return seed


def build_docs(
    *,
    docs_dir: Path = DOCS_DIR,
    static_src: Path = STATIC_SRC,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)

    shutil.copytree(static_src / "css", docs_dir / "css")
    shutil.copytree(static_src / "js", docs_dir / "js")

    (docs_dir / "index.html").write_text(STATIC_INDEX_HTML, encoding="utf-8")
    (docs_dir / "404.html").write_text(REDIRECT_404_HTML, encoding="utf-8")
    (docs_dir / ".nojekyll").write_text("", encoding="utf-8")

    seed = export_seed_from_db(db_path)
    (docs_dir / "seed.json").write_text(
        json.dumps(seed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return seed


if __name__ == "__main__":
    exported = build_docs()
    print(
        f"Built docs/ for GitHub Pages: clan={exported['auth']['clanName']}, "
        f"players={len(exported['players'])}, aliases={len(exported['playerAliases'])}, "
        f"duels={len(exported['duels'])}, limit={exported['activeDailyMinScore']}"
    )
