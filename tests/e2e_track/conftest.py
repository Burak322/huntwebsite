"""Pytest fixtures and live Uvicorn/Playwright harness for opaque-box E2E tests."""

from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

import httpx
import pytest
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from tests.e2e_track.helpers.ui_helpers import authenticate_browser_via_api

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def pytest_configure(config: pytest.Config) -> None:
    """Register E2E markers additively without touching root pyproject.toml."""
    for spec in (
        "harness: E2E harness smoke and infrastructure checks",
        "tier1: Category-partition E2E feature coverage tests",
        "tier2: Boundary and corner-case E2E tests",
        "tier3: Pairwise cross-feature combination E2E tests",
        "tier4: Real-world scenario and restart persistence E2E tests",
    ):
        config.addinivalue_line("markers", spec)


def _resolve_python() -> str:
    """Resolve the project virtualenv Python interpreter when present."""
    if sys.platform == "win32":
        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return str(venv_python)
    return sys.executable


def _find_free_port() -> int:
    """Bind an ephemeral loopback port and return its port number."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _is_port_listening(port: int) -> bool:
    """Return True if 127.0.0.1:port accepts a TCP connection."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _collect_win32_descendant_pids(root_pid: int) -> list[int]:
    """Return all living descendant PIDs of root_pid on Windows."""
    from ctypes import wintypes

    class _ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    th32cs_snapprocess = 0x00000002
    invalid_handle = ctypes.c_void_p(-1).value
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snap = kernel32.CreateToolhelp32Snapshot(th32cs_snapprocess, 0)
    if snap == invalid_handle or snap is None:
        return []

    children_by_parent: dict[int, list[int]] = {}
    try:
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
        if kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                children_by_parent.setdefault(int(entry.th32ParentProcessID), []).append(
                    int(entry.th32ProcessID)
                )
                if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snap)

    descendants: list[int] = []
    stack = list(children_by_parent.get(root_pid, []))
    seen: set[int] = {root_pid}
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        descendants.append(pid)
        stack.extend(children_by_parent.get(pid, []))
    return descendants


def _terminate_win32_process_tree(proc: subprocess.Popen[Any], timeout: float = 5.0) -> None:
    """Synchronously kill proc and its entire Windows descendant tree and wait for exit."""
    from ctypes import wintypes

    synchronize = 0x00100000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    descendant_pids = _collect_win32_descendant_pids(proc.pid)
    descendant_handles: list[tuple[int, Any]] = []
    for pid in descendant_pids:
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if handle:
            descendant_handles.append((pid, handle))

    try:
        if proc.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

        for pid, handle in descendant_handles:
            if kernel32.WaitForSingleObject(handle, 0) != 0:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )

        if proc.poll() is None:
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=timeout)
        else:
            proc.wait(timeout=timeout)

        wait_ms = max(1, int(timeout * 1000))
        for _, handle in descendant_handles:
            kernel32.WaitForSingleObject(handle, wait_ms)
    finally:
        for _, handle in descendant_handles:
            kernel32.CloseHandle(handle)


class ServerHandle:
    """Manages an isolated single-worker Uvicorn subprocess for E2E tests."""

    def __init__(
        self,
        *,
        project_root: Path,
        db_path: Path,
        upload_dir: Path,
        log_path: Path,
        env: dict[str, str],
        scrub_admin_env: bool = True,
    ) -> None:
        self.project_root = project_root
        self.db_path = db_path
        self.upload_dir = upload_dir
        self.log_path = log_path
        self.env = dict(env)
        if scrub_admin_env:
            self.env.pop("CLAN_ADMIN_USERNAME", None)
            self.env.pop("CLAN_ADMIN_PASSWORD", None)
        self.port: int = 0
        self._proc: subprocess.Popen[bytes] | None = None
        self._log_fh: Any = None

    @property
    def base_url(self) -> str:
        """Return the base HTTP URL of the live server."""
        if not self.port:
            raise RuntimeError("ServerHandle has not been started yet")
        return f"http://127.0.0.1:{self.port}"

    def read_logs(self) -> str:
        """Read accumulated Uvicorn log output safely."""
        if not self.log_path.exists():
            return ""
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def _close_log_handle(self) -> None:
        if self._log_fh is not None:
            try:
                self._log_fh.flush()
            except Exception:
                pass
            try:
                self._log_fh.close()
            finally:
                self._log_fh = None

    def start(self, preferred_port: int | None = None, timeout: float = 25.0) -> str:
        """Start Uvicorn and wait until GET /api/health confirms DB connectivity."""
        if self._proc is not None and self._proc.poll() is None:
            return self.base_url

        max_attempts = 3
        last_error: str = ""

        for attempt in range(1, max_attempts + 1):
            port = (
                preferred_port
                if (attempt == 1 and preferred_port is not None and not _is_port_listening(preferred_port))
                else _find_free_port()
            )
            self.port = port

            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_fh = open(self.log_path, "a", encoding="utf-8", errors="replace", buffering=1)
            try:
                self._log_fh.write(
                    f"\n=== E2E Uvicorn launch attempt {attempt} on 127.0.0.1:{port} ===\n"
                )
                self._log_fh.flush()

                cmd = [
                    _resolve_python(),
                    "-m",
                    "uvicorn",
                    "app.main:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                ]
                popen_kwargs: dict[str, Any] = {
                    "cwd": str(self.project_root),
                    "env": self.env,
                    "stdin": subprocess.DEVNULL,
                    "stdout": self._log_fh,
                    "stderr": subprocess.STDOUT,
                }
                if sys.platform == "win32":
                    popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

                self._proc = subprocess.Popen(cmd, **popen_kwargs)
            except Exception:
                self._close_log_handle()
                raise

            deadline = time.monotonic() + timeout
            health_url = f"http://127.0.0.1:{port}/api/health"
            bind_conflict = False

            while time.monotonic() < deadline:
                exit_code = self._proc.poll()
                if exit_code is not None:
                    self._close_log_handle()
                    logs = self.read_logs()
                    lower_logs = logs.lower()
                    if (
                        "10048" in lower_logs
                        or "address already in use" in lower_logs
                        or "error while attempting to bind" in lower_logs
                    ):
                        bind_conflict = True
                        last_error = f"Port {port} bind conflict on attempt {attempt}"
                        break
                    tail = "\n".join(logs.splitlines()[-80:])
                    raise RuntimeError(
                        f"Uvicorn exited early with code {exit_code} before becoming healthy.\n"
                        f"Last logs:\n{tail}"
                    )

                try:
                    resp = httpx.get(health_url, timeout=1.0)
                    if resp.status_code == 200 and resp.json() == {"ok": True, "db": "connected"}:
                        return self.base_url
                except (httpx.HTTPError, ValueError):
                    pass

                time.sleep(0.1)

            if bind_conflict:
                self._proc = None
                continue

            self.stop()
            tail = "\n".join(self.read_logs().splitlines()[-80:])
            raise RuntimeError(
                f"Timed out after {timeout}s waiting for {health_url}.\nLast logs:\n{tail}"
            )

        raise RuntimeError(f"Failed to bind Uvicorn after {max_attempts} attempts: {last_error}")

    def stop(self) -> None:
        """Terminate Uvicorn cleanly and release all log file handles."""
        proc = self._proc
        self._proc = None
        try:
            if proc is not None:
                if sys.platform == "win32":
                    _terminate_win32_process_tree(proc, timeout=5.0)
                elif proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5.0)
        finally:
            self._close_log_handle()

    def restart(self, timeout: float = 25.0) -> str:
        """Stop Uvicorn and restart it against the exact same DB and upload directory."""
        previous_port = self.port or None
        self.stop()
        if previous_port is not None:
            wait_deadline = time.monotonic() + 2.0
            while time.monotonic() < wait_deadline and _is_port_listening(previous_port):
                time.sleep(0.05)
        return self.start(preferred_port=previous_port, timeout=timeout)


@pytest.fixture
def e2e_env(tmp_path: Path) -> dict[str, Any]:
    """Provide isolated SQLite DB, upload dir, log file, and sanitized child env."""
    db_path = tmp_path / "clan.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / "uvicorn.log"

    env = os.environ.copy()
    for key in (
        "CLAN_ADMIN_USERNAME",
        "CLAN_ADMIN_PASSWORD",
        "CLAN_COOKIE_SECURE",
        "CLAN_STATIC_DIR",
        "CLAN_SESSION_TTL_HOURS",
        "CLAN_MAX_UPLOAD_BYTES",
    ):
        env.pop(key, None)
    env["CLAN_DB_PATH"] = str(db_path)
    env["CLAN_UPLOAD_DIR"] = str(upload_dir)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    return {
        "db_path": db_path,
        "upload_dir": upload_dir,
        "log_path": log_path,
        "env": env,
    }


@pytest.fixture
def live_server(e2e_env: dict[str, Any]) -> Generator[ServerHandle, None, None]:
    """Start an isolated single-worker Uvicorn server for the current test."""
    handle = ServerHandle(
        project_root=PROJECT_ROOT,
        db_path=e2e_env["db_path"],
        upload_dir=e2e_env["upload_dir"],
        log_path=e2e_env["log_path"],
        env=e2e_env["env"],
    )
    try:
        handle.start()
        yield handle
    finally:
        handle.stop()


@pytest.fixture(scope="session")
def playwright_instance() -> Generator[Playwright, None, None]:
    """Start a session-scoped Playwright instance without depending on live_server."""
    pw = sync_playwright().start()
    try:
        yield pw
    finally:
        pw.stop()


@pytest.fixture(scope="session")
def browser(playwright_instance: Playwright) -> Generator[Browser, None, None]:
    """Launch headless Chrome, falling back to Edge if Chrome is unavailable."""
    last_err: Exception | None = None
    for channel in ("chrome", "msedge"):
        try:
            launched = playwright_instance.chromium.launch(channel=channel, headless=True)
        except Exception as exc:  # pragma: no cover - fallback path depends on host browsers
            last_err = exc
            continue
        try:
            yield launched
        finally:
            launched.close()
        return
    raise RuntimeError(f"Could not launch headless Chrome or Edge: {last_err}") from last_err


@pytest.fixture
def context(browser: Browser, live_server: ServerHandle) -> Generator[BrowserContext, None, None]:
    """Provide an isolated BrowserContext bound to live_server.base_url."""
    ctx = browser.new_context(
        base_url=live_server.base_url,
        viewport={"width": 1440, "height": 900},
        locale="tr-TR",
    )
    ctx.set_default_timeout(10_000)
    try:
        yield ctx
    finally:
        ctx.close()


@pytest.fixture
def page(context: BrowserContext) -> Generator[Page, None, None]:
    """Provide a fresh Playwright Page with a 10s default timeout."""
    pg = context.new_page()
    pg.set_default_timeout(10_000)
    try:
        yield pg
    finally:
        pg.close()


@pytest.fixture
def authed_page(page: Page, live_server: ServerHandle) -> Page:
    """Perform one-time admin setup/login via API and leave browser authenticated on /."""
    authenticate_browser_via_api(page, base_url=live_server.base_url)
    return page


@pytest.fixture
def api_client(live_server: ServerHandle) -> Generator[httpx.Client, None, None]:
    """Provide an httpx.Client configured for the isolated live_server."""
    with httpx.Client(base_url=live_server.base_url, timeout=15.0) as client:
        yield client
