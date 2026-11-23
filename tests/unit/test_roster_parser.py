from __future__ import annotations

import ast
from pathlib import Path

from app.services.roster_parser import (
    is_roster_header_or_noise_line,
    reconstruct_roster_candidates,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _box(x1: float, y1: float, x2: float, y2: float, text: str, conf: float = 0.96) -> list:
    return [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]], text, conf]


class TestRosterParserPurity:
    def test_roster_parser_has_no_image_or_ocr_imports(self) -> None:
        source = (PROJECT_ROOT / "app" / "services" / "roster_parser.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_roots.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        forbidden = {"cv2", "PIL", "Pillow", "rapidocr_onnxruntime", "rapidocr", "numpy"}
        assert imported_roots.isdisjoint(forbidden), f"Forbidden imports found: {imported_roots & forbidden}"


class TestRosterNoiseFiltering:
    def test_filters_roster_headers_counts_and_timestamps(self) -> None:
        for line in (
            "KLAN ÜYELERİ 24/50",
            "SIRA | OYUNCU | RÜTBE | DURUM",
            "PLAYER NAME ROLE STATUS",
            "ONLINE",
            "ÇEVRİMİÇİ",
            "2026-10-12",
            "14:30",
            "DAY 3 | PLAYER | SCORE",
            "Tüm üyelerin akşam toplantısında hazır bulunması gerekmektedir.",
        ):
            assert is_roster_header_or_noise_line(line) is True, line

    def test_preserves_actual_roster_rows(self) -> None:
        for line in (
            "1. DemirKurt R4 Çevrimiçi",
            "[APEX] Shadow Wolf Subay Aktif",
            "AylinKilic",
        ):
            assert is_roster_header_or_noise_line(line) is False, line


class TestReconstructRosterCandidates:
    def test_multi_column_scoreless_roster_with_roles_and_tags(self) -> None:
        boxes = [
            _box(40, 20, 260, 44, "KLAN ÜYELERİ"),
            _box(280, 20, 360, 44, "24/50"),
            _box(40, 60, 100, 86, "Sıra"),
            _box(150, 60, 320, 86, "Oyuncu"),
            _box(420, 60, 520, 86, "Rütbe"),
            _box(580, 60, 700, 86, "Durum"),
            # Row 1: split [APEX] + DemirKurt
            _box(45, 110, 80, 136, "1."),
            _box(130, 110, 205, 136, "[APEX]"),
            _box(212, 110, 340, 136, "DemirKurt"),
            _box(430, 110, 470, 136, "R4"),
            _box(585, 110, 690, 136, "Çevrimiçi"),
            # Row 2: normal player with relative timestamp
            _box(45, 160, 80, 186, "2."),
            _box(140, 160, 290, 186, "AylinKilic"),
            _box(430, 160, 480, 186, "Üye"),
            _box(585, 160, 680, 186, "2sa önce"),
            # Row 3: multi-box role + online
            _box(45, 210, 80, 236, "3."),
            _box(140, 210, 260, 236, "Gökhan"),
            _box(430, 210, 500, 236, "Lider"),
            _box(585, 210, 665, 236, "Online"),
        ]
        cands = reconstruct_roster_candidates(boxes)
        assert [c.extracted_name for c in cands] == ["[APEX] DemirKurt", "AylinKilic", "Gökhan"]
        assert [c.clean_name for c in cands] == ["DemirKurt", "AylinKilic", "Gökhan"]
        assert all(c.detected_number is None for c in cands)

    def test_single_column_plain_name_list(self) -> None:
        boxes = [
            _box(60, 20, 260, 46, "ÜYELER"),
            _box(60, 70, 240, 96, "DemirKurt"),
            _box(60, 115, 200, 141, "Çağrı"),
            _box(60, 160, 190, 186, "Işık"),
        ]
        cands = reconstruct_roster_candidates(boxes)
        assert [c.clean_name for c in cands] == ["DemirKurt", "Çağrı", "Işık"]

    def test_leaderboard_rows_extract_names_and_detected_numbers(self) -> None:
        boxes = [
            _box(50, 30, 650, 56, "1. ShadowWolf 14,500"),
            _box(50, 80, 320, 106, "2. [TR] Alparslan"),
            _box(450, 80, 560, 106, "1.2M"),
            _box(50, 130, 650, 156, "3. MehmetBey R4 Çevrimiçi 2sa önce"),
        ]
        cands = reconstruct_roster_candidates(boxes)
        assert len(cands) == 3
        assert cands[0].clean_name == "ShadowWolf"
        assert cands[0].detected_number == 14500
        assert cands[1].extracted_name == "[TR] Alparslan"
        assert cands[1].clean_name == "Alparslan"
        assert cands[1].detected_number == 1_200_000
        assert cands[2].clean_name == "MehmetBey"

    def test_deduplicates_identical_turkish_names_in_same_image(self) -> None:
        boxes = [
            _box(60, 50, 240, 76, "Işık", conf=0.82),
            _box(60, 100, 260, 126, "[APEX] IŞIK", conf=0.95),
        ]
        cands = reconstruct_roster_candidates(boxes)
        assert len(cands) == 1
        assert cands[0].ocr_confidence == 0.95

    def test_extracts_clan_rank_and_tower_level_without_polluting_name(self) -> None:
        boxes = [
            _box(40, 20, 700, 46, "1. | [APEX] DemirKurt | R4 | I8 | Çevrimiçi"),
            _box(40, 80, 75, 106, "2."),
            _box(130, 80, 290, 106, "AylinKilic"),
            _box(350, 80, 410, 106, "r5"),
            _box(460, 80, 520, 106, "i10"),
            _box(580, 80, 680, 106, "Online"),
        ]
        cands = reconstruct_roster_candidates(boxes)
        assert len(cands) == 2
        assert cands[0].extracted_name == "[APEX] DemirKurt"
        assert cands[0].clean_name == "DemirKurt"
        assert cands[0].detected_rank == "R4"
        assert cands[0].detected_tower_level == "I8"

        assert cands[1].clean_name == "AylinKilic"
        assert cands[1].detected_rank == "R5"
        assert cands[1].detected_tower_level == "I10"
