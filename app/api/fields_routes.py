from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, StrictInt

from app.api.deps import require_admin
from app.db.connection import get_db
from app.services import field_validator
from app.services.auth_service import AuthenticatedSession
from app.services.field_validator import (
    FieldConflictError,
    FieldNotFoundError,
    FieldValidationError,
)

router = APIRouter(
    prefix="/api",
    tags=["fields"],
    dependencies=[Depends(require_admin)],
)


class CreateFieldRequest(BaseModel):
    label: str
    field_key: str | None = None
    scope: Literal["profile", "progression"]
    field_type: Literal["text", "number", "boolean", "select", "date"]
    unit: str | None = None
    options: list[str] | None = None
    is_required: bool = False
    is_active: bool = True
    sort_order: StrictInt = 0


class UpdateFieldRequest(BaseModel):
    field_key: str | None = None
    scope: str | None = None
    field_type: str | None = None
    label: str | None = None
    unit: str | None = None
    options: list[str] | None = None
    is_required: bool | None = None
    is_active: bool | None = None
    sort_order: Any = None


@router.get("/fields")
def list_fields(
    scope: Literal["profile", "progression"] | None = Query(default=None),
    activeOnly: bool = Query(default=False),
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _ = session
    try:
        fields = field_validator.list_tracking_fields(
            db,
            scope=scope,
            active_only=activeOnly,
        )
    except FieldValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return {"fields": fields}


@router.post("/fields", status_code=status.HTTP_201_CREATED)
def create_field(
    payload: CreateFieldRequest,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _ = session
    try:
        field = field_validator.create_tracking_field(
            db,
            label=payload.label,
            field_key=payload.field_key,
            scope=payload.scope,
            field_type=payload.field_type,
            unit=payload.unit,
            options=payload.options,
            is_required=payload.is_required,
            is_active=payload.is_active,
            sort_order=payload.sort_order,
        )
    except FieldValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except FieldConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return {"field": field}


@router.patch("/fields/{field_id}")
def update_field(
    field_id: int,
    payload: UpdateFieldRequest,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _ = session
    try:
        field = field_validator.update_tracking_field(
            db,
            field_id,
            set(payload.model_fields_set),
            field_key=payload.field_key,
            scope=payload.scope,
            field_type=payload.field_type,
            label=payload.label,
            unit=payload.unit,
            options=payload.options,
            is_required=payload.is_required,
            is_active=payload.is_active,
            sort_order=payload.sort_order,
        )
    except FieldNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except FieldValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return {"field": field}


@router.delete("/fields/{field_id}")
def delete_field(
    field_id: int,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, bool]:
    _ = session
    try:
        return field_validator.delete_tracking_field(db, field_id)
    except FieldNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
