from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api.deps import require_admin
from app.db.connection import get_db
from app.repositories import players_repo, progression_repo
from app.repositories.players_repo import (
    AliasNotFoundError,
    PlayerConflictError,
    PlayerNotFoundError,
    PlayerValidationError,
)
from app.repositories.progression_repo import (
    ProgressionNotFoundError,
    ProgressionValidationError,
)
from app.services import field_validator
from app.services.auth_service import AuthenticatedSession
from app.services.field_validator import FieldValidationError
from app.services.player_matcher import RosterCandidate

router = APIRouter(
    prefix="/api",
    tags=["players"],
    dependencies=[Depends(require_admin)],
)


class PlayerCreateRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    status: Literal["active", "inactive", "left"] = "active"
    clan_rank: str | None = None
    tower_level: str | None = None
    joined_at: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    profile_values: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)


class PlayerUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    status: Literal["active", "inactive", "left"] | None = None
    clan_rank: str | None = None
    tower_level: str | None = None
    joined_at: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    profile_values: dict[str, Any] | None = None


class AliasCreateRequest(BaseModel):
    alias_name: str = Field(..., min_length=1, max_length=100)


class ProgressionCreateRequest(BaseModel):
    recorded_at: str = Field(..., min_length=1, max_length=64)
    metrics: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=2000)


class ProgressionUpdateRequest(BaseModel):
    recorded_at: str | None = Field(default=None, min_length=1, max_length=64)
    metrics: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=2000)


class BulkImportPlayerItem(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    status: Literal["active", "inactive", "left"] = "active"
    clan_rank: str | None = None
    tower_level: str | None = None
    joined_at: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    profile_values: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    initial_metrics: dict[str, Any] | None = None


class BulkImportPlayersRequest(BaseModel):
    players: list[BulkImportPlayerItem] = Field(..., min_length=1, max_length=200)
    skip_existing: bool = True
    recorded_at: str | None = None


def _build_roster(db: sqlite3.Connection) -> list[RosterCandidate]:
    return [
        RosterCandidate(
            id=int(p["id"]),
            display_name=str(p["display_name"]),
            aliases=[str(a["alias_name"]) for a in p.get("aliases", [])],
        )
        for p in players_repo.list_players(db)
    ]


@router.get("/players")
def list_players(
    search: str = Query(default=""),
    player_status: str | None = Query(default=None, alias="status"),
    clan_rank: str | None = Query(default=None),
    tower_level: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _ = session
    try:
        players = players_repo.list_players(
            db,
            search=search,
            status=player_status,
            clan_rank=clan_rank,
            tower_level=tower_level,
            sort=sort,
        )
    except PlayerValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return {"players": players}


@router.post("/players", status_code=status.HTTP_201_CREATED)
def create_player(
    payload: PlayerCreateRequest,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _ = session
    try:
        player = players_repo.create_player(
            db,
            display_name=payload.display_name,
            status=payload.status,
            clan_rank=payload.clan_rank,
            tower_level=payload.tower_level,
            joined_at=payload.joined_at,
            notes=payload.notes,
            profile_values=payload.profile_values,
            aliases=payload.aliases,
        )
    except (PlayerValidationError, FieldValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except PlayerConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return {"player": player}


@router.post("/players/import-ocr")
async def import_players_ocr(
    request: Request,
    file: UploadFile = File(...),
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    from app.services.ocr_service import OcrError, extract_players_from_image

    _ = session
    settings = request.app.state.settings
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail="Dosya çok büyük (en fazla 15 MB).",
        )

    roster = _build_roster(db)
    try:
        result = await run_in_threadpool(
            extract_players_from_image,
            data,
            roster,
            max_bytes=settings.max_upload_bytes,
        )
    except OcrError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return result.to_api_dict()


@router.post("/players/import-bulk", status_code=status.HTTP_201_CREATED)
def import_players_bulk(
    payload: BulkImportPlayersRequest,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _ = session
    try:
        clean_recorded_at = (
            progression_repo.validate_recorded_at(payload.recorded_at)
            if payload.recorded_at is not None
            else None
        )
    except ProgressionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    profile_fields = field_validator.list_tracking_fields(
        db, scope="profile", active_only=False
    )
    prog_fields = field_validator.list_tracking_fields(
        db, scope="progression", active_only=False
    )

    seen_names: set[str] = set()
    validated_items: list[dict[str, Any]] = []
    for idx, item in enumerate(payload.players, start=1):
        try:
            clean_name = players_repo._validate_display_name(item.display_name)
            folded_name = players_repo._fold_tr(clean_name)
            if folded_name in seen_names:
                raise PlayerValidationError("Aynı oyuncu adı listede birden fazla kez yer alıyor.")
            seen_names.add(folded_name)

            clean_status = players_repo._validate_status(item.status)
            clean_rank = players_repo._validate_clan_rank(item.clan_rank)
            clean_tower = players_repo._validate_tower_level(item.tower_level)
            clean_joined_at = players_repo._validate_joined_at(item.joined_at)
            clean_notes = players_repo._validate_notes(item.notes)
            clean_profile = field_validator.validate_field_values(
                profile_fields, item.profile_values, partial=False
            )

            clean_aliases: list[str] = []
            seen_aliases: set[str] = set()
            for raw_alias in item.aliases:
                clean_alias = players_repo._validate_alias_name(raw_alias)
                folded_alias = players_repo._fold_tr(clean_alias)
                if folded_alias == folded_name or folded_alias in seen_aliases:
                    continue
                seen_aliases.add(folded_alias)
                clean_aliases.append(clean_alias)

            clean_metrics: dict[str, Any] | None = None
            if item.initial_metrics:
                clean_metrics = field_validator.validate_field_values(
                    prog_fields, item.initial_metrics, partial=False
                )
        except (PlayerValidationError, FieldValidationError) as exc:
            label = item.display_name.strip() or "?"
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{idx}. satır ({label}): {exc}",
            ) from exc

        if not payload.skip_existing:
            try:
                players_repo._check_display_name_unique(db, clean_name)
                for alias in clean_aliases:
                    players_repo._check_alias_unique(db, alias)
            except PlayerConflictError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"{idx}. satır ({clean_name}): {exc}",
                ) from exc

        validated_items.append(
            {
                "display_name": clean_name,
                "status": clean_status,
                "clan_rank": clean_rank,
                "tower_level": clean_tower,
                "joined_at": clean_joined_at,
                "notes": clean_notes,
                "profile_values": clean_profile,
                "aliases": clean_aliases,
                "initial_metrics": clean_metrics,
            }
        )

    created_players: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for item_data in validated_items:
        try:
            player = players_repo.create_player(
                db,
                display_name=item_data["display_name"],
                status=item_data["status"],
                clan_rank=item_data["clan_rank"],
                tower_level=item_data["tower_level"],
                joined_at=item_data["joined_at"],
                notes=item_data["notes"],
                profile_values=item_data["profile_values"],
                aliases=item_data["aliases"],
            )
        except PlayerConflictError as exc:
            if payload.skip_existing:
                skipped.append({"display_name": item_data["display_name"], "reason": str(exc)})
                continue
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except (PlayerValidationError, FieldValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

        metrics = item_data["initial_metrics"]
        if metrics:
            entry = progression_repo.create_progression_entry(
                db,
                int(player["id"]),
                recorded_at=clean_recorded_at or item_data["joined_at"] or date.today().isoformat(),
                metrics=metrics,
                note="Fotoğraftan ilk kayıt",
            )
            player = {**player, "latestProgression": entry}

        created_players.append(player)

    return {
        "createdPlayers": created_players,
        "skipped": skipped,
        "createdCount": len(created_players),
        "skippedCount": len(skipped),
    }


@router.get("/players/{player_id}")
def get_player_detail(
    player_id: int,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _ = session
    try:
        return players_repo.get_player_detail(db, player_id)
    except (PlayerNotFoundError, ProgressionNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.patch("/players/{player_id}")
def update_player(
    player_id: int,
    payload: PlayerUpdateRequest,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _ = session
    try:
        player = players_repo.update_player(
            db,
            player_id,
            set(payload.model_fields_set),
            display_name=payload.display_name,
            status=payload.status,
            clan_rank=payload.clan_rank,
            tower_level=payload.tower_level,
            joined_at=payload.joined_at,
            notes=payload.notes,
            profile_values=payload.profile_values,
        )
    except PlayerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PlayerConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (PlayerValidationError, FieldValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return {"player": player}


@router.delete("/players/{player_id}")
def delete_player(
    player_id: int,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, bool]:
    _ = session
    try:
        players_repo.delete_player(db, player_id)
    except PlayerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return {"deleted": True}


@router.post("/players/{player_id}/aliases", status_code=status.HTTP_201_CREATED)
def add_player_alias(
    player_id: int,
    payload: AliasCreateRequest,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _ = session
    try:
        alias = players_repo.add_alias(db, player_id, payload.alias_name)
    except PlayerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PlayerConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except PlayerValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return {"alias": alias}


@router.delete("/players/{player_id}/aliases/{alias_id}")
def delete_player_alias(
    player_id: int,
    alias_id: int,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, bool]:
    _ = session
    try:
        players_repo.delete_alias(db, player_id, alias_id)
    except AliasNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return {"deleted": True}


@router.get("/players/{player_id}/progression")
def list_player_progression(
    player_id: int,
    order: Literal["asc", "desc"] = Query(default="desc"),
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _ = session
    try:
        entries = progression_repo.list_player_progression(db, player_id, order=order)
    except ProgressionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ProgressionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return {"entries": entries}


@router.post("/players/{player_id}/progression", status_code=status.HTTP_201_CREATED)
def create_progression_entry(
    player_id: int,
    payload: ProgressionCreateRequest,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _ = session
    try:
        entry = progression_repo.create_progression_entry(
            db,
            player_id,
            recorded_at=payload.recorded_at,
            metrics=payload.metrics,
            note=payload.note,
        )
    except ProgressionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (ProgressionValidationError, FieldValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return {"entry": entry}


@router.patch("/progression/{entry_id}")
def update_progression_entry(
    entry_id: int,
    payload: ProgressionUpdateRequest,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    _ = session
    try:
        entry = progression_repo.update_progression_entry(
            db,
            entry_id,
            set(payload.model_fields_set),
            recorded_at=payload.recorded_at,
            metrics=payload.metrics,
            note=payload.note,
        )
    except ProgressionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (ProgressionValidationError, FieldValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return {"entry": entry}


@router.delete("/progression/{entry_id}")
def delete_progression_entry(
    entry_id: int,
    session: AuthenticatedSession = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, bool]:
    _ = session
    try:
        progression_repo.delete_progression_entry(db, entry_id)
    except ProgressionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return {"deleted": True}
