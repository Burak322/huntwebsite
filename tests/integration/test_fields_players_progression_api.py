from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _create_field(client: TestClient, **payload) -> dict:
    resp = client.post("/api/fields", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["field"]


def _create_player(client: TestClient, **payload) -> dict:
    resp = client.post("/api/players", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["player"]


def test_m2_all_15_endpoints_require_auth_and_slash_normalization(
    client: TestClient,
) -> None:
    protected_calls = [
        ("GET", "/api/fields"),
        ("POST", "/api/fields"),
        ("PATCH", "/api/fields/1"),
        ("DELETE", "/api/fields/1"),
        ("GET", "/api/players"),
        ("POST", "/api/players"),
        ("GET", "/api/players/1"),
        ("PATCH", "/api/players/1"),
        ("DELETE", "/api/players/1"),
        ("POST", "/api/players/1/aliases"),
        ("DELETE", "/api/players/1/aliases/1"),
        ("GET", "/api/players/1/progression"),
        ("POST", "/api/players/1/progression"),
        ("PATCH", "/api/progression/1"),
        ("DELETE", "/api/progression/1"),
        # M1 Caveat #1 hardening: repeated slashes in request path must still return 401
        ("GET", "http://testserver//api/fields"),
        ("GET", "http://testserver//api/players"),
        ("GET", "/api/fields//"),
    ]
    for method, path in protected_calls:
        resp = client.request(method, path)
        assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"
        assert resp.headers["content-type"].startswith("application/json")

    # Public health with trailing slash should still succeed cleanly
    health_slash = client.get("/api/health/")
    assert health_slash.status_code == 200
    assert health_slash.json() == {"ok": True, "db": "connected"}


def test_authenticated_slash_normalization_and_logout_401(
    authed_client: TestClient,
) -> None:
    resp_trailing = authed_client.get("/api/fields/")
    assert resp_trailing.status_code == 200
    assert resp_trailing.json() == {"fields": []}

    resp_double = authed_client.get("http://testserver//api/players")
    assert resp_double.status_code == 200
    assert resp_double.json() == {"players": []}

    resp_double_trailing = authed_client.get("/api/players//")
    assert resp_double_trailing.status_code == 200
    assert resp_double_trailing.json() == {"players": []}

    unknown_post = authed_client.post("/api/does-not-exist")
    assert unknown_post.status_code == 404
    assert "detail" in unknown_post.json()

    authed_client.cookies.clear()
    assert authed_client.get("/api/fields").status_code == 401
    assert authed_client.get("/api/players").status_code == 401


def test_fields_full_lifecycle_slugs_immutability_and_archive_vs_delete(
    authed_client: TestClient,
) -> None:
    # Create all 5 field types across both scopes + Turkish slugification
    f_text = _create_field(
        authed_client,
        label="İttifak Gücü — Şehir (Özel)",
        scope="profile",
        field_type="text",
        is_required=True,
        sort_order=20,
    )
    assert f_text["field_key"] == "ittifak_gucu_sehir_ozel"

    # Auto-suffix _2 on omitted field_key collision
    f_text_2 = _create_field(
        authed_client,
        label="İttifak Gücü — Şehir (Özel)",
        scope="profile",
        field_type="text",
        sort_order=30,
    )
    assert f_text_2["field_key"] == "ittifak_gucu_sehir_ozel_2"

    # Punctuation-only label with omitted field_key -> 422
    bad_label = authed_client.post(
        "/api/fields",
        json={"label": "--- !!! ---", "scope": "profile", "field_type": "text"},
    )
    assert bad_label.status_code == 422

    # Explicit field_key collision -> 409
    explicit_dup = authed_client.post(
        "/api/fields",
        json={
            "label": "Başka Etiket",
            "field_key": "ittifak_gucu_sehir_ozel",
            "scope": "profile",
            "field_type": "text",
        },
    )
    assert explicit_dup.status_code == 409

    f_select = _create_field(
        authed_client,
        label="Birlik Sınıfı",
        field_key="birlik_sinifi",
        scope="profile",
        field_type="select",
        options=["Piyade", "Okçu", "Süvari"],
        sort_order=5,
    )
    f_bool = _create_field(
        authed_client,
        label="VIP Aktif",
        field_key="vip_aktif",
        scope="profile",
        field_type="boolean",
        sort_order=10,
    )
    f_date = _create_field(
        authed_client,
        label="Kayıt Tarihi",
        field_key="kayit_tarihi",
        scope="profile",
        field_type="date",
        sort_order=15,
    )
    f_prog_num = _create_field(
        authed_client,
        label="Toplam Güç",
        field_key="toplam_guc",
        scope="progression",
        field_type="number",
        unit="Güç",
        is_required=True,
        sort_order=1,
    )
    f_prog_bool = _create_field(
        authed_client,
        label="Haftalık Hazır",
        field_key="haftalik_hazir",
        scope="progression",
        field_type="boolean",
        sort_order=2,
    )

    # Filter & deterministic sort_order ASC, id ASC
    prof_resp = authed_client.get("/api/fields?scope=profile&activeOnly=true")
    assert prof_resp.status_code == 200
    prof_keys = [f["field_key"] for f in prof_resp.json()["fields"]]
    assert prof_keys == [
        "birlik_sinifi",
        "vip_aktif",
        "kayit_tarihi",
        "ittifak_gucu_sehir_ozel",
        "ittifak_gucu_sehir_ozel_2",
    ]

    # PATCH mutable attributes & reject immutable modifications
    patch_ok = authed_client.patch(
        f"/api/fields/{f_prog_num['id']}",
        json={"label": "Savaş Gücü", "unit": "Puan", "sort_order": 0},
    )
    assert patch_ok.status_code == 200
    assert patch_ok.json()["field"]["label"] == "Savaş Gücü"
    assert patch_ok.json()["field"]["unit"] == "Puan"

    # Sending identical immutable fields is harmless
    patch_same_immut = authed_client.patch(
        f"/api/fields/{f_prog_num['id']}",
        json={
            "field_key": "toplam_guc",
            "scope": "progression",
            "field_type": "number",
            "label": "Savaş Gücü Güncel",
        },
    )
    assert patch_same_immut.status_code == 200

    # Changing immutable field_key / scope / field_type -> 422
    for bad_patch in (
        {"field_key": "baska_key"},
        {"scope": "profile"},
        {"field_type": "text"},
    ):
        r = authed_client.patch(f"/api/fields/{f_prog_num['id']}", json=bad_patch)
        assert r.status_code == 422

    assert authed_client.patch("/api/fields/99999", json={"label": "Yok"}).status_code == 404

    # Hard-delete unreferenced field
    del_unused = authed_client.delete(f"/api/fields/{f_text_2['id']}")
    assert del_unused.status_code == 200
    assert del_unused.json() == {"deleted": True, "archived": False}
    all_keys = [
        f["field_key"] for f in authed_client.get("/api/fields?activeOnly=false").json()["fields"]
    ]
    assert "ittifak_gucu_sehir_ozel_2" not in all_keys

    # Reference profile boolean field with falsy False, and progression number field with falsy 0
    player = _create_player(
        authed_client,
        display_name="DenizHan",
        profile_values={
            "ittifak_gucu_sehir_ozel": "Başkent",
            "birlik_sinifi": "Okçu",
            "vip_aktif": False,
            "kayit_tarihi": "2026-11-22",
        },
    )
    prog_resp = authed_client.post(
        f"/api/players/{player['id']}/progression",
        json={
            "recorded_at": "2026-11-22",
            "metrics": {"toplam_guc": 0, "haftalik_hazir": False},
        },
    )
    assert prog_resp.status_code == 201, prog_resp.text

    # Deleting referenced fields (even with falsy False / 0) MUST soft-archive
    arch_bool = authed_client.delete(f"/api/fields/{f_bool['id']}")
    assert arch_bool.status_code == 200
    assert arch_bool.json() == {"deleted": True, "archived": True}

    arch_req_prog = authed_client.delete(f"/api/fields/{f_prog_num['id']}")
    assert arch_req_prog.status_code == 200
    assert arch_req_prog.json() == {"deleted": True, "archived": True}

    active_prog_keys = [
        f["field_key"]
        for f in authed_client.get("/api/fields?scope=progression&activeOnly=true").json()["fields"]
    ]
    assert "toplam_guc" not in active_prog_keys
    all_prog = authed_client.get("/api/fields?scope=progression&activeOnly=false").json()["fields"]
    archived_item = next(f for f in all_prog if f["field_key"] == "toplam_guc")
    assert archived_item["is_active"] is False

    # Archived required progression field no longer blocks creating new progression entries
    prog_after_archive = authed_client.post(
        f"/api/players/{player['id']}/progression",
        json={"recorded_at": "2026-11-23", "metrics": {"haftalik_hazir": True}},
    )
    assert prog_after_archive.status_code == 201
    assert authed_client.delete("/api/fields/99999").status_code == 404
    _ = (f_select, f_date, f_prog_bool)


def test_players_aliases_search_atomic_rollback_and_fk_cascades(
    authed_client: TestClient,
    db_conn: sqlite3.Connection,
) -> None:
    _create_field(
        authed_client,
        label="Seviye",
        field_key="seviye",
        scope="profile",
        field_type="number",
        is_required=True,
    )
    _create_field(
        authed_client,
        label="Not",
        field_key="ozel_not",
        scope="profile",
        field_type="text",
        is_required=False,
    )
    _create_field(
        authed_client,
        label="Savaş Puanı",
        field_key="savas_puani",
        scope="progression",
        field_type="number",
    )

    p1 = _create_player(
        authed_client,
        display_name="BozKurt",
        status="active",
        joined_at="2026-11-01",
        notes="Klan komutanı",
        profile_values={"seviye": 50, "ozel_not": "Piyade lideri"},
        aliases=["GhostWolf", "Boz_Alt"],
    )
    assert p1["display_name"] == "BozKurt"
    assert len(p1["aliases"]) == 2
    assert p1["latestProgression"] is None

    p2 = _create_player(
        authed_client,
        display_name="KaraŞahin",
        status="inactive",
        profile_values={"seviye": 40},
        aliases=["Şahin_TR", "100%_Gerçek"],
    )

    # Validation errors (422)
    for bad_payload in (
        {"display_name": "   ", "profile_values": {"seviye": 1}},
        {"display_name": "Yeni", "status": "banned", "profile_values": {"seviye": 1}},
        {"display_name": "Yeni", "profile_values": {}},  # missing required seviye
        {"display_name": "Yeni", "profile_values": {"seviye": True}},  # bool-is-int trap
        {"display_name": "Yeni", "profile_values": {"seviye": 1, "unknown": "x"}},
        {"display_name": "Yeni", "profile_values": {"seviye": 1, "savas_puani": 100}},  # cross-scope
    ):
        r = authed_client.post("/api/players", json=bad_payload)
        assert r.status_code == 422, f"{bad_payload} returned {r.status_code}"

    # Duplicate display_name (ASCII NOCASE + Turkish case) -> 409
    assert (
        authed_client.post(
            "/api/players",
            json={"display_name": "bozkurt", "profile_values": {"seviye": 10}},
        ).status_code
        == 409
    )
    assert (
        authed_client.post(
            "/api/players",
            json={"display_name": "karaşahin", "profile_values": {"seviye": 10}},
        ).status_code
        == 409
    )

    # Atomic rollback when alias collides on POST /api/players -> 409 and NO orphan player row
    orphan_attempt = authed_client.post(
        "/api/players",
        json={
            "display_name": "YetimKalmayacak",
            "profile_values": {"seviye": 20},
            "aliases": ["TemizTakmaAd", "ghostwolf"],
        },
    )
    assert orphan_attempt.status_code == 409
    orphan_row = db_conn.execute(
        "SELECT id FROM players WHERE display_name = 'YetimKalmayacak'"
    ).fetchone()
    assert orphan_row is None

    # List, status filter, search by display_name, Turkish alias search, wildcard safety
    assert authed_client.get("/api/players?status=").status_code == 200
    assert len(authed_client.get("/api/players?status=").json()["players"]) == 2
    assert authed_client.get("/api/players?status=invalid").status_code == 422

    active_list = authed_client.get("/api/players?status=active").json()["players"]
    assert [p["display_name"] for p in active_list] == ["BozKurt"]

    # Matching multiple aliases/name for BozKurt must return BozKurt exactly ONCE
    search_boz = authed_client.get("/api/players?search=boz").json()["players"]
    assert [p["display_name"] for p in search_boz] == ["BozKurt"]

    search_tr_alias = authed_client.get("/api/players?search=şahin_tr").json()["players"]
    assert [p["display_name"] for p in search_tr_alias] == ["KaraŞahin"]

    # SQL LIKE wildcard safety (% should match literal % only, not BozKurt)
    search_pct = authed_client.get("/api/players?search=100%25_").json()["players"]
    assert [p["display_name"] for p in search_pct] == ["KaraŞahin"]

    # Partial PATCH preserves untouched profile_values & rejects rename collision
    patch_conflict = authed_client.patch(
        f"/api/players/{p2['id']}",
        json={"display_name": "bozkurt"},
    )
    assert patch_conflict.status_code == 409

    patch_p1 = authed_client.patch(
        f"/api/players/{p1['id']}",
        json={"status": "inactive", "profile_values": {"seviye": 55}},
    )
    assert patch_p1.status_code == 200
    assert patch_p1.json()["player"]["status"] == "inactive"
    assert patch_p1.json()["player"]["profile_values"] == {
        "seviye": 55,
        "ozel_not": "Piyade lideri",
    }

    # Aliases add/conflict/cross-player delete
    add_a = authed_client.post(
        f"/api/players/{p2['id']}/aliases",
        json={"alias_name": "YeniSahin"},
    )
    assert add_a.status_code == 201
    p2_alias_id = add_a.json()["alias"]["id"]

    # Global NOCASE conflict across players and against display_name
    assert (
        authed_client.post(
            f"/api/players/{p2['id']}/aliases",
            json={"alias_name": "ghostwolf"},
        ).status_code
        == 409
    )
    assert (
        authed_client.post(
            f"/api/players/{p2['id']}/aliases",
            json={"alias_name": "bozkurt"},
        ).status_code
        == 409
    )
    assert (
        authed_client.post(
            f"/api/players/{p2['id']}/aliases",
            json={"alias_name": "   "},
        ).status_code
        == 422
    )

    # Cross-player alias delete MUST return 404 and leave p2's alias intact
    assert (
        authed_client.delete(f"/api/players/{p1['id']}/aliases/{p2_alias_id}").status_code
        == 404
    )
    assert (
        db_conn.execute(
            "SELECT id FROM player_aliases WHERE id = ?", (p2_alias_id,)
        ).fetchone()
        is not None
    )
    assert authed_client.delete(f"/api/players/{p2['id']}/aliases/{p2_alias_id}").status_code == 200

    # Seed duel + duel_scores and progression entry to test GET detail & DELETE FK cascades
    duel_cur = db_conn.execute(
        "INSERT INTO duels (opponent_clan_name, start_date, status) VALUES ('RakipKlan', '2026-11-22', 'ongoing')"
    )
    duel_id = int(duel_cur.lastrowid)
    score_cur = db_conn.execute(
        """
        INSERT INTO duel_scores (duel_id, player_id, extracted_name, score, score_date, source)
        VALUES (?, ?, 'BozKurt', 14250, '2026-11-22', 'manual')
        """,
        (duel_id, p1["id"]),
    )
    score_id = int(score_cur.lastrowid)
    db_conn.commit()

    assert (
        authed_client.post(
            f"/api/players/{p1['id']}/progression",
            json={"recorded_at": "2026-11-22", "metrics": {"savas_puani": 999}},
        ).status_code
        == 201
    )

    detail = authed_client.get(f"/api/players/{p1['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["player"]["id"] == p1["id"]
    assert len(body["aliases"]) == 2
    assert len(body["progressionEntries"]) == 1
    assert len(body["recentDuelScores"]) == 1
    assert body["recentDuelScores"][0]["score"] == 14250
    assert body["recentDuelScores"][0]["opponent_clan_name"] == "RakipKlan"
    assert authed_client.get("/api/players/99999").status_code == 404

    # Delete player -> cascade aliases & progression_entries, SET NULL on duel_scores
    del_p1 = authed_client.delete(f"/api/players/{p1['id']}")
    assert del_p1.status_code == 200
    assert del_p1.json() == {"deleted": True}
    assert authed_client.get(f"/api/players/{p1['id']}").status_code == 404
    assert authed_client.delete(f"/api/players/{p1['id']}").status_code == 404

    assert (
        db_conn.execute(
            "SELECT COUNT(*) FROM player_aliases WHERE player_id = ?", (p1["id"],)
        ).fetchone()[0]
        == 0
    )
    assert (
        db_conn.execute(
            "SELECT COUNT(*) FROM progression_entries WHERE player_id = ?", (p1["id"],)
        ).fetchone()[0]
        == 0
    )
    score_after = db_conn.execute(
        "SELECT player_id, score FROM duel_scores WHERE id = ?", (score_id,)
    ).fetchone()
    assert score_after is not None
    assert score_after["player_id"] is None
    assert score_after["score"] == 14250


def test_progression_chronological_deltas_tie_breaking_and_mutations(
    authed_client: TestClient,
) -> None:
    _create_field(
        authed_client,
        label="Seviye",
        field_key="seviye",
        scope="profile",
        field_type="number",
    )
    _create_field(
        authed_client,
        label="Güç",
        field_key="guc",
        scope="progression",
        field_type="number",
        is_required=True,
    )
    _create_field(
        authed_client,
        label="Hazır",
        field_key="hazir",
        scope="progression",
        field_type="boolean",
    )

    player = _create_player(authed_client, display_name="AlpArslan")
    pid = player["id"]

    # Validation errors
    for bad_prog in (
        {"recorded_at": "bugün", "metrics": {"guc": 100}},
        {"recorded_at": "2026-11-10", "metrics": {}},  # missing required guc
        {"recorded_at": "2026-11-10", "metrics": {"guc": True}},  # bool trap
        {"recorded_at": "2026-11-10", "metrics": {"guc": 100, "seviye": 5}},  # profile key
    ):
        r = authed_client.post(f"/api/players/{pid}/progression", json=bad_prog)
        assert r.status_code == 422

    assert (
        authed_client.post(
            "/api/players/99999/progression",
            json={"recorded_at": "2026-11-10", "metrics": {"guc": 100}},
        ).status_code
        == 404
    )

    # Insert out of chronological order, including a recorded_at tie
    e_oldest = authed_client.post(
        f"/api/players/{pid}/progression",
        json={"recorded_at": "2026-11-10", "metrics": {"guc": 1000, "hazir": True}},
    ).json()["entry"]
    e_newest = authed_client.post(
        f"/api/players/{pid}/progression",
        json={"recorded_at": "2026-11-20", "metrics": {"guc": 1550, "hazir": False}},
    ).json()["entry"]
    e_middle = authed_client.post(
        f"/api/players/{pid}/progression",
        json={"recorded_at": "2026-11-15", "metrics": {"guc": 1200, "hazir": True}},
    ).json()["entry"]
    e_tie = authed_client.post(
        f"/api/players/{pid}/progression",
        json={"recorded_at": "2026-11-20", "metrics": {"guc": 1600}},
    ).json()["entry"]
    assert e_tie["deltas"] == {"guc": 50}

    # Check ASC order & deltas (booleans MUST NOT produce deltas)
    asc_entries = authed_client.get(
        f"/api/players/{pid}/progression?order=asc"
    ).json()["entries"]
    assert [e["id"] for e in asc_entries] == [
        e_oldest["id"],
        e_middle["id"],
        e_newest["id"],
        e_tie["id"],
    ]
    assert asc_entries[0]["deltas"] == {}
    assert asc_entries[1]["deltas"] == {"guc": 200}
    assert asc_entries[2]["deltas"] == {"guc": 350}
    assert asc_entries[3]["deltas"] == {"guc": 50}

    # Default DESC order & latestProgression matches (recorded_at DESC, id DESC) -> e_tie
    desc_entries = authed_client.get(f"/api/players/{pid}/progression").json()["entries"]
    assert [e["id"] for e in desc_entries] == [
        e_tie["id"],
        e_newest["id"],
        e_middle["id"],
        e_oldest["id"],
    ]
    players_list = authed_client.get("/api/players").json()["players"]
    assert players_list[0]["latestProgression"]["id"] == e_tie["id"]

    # PATCH note only preserves existing metrics_json; PATCH metrics recalculates deltas
    patch_note = authed_client.patch(
        f"/api/progression/{e_middle['id']}",
        json={"note": "Ara güncelleme"},
    )
    assert patch_note.status_code == 200
    assert patch_note.json()["entry"]["metrics"] == {"guc": 1200, "hazir": True}
    assert patch_note.json()["entry"]["note"] == "Ara güncelleme"

    patch_metric = authed_client.patch(
        f"/api/progression/{e_middle['id']}",
        json={"metrics": {"guc": 1300}},
    )
    assert patch_metric.status_code == 200
    assert patch_metric.json()["entry"]["deltas"] == {"guc": 300}
    assert patch_metric.json()["entry"]["metrics"] == {"guc": 1300, "hazir": True}

    asc_after_patch = authed_client.get(
        f"/api/players/{pid}/progression?order=asc"
    ).json()["entries"]
    assert asc_after_patch[2]["deltas"] == {"guc": 250}  # 1550 - 1300

    # DELETE middle snapshot -> e_newest delta recalculates to 550 (1550 - 1000)
    assert authed_client.delete(f"/api/progression/{e_middle['id']}").status_code == 200
    asc_after_del_mid = authed_client.get(
        f"/api/players/{pid}/progression?order=asc"
    ).json()["entries"]
    assert [e["id"] for e in asc_after_del_mid] == [
        e_oldest["id"],
        e_newest["id"],
        e_tie["id"],
    ]
    assert asc_after_del_mid[1]["deltas"] == {"guc": 550}

    # DELETE newest tie -> latestProgression reverts to e_newest
    assert authed_client.delete(f"/api/progression/{e_tie['id']}").status_code == 200
    assert (
        authed_client.get("/api/players").json()["players"][0]["latestProgression"]["id"]
        == e_newest["id"]
    )
    assert authed_client.patch("/api/progression/99999", json={"note": "x"}).status_code == 404
    assert authed_client.delete("/api/progression/99999").status_code == 404


def test_m2_sqlite_persistence_across_create_app_restart(
    test_settings: Settings,
) -> None:
    app1 = create_app(test_settings)
    with TestClient(app1) as c1:
        assert (
            c1.post(
                "/api/auth/setup",
                json={"username": "lider", "password": "PersistPassword1!"},
            ).status_code
            == 201
        )
        _create_field(
            c1,
            label="Savaş Gücü",
            scope="progression",
            field_type="number",
            unit="Güç",
            is_required=True,
        )
        _create_field(
            c1,
            label="Rol",
            scope="profile",
            field_type="select",
            options=["Tank", "DPS"],
        )
        p = _create_player(
            c1,
            display_name="KalıcıOyuncu",
            profile_values={"rol": "Tank"},
            aliases=["KaliciAlt"],
        )
        pid = p["id"]
        assert (
            c1.post(
                f"/api/players/{pid}/progression",
                json={"recorded_at": "2026-11-10", "metrics": {"savas_gucu": 5000}},
            ).status_code
            == 201
        )
        assert (
            c1.post(
                f"/api/players/{pid}/progression",
                json={"recorded_at": "2026-11-20", "metrics": {"savas_gucu": 6200}},
            ).status_code
            == 201
        )

    app2 = create_app(test_settings)
    with TestClient(app2) as c2:
        assert c2.get("/api/players").status_code == 401
        assert (
            c2.post(
                "/api/auth/login",
                json={"username": "lider", "password": "PersistPassword1!"},
            ).status_code
            == 200
        )

        fields = c2.get("/api/fields?activeOnly=false").json()["fields"]
        assert {f["field_key"] for f in fields} == {"savas_gucu", "rol"}

        players = c2.get("/api/players").json()["players"]
        assert len(players) == 1
        assert players[0]["display_name"] == "KalıcıOyuncu"
        assert players[0]["profile_values"] == {"rol": "Tank"}
        assert [a["alias_name"] for a in players[0]["aliases"]] == ["KaliciAlt"]
        assert players[0]["latestProgression"]["metrics"] == {"savas_gucu": 6200}

        detail = c2.get(f"/api/players/{pid}").json()
        assert len(detail["progressionEntries"]) == 2
        assert detail["progressionEntries"][0]["deltas"] == {"savas_gucu": 1200}
        assert detail["progressionEntries"][1]["deltas"] == {}
