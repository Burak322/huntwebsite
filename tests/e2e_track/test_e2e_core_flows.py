"""Core opaque-box Playwright E2E tests covering M1-M5 user flows and server restart."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e_track.conftest import ServerHandle
from tests.e2e_track.helpers.screenshot_factory import (
    LeaderboardRowSpec,
    generate_leaderboard_image,
)
from tests.e2e_track.helpers.ui_helpers import (
    click_nav_link,
    navigate_and_wait,
    setup_admin_via_ui,
    setup_and_login_via_api,
)


@pytest.mark.tier1
@pytest.mark.tier3
def test_setup_fields_players_progression_and_reload(
    page: Page, live_server: ServerHandle
) -> None:
    """Setup admin, define profile & progression fields, add player + progression, reload."""
    setup_admin_via_ui(page)
    expect(page.locator('[data-testid="dashboard-active-limit"]')).to_be_visible()

    # 1. Define a select profile field ("Rol") and numeric progression field ("Güç")
    click_nav_link(page, r"Ayarlar")
    expect(page.locator('[data-testid="settings-fields-section"]')).to_be_visible()

    create_field_form = page.locator('[data-testid="create-field-form"]')
    create_field_form.locator("#field-label").fill("Rol")
    create_field_form.locator("#field-scope").select_option("profile")
    create_field_form.locator("#field-type").select_option("select")
    create_field_form.locator("#field-options").fill("Tank, DPS, Destek")
    create_field_form.locator('[data-testid="create-field-submit"]').click()
    expect(page.locator('[data-testid="fields-table"]')).to_contain_text("Rol")

    create_field_form.locator("#field-label").fill("Güç")
    create_field_form.locator("#field-scope").select_option("progression")
    create_field_form.locator("#field-type").select_option("number")
    create_field_form.locator("#field-unit").fill("K")
    create_field_form.locator('[data-testid="create-field-submit"]').click()
    expect(page.locator('[data-testid="fields-table"]')).to_contain_text("Güç")

    # 2. Add player "DemirKurt" with custom profile field "Rol" = "Tank"
    click_nav_link(page, r"Oyuncular")
    expect(page.locator('[data-testid="toggle-add-player-btn"]')).to_be_visible()
    page.locator('[data-testid="toggle-add-player-btn"]').click()

    add_player_form = page.locator('[data-testid="add-player-form"]')
    add_player_form.locator("#add-player-name").fill("DemirKurt")
    add_player_form.locator('select[data-field-key="rol"]').select_option("Tank")
    add_player_form.locator('[data-testid="create-player-submit"]').click()

    players_table = page.locator('[data-testid="players-table"]')
    expect(players_table).to_contain_text("DemirKurt")
    expect(players_table).to_contain_text("Tank")

    # 3. Open player detail and add two progression snapshots
    players_table.get_by_role("link", name="DemirKurt").click()
    expect(page.locator('[data-testid="player-detail-name"]')).to_have_text("DemirKurt")

    prog_form = page.locator('[data-testid="add-progression-form"]')
    prog_form.locator("#prog-date").fill("2026-10-01")
    prog_form.locator('input[data-field-key="guc"]').fill("1200")
    prog_form.locator('[data-testid="add-prog-submit"]').click()

    history_table = page.locator('[data-testid="progression-history-table"]')
    expect(history_table).to_contain_text("01.10.2026")
    expect(history_table).to_contain_text("1.200 K")

    prog_form = page.locator('[data-testid="add-progression-form"]')
    prog_form.locator("#prog-date").fill("2026-10-08")
    prog_form.locator('input[data-field-key="guc"]').fill("1450")
    prog_form.locator('[data-testid="add-prog-submit"]').click()

    history_table = page.locator('[data-testid="progression-history-table"]')
    expect(history_table).to_contain_text("08.10.2026")
    expect(history_table).to_contain_text("1.450 K")
    expect(history_table).to_contain_text("+250")
    expect(page.locator('[data-testid="progression-trend-chart"] svg')).to_be_visible()

    # 4. Reload browser page and verify data persists from SQLite
    page.reload(wait_until="load")
    expect(page.locator('[data-testid="player-detail-name"]')).to_have_text("DemirKurt")
    expect(page.locator('[data-testid="player-edit-form"] select[data-field-key="rol"]')).to_have_value(
        "Tank"
    )
    history_after = page.locator('[data-testid="progression-history-table"]')
    expect(history_after).to_contain_text("08.10.2026")
    expect(history_after).to_contain_text("+250")
    expect(page.locator('[data-testid="progression-trend-chart"] svg')).to_be_visible()


@pytest.mark.tier1
@pytest.mark.tier4
def test_duel_dark_screenshot_ocr_review_and_commit(
    authed_page: Page, live_server: ServerHandle, tmp_path: Path
) -> None:
    """Create duel, upload dark-theme PNG leaderboard, edit OCR rows in UI, commit & verify."""
    for name in ("ShadowWolf", "AylinKilic"):
        resp = authed_page.request.post(
            f"{live_server.base_url}/api/players",
            data={"display_name": name, "status": "active"},
        )
        assert resp.status == 201, resp.text()

    click_nav_link(authed_page, r"Klan Düelloları")
    authed_page.locator('[data-testid="toggle-create-duel-btn"]').click()

    duel_form = authed_page.locator('[data-testid="create-duel-form"]')
    duel_form.locator("#duel-opponent").fill("Karanlık Lejyon")
    duel_form.locator("#duel-title").fill("Hafta 1 Savaşı")
    duel_form.locator("#duel-start").fill("2026-10-12")
    duel_form.locator('[data-testid="create-duel-submit"]').click()

    duels_table = authed_page.locator('[data-testid="duels-table"]')
    expect(duels_table).to_contain_text("Karanlık Lejyon")
    duels_table.get_by_role("link", name="Karanlık Lejyon").click()

    expect(authed_page).to_have_url(re.compile(r"/duels/\d+$"))

    # Generate a real dark-theme leaderboard PNG with Pillow
    img_path = tmp_path / "dark_duel_leaderboard.png"
    generate_leaderboard_image(
        img_path,
        rows=[
            LeaderboardRowSpec(rank=1, name="ShadowWolf", score="14,500"),
            LeaderboardRowSpec(rank=2, name="AylinKilic", score="9,200"),
            LeaderboardRowSpec(rank=3, name="YeniSavasci", score="11,800"),
        ],
        theme="dark",
        fmt="PNG",
        title="Klan Düellosu",
        headers=["Sıra", "Oyuncu", "Puan"],
    )

    authed_page.locator('[data-testid="screenshot-date-input"]').fill("2026-10-12")
    authed_page.locator('[data-testid="screenshot-file-input"]').set_input_files(str(img_path))
    authed_page.locator('[data-testid="screenshot-extract-btn"]').click()

    review_table = authed_page.locator('[data-testid="ocr-review-table"]')
    expect(review_table).to_be_visible(timeout=25_000)

    preview_img = authed_page.locator('[data-testid="ocr-preview-image"]')
    expect(preview_img).to_be_visible()
    assert preview_img.evaluate("el => el.complete && el.naturalWidth > 0") is True

    review_rows = authed_page.locator('[data-testid="ocr-review-tbody"] tr')
    row_count = review_rows.count()
    assert row_count >= 3, f"Expected >= 3 OCR rows, got {row_count}"

    edited_aylin = False
    marked_yeni = False
    for idx in range(row_count):
        tr = review_rows.nth(idx)
        extracted_val = tr.locator('input[data-col="extractedName"]').input_value()
        folded = extracted_val.lower()
        if "aylin" in folded:
            tr.locator('input[data-col="score"]').fill("12500")
            edited_aylin = True
        elif "yeni" in folded:
            if not tr.locator('select[data-col="playerId"]').input_value():
                tr.locator('input[data-col="createPlayer"]').check()
            marked_yeni = True

    assert edited_aylin, "OCR did not extract AylinKilic row from dark PNG"
    assert marked_yeni, "OCR did not extract YeniSavasci row from dark PNG"

    authed_page.locator('[data-testid="ocr-commit-btn"]').click()
    expect(authed_page.locator('[data-testid="ocr-review-panel"]')).to_have_count(0, timeout=15_000)

    summaries = authed_page.locator('[data-testid="duel-summaries-table"]')
    expect(summaries).to_contain_text("ShadowWolf")
    expect(summaries).to_contain_text("AylinKilic")
    expect(summaries).to_contain_text("YeniSavasci")
    expect(summaries).to_contain_text("12.500")
    expect(summaries).to_contain_text("14.500")

    click_nav_link(authed_page, r"Oyuncular")
    expect(authed_page.locator('[data-testid="players-table"]')).to_contain_text("YeniSavasci")


@pytest.mark.tier1
@pytest.mark.tier3
def test_dynamic_daily_limit_changes_and_history(
    authed_page: Page, live_server: ServerHandle
) -> None:
    """Changing daily limit 10,000 -> 15,000 -> 12,000 recalculates compliance and logs history."""
    base = live_server.base_url
    duel_resp = authed_page.request.post(
        f"{base}/api/duels",
        data={"opponent_clan_name": "Buz Klanı", "start_date": "2026-10-10", "status": "ongoing"},
    )
    assert duel_resp.status == 201, duel_resp.text()
    duel_id = duel_resp.json()["duel"]["id"]

    for pname, score in (("OyuncuBir", 16000), ("OyuncuIki", 13000), ("OyuncuUc", 9000)):
        p_resp = authed_page.request.post(
            f"{base}/api/players",
            data={"display_name": pname, "status": "active"},
        )
        assert p_resp.status == 201
        pid = p_resp.json()["player"]["id"]
        s_resp = authed_page.request.post(
            f"{base}/api/duels/{duel_id}/scores",
            data={"player_id": pid, "score": score, "score_date": "2026-10-10"},
        )
        assert s_resp.status == 201

    navigate_and_wait(
        authed_page,
        f"{base}/duels/{duel_id}",
        wait_for_text="Buz Klanı",
    )

    limit_form = authed_page.locator('[data-testid="duel-limit-form"]')
    summaries = authed_page.locator('[data-testid="duel-summaries-table"]')

    # 1. Limit = 10,000 -> 2 met (16k, 13k), 1 missed (9k)
    limit_form.locator('input[name="minScore"]').fill("10000")
    limit_form.locator('input[name="note"]').fill("Başlangıç")
    limit_form.locator('[data-testid="duel-limit-submit"]').click()
    expect(authed_page.locator('[data-testid="duel-active-limit"]')).to_have_text("10.000")
    expect(summaries.locator('[data-limit-status="met"]')).to_have_count(2)
    expect(summaries.locator('[data-limit-status="missed"]')).to_have_count(1)

    # 2. Limit = 15,000 -> 1 met (16k), 2 missed (13k, 9k)
    limit_form.locator('input[name="minScore"]').fill("15000")
    limit_form.locator('input[name="note"]').fill("Hafta sonu")
    limit_form.locator('[data-testid="duel-limit-submit"]').click()
    expect(authed_page.locator('[data-testid="duel-active-limit"]')).to_have_text("15.000")
    expect(summaries.locator('[data-limit-status="met"]')).to_have_count(1)
    expect(summaries.locator('[data-limit-status="missed"]')).to_have_count(2)

    # 3. Limit = 12,000 -> 2 met (16k, 13k), 1 missed (9k)
    limit_form.locator('input[name="minScore"]').fill("12000")
    limit_form.locator('input[name="note"]').fill("Dengeleme")
    limit_form.locator('[data-testid="duel-limit-submit"]').click()
    expect(authed_page.locator('[data-testid="duel-active-limit"]')).to_have_text("12.000")
    expect(summaries.locator('[data-limit-status="met"]')).to_have_count(2)
    expect(summaries.locator('[data-limit-status="missed"]')).to_have_count(1)

    # 4. Check history table on Settings page
    click_nav_link(authed_page, r"Ayarlar")
    history_table = authed_page.locator('[data-testid="limit-history-table"]')
    expect(history_table).to_be_visible()
    expect(history_table).to_contain_text("12.000")
    expect(history_table).to_contain_text("15.000")
    expect(history_table).to_contain_text("10.000")
    expect(history_table).to_contain_text("Dengeleme")
    expect(history_table).to_contain_text("Hafta sonu")
    expect(history_table).to_contain_text("Başlangıç")


@pytest.mark.tier4
def test_server_restart_preserves_data_and_uploaded_screenshot(
    authed_page: Page, live_server: ServerHandle, tmp_path: Path
) -> None:
    """Data, active limit, session, and uploaded screenshot image survive Uvicorn restart."""
    base = live_server.base_url

    p_resp = authed_page.request.post(
        f"{base}/api/players",
        data={"display_name": "KurtBey", "status": "active"},
    )
    assert p_resp.status == 201
    player_id = p_resp.json()["player"]["id"]

    d_resp = authed_page.request.post(
        f"{base}/api/duels",
        data={"opponent_clan_name": "Demir Kalkan", "start_date": "2026-10-15"},
    )
    assert d_resp.status == 201
    duel_id = d_resp.json()["duel"]["id"]

    l_resp = authed_page.request.put(
        f"{base}/api/limits/daily",
        data={"minScore": 11500, "note": "Kalıcılık testi"},
    )
    assert l_resp.status == 200

    img_path = tmp_path / "restart_persist.png"
    generate_leaderboard_image(
        img_path,
        rows=[LeaderboardRowSpec(rank=1, name="KurtBey", score="14,000")],
        theme="dark",
        fmt="PNG",
        headers=["Sıra", "Oyuncu", "Puan"],
    )

    ext_resp = authed_page.request.post(
        f"{base}/api/duels/{duel_id}/screenshots/extract",
        multipart={
            "file": {
                "name": img_path.name,
                "mimeType": "image/png",
                "buffer": img_path.read_bytes(),
            },
            "score_date": "2026-10-15",
        },
        timeout=30_000,
    )
    assert ext_resp.status == 201, ext_resp.text()
    ext_data = ext_resp.json()
    screenshot_id = ext_data["screenshotId"]
    image_url = ext_data["imageUrl"]

    commit_resp = authed_page.request.post(
        f"{base}/api/duels/{duel_id}/screenshots/{screenshot_id}/commit",
        data={
            "score_date": "2026-10-15",
            "rows": [
                {
                    "extractedName": "KurtBey",
                    "score": 14000,
                    "playerId": player_id,
                    "createPlayer": False,
                    "saveAlias": False,
                }
            ],
        },
    )
    assert commit_resp.status == 201, commit_resp.text()

    # Restart Uvicorn against the exact same SQLite DB & upload directory
    new_base = live_server.restart()

    navigate_and_wait(
        authed_page,
        f"{new_base}/duels/{duel_id}",
        wait_for_text="Demir Kalkan",
    )
    expect(authed_page.locator('[data-testid="duel-active-limit"]')).to_have_text("11.500")
    expect(authed_page.locator('[data-testid="duel-summaries-table"]')).to_contain_text("KurtBey")
    expect(authed_page.locator('[data-testid="duel-summaries-table"]')).to_contain_text("14.000")
    expect(authed_page.locator('[data-testid="duel-summaries-table"]')).to_contain_text(
        "Limiti Karşıladı"
    )

    thumb = authed_page.locator('[data-testid="duel-screenshots-list"] img').first
    expect(thumb).to_be_visible()
    assert thumb.evaluate("el => el.complete && el.naturalWidth > 0") is True

    img_fetch = authed_page.request.get(f"{new_base}{image_url}")
    assert img_fetch.status == 200
    assert img_fetch.body().startswith(b"\x89PNG")

    navigate_and_wait(
        authed_page,
        f"{new_base}/players",
        wait_for_text="KurtBey",
    )
    expect(authed_page.locator('[data-testid="players-table"]')).to_contain_text("KurtBey")


@pytest.mark.tier1
def test_unauthenticated_api_blocked_with_401(
    live_server: ServerHandle, api_client: httpx.Client
) -> None:
    """All protected API endpoints reject unauthenticated callers with HTTP 401."""
    with httpx.Client(base_url=live_server.base_url, timeout=15.0) as setup_client:
        setup_and_login_via_api(setup_client)

    assert api_client.get("/api/health").status_code == 200

    for method, path, body in (
        ("GET", "/api/players", None),
        ("POST", "/api/players", {"display_name": "Anon"}),
        ("POST", "/api/players/import-ocr", None),
        ("POST", "/api/players/import-bulk", {"players": [{"display_name": "Anon"}]}),
        ("GET", "/api/fields", None),
        ("GET", "/api/duels", None),
        ("GET", "/api/limits/daily", None),
        ("PUT", "/api/limits/daily", {"minScore": 5000}),
        ("GET", "/api/dashboard", None),
        ("GET", "/api/duels/1/screenshots/1/image", None),
    ):
        if method == "GET":
            r = api_client.get(path)
        elif method == "POST":
            r = api_client.post(path, json=body) if body is not None else api_client.post(path)
        else:
            r = api_client.put(path, json=body)
        assert r.status_code == 401, f"{method} {path} returned {r.status_code} instead of 401"


@pytest.mark.tier1
@pytest.mark.tier3
def test_add_players_from_photo_ocr_flow(
    authed_page: Page, live_server: ServerHandle, tmp_path: Path
) -> None:
    """Upload clan member roster PNG on /players, verify duplicate detection, edit & bulk import."""
    resp = authed_page.request.post(
        f"{live_server.base_url}/api/players",
        data={"display_name": "ShadowWolf", "status": "active"},
    )
    assert resp.status == 201, resp.text()

    img_path = tmp_path / "clan_roster_dark.png"
    generate_leaderboard_image(
        img_path,
        rows=[
            LeaderboardRowSpec(rank=1, name="ShadowWolf", score="Lider"),
            LeaderboardRowSpec(rank=2, clan_tag="[TR]", name="DemirKurt", score="Subay"),
            LeaderboardRowSpec(rank=3, name="AylinKilic", score="Çevrimiçi"),
        ],
        theme="dark",
        fmt="PNG",
        title="Klan Üyeleri",
        headers=["Sıra", "Oyuncu", "Durum"],
    )

    click_nav_link(authed_page, r"Oyuncular")
    expect(authed_page.locator('[data-testid="toggle-photo-import-btn"]')).to_be_visible()
    authed_page.locator('[data-testid="toggle-photo-import-btn"]').click()

    authed_page.locator('[data-testid="player-photo-file-input"]').set_input_files(str(img_path))
    authed_page.locator('[data-testid="player-photo-extract-btn"]').click()

    import_table = authed_page.locator('[data-testid="player-import-table"]')
    expect(import_table).to_be_visible(timeout=25_000)

    preview_img = authed_page.locator('[data-testid="player-import-preview-image"]')
    expect(preview_img).to_be_visible()
    assert preview_img.evaluate("el => el.complete && el.naturalWidth > 0") is True

    import_rows = authed_page.locator('[data-testid="player-import-tbody"] tr')
    row_count = import_rows.count()
    assert row_count == 3, f"Expected 3 extracted candidates, got {row_count}"

    saw_existing_shadow = False
    saw_demirkurt = False
    edited_aylin = False
    for idx in range(row_count):
        tr = import_rows.nth(idx)
        name_input = tr.locator('input[data-col="display_name"]')
        cb = tr.locator('input[data-col="selected"]')
        val = name_input.input_value().lower()
        if "shadow" in val:
            saw_existing_shadow = True
            expect(tr).to_contain_text("Zaten Kayıtlı")
            assert cb.is_checked() is False
        elif "demir" in val:
            saw_demirkurt = True
            assert cb.is_checked() is True
        elif "aylin" in val:
            name_input.fill("AylinKilicPro")
            edited_aylin = True
            assert cb.is_checked() is True

    assert saw_existing_shadow, "Existing player ShadowWolf was not flagged"
    assert saw_demirkurt, "DemirKurt was not extracted from roster PNG"
    assert edited_aylin, "AylinKilic was not extracted from roster PNG"

    authed_page.locator('[data-testid="player-import-commit-btn"]').click()
    expect(authed_page.locator('[data-testid="player-import-table"]')).to_have_count(
        0, timeout=15_000
    )

    players_table = authed_page.locator('[data-testid="players-table"]')
    expect(players_table).to_contain_text("DemirKurt")
    expect(players_table).to_contain_text("AylinKilicPro")
    expect(players_table.locator("tbody tr")).to_have_count(3)

    authed_page.reload(wait_until="load")
    players_after = authed_page.locator('[data-testid="players-table"]')
    expect(players_after).to_contain_text("DemirKurt")
    expect(players_after).to_contain_text("AylinKilicPro")
    expect(players_after.locator("tbody tr")).to_have_count(3)


@pytest.mark.tier1
@pytest.mark.tier3
def test_player_rank_and_tower_level_ui_and_filters(
    authed_page: Page, live_server: ServerHandle
) -> None:
    """Create players with Rank (R1-R5) and Tower Level (I1-I10), filter list, edit & persist."""
    _ = live_server
    click_nav_link(authed_page, r"Oyuncular")
    expect(authed_page.locator('[data-testid="toggle-add-player-btn"]')).to_be_visible()

    # 1. Add Kuleci (R4, I7)
    authed_page.locator('[data-testid="toggle-add-player-btn"]').click()
    add_form = authed_page.locator('[data-testid="add-player-form"]')
    add_form.locator("#add-player-name").fill("Kuleci")
    add_form.locator("#add-player-rank").select_option("R4")
    add_form.locator("#add-player-tower").select_option("I7")
    add_form.locator('[data-testid="create-player-submit"]').click()
    table = authed_page.locator('[data-testid="players-table"]')
    expect(table).to_contain_text("Kuleci")

    # 2. Add LiderBey (R5, I10)
    authed_page.locator('[data-testid="toggle-add-player-btn"]').click()
    add_form.locator("#add-player-name").fill("LiderBey")
    add_form.locator("#add-player-rank").select_option("R5")
    add_form.locator("#add-player-tower").select_option("I10")
    add_form.locator('[data-testid="create-player-submit"]').click()
    expect(table).to_contain_text("LiderBey")

    # 3. Add Acemi (R1, I9)
    authed_page.locator('[data-testid="toggle-add-player-btn"]').click()
    add_form.locator("#add-player-name").fill("Acemi")
    add_form.locator("#add-player-rank").select_option("R1")
    add_form.locator("#add-player-tower").select_option("I9")
    add_form.locator('[data-testid="create-player-submit"]').click()
    expect(table).to_contain_text("Acemi")

    expect(table.locator("tbody tr")).to_have_count(3)
    expect(table).to_contain_text("R4")
    expect(table).to_contain_text("I7")
    expect(table).to_contain_text("R5")
    expect(table).to_contain_text("I10")
    expect(table).to_contain_text("R1")
    expect(table).to_contain_text("I9")

    # 3b. Verify all 6 sort modes + clickable header sorting
    row_names = table.locator("tbody tr td:first-child a strong")
    sort_select = authed_page.locator('[data-testid="players-sort-select"]')

    # Default sort is rank_desc (R5 -> R4 -> R1)
    expect(row_names).to_have_text(["LiderBey", "Kuleci", "Acemi"])

    sort_select.select_option("rank_asc")
    expect(row_names).to_have_text(["Acemi", "Kuleci", "LiderBey"])

    sort_select.select_option("tower_desc")
    expect(row_names).to_have_text(["LiderBey", "Acemi", "Kuleci"])

    sort_select.select_option("tower_asc")
    expect(row_names).to_have_text(["Kuleci", "Acemi", "LiderBey"])

    sort_select.select_option("name_asc")
    expect(row_names).to_have_text(["Acemi", "Kuleci", "LiderBey"])

    # Click "Oyuncu Adı" header button to toggle to name_desc
    table.locator('button[data-sort-col="name"]').click()
    expect(row_names).to_have_text(["LiderBey", "Kuleci", "Acemi"])
    expect(sort_select).to_have_value("name_desc")

    # 3c. Filter by Rank = R5 -> only LiderBey
    rank_filter = authed_page.locator('[data-testid="players-rank-filter"]')
    tower_filter = authed_page.locator('[data-testid="players-tower-filter"]')

    rank_filter.select_option("R5")
    expect(table.locator("tbody tr")).to_have_count(1)
    expect(table).to_contain_text("LiderBey")

    rank_filter.select_option("")
    tower_filter.select_option("I7")
    expect(table.locator("tbody tr")).to_have_count(1)
    expect(table).to_contain_text("Kuleci")

    tower_filter.select_option("")
    expect(table.locator("tbody tr")).to_have_count(3)

    # 4. Open Kuleci detail page, update Rank R4 -> R5 and Tower I7 -> I9, reload
    table.get_by_role("link", name="Kuleci").click()
    expect(authed_page.locator('[data-testid="player-detail-name"]')).to_have_text("Kuleci")
    expect(authed_page.locator('[data-testid="player-detail-rank"]')).to_have_text("R4")
    expect(authed_page.locator('[data-testid="player-detail-tower"]')).to_have_text("I7")

    edit_form = authed_page.locator('[data-testid="player-edit-form"]')
    edit_form.locator("#edit-player-rank").select_option("R5")
    edit_form.locator("#edit-player-tower").select_option("I9")
    edit_form.locator('[data-testid="save-player-btn"]').click()

    expect(authed_page.locator('[data-testid="player-detail-rank"]')).to_have_text("R5")
    expect(authed_page.locator('[data-testid="player-detail-tower"]')).to_have_text("I9")

    authed_page.reload(wait_until="load")
    expect(authed_page.locator('[data-testid="player-detail-rank"]')).to_have_text("R5")
    expect(authed_page.locator('[data-testid="player-detail-tower"]')).to_have_text("I9")


@pytest.mark.tier1
@pytest.mark.tier3
def test_language_switching_en_ar_rtl_it_and_persistence(
    authed_page: Page, live_server: ServerHandle
) -> None:
    """Switch UI languages TR -> EN -> AR (RTL + reload) -> IT -> TR -> /login with zero page errors."""
    _ = live_server
    pageerrors: list[str] = []
    authed_page.on("pageerror", lambda err: pageerrors.append(str(err)))

    html = authed_page.locator("html")
    lang_select = authed_page.locator('[data-testid="lang-select"]')

    # 1. Default is Turkish (LTR)
    expect(html).to_have_attribute("lang", "tr")
    expect(html).to_have_attribute("dir", "ltr")
    expect(lang_select).to_have_value("tr")
    expect(authed_page.get_by_role("heading", name="Genel Bakış")).to_be_visible()

    # 2. Switch to English via topbar language selector
    lang_select.select_option("en")
    expect(html).to_have_attribute("lang", "en")
    expect(html).to_have_attribute("dir", "ltr")
    expect(authed_page.get_by_role("heading", name="Overview")).to_be_visible()
    expect(authed_page.locator('[data-testid="nav-players"]')).to_have_text("Players")
    expect(authed_page.locator('[data-testid="nav-duels"]')).to_have_text("Clan Duels")
    expect(authed_page.locator('[data-testid="nav-settings"]')).to_have_text("Settings")

    authed_page.locator('[data-testid="nav-players"]').click()
    expect(authed_page.get_by_role("heading", name="Players")).to_be_visible()
    sort_select = authed_page.locator('[data-testid="players-sort-select"]')
    expect(sort_select.locator('option[value="rank_desc"]')).to_have_text("Rank (R5 → R1)")
    expect(sort_select.locator('option[value="tower_desc"]')).to_have_text(
        "Tower Level (I10 → I1)"
    )

    # 3. Switch to Arabic and verify RTL layout geometry + reload persistence
    lang_select.select_option("ar")
    expect(html).to_have_attribute("lang", "ar")
    expect(html).to_have_attribute("dir", "rtl")
    expect(authed_page.get_by_role("heading", name="اللاعبون")).to_be_visible()

    sidebar_box = authed_page.locator(".sidebar").bounding_box()
    main_box = authed_page.locator(".main-area").bounding_box()
    assert sidebar_box is not None and main_box is not None
    assert sidebar_box["x"] > main_box["x"], (
        f"Expected RTL sidebar on the right (sidebar.x={sidebar_box['x']}, main.x={main_box['x']})"
    )

    authed_page.reload(wait_until="load")
    expect(html).to_have_attribute("lang", "ar")
    expect(html).to_have_attribute("dir", "rtl")
    expect(lang_select).to_have_value("ar")
    expect(authed_page.get_by_role("heading", name="اللاعبون")).to_be_visible()

    # 4. Switch to Italian and verify Settings language selector synchronization
    lang_select.select_option("it")
    expect(html).to_have_attribute("lang", "it")
    expect(html).to_have_attribute("dir", "ltr")
    expect(authed_page.get_by_role("heading", name="Giocatori")).to_be_visible()

    authed_page.locator('[data-testid="nav-settings"]').click()
    expect(authed_page.get_by_role("heading", name="Impostazioni")).to_be_visible()
    settings_lang = authed_page.locator('[data-testid="settings-lang-select"]')
    expect(settings_lang).to_have_value("it")

    # Switch back to Turkish from Settings card selector
    settings_lang.select_option("tr")
    expect(html).to_have_attribute("lang", "tr")
    expect(html).to_have_attribute("dir", "ltr")
    expect(lang_select).to_have_value("tr")
    expect(authed_page.get_by_role("heading", name="Ayarlar")).to_be_visible()

    # 5. Logout to /login and verify language switching on auth screen
    authed_page.locator('[data-testid="logout-btn"]').click()
    expect(authed_page).to_have_url(re.compile(r"/login/?$"))

    login_lang = authed_page.locator('[data-testid="lang-select"]')
    login_lang.select_option("en")
    expect(html).to_have_attribute("lang", "en")
    expect(authed_page.get_by_role("heading", name="Admin Login")).to_be_visible()

    login_lang.select_option("it")
    expect(html).to_have_attribute("lang", "it")
    expect(authed_page.get_by_role("heading", name="Accesso Amministratore")).to_be_visible()

    login_lang.select_option("ar")
    expect(html).to_have_attribute("lang", "ar")
    expect(html).to_have_attribute("dir", "rtl")
    expect(authed_page.get_by_role("heading", name="تسجيل دخول المشرف")).to_be_visible()

    assert pageerrors == [], f"Unexpected browser page errors: {pageerrors}"
