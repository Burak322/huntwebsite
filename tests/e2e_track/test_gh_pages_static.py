"""Opaque-box Playwright E2E tests for the GitHub Pages static bundle in docs/."""

from __future__ import annotations

import json
import mimetypes
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from playwright.sync_api import Browser, expect

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = PROJECT_ROOT / "docs"
SUBPATH_PREFIX = "/huntwebsite"


def _walk_dict_keys(obj: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(str(k))
            found.update(_walk_dict_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            found.update(_walk_dict_keys(item))
    return found


@pytest.mark.tier1
def test_gh_pages_seed_has_no_secrets_and_expected_roster() -> None:
    """Verify docs/seed.json contains the clan roster and zero credentials or session tokens."""
    seed_path = DOCS_ROOT / "seed.json"
    assert seed_path.is_file(), "docs/seed.json not found; run scripts/build_gh_pages.py"
    assert (DOCS_ROOT / "index.html").is_file()
    assert (DOCS_ROOT / "404.html").is_file()
    assert (DOCS_ROOT / ".nojekyll").is_file()

    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    assert seed["auth"]["clanName"] == "Hunt"
    assert seed["auth"]["passwordHash"] is None
    assert seed["activeDailyMinScore"] == 2500000
    assert len(seed["players"]) == 99
    assert seed["duels"][0]["opponent_clan_name"] == "S21 [CVC]"

    keys = _walk_dict_keys(seed)
    forbidden = {"admin_users", "admin_sessions", "password", "password_hash", "token", "token_hash"}
    assert keys.isdisjoint(forbidden), f"Secret keys leaked in seed.json: {keys & forbidden}"


@pytest.mark.tier1
@pytest.mark.tier3
def test_gh_pages_static_site_under_subpath_end_to_end(browser: Browser) -> None:
    """Serve docs/ under /huntwebsite/ and verify dashboard, players, reload, i18n, limits & reset."""
    docs_resolved = DOCS_ROOT.resolve()

    class _SubpathStaticHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            req_path = unquote(self.path.split("?", 1)[0])
            if not req_path.startswith(SUBPATH_PREFIX):
                self.send_error(404, "Outside GitHub Pages project subpath")
                return

            rel = req_path[len(SUBPATH_PREFIX) :].lstrip("/")
            if rel == "":
                rel = "index.html"

            target = (docs_resolved / rel).resolve()
            if target.is_dir():
                target = (target / "index.html").resolve()

            if not target.is_relative_to(docs_resolved) or not target.is_file():
                self.send_error(404, "File not found")
                return

            ctype, _ = mimetypes.guess_type(target.name)
            if target.suffix == ".js":
                ctype = "application/javascript; charset=utf-8"
            elif target.suffix == ".css":
                ctype = "text/css; charset=utf-8"
            elif target.suffix == ".json":
                ctype = "application/json; charset=utf-8"
            elif target.suffix == ".html":
                ctype = "text/html; charset=utf-8"
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _SubpathStaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}{SUBPATH_PREFIX}/"

    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="tr-TR")
    try:
        pg = ctx.new_page()
        pg.set_default_timeout(10_000)
        pageerrors: list[str] = []
        bad_responses: list[tuple[int, str]] = []
        pg.on("pageerror", lambda err: pageerrors.append(str(err)))
        pg.on(
            "response",
            lambda r: bad_responses.append((r.status, r.url))
            if r.status >= 400 and "favicon.ico" not in r.url
            else None,
        )

        # 1. Load root subpath -> Dashboard seeded with Hunt clan & 99 players
        pg.goto(base, wait_until="load")
        expect(pg.get_by_role("heading", name="Genel Bakış")).to_be_visible(timeout=15_000)
        expect(pg.locator(".brand-title")).to_have_text("Hunt")
        expect(pg.locator('[data-testid="dashboard-active-limit"]')).to_have_text("2.500.000")
        expect(pg.get_by_text("S21 [CVC]")).to_be_visible()

        # 2. Navigate to Players -> verify 99 players + add + reload hash route
        pg.locator('[data-testid="nav-players"]').click()
        expect(pg).to_have_url(re.compile(r"#/players$"))
        table = pg.locator('[data-testid="players-table"]')
        expect(table).to_be_visible()
        expect(table.locator("tbody tr")).to_have_count(99)

        pg.locator('[data-testid="players-sort-select"]').select_option("name_asc")
        pg.locator('[data-testid="toggle-add-player-btn"]').click()
        add_form = pg.locator('[data-testid="add-player-form"]')
        add_form.locator("#add-player-name").fill("PagesTestOyuncu")
        add_form.locator("#add-player-rank").select_option("R4")
        add_form.locator("#add-player-tower").select_option("I10")
        add_form.locator('[data-testid="create-player-submit"]').click()

        expect(table).to_contain_text("PagesTestOyuncu")
        expect(table.locator("tbody tr")).to_have_count(100)

        pg.reload(wait_until="load")
        expect(pg).to_have_url(re.compile(r"#/players$"))
        expect(pg.locator('[data-testid="players-table"]')).to_contain_text("PagesTestOyuncu")
        expect(pg.locator('[data-testid="players-table"] tbody tr')).to_have_count(100)

        # 3. Switch UI languages TR -> EN -> AR (RTL) -> IT -> TR
        lang_sel = pg.locator('[data-testid="lang-select"]')
        html = pg.locator("html")

        lang_sel.select_option("en")
        expect(html).to_have_attribute("lang", "en")
        expect(pg.get_by_role("heading", name="Players")).to_be_visible()

        lang_sel.select_option("ar")
        expect(html).to_have_attribute("lang", "ar")
        expect(html).to_have_attribute("dir", "rtl")
        expect(pg.get_by_role("heading", name="اللاعبون")).to_be_visible()

        lang_sel.select_option("it")
        expect(html).to_have_attribute("lang", "it")
        expect(html).to_have_attribute("dir", "ltr")
        expect(pg.get_by_role("heading", name="Giocatori")).to_be_visible()

        lang_sel.select_option("tr")
        expect(pg.get_by_role("heading", name="Oyuncular")).to_be_visible()

        # 4. Settings -> backup section visible, update limit, and reset back to seed
        pg.locator('[data-testid="nav-settings"]').click()
        expect(pg).to_have_url(re.compile(r"#/settings$"))
        expect(pg.locator('[data-testid="settings-backup-section"]')).to_be_visible()

        limit_form = pg.locator('[data-testid="settings-limit-form"]')
        limit_form.locator('input[name="minScore"]').fill("3000000")
        limit_form.locator('input[name="note"]').fill("Pages testi")
        limit_form.locator('[data-testid="settings-limit-submit"]').click()
        expect(pg.locator('[data-testid="settings-active-limit"]')).to_have_text("3.000.000")
        expect(pg.locator('[data-testid="limit-history-table"]')).to_contain_text("3.000.000")

        pg.locator('[data-testid="ask-reset-seed-btn"]').click()
        pg.locator('[data-testid="confirm-reset-seed-btn"]').click()
        expect(pg.locator('[data-testid="settings-active-limit"]')).to_have_text("2.500.000")

        pg.locator('[data-testid="nav-players"]').click()
        expect(pg.locator('[data-testid="players-table"] tbody tr')).to_have_count(99)

        assert pageerrors == [], f"Unexpected browser pageerrors: {pageerrors}"
        assert bad_responses == [], f"Unexpected HTTP errors: {bad_responses}"
    finally:
        ctx.close()
        server.shutdown()
        server.server_close()
