from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app.services.ocr_service import (
    OcrExtractionResult,
    OcrImageTooLargeError,
    OcrInvalidImageError,
    extract_leaderboard_from_image,
)
from app.services.player_matcher import RosterCandidate
from tests.fixtures.leaderboard_generator import (
    LeaderboardRow,
    generate_blank_image,
    generate_corrupt_image_bytes,
    generate_leaderboard_image,
    generate_non_leaderboard_image,
    resolve_ttf_font,
)


def _sample_roster() -> list[RosterCandidate]:
    return [
        RosterCandidate(id=1, display_name="ShadowWolf", aliases=["ShadowTR"]),
        RosterCandidate(id=2, display_name="Iron_Fist"),
        RosterCandidate(id=3, display_name="Kira99"),
        RosterCandidate(id=4, display_name="Alparslan"),
        RosterCandidate(id=10, display_name="Çağrı Şahin", aliases=["CagriTR"]),
        RosterCandidate(id=11, display_name="Gökhan Öztürk"),
        RosterCandidate(id=12, display_name="İrem Işık"),
        RosterCandidate(id=13, display_name="Ümit Bozkurt"),
        RosterCandidate(id=14, display_name="Türkçeli Üye"),
    ]


class TestOcrPipelineRealImages:
    def test_dark_multicolumn_png_ocr_pipeline(self) -> None:
        img_bytes = generate_leaderboard_image(
            rows=[
                LeaderboardRow(rank=1, clan_tag="[APEX]", name="ShadowWolf", extra_cols=("14",), score="12,450"),
                LeaderboardRow(rank=2, name="Kira99", extra_cols=("11",), score="10.800"),
                LeaderboardRow(rank=3, clan_tag="[APEX]", name="Iron_Fist", extra_cols=("9",), score="1.2M"),
                LeaderboardRow(rank=4, name="Alparslan", extra_cols=("6",), score="45K"),
            ],
            theme="dark",
            fmt="PNG",
            title="Haftalık Klan Düellosu",
            headers=["Sıra", "Oyuncu", "Öldürme", "Puan"],
        )
        result = extract_leaderboard_from_image(img_bytes, _sample_roster())
        assert isinstance(result, OcrExtractionResult)
        assert result.raw_text.strip() != ""
        assert len(result.parsed_rows) == 4

        scores = [row.extractedScore for row in result.parsed_rows]
        assert scores == [12450, 10800, 1_200_000, 45_000]

        matched_ids = [row.matchedPlayerId for row in result.parsed_rows]
        assert matched_ids == [1, 3, 2, 4]

        api_dict = result.to_api_dict()
        assert "rawText" in api_dict and "parsedRows" in api_dict
        assert len(api_dict["parsedRows"]) == 4

    def test_light_compact_jpg_ocr_pipeline(self) -> None:
        img_bytes = generate_leaderboard_image(
            rows=[
                LeaderboardRow(rank=1, name="ShadowWolf", score="15000"),
                LeaderboardRow(rank=2, name="Alparslan", score="4200"),
                LeaderboardRow(rank=3, name="Türkçeli Üye", score="1 250 000"),
            ],
            theme="light",
            fmt="JPG",
            headers=["Sıra", "Oyuncu", "Puan"],
            width=680,
            font_size=24,
        )
        result = extract_leaderboard_from_image(img_bytes, _sample_roster())
        assert len(result.parsed_rows) == 3
        assert [row.extractedScore for row in result.parsed_rows] == [15000, 4200, 1_250_000]
        assert [row.matchedPlayerId for row in result.parsed_rows] == [1, 4, 14]

    def test_small_colored_text_png_ocr_pipeline(self) -> None:
        img_bytes = generate_leaderboard_image(
            rows=[
                LeaderboardRow(rank=1, name="ShadowWolf", score="25,600"),
                LeaderboardRow(rank=2, name="Kira99", score="18,300"),
                LeaderboardRow(rank=3, name="Alparslan", score="9,450"),
            ],
            theme="colored_small",
            fmt="PNG",
            headers=["Rank", "Player", "Score"],
            width=660,
            font_size=17,
        )
        result = extract_leaderboard_from_image(img_bytes, _sample_roster())
        assert len(result.parsed_rows) == 3
        assert [row.extractedScore for row in result.parsed_rows] == [25600, 18300, 9450]
        assert [row.matchedPlayerId for row in result.parsed_rows] == [1, 3, 4]

    def test_webp_format_supported(self) -> None:
        img_bytes = generate_leaderboard_image(
            rows=[
                LeaderboardRow(rank=1, name="ShadowWolf", score="12,450"),
                LeaderboardRow(rank=2, name="Alparslan", score="8,250"),
            ],
            theme="dark",
            fmt="WEBP",
            headers=["Rank", "Player", "Score"],
        )
        result = extract_leaderboard_from_image(img_bytes, _sample_roster())
        assert len(result.parsed_rows) == 2
        assert [row.extractedScore for row in result.parsed_rows] == [12450, 8250]

    def test_turkish_names_and_duplicate_player_detection(self) -> None:
        img_bytes = generate_leaderboard_image(
            rows=[
                LeaderboardRow(rank=1, clan_tag="[TR]", name="Çağrı Şahin", score="14,500"),
                LeaderboardRow(rank=2, name="Gökhan Öztürk", score="11,200"),
                LeaderboardRow(rank=3, name="İrem Işık", score="9,800"),
                LeaderboardRow(rank=4, name="CagriTR", score="7,100"),
            ],
            theme="dark",
            fmt="PNG",
            headers=["Sıra", "Oyuncu", "Puan"],
        )
        result = extract_leaderboard_from_image(img_bytes, _sample_roster())
        assert len(result.parsed_rows) == 4
        assert [row.extractedScore for row in result.parsed_rows] == [14500, 11200, 9800, 7100]

        # Row 1 (Çağrı Şahin) and Row 4 (alias CagriTR) both resolve to player id 10
        assert result.parsed_rows[0].matchedPlayerId == 10
        assert result.parsed_rows[3].matchedPlayerId == 10
        assert result.parsed_rows[0].needsReview is True
        assert result.parsed_rows[3].needsReview is True
        assert "duplicate_matched_player" in result.parsed_rows[0].warnings
        assert "duplicate_matched_player" in result.parsed_rows[3].warnings

        # Gökhan Öztürk & İrem Işık resolve to 11 & 12
        assert result.parsed_rows[1].matchedPlayerId == 11
        assert result.parsed_rows[2].matchedPlayerId == 12

    def test_negative_blank_and_prose_images_return_empty_rows(self) -> None:
        blank_bytes = generate_blank_image()
        blank_res = extract_leaderboard_from_image(blank_bytes, _sample_roster())
        assert blank_res.parsed_rows == []

        prose_bytes = generate_non_leaderboard_image()
        prose_res = extract_leaderboard_from_image(prose_bytes, _sample_roster())
        assert prose_res.parsed_rows == []

    def test_corrupt_unsupported_and_oversized_inputs_raise_structured_errors(self) -> None:
        with pytest.raises(OcrInvalidImageError) as exc_empty:
            extract_leaderboard_from_image(b"", _sample_roster())
        assert exc_empty.value.code == "EMPTY_IMAGE"

        with pytest.raises(OcrInvalidImageError) as exc_fmt:
            extract_leaderboard_from_image(b"GIF89a\x01\x00\x01\x00\x80\x00\x00", _sample_roster())
        assert exc_fmt.value.code == "UNSUPPORTED_FORMAT"

        with pytest.raises(OcrInvalidImageError) as exc_corrupt:
            extract_leaderboard_from_image(generate_corrupt_image_bytes(), _sample_roster())
        assert exc_corrupt.value.code == "CORRUPT_IMAGE"

        with pytest.raises(OcrImageTooLargeError) as exc_large:
            extract_leaderboard_from_image(generate_blank_image(), _sample_roster(), max_bytes=128)
        assert exc_large.value.code == "IMAGE_TOO_LARGE"
        assert exc_large.value.status_code == 413

        tiny_buf = BytesIO()
        Image.new("RGB", (8, 8), (0, 0, 0)).save(tiny_buf, format="PNG")
        with pytest.raises(OcrInvalidImageError) as exc_small:
            extract_leaderboard_from_image(tiny_buf.getvalue(), _sample_roster())
        assert exc_small.value.code == "IMAGE_TOO_SMALL"

    def test_rgba_transparent_png_luminance_compositing(self) -> None:
        # Bright text on transparent background -> must composite onto dark background, not invert/vanish
        img = Image.new("RGBA", (620, 140), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = resolve_ttf_font(26, require_turkish=True)
        draw.text((30, 50), "1. ShadowWolf", fill=(245, 248, 255, 255), font=font)
        draw.text((460, 50), "12,450", fill=(250, 204, 21, 255), font=font)
        buf = BytesIO()
        img.save(buf, format="PNG")

        result = extract_leaderboard_from_image(buf.getvalue(), _sample_roster())
        assert len(result.parsed_rows) == 1
        assert result.parsed_rows[0].extractedScore == 12450
        assert result.parsed_rows[0].matchedPlayerId == 1
