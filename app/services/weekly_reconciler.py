"""Pure Python weekly-total to daily-score diff reconciliation engine.

Computes a target day's exact duel score from a cumulative weekly leaderboard
snapshot (W_t), an optional live current-day snapshot (T_t), and previously
recorded duel days (S_prev):

    derivedScore = weeklyTotal - todayLiveScore - previousDaysSum
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Sequence


def _fold_name(name: str | None) -> str:
    return (
        str(name or "")
        .strip()
        .replace("İ", "i")
        .replace("I", "ı")
        .casefold()
    )


def _row_identity(row: Mapping[str, Any]) -> tuple[str, Any]:
    pid = row.get("matchedPlayerId")
    if pid is not None:
        return ("id", int(pid))
    clean = str(row.get("cleanName") or row.get("extractedName") or "").strip()
    return ("name", _fold_name(clean))


def merge_screenshot_rows(
    batches: Sequence[Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Merge OCR rows from multiple scrolled screenshots of the same leaderboard.

    Identical scores for the same player are deduplicated silently; conflicting
    scores for the same player keep the higher value and attach
    ``conflicting_duplicate_in_batch``.
    """
    merged: dict[tuple[str, Any], dict[str, Any]] = {}
    order: list[tuple[str, Any]] = []

    for batch in batches:
        for raw in batch:
            key = _row_identity(raw)
            if not key[1] and key[1] != 0:
                continue
            score = int(raw.get("extractedScore") or 0)
            warnings = list(raw.get("warnings") or [])
            item = {
                "tempId": str(raw.get("tempId") or f"merged-{len(order) + 1}"),
                "extractedName": str(raw.get("extractedName") or ""),
                "cleanName": str(raw.get("cleanName") or raw.get("extractedName") or ""),
                "extractedScore": score,
                "ocrConfidence": float(raw.get("ocrConfidence") or 0.0),
                "matchedPlayerId": (
                    int(raw["matchedPlayerId"])
                    if raw.get("matchedPlayerId") is not None
                    else None
                ),
                "matchedPlayerName": raw.get("matchedPlayerName"),
                "matchStatus": str(raw.get("matchStatus") or "unmatched"),
                "needsReview": bool(raw.get("needsReview", False)),
                "warnings": warnings,
            }

            existing = merged.get(key)
            if existing is None:
                merged[key] = item
                order.append(key)
                continue

            if existing["extractedScore"] != score:
                existing["extractedScore"] = max(existing["extractedScore"], score)
                existing["needsReview"] = True
                if "conflicting_duplicate_in_batch" not in existing["warnings"]:
                    existing["warnings"].append("conflicting_duplicate_in_batch")

            if item["ocrConfidence"] > existing["ocrConfidence"]:
                existing["ocrConfidence"] = item["ocrConfidence"]

            for w in warnings:
                if w not in existing["warnings"]:
                    existing["warnings"].append(w)

    return [merged[k] for k in order]


def find_missing_calendar_dates(
    start_date: str | None,
    target_date: str,
    recorded_dates: Iterable[str],
) -> list[str]:
    """Return ISO dates in [start_date, target_date) missing from recorded_dates."""
    if not start_date:
        return []
    try:
        start_d = date.fromisoformat(str(start_date)[:10])
        target_d = date.fromisoformat(str(target_date)[:10])
    except ValueError:
        return []

    if start_d >= target_d:
        return []

    # Guard against abnormally wide duel spans (> 31 days)
    if (target_d - start_d).days > 31:
        start_d = target_d - timedelta(days=31)

    rec_set = {str(d)[:10] for d in recorded_dates}
    missing: list[str] = []
    cur = start_d
    while cur < target_d:
        iso = cur.isoformat()
        if iso not in rec_set:
            missing.append(iso)
        cur += timedelta(days=1)
    return missing


def reconcile_weekly_diff(
    weekly_rows: Sequence[Mapping[str, Any]],
    today_rows: Sequence[Mapping[str, Any]],
    previous_sums_by_player: Mapping[int, int],
    previous_sums_by_name: Mapping[str, int] | None = None,
    *,
    target_date: str,
    included_previous_dates: Sequence[str],
    duel_start_date: str | None = None,
    recorded_dates: Iterable[str] = (),
) -> dict[str, Any]:
    """Compute target day derived scores from weekly total, today live score, and prior days."""
    prev_by_name = previous_sums_by_name or {}
    weekly_map: dict[tuple[str, Any], Mapping[str, Any]] = {}
    today_map: dict[tuple[str, Any], Mapping[str, Any]] = {}
    ordered_keys: list[tuple[str, Any]] = []

    for w in weekly_rows:
        key = _row_identity(w)
        if key not in weekly_map:
            weekly_map[key] = w
            ordered_keys.append(key)

    for t in today_rows:
        key = _row_identity(t)
        if key not in today_map:
            today_map[key] = t
        if key not in weekly_map and key not in ordered_keys:
            ordered_keys.append(key)

    reconciled_rows: list[dict[str, Any]] = []
    for idx, key in enumerate(ordered_keys, start=1):
        w_row = weekly_map.get(key)
        t_row = today_map.get(key)
        ref = w_row if w_row is not None else t_row
        assert ref is not None

        pid = ref.get("matchedPlayerId")
        matched_pid = int(pid) if pid is not None else None
        extracted_name = str(ref.get("extractedName") or ref.get("cleanName") or "").strip()
        clean_name = str(ref.get("cleanName") or extracted_name).strip()
        matched_name = ref.get("matchedPlayerName")
        match_status = str(ref.get("matchStatus") or ("exact" if matched_pid is not None else "unmatched"))

        weekly_total = int(w_row.get("extractedScore") or 0) if w_row is not None else 0
        today_live = int(t_row.get("extractedScore") or 0) if t_row is not None else 0

        if matched_pid is not None:
            prev_sum = int(previous_sums_by_player.get(matched_pid, 0))
        else:
            prev_sum = int(prev_by_name.get(_fold_name(clean_name), 0))

        derived = weekly_total - today_live - prev_sum

        warnings: list[str] = []
        for src in (w_row, t_row):
            if src is not None:
                for warn in src.get("warnings") or []:
                    if warn not in warnings:
                        warnings.append(str(warn))

        if w_row is None:
            if "missing_from_weekly" not in warnings:
                warnings.append("missing_from_weekly")
        elif t_row is None:
            if "missing_today_score" not in warnings:
                warnings.append("missing_today_score")

        if matched_pid is None and "unmatched_player" not in warnings:
            warnings.append("unmatched_player")

        if derived < 0 and "negative_derived_score" not in warnings:
            warnings.append("negative_derived_score")

        needs_review = bool(
            derived < 0
            or matched_pid is None
            or w_row is None
            or "conflicting_duplicate_in_batch" in warnings
            or "fuzzy_match_needs_review" in warnings
        )

        reconciled_rows.append(
            {
                "tempId": f"diff-{idx}",
                "extractedName": extracted_name,
                "cleanName": clean_name,
                "matchedPlayerId": matched_pid,
                "matchedPlayerName": matched_name,
                "matchStatus": match_status,
                "weeklyTotal": weekly_total,
                "todayLiveScore": today_live,
                "previousDaysSum": prev_sum,
                "derivedScore": derived,
                "needsReview": needs_review,
                "warnings": warnings,
            }
        )

    missing_dates = find_missing_calendar_dates(
        duel_start_date,
        target_date,
        recorded_dates,
    )

    return {
        "targetDate": str(target_date),
        "includedPreviousDates": list(included_previous_dates),
        "missingCalendarDates": missing_dates,
        "rows": reconciled_rows,
    }
