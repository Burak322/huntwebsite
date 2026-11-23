from __future__ import annotations

import sqlite3

from fastapi import Depends, HTTPException, Request, Response, status

from app.config import Settings
from app.db.connection import get_db
from app.services import auth_service
from app.services.auth_service import AuthenticatedSession

SESSION_COOKIE_NAME = "clan_session"


def _cookie_name_for(request: Request) -> str:
    settings: Settings | None = getattr(request.app.state, "settings", None)
    return settings.cookie_name if settings is not None else SESSION_COOKIE_NAME


def try_get_current_admin(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> AuthenticatedSession | None:
    cached = getattr(request.state, "auth_session", None)
    if cached is not None:
        return cached

    raw_token = request.cookies.get(_cookie_name_for(request))
    session = auth_service.authenticate_session(db, raw_token)
    if session is not None:
        request.state.auth_session = session
    return session


def require_admin(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> AuthenticatedSession:
    session = try_get_current_admin(request, db)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturum geçersiz veya süresi dolmuş.",
        )
    return session


def set_session_cookie(response: Response, raw_token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=raw_token,
        httponly=True,
        samesite="lax",
        path="/",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_hours * 3600,
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.cookie_name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
