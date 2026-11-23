from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import clear_session_cookie, require_admin, set_session_cookie
from app.config import Settings
from app.db.connection import get_db
from app.services import auth_service
from app.services.auth_service import (
    AdminAlreadyExistsError,
    AuthenticatedSession,
    InvalidCredentialsError,
    ValidationError,
)

router = APIRouter(prefix="/api", tags=["auth"])


class SetupRequest(BaseModel):
    username: str
    password: str
    clanName: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str


class UpdateClanRequest(BaseModel):
    clanName: str = Field(..., min_length=1, max_length=80)


@router.get("/auth/status")
def auth_status(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    settings: Settings = request.app.state.settings
    raw_token = request.cookies.get(settings.cookie_name)
    return auth_service.get_auth_status(db, raw_token)


@router.post("/auth/setup", status_code=status.HTTP_201_CREATED)
def auth_setup(
    payload: SetupRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    try:
        admin, clan_name, raw_token = auth_service.setup_initial_admin(
            db,
            username=payload.username,
            password=payload.password,
            clan_name=payload.clanName,
            ttl_hours=settings.session_ttl_hours,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except AdminAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Yönetici hesabı zaten oluşturulmuş.",
        ) from exc

    response = JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "admin": {"id": admin.id, "username": admin.username},
            "clanName": clan_name,
        },
    )
    set_session_cookie(response, raw_token, settings)
    return response


@router.post("/auth/login")
def auth_login(
    payload: LoginRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    try:
        admin, clan_name, raw_token = auth_service.login_admin(
            db,
            username=payload.username,
            password=payload.password,
            ttl_hours=settings.session_ttl_hours,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı adı veya şifre hatalı.",
        ) from exc

    response = JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "admin": {"id": admin.id, "username": admin.username},
            "clanName": clan_name,
        },
    )
    set_session_cookie(response, raw_token, settings)
    return response


@router.post("/auth/logout")
def auth_logout(
    request: Request,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    auth_service.logout_session(db, session.token_hash)
    response = JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})
    clear_session_cookie(response, settings)
    return response


@router.get("/auth/me")
def auth_me(
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    clan_name = auth_service.get_clan_name(db)
    return {
        "admin": {"id": session.admin.id, "username": session.admin.username},
        "clanName": clan_name,
    }


@router.post("/auth/change-password")
def auth_change_password(
    payload: ChangePasswordRequest,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    try:
        auth_service.change_password(
            db,
            admin_id=session.admin.id,
            current_password=payload.currentPassword,
            new_password=payload.newPassword,
            current_token_hash=session.token_hash,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mevcut şifre hatalı.",
        ) from exc

    return {"ok": True, "message": "Şifre başarıyla güncellendi."}


@router.put("/settings/clan")
def update_clan_settings(
    payload: UpdateClanRequest,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    _ = session
    try:
        updated = auth_service.update_clan_name(db, payload.clanName)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return {"clanName": updated}
