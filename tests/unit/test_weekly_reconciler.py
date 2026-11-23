"""Unit tests for pure Python weekly_reconciler service."""

from __future__ import annotations

import ast
from pathlib import Path

from app.services.weekly_reconciler import (
    find_missing_calendar_dates,
    merge_screenshot_rows,
    reconcile_weekly_diff,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_weekly_reconciler_is_pure_python_without_ocr_imports() -> None:
    src = (PROJECT_ROOT / "app" / "services" / "weekly_reconciler.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"cv2", "PIL", "rapidocr_onnxruntime", "numpy", "sqlite3"}
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    assert found.isdisjoint(forbidden), f"Forbidden imports: {found & forbidden}"


def test_merge_screenshot_rows_deduplicates_and_flags_conflicts() -> None:
    batch1 = [
        {"matchedPlayerId": 1, "extractedName": "Alpha", "extractedScore": 1000, "ocrConfidence": 0.9, "matchStatus": "exact", "warnings": []},
        {"matchedPlayerId": 2, "extractedName": "Beta", "extractedScore": 2000, "ocrConfidence": 0.85, "matchStatus": "exact", "warnings": []},
    ]
    batch2 = [
        {"matchedPlayerId": 2, "extractedName": "Beta", "extractedScore": 2000, "ocrConfidence": 0.95, "matchStatus": "exact", "warnings": []},
        {"matchedPlayerId": 1, "extractedName": "Alpha", "extractedScore": 1200, "ocrConfidence": 0.8, "matchStatus": "exact", "warnings": []},
        {"matchedPlayerId": 3, "extractedName": "Gamma", "extractedScore": 3000, "ocrConfidence": 0.9, "matchStatus": "exact", "warnings": []},
    ]
    merged = merge_screenshot_rows([batch1, batch2])
    assert [r["matchedPlayerId"] for r in merged] == [1, 2, 3]
    by_id = {r["matchedPlayerId"]: r for r in merged}
    assert by_id[1]["extractedScore"] == 1200
    assert "conflicting_duplicate_in_batch" in by_id[1]["warnings"]
    assert by_id[1]["needsReview"] is True
    assert by_id[2]["extractedScore"] == 2000
    assert "conflicting_duplicate_in_batch" not in by_id[2]["warnings"]
    assert by_id[2]["ocrConfidence"] == 0.95


def test_reconcile_midweek_thursday_derives_wednesday_exact_score() -> None:
    # Mon + Tue stored sums: Alpha=3000 (1000+2000), Beta=2500
    # Thu midday snapshots:
    #   Alpha: Weekly=9500, Today=1500 => Wed = 9500 - 1500 - 3000 = 5000
    #   Beta:  Weekly=4000, Today=missing (0) => Wed = 4000 - 0 - 2500 = 1500 + missing_today_score
    #   Gamma: Weekly=1000, Today=1200 (earned points between SS) => derived=-200 + negative_derived_score
    weekly = [
        {"matchedPlayerId": 1, "extractedName": "Alpha", "extractedScore": 9500, "matchStatus": "exact", "warnings": []},
        {"matchedPlayerId": 2, "extractedName": "Beta", "extractedScore": 4000, "matchStatus": "exact", "warnings": []},
        {"matchedPlayerId": 3, "extractedName": "Gamma", "extractedScore": 1000, "matchStatus": "exact", "warnings": []},
    ]
    today = [
        {"matchedPlayerId": 1, "extractedName": "Alpha", "extractedScore": 1500, "matchStatus": "exact", "warnings": []},
        {"matchedPlayerId": 3, "extractedName": "Gamma", "extractedScore": 1200, "matchStatus": "exact", "warnings": []},
    ]

    result = reconcile_weekly_diff(
        weekly,
        today,
        {1: 3000, 2: 2500},
        target_date="2026-11-25",
        included_previous_dates=["2026-11-23", "2026-11-24"],
        duel_start_date="2026-11-23",
        recorded_dates=["2026-11-23", "2026-11-24"],
    )

    assert result["missingCalendarDates"] == []
    by_id = {r["matchedPlayerId"]: r for r in result["rows"]}
    assert by_id[1]["derivedScore"] == 5000
    assert by_id[1]["needsReview"] is False
    assert by_id[2]["derivedScore"] == 1500
    assert "missing_today_score" in by_id[2]["warnings"]
    assert by_id[3]["derivedScore"] == -200
    assert "negative_derived_score" in by_id[3]["warnings"]
    assert by_id[3]["needsReview"] is True


def test_find_missing_calendar_dates_detects_gap() -> None:
    missing = find_missing_calendar_dates(
        "2026-11-23",
        "2026-11-26",
        ["2026-11-23", "2026-11-25"],
    )
    assert missing == ["2026-11-24"]
