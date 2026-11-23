"""Integration tests for weekly-diff preview (multi-PNG RapidOCR) and commit APIs."""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.leaderboard_generator import LeaderboardRow, generate_leaderboard_image


def test_weekly_diff_preview_and_commit_with_real_ocr(
    authed_client, tmp_path: Path
) -> None:
    # 1. Setup limit=4000, 2 players, 1 duel starting Mon 2026-11-23
    assert authed_client.put("/api/limits/daily", json={"minScore": 4000}).status_code == 200
    p1 = authed_client.post("/api/players", json={"display_name": "ShadowWolf"}).json()["player"]
    p2 = authed_client.post("/api/players", json={"display_name": "AylinKilic"}).json()["player"]
    duel = authed_client.post(
        "/api/duels",
        json={"opponent_clan_name": "Kuzey Klan", "start_date": "2026-11-23"},
    ).json()["duel"]
    duel_id = duel["id"]

    # Seed Mon (23) + Tue (24)
    for pid, mon, tue in ((p1["id"], 2000, 3000), (p2["id"], 1000, 1500)):
        assert authed_client.post(
            f"/api/duels/{duel_id}/scores",
            json={"player_id": pid, "score": mon, "score_date": "2026-11-23"},
        ).status_code == 201
        assert authed_client.post(
            f"/api/duels/{duel_id}/scores",
            json={"player_id": pid, "score": tue, "score_date": "2026-11-24"},
        ).status_code == 201

    # Generate Thu midday Weekly & Today PNGs:
    # ShadowWolf: prev=5000, Weekly=11500, Today=1500 => Wed = 5000 (meets 4000 limit)
    # AylinKilic: prev=2500, Weekly=6000,  Today=500  => Wed = 3000 (below 4000 limit)
    weekly_png = tmp_path / "weekly.png"
    today_png = tmp_path / "today.png"
    generate_leaderboard_image(
        rows=[
            LeaderboardRow(rank=1, name="ShadowWolf", score="11,500"),
            LeaderboardRow(rank=2, name="AylinKilic", score="6,000"),
        ],
        theme="dark",
        headers=["Sıra", "Oyuncu", "Puan"],
        output_path=weekly_png,
    )
    generate_leaderboard_image(
        rows=[
            LeaderboardRow(rank=1, name="ShadowWolf", score="1,500"),
            LeaderboardRow(rank=2, name="AylinKilic", score="500"),
        ],
        theme="dark",
        headers=["Sıra", "Oyuncu", "Puan"],
        output_path=today_png,
    )

    prev_resp = authed_client.post(
        f"/api/duels/{duel_id}/weekly-diff/preview",
        data={"target_date": "2026-11-25", "today_date": "2026-11-26"},
        files=[
            ("weekly_files", ("weekly.png", weekly_png.read_bytes(), "image/png")),
            ("today_files", ("today.png", today_png.read_bytes(), "image/png")),
        ],
    )
    assert prev_resp.status_code == 200, prev_resp.text
    preview = prev_resp.json()
    assert preview["includedPreviousDates"] == ["2026-11-23", "2026-11-24"]
    assert preview["missingCalendarDates"] == []

    by_pid = {r["matchedPlayerId"]: r for r in preview["rows"]}
    assert by_pid[p1["id"]]["previousDaysSum"] == 5000
    assert by_pid[p1["id"]]["weeklyTotal"] == 11500
    assert by_pid[p1["id"]]["todayLiveScore"] == 1500
    assert by_pid[p1["id"]]["derivedScore"] == 5000

    assert by_pid[p2["id"]]["previousDaysSum"] == 2500
    assert by_pid[p2["id"]]["weeklyTotal"] == 6000
    assert by_pid[p2["id"]]["todayLiveScore"] == 500
    assert by_pid[p2["id"]]["derivedScore"] == 3000

    # Negative derivedScore must fail validation on commit
    bad_commit = authed_client.post(
        f"/api/duels/{duel_id}/weekly-diff/commit",
        json={
            "target_date": "2026-11-25",
            "included_previous_dates": ["2026-11-23", "2026-11-24"],
            "rows": [
                {
                    "extractedName": "ShadowWolf",
                    "playerId": p1["id"],
                    "weeklyTotal": 100,
                    "todayLiveScore": 0,
                    "previousDaysSum": 5000,
                    "derivedScore": -100,
                }
            ],
        },
    )
    assert bad_commit.status_code == 422

    # Commit valid reconciled rows + save_today_scores=True
    commit_resp = authed_client.post(
        f"/api/duels/{duel_id}/weekly-diff/commit",
        json={
            "target_date": "2026-11-25",
            "today_date": "2026-11-26",
            "save_today_scores": True,
            "included_previous_dates": ["2026-11-23", "2026-11-24"],
            "rows": [
                {
                    "extractedName": "ShadowWolf",
                    "playerId": p1["id"],
                    "weeklyTotal": 11500,
                    "todayLiveScore": 1500,
                    "previousDaysSum": 5000,
                    "derivedScore": 5000,
                },
                {
                    "extractedName": "AylinKilic",
                    "playerId": p2["id"],
                    "weeklyTotal": 6000,
                    "todayLiveScore": 500,
                    "previousDaysSum": 2500,
                    "derivedScore": 3000,
                },
            ],
        },
    )
    assert commit_resp.status_code == 201, commit_resp.text
    c_data = commit_resp.json()
    assert len(c_data["savedScores"]) == 2
    assert c_data["savedTodayCount"] == 2

    wed_eval = authed_client.get(
        f"/api/limits/evaluate?duelId={duel_id}&date=2026-11-25"
    ).json()
    assert wed_eval["compliance"] == {"total": 2, "met": 1, "missed": 1}

    detail = authed_client.get(f"/api/duels/{duel_id}").json()
    wed_scores = [s for s in detail["scores"] if s["score_date"] == "2026-11-25"]
    assert all(s["calculationMeta"]["method"] == "weekly_diff" for s in wed_scores)
