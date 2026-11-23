from __future__ import annotations

import threading
import warnings
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Mapping, Sequence

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from rapidocr_onnxruntime import RapidOCR

from app.services.player_matcher import (
    MatchStatus,
    RosterCandidate,
    apply_review_flags,
    match_player,
)
from app.services.roster_parser import (
    ParsedRosterRow,
    reconstruct_roster_candidates,
)
from app.services.score_parser import (
    ParsedScoreRow,
    cluster_boxes_into_rows,
    reconstruct_rows_and_parse,
)

DEFAULT_MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_DIMENSION = 10_000
MIN_IMAGE_DIMENSION = 16
MAX_IMAGE_PIXELS = 40_000_000
ALLOWED_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})


class OcrError(Exception):
    """Base structured OCR domain error."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class OcrInvalidImageError(OcrError):
    """Empty payload, unsupported format/magic bytes, or corrupt image (HTTP 400/422)."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(code=code, message=message, status_code=status_code)


class OcrImageTooLargeError(OcrError):
    """Payload exceeds byte limit, dimension bounds, or pixel cap (HTTP 413)."""

    def __init__(self, code: str, message: str, status_code: int = 413) -> None:
        super().__init__(code=code, message=message, status_code=status_code)


class OcrEngineError(OcrError):
    """Unexpected RapidOCR / ONNXRuntime failure (HTTP 500)."""

    def __init__(self, code: str, message: str, status_code: int = 500) -> None:
        super().__init__(code=code, message=message, status_code=status_code)


@dataclass(frozen=True, slots=True)
class ParsedLeaderboardRow:
    tempId: str
    rawLine: str
    extractedName: str
    cleanName: str
    rawScoreText: str
    extractedScore: int
    ocrConfidence: float
    matchedPlayerId: int | None
    matchedPlayerName: str | None
    matchStatus: MatchStatus
    matchConfidence: float
    needsReview: bool
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "tempId": self.tempId,
            "rawLine": self.rawLine,
            "extractedName": self.extractedName,
            "cleanName": self.cleanName,
            "rawScoreText": self.rawScoreText,
            "extractedScore": self.extractedScore,
            "ocrConfidence": self.ocrConfidence,
            "matchedPlayerId": self.matchedPlayerId,
            "matchedPlayerName": self.matchedPlayerName,
            "matchStatus": self.matchStatus,
            "matchConfidence": self.matchConfidence,
            "needsReview": self.needsReview,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class OcrExtractionResult:
    raw_text: str
    parsed_rows: list[ParsedLeaderboardRow]
    pass_used: str = "pass1"
    warnings: tuple[str, ...] = ()

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "rawText": self.raw_text,
            "parsedRows": [row.to_dict() for row in self.parsed_rows],
            "passUsed": self.pass_used,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class ParsedRosterCandidate:
    tempId: str
    rawLine: str
    extractedName: str
    cleanName: str
    suggestedAlias: str | None
    detectedNumber: int | None
    ocrConfidence: float
    alreadyExists: bool
    matchedPlayerId: int | None
    matchedPlayerName: str | None
    matchStatus: MatchStatus
    matchConfidence: float
    needsReview: bool
    detectedRank: str | None = None
    detectedTowerLevel: str | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "tempId": self.tempId,
            "rawLine": self.rawLine,
            "extractedName": self.extractedName,
            "cleanName": self.cleanName,
            "suggestedAlias": self.suggestedAlias,
            "detectedNumber": self.detectedNumber,
            "detectedRank": self.detectedRank,
            "detectedTowerLevel": self.detectedTowerLevel,
            "ocrConfidence": self.ocrConfidence,
            "alreadyExists": self.alreadyExists,
            "matchedPlayerId": self.matchedPlayerId,
            "matchedPlayerName": self.matchedPlayerName,
            "matchStatus": self.matchStatus,
            "matchConfidence": self.matchConfidence,
            "needsReview": self.needsReview,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class RosterExtractionResult:
    raw_text: str
    candidates: list[ParsedRosterCandidate]
    pass_used: str = "pass1"
    warnings: tuple[str, ...] = ()

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "rawText": self.raw_text,
            "candidates": [cand.to_dict() for cand in self.candidates],
            "passUsed": self.pass_used,
            "warnings": list(self.warnings),
        }


_OCR_LOCK = threading.Lock()
_PIL_DECODE_LOCK = threading.Lock()
_OCR_ENGINE: RapidOCR | None = None


def get_ocr_engine() -> RapidOCR:
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        with _OCR_LOCK:
            if _OCR_ENGINE is None:
                _OCR_ENGINE = RapidOCR(
                    use_cls=False,
                    max_side_len=3200,
                    intra_op_num_threads=4,
                    inter_op_num_threads=1,
                    text_score=0.3,
                )
    return _OCR_ENGINE


def _has_supported_magic_bytes(data: bytes) -> bool:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if data.startswith(b"\xff\xd8\xff"):
        return True
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def _flatten_alpha_luminance_aware(im: Image.Image) -> Image.Image:
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        arr = np.asarray(rgba, dtype=np.uint8)
        alpha = arr[:, :, 3]
        opaque_mask = alpha > 128
        if np.any(opaque_mask):
            rgb_opaque = arr[:, :, :3][opaque_mask]
            mean_lum = float(
                np.mean(
                    0.299 * rgb_opaque[:, 0]
                    + 0.587 * rgb_opaque[:, 1]
                    + 0.114 * rgb_opaque[:, 2]
                )
            )
            bg_color = (0, 0, 0, 255) if mean_lum >= 128.0 else (255, 255, 255, 255)
        else:
            bg_color = (255, 255, 255, 255)
        bg = Image.new("RGBA", rgba.size, bg_color)
        composited = Image.alpha_composite(bg, rgba)
        return composited.convert("RGB")
    if im.mode != "RGB":
        return im.convert("RGB")
    return im


def validate_and_decode_image(
    image_bytes: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> np.ndarray:
    if not isinstance(image_bytes, (bytes, bytearray)):
        raise OcrInvalidImageError("EMPTY_IMAGE", "Ekran görüntüsü verisi geçersiz.", 400)

    data = bytes(image_bytes)
    if len(data) < 12:
        raise OcrInvalidImageError("EMPTY_IMAGE", "Ekran görüntüsü dosyası boş veya geçersiz.", 400)

    if len(data) > max_bytes:
        raise OcrImageTooLargeError(
            "IMAGE_TOO_LARGE",
            f"Görsel boyutu maksimum sınırı ({max_bytes} bayt) aşıyor.",
            413,
        )

    if not _has_supported_magic_bytes(data):
        raise OcrInvalidImageError(
            "UNSUPPORTED_FORMAT",
            "Yalnızca PNG, JPG/JPEG ve WEBP formatındaki görseller desteklenir.",
            400,
        )

    with _PIL_DECODE_LOCK:
        prev_max_pixels = Image.MAX_IMAGE_PIXELS
        try:
            Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)

                # First pass: header check + verify()
                with Image.open(BytesIO(data)) as im:
                    if im.format not in ALLOWED_FORMATS:
                        raise OcrInvalidImageError(
                            "UNSUPPORTED_FORMAT",
                            "Yalnızca PNG, JPG/JPEG ve WEBP formatındaki görseller desteklenir.",
                            400,
                        )
                    w, h = im.size
                    if w < MIN_IMAGE_DIMENSION or h < MIN_IMAGE_DIMENSION:
                        raise OcrInvalidImageError(
                            "IMAGE_TOO_SMALL",
                            f"Görsel boyutları en az {MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION} piksel olmalıdır.",
                            422,
                        )
                    if w > MAX_IMAGE_DIMENSION or h > MAX_IMAGE_DIMENSION or (w * h) > MAX_IMAGE_PIXELS:
                        raise OcrImageTooLargeError(
                            "IMAGE_DIMENSIONS_TOO_LARGE",
                            "Görsel çözünürlüğü izin verilen maksimum sınırı aşıyor.",
                            413,
                        )
                    im.verify()

                # Second pass: full pixel decode + EXIF transpose + safe alpha flattening
                with Image.open(BytesIO(data)) as im2:
                    transposed = ImageOps.exif_transpose(im2)
                    transposed.load()
                    w2, h2 = transposed.size
                    if w2 < MIN_IMAGE_DIMENSION or h2 < MIN_IMAGE_DIMENSION:
                        raise OcrInvalidImageError(
                            "IMAGE_TOO_SMALL",
                            f"Görsel boyutları en az {MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION} piksel olmalıdır.",
                            422,
                        )
                    if w2 > MAX_IMAGE_DIMENSION or h2 > MAX_IMAGE_DIMENSION or (w2 * h2) > MAX_IMAGE_PIXELS:
                        raise OcrImageTooLargeError(
                            "IMAGE_DIMENSIONS_TOO_LARGE",
                            "Görsel çözünürlüğü izin verilen maksimum sınırı aşıyor.",
                            413,
                        )
                    rgb_im = _flatten_alpha_luminance_aware(transposed)
                    rgb_arr = np.asarray(rgb_im, dtype=np.uint8)
                    if rgb_arr.ndim != 3 or rgb_arr.shape[2] != 3:
                        raise OcrInvalidImageError(
                            "CORRUPT_IMAGE",
                            "Görsel RGB formatına dönüştürülemedi.",
                            422,
                        )
                    return np.ascontiguousarray(rgb_arr)
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise OcrImageTooLargeError(
                "IMAGE_DIMENSIONS_TOO_LARGE",
                "Görsel piksel sayısı güvenlik sınırını aşıyor.",
                413,
            ) from exc
        except OcrError:
            raise
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
            raise OcrInvalidImageError(
                "CORRUPT_IMAGE",
                "Görsel dosyası bozuk veya okunamıyor.",
                422,
            ) from exc
        finally:
            Image.MAX_IMAGE_PIXELS = prev_max_pixels


def preprocess_pass1(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    median_lum = float(np.median(gray))
    if median_lum < 128.0:
        gray = 255 - gray

    h, w = gray.shape[:2]
    if w < 1600:
        scale = min(2.5, 3200.0 / float(max(w, h)))
        if scale > 1.0:
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    p1, p99 = np.percentile(gray, (1.0, 99.0))
    if p99 > p1:
        stretched = np.clip((gray.astype(np.float32) - p1) * (255.0 / (p99 - p1)), 0.0, 255.0)
        norm = stretched.astype(np.uint8)
    else:
        norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    return cv2.cvtColor(norm, cv2.COLOR_GRAY2BGR)


def preprocess_pass2(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    median_lum = float(np.median(gray))
    if median_lum < 128.0:
        signal = 255 - np.max(rgb, axis=2)
    else:
        signal = np.min(rgb, axis=2)

    h, w = signal.shape[:2]
    if w < 1800:
        scale = min(3.0, 3200.0 / float(max(w, h)))
        if scale > 1.0:
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            signal = cv2.resize(signal, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    _, bin_img = cv2.threshold(signal, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    fg_ratio = float(np.mean(bin_img == 0))
    if fg_ratio < 0.005 or fg_ratio > 0.60:
        bin_img = cv2.adaptiveThreshold(
            signal,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            10,
        )

    return cv2.cvtColor(bin_img, cv2.COLOR_GRAY2BGR)


def _run_rapidocr(bgr_img: np.ndarray) -> list[Any]:
    engine = get_ocr_engine()
    try:
        with _OCR_LOCK:
            result, _ = engine(bgr_img)
    except Exception as exc:
        raise OcrEngineError("OCR_ENGINE_FAILED", f"OCR motoru çalıştırılamadı: {exc}", 500) from exc
    if not result:
        return []
    return list(result)


@dataclass(frozen=True, slots=True)
class _PassEvaluation:
    pass_name: str
    raw_boxes: list[Any]
    parsed_score_rows: list[ParsedScoreRow]
    mean_confidence: float
    score: float
    repaired_count: int


def _evaluate_pass(pass_name: str, bgr_img: np.ndarray) -> _PassEvaluation:
    raw_boxes = _run_rapidocr(bgr_img)
    parsed_rows = reconstruct_rows_and_parse(raw_boxes)

    if parsed_rows:
        mean_conf = sum(row.ocr_confidence for row in parsed_rows) / len(parsed_rows)
    elif raw_boxes:
        mean_conf = sum(float(item[2]) for item in raw_boxes) / len(raw_boxes)
    else:
        mean_conf = 0.0

    repaired_count = sum(1 for row in parsed_rows if "digit_repaired" in row.warnings)
    score = len(parsed_rows) * 100.0 + mean_conf * 100.0
    return _PassEvaluation(
        pass_name=pass_name,
        raw_boxes=raw_boxes,
        parsed_score_rows=parsed_rows,
        mean_confidence=mean_conf,
        score=score,
        repaired_count=repaired_count,
    )


def _should_run_pass2(eval1: _PassEvaluation) -> bool:
    if len(eval1.parsed_score_rows) < 2:
        return True
    if eval1.mean_confidence < 0.70:
        return True
    for row in eval1.parsed_score_rows:
        if "digit_repaired" in row.warnings or row.ocr_confidence < 0.75:
            return True
    return False


def _build_raw_text(raw_boxes: list[Any]) -> str:
    rows = cluster_boxes_into_rows(raw_boxes)
    if not rows:
        return ""
    return "\n".join(" ".join(box.text.strip() for box in row if box.text.strip()) for row in rows)


def extract_leaderboard_from_image(
    image_bytes: bytes,
    roster: Sequence[RosterCandidate | Mapping[str, Any]],
    *,
    max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> OcrExtractionResult:
    rgb = validate_and_decode_image(image_bytes, max_bytes=max_bytes)

    pass1_bgr = preprocess_pass1(rgb)
    eval1 = _evaluate_pass("pass1", pass1_bgr)
    winner = eval1

    if _should_run_pass2(eval1):
        pass2_bgr = preprocess_pass2(rgb)
        eval2 = _evaluate_pass("pass2", pass2_bgr)
        # Higher score wins; tie-break by fewer digit_repaired, then pass1
        if (eval2.score, -eval2.repaired_count) > (eval1.score, -eval1.repaired_count):
            winner = eval2

    raw_text = _build_raw_text(winner.raw_boxes)
    if not winner.parsed_score_rows:
        return OcrExtractionResult(
            raw_text=raw_text,
            parsed_rows=[],
            pass_used=winner.pass_name,
            warnings=("NO_LEADERBOARD_ROWS_DETECTED",),
        )

    staged_rows: list[dict[str, Any]] = []
    for idx, score_row in enumerate(winner.parsed_score_rows):
        match_res = match_player(score_row.extracted_name, roster)
        combined_warnings = list(score_row.warnings) + list(match_res.warnings)
        staged_rows.append({
            "tempId": f"row-{idx + 1}",
            "rawLine": score_row.raw_line,
            "extractedName": score_row.extracted_name,
            "cleanName": match_res.clean_name,
            "rawScoreText": score_row.raw_score_text,
            "extractedScore": score_row.extracted_score,
            "ocrConfidence": round(float(score_row.ocr_confidence), 4),
            "matchedPlayerId": match_res.matched_player_id,
            "matchedPlayerName": match_res.matched_player_name,
            "matchStatus": match_res.match_status,
            "matchConfidence": round(float(match_res.match_confidence), 4),
            "needsReview": match_res.needs_review,
            "warnings": combined_warnings,
        })

    flagged_rows = apply_review_flags(staged_rows)
    final_rows = [
        ParsedLeaderboardRow(
            tempId=row["tempId"],
            rawLine=row["rawLine"],
            extractedName=row["extractedName"],
            cleanName=row["cleanName"],
            rawScoreText=row["rawScoreText"],
            extractedScore=row["extractedScore"],
            ocrConfidence=row["ocrConfidence"],
            matchedPlayerId=row["matchedPlayerId"],
            matchedPlayerName=row["matchedPlayerName"],
            matchStatus=row["matchStatus"],
            matchConfidence=row["matchConfidence"],
            needsReview=row["needsReview"],
            warnings=tuple(row["warnings"]),
        )
        for row in flagged_rows
    ]

    return OcrExtractionResult(
        raw_text=raw_text,
        parsed_rows=final_rows,
        pass_used=winner.pass_name,
        warnings=(),
    )


def _score_roster_pass(
    raw_boxes: list[Any], parsed: list[ParsedRosterRow]
) -> tuple[float, float]:
    if parsed:
        mean_conf = sum(row.ocr_confidence for row in parsed) / len(parsed)
    elif raw_boxes:
        mean_conf = sum(float(item[2]) for item in raw_boxes) / len(raw_boxes)
    else:
        mean_conf = 0.0
    score = len(parsed) * 100.0 + mean_conf * 100.0
    return score, mean_conf


def extract_players_from_image(
    image_bytes: bytes,
    roster: Sequence[RosterCandidate | Mapping[str, Any]],
    *,
    max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> RosterExtractionResult:
    rgb = validate_and_decode_image(image_bytes, max_bytes=max_bytes)

    pass1_bgr = preprocess_pass1(rgb)
    raw1 = _run_rapidocr(pass1_bgr)
    parsed1 = reconstruct_roster_candidates(raw1)
    score1, mean_conf1 = _score_roster_pass(raw1, parsed1)

    win_name = "pass1"
    win_boxes = raw1
    win_parsed = parsed1

    need_pass2 = (
        len(parsed1) < 2
        or mean_conf1 < 0.72
        or any(row.ocr_confidence < 0.75 for row in parsed1)
    )
    if need_pass2:
        pass2_bgr = preprocess_pass2(rgb)
        raw2 = _run_rapidocr(pass2_bgr)
        parsed2 = reconstruct_roster_candidates(raw2)
        score2, _ = _score_roster_pass(raw2, parsed2)
        if (score2, len(parsed2)) > (score1, len(parsed1)):
            win_name = "pass2"
            win_boxes = raw2
            win_parsed = parsed2

    raw_text = _build_raw_text(win_boxes)
    if not win_parsed:
        return RosterExtractionResult(
            raw_text=raw_text,
            candidates=[],
            pass_used=win_name,
            warnings=("NO_PLAYERS_DETECTED",),
        )

    candidates: list[ParsedRosterCandidate] = []
    for idx, row in enumerate(win_parsed):
        match_res = match_player(row.extracted_name, roster)
        clean_name = match_res.clean_name or row.clean_name
        suggested_alias = (
            row.extracted_name
            if row.extracted_name.casefold() != clean_name.casefold()
            else None
        )
        already_exists = match_res.match_status in (
            "exact",
            "case_insensitive",
            "ocr_normalized",
        )
        warnings_list: list[str] = list(row.warnings)
        if already_exists:
            warnings_list.append("already_registered")
        elif match_res.match_status == "fuzzy_review":
            warnings_list.append("similar_existing_player")
        if row.ocr_confidence < 0.75:
            warnings_list.append("low_ocr_confidence")

        needs_review = (not already_exists) and (
            match_res.match_status == "fuzzy_review"
            or row.ocr_confidence < 0.75
            or len(clean_name) < 3
        )

        candidates.append(
            ParsedRosterCandidate(
                tempId=f"cand-{idx + 1}",
                rawLine=row.raw_line,
                extractedName=row.extracted_name,
                cleanName=clean_name,
                suggestedAlias=suggested_alias,
                detectedNumber=row.detected_number,
                detectedRank=row.detected_rank,
                detectedTowerLevel=row.detected_tower_level,
                ocrConfidence=round(float(row.ocr_confidence), 4),
                alreadyExists=already_exists,
                matchedPlayerId=match_res.matched_player_id,
                matchedPlayerName=match_res.matched_player_name,
                matchStatus=match_res.match_status,
                matchConfidence=round(float(match_res.match_confidence), 4),
                needsReview=needs_review,
                warnings=tuple(warnings_list),
            )
        )

    return RosterExtractionResult(
        raw_text=raw_text,
        candidates=candidates,
        pass_used=win_name,
        warnings=(),
    )
