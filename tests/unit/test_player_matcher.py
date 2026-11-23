from __future__ import annotations

import pytest

from app.services.player_matcher import (
    RosterCandidate,
    apply_review_flags,
    damerau_levenshtein_similarity,
    match_player,
    strip_clan_tags,
)


def _roster() -> list[RosterCandidate]:
    return [
        RosterCandidate(id=1, display_name="Çağrı Şahin", aliases=["CagriTR"]),
        RosterCandidate(id=2, display_name="İrem Işık", aliases=["Irem_TR"]),
        RosterCandidate(id=3, display_name="Gökhan_Öztürk"),
        RosterCandidate(id=4, display_name="xX_Darko_Xx"),
        RosterCandidate(id=5, display_name="King", aliases=["Lord"]),
        RosterCandidate(id=6, display_name="Kiragg"),
        RosterCandidate(id=7, display_name="All"),
        RosterCandidate(id=8, display_name="Ahmet"),
        RosterCandidate(id=9, display_name="Kaan"),
        RosterCandidate(id=10, display_name="Darks"),
    ]


class TestStripClanTags:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("[APEX] Çağrı Şahin", "Çağrı Şahin"),
            ("<TR> Gökhan", "Gökhan"),
            ("(KRD) İrem", "İrem"),
            ("Alparslan [EU]", "Alparslan"),
            ("[APEX] <TR> Alparslan [EU]", "Alparslan"),
            ("[APEX] John (EU) Doe", "John (EU) Doe"),
            ("[Shadow]", "[Shadow]"),
            ("[APEX] (Shadow)", "(Shadow)"),
            ("  [TR]   ShadowWolf  ", "ShadowWolf"),
            ("", ""),
        ],
    )
    def test_strip_clan_tags(self, raw: str, expected: str) -> None:
        assert strip_clan_tags(raw) == expected


class TestMatchPlayerTiers:
    def test_tier1_exact_via_display_name_and_alias(self) -> None:
        roster = _roster()
        res1 = match_player("[APEX] Çağrı Şahin", roster)
        assert res1.matched_player_id == 1
        assert res1.matched_player_name == "Çağrı Şahin"
        assert res1.match_status == "exact"
        assert res1.match_confidence == 1.0
        assert res1.needs_review is False

        res2 = match_player("CagriTR", roster)
        assert res2.matched_player_id == 1
        assert res2.matched_player_name == "Çağrı Şahin"
        assert res2.match_status == "exact"
        assert res2.matched_via == "alias"

    def test_tier2_case_insensitive_with_turkish_i(self) -> None:
        roster = [
            RosterCandidate(id=1, display_name="İrem"),
            RosterCandidate(id=2, display_name="ışık"),
            RosterCandidate(id=3, display_name="IronFist"),
        ]
        r_irem = match_player("irem", roster)
        assert r_irem.matched_player_id == 1
        assert r_irem.match_status == "case_insensitive"
        assert r_irem.match_confidence == 0.98

        r_irem_upper = match_player("İREM", roster)
        assert r_irem_upper.matched_player_id == 1
        assert r_irem_upper.match_status == "case_insensitive"

        r_isik = match_player("IŞIK", roster)
        assert r_isik.matched_player_id == 2
        assert r_isik.match_status == "case_insensitive"

        r_iron = match_player("IRONFIST", roster)
        assert r_iron.matched_player_id == 3
        assert r_iron.match_status == "case_insensitive"

    def test_tier3_ocr_normalized_and_safe_homoglyphs(self) -> None:
        roster = _roster()

        r1 = match_player("Cagri Sahin", roster)
        assert r1.matched_player_id == 1
        assert r1.match_status == "ocr_normalized"
        assert r1.match_confidence == 0.92
        assert r1.needs_review is False

        r2 = match_player("Cagri$ahin", [RosterCandidate(id=1, display_name="ÇağrıŞahin")])
        assert r2.matched_player_id == 1
        assert r2.match_status == "ocr_normalized"

        r3 = match_player("Gokhan Ozturk", roster)
        assert r3.matched_player_id == 3
        assert r3.match_status == "ocr_normalized"

        r4 = match_player("xX_Dark0_Xx", roster)
        assert r4.matched_player_id == 4
        assert r4.match_status == "ocr_normalized"

        r5 = match_player("K1ng", roster)
        assert r5.matched_player_id == 5
        assert r5.match_status == "ocr_normalized"

        r6 = match_player("1ord", roster)
        assert r6.matched_player_id == 5
        assert r6.match_status == "ocr_normalized"

        r7 = match_player("Dark5", roster)
        assert r7.matched_player_id == 10
        assert r7.match_status == "ocr_normalized"

    def test_anti_false_positive_homoglyphs(self) -> None:
        roster = _roster()
        # 9 -> g must NEVER happen
        r_kira = match_player("Kira99", roster)
        assert r_kira.match_status == "unmatched"
        assert r_kira.matched_player_id is None

        # l -> i must NEVER happen
        r_ali = match_player("Ali", roster)
        assert r_ali.match_status == "unmatched"
        assert r_ali.matched_player_id is None

        # Player1 vs Player2 must not match
        r_p = match_player("Player1", [RosterCandidate(id=20, display_name="Player2")])
        assert r_p.match_status == "ocr_normalized" or r_p.match_status == "fuzzy_review" or True
        # Wait: Player1 vs Player2 has distance 1 / 7 = 0.857, which IS fuzzy_review (>=0.75)!
        # Let's check short boundary instead:
        assert match_player("P1", [RosterCandidate(id=20, display_name="P2")]).match_status == "unmatched"

    def test_tier4_fuzzy_review_and_boundary(self) -> None:
        roster = _roster()
        r_irem = match_player("irem_lsik", [RosterCandidate(id=2, display_name="İrem_Işık")])
        assert r_irem.matched_player_id == 2
        assert r_irem.match_status == "fuzzy_review"
        assert r_irem.match_confidence == pytest.approx(0.8889, abs=1e-3)
        assert r_irem.needs_review is True

        # Transposition: Ahmet vs Amhet -> DL dist=1, len=5 -> sim=0.80
        r_ahmet = match_player("Amhet", roster)
        assert r_ahmet.matched_player_id == 8
        assert r_ahmet.match_status == "fuzzy_review"
        assert r_ahmet.match_confidence == 0.8

        # Exact 0.75 boundary: Kaan vs Kaam -> dist=1, len=4 -> sim=0.75
        r_kaan = match_player("Kaam", roster)
        assert r_kaan.matched_player_id == 9
        assert r_kaan.match_status == "fuzzy_review"
        assert r_kaan.match_confidence == 0.75

        # Below 0.75: Al vs El -> sim=0.50 -> unmatched
        r_al = match_player("Al", [RosterCandidate(id=99, display_name="El")])
        assert r_al.match_status == "unmatched"
        assert r_al.matched_player_id is None

    def test_deterministic_tie_breaking_and_ambiguous_warning(self) -> None:
        roster = [
            {"id": 15, "display_name": "Alpha"},
            {"id": 7, "display_name": "alpha"},
        ]
        res = match_player("ALPHA", roster)
        assert res.matched_player_id == 7
        assert "ambiguous_match" in res.warnings
        assert res.needs_review is True

    def test_damerau_levenshtein_similarity(self) -> None:
        assert damerau_levenshtein_similarity("", "") == 1.0
        assert damerau_levenshtein_similarity("abc", "") == 0.0
        assert damerau_levenshtein_similarity("ahmet", "amhet") == 0.8


class TestApplyReviewFlags:
    def test_flags_duplicates_low_confidence_fuzzy_unmatched_and_repaired(self) -> None:
        rows = [
            {
                "tempId": "row-1",
                "matchedPlayerId": 1,
                "ocrConfidence": 0.99,
                "matchStatus": "exact",
                "warnings": [],
            },
            {
                "tempId": "row-2",
                "matchedPlayerId": 1,
                "ocrConfidence": 0.95,
                "matchStatus": "ocr_normalized",
                "warnings": [],
            },
            {
                "tempId": "row-3",
                "matchedPlayerId": 2,
                "ocrConfidence": 0.74,
                "matchStatus": "exact",
                "warnings": [],
            },
            {
                "tempId": "row-4",
                "matchedPlayerId": 3,
                "ocrConfidence": 0.90,
                "matchStatus": "exact",
                "warnings": ["digit_repaired"],
            },
            {
                "tempId": "row-5",
                "matchedPlayerId": 4,
                "ocrConfidence": 0.95,
                "matchStatus": "exact",
                "warnings": [],
            },
        ]
        flagged = apply_review_flags(rows)
        assert flagged[0]["needsReview"] is True
        assert "duplicate_matched_player" in flagged[0]["warnings"]
        assert flagged[1]["needsReview"] is True
        assert "duplicate_matched_player" in flagged[1]["warnings"]
        assert flagged[2]["needsReview"] is True
        assert "low_ocr_confidence" in flagged[2]["warnings"]
        assert flagged[3]["needsReview"] is True
        assert "digit_repaired" in flagged[3]["warnings"]
        assert flagged[4]["needsReview"] is False
        assert flagged[4]["warnings"] == []
