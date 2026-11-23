"""Opaque-box Playwright UI and httpx REST API helpers aligned with PROJECT.md §2 & §4."""

from __future__ import annotations

import mimetypes
import re
import time
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

DEFAULT_ADMIN_USERNAME = "klanlideri"
DEFAULT_ADMIN_PASSWORD = "GucluSifre!2026"
DEFAULT_CLAN_NAME = "Anadolu Kurtları"


def _assert_status(resp: httpx.Response, expected: int, context: str) -> dict[str, Any]:
    if resp.status_code != expected:
        raise AssertionError(
            f"{context}: expected HTTP {expected}, got {resp.status_code}. Body: {resp.text}"
        )
    return resp.json()


# ---------------------------------------------------------------------------
# Opaque-box HTTP API helpers (exact PROJECT.md §2 payload casing)
# ---------------------------------------------------------------------------


def get_auth_status_via_api(client: httpx.Client) -> dict[str, Any]:
    """GET /api/auth/status."""
    return _assert_status(client.get("/api/auth/status"), 200, "GET /api/auth/status")


def setup_and_login_via_api(
    client: httpx.Client,
    *,
    username: str = DEFAULT_ADMIN_USERNAME,
    password: str = DEFAULT_ADMIN_PASSWORD,
    clan_name: str = DEFAULT_CLAN_NAME,
) -> dict[str, Any]:
    """Idempotently perform initial /api/auth/setup or /api/auth/login and verify /api/auth/me."""
    status = get_auth_status_via_api(client)
    if status.get("needsSetup"):
        _assert_status(
            client.post(
                "/api/auth/setup",
                json={"username": username, "password": password, "clanName": clan_name},
            ),
            201,
            "POST /api/auth/setup",
        )
    elif not status.get("authenticated"):
        _assert_status(
            client.post(
                "/api/auth/login",
                json={"username": username, "password": password},
            ),
            200,
            "POST /api/auth/login",
        )
    return _assert_status(client.get("/api/auth/me"), 200, "GET /api/auth/me")


def login_via_api(
    client: httpx.Client,
    *,
    username: str = DEFAULT_ADMIN_USERNAME,
    password: str = DEFAULT_ADMIN_PASSWORD,
) -> dict[str, Any]:
    """POST /api/auth/login."""
    return _assert_status(
        client.post("/api/auth/login", json={"username": username, "password": password}),
        200,
        "POST /api/auth/login",
    )


def logout_via_api(client: httpx.Client) -> dict[str, Any]:
    """POST /api/auth/logout."""
    return _assert_status(client.post("/api/auth/logout"), 200, "POST /api/auth/logout")


def create_field_via_api(
    client: httpx.Client,
    *,
    label: str,
    scope: str,
    field_type: str,
    field_key: str | None = None,
    unit: str | None = None,
    options: list[str] | None = None,
    is_required: bool = False,
    sort_order: int = 0,
) -> dict[str, Any]:
    """POST /api/fields -> return created field object."""
    payload: dict[str, Any] = {
        "label": label,
        "scope": scope,
        "field_type": field_type,
        "is_required": is_required,
        "sort_order": sort_order,
    }
    if field_key is not None:
        payload["field_key"] = field_key
    if unit is not None:
        payload["unit"] = unit
    if options is not None:
        payload["options"] = options
    data = _assert_status(client.post("/api/fields", json=payload), 201, "POST /api/fields")
    return data["field"]


def create_player_via_api(
    client: httpx.Client,
    *,
    display_name: str,
    status: str = "active",
    joined_at: str | None = None,
    notes: str | None = None,
    profile_values: dict[str, Any] | None = None,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    """POST /api/players -> return created player object."""
    payload: dict[str, Any] = {
        "display_name": display_name,
        "status": status,
    }
    if joined_at is not None:
        payload["joined_at"] = joined_at
    if notes is not None:
        payload["notes"] = notes
    if profile_values is not None:
        payload["profile_values"] = profile_values
    if aliases is not None:
        payload["aliases"] = aliases
    data = _assert_status(client.post("/api/players", json=payload), 201, "POST /api/players")
    return data["player"]


def add_alias_via_api(client: httpx.Client, player_id: int, alias_name: str) -> dict[str, Any]:
    """POST /api/players/{player_id}/aliases -> return created alias object."""
    data = _assert_status(
        client.post(f"/api/players/{player_id}/aliases", json={"alias_name": alias_name}),
        201,
        f"POST /api/players/{player_id}/aliases",
    )
    return data["alias"]


def add_progression_via_api(
    client: httpx.Client,
    player_id: int,
    *,
    recorded_at: str,
    metrics: dict[str, Any],
    note: str | None = None,
) -> dict[str, Any]:
    """POST /api/players/{player_id}/progression -> return created progression entry."""
    payload: dict[str, Any] = {"recorded_at": recorded_at, "metrics": metrics}
    if note is not None:
        payload["note"] = note
    data = _assert_status(
        client.post(f"/api/players/{player_id}/progression", json=payload),
        201,
        f"POST /api/players/{player_id}/progression",
    )
    return data["entry"]


def create_duel_via_api(
    client: httpx.Client,
    *,
    opponent_clan_name: str,
    start_date: str,
    title: str | None = None,
    end_date: str | None = None,
    status: str = "ongoing",
    notes: str | None = None,
) -> dict[str, Any]:
    """POST /api/duels -> return created duel object."""
    payload: dict[str, Any] = {
        "opponent_clan_name": opponent_clan_name,
        "start_date": start_date,
        "status": status,
    }
    if title is not None:
        payload["title"] = title
    if end_date is not None:
        payload["end_date"] = end_date
    if notes is not None:
        payload["notes"] = notes
    data = _assert_status(client.post("/api/duels", json=payload), 201, "POST /api/duels")
    return data["duel"]


def add_manual_score_via_api(
    client: httpx.Client,
    duel_id: int,
    *,
    extracted_name: str,
    score: int,
    score_date: str,
    player_id: int | None = None,
) -> dict[str, Any]:
    """POST /api/duels/{duel_id}/scores -> return created duel score object."""
    payload: dict[str, Any] = {
        "extracted_name": extracted_name,
        "score": score,
        "score_date": score_date,
    }
    if player_id is not None:
        payload["player_id"] = player_id
    data = _assert_status(
        client.post(f"/api/duels/{duel_id}/scores", json=payload),
        201,
        f"POST /api/duels/{duel_id}/scores",
    )
    return data["score"]


def extract_screenshot_via_api(
    client: httpx.Client,
    duel_id: int,
    image_path: Path,
    *,
    score_date: str,
) -> dict[str, Any]:
    """POST /api/duels/{duel_id}/screenshots/extract with multipart image + score_date."""
    img_path = Path(image_path)
    mime_type, _ = mimetypes.guess_type(img_path.name)
    mime_type = mime_type or "application/octet-stream"
    resp = client.post(
        f"/api/duels/{duel_id}/screenshots/extract",
        files={"file": (img_path.name, img_path.read_bytes(), mime_type)},
        data={"score_date": score_date},
    )
    return _assert_status(resp, 201, f"POST /api/duels/{duel_id}/screenshots/extract")


def commit_screenshot_via_api(
    client: httpx.Client,
    duel_id: int,
    screenshot_id: int,
    *,
    score_date: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """POST /api/duels/{duel_id}/screenshots/{screenshot_id}/commit."""
    return _assert_status(
        client.post(
            f"/api/duels/{duel_id}/screenshots/{screenshot_id}/commit",
            json={"score_date": score_date, "rows": rows},
        ),
        201,
        f"POST /api/duels/{duel_id}/screenshots/{screenshot_id}/commit",
    )


def set_daily_limit_via_api(
    client: httpx.Client,
    min_score: int,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    """PUT /api/limits/daily."""
    payload: dict[str, Any] = {"minScore": min_score}
    if note is not None:
        payload["note"] = note
    return _assert_status(client.put("/api/limits/daily", json=payload), 200, "PUT /api/limits/daily")


def get_daily_limit_via_api(client: httpx.Client) -> dict[str, Any]:
    """GET /api/limits/daily."""
    return _assert_status(client.get("/api/limits/daily"), 200, "GET /api/limits/daily")


def evaluate_limits_via_api(
    client: httpx.Client,
    *,
    date: str | None = None,
    duel_id: int | None = None,
) -> dict[str, Any]:
    """GET /api/limits/evaluate."""
    params: dict[str, Any] = {}
    if date is not None:
        params["date"] = date
    if duel_id is not None:
        params["duelId"] = duel_id
    return _assert_status(
        client.get("/api/limits/evaluate", params=params),
        200,
        "GET /api/limits/evaluate",
    )


# ---------------------------------------------------------------------------
# Resilient Playwright UI helpers (semantic Turkish labels + DOM fallbacks)
# ---------------------------------------------------------------------------


def _compile_pattern(pattern: str | re.Pattern[str]) -> re.Pattern[str]:
    if isinstance(pattern, re.Pattern):
        return pattern
    return re.compile(pattern, re.I)


def _wait_first_visible(
    candidates: list[tuple[str, Locator]],
    *,
    timeout: int = 10_000,
) -> Locator:
    """Poll candidate locators until the first visible matching element is found."""
    deadline = time.monotonic() + (timeout / 1000.0)
    while True:
        for _, locator in candidates:
            try:
                count = locator.count()
                for idx in range(count):
                    candidate = locator.nth(idx)
                    if candidate.is_visible():
                        return candidate
            except Exception:
                pass
        if time.monotonic() >= deadline:
            tried = ", ".join(desc for desc, _ in candidates)
            raise AssertionError(
                f"No visible element matched within {timeout}ms. Tried strategies: [{tried}]"
            )
        time.sleep(0.05)


def locate_input_resilient(
    page: Page,
    *,
    label_patterns: list[str] | None = None,
    placeholder_patterns: list[str] | None = None,
    attr_names: list[str] | None = None,
    fallback_selectors: list[str] | None = None,
    timeout: int = 10_000,
) -> Locator:
    """Locate an input/textarea/select using label, placeholder, name/id, and container fallbacks."""
    candidates: list[tuple[str, Locator]] = []

    for pat in label_patterns or []:
        rx = _compile_pattern(pat)
        candidates.append((f"label:{pat}", page.get_by_label(rx)))

    for pat in placeholder_patterns or []:
        rx = _compile_pattern(pat)
        candidates.append((f"placeholder:{pat}", page.get_by_placeholder(rx)))

    for attr in attr_names or []:
        selector = (
            f'input[name="{attr}"], input[id="{attr}"], '
            f'textarea[name="{attr}"], select[name="{attr}"]'
        )
        candidates.append((f"attr:{attr}", page.locator(selector)))

    for pat in label_patterns or []:
        rx = _compile_pattern(pat)
        label_loc = page.locator("label", has_text=rx)
        candidates.append(
            (
                f"wrapped-label:{pat}",
                label_loc.locator("input, textarea, select"),
            )
        )
        candidates.append(
            (
                f"sibling-label:{pat}",
                label_loc.locator(
                    "xpath=following-sibling::*[self::input or self::textarea or self::select][1]"
                ),
            )
        )
        candidates.append(
            (
                f"container-label:{pat}",
                label_loc.locator("xpath=..").locator("input, textarea, select"),
            )
        )

    for sel in fallback_selectors or []:
        candidates.append((f"selector:{sel}", page.locator(sel)))

    return _wait_first_visible(candidates, timeout=timeout)


def fill_field_resilient(
    page: Page,
    value: str,
    *,
    label_patterns: list[str] | None = None,
    placeholder_patterns: list[str] | None = None,
    attr_names: list[str] | None = None,
    fallback_selectors: list[str] | None = None,
    timeout: int = 10_000,
) -> Locator:
    """Locate a field resiliently and fill it with value."""
    field = locate_input_resilient(
        page,
        label_patterns=label_patterns,
        placeholder_patterns=placeholder_patterns,
        attr_names=attr_names,
        fallback_selectors=fallback_selectors,
        timeout=timeout,
    )
    field.fill(value)
    return field


def click_button_resilient(
    page: Page,
    name_pattern: str | re.Pattern[str],
    *,
    fallback_submit: bool = False,
    timeout: int = 10_000,
) -> None:
    """Click a button matched by accessible Turkish name, optionally falling back to submit."""
    rx = _compile_pattern(name_pattern)
    candidates: list[tuple[str, Locator]] = [
        (f"role-button:{rx.pattern}", page.get_by_role("button", name=rx)),
    ]
    if fallback_submit:
        candidates.append(
            ("submit-fallback", page.locator('button[type="submit"], input[type="submit"]'))
        )
    btn = _wait_first_visible(candidates, timeout=timeout)
    btn.click()


def navigate_and_wait(
    page: Page,
    route: str,
    *,
    wait_for_text: str | re.Pattern[str] | None = None,
    timeout: int = 10_000,
) -> None:
    """Navigate to an SPA route and wait for visible rendered content.

    Note: Authenticated M5 routes mount ``<nav>`` and ``<main>`` synchronously before
    async ``fetch()`` calls finish populating ``#page-content``. Pass ``wait_for_text``
    when navigating to async M5 routes (or follow immediately with ``expect(...)`` /
    resilient locators) so assertions wait for fetched data to render.
    """
    page.goto(route, wait_until="load")
    page.locator("main:visible, nav:visible, form:visible, h1:visible, h2:visible").first.wait_for(
        state="visible", timeout=timeout
    )
    visible_loading = page.locator('.loading-screen:visible, [aria-busy="true"]:visible')
    if visible_loading.count() > 0:
        visible_loading.first.wait_for(state="hidden", timeout=timeout)
    if wait_for_text is not None:
        expect(page.get_by_text(wait_for_text).first).to_be_visible(timeout=timeout)


def click_nav_link(
    page: Page,
    label_pattern: str | re.Pattern[str],
    *,
    timeout: int = 10_000,
) -> None:
    """Click a navigation link or nav button by accessible label."""
    rx = _compile_pattern(label_pattern)
    candidates: list[tuple[str, Locator]] = [
        (f"nav-link:{rx.pattern}", page.get_by_role("link", name=rx)),
        (f"nav-button:{rx.pattern}", page.locator("nav").get_by_role("button", name=rx)),
    ]
    item = _wait_first_visible(candidates, timeout=timeout)
    item.click()


def setup_admin_via_ui(
    page: Page,
    *,
    username: str = DEFAULT_ADMIN_USERNAME,
    password: str = DEFAULT_ADMIN_PASSWORD,
    clan_name: str | None = DEFAULT_CLAN_NAME,
    wait_for_redirect: bool = True,
    timeout: int = 10_000,
) -> None:
    """Complete the initial /setup form through real browser interactions."""
    if not page.url.rstrip("/").endswith("/setup"):
        navigate_and_wait(page, "/setup", timeout=timeout)

    page.locator("form:visible, input:visible").first.wait_for(state="visible", timeout=timeout)

    if clan_name is not None:
        try:
            fill_field_resilient(
                page,
                clan_name,
                label_patterns=[r"klan\s*adı|clan"],
                placeholder_patterns=[r"klan"],
                attr_names=["clanName", "clan_name"],
                timeout=800,
            )
        except AssertionError:
            pass

    fill_field_resilient(
        page,
        username,
        label_patterns=[r"kullanıcı\s*adı|yönetici\s*adı|username"],
        placeholder_patterns=[r"kullanıcı|username|klanlideri"],
        attr_names=["username", "adminUsername"],
        timeout=timeout,
    )

    fill_field_resilient(
        page,
        password,
        label_patterns=[r"^(?:şifre|parola|password)\s*\*?$", r"yeni\s*şifre"],
        attr_names=["password"],
        fallback_selectors=['input[type="password"]'],
        timeout=timeout,
    )

    try:
        fill_field_resilient(
            page,
            password,
            label_patterns=[r"tekrar|doğrula|confirm"],
            placeholder_patterns=[r"tekrar|confirm"],
            attr_names=["confirmPassword", "confirm_password", "passwordConfirm"],
            timeout=500,
        )
    except AssertionError:
        pw_inputs = page.locator('input[type="password"]')
        if pw_inputs.count() >= 2 and pw_inputs.nth(1).is_visible():
            pw_inputs.nth(1).fill(password)

    click_button_resilient(
        page,
        r"kurulum|oluştur|kaydet|başla|tamamla|yönetici",
        fallback_submit=True,
        timeout=timeout,
    )

    if wait_for_redirect:
        expect(page).not_to_have_url(re.compile(r"/setup/?$"), timeout=timeout)


def login_via_ui(
    page: Page,
    *,
    username: str = DEFAULT_ADMIN_USERNAME,
    password: str = DEFAULT_ADMIN_PASSWORD,
    wait_for_redirect: bool = True,
    timeout: int = 10_000,
) -> None:
    """Log in through the /login UI form."""
    if not page.url.rstrip("/").endswith("/login"):
        navigate_and_wait(page, "/login", timeout=timeout)

    page.locator("form:visible, input:visible").first.wait_for(state="visible", timeout=timeout)

    fill_field_resilient(
        page,
        username,
        label_patterns=[r"kullanıcı\s*adı|yönetici\s*adı|username"],
        placeholder_patterns=[r"kullanıcı|username"],
        attr_names=["username"],
        timeout=timeout,
    )
    fill_field_resilient(
        page,
        password,
        label_patterns=[r"^(?:şifre|parola|password)\s*\*?$"],
        attr_names=["password"],
        fallback_selectors=['input[type="password"]'],
        timeout=timeout,
    )

    click_button_resilient(page, r"giriş|oturum|login", fallback_submit=True, timeout=timeout)

    if wait_for_redirect:
        expect(page).not_to_have_url(re.compile(r"/login/?$"), timeout=timeout)


def logout_via_ui(page: Page, *, timeout: int = 10_000) -> None:
    """Click the Turkish logout control and verify redirect to /login."""
    rx = re.compile(r"çıkış|oturumu\s*kapat|logout", re.I)
    control = _wait_first_visible(
        [
            ("role-button-logout", page.get_by_role("button", name=rx)),
            ("role-link-logout", page.get_by_role("link", name=rx)),
        ],
        timeout=timeout,
    )
    control.click()
    expect(page).to_have_url(re.compile(r"/login/?$"), timeout=timeout)


def authenticate_browser_via_api(
    page: Page,
    *,
    base_url: str | None = None,
    username: str = DEFAULT_ADMIN_USERNAME,
    password: str = DEFAULT_ADMIN_PASSWORD,
    clan_name: str = DEFAULT_CLAN_NAME,
    timeout: int = 10_000,
) -> dict[str, Any]:
    """Authenticate BrowserContext cookie jar via Playwright APIRequestContext and load /."""

    def _url(path: str) -> str:
        if base_url:
            return f"{base_url.rstrip('/')}{path}"
        return path

    status_resp = page.request.get(_url("/api/auth/status"))
    if status_resp.status != 200:
        raise AssertionError(
            f"GET /api/auth/status returned {status_resp.status}: {status_resp.text()}"
        )
    status_data = status_resp.json()

    if status_data.get("needsSetup"):
        setup_resp = page.request.post(
            _url("/api/auth/setup"),
            data={"username": username, "password": password, "clanName": clan_name},
        )
        if setup_resp.status != 201:
            raise AssertionError(
                f"POST /api/auth/setup returned {setup_resp.status}: {setup_resp.text()}"
            )
    elif not status_data.get("authenticated"):
        login_resp = page.request.post(
            _url("/api/auth/login"),
            data={"username": username, "password": password},
        )
        if login_resp.status != 200:
            raise AssertionError(
                f"POST /api/auth/login returned {login_resp.status}: {login_resp.text()}"
            )

    me_resp = page.request.get(_url("/api/auth/me"))
    if me_resp.status != 200:
        raise AssertionError(f"GET /api/auth/me returned {me_resp.status}: {me_resp.text()}")

    page.goto(_url("/"), wait_until="load")
    page.locator("main:visible, nav:visible, h1:visible").first.wait_for(
        state="visible", timeout=timeout
    )
    expect(page).not_to_have_url(re.compile(r"/(?:login|setup)/?$"), timeout=timeout)
    return me_resp.json()
