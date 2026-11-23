from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

_SPACE_TRANSLATION = str.maketrans({
    "\u00a0": " ",
    "\u2009": " ",
    "\u202f": " ",
    "\u200b": "",
})

_TURKISH_FOLD_MAP = str.maketrans({
    "ç": "c",
    "ğ": "g",
    "ı": "i",
    "ö": "o",
    "ş": "s",
    "ü": "u",
    "Ç": "C",
    "Ğ": "G",
    "İ": "I",
    "Ö": "O",
    "Ş": "S",
    "Ü": "U",
})

_HEADER_KEYWORDS = frozenset({
    "RANK",
    "PLAYER",
    "PLAYERS",
    "NAME",
    "SCORE",
    "SCORES",
    "POINTS",
    "PTS",
    "KILL",
    "KILLS",
    "OLDURME",
    "OLDURMELER",
    "PUAN",
    "PUANI",
    "PUANLAR",
    "SIRA",
    "OYUNCU",
    "OYUNCULAR",
    "ISIM",
    "AD",
    "KLAN",
    "CLAN",
    "LEADERBOARD",
    "RANKING",
    "DAY",
    "GUN",
    "TOTAL",
    "TOPLAM",
    "DAMAGE",
    "HASAR",
    "POWER",
    "GUC",
    "LEVEL",
    "LVL",
    "NO",
    "SKOR",
    "TABLO",
    "TABLOSU",
    "HAFTALIK",
    "DUELLO",
    "DUELLOSU",
    "WEEK",
    "HAFTA",
    "SEASON",
    "SEZON",
    "UYE",
    "UYELER",
})

_SCORE_HEADER_KEYWORDS = frozenset({
    "SCORE",
    "SCORES",
    "PUAN",
    "PUANI",
    "POINTS",
    "PTS",
    "SKOR",
    "TOTAL",
    "TOPLAM",
})

_SUFFIX_MULTIPLIERS: dict[str, int] = {
    "K": 1_000,
    "M": 1_000_000,
    "B": 1_000_000_000,
}

_DIGIT_REPAIR_MAP: dict[str, str] = {
    "O": "0",
    "o": "0",
    "Q": "0",
    "D": "0",
    "l": "1",
    "I": "1",
    "|": "1",
    "Z": "2",
    "z": "2",
    "S": "5",
    "s": "5",
    "$": "5",
    "G": "6",
    "B": "8",
}

_DATE_RE = re.compile(
    r"^(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}/\d{1,2})$"
)
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
_RANK_TOKEN_RE = re.compile(r"^(?:#\s*\d{1,4}|\d{1,4}\s*[.)\]:])$")
_PURE_RANK_BOX_RE = re.compile(r"^(?:#?\d{1,4}[.)\]:-]?|\d{1,4}\s*[.)\]:-])$")
_RANK_PREFIX_RE = re.compile(
    r"^\s*(?:#\s*\d{1,4}[.)\]:-]?\s+|\d{1,4}\s*[)\]:-]\s*|\d{1,4}\.(?:\s+|(?=[A-Za-zÇĞİÖŞÜçğıöşü\[<\(\{])))"
)

_COMMA_THOUSANDS_RE = re.compile(r"^\d{1,3}(?:,\d{3})+$")
_DOT_THOUSANDS_RE = re.compile(r"^\d{1,3}(?:\.\d{3})+$")
_SPACE_THOUSANDS_RE = re.compile(r"^\d{1,3}(?: \d{3})+$")
_PLAIN_INT_RE = re.compile(r"^\d+$")
_SUFFIX_SIMPLE_RE = re.compile(r"^(?P<num>\d+(?:[.,]\d+)?)\s*(?P<suffix>[KMBkmb])$")
_SUFFIX_GROUPED_COMMA_RE = re.compile(
    r"^(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?)\s*(?P<suffix>[KMBkmb])$"
)
_SUFFIX_GROUPED_DOT_RE = re.compile(
    r"^(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d+)?)\s*(?P<suffix>[KMBkmb])$"
)

_TRAILING_SPACE_SCORE_RE = re.compile(r"^(?P<left>.+?)\s+(?P<score>\d{1,3}(?: \d{3})+)$")
_TRAILING_SUFFIX_SPACE_RE = re.compile(
    r"^(?P<left>.+?)\s+(?P<score>\d+(?:[.,]\d+)?\s*[KMBkmb])$"
)
_TRAILING_TOKEN_RE = re.compile(r"^(?P<left>.+?)\s+(?P<score>\S+)$")
_BANNER_LINE_RE = re.compile(
    r"^(?:DAY|GUN|GÜN|WEEK|HAFTA|SEASON|SEZON|ROUND|TUR|PAGE|SAYFA)\s+\d{1,3}(?:\s*/\s*\d{1,3})?$",
    re.IGNORECASE,
)
_BANNER_KEYWORDS = frozenset({
    "DAY",
    "GUN",
    "WEEK",
    "HAFTA",
    "SEASON",
    "SEZON",
    "ROUND",
    "TUR",
    "PAGE",
    "SAYFA",
})
_BANNER_NUM_RE = re.compile(r"^\d{1,3}(?:/\d{1,3})?$")
_PURE_NUMERIC_COL_RE = re.compile(r"^(?:\d{1,4}|(?:LV|LVL)\.?\s*\d{1,4})$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class OcrBox:
    bbox: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ]
    text: str
    confidence: float

    @property
    def x_left(self) -> float:
        return min(pt[0] for pt in self.bbox)

    @property
    def x_right(self) -> float:
        return max(pt[0] for pt in self.bbox)

    @property
    def x_center(self) -> float:
        return 0.5 * (self.x_left + self.x_right)

    @property
    def y_top(self) -> float:
        return min(pt[1] for pt in self.bbox)

    @property
    def y_bottom(self) -> float:
        return max(pt[1] for pt in self.bbox)

    @property
    def y_center(self) -> float:
        return sum(pt[1] for pt in self.bbox) / 4.0

    @property
    def height(self) -> float:
        return max(1.0, self.y_bottom - self.y_top)


@dataclass(frozen=True, slots=True)
class ParsedScore:
    value: int
    raw_text: str
    digit_repaired: bool = False
    format_kind: str = "integer"  # "integer" | "thousands_sep" | "suffix" | "repaired"


@dataclass(frozen=True, slots=True)
class ParsedScoreRow:
    raw_line: str
    extracted_name: str
    raw_score_text: str
    extracted_score: int
    ocr_confidence: float
    warnings: tuple[str, ...] = ()


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.translate(_SPACE_TRANSLATION).strip().split())


def _fold_keyword(token: str) -> str:
    folded = token.translate(_TURKISH_FOLD_MAP).upper()
    return re.sub(r"[^A-Z0-9]+", "", folded)


def strip_rank_prefix(text: str) -> str:
    if not text:
        return ""
    cleaned = _normalize_whitespace(text)
    stripped = _RANK_PREFIX_RE.sub("", cleaned, count=1).strip()
    return stripped


def _parse_exact_score(cleaned: str, original_raw: str) -> ParsedScore | None:
    if not cleaned:
        return None
    if _DATE_RE.match(cleaned) or _TIME_RE.match(cleaned) or _RANK_TOKEN_RE.match(cleaned):
        return None
    if "%" in cleaned or ":" in cleaned or "/" in cleaned or cleaned.startswith("-") or cleaned.startswith("#"):
        return None

    # Suffix formats (K, M, B)
    m_grp_comma = _SUFFIX_GROUPED_COMMA_RE.match(cleaned)
    if m_grp_comma:
        num_str = m_grp_comma.group("num").replace(",", "")
        mult = _SUFFIX_MULTIPLIERS[m_grp_comma.group("suffix").upper()]
        try:
            val = int((Decimal(num_str) * mult).to_integral_value())
            return ParsedScore(value=val, raw_text=original_raw, digit_repaired=False, format_kind="suffix")
        except InvalidOperation:
            return None

    m_grp_dot = _SUFFIX_GROUPED_DOT_RE.match(cleaned)
    if m_grp_dot:
        num_str = m_grp_dot.group("num").replace(".", "").replace(",", ".")
        mult = _SUFFIX_MULTIPLIERS[m_grp_dot.group("suffix").upper()]
        try:
            val = int((Decimal(num_str) * mult).to_integral_value())
            return ParsedScore(value=val, raw_text=original_raw, digit_repaired=False, format_kind="suffix")
        except InvalidOperation:
            return None

    m_simple = _SUFFIX_SIMPLE_RE.match(cleaned)
    if m_simple:
        num_str = m_simple.group("num").replace(",", ".")
        mult = _SUFFIX_MULTIPLIERS[m_simple.group("suffix").upper()]
        try:
            val = int((Decimal(num_str) * mult).to_integral_value())
            return ParsedScore(value=val, raw_text=original_raw, digit_repaired=False, format_kind="suffix")
        except InvalidOperation:
            return None

    # Thousands-separated integers
    if _COMMA_THOUSANDS_RE.match(cleaned):
        return ParsedScore(
            value=int(cleaned.replace(",", "")),
            raw_text=original_raw,
            digit_repaired=False,
            format_kind="thousands_sep",
        )
    if _DOT_THOUSANDS_RE.match(cleaned):
        return ParsedScore(
            value=int(cleaned.replace(".", "")),
            raw_text=original_raw,
            digit_repaired=False,
            format_kind="thousands_sep",
        )
    if _SPACE_THOUSANDS_RE.match(cleaned):
        return ParsedScore(
            value=int(cleaned.replace(" ", "")),
            raw_text=original_raw,
            digit_repaired=False,
            format_kind="thousands_sep",
        )

    # Plain integer
    if _PLAIN_INT_RE.match(cleaned):
        return ParsedScore(
            value=int(cleaned),
            raw_text=original_raw,
            digit_repaired=False,
            format_kind="integer",
        )

    return None


def parse_score_token(text: str, *, allow_digit_repair: bool = True) -> ParsedScore | None:
    if not isinstance(text, str):
        return None
    cleaned = _normalize_whitespace(text)
    if not cleaned:
        return None

    exact = _parse_exact_score(cleaned, text)
    if exact is not None:
        return exact

    if not allow_digit_repair:
        return None

    # Pre-reject non-score shapes before repair
    if (
        _DATE_RE.match(cleaned)
        or _TIME_RE.match(cleaned)
        or _RANK_TOKEN_RE.match(cleaned)
        or "%" in cleaned
        or ":" in cleaned
        or "/" in cleaned
        or cleaned.startswith("-")
        or cleaned.startswith("#")
        or cleaned.endswith(".")
        or cleaned.endswith(")")
    ):
        return None

    # Peel trailing suffix K/M/B first so 'B' is not repaired to '8'
    suffix = ""
    mantissa = cleaned
    if len(cleaned) >= 2 and cleaned[-1].upper() in _SUFFIX_MULTIPLIERS:
        # Only treat trailing K/M/B as suffix if preceded by digit/repairable/sep
        suffix = cleaned[-1]
        mantissa = cleaned[:-1].rstrip()

    if not mantissa:
        return None

    digit_count = 0
    repaired_count = 0
    non_sep_count = 0
    repaired_chars: list[str] = []

    for ch in mantissa:
        if ch in ",. ":
            repaired_chars.append(ch)
            continue
        non_sep_count += 1
        if "0" <= ch <= "9":
            digit_count += 1
            repaired_chars.append(ch)
        elif ch in _DIGIT_REPAIR_MAP:
            repaired_count += 1
            repaired_chars.append(_DIGIT_REPAIR_MAP[ch])
        else:
            return None

    if digit_count < 2 or repaired_count == 0 or repaired_count > 3:
        return None
    if non_sep_count == 0 or (digit_count / non_sep_count) < 0.5:
        return None

    repaired_str = "".join(repaired_chars) + suffix
    if repaired_str == cleaned:
        return None

    parsed = _parse_exact_score(repaired_str, text)
    if parsed is None:
        return None

    return ParsedScore(
        value=parsed.value,
        raw_text=text,
        digit_repaired=True,
        format_kind="repaired",
    )


def is_header_or_noise_line(text: str) -> bool:
    cleaned = _normalize_whitespace(text)
    if not cleaned:
        return True
    if _BANNER_LINE_RE.match(cleaned):
        return True
    if _DATE_RE.match(cleaned) or _TIME_RE.match(cleaned):
        return True

    raw_tokens = [tok for tok in re.split(r"[\s|]+", cleaned) if tok]
    if not raw_tokens:
        return True

    effective_raw: list[str] = []
    effective_folded: list[str] = []
    prev_folded = ""
    for tok in raw_tokens:
        stripped_tok = tok.strip(".,-:#()[]")
        if prev_folded in _BANNER_KEYWORDS and _BANNER_NUM_RE.match(stripped_tok):
            prev_folded = ""
            continue
        fld = _fold_keyword(tok)
        effective_raw.append(tok)
        if fld:
            effective_folded.append(fld)
        prev_folded = fld

    if not effective_folded:
        return True

    if all(t in _HEADER_KEYWORDS for t in effective_folded):
        return True

    header_hits = sum(1 for t in effective_folded if t in _HEADER_KEYWORDS)
    has_score = any(parse_score_token(tok, allow_digit_repair=False) is not None for tok in effective_raw)

    if header_hits >= 2 and not has_score:
        return True

    alpha_words = [t for t in effective_raw if sum(ch.isalpha() for ch in t) >= 2]
    if len(alpha_words) >= 4 and not has_score:
        return True

    return False


def _coerce_box(item: OcrBox | Sequence[Any] | Mapping[str, Any]) -> OcrBox | None:
    if isinstance(item, OcrBox):
        bbox = item.bbox
        text = item.text
        conf = float(item.confidence)
    elif isinstance(item, Mapping):
        raw_bbox = item["bbox"]
        bbox = tuple((float(pt[0]), float(pt[1])) for pt in raw_bbox)  # type: ignore[assignment]
        text = str(item.get("text", ""))
        conf = float(item.get("confidence", item.get("conf", 0.0)))
    elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)) and len(item) >= 3:
        raw_bbox = item[0]
        bbox = tuple((float(pt[0]), float(pt[1])) for pt in raw_bbox)  # type: ignore[assignment]
        text = str(item[1])
        conf = float(item[2])
    else:
        return None

    if len(bbox) != 4 or not _normalize_whitespace(text):
        return None
    return OcrBox(bbox=bbox, text=text, confidence=conf)


def cluster_boxes_into_rows(
    boxes: Sequence[OcrBox | Sequence[Any] | Mapping[str, Any]],
) -> list[list[OcrBox]]:
    normalized: list[OcrBox] = []
    for item in boxes:
        coerced = _coerce_box(item)
        if coerced is not None:
            normalized.append(coerced)

    if not normalized:
        return []

    heights = [box.height for box in normalized]
    median_h = statistics.median(heights) if heights else 24.0
    mean_tol = max(10.0, 0.55 * median_h)
    anchor_tol = max(10.0, 0.85 * median_h)

    sorted_boxes = sorted(normalized, key=lambda b: (b.y_center, b.x_left))

    rows: list[list[OcrBox]] = []
    current_row: list[OcrBox] = [sorted_boxes[0]]
    row_sum_y = sorted_boxes[0].y_center
    row_first_y = sorted_boxes[0].y_center

    for box in sorted_boxes[1:]:
        row_mean_y = row_sum_y / len(current_row)
        if (
            abs(box.y_center - row_mean_y) <= mean_tol
            and abs(box.y_center - row_first_y) <= anchor_tol
        ):
            current_row.append(box)
            row_sum_y += box.y_center
        else:
            current_row.sort(key=lambda b: (b.x_left, b.x_right))
            rows.append(current_row)
            current_row = [box]
            row_sum_y = box.y_center
            row_first_y = box.y_center

    current_row.sort(key=lambda b: (b.x_left, b.x_right))
    rows.append(current_row)
    return rows


def _detect_header_anchors(row: list[OcrBox]) -> tuple[bool, float | None, int | None]:
    raw_line = " ".join(_normalize_whitespace(b.text) for b in row)

    if not is_header_or_noise_line(raw_line):
        return False, None, None

    # Check pipe-delimited single box header column index
    if len(row) == 1 and "|" in raw_line:
        pipe_segs = [seg.strip() for seg in raw_line.split("|") if seg.strip()]
        folded_segs = [_fold_keyword(seg) for seg in pipe_segs]
        col_idx = next(
            (idx for idx, f in enumerate(folded_segs) if f in _SCORE_HEADER_KEYWORDS),
            None,
        )
        if col_idx is None:
            col_idx = next(
                (
                    idx
                    for idx, seg in enumerate(pipe_segs)
                    if any(_fold_keyword(tok) in _SCORE_HEADER_KEYWORDS for tok in seg.split())
                ),
                None,
            )
        if col_idx is not None:
            return True, None, col_idx

    score_anchor_x: float | None = None
    for box in row:
        tokens = [t for t in re.split(r"[\s|]+", _normalize_whitespace(box.text)) if t]
        for tok in tokens:
            if _fold_keyword(tok) in _SCORE_HEADER_KEYWORDS:
                score_anchor_x = box.x_center
                break
        if score_anchor_x is not None:
            break

    return True, score_anchor_x, None


def _is_pure_numeric_intermediate(text: str) -> bool:
    cleaned = _normalize_whitespace(text)
    if not cleaned:
        return True
    return bool(_PURE_NUMERIC_COL_RE.match(cleaned))


def _build_name_from_parts(parts: list[str]) -> str:
    if not parts:
        return ""
    kept: list[str] = [parts[0]]
    for part in parts[1:]:
        if _is_pure_numeric_intermediate(part):
            continue
        kept.append(part)
    joined = _normalize_whitespace(" ".join(kept))
    if not joined:
        joined = _normalize_whitespace(" ".join(parts))
    return strip_rank_prefix(joined)


def _parse_single_string_row(
    raw_text: str,
    confidence: float,
    score_col_index: int | None,
) -> ParsedScoreRow | None:
    cleaned = _normalize_whitespace(raw_text)
    if not cleaned:
        return None

    # 1. Pipe-delimited row
    if "|" in cleaned:
        segments = [seg.strip() for seg in cleaned.split("|")]
        non_empty = [(idx, seg) for idx, seg in enumerate(segments) if seg]
        if len(non_empty) >= 2:
            chosen_idx: int | None = None
            chosen_score: ParsedScore | None = None

            if score_col_index is not None and 0 < score_col_index < len(segments):
                seg_txt = segments[score_col_index].strip()
                if seg_txt:
                    parsed = parse_score_token(seg_txt, allow_digit_repair=True)
                    if parsed is not None:
                        chosen_idx = score_col_index
                        chosen_score = parsed

            if chosen_score is None:
                for allow_repair in (False, True):
                    for orig_idx, seg_txt in reversed(non_empty[1:]):
                        parsed = parse_score_token(seg_txt, allow_digit_repair=allow_repair)
                        if parsed is not None:
                            chosen_idx = orig_idx
                            chosen_score = parsed
                            break
                    if chosen_score is not None:
                        break

            if chosen_score is not None and chosen_idx is not None:
                left_parts = [
                    seg.strip()
                    for idx, seg in enumerate(segments[:chosen_idx])
                    if seg.strip()
                ]
                if left_parts and _PURE_RANK_BOX_RE.match(left_parts[0]) and len(left_parts) >= 2:
                    left_parts = left_parts[1:]
                extracted_name = _build_name_from_parts(left_parts)
                if extracted_name and any(ch.isalnum() for ch in extracted_name):
                    warnings = ("digit_repaired",) if chosen_score.digit_repaired else ()
                    return ParsedScoreRow(
                        raw_line=cleaned,
                        extracted_name=extracted_name,
                        raw_score_text=chosen_score.raw_text.strip(),
                        extracted_score=chosen_score.value,
                        ocr_confidence=confidence,
                        warnings=warnings,
                    )
        return None

    # 2. Multi-space delimited segments
    space_segments = [seg.strip() for seg in re.split(r"\s{2,}", raw_text.translate(_SPACE_TRANSLATION)) if seg.strip()]
    if len(space_segments) >= 2:
        if len(space_segments) >= 3 and _PURE_RANK_BOX_RE.match(space_segments[0]):
            space_segments = space_segments[1:]
        chosen_seg_idx: int | None = None
        chosen_seg_score: ParsedScore | None = None
        for allow_repair in (False, True):
            for idx in range(len(space_segments) - 1, 0, -1):
                parsed = parse_score_token(space_segments[idx], allow_digit_repair=allow_repair)
                if parsed is not None:
                    chosen_seg_idx = idx
                    chosen_seg_score = parsed
                    break
            if chosen_seg_score is not None:
                break
        if chosen_seg_score is not None and chosen_seg_idx is not None:
            extracted_name = _build_name_from_parts(space_segments[:chosen_seg_idx])
            if extracted_name and any(ch.isalnum() for ch in extracted_name):
                warnings = ("digit_repaired",) if chosen_seg_score.digit_repaired else ()
                return ParsedScoreRow(
                    raw_line=cleaned,
                    extracted_name=extracted_name,
                    raw_score_text=chosen_seg_score.raw_text.strip(),
                    extracted_score=chosen_seg_score.value,
                    ocr_confidence=confidence,
                    warnings=warnings,
                )

    # 3. Single-spaced line: strip leading rank prefix first
    no_rank = strip_rank_prefix(cleaned)
    if not no_rank:
        return None

    for allow_repair in (False, True):
        # Try trailing space-grouped integer first (e.g. "Turkceli_Uye 1 250 000")
        if not allow_repair:
            m_space = _TRAILING_SPACE_SCORE_RE.match(no_rank)
            if m_space:
                parsed = parse_score_token(m_space.group("score"), allow_digit_repair=False)
                if parsed is not None:
                    left_parts = m_space.group("left").strip().split()
                    extracted_name = _build_name_from_parts(left_parts)
                    if extracted_name and any(ch.isalnum() for ch in extracted_name):
                        return ParsedScoreRow(
                            raw_line=cleaned,
                            extracted_name=extracted_name,
                            raw_score_text=parsed.raw_text.strip(),
                            extracted_score=parsed.value,
                            ocr_confidence=confidence,
                            warnings=(),
                        )

        # Try trailing number + space + K/M/B (e.g. "ShadowWolf 1.2 M")
        m_sfx = _TRAILING_SUFFIX_SPACE_RE.match(no_rank)
        if m_sfx:
            parsed = parse_score_token(m_sfx.group("score"), allow_digit_repair=allow_repair)
            if parsed is not None:
                left_parts = m_sfx.group("left").strip().split()
                extracted_name = _build_name_from_parts(left_parts)
                if extracted_name and any(ch.isalnum() for ch in extracted_name):
                    warnings = ("digit_repaired",) if parsed.digit_repaired else ()
                    return ParsedScoreRow(
                        raw_line=cleaned,
                        extracted_name=extracted_name,
                        raw_score_text=parsed.raw_text.strip(),
                        extracted_score=parsed.value,
                        ocr_confidence=confidence,
                        warnings=warnings,
                    )

        # Try trailing single token
        m_tok = _TRAILING_TOKEN_RE.match(no_rank)
        if m_tok:
            parsed = parse_score_token(m_tok.group("score"), allow_digit_repair=allow_repair)
            if parsed is not None:
                left_str = m_tok.group("left").strip()
                left_tokens = left_str.split()
                # Drop trailing intermediate numeric columns like Lv.68 or 14 if name remains
                while len(left_tokens) >= 2 and _is_pure_numeric_intermediate(left_tokens[-1]):
                    left_tokens.pop()
                extracted_name = _normalize_whitespace(" ".join(left_tokens))
                if extracted_name and any(ch.isalnum() for ch in extracted_name):
                    warnings = ("digit_repaired",) if parsed.digit_repaired else ()
                    return ParsedScoreRow(
                        raw_line=cleaned,
                        extracted_name=extracted_name,
                        raw_score_text=parsed.raw_text.strip(),
                        extracted_score=parsed.value,
                        ocr_confidence=confidence,
                        warnings=warnings,
                    )

    return None


def reconstruct_rows_and_parse(
    boxes: Sequence[OcrBox | Sequence[Any] | Mapping[str, Any]],
) -> list[ParsedScoreRow]:
    clustered_rows = cluster_boxes_into_rows(boxes)
    if not clustered_rows:
        return []

    score_anchor_x: float | None = None
    score_col_index: int | None = None
    parsed_rows: list[ParsedScoreRow] = []

    for row in clustered_rows:
        is_header, anchor_x, col_idx = _detect_header_anchors(row)
        if is_header:
            if anchor_x is not None:
                score_anchor_x = anchor_x
            if col_idx is not None:
                score_col_index = col_idx
            continue

        raw_line = _normalize_whitespace(" ".join(_normalize_whitespace(b.text) for b in row))
        if not raw_line:
            continue

        # Strip leftmost isolated rank box when present
        remaining = list(row)
        first_txt = _normalize_whitespace(remaining[0].text)
        if len(remaining) >= 3 and _PURE_RANK_BOX_RE.match(first_txt):
            remaining = remaining[1:]
        elif len(remaining) == 2 and _RANK_TOKEN_RE.match(first_txt):
            remaining = remaining[1:]

        if len(remaining) == 1:
            single_box = remaining[0]
            parsed_single = _parse_single_string_row(
                single_box.text,
                single_box.confidence,
                score_col_index,
            )
            if parsed_single is not None:
                parsed_rows.append(
                    ParsedScoreRow(
                        raw_line=raw_line,
                        extracted_name=parsed_single.extracted_name,
                        raw_score_text=parsed_single.raw_score_text,
                        extracted_score=parsed_single.extracted_score,
                        ocr_confidence=parsed_single.ocr_confidence,
                        warnings=parsed_single.warnings,
                    )
                )
            continue

        # Multi-box row (len(remaining) >= 2)
        chosen_idx: int | None = None
        chosen_parsed: ParsedScore | None = None

        if score_anchor_x is not None:
            candidates: list[tuple[int, OcrBox, ParsedScore]] = []
            for idx in range(1, len(remaining)):
                box = remaining[idx]
                parsed = parse_score_token(box.text, allow_digit_repair=True)
                if parsed is not None:
                    candidates.append((idx, box, parsed))
            if candidates:
                # Prefer candidate closest to header-anchored score column X, breaking ties by exactness
                chosen_idx, _, chosen_parsed = min(
                    candidates,
                    key=lambda item: (
                        abs(item[1].x_center - score_anchor_x),
                        1 if item[2].digit_repaired else 0,
                        -item[0],
                    ),
                )
        else:
            for allow_repair in (False, True):
                candidates = []
                for idx in range(1, len(remaining)):
                    box = remaining[idx]
                    parsed = parse_score_token(box.text, allow_digit_repair=allow_repair)
                    if parsed is not None:
                        candidates.append((idx, box, parsed))

                if not candidates:
                    continue

                # Choose rightmost valid score token
                chosen_idx, _, chosen_parsed = candidates[-1]
                break

        if chosen_parsed is None or chosen_idx is None:
            continue

        name_boxes = remaining[:chosen_idx]
        name_parts = [_normalize_whitespace(b.text) for b in name_boxes]
        extracted_name = _build_name_from_parts(name_parts)
        if not extracted_name or not any(ch.isalnum() for ch in extracted_name):
            continue

        used_boxes = [b for i, b in enumerate(name_boxes) if i == 0 or not _is_pure_numeric_intermediate(b.text)]
        used_boxes.append(remaining[chosen_idx])
        row_conf = min(b.confidence for b in used_boxes)

        warnings = ("digit_repaired",) if chosen_parsed.digit_repaired else ()
        parsed_rows.append(
            ParsedScoreRow(
                raw_line=raw_line,
                extracted_name=extracted_name,
                raw_score_text=_normalize_whitespace(chosen_parsed.raw_text),
                extracted_score=chosen_parsed.value,
                ocr_confidence=row_conf,
                warnings=warnings,
            )
        )

    return parsed_rows
