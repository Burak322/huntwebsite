from __future__ import annotations

import pytest

from app.services.score_parser import (
    OcrBox,
    ParsedScore,
    is_header_or_noise_line,
    parse_score_token,
    reconstruct_rows_and_parse,
    strip_rank_prefix,
)


def _box(x1: float, y1: float, x2: float, y2: float, text: str, conf: float = 0.98) -> list:
    return [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]], text, conf]


class TestParseScoreToken:
    @pytest.mark.parametrize(
        ("token", "expected_value", "expected_kind"),
        [
            ("0", 0, "integer"),
            ("9500", 9500, "integer"),
            ("12450", 12450, "integer"),
            ("12,450", 12450, "thousands_sep"),
            ("10.800", 10800, "thousands_sep"),
            ("1,234,567", 1234567, "thousands_sep"),
            ("1.250.000", 1250000, "thousands_sep"),
            ("1 250 000", 1250000, "thousands_sep"),
            ("1.2M", 1_200_000, "suffix"),
            ("1,2M", 1_200_000, "suffix"),
            ("1.25M", 1_250_000, "suffix"),
            ("45K", 45_000, "suffix"),
            ("1.5k", 1_500, "suffix"),
            ("2B", 2_000_000_000, "suffix"),
            ("1,250.5K", 1_250_500, "suffix"),
        ],
    )
    def test_valid_score_formats(self, token: str, expected_value: int, expected_kind: str) -> None:
        parsed = parse_score_token(token)
        assert parsed == ParsedScore(
            value=expected_value,
            raw_text=token,
            digit_repaired=False,
            format_kind=expected_kind,
        )

    @pytest.mark.parametrize(
        "token",
        [
            "",
            "   ",
            "1.",
            "#1",
            "#3",
            "1:",
            "Lv.65",
            "2026-11-22",
            "22.11.2026",
            "22/11",
            "14:35",
            "22:00",
            "85%",
            "-100",
            "3.14",
            "1.5",
            "BOSS",
            "Alparslan",
            "KILLS",
            "Kira99",
        ],
    )
    def test_rejects_non_score_tokens(self, token: str) -> None:
        assert parse_score_token(token) is None

    def test_digit_repair_handles_common_ocr_confusions(self) -> None:
        p1 = parse_score_token("12,45O")
        assert p1 is not None
        assert p1.value == 12450
        assert p1.digit_repaired is True
        assert p1.format_kind == "repaired"

        p2 = parse_score_token("10.8OO")
        assert p2 is not None
        assert p2.value == 10800
        assert p2.digit_repaired is True

        p3 = parse_score_token("45K")
        assert p3 is not None and p3.digit_repaired is False

        # B suffix must NOT be turned into 8
        p4 = parse_score_token("2B")
        assert p4 is not None
        assert p4.value == 2_000_000_000
        assert p4.digit_repaired is False

        # Repairable mantissa with suffix
        p5 = parse_score_token("10OK")
        assert p5 is not None
        assert p5.value == 100_000
        assert p5.digit_repaired is True

        # Disabled repair returns None
        assert parse_score_token("12,45O", allow_digit_repair=False) is None

    def test_digit_repair_respects_max_repaired_and_digit_ratio(self) -> None:
        # Only 1 ASCII digit -> rejected
        assert parse_score_token("1OOO") is None
        # < 50% ASCII digits (2 digits, 3 repaired) -> rejected
        assert parse_score_token("1O.8OO") is None
        # >3 repaired chars -> rejected
        assert parse_score_token("12OOOO") is None


class TestHeaderAndRankHelpers:
    @pytest.mark.parametrize(
        "line",
        [
            "Sıra Oyuncu Puan",
            "RANK PLAYER SCORE",
            "Üye | Düello Puanı",
            "HAFTALIK KLAN DÜELLOSU",
            "DAY 3",
            "GÜN 2/5",
            "2026-11-22",
            "14:30",
            "Tüm üyelerin sesli sohbet kanalında hazır bulunması beklenmektedir.",
        ],
    )
    def test_header_and_noise_lines_filtered(self, line: str) -> None:
        assert is_header_or_noise_line(line) is True

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1. ShadowWolf", "ShadowWolf"),
            ("#2 IronFist", "IronFist"),
            ("3) Kira99", "Kira99"),
            ("4: Turkceli_Uye", "Turkceli_Uye"),
            ("5.UmitBozkurt", "UmitBozkurt"),
            ("10.800", "10.800"),
            ("[APEX] ShadowWolf", "[APEX] ShadowWolf"),
        ],
    )
    def test_strip_rank_prefix(self, raw: str, expected: str) -> None:
        assert strip_rank_prefix(raw) == expected


class TestReconstructRowsAndParse:
    def test_y_clustering_handles_11px_jitter_and_sorts_left_to_right(self) -> None:
        # At ~27px box height, 11px jitter within same row (> RapidOCR's 10px default) must cluster together
        boxes = [
            _box(50, 100, 180, 127, "Sıra"),
            _box(200, 100, 400, 127, "Oyuncu"),
            _box(600, 100, 740, 127, "Puan"),
            # Row 1: intentionally out-of-order horizontally and vertically jittered by 11px
            _box(200, 150, 420, 177, "[APEX] Çağrı"),
            _box(610, 155, 735, 182, "12,450"),
            _box(55, 161, 85, 188, "1."),
            # Row 2: distinct row below
            _box(55, 210, 85, 237, "2."),
            _box(200, 210, 380, 237, "Gökhan"),
            _box(610, 210, 735, 237, "10.800"),
        ]
        rows = reconstruct_rows_and_parse(boxes)
        assert len(rows) == 2
        assert rows[0].extracted_name == "[APEX] Çağrı"
        assert rows[0].extracted_score == 12450
        assert rows[0].raw_line == "1. [APEX] Çağrı 12,450"
        assert rows[1].extracted_name == "Gökhan"
        assert rows[1].extracted_score == 10800

    def test_header_anchored_score_column_beats_rightmost_kills_column(self) -> None:
        # Table has PLAYER | SCORE | KILLS — anchor must pick SCORE (12,450), not KILLS (14)!
        boxes = [
            _box(120, 40, 260, 66, "PLAYER"),
            _box(420, 40, 540, 66, "SCORE"),
            _box(640, 40, 740, 66, "KILLS"),
            _box(40, 90, 75, 116, "1."),
            _box(120, 90, 310, 116, "[APEX] Shadow"),
            _box(425, 90, 535, 116, "12,450"),
            _box(665, 90, 705, 116, "14"),
        ]
        rows = reconstruct_rows_and_parse(boxes)
        assert len(rows) == 1
        assert rows[0].extracted_name == "[APEX] Shadow"
        assert rows[0].extracted_score == 12450

    def test_excludes_intermediate_numeric_columns_from_name(self) -> None:
        boxes = [
            OcrBox(((40, 90), (75, 90), (75, 116), (40, 116)), "1.", 0.99),
            OcrBox(((120, 90), (300, 90), (300, 116), (120, 116)), "[APEX] Çağrı", 0.97),
            OcrBox(((420, 90), (490, 90), (490, 116), (420, 116)), "Lv.68", 0.98),
            OcrBox(((520, 90), (560, 90), (560, 116), (520, 116)), "14", 0.98),
            OcrBox(((620, 90), (730, 90), (730, 116), (620, 116)), "12,450", 0.99),
        ]
        rows = reconstruct_rows_and_parse(boxes)
        assert len(rows) == 1
        assert rows[0].extracted_name == "[APEX] Çağrı"
        assert rows[0].extracted_score == 12450

    def test_pipe_delimited_and_single_box_rows(self) -> None:
        boxes = [
            _box(40, 40, 700, 66, "SIRA | OYUNCU | PUAN | ÖLDÜRME"),
            _box(40, 90, 700, 116, "1. | [APEX] ShadowWolf | 12,450 | 14"),
            _box(40, 140, 700, 166, "2. Turkceli_Uye 1 250 000"),
            _box(40, 190, 700, 216, "5.UmitBozkurt 12,45O"),
        ]
        rows = reconstruct_rows_and_parse(boxes)
        assert len(rows) == 3
        assert rows[0].extracted_name == "[APEX] ShadowWolf"
        assert rows[0].extracted_score == 12450
        assert rows[1].extracted_name == "Turkceli_Uye"
        assert rows[1].extracted_score == 1_250_000
        assert rows[2].extracted_name == "UmitBozkurt"
        assert rows[2].extracted_score == 12450
        assert "digit_repaired" in rows[2].warnings

    def test_mixed_banner_and_number_headers_are_ignored(self) -> None:
        assert is_header_or_noise_line("DAY 3 | PLAYER | SCORE") is True
        assert is_header_or_noise_line("KLAN DUELLOSU GUN 3") is True
        assert is_header_or_noise_line("Day 15000") is False
        assert is_header_or_noise_line("ShadowWolf 3") is False

        boxes = [
            _box(40, 20, 260, 44, "KLAN DUELLOSU"),
            _box(280, 20, 350, 44, "GUN"),
            _box(360, 20, 390, 44, "3"),
            _box(40, 60, 700, 86, "DAY 3 | PLAYER | SCORE"),
            _box(40, 110, 700, 136, "1 | ShadowWolf | 15,000"),
        ]
        rows = reconstruct_rows_and_parse(boxes)
        assert len(rows) == 1
        assert rows[0].extracted_name == "ShadowWolf"
        assert rows[0].extracted_score == 15000

    def test_header_anchored_repaired_score_beats_exact_adjacent_column(self) -> None:
        boxes = [
            _box(120, 40, 260, 66, "PLAYER"),
            _box(420, 40, 540, 66, "SCORE"),
            _box(640, 40, 740, 66, "KILLS"),
            _box(120, 90, 310, 116, "ShadowWolf"),
            _box(425, 90, 535, 116, "12,45O"),
            _box(665, 90, 705, 116, "14"),
        ]
        rows = reconstruct_rows_and_parse(boxes)
        assert len(rows) == 1
        assert rows[0].extracted_name == "ShadowWolf"
        assert rows[0].extracted_score == 12450
        assert "digit_repaired" in rows[0].warnings

        pipe_boxes = [
            _box(40, 40, 700, 66, "PLAYER | SCORE | KILLS"),
            _box(40, 90, 700, 116, "ShadowWolf | 12,45O | 14"),
        ]
        pipe_rows = reconstruct_rows_and_parse(pipe_boxes)
        assert len(pipe_rows) == 1
        assert pipe_rows[0].extracted_name == "ShadowWolf"
        assert pipe_rows[0].extracted_score == 12450
        assert "digit_repaired" in pipe_rows[0].warnings

    def test_single_spaced_row_strips_multiple_trailing_intermediate_tokens(self) -> None:
        boxes = [
            _box(40, 90, 700, 116, "1. ShadowWolf Lv.68 14 12,450"),
        ]
        rows = reconstruct_rows_and_parse(boxes)
        assert len(rows) == 1
        assert rows[0].extracted_name == "ShadowWolf"
        assert rows[0].extracted_score == 12450
