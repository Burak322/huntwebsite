from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.services.player_matcher import strip_clan_tags
from app.services.score_parser import (
    _BANNER_KEYWORDS,
    _BANNER_LINE_RE,
    _BANNER_NUM_RE,
    _DATE_RE,
    _HEADER_KEYWORDS,
    _PURE_NUMERIC_COL_RE,
    _PURE_RANK_BOX_RE,
    _RANK_TOKEN_RE,
    _TIME_RE,
    OcrBox,
    _fold_keyword,
    _normalize_whitespace,
    cluster_boxes_into_rows,
    parse_score_token,
    strip_rank_prefix,
)

_ROSTER_HEADER_KEYWORDS = frozenset({
    *_HEADER_KEYWORDS,
    "MEMBER",
    "MEMBERS",
    "UYE",
    "UYELER",
    "UYELERI",
    "UYELERIMIZ",
    "OYUNCULARI",
    "ROSTER",
    "LISTE",
    "LISTESI",
    "LIST",
    "ROLE",
    "ROL",
    "RUTBE",
    "RUTBESI",
    "KULE",
    "TOWER",
    "TITLE",
    "UNVAN",
    "STATUS",
    "DURUM",
    "DURUMU",
    "ONLINE",
    "OFFLINE",
    "CEVRIMICI",
    "CEVRIMDISI",
    "ACTIVE",
    "AKTIF",
    "INACTIVE",
    "PASIF",
    "LAST",
    "SEEN",
    "SON",
    "GORULME",
    "DONATION",
    "BAGIS",
    "CONTRIBUTION",
    "KATKI",
    "MANAGE",
    "YONET",
    "INVITE",
    "DAVET",
    "SEARCH",
    "ARA",
    "KICK",
    "AT",
    "NICK",
    "NICKNAME",
    "ISIMLER",
})

_NAME_HEADER_KEYWORDS = frozenset({
    "PLAYER",
    "PLAYERS",
    "OYUNCU",
    "OYUNCULAR",
    "OYUNCULARI",
    "NAME",
    "ISIM",
    "ISIMLER",
    "AD",
    "MEMBER",
    "MEMBERS",
    "UYE",
    "UYELER",
    "UYELERI",
    "NICK",
    "NICKNAME",
})

_ROLE_STATUS_TOKENS = frozenset({
    "ONLINE",
    "OFFLINE",
    "CEVRIMICI",
    "CEVRIMDISI",
    "ACTIVE",
    "AKTIF",
    "INACTIVE",
    "PASIF",
    "LEADER",
    "LIDER",
    "COLEADER",
    "VICE",
    "OFFICER",
    "SUBAY",
    "ELDER",
    "KIDEMLI",
    "MEMBER",
    "UYE",
    "RECRUIT",
    "YENI",
    "ADMIN",
    "YONETICI",
    "MASTER",
    "AGO",
    "ONCE",
    "R1",
    "R2",
    "R3",
    "R4",
    "R5",
})

_RATIO_RE = re.compile(r"^\d{1,4}\s*/\s*\d{1,4}$")
_TIME_AGO_RE = re.compile(
    r"^(?:\d{1,3}\s*(?:s|sn|sec|m|min|dk|h|hr|sa|d|g|gun|gün|w|hf|mo|ay)(?:\s*(?:ago|once|önce))?)$",
    re.IGNORECASE,
)
_PURE_TAG_RE = re.compile(r"^(?:\[[^\[\]]{1,16}\]|<[^<>]{1,16}>|\([^()]{1,16}\)|\{[^{}]{1,16}\})$")
_SMALL_INT_RE = re.compile(r"^\d{1,3}$")
_CLAN_RANK_RE = re.compile(r"^R[1-5]$", re.IGNORECASE)
_TOWER_LEVEL_RE = re.compile(r"^[I\u0130ıi](?:10|[1-9])$")


@dataclass(frozen=True, slots=True)
class ParsedRosterRow:
    raw_line: str
    extracted_name: str
    clean_name: str
    detected_number: int | None
    ocr_confidence: float
    detected_rank: str | None = None
    detected_tower_level: str | None = None
    warnings: tuple[str, ...] = ()


def _normalize_rank_token(token: str) -> str | None:
    cleaned = _normalize_whitespace(token)
    if _CLAN_RANK_RE.match(cleaned):
        return cleaned.upper()
    return None


def _normalize_tower_token(token: str) -> str | None:
    cleaned = _normalize_whitespace(token)
    if _TOWER_LEVEL_RE.match(cleaned):
        return "I" + cleaned[1:]
    return None


def _fold_tr_key(name: str) -> str:
    return name.replace("\u0130", "i").replace("I", "ı").casefold()


def is_roster_header_or_noise_line(text: str) -> bool:
    cleaned = _normalize_whitespace(text)
    if not cleaned:
        return True
    if _BANNER_LINE_RE.match(cleaned) or _RATIO_RE.match(cleaned):
        return True
    if _DATE_RE.match(cleaned) or _TIME_RE.match(cleaned) or _TIME_AGO_RE.match(cleaned):
        return True

    raw_tokens = [tok for tok in re.split(r"[\s|]+", cleaned) if tok]
    if not raw_tokens:
        return True

    effective_raw: list[str] = []
    effective_folded: list[str] = []
    prev_folded = ""
    for tok in raw_tokens:
        if _RATIO_RE.match(tok):
            prev_folded = ""
            continue
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

    all_noise_keywords = _ROSTER_HEADER_KEYWORDS | _ROLE_STATUS_TOKENS
    if all(t in all_noise_keywords for t in effective_folded):
        return True

    header_hits = sum(1 for t in effective_folded if t in _ROSTER_HEADER_KEYWORDS)
    has_score = any(parse_score_token(tok, allow_digit_repair=False) is not None for tok in effective_raw)
    non_keyword_alpha = [
        t for t in effective_raw
        if sum(ch.isalpha() for ch in t) >= 2 and _fold_keyword(t) not in all_noise_keywords
    ]

    if header_hits >= 2 and not has_score and not non_keyword_alpha:
        return True

    # Sentence / announcement prose noise (many alpha words with no roster tag/role/score markers)
    alpha_words = [t for t in effective_raw if sum(ch.isalpha() for ch in t) >= 2]
    has_tag_marker = any(ch in cleaned for ch in "[]<>|")
    if len(alpha_words) >= 5 and header_hits == 0 and not has_score and not has_tag_marker:
        return True

    return False


def _is_metadata_box(text: str) -> bool:
    cleaned = _normalize_whitespace(text)
    if not cleaned:
        return True
    if (
        _PURE_RANK_BOX_RE.match(cleaned)
        or _RANK_TOKEN_RE.match(cleaned)
        or _PURE_NUMERIC_COL_RE.match(cleaned)
        or _RATIO_RE.match(cleaned)
        or _DATE_RE.match(cleaned)
        or _TIME_RE.match(cleaned)
        or _TIME_AGO_RE.match(cleaned)
        or "%" in cleaned
    ):
        return True
    if parse_score_token(cleaned, allow_digit_repair=False) is not None:
        return True

    tokens = [t for t in cleaned.split() if t]
    if not tokens:
        return True
    if all(
        _fold_keyword(t) in _ROLE_STATUS_TOKENS
        or bool(_TIME_AGO_RE.match(t))
        or bool(_PURE_NUMERIC_COL_RE.match(t))
        or bool(_TOWER_LEVEL_RE.match(t))
        for t in tokens
    ):
        return True
    return False


def _is_valid_player_name(name: str) -> bool:
    clean = strip_clan_tags(_normalize_whitespace(name))
    if not (2 <= len(clean) <= 60):
        return False
    if not any(ch.isalpha() for ch in clean):
        return False
    if (
        _PURE_NUMERIC_COL_RE.match(clean)
        or _TIME_AGO_RE.match(clean)
        or _DATE_RE.match(clean)
        or _TIME_RE.match(clean)
        or _RATIO_RE.match(clean)
        or _TOWER_LEVEL_RE.match(clean)
    ):
        return False
    tokens = clean.split()
    if all(
        _fold_keyword(t) in (_ROSTER_HEADER_KEYWORDS | _ROLE_STATUS_TOKENS)
        or bool(_TOWER_LEVEL_RE.match(t))
        for t in tokens
    ):
        return False
    return True


def _extract_number_from_text(text: str) -> int | None:
    parsed = parse_score_token(text, allow_digit_repair=False)
    if parsed is not None:
        return parsed.value
    lvl_match = re.match(r"^(?:LV|LVL)\.?\s*(\d{1,4})$", text.strip(), re.IGNORECASE)
    if lvl_match:
        return int(lvl_match.group(1))
    return None


def _detect_roster_header(row: list[OcrBox]) -> tuple[bool, float | None, int | None]:
    raw_line = " ".join(_normalize_whitespace(b.text) for b in row)
    if not is_roster_header_or_noise_line(raw_line):
        return False, None, None

    if len(row) == 1 and "|" in raw_line:
        pipe_segs = [seg.strip() for seg in raw_line.split("|") if seg.strip()]
        col_idx = next(
            (idx for idx, seg in enumerate(pipe_segs) if _fold_keyword(seg) in _NAME_HEADER_KEYWORDS),
            None,
        )
        if col_idx is None:
            col_idx = next(
                (
                    idx
                    for idx, seg in enumerate(pipe_segs)
                    if any(_fold_keyword(tok) in _NAME_HEADER_KEYWORDS for tok in seg.split())
                ),
                None,
            )
        if col_idx is not None:
            return True, None, col_idx

    name_anchor_x: float | None = None
    for box in row:
        tokens = [t for t in re.split(r"[\s|]+", _normalize_whitespace(box.text)) if t]
        if any(_fold_keyword(tok) in _NAME_HEADER_KEYWORDS for tok in tokens):
            name_anchor_x = box.x_center
            break

    return True, name_anchor_x, None


def _parse_single_roster_box(
    raw_text: str,
    confidence: float,
    name_col_index: int | None,
) -> ParsedRosterRow | None:
    cleaned = _normalize_whitespace(raw_text)
    if not cleaned:
        return None

    # 1. Pipe-delimited or multi-space delimited single box
    segments: list[str] | None = None
    if "|" in cleaned:
        segments = [seg.strip() for seg in cleaned.split("|") if seg.strip()]
    else:
        raw_norm = raw_text.replace("\u00a0", " ")
        space_segs = [seg.strip() for seg in re.split(r"\s{2,}", raw_norm) if seg.strip()]
        if len(space_segs) >= 2:
            segments = space_segs

    if segments and len(segments) >= 2:
        offset = 0
        if len(segments) >= 2 and (_PURE_RANK_BOX_RE.match(segments[0]) or _SMALL_INT_RE.match(segments[0])):
            offset = 1
        trimmed_segs = segments[offset:]

        detected_num: int | None = None
        detected_rank: str | None = None
        detected_tower: str | None = None
        for seg in trimmed_segs:
            for tok in seg.split():
                r_tok = _normalize_rank_token(tok)
                if r_tok is not None and detected_rank is None:
                    detected_rank = r_tok
                t_tok = _normalize_tower_token(tok)
                if t_tok is not None and detected_tower is None:
                    detected_tower = t_tok
        for seg in reversed(trimmed_segs):
            val = _extract_number_from_text(seg)
            if val is not None:
                detected_num = val
                break

        chosen_name: str | None = None
        if name_col_index is not None and 0 <= name_col_index < len(segments):
            cand_seg = strip_rank_prefix(segments[name_col_index])
            if cand_seg and not _is_metadata_box(cand_seg) and _is_valid_player_name(cand_seg):
                chosen_name = cand_seg

        if chosen_name is None:
            for seg in trimmed_segs:
                cand_seg = strip_rank_prefix(seg)
                if cand_seg and not _is_metadata_box(cand_seg) and _is_valid_player_name(cand_seg):
                    chosen_name = cand_seg
                    break

        if chosen_name is not None:
            clean_name = strip_clan_tags(chosen_name)
            return ParsedRosterRow(
                raw_line=cleaned,
                extracted_name=chosen_name,
                clean_name=clean_name,
                detected_number=detected_num,
                ocr_confidence=confidence,
                detected_rank=detected_rank,
                detected_tower_level=detected_tower,
            )
        return None

    # 2. Single-spaced line: strip rank prefix & peel trailing metadata tokens
    no_rank = strip_rank_prefix(cleaned)
    if not no_rank:
        return None

    tokens = no_rank.split()
    detected_num = None
    detected_rank = None
    detected_tower = None

    # Check if two trailing tokens form a time-ago expression like "2sa önce" or "3h ago"
    while len(tokens) >= 2:
        tail = tokens[-1]
        if len(tokens) >= 3 and _fold_keyword(tail) in ("AGO", "ONCE") and _TIME_AGO_RE.match(tokens[-2]):
            tokens = tokens[:-2]
            continue
        if _is_metadata_box(tail):
            r_tok = _normalize_rank_token(tail)
            if r_tok is not None and detected_rank is None:
                detected_rank = r_tok
            t_tok = _normalize_tower_token(tail)
            if t_tok is not None and detected_tower is None:
                detected_tower = t_tok
            num_val = _extract_number_from_text(tail)
            if num_val is not None and detected_num is None:
                detected_num = num_val
            tokens.pop()
            continue
        break

    candidate_name = _normalize_whitespace(" ".join(tokens))
    if not _is_valid_player_name(candidate_name):
        return None

    clean_name = strip_clan_tags(candidate_name)
    return ParsedRosterRow(
        raw_line=cleaned,
        extracted_name=candidate_name,
        clean_name=clean_name,
        detected_number=detected_num,
        ocr_confidence=confidence,
        detected_rank=detected_rank,
        detected_tower_level=detected_tower,
    )


def reconstruct_roster_candidates(
    boxes: Sequence[OcrBox | Sequence[Any] | Mapping[str, Any]],
) -> list[ParsedRosterRow]:
    clustered_rows = cluster_boxes_into_rows(boxes)
    if not clustered_rows:
        return []

    name_anchor_x: float | None = None
    name_col_index: int | None = None
    raw_candidates: list[ParsedRosterRow] = []

    for row in clustered_rows:
        is_header, anchor_x, col_idx = _detect_roster_header(row)
        if is_header:
            if anchor_x is not None:
                name_anchor_x = anchor_x
            if col_idx is not None:
                name_col_index = col_idx
            continue

        raw_line = _normalize_whitespace(" ".join(_normalize_whitespace(b.text) for b in row))
        if not raw_line:
            continue

        remaining = list(row)
        first_txt = _normalize_whitespace(remaining[0].text)
        if len(remaining) >= 2 and (_PURE_RANK_BOX_RE.match(first_txt) or _SMALL_INT_RE.match(first_txt)):
            remaining = remaining[1:]

        if len(remaining) == 1:
            box = remaining[0]
            parsed = _parse_single_roster_box(box.text, box.confidence, name_col_index)
            if parsed is not None:
                raw_candidates.append(
                    ParsedRosterRow(
                        raw_line=raw_line,
                        extracted_name=parsed.extracted_name,
                        clean_name=parsed.clean_name,
                        detected_number=parsed.detected_number,
                        ocr_confidence=parsed.ocr_confidence,
                        detected_rank=parsed.detected_rank,
                        detected_tower_level=parsed.detected_tower_level,
                        warnings=parsed.warnings,
                    )
                )
            continue

        # Multi-box row: find optional numeric score, rank, tower level & player name box
        detected_num: int | None = None
        detected_rank: str | None = None
        detected_tower: str | None = None
        for box in remaining:
            for tok in _normalize_whitespace(box.text).split():
                r_tok = _normalize_rank_token(tok)
                if r_tok is not None and detected_rank is None:
                    detected_rank = r_tok
                t_tok = _normalize_tower_token(tok)
                if t_tok is not None and detected_tower is None:
                    detected_tower = t_tok
        for box in reversed(remaining):
            txt = _normalize_whitespace(box.text)
            val = _extract_number_from_text(txt)
            if val is not None:
                detected_num = val
                break

        # Build merged name candidates (e.g. "[APEX]" + "DemirKurt")
        name_candidates: list[tuple[float, str, float]] = []  # (x_center, name, conf)
        idx = 0
        while idx < len(remaining):
            box = remaining[idx]
            txt = _normalize_whitespace(box.text)
            if _PURE_TAG_RE.match(txt) and idx + 1 < len(remaining):
                next_box = remaining[idx + 1]
                next_txt = strip_rank_prefix(_normalize_whitespace(next_box.text))
                if next_txt and not _is_metadata_box(next_txt) and _is_valid_player_name(next_txt):
                    merged = f"{txt} {next_txt}"
                    name_candidates.append(
                        (next_box.x_center, merged, min(box.confidence, next_box.confidence))
                    )
                    idx += 2
                    continue

            stripped = strip_rank_prefix(txt)
            if stripped and not _is_metadata_box(stripped) and _is_valid_player_name(stripped):
                name_candidates.append((box.x_center, stripped, box.confidence))
            idx += 1

        if not name_candidates:
            continue

        if name_anchor_x is not None:
            _, chosen_name, chosen_conf = min(
                name_candidates, key=lambda item: abs(item[0] - name_anchor_x)
            )
        else:
            _, chosen_name, chosen_conf = name_candidates[0]

        clean_name = strip_clan_tags(chosen_name)
        if not _is_valid_player_name(clean_name):
            continue

        raw_candidates.append(
            ParsedRosterRow(
                raw_line=raw_line,
                extracted_name=chosen_name,
                clean_name=clean_name,
                detected_number=detected_num,
                ocr_confidence=chosen_conf,
                detected_rank=detected_rank,
                detected_tower_level=detected_tower,
            )
        )

    # Deduplicate by Turkish-folded clean_name within the same image
    deduped: list[ParsedRosterRow] = []
    index_by_key: dict[str, int] = {}
    for cand in raw_candidates:
        key = _fold_tr_key(cand.clean_name)
        existing_idx = index_by_key.get(key)
        if existing_idx is None:
            index_by_key[key] = len(deduped)
            deduped.append(cand)
        else:
            prev = deduped[existing_idx]
            best = cand if cand.ocr_confidence > prev.ocr_confidence else prev
            merged_num = best.detected_number if best.detected_number is not None else prev.detected_number
            if merged_num is None:
                merged_num = cand.detected_number
            merged_rank = best.detected_rank or prev.detected_rank or cand.detected_rank
            merged_tower = (
                best.detected_tower_level
                or prev.detected_tower_level
                or cand.detected_tower_level
            )
            deduped[existing_idx] = ParsedRosterRow(
                raw_line=best.raw_line,
                extracted_name=best.extracted_name,
                clean_name=best.clean_name,
                detected_number=merged_num,
                ocr_confidence=best.ocr_confidence,
                detected_rank=merged_rank,
                detected_tower_level=merged_tower,
                warnings=best.warnings,
            )

    return deduped
