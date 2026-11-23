from __future__ import annotations

import re
import sqlite3
from typing import Any

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.auth_routes import router as auth_router
from app.api.deps import try_get_current_admin
from app.api.duels_routes import router as duels_router
from app.api.fields_routes import router as fields_router
from app.api.players_routes import router as players_router
from app.config import Settings
from app.db.connection import get_connection, get_db
from app.db.migrations import run_migrations
from app.services import auth_service

PUBLIC_API_PATHS = frozenset(
    {
        "/api/health",
        "/api/auth/status",
        "/api/auth/setup",
        "/api/auth/login",
    }
)


def initialize_app_storage(settings: Settings) -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    with get_connection(settings.db_path) as conn:
        run_migrations(conn, settings=settings)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings if settings is not None else Settings.from_env()
    initialize_app_storage(resolved_settings)

    app = FastAPI(title="Klan Yönetim Sistemi", version="0.1.0")
    app.state.settings = resolved_settings

    @app.middleware("http")
    async def api_auth_guard(request: Request, call_next):
        raw_path = request.url.path
        collapsed_path = re.sub(r"/+", "/", raw_path)
        normalized_path = collapsed_path.rstrip("/") or "/"
        if normalized_path == "/api" or normalized_path.startswith("/api/"):
            if normalized_path not in PUBLIC_API_PATHS:
                raw_token = request.cookies.get(resolved_settings.cookie_name)
                with get_connection(resolved_settings.db_path) as conn:
                    session = auth_service.authenticate_session(conn, raw_token)
                if session is None:
                    return JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={"detail": "Yetkisiz erişim. Lütfen giriş yapın."},
                    )
                request.state.auth_session = session
            if raw_path != normalized_path:
                request.scope["path"] = normalized_path
                if "raw_path" in request.scope:
                    request.scope["raw_path"] = normalized_path.encode("latin-1")
        return await call_next(request)

    @app.get("/api/health", tags=["health"])
    def health_check(db: sqlite3.Connection = Depends(get_db)) -> JSONResponse:
        try:
            row = db.execute("SELECT 1 AS ok").fetchone()
            if row is None or row["ok"] != 1:
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={"ok": False, "db": "error"},
                )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"ok": True, "db": "connected"},
            )
        except sqlite3.Error:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"ok": False, "db": "error"},
            )

    app.include_router(auth_router)
    app.include_router(fields_router)
    app.include_router(players_router)
    app.include_router(duels_router)

    @app.api_route(
        "/api",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        include_in_schema=False,
    )
    @app.api_route(
        "/api/{rest:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        include_in_schema=False,
    )
    def api_fallback(
        request: Request,
        rest: str = "",
        db: sqlite3.Connection = Depends(get_db),
    ) -> JSONResponse:
        _ = rest
        if try_get_current_admin(request, db) is None:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Yetkisiz erişim. Lütfen giriş yapın."},
            )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "API uç noktası bulunamadı."},
        )

    static_dir = resolved_settings.static_dir
    for mount_path, subdir in (
        ("/css", static_dir / "css"),
        ("/js", static_dir / "js"),
        ("/static", static_dir),
    ):
        if subdir.is_dir():
            app.mount(
                mount_path,
                StaticFiles(directory=str(subdir)),
                name=f"static-{mount_path.strip('/')}",
            )

    static_root_resolved = static_dir.resolve()
    index_file = static_dir / "index.html"

    def _serve_spa() -> FileResponse | HTMLResponse:
        if index_file.is_file():
            return FileResponse(
                path=str(index_file),
                media_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        return HTMLResponse(
            content="<!doctype html><html lang='tr'><body>Klan Yönetim Sistemi</body></html>",
            status_code=status.HTTP_200_OK,
            headers={"Cache-Control": "no-store"},
        )

    def _handle_ui_route(
        request: Request,
        db: sqlite3.Connection,
    ) -> Response:
        path = request.url.path.rstrip("/") or "/"
        raw_token = request.cookies.get(resolved_settings.cookie_name)
        auth_state = auth_service.get_auth_status(db, raw_token)

        if auth_state["needsSetup"]:
            if path != "/setup":
                return RedirectResponse(url="/setup", status_code=status.HTTP_302_FOUND)
        elif not auth_state["authenticated"]:
            if path != "/login":
                return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        else:
            if path in {"/setup", "/login"}:
                return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

        return _serve_spa()

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/", include_in_schema=False)
    @app.get("/setup", include_in_schema=False)
    @app.get("/login", include_in_schema=False)
    @app.get("/players", include_in_schema=False)
    @app.get("/players/{rest:path}", include_in_schema=False)
    @app.get("/duels", include_in_schema=False)
    @app.get("/duels/{rest:path}", include_in_schema=False)
    @app.get("/settings", include_in_schema=False)
    def spa_ui_routes(
        request: Request,
        rest: str = "",
        db: sqlite3.Connection = Depends(get_db),
    ) -> Response:
        _ = rest
        return _handle_ui_route(request, db)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(
        full_path: str,
        request: Request,
        db: sqlite3.Connection = Depends(get_db),
    ) -> Response:
        normalized = full_path.lstrip("/")
        if normalized == "api" or normalized.startswith("api/"):
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"detail": "API uç noktası bulunamadı."},
            )
        if normalized.startswith(("css/", "js/", "static/")):
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"detail": "Statik dosya bulunamadı."},
            )

        if static_dir.is_dir() and normalized:
            candidate = (static_dir / normalized).resolve()
            if candidate.is_relative_to(static_root_resolved) and candidate.is_file():
                return FileResponse(path=str(candidate))

        return _handle_ui_route(request, db)

    return app


_default_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    global _default_app
    if name == "app":
        if _default_app is None:
            _default_app = create_app()
        return _default_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=8000)
