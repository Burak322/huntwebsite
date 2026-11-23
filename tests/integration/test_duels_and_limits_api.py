from __future__ import annotations

from fastapi.testclient import TestClient

from tests.fixtures.leaderboard_generator import (
    LeaderboardRow,
    generate_corrupt_image_bytes,
    generate_leaderboard_image,
)

DAY1 = "2026-11-20"
DAY2 = "2026-11-21"


def _mk_player(c: TestClient, name: str, aliases: list[str] | None = None) -> int:
    r = c.post("/api/players", json={"display_name": name, "aliases": aliases or []})
    assert r.status_code == 201, r.text
    return r.json()["player"]["id"]


def _mk_duel(c: TestClient, opp: str = "Rakip Klan") -> int:
    r = c.post("/api/duels", json={"opponent_clan_name": opp, "start_date": DAY1})
    assert r.status_code == 201, r.text
    return r.json()["duel"]["id"]


# ------------------------------------------------------------------ auth

def test_duel_and_limit_endpoints_require_auth(client: TestClient) -> None:
    for method, path in [
        ("get", "/api/duels"),
        ("post", "/api/duels"),
        ("get", "/api/duels/1"),
        ("get", "/api/limits/daily"),
        ("put", "/api/limits/daily"),
        ("get", "/api/limits/evaluate"),
        ("get", "/api/dashboard"),
        ("get", "/api/duels/1/screenshots/1/image"),
        ("delete", "/api/scores/1"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path


# ------------------------------------------------------------------ duels CRUD

def test_duel_crud(authed_client: TestClient) -> None:
    c = authed_client
    duel_id = _mk_duel(c, "Ejderhalar")
    listing = c.get("/api/duels").json()
    assert listing["activeDailyMinScore"] == 0
    assert listing["duels"][0]["opponent_clan_name"] == "Ejderhalar"

    r = c.patch(f"/api/duels/{duel_id}", json={"status": "completed", "end_date": "2026-11-27"})
    assert r.status_code == 200 and r.json()["duel"]["status"] == "completed"

    assert c.patch(f"/api/duels/{duel_id}", json={"end_date": "2026-01-01"}).status_code == 422
    assert c.post("/api/duels", json={"opponent_clan_name": " ", "start_date": DAY1}).status_code == 422
    assert c.post("/api/duels", json={"opponent_clan_name": "X", "start_date": "2026-13-01"}).status_code == 422

    assert c.delete(f"/api/duels/{duel_id}").status_code == 200
    assert c.get(f"/api/duels/{duel_id}").status_code == 404


# ------------------------------------------------------------------ manual scores + limits

def test_manual_scores_upsert_and_dynamic_limit(authed_client: TestClient) -> None:
    c = authed_client
    ali = _mk_player(c, "Ali")
    veli = _mk_player(c, "Veli")
    duel_id = _mk_duel(c)

    assert c.put("/api/limits/daily", json={"minScore": 10_000, "note": "Başlangıç"}).status_code == 200

    r = c.post(f"/api/duels/{duel_id}/scores", json={"player_id": ali, "score": 12_000, "score_date": DAY1})
    assert r.status_code == 201, r.text
    s = r.json()["score"]
    assert s["meetsLimit"] is True and s["delta"] == 2_000 and s["player_name"] == "Ali"

    c.post(f"/api/duels/{duel_id}/scores", json={"player_id": veli, "score": 9_000, "score_date": DAY1})

    # upsert: same player/day updates instead of duplicating
    r2 = c.post(f"/api/duels/{duel_id}/scores", json={"player_id": veli, "score": 11_000, "score_date": DAY1})
    detail = c.get(f"/api/duels/{duel_id}").json()
    assert len(detail["scores"]) == 2
    assert r2.json()["score"]["score"] == 11_000
    assert detail["compliance"] == {"total": 2, "met": 2, "missed": 0}

    # raise limit -> both re-evaluated without touching stored scores
    r = c.put("/api/limits/daily", json={"minScore": 15_000})
    assert r.json()["activeMinScore"] == 15_000
    detail = c.get(f"/api/duels/{duel_id}").json()
    assert detail["activeDailyMinScore"] == 15_000
    assert all(not s["meetsLimit"] for s in detail["scores"])
    assert detail["compliance"]["missed"] == 2

    # lower to 12,000 -> Ali meets, Veli misses
    c.put("/api/limits/daily", json={"minScore": 12_000})
    ev = c.get("/api/limits/evaluate", params={"date": DAY1, "duelId": duel_id}).json()
    by_name = {e["playerName"]: e for e in ev["evaluations"]}
    assert by_name["Ali"]["meetsLimit"] is True and by_name["Ali"]["completionPct"] == 100
    assert by_name["Veli"]["meetsLimit"] is False and by_name["Veli"]["delta"] == -1_000

    hist = c.get("/api/limits/daily").json()["history"]
    assert [h["minScore"] for h in hist] == [12_000, 15_000, 10_000]
    assert hist[-1]["note"] == "Başlangıç"

    # player detail exposes evaluated duel scores
    pd = c.get(f"/api/players/{ali}").json()
    assert pd["recentDuelScores"][0]["meetsLimit"] is True


def test_limit_validation(authed_client: TestClient) -> None:
    c = authed_client
    assert c.put("/api/limits/daily", json={"minScore": -1}).status_code == 422
    assert c.put("/api/limits/daily", json={"minScore": "abc"}).status_code == 422
    assert c.get("/api/limits/daily").json()["activeMinScore"] == 0


def test_limit_persists_across_app_restart(authed_client: TestClient, test_settings) -> None:
    from app.main import create_app

    authed_client.put("/api/limits/daily", json={"minScore": 7_777})
    with TestClient(create_app(test_settings)) as c2:
        c2.post("/api/auth/login", json={"username": "lider", "password": "StrongPassword123!"})
        assert c2.get("/api/limits/daily").json()["activeMinScore"] == 7_777


def test_score_update_delete_and_validation(authed_client: TestClient) -> None:
    c = authed_client
    ali = _mk_player(c, "Ali")
    duel_id = _mk_duel(c)
    sid = c.post(f"/api/duels/{duel_id}/scores", json={"player_id": ali, "score": 100, "score_date": DAY1}).json()["score"]["id"]

    assert c.patch(f"/api/scores/{sid}", json={"score": 250}).json()["score"]["score"] == 250
    assert c.patch(f"/api/scores/{sid}", json={"score": -5}).status_code == 422
    assert c.post(f"/api/duels/{duel_id}/scores", json={"score": 5, "score_date": DAY1}).status_code == 422
    assert c.post(f"/api/duels/{duel_id}/scores", json={"player_id": 999, "score": 5, "score_date": DAY1}).status_code == 422
    assert c.post(f"/api/duels/9999/scores", json={"player_id": ali, "score": 5, "score_date": DAY1}).status_code == 404

    # unmatched (no player) manual score is allowed with a name
    r = c.post(f"/api/duels/{duel_id}/scores", json={"extracted_name": "Misafir", "score": 5, "score_date": DAY1})
    assert r.status_code == 201 and r.json()["score"]["player_id"] is None

    assert c.delete(f"/api/scores/{sid}").status_code == 200
    assert c.delete(f"/api/scores/{sid}").status_code == 404


# ------------------------------------------------------------------ screenshot OCR workflow (real OCR)

def test_screenshot_extract_commit_flow(authed_client: TestClient) -> None:
    c = authed_client
    shadow = _mk_player(c, "ShadowWolf")
    kira = _mk_player(c, "Kira99")
    _mk_player(c, "Alparslan")
    duel_id = _mk_duel(c)
    c.put("/api/limits/daily", json={"minScore": 11_000})

    png = generate_leaderboard_image(
        rows=[
            LeaderboardRow(rank=1, clan_tag="[APEX]", name="ShadowWolf", score="12,450"),
            LeaderboardRow(rank=2, name="Kira99", score="10.800"),
            LeaderboardRow(rank=3, name="YeniUye", score="9,100"),
        ],
        theme="dark",
        fmt="PNG",
        title="Klan Düellosu",
        headers=["Sıra", "Oyuncu", "Puan"],
    )
    r = c.post(
        f"/api/duels/{duel_id}/screenshots/extract",
        files={"file": ("lb.png", png, "image/png")},
        data={"score_date": DAY1},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    rows = body["parsedRows"]
    assert [row["extractedScore"] for row in rows] == [12_450, 10_800, 9_100]
    assert rows[0]["matchedPlayerId"] == shadow
    assert rows[1]["matchedPlayerId"] == kira
    assert rows[2]["matchedPlayerId"] is None

    img = c.get(body["imageUrl"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"

    commit = c.post(
        f"/api/duels/{duel_id}/screenshots/{body['screenshotId']}/commit",
        json={
            "score_date": DAY1,
            "rows": [
                {"extractedName": rows[0]["extractedName"], "score": 12_450, "playerId": shadow},
                {"extractedName": "Kira_99", "score": 10_800, "playerId": kira, "saveAlias": True},
                {"extractedName": "YeniUye", "score": 9_100, "createPlayer": True},
            ],
        },
    )
    assert commit.status_code == 201, commit.text
    cb = commit.json()
    assert len(cb["savedScores"]) == 3
    assert cb["createdPlayers"][0]["display_name"] == "YeniUye"
    met = {e["playerName"]: e["meetsLimit"] for e in cb["evaluatedDailySummaries"]}
    assert met == {"ShadowWolf": True, "Kira99": False, "YeniUye": False}

    # alias saved
    aliases = [a["alias_name"] for a in c.get(f"/api/players/{kira}").json()["aliases"]]
    assert "Kira_99" in aliases

    detail = c.get(f"/api/duels/{duel_id}").json()
    assert detail["screenshots"][0]["status"] == "committed"
    assert len(detail["scores"]) == 3

    # second screenshot same day updates (no duplicates)
    commit2 = c.post(
        f"/api/duels/{duel_id}/screenshots/{body['screenshotId']}/commit",
        json={"score_date": DAY1, "rows": [{"extractedName": "Kira99", "score": 13_000, "playerId": kira}]},
    )
    assert commit2.status_code == 201
    detail = c.get(f"/api/duels/{duel_id}").json()
    assert len(detail["scores"]) == 3
    assert next(s for s in detail["scores"] if s["player_id"] == kira)["score"] == 13_000

    dash = c.get("/api/dashboard").json()
    assert dash["latestScoreDate"] == DAY1
    assert dash["latestDayCompliance"] == {"total": 3, "met": 2, "missed": 1}


def test_commit_validation(authed_client: TestClient) -> None:
    c = authed_client
    p = _mk_player(c, "Ali")
    duel_id = _mk_duel(c)
    png = generate_leaderboard_image(
        rows=[LeaderboardRow(rank=1, name="Ali", score="5,000")], theme="light", fmt="PNG",
        headers=["Sıra", "Oyuncu", "Puan"],
    )
    sid = c.post(
        f"/api/duels/{duel_id}/screenshots/extract",
        files={"file": ("a.png", png, "image/png")},
        data={"score_date": DAY1},
    ).json()["screenshotId"]
    url = f"/api/duels/{duel_id}/screenshots/{sid}/commit"
    dup = [{"extractedName": "Ali", "score": 1, "playerId": p}, {"extractedName": "Ali2", "score": 2, "playerId": p}]
    assert c.post(url, json={"score_date": DAY1, "rows": dup}).status_code == 422
    assert c.post(url, json={"score_date": DAY1, "rows": [{"extractedName": "Ali", "score": -1}]}).status_code == 422
    assert c.post(url, json={"score_date": "bad", "rows": [{"extractedName": "Ali", "score": 1}]}).status_code == 422
    assert c.post(url, json={"score_date": DAY1, "rows": []}).status_code == 422
    assert c.post(f"/api/duels/{duel_id}/screenshots/999/commit",
                  json={"score_date": DAY1, "rows": [{"extractedName": "Ali", "score": 1}]}).status_code == 404
    # nothing was written by failed commits
    assert c.get(f"/api/duels/{duel_id}").json()["scores"] == []


def test_extract_rejects_bad_files(authed_client: TestClient) -> None:
    c = authed_client
    duel_id = _mk_duel(c)
    r = c.post(
        f"/api/duels/{duel_id}/screenshots/extract",
        files={"file": ("x.png", generate_corrupt_image_bytes(), "image/png")},
        data={"score_date": DAY1},
    )
    assert r.status_code in (400, 422)
    r = c.post(
        f"/api/duels/{duel_id}/screenshots/extract",
        files={"file": ("x.txt", b"hello world, not an image", "text/plain")},
        data={"score_date": DAY1},
    )
    assert r.status_code in (400, 422)
    png = generate_leaderboard_image(rows=[LeaderboardRow(rank=1, name="A", score="1")], fmt="PNG")
    assert c.post(
        "/api/duels/9999/screenshots/extract",
        files={"file": ("a.png", png, "image/png")},
        data={"score_date": DAY1},
    ).status_code == 404
    assert c.post(
        f"/api/duels/{duel_id}/screenshots/extract",
        files={"file": ("a.png", png, "image/png")},
        data={"score_date": "2026/11/20"},
    ).status_code == 422
    assert c.get(f"/api/duels/{duel_id}").json()["screenshots"] == []
