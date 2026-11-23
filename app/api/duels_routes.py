from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import require_admin
from app.config import Settings
from app.db.connection import get_db
from app.repositories import duels_repo, limits_repo, players_repo
from app.repositories.duels_repo import DuelNotFoundError, DuelValidationError
from app.repositories.limits_repo import LimitValidationError
from app.repositories.players_repo import PlayerConflictError, PlayerValidationError
from app.services import limit_evaluator
from app.services.player_matcher import RosterCandidate

router = APIRouter(prefix="/api", tags=["duels"], dependencies=[Depends(require_admin)])

_EXT_BY_MAGIC = ((b"\x89PNG", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"RIFF", ".webp"))
_MEDIA_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}


def _422(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _404(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _settings(request: Request) -> Settings:
    return request.app.state.settings


# ---------------------------------------------------------------- models

class DuelCreateRequest(BaseModel):
    opponent_clan_name: str
    title: str | None = None
    start_date: str
    end_date: str | None = None
    status: Literal["ongoing", "completed", "cancelled"] = "ongoing"
    notes: str | None = None


class DuelUpdateRequest(BaseModel):
    opponent_clan_name: str | None = None
    title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: Literal["ongoing", "completed", "cancelled"] | None = None
    notes: str | None = None


class ScoreCreateRequest(BaseModel):
    player_id: int | None = None
    extracted_name: str | None = None
    score: int
    score_date: str


class ScoreUpdateRequest(BaseModel):
    player_id: int | None = None
    extracted_name: str | None = None
    score: int | None = None
    score_date: str | None = None


class CommitRow(BaseModel):
    extractedName: str = Field(..., min_length=1, max_length=100)
    score: int
    playerId: int | None = None
    createPlayer: bool = False
    saveAlias: bool = False


class CommitRequest(BaseModel):
    score_date: str
    rows: list[CommitRow] = Field(..., min_length=1, max_length=200)


class LimitUpdateRequest(BaseModel):
    minScore: int
    note: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------- duels

@router.get("/duels")
def list_duels(db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return {"duels": duels_repo.list_duels(db), "activeDailyMinScore": limits_repo.get_active_limit(db)}


@router.post("/duels", status_code=status.HTTP_201_CREATED)
def create_duel(payload: DuelCreateRequest, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    try:
        return {"duel": duels_repo.create_duel(db, **payload.model_dump())}
    except DuelValidationError as exc:
        raise _422(exc) from exc


@router.get("/duels/{duel_id}")
def get_duel(duel_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    try:
        return duels_repo.get_duel_detail(db, duel_id)
    except DuelNotFoundError as exc:
        raise _404(exc) from exc


@router.patch("/duels/{duel_id}")
def update_duel(
    duel_id: int, payload: DuelUpdateRequest, db: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    try:
        duel = duels_repo.update_duel(db, duel_id, set(payload.model_fields_set), **payload.model_dump())
    except DuelNotFoundError as exc:
        raise _404(exc) from exc
    except DuelValidationError as exc:
        raise _422(exc) from exc
    return {"duel": duel}


@router.delete("/duels/{duel_id}")
def delete_duel(duel_id: int, request: Request, db: sqlite3.Connection = Depends(get_db)) -> dict[str, bool]:
    try:
        files = duels_repo.delete_duel(db, duel_id)
    except DuelNotFoundError as exc:
        raise _404(exc) from exc
    upload_dir = _settings(request).upload_dir
    for name in files:
        try:
            (upload_dir / Path(name).name).unlink(missing_ok=True)
        except OSError:
            pass
    return {"deleted": True}


# ---------------------------------------------------------------- screenshots

def _build_roster(db: sqlite3.Connection) -> list[RosterCandidate]:
    roster: list[RosterCandidate] = []
    for p in players_repo.list_players(db):
        roster.append(
            RosterCandidate(
                id=int(p["id"]),
                display_name=str(p["display_name"]),
                aliases=[a["alias_name"] for a in p.get("aliases", [])],
            )
        )
    return roster


@router.post("/duels/{duel_id}/screenshots/extract", status_code=status.HTTP_201_CREATED)
async def extract_screenshot(
    duel_id: int,
    request: Request,
    file: UploadFile = File(...),
    score_date: str = Form(...),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    from app.services.ocr_service import OcrError, extract_leaderboard_from_image

    settings = _settings(request)
    try:
        duels_repo.get_duel_detail(db, duel_id)
        clean_date = duels_repo.validate_date(score_date, "Puan tarihi")
    except DuelNotFoundError as exc:
        raise _404(exc) from exc
    except DuelValidationError as exc:
        raise _422(exc) from exc

    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Dosya çok büyük (en fazla 15 MB).")

    roster = _build_roster(db)
    try:
        result = await run_in_threadpool(
            extract_leaderboard_from_image, data, roster, max_bytes=settings.max_upload_bytes
        )
    except OcrError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    ext = next((e for magic, e in _EXT_BY_MAGIC if data.startswith(magic)), ".png")
    stored_name = f"{uuid.uuid4().hex}{ext}"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / stored_name).write_bytes(data)

    api = result.to_api_dict()
    screenshot_id = duels_repo.create_screenshot(
        db,
        duel_id=duel_id,
        score_date=clean_date,
        file_path=stored_name,
        original_filename=file.filename or stored_name,
        raw_text=api["rawText"],
        parsed_rows=api["parsedRows"],
    )
    return {
        "screenshotId": screenshot_id,
        "imageUrl": f"/api/duels/{duel_id}/screenshots/{screenshot_id}/image",
        "scoreDate": clean_date,
        **api,
    }


@router.get("/duels/{duel_id}/screenshots/{screenshot_id}/image")
def get_screenshot_image(
    duel_id: int, screenshot_id: int, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> FileResponse:
    try:
        row = duels_repo.get_screenshot_row(db, duel_id, screenshot_id)
    except DuelNotFoundError as exc:
        raise _404(exc) from exc
    path = _settings(request).upload_dir / Path(str(row["file_path"])).name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Görüntü dosyası bulunamadı.")
    return FileResponse(
        str(path),
        media_type=_MEDIA_BY_EXT.get(path.suffix.lower(), "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/duels/{duel_id}/screenshots/{screenshot_id}/commit", status_code=status.HTTP_201_CREATED)
def commit_screenshot(
    duel_id: int,
    screenshot_id: int,
    payload: CommitRequest,
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    try:
        duels_repo.get_screenshot_row(db, duel_id, screenshot_id)
        clean_date = duels_repo.validate_date(payload.score_date, "Puan tarihi")
        # ---- validate everything before writing anything
        seen_players: set[int] = set()
        seen_names: set[str] = set()
        for idx, row in enumerate(payload.rows, start=1):
            duels_repo.validate_score(row.score)
            name = row.extractedName.strip()
            if not name:
                raise DuelValidationError(f"{idx}. satır: oyuncu adı boş olamaz.")
            if row.playerId is not None:
                if row.createPlayer:
                    raise DuelValidationError(f"{idx}. satır: hem oyuncu seçilip hem yeni oyuncu oluşturulamaz.")
                if db.execute("SELECT 1 FROM players WHERE id = ?", (row.playerId,)).fetchone() is None:
                    raise DuelValidationError(f"{idx}. satır: seçilen oyuncu bulunamadı.")
                if row.playerId in seen_players:
                    raise DuelValidationError(f"{idx}. satır: aynı oyuncu birden fazla satırda seçilmiş.")
                seen_players.add(row.playerId)
            else:
                folded = name.casefold()
                if folded in seen_names:
                    raise DuelValidationError(f"{idx}. satır: aynı isim birden fazla kez girilmiş.")
                seen_names.add(folded)
    except DuelNotFoundError as exc:
        raise _404(exc) from exc
    except DuelValidationError as exc:
        raise _422(exc) from exc

    warnings: list[str] = []
    saved_ids: list[int] = []
    created_players: list[dict[str, Any]] = []
    for row in payload.rows:
        name = row.extractedName.strip()
        player_id = row.playerId
        if row.createPlayer:
            try:
                player = players_repo.create_player(db, display_name=name)
                player_id = int(player["id"])
                created_players.append(player)
            except PlayerConflictError:
                existing = next(
                    (p for p in players_repo.list_players(db, search=name)
                     if p["display_name"].casefold() == name.casefold()),
                    None,
                )
                if existing is None:
                    warnings.append(f"'{name}' için oyuncu oluşturulamadı (isim çakışması).")
                else:
                    player_id = int(existing["id"])
            except (PlayerValidationError, Exception) as exc:  # field validation (required fields)
                warnings.append(f"'{name}' için oyuncu oluşturulamadı: {exc}")
        elif player_id is not None and row.saveAlias:
            player_name = db.execute("SELECT display_name FROM players WHERE id = ?", (player_id,)).fetchone()
            if player_name is not None and str(player_name[0]).casefold() != name.casefold():
                try:
                    players_repo.add_alias(db, player_id, name)
                except (PlayerConflictError, PlayerValidationError) as exc:
                    warnings.append(f"'{name}' takma adı kaydedilemedi: {exc}")

        saved_ids.append(
            duels_repo.upsert_score(
                db,
                duel_id=duel_id,
                player_id=player_id,
                extracted_name=name,
                score=row.score,
                score_date=clean_date,
                source="ocr",
                screenshot_id=screenshot_id,
                commit=False,
            )
        )
    db.execute(
        "UPDATE duel_screenshots SET status = 'committed', score_date = ? WHERE id = ?",
        (clean_date, screenshot_id),
    )
    db.commit()

    evaluated = duels_repo.evaluate(db, score_date=clean_date, duel_id=duel_id)
    return {
        "savedScores": duels_repo.get_scores_by_ids(db, saved_ids),
        "createdPlayers": created_players,
        "evaluatedDailySummaries": evaluated["evaluations"],
        "warnings": warnings,
    }


# ---------------------------------------------------------------- scores

@router.post("/duels/{duel_id}/scores", status_code=status.HTTP_201_CREATED)
def add_score(duel_id: int, payload: ScoreCreateRequest, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    try:
        score = duels_repo.add_manual_score(db, duel_id, **payload.model_dump())
    except DuelNotFoundError as exc:
        raise _404(exc) from exc
    except DuelValidationError as exc:
        raise _422(exc) from exc
    return {"score": score}


@router.patch("/scores/{score_id}")
def update_score(score_id: int, payload: ScoreUpdateRequest, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    try:
        score = duels_repo.update_score(db, score_id, set(payload.model_fields_set), **payload.model_dump())
    except DuelNotFoundError as exc:
        raise _404(exc) from exc
    except DuelValidationError as exc:
        raise _422(exc) from exc
    return {"score": score}


@router.delete("/scores/{score_id}")
def delete_score(score_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict[str, bool]:
    try:
        duels_repo.delete_score(db, score_id)
    except DuelNotFoundError as exc:
        raise _404(exc) from exc
    return {"deleted": True}


# ---------------------------------------------------------------- limits

@router.get("/limits/daily")
def get_daily_limit(db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return limits_repo.get_limit_state(db)


@router.put("/limits/daily")
def put_daily_limit(payload: LimitUpdateRequest, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    try:
        return limits_repo.set_daily_limit(db, payload.minScore, payload.note)
    except LimitValidationError as exc:
        raise _422(exc) from exc


@router.get("/limits/evaluate")
def evaluate_limits(
    score_date: str | None = Query(default=None, alias="date"),
    duel_id: int | None = Query(default=None, alias="duelId"),
    player_id: int | None = Query(default=None, alias="playerId"),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    try:
        clean_date = duels_repo.validate_date(score_date, "Tarih", required=False)
    except DuelValidationError as exc:
        raise _422(exc) from exc
    return duels_repo.evaluate(db, score_date=clean_date, duel_id=duel_id, player_id=player_id)


@router.get("/dashboard")
def dashboard(db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    active = limits_repo.get_active_limit(db)
    counts = {
        row["status"]: int(row["cnt"])
        for row in db.execute("SELECT status, COUNT(*) AS cnt FROM players GROUP BY status")
    }
    duels = duels_repo.list_duels(db)
    latest_row = db.execute("SELECT MAX(score_date) AS d FROM duel_scores").fetchone()
    latest_date = latest_row["d"] if latest_row else None
    latest_eval = duels_repo.evaluate(db, score_date=latest_date) if latest_date else {
        "evaluations": [], "compliance": limit_evaluator.summarize_compliance([])
    }
    return {
        "activeDailyMinScore": active,
        "playerCounts": {
            "active": counts.get("active", 0),
            "inactive": counts.get("inactive", 0),
            "left": counts.get("left", 0),
            "total": sum(counts.values()),
        },
        "duelCounts": {
            "total": len(duels),
            "ongoing": sum(1 for d in duels if d["status"] == "ongoing"),
        },
        "recentDuels": duels[:5],
        "latestScoreDate": latest_date,
        "latestDayEvaluations": latest_eval["evaluations"],
        "latestDayCompliance": latest_eval["compliance"],
    }
