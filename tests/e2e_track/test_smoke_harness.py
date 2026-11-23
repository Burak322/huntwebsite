"""Smoke tests for E2E-M1 harness, screenshot factory, Playwright browser, and live Uvicorn."""

from __future__ import annotations

import ast
import os
import re
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageStat, UnidentifiedImageError
from playwright.sync_api import Browser, Page, expect

from tests.e2e_track.conftest import ServerHandle
from tests.e2e_track.helpers import screenshot_factory, ui_helpers
from tests.e2e_track.helpers.screenshot_factory import (
    LeaderboardRowSpec,
    TURKISH_SAMPLE_CHARS,
    generate_corrupt_or_blank_image,
    generate_leaderboard_image,
)
from tests.e2e_track.helpers.ui_helpers import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_CLAN_NAME,
    login_via_api,
    login_via_ui,
    logout_via_ui,
    setup_admin_via_ui,
    setup_and_login_via_api,
)

E2E_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = E2E_ROOT.parents[1]


def _has_app_entrypoint() -> bool:
    return (PROJECT_ROOT / "app" / "main.py").is_file()


# ---------------------------------------------------------------------------
# Group A: Always-executable harness checks (no live_server dependency)
# ---------------------------------------------------------------------------


@pytest.mark.harness
def test_e2e_env_isolation(e2e_env: dict) -> None:
    """Verify e2e_env points DB and uploads to an isolated temp dir with sanitized admin env."""
    db_path: Path = e2e_env["db_path"]
    upload_dir: Path = e2e_env["upload_dir"]
    env: dict[str, str] = e2e_env["env"]

    assert db_path.name == "clan.db"
    assert db_path != PROJECT_ROOT / "data" / "clan.db"
    assert upload_dir.is_dir()
    assert upload_dir != PROJECT_ROOT / "data" / "uploads"
    assert env["CLAN_DB_PATH"] == str(db_path)
    assert env["CLAN_UPLOAD_DIR"] == str(upload_dir)
    assert "CLAN_ADMIN_USERNAME" not in env
    assert "CLAN_ADMIN_PASSWORD" not in env
    assert "CLAN_COOKIE_SECURE" not in env
    assert "CLAN_STATIC_DIR" not in env
    assert "CLAN_SESSION_TTL_HOURS" not in env
    assert "CLAN_MAX_UPLOAD_BYTES" not in env
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"

    scrubbed_handle = ServerHandle(
        project_root=PROJECT_ROOT,
        db_path=db_path,
        upload_dir=upload_dir,
        log_path=e2e_env["log_path"],
        env={**env, "CLAN_ADMIN_USERNAME": "leaked", "CLAN_ADMIN_PASSWORD": "leaked"},
    )
    assert "CLAN_ADMIN_USERNAME" not in scrubbed_handle.env
    assert "CLAN_ADMIN_PASSWORD" not in scrubbed_handle.env


@pytest.mark.harness
def test_screenshot_factory_dark_and_light_images(tmp_path: Path) -> None:
    """Verify real PNG/JPG leaderboard generation with Turkish glyphs, tags, and score formats."""
    rows = [
        LeaderboardRowSpec(rank=1, clan_tag="[TR]", name="Çağatay Şahin", score="12,450"),
        LeaderboardRowSpec(rank=2, clan_tag="[AK]", name="Güneş Yılmaz", score="10.800"),
        LeaderboardRowSpec(rank=3, name="İbrahim Öztürk_UzunİsimDenemesi", score="1.2M"),
        LeaderboardRowSpec(rank=4, name="Şebnem Çelik", score="45K"),
    ]

    dark_png = generate_leaderboard_image(
        tmp_path / "dark_board.png",
        rows,
        theme="dark",
        fmt="PNG",
        title=f"Klan Düellosu — {TURKISH_SAMPLE_CHARS}",
        headers=["Sıra", "Oyuncu", "Puan"],
    )
    light_jpg = generate_leaderboard_image(
        tmp_path / "light_board.jpg",
        rows,
        theme="light",
        fmt="JPG",
        title="Aydınlık Tema Tablosu",
        headers=["Sıra", "Oyuncu", "Puan"],
    )

    assert dark_png.is_file()
    assert light_jpg.is_file()

    with Image.open(dark_png) as img_dark:
        assert img_dark.format == "PNG"
        assert img_dark.size[0] >= 900
        assert img_dark.size[1] > 200
        dark_mean = ImageStat.Stat(img_dark.convert("L")).mean[0]

    with Image.open(light_jpg) as img_light:
        assert img_light.format == "JPEG"
        assert img_light.mode == "RGB"
        assert img_light.size[0] >= 900
        light_mean = ImageStat.Stat(img_light.convert("L")).mean[0]

    assert dark_mean < light_mean


@pytest.mark.harness
def test_screenshot_factory_blank_corrupt_and_no_scores(tmp_path: Path) -> None:
    """Verify blank, corrupt_bytes, and no_scores edge-case screenshot generators."""
    blank_path = generate_corrupt_or_blank_image(tmp_path / "blank.png", mode="blank")
    corrupt_path = generate_corrupt_or_blank_image(tmp_path / "corrupt.png", mode="corrupt_bytes")
    no_scores_path = generate_corrupt_or_blank_image(tmp_path / "no_scores.png", mode="no_scores")

    with Image.open(blank_path) as blank_img:
        assert blank_img.format == "PNG"
        assert max(ImageStat.Stat(blank_img.convert("L")).stddev) < 0.01

    assert corrupt_path.is_file()
    assert corrupt_path.stat().st_size > 0
    with pytest.raises((UnidentifiedImageError, OSError)):
        with Image.open(corrupt_path) as bad_img:
            bad_img.verify()

    with Image.open(no_scores_path) as prose_img:
        assert prose_img.format == "PNG"
        assert ImageStat.Stat(prose_img.convert("L")).stddev[0] > 5.0


@pytest.mark.harness
def test_playwright_launch_and_turkish_utf8_svg(browser: Browser) -> None:
    """Verify headless Chrome/Edge renders Turkish UTF-8 text and inline SVG cleanly."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="tr-TR")
    try:
        pg = ctx.new_page()
        pg.set_content(
            f"""
            <!doctype html>
            <html lang="tr">
              <head><meta charset="utf-8"></head>
              <body>
                <h1 id="title">Klan Yönetimi — {TURKISH_SAMPLE_CHARS}</h1>
                <svg id="trend" width="220" height="80" viewBox="0 0 220 80">
                  <polyline points="0,65 110,30 220,10" stroke="#38bdf8" fill="none" />
                </svg>
              </body>
            </html>
            """
        )
        text = pg.locator("#title").text_content()
        assert text == f"Klan Yönetimi — {TURKISH_SAMPLE_CHARS}"
        box = pg.locator("#trend").bounding_box()
        assert box is not None
        assert box["width"] > 0 and box["height"] > 0
    finally:
        ctx.close()


@pytest.mark.harness
def test_e2e_track_opaque_box_hygiene() -> None:
    """Ensure zero app.* imports exist anywhere under tests/e2e_track/."""
    py_files = sorted(E2E_ROOT.rglob("*.py"))
    assert len(py_files) >= 5

    violations: list[str] = []
    for py_file in py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app" or alias.name.startswith("app."):
                        violations.append(f"{py_file}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "app" or mod.startswith("app."):
                    violations.append(f"{py_file}: from {mod} import ...")

    assert not violations, f"Opaque-box violation: {violations}"
    assert callable(screenshot_factory.generate_leaderboard_image)
    assert callable(screenshot_factory.generate_corrupt_or_blank_image)
    assert callable(ui_helpers.setup_and_login_via_api)
    assert callable(ui_helpers.setup_admin_via_ui)
    assert callable(ui_helpers.authenticate_browser_via_api)


# ---------------------------------------------------------------------------
# Group B: Live Uvicorn & M1 UI/Auth checks
# ---------------------------------------------------------------------------


@pytest.mark.harness
@pytest.mark.skipif(not _has_app_entrypoint(), reason="M1 runtime (app/main.py) not yet present")
def test_live_server_health_and_unauthenticated_guard(live_server, api_client: httpx.Client) -> None:
    """Verify isolated Uvicorn starts healthy, needs setup, and guards /api/auth/me with 401."""
    health = api_client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"ok": True, "db": "connected"}

    status = api_client.get("/api/auth/status")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["needsSetup"] is True
    assert status_body["authenticated"] is False

    me = api_client.get("/api/auth/me")
    assert me.status_code == 401


@pytest.mark.harness
@pytest.mark.skipif(not _has_app_entrypoint(), reason="M1 runtime (app/main.py) not yet present")
def test_live_server_restart_preserves_state(live_server, api_client: httpx.Client) -> None:
    """Verify ServerHandle.restart() preserves SQLite admin state across subprocess restarts."""
    me_before = setup_and_login_via_api(
        api_client,
        username=DEFAULT_ADMIN_USERNAME,
        password=DEFAULT_ADMIN_PASSWORD,
        clan_name=DEFAULT_CLAN_NAME,
    )
    assert me_before["admin"]["username"] == DEFAULT_ADMIN_USERNAME
    assert live_server.db_path.is_file()

    new_base_url = live_server.restart()

    with httpx.Client(base_url=new_base_url, timeout=15.0) as restarted_client:
        health = restarted_client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"ok": True, "db": "connected"}

        status = restarted_client.get("/api/auth/status")
        assert status.status_code == 200
        assert status.json()["needsSetup"] is False
        assert status.json()["clanName"] == DEFAULT_CLAN_NAME

        login_resp = login_via_api(
            restarted_client,
            username=DEFAULT_ADMIN_USERNAME,
            password=DEFAULT_ADMIN_PASSWORD,
        )
        assert login_resp["admin"]["username"] == DEFAULT_ADMIN_USERNAME


@pytest.mark.harness
@pytest.mark.skipif(not _has_app_entrypoint(), reason="M1 runtime (app/main.py) not yet present")
def test_authed_page_lands_on_dashboard(authed_page: Page) -> None:
    """Verify authed_page authenticates via BrowserContext cookie jar and renders /."""
    expect(authed_page).to_have_url(re.compile(r"/$"))
    expect(authed_page.get_by_role("heading", name=re.compile(r"Genel Bakış", re.I))).to_be_visible()
    expect(authed_page.get_by_text(DEFAULT_CLAN_NAME).first).to_be_visible()


@pytest.mark.harness
@pytest.mark.skipif(not _has_app_entrypoint(), reason="M1 runtime (app/main.py) not yet present")
def test_ui_setup_logout_login_round_trip(page: Page) -> None:
    """Verify real browser setup -> dashboard -> logout -> login round-trip against M1."""
    setup_admin_via_ui(
        page,
        username=DEFAULT_ADMIN_USERNAME,
        password=DEFAULT_ADMIN_PASSWORD,
        clan_name=DEFAULT_CLAN_NAME,
    )
    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.get_by_role("heading", name=re.compile(r"Genel Bakış", re.I))).to_be_visible()

    logout_via_ui(page)
    expect(page.get_by_role("heading", name=re.compile(r"Yönetici Girişi", re.I))).to_be_visible()

    login_via_ui(
        page,
        username=DEFAULT_ADMIN_USERNAME,
        password=DEFAULT_ADMIN_PASSWORD,
    )
    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.get_by_role("heading", name=re.compile(r"Genel Bakış", re.I))).to_be_visible()


@pytest.mark.harness
def test_locate_input_resilient_nested_container_and_hidden_match(browser: Browser) -> None:
    """Verify Strategy 4 resolves wrapped, sibling, and .form-field labels and skips hidden nth(0)."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="tr-TR")
    try:
        pg = ctx.new_page()
        pg.set_content(
            """
            <!doctype html>
            <html lang="tr">
              <head><meta charset="utf-8"></head>
              <body>
                <div class="app-shell">
                  <form>
                    <div class="form-field"><label>Oyuncu Adı</label><input id="first"></div>
                    <div class="form-field"><label>Puan</label><div class="ctrl"><input id="second"></div></div>
                    <fieldset>
                      <label>Rütbe</label><input id="fs-multi-rank">
                      <label>Seviye</label><input id="fs-multi-level">
                    </fieldset>
                    <p>
                      <label>Şehir</label><select id="p-city"><option>Ankara</option></select>
                      <label>Notlar</label><textarea id="p-notes"></textarea>
                    </p>
                    <label>Bölge <input id="wrapped-region"></label>
                    <div style="display:none"><input id="hidden-score" name="score"></div>
                    <div><input id="visible-score" name="score"></div>
                  </form>
                </div>
              </body>
            </html>
            """
        )
        second = ui_helpers.locate_input_resilient(pg, label_patterns=[r"Puan"])
        assert second.get_attribute("id") == "second"

        fs_rank = ui_helpers.locate_input_resilient(pg, label_patterns=[r"Rütbe"])
        assert fs_rank.get_attribute("id") == "fs-multi-rank"

        fs_level = ui_helpers.locate_input_resilient(pg, label_patterns=[r"Seviye"])
        assert fs_level.get_attribute("id") == "fs-multi-level"

        p_notes = ui_helpers.locate_input_resilient(pg, label_patterns=[r"Notlar"])
        assert p_notes.get_attribute("id") == "p-notes"

        wrapped_region = ui_helpers.locate_input_resilient(pg, label_patterns=[r"Bölge"])
        assert wrapped_region.get_attribute("id") == "wrapped-region"

        visible_score = ui_helpers.locate_input_resilient(pg, attr_names=["score"])
        assert visible_score.get_attribute("id") == "visible-score"
    finally:
        ctx.close()


@pytest.mark.harness
def test_navigate_and_wait_skips_hidden_preceding_landmark(browser: Browser) -> None:
    """Verify navigate_and_wait succeeds when hidden <nav>/<form> precedes visible <main>."""
    html_pages = {
        "/": (
            '<!doctype html><html lang="tr"><head><meta charset="utf-8"></head>'
            '<body><nav id="hidden-nav" style="display:none"><a href="/">Ana Sayfa</a></nav>'
            "<main><h1>Yönetici Girişi</h1></main></body></html>"
        ),
        "/login": (
            '<!doctype html><html lang="tr"><head><meta charset="utf-8"></head>'
            '<body><form id="hidden-form" style="display:none"><input id="hid-u"></form>'
            '<main><form id="vis-form"><input id="vis-u" name="username"></form></main>'
            "</body></html>"
        ),
    }

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = html_pages.get(self.path, "<h1>404</h1>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="tr-TR")
    try:
        pg = ctx.new_page()
        ui_helpers.navigate_and_wait(
            pg,
            f"http://127.0.0.1:{port}/",
            wait_for_text="Yönetici Girişi",
            timeout=3000,
        )
        assert pg.locator("main h1").text_content() == "Yönetici Girişi"

        ui_helpers.navigate_and_wait(pg, f"http://127.0.0.1:{port}/login", timeout=3000)
        pg.locator("form:visible, input:visible").first.wait_for(state="visible", timeout=3000)
        vis_input = ui_helpers.locate_input_resilient(pg, attr_names=["username"], timeout=3000)
        assert vis_input.get_attribute("id") == "vis-u"
    finally:
        ctx.close()
        server.shutdown()
        server.server_close()


@pytest.mark.harness
@pytest.mark.skipif(not _has_app_entrypoint(), reason="M1 runtime (app/main.py) not yet present")
def test_server_handle_stop_immediate_cleanup_multi_cycle(tmp_path: Path) -> None:
    """Verify ServerHandle.stop() releases uvicorn.log and DB handles with 0ms delay across cycles."""
    base_env = os.environ.copy()
    for key in (
        "CLAN_ADMIN_USERNAME",
        "CLAN_ADMIN_PASSWORD",
        "CLAN_COOKIE_SECURE",
        "CLAN_STATIC_DIR",
        "CLAN_SESSION_TTL_HOURS",
        "CLAN_MAX_UPLOAD_BYTES",
    ):
        base_env.pop(key, None)
    base_env["PYTHONUTF8"] = "1"
    base_env["PYTHONIOENCODING"] = "utf-8"
    base_env["PYTHONUNBUFFERED"] = "1"

    for cycle in range(3):
        cycle_dir = tmp_path / f"cycle_{cycle}"
        db_path = cycle_dir / "clan.db"
        upload_dir = cycle_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        log_path = cycle_dir / "uvicorn.log"

        cycle_env = dict(base_env)
        cycle_env["CLAN_DB_PATH"] = str(db_path)
        cycle_env["CLAN_UPLOAD_DIR"] = str(upload_dir)

        handle = ServerHandle(
            project_root=PROJECT_ROOT,
            db_path=db_path,
            upload_dir=upload_dir,
            log_path=log_path,
            env=cycle_env,
        )
        try:
            url = handle.start()
            with httpx.Client(base_url=url, timeout=15.0) as client:
                setup_and_login_via_api(client)
            restarted_url = handle.restart()
            with httpx.Client(base_url=restarted_url, timeout=15.0) as client:
                health = client.get("/api/health")
                assert health.status_code == 200
                assert health.json() == {"ok": True, "db": "connected"}
        finally:
            handle.stop()

        os.unlink(log_path)
        shutil.rmtree(cycle_dir)
        assert not cycle_dir.exists()
