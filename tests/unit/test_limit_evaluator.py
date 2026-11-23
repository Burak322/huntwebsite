from __future__ import annotations

from app.services.limit_evaluator import (
    evaluate_daily_scores,
    evaluate_score,
    summarize_compliance,
)


def test_evaluate_score_meets_and_misses() -> None:
    ok = evaluate_score(12_000, 10_000)
    assert ok.meets_limit and ok.delta == 2_000 and ok.completion_pct == 120
    bad = evaluate_score(7_500, 10_000)
    assert not bad.meets_limit and bad.delta == -2_500 and bad.completion_pct == 75


def test_evaluate_score_boundary_equal_counts_as_met() -> None:
    ev = evaluate_score(10_000, 10_000)
    assert ev.meets_limit and ev.delta == 0 and ev.completion_pct == 100


def test_zero_limit_always_met() -> None:
    ev = evaluate_score(0, 0)
    assert ev.meets_limit and ev.completion_pct == 100


def test_negative_limit_is_clamped_to_zero() -> None:
    ev = evaluate_score(5, -10)
    assert ev.active_min_score == 0 and ev.meets_limit


def test_to_dict_keys() -> None:
    assert set(evaluate_score(1, 2).to_dict()) == {
        "activeDailyMinScore", "delta", "meetsLimit", "completionPct",
    }


def test_daily_aggregation_by_player_and_date() -> None:
    scores = [
        {"player_id": 1, "player_name": "Ali", "score": 4000, "score_date": "2026-11-20"},
        {"player_id": 1, "player_name": "Ali", "score": 7000, "score_date": "2026-11-20"},
        {"player_id": 1, "player_name": "Ali", "score": 3000, "score_date": "2026-11-21"},
        {"player_id": 2, "player_name": "Veli", "score": 9000, "score_date": "2026-11-20"},
        {"player_id": None, "extracted_name": "Yabanci", "score": 15000, "score_date": "2026-11-20"},
        {"player_id": None, "extracted_name": "yabanci", "score": 1, "score_date": "2026-11-20"},
    ]
    res = evaluate_daily_scores(scores, 10_000)
    # newest date first
    assert res[0]["scoreDate"] == "2026-11-21"
    day20 = {r["playerName"].lower(): r for r in res if r["scoreDate"] == "2026-11-20"}
    assert day20["ali"]["totalScore"] == 11_000 and day20["ali"]["meetsLimit"]
    assert day20["ali"]["entryCount"] == 2
    assert day20["veli"]["totalScore"] == 9_000 and not day20["veli"]["meetsLimit"]
    assert day20["yabanci"]["totalScore"] == 15_001
    # sorted by total desc within a date
    totals = [r["totalScore"] for r in res if r["scoreDate"] == "2026-11-20"]
    assert totals == sorted(totals, reverse=True)


def test_same_scores_reevaluate_with_new_limit() -> None:
    scores = [{"player_id": 1, "player_name": "Ali", "score": 12_000, "score_date": "2026-11-20"}]
    assert evaluate_daily_scores(scores, 10_000)[0]["meetsLimit"] is True
    assert evaluate_daily_scores(scores, 15_000)[0]["meetsLimit"] is False
    assert evaluate_daily_scores(scores, 12_000)[0]["meetsLimit"] is True


def test_summarize_compliance() -> None:
    assert summarize_compliance([{"meetsLimit": True}, {"meetsLimit": False}, {"meetsLimit": True}]) == {
        "total": 3, "met": 2, "missed": 1,
    }
