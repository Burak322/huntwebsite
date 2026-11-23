"""Pure dynamic daily minimum score limit evaluation.

Compliance is always computed at read time against the *currently active*
limit, so changing the limit instantly re-evaluates every stored score.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class LimitEvaluation:
    score: int
    active_min_score: int
    delta: int
    meets_limit: bool
    completion_pct: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "activeDailyMinScore": self.active_min_score,
            "delta": self.delta,
            "meetsLimit": self.meets_limit,
            "completionPct": self.completion_pct,
        }


def evaluate_score(score: int, active_min_score: int) -> LimitEvaluation:
    score = int(score)
    limit = max(0, int(active_min_score))
    pct = 100 if limit == 0 else round((score / limit) * 100)
    return LimitEvaluation(
        score=score,
        active_min_score=limit,
        delta=score - limit,
        meets_limit=score >= limit,
        completion_pct=int(pct),
    )


def _player_key(record: Mapping[str, Any]) -> tuple[str, Any]:
    pid = record.get("player_id")
    if pid is not None:
        return ("id", int(pid))
    return ("name", str(record.get("extracted_name") or "").casefold())


def evaluate_daily_scores(
    scores: Iterable[Mapping[str, Any]],
    active_min_score: int,
) -> list[dict[str, Any]]:
    """Aggregate scores per (player, score_date) and evaluate each total.

    Each record needs ``score``, ``score_date`` and ``player_id`` (nullable)
    plus optional ``player_name`` / ``extracted_name`` for display.
    Output is sorted by date desc, then total desc, then name.
    """
    buckets: dict[tuple[str, tuple[str, Any]], dict[str, Any]] = {}
    for rec in scores:
        date = str(rec["score_date"])
        key = (date, _player_key(rec))
        bucket = buckets.get(key)
        if bucket is None:
            name = rec.get("player_name") or rec.get("extracted_name") or ""
            bucket = {
                "playerId": int(rec["player_id"]) if rec.get("player_id") is not None else None,
                "playerName": str(name),
                "scoreDate": date,
                "totalScore": 0,
                "entryCount": 0,
            }
            buckets[key] = bucket
        bucket["totalScore"] += int(rec["score"])
        bucket["entryCount"] += 1

    results: list[dict[str, Any]] = []
    for bucket in buckets.values():
        ev = evaluate_score(bucket["totalScore"], active_min_score)
        results.append({**bucket, **ev.to_dict()})

    results.sort(key=lambda r: (r["playerName"].casefold(),))
    results.sort(key=lambda r: r["totalScore"], reverse=True)
    results.sort(key=lambda r: r["scoreDate"], reverse=True)
    return results


def summarize_compliance(evaluations: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    total = met = 0
    for ev in evaluations:
        total += 1
        if ev.get("meetsLimit"):
            met += 1
    return {"total": total, "met": met, "missed": total - met}
