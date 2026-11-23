from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.db.migrations import run_migrations


def test_player_create_and_validate_ranks_and_tower_levels(authed_client: TestClient) -> None:
    c = authed_client

    # All valid ranks R1-R5 (including lowercase normalization) and tower levels I1-I10 (including Turkish İ/ı/i)
    r1 = c.post(
        "/api/players",
        json={"display_name": "Kuleci1", "clan_rank": "r3", "tower_level": "i7"},
    )
    assert r1.status_code == 201, r1.text
    assert r1.json()["player"]["clan_rank"] == "R3"
    assert r1.json()["player"]["tower_level"] == "I7"

    r2 = c.post(
        "/api/players",
        json={"display_name": "Kuleci10", "clan_rank": "R5", "tower_level": "ı10"},
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["player"]["clan_rank"] == "R5"
    assert r2.json()["player"]["tower_level"] == "I10"

    r3 = c.post(
        "/api/players",
        json={"display_name": "Kuleci3", "clan_rank": "R1", "tower_level": "İ1"},
    )
    assert r3.status_code == 201, r3.text
    assert r3.json()["player"]["clan_rank"] == "R1"
    assert r3.json()["player"]["tower_level"] == "I1"

    # Nullable defaults
    r4 = c.post("/api/players", json={"display_name": "Derecesiz"})
    assert r4.status_code == 201, r4.text
    assert r4.json()["player"]["clan_rank"] is None
    assert r4.json()["player"]["tower_level"] is None

    # Invalid values rejected with 422
    for bad in ("R0", "R6", "Admin", "1"):
        resp = c.post("/api/players", json={"display_name": f"BadRank_{bad}", "clan_rank": bad})
        assert resp.status_code == 422, f"rank={bad} returned {resp.status_code}"

    for bad_tower in ("I0", "I11", "L3", "T5", "10"):
        resp = c.post("/api/players", json={"display_name": f"BadTower_{bad_tower}", "tower_level": bad_tower})
        assert resp.status_code == 422, f"tower={bad_tower} returned {resp.status_code}"


def test_patch_and_filter_player_rank_and_tower_level(authed_client: TestClient) -> None:
    c = authed_client

    p1 = c.post(
        "/api/players",
        json={"display_name": "BetaKule", "clan_rank": "R4", "tower_level": "I8"},
    ).json()["player"]
    p2 = c.post(
        "/api/players",
        json={"display_name": "AlfaKule", "clan_rank": "R5", "tower_level": "I10"},
    ).json()["player"]

    # Patch without touching rank/tower preserves existing values
    keep = c.patch(f"/api/players/{p1['id']}", json={"notes": "Not güncellendi"})
    assert keep.status_code == 200
    assert keep.json()["player"]["clan_rank"] == "R4"
    assert keep.json()["player"]["tower_level"] == "I8"

    # Patch updates rank/tower cleanly
    upd = c.patch(f"/api/players/{p1['id']}", json={"clan_rank": "R5", "tower_level": "I9"})
    assert upd.status_code == 200
    assert upd.json()["player"]["clan_rank"] == "R5"
    assert upd.json()["player"]["tower_level"] == "I9"

    # Filter by clan_rank and tower_level
    by_rank = c.get("/api/players?clan_rank=R5").json()["players"]
    assert {p["display_name"] for p in by_rank} == {"AlfaKule", "BetaKule"}

    by_tower = c.get("/api/players?tower_level=I10").json()["players"]
    assert [p["display_name"] for p in by_tower] == ["AlfaKule"]

    by_both = c.get("/api/players?clan_rank=R5&tower_level=I9").json()["players"]
    assert [p["display_name"] for p in by_both] == ["BetaKule"]

    # Invalid query filter -> 422
    assert c.get("/api/players?clan_rank=R9").status_code == 422
    assert c.get("/api/players?tower_level=I15").status_code == 422

    # Clear rank/tower via empty string or None
    cleared = c.patch(f"/api/players/{p1['id']}", json={"clan_rank": "", "tower_level": None})
    assert cleared.status_code == 200
    assert cleared.json()["player"]["clan_rank"] is None
    assert cleared.json()["player"]["tower_level"] is None
    _ = p2


def test_bulk_import_persists_rank_and_tower_level(authed_client: TestClient) -> None:
    c = authed_client
    resp = c.post(
        "/api/players/import-bulk",
        json={
            "players": [
                {"display_name": "TopluUye1", "clan_rank": "r4", "tower_level": "i6"},
                {"display_name": "TopluUye2", "clan_rank": "R2", "tower_level": "I3"},
            ]
        },
    )
    assert resp.status_code == 201, resp.text
    created = {p["display_name"]: p for p in resp.json()["createdPlayers"]}
    assert created["TopluUye1"]["clan_rank"] == "R4"
    assert created["TopluUye1"]["tower_level"] == "I6"
    assert created["TopluUye2"]["clan_rank"] == "R2"
    assert created["TopluUye2"]["tower_level"] == "I3"


def test_legacy_sqlite_database_upgrades_add_rank_and_tower_columns(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # Simulate pre-feature players table lacking clan_rank and tower_level
        conn.executescript(
            """
            CREATE TABLE players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                status TEXT NOT NULL DEFAULT 'active',
                joined_at TEXT,
                notes TEXT,
                profile_values_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            );
            INSERT INTO players (display_name, status) VALUES ('EskiOyuncu', 'active');
            """
        )
        conn.commit()

        # Run migrations twice to verify idempotency
        run_migrations(conn)
        run_migrations(conn)

        cols = {row[1] for row in conn.execute("PRAGMA table_info(players)").fetchall()}
        assert "clan_rank" in cols
        assert "tower_level" in cols

        row = conn.execute(
            "SELECT display_name, clan_rank, tower_level FROM players WHERE display_name = 'EskiOyuncu'"
        ).fetchone()
        assert row is not None
        assert row["display_name"] == "EskiOyuncu"
        assert row["clan_rank"] is None
        assert row["tower_level"] is None
    finally:
        conn.close()


def test_list_players_sorting_all_six_modes_and_nulls_last(authed_client: TestClient) -> None:
    c = authed_client
    for payload in (
        {"display_name": "Zebra", "clan_rank": "R1", "tower_level": "I9"},
        {"display_name": "Alfa", "clan_rank": "R5", "tower_level": "I10"},
        {"display_name": "Orta", "clan_rank": "R3", "tower_level": "I1"},
        {"display_name": "Boslu", "clan_rank": None, "tower_level": None},
    ):
        assert c.post("/api/players", json=payload).status_code == 201

    def names(sort_param: str | None) -> list[str]:
        qs = f"?sort={sort_param}" if sort_param is not None else ""
        r = c.get(f"/api/players{qs}")
        assert r.status_code == 200, r.text
        return [p["display_name"] for p in r.json()["players"]]

    # Default (no param) matches name_asc
    assert names(None) == ["Alfa", "Boslu", "Orta", "Zebra"]
    assert names("name_asc") == ["Alfa", "Boslu", "Orta", "Zebra"]
    assert names("name_desc") == ["Zebra", "Orta", "Boslu", "Alfa"]

    # Rank desc / asc: nulls stay last
    assert names("rank_desc") == ["Alfa", "Orta", "Zebra", "Boslu"]
    assert names("rank_asc") == ["Zebra", "Orta", "Alfa", "Boslu"]

    # Tower desc / asc: numeric order (I10 > I9 > I1) and nulls stay last
    assert names("tower_desc") == ["Alfa", "Zebra", "Orta", "Boslu"]
    assert names("tower_asc") == ["Orta", "Zebra", "Alfa", "Boslu"]

    # Invalid sort -> 422
    assert c.get("/api/players?sort=invalid").status_code == 422
