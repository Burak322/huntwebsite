from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from tests.fixtures.leaderboard_generator import resolve_ttf_font


def _render_dark_roster_png(lines: list[tuple[str, str, str]]) -> bytes:
    """Render a realistic dark-theme clan member roster PNG with Pillow."""
    font = resolve_ttf_font(26)
    bold_font = resolve_ttf_font(26, bold=True)
    row_h = 54
    width = 860
    height = 110 + len(lines) * row_h

    img = Image.new("RGB", (width, height), color=(18, 23, 34))
    draw = ImageDraw.Draw(img)

    # Header bar
    draw.rectangle([28, 24, width - 28, 72], fill=(34, 42, 60), outline=(55, 68, 92))
    draw.text((48, 36), "Sıra", fill=(203, 213, 225), font=bold_font)
    draw.text((150, 36), "Oyuncu", fill=(203, 213, 225), font=bold_font)
    draw.text((620, 36), "Rütbe", fill=(203, 213, 225), font=bold_font)

    for idx, (rank_txt, name_txt, role_txt) in enumerate(lines):
        y = 84 + idx * row_h
        bg = (26, 32, 46) if idx % 2 == 0 else (21, 27, 39)
        draw.rectangle([28, y, width - 28, y + row_h - 4], fill=bg)
        draw.text((48, y + 10), rank_txt, fill=(240, 244, 250), font=font)
        draw.text((150, y + 10), name_txt, fill=(240, 244, 250), font=font)
        draw.text((620, y + 10), role_txt, fill=(148, 163, 184), font=font)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_player_photo_import_endpoints_require_auth(client: TestClient) -> None:
    assert client.post("/api/players/import-ocr").status_code == 401
    assert (
        client.post(
            "/api/players/import-bulk",
            json={"players": [{"display_name": "Anon"}]},
        ).status_code
        == 401
    )


def test_import_ocr_extracts_scoreless_roster_and_flags_existing_players(
    authed_client: TestClient,
) -> None:
    c = authed_client
    r = c.post("/api/players", json={"display_name": "ShadowWolf", "status": "active"})
    assert r.status_code == 201
    shadow_id = r.json()["player"]["id"]

    img_bytes = _render_dark_roster_png(
        [
            ("1.", "ShadowWolf", "Lider"),
            ("2.", "[TR] AylinKilic", "Subay"),
            ("3.", "DemirKurt", "Üye"),
        ]
    )

    resp = c.post(
        "/api/players/import-ocr",
        files={"file": ("roster.png", img_bytes, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    cands = body["candidates"]
    assert len(cands) == 3

    by_clean = {item["cleanName"]: item for item in cands}
    assert "ShadowWolf" in by_clean
    assert by_clean["ShadowWolf"]["alreadyExists"] is True
    assert by_clean["ShadowWolf"]["matchedPlayerId"] == shadow_id

    assert "AylinKilic" in by_clean
    assert by_clean["AylinKilic"]["alreadyExists"] is False
    assert by_clean["AylinKilic"]["suggestedAlias"] == "[TR] AylinKilic"

    assert "DemirKurt" in by_clean
    assert by_clean["DemirKurt"]["alreadyExists"] is False


def test_import_ocr_rejects_corrupt_payload(authed_client: TestClient) -> None:
    resp = authed_client.post(
        "/api/players/import-ocr",
        files={"file": ("bad.txt", b"not-an-image-payload", "text/plain")},
    )
    assert resp.status_code == 400


def test_bulk_import_players_skips_existing_and_records_initial_metrics(
    authed_client: TestClient,
) -> None:
    c = authed_client
    assert (
        c.post("/api/players", json={"display_name": "ShadowWolf", "status": "active"}).status_code
        == 201
    )

    assert (
        c.post(
            "/api/fields",
            json={
                "label": "Rol",
                "scope": "profile",
                "field_type": "select",
                "options": ["Tank", "DPS"],
                "is_required": True,
            },
        ).status_code
        == 201
    )
    assert (
        c.post(
            "/api/fields",
            json={
                "label": "Güç",
                "scope": "progression",
                "field_type": "number",
                "unit": "K",
            },
        ).status_code
        == 201
    )

    # Missing required profile field -> 422 before creating any player
    bad = c.post(
        "/api/players/import-bulk",
        json={
            "players": [{"display_name": "YeniUye", "profile_values": {}}],
            "skip_existing": True,
        },
    )
    assert bad.status_code == 422

    # Valid batch with existing player (skipped) + 2 new players + initial progression metric
    ok = c.post(
        "/api/players/import-bulk",
        json={
            "skip_existing": True,
            "recorded_at": "2026-10-20",
            "players": [
                {
                    "display_name": "ShadowWolf",
                    "profile_values": {"rol": "Tank"},
                },
                {
                    "display_name": "AylinKilic",
                    "profile_values": {"rol": "DPS"},
                    "aliases": ["[TR] AylinKilic"],
                    "initial_metrics": {"guc": 1500},
                },
                {
                    "display_name": "DemirKurt",
                    "profile_values": {"rol": "Tank"},
                },
            ],
        },
    )
    assert ok.status_code == 201, ok.text
    res = ok.json()
    assert res["createdCount"] == 2
    assert res["skippedCount"] == 1
    assert res["skipped"][0]["display_name"] == "ShadowWolf"

    listed = c.get("/api/players").json()["players"]
    by_name = {p["display_name"]: p for p in listed}
    assert set(by_name.keys()) == {"ShadowWolf", "AylinKilic", "DemirKurt"}
    assert [a["alias_name"] for a in by_name["AylinKilic"]["aliases"]] == ["[TR] AylinKilic"]
    assert by_name["AylinKilic"]["latestProgression"]["metrics"] == {"guc": 1500}
    assert by_name["AylinKilic"]["latestProgression"]["recorded_at"] == "2026-10-20"
