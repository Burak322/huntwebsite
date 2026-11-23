from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.connection import get_connection
from app.db.migrations import run_migrations
from app.main import create_app


EXPECTED_TABLES = {
    "admin_users",
    "admin_sessions",
    "system_settings",
    "daily_limit_history",
    "tracking_fields",
    "players",
    "player_aliases",
    "progression_entries",
    "duels",
    "duel_screenshots",
    "duel_scores",
}


def test_health_endpoint_public(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "db": "connected"}


def test_schema_11_tables_pragmas_and_seed(db_conn: sqlite3.Connection) -> None:
    table_rows = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    table_names = {row["name"] for row in table_rows}
    assert EXPECTED_TABLES.issubset(table_names)
    assert len(table_names) == 11

    index_rows = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    index_names = {row["name"] for row in index_rows}
    assert {
        "idx_progression_entries_player_recorded",
        "idx_duel_scores_duel_date",
        "idx_duel_scores_player_date",
        "idx_player_aliases_player_id",
        "idx_admin_sessions_admin_id",
    }.issubset(index_names)

    fk_enabled = db_conn.execute("PRAGMA foreign_keys").fetchone()[0]
    journal_mode = db_conn.execute("PRAGMA journal_mode").fetchone()[0]
    busy_timeout = db_conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert fk_enabled == 1
    assert str(journal_mode).lower() == "wal"
    assert busy_timeout == 5000

    settings_rows = {
        row["key"]: row["value"]
        for row in db_conn.execute("SELECT key, value FROM system_settings").fetchall()
    }
    assert settings_rows["daily_min_score"] == "0"
    assert settings_rows["clan_name"] == "Klanım"


def test_foreign_key_cascades_and_set_null(db_conn: sqlite3.Connection) -> None:
    player_cur = db_conn.execute(
        "INSERT INTO players (display_name, status) VALUES ('OyuncuBir', 'active')"
    )
    player_id = int(player_cur.lastrowid)

    db_conn.execute(
        "INSERT INTO player_aliases (player_id, alias_name) VALUES (?, 'AliasBir')",
        (player_id,),
    )
    db_conn.execute(
        "INSERT INTO progression_entries (player_id, recorded_at, metrics_json) VALUES (?, '2026-11-22', '{\"power\": 100}')",
        (player_id,),
    )
    duel_cur = db_conn.execute(
        "INSERT INTO duels (opponent_clan_name, start_date) VALUES ('RakipKlan', '2026-11-22')"
    )
    duel_id = int(duel_cur.lastrowid)

    score_cur = db_conn.execute(
        """
        INSERT INTO duel_scores (duel_id, player_id, extracted_name, score, score_date, source)
        VALUES (?, ?, 'OyuncuBir', 5000, '2026-11-22', 'manual')
        """,
        (duel_id, player_id),
    )
    score_id = int(score_cur.lastrowid)
    db_conn.commit()

    db_conn.execute("DELETE FROM players WHERE id = ?", (player_id,))
    db_conn.commit()

    assert (
        db_conn.execute("SELECT COUNT(*) FROM player_aliases WHERE player_id = ?", (player_id,)).fetchone()[0]
        == 0
    )
    assert (
        db_conn.execute(
            "SELECT COUNT(*) FROM progression_entries WHERE player_id = ?", (player_id,)
        ).fetchone()[0]
        == 0
    )
    score_row = db_conn.execute(
        "SELECT player_id, extracted_name, score FROM duel_scores WHERE id = ?",
        (score_id,),
    ).fetchone()
    assert score_row is not None
    assert score_row["player_id"] is None
    assert score_row["extracted_name"] == "OyuncuBir"
    assert score_row["score"] == 5000


def test_multi_app_env_db_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_a = tmp_path / "db_a.db"
    db_b = tmp_path / "db_b.db"
    upload_a = tmp_path / "uploads_a"
    upload_b = tmp_path / "uploads_b"

    monkeypatch.setenv("CLAN_DB_PATH", str(db_a))
    monkeypatch.setenv("CLAN_UPLOAD_DIR", str(upload_a))
    app_a = create_app()

    monkeypatch.setenv("CLAN_DB_PATH", str(db_b))
    monkeypatch.setenv("CLAN_UPLOAD_DIR", str(upload_b))
    app_b = create_app()

    with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
        resp_a = client_a.post(
            "/api/auth/setup",
            json={"username": "admin_a", "password": "PasswordA1!", "clanName": "Klan A"},
        )
        assert resp_a.status_code == 201

        # DB B must still require setup and have zero admins
        status_b = client_b.get("/api/auth/status")
        assert status_b.status_code == 200
        assert status_b.json()["needsSetup"] is True
        assert status_b.json()["clanName"] == "Klanım"

        resp_b = client_b.post(
            "/api/auth/setup",
            json={"username": "admin_b", "password": "PasswordB1!", "clanName": "Klan B"},
        )
        assert resp_b.status_code == 201
        assert client_a.get("/api/auth/me").json()["clanName"] == "Klan A"
        assert client_b.get("/api/auth/me").json()["clanName"] == "Klan B"


def test_unauthenticated_api_routes_return_401(client: TestClient) -> None:
    protected_calls = [
        ("GET", "/api/auth/me"),
        ("POST", "/api/auth/logout"),
        ("POST", "/api/auth/change-password"),
        ("PUT", "/api/settings/clan"),
        ("GET", "/api/players"),
        ("GET", "/api/duels"),
        ("GET", "/api/limits/daily"),
        ("GET", "/api/unknown"),
        ("POST", "/api/unknown"),
    ]
    for method, path in protected_calls:
        resp = client.request(method, path)
        assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"
        assert resp.headers["content-type"].startswith("application/json")


def test_authenticated_unknown_api_returns_404_json(authed_client: TestClient) -> None:
    for method in ("GET", "POST"):
        resp = authed_client.request(method, "/api/does-not-exist")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")
        assert "detail" in resp.json()


def test_unauthenticated_ui_routes_redirect(client: TestClient) -> None:
    # Before setup -> redirect to /setup
    for path in ("/", "/players", "/duels", "/settings", "/login"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/setup"

    setup_page = client.get("/setup", follow_redirects=False)
    assert setup_page.status_code == 200
    assert "text/html" in setup_page.headers["content-type"]

    # Create admin and clear cookies -> redirect to /login
    create_resp = client.post(
        "/api/auth/setup",
        json={"username": "lider", "password": "Password123!"},
    )
    assert create_resp.status_code == 201
    client.cookies.clear()

    for path in ("/", "/players", "/duels", "/settings", "/setup"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"


def test_setup_201_cookie_flags_and_409_lock(client: TestClient) -> None:
    status_before = client.get("/api/auth/status")
    assert status_before.status_code == 200
    assert status_before.json() == {
        "needsSetup": True,
        "authenticated": False,
        "admin": None,
        "clanName": "Klanım",
    }

    setup_resp = client.post(
        "/api/auth/setup",
        json={"username": "lider", "password": "Password123!", "clanName": "Efsane Klan"},
    )
    assert setup_resp.status_code == 201
    assert setup_resp.json()["admin"]["username"] == "lider"
    assert setup_resp.json()["clanName"] == "Efsane Klan"

    set_cookie = setup_resp.headers.get("set-cookie", "")
    assert "clan_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie.lower() or "samesite=lax" in set_cookie.lower()
    assert "Path=/" in set_cookie

    second_setup = client.post(
        "/api/auth/setup",
        json={"username": "baska", "password": "Password123!"},
    )
    assert second_setup.status_code == 409


def test_login_200_and_401(client: TestClient) -> None:
    client.post(
        "/api/auth/setup",
        json={"username": "lider", "password": "Password123!", "clanName": "Klanım"},
    )
    client.cookies.clear()

    bad_login = client.post(
        "/api/auth/login",
        json={"username": "lider", "password": "WrongPassword!"},
    )
    assert bad_login.status_code == 401

    good_login = client.post(
        "/api/auth/login",
        json={"username": "lider", "password": "Password123!"},
    )
    assert good_login.status_code == 200
    assert "clan_session=" in good_login.headers.get("set-cookie", "")

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["admin"]["username"] == "lider"


def test_logout_clears_and_invalidates_session(authed_client: TestClient) -> None:
    saved_token = authed_client.cookies.get("clan_session")
    assert saved_token

    logout_resp = authed_client.post("/api/auth/logout")
    assert logout_resp.status_code == 200
    assert logout_resp.json() == {"ok": True}

    # Even if a client replays the old session cookie, the server-side row is gone
    authed_client.cookies.set("clan_session", saved_token)
    assert authed_client.get("/api/auth/me").status_code == 401


def test_expired_cookie_rejected_with_401(
    authed_client: TestClient,
    test_settings: Settings,
) -> None:
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection(test_settings.db_path) as conn:
        conn.execute("UPDATE admin_sessions SET expires_at = ?", (past_iso,))

    me_resp = authed_client.get("/api/auth/me")
    assert me_resp.status_code == 401

    status_resp = authed_client.get("/api/auth/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["authenticated"] is False


def test_change_password_and_relogin(authed_client: TestClient) -> None:
    bad_change = authed_client.post(
        "/api/auth/change-password",
        json={"currentPassword": "WrongCurrentPassword", "newPassword": "NewStrongPassword9!"},
    )
    assert bad_change.status_code == 400

    ok_change = authed_client.post(
        "/api/auth/change-password",
        json={"currentPassword": "StrongPassword123!", "newPassword": "NewStrongPassword9!"},
    )
    assert ok_change.status_code == 200
    assert ok_change.json()["ok"] is True

    authed_client.cookies.clear()
    assert (
        authed_client.post(
            "/api/auth/login",
            json={"username": "lider", "password": "StrongPassword123!"},
        ).status_code
        == 401
    )
    assert (
        authed_client.post(
            "/api/auth/login",
            json={"username": "lider", "password": "NewStrongPassword9!"},
        ).status_code
        == 200
    )


def test_update_clan_name(authed_client: TestClient) -> None:
    resp = authed_client.put("/api/settings/clan", json={"clanName": "Yeni Klan"})
    assert resp.status_code == 200
    assert resp.json() == {"clanName": "Yeni Klan"}

    assert authed_client.get("/api/auth/me").json()["clanName"] == "Yeni Klan"
    assert authed_client.get("/api/auth/status").json()["clanName"] == "Yeni Klan"


def test_sqlite_persistence_across_create_app_restart(test_settings: Settings) -> None:
    app1 = create_app(test_settings)
    with TestClient(app1) as client1:
        setup_resp = client1.post(
            "/api/auth/setup",
            json={"username": "kalici_lider", "password": "PersistPassword1!", "clanName": "Kalıcı Klan"},
        )
        assert setup_resp.status_code == 201
        session_cookie = client1.cookies.get("clan_session")
        assert session_cookie
        client1.put("/api/settings/clan", json={"clanName": "Güncel Klan"})

    # Simulate full server restart pointing to same SQLite DB
    app2 = create_app(test_settings)
    with TestClient(app2) as client2:
        status_resp = client2.get("/api/auth/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["needsSetup"] is False
        assert status_resp.json()["clanName"] == "Güncel Klan"

        client2.cookies.set("clan_session", session_cookie)
        me_resp = client2.get("/api/auth/me")
        assert me_resp.status_code == 200
        assert me_resp.json()["admin"]["username"] == "kalici_lider"
        assert me_resp.json()["clanName"] == "Güncel Klan"

        client2.cookies.clear()
        login_resp = client2.post(
            "/api/auth/login",
            json={"username": "kalici_lider", "password": "PersistPassword1!"},
        )
        assert login_resp.status_code == 200


def test_env_admin_bootstrap_idempotent(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "env_boot.db",
        upload_dir=tmp_path / "uploads",
        admin_username="envlider",
        admin_password="EnvPassword123!",
    )
    app1 = create_app(settings)
    with get_connection(settings.db_path) as conn:
        run_migrations(conn, settings=settings)
        cnt = conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
        assert cnt == 1

    with TestClient(app1) as c1:
        status_resp = c1.get("/api/auth/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["needsSetup"] is False

        login_resp = c1.post(
            "/api/auth/login",
            json={"username": "envlider", "password": "EnvPassword123!"},
        )
        assert login_resp.status_code == 200


def test_spa_html_and_static_assets_served(authed_client: TestClient) -> None:
    # Authenticated root serves SPA HTML; /setup & /login redirect to /
    root_resp = authed_client.get("/")
    assert root_resp.status_code == 200
    assert 'lang="tr"' in root_resp.text
    assert "Klan Yönetim Sistemi" in root_resp.text

    assert authed_client.get("/login", follow_redirects=False).status_code == 302
    assert authed_client.get("/setup", follow_redirects=False).status_code == 302

    authed_client.cookies.clear()
    login_html = authed_client.get("/login")
    assert login_html.status_code == 200
    assert 'lang="tr"' in login_html.text

    for asset in (
        "/css/styles.css",
        "/js/api.js",
        "/js/router.js",
        "/js/components/nav.js",
        "/js/pages/setupPage.js",
        "/js/pages/loginPage.js",
        "/js/pages/dashboardPage.js",
    ):
        resp = authed_client.get(asset)
        assert resp.status_code == 200, f"Asset {asset} returned {resp.status_code}"

    missing_css = authed_client.get("/css/missing.css")
    assert missing_css.status_code == 404
    assert missing_css.headers["content-type"].startswith("application/json")

    fav = authed_client.get("/favicon.ico")
    assert fav.status_code == 204
