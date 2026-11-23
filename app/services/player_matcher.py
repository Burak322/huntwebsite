from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from itertools import product
from typing import Any, Literal, Mapping, Sequence, TypedDict

MatchStatus = Literal["exact", "case_insensitive", "ocr_normalized", "fuzzy_review", "unmatched"]

FUZZY_MATCH_THRESHOLD = 0.75
LOW_OCR_CONFIDENCE_THRESHOLD = 0.75

_LEADING_TAG_RE = re.compile(
    r"^\s*(?:\[[^\[\]]{1,16}\]|<[^<>]{1,16}>|\([^()]{1,16}\)|\{[^{}]{1,16}\}|【[^【】]{1,16}】)\s*"
)
_TRAILING_TAG_RE = re.compile(
    r"\s*(?:\[[^\[\]]{1,16}\]|<[^<>]{1,16}>|\([^()]{1,16}\)|\{[^{}]{1,16}\}|【[^【】]{1,16}】)\s*$"
)

_TURKISH_OCR_FOLD = str.maketrans({
    "ı": "i",
    "ğ": "g",
    "ş": "s",
    "ç": "c",
    "ö": "o",
    "ü": "u",
})

_SAFE_HOMOGLYPH_FOLD = str.maketrans({
    "0": "o",
    "5": "s",
    "$": "s",
})


class RosterCandidateDict(TypedDict, total=False):
    id: int
    display_name: str
    aliases: list[str]


@dataclass(frozen=True, slots=True)
class RosterCandidate:
    id: int
    display_name: str
    aliases: tuple[str, ...] | list[str] = ()


@dataclass(frozen=True, slots=True)
class PlayerMatchResult:
    raw_name: str
    clean_name: str
    matched_player_id: int | None
    matched_player_name: str | None
    match_status: MatchStatus
    match_confidence: float
    needs_review: bool = False
    matched_via: Literal["display_name", "alias"] | None = None
    matched_alias: str | None = None
    warnings: tuple[str, ...] = ()


def _collapse_spaces(text: str) -> str:
    return " ".join((text or "").split())


def strip_clan_tags(name: str) -> str:
    current = _collapse_spaces(name)
    if not current:
        return ""

    while True:
        changed = False
        lead_candidate = _LEADING_TAG_RE.sub("", current, count=1).strip()
        if lead_candidate and lead_candidate != current:
            current = lead_candidate
            changed = True

        trail_candidate = _TRAILING_TAG_RE.sub("", current, count=1).strip()
        if trail_candidate and trail_candidate != current:
            current = trail_candidate
            changed = True

        if not changed:
            break

    return _collapse_spaces(current)


def _casefold_standard(text: str) -> str:
    s = unicodedata.normalize("NFC", _collapse_spaces(text))
    s = s.replace("\u0130", "i").casefold()
    return s.replace("i\u0307", "i")


def _casefold_turkish_i(text: str) -> str:
    s = unicodedata.normalize("NFC", _collapse_spaces(text))
    s = s.replace("\u0130", "i").replace("I", "ı").casefold()
    return s.replace("i\u0307", "i")


def normalize_for_ocr(name: str) -> str:
    s = _casefold_standard(name)
    s = s.translate(_TURKISH_OCR_FOLD)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[_-]+", " ", s)
    return _collapse_spaces(s)


def _homoglyph_variants(norm_text: str) -> set[str]:
    base = norm_text.translate(_SAFE_HOMOGLYPH_FOLD)
    variants: set[str] = {norm_text, base}

    one_positions = [idx for idx, ch in enumerate(base) if ch == "1"]
    if one_positions:
        if len(one_positions) <= 4:
            chars = list(base)
            for combo in product(("1", "i", "l"), repeat=len(one_positions)):
                for pos, repl in zip(one_positions, combo):
                    chars[pos] = repl
                variants.add("".join(chars))
        else:
            variants.add(base.replace("1", "i"))
            variants.add(base.replace("1", "l"))

    return variants


def damerau_levenshtein_distance(a: str, b: str) -> int:
    len_a = len(a)
    len_b = len(b)
    if len_a == 0:
        return len_b
    if len_b == 0:
        return len_a

    dp = [[0] * (len_b + 1) for _ in range(len_a + 1)]
    for i in range(len_a + 1):
        dp[i][0] = i
    for j in range(len_b + 1):
        dp[0][j] = j

    for i in range(1, len_a + 1):
        for j in range(1, len_b + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            best = min(
                dp[i - 1][j] + 1,
                dp[i][j - 1] + 1,
                dp[i - 1][j - 1] + cost,
            )
            if (
                i > 1
                and j > 1
                and a[i - 1] == b[j - 2]
                and a[i - 2] == b[j - 1]
            ):
                best = min(best, dp[i - 2][j - 2] + 1)
            dp[i][j] = best

    return dp[len_a][len_b]


def damerau_levenshtein_similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    max_len = max(len(a), len(b))
    return 1.0 - (damerau_levenshtein_distance(a, b) / max_len)


def _iter_roster_entries(
    roster: Sequence[RosterCandidate | Mapping[str, Any]],
) -> list[tuple[int, str, str, Literal["display_name", "alias"]]]:
    entries: list[tuple[int, str, str, Literal["display_name", "alias"]]] = []
    for item in roster:
        if isinstance(item, RosterCandidate):
            pid = int(item.id)
            display_name = _collapse_spaces(item.display_name)
            raw_aliases = item.aliases
        elif isinstance(item, Mapping):
            pid = int(item["id"])
            display_name = _collapse_spaces(str(item.get("display_name") or item.get("displayName") or ""))
            raw_aliases = item.get("aliases") or ()
        else:
            pid = int(getattr(item, "id"))
            display_name = _collapse_spaces(str(getattr(item, "display_name")))
            raw_aliases = getattr(item, "aliases", ()) or ()

        if not display_name:
            continue

        entries.append((pid, display_name, display_name, "display_name"))
        for alias in raw_aliases:
            clean_alias = _collapse_spaces(str(alias))
            if clean_alias:
                entries.append((pid, display_name, clean_alias, "alias"))

    return entries


def _select_best_exact_tier(
    matches: list[tuple[int, str, str, Literal["display_name", "alias"]]],
) -> tuple[tuple[int, str, str, Literal["display_name", "alias"]], tuple[str, ...]]:
    # Prefer display_name over alias, then lowest player_id deterministically
    sorted_matches = sorted(
        matches,
        key=lambda m: (0 if m[3] == "display_name" else 1, m[0]),
    )
    winner = sorted_matches[0]
    distinct_ids = {m[0] for m in matches}
    warnings: tuple[str, ...] = ("ambiguous_match",) if len(distinct_ids) > 1 else ()
    return winner, warnings


def match_player(
    name: str,
    roster: Sequence[RosterCandidate | Mapping[str, Any]],
    *,
    fuzzy_threshold: float = FUZZY_MATCH_THRESHOLD,
) -> PlayerMatchResult:
    raw_collapsed = _collapse_spaces(name)
    clean_name = strip_clan_tags(raw_collapsed)
    if not clean_name:
        return PlayerMatchResult(
            raw_name=name,
            clean_name="",
            matched_player_id=None,
            matched_player_name=None,
            match_status="unmatched",
            match_confidence=0.0,
            needs_review=True,
            warnings=("empty_name", "unmatched_player"),
        )

    entries = _iter_roster_entries(roster)
    if not entries:
        return PlayerMatchResult(
            raw_name=name,
            clean_name=clean_name,
            matched_player_id=None,
            matched_player_name=None,
            match_status="unmatched",
            match_confidence=0.0,
            needs_review=True,
            warnings=("unmatched_player",),
        )

    # Tier 1: Exact match
    tier1 = [
        e for e in entries
        if e[2] == clean_name or (raw_collapsed != clean_name and e[2] == raw_collapsed)
    ]
    if tier1:
        winner, extra_warnings = _select_best_exact_tier(tier1)
        return PlayerMatchResult(
            raw_name=name,
            clean_name=clean_name,
            matched_player_id=winner[0],
            matched_player_name=winner[1],
            match_status="exact",
            match_confidence=1.0,
            needs_review=bool(extra_warnings),
            matched_via=winner[3],
            matched_alias=winner[2] if winner[3] == "alias" else None,
            warnings=extra_warnings,
        )

    # Tier 2: Case-insensitive (Turkish-safe)
    cf_std_q = _casefold_standard(clean_name)
    cf_tr_q = _casefold_turkish_i(clean_name)
    tier2 = [
        e for e in entries
        if _casefold_standard(e[2]) == cf_std_q or _casefold_turkish_i(e[2]) == cf_tr_q
    ]
    if tier2:
        winner, extra_warnings = _select_best_exact_tier(tier2)
        return PlayerMatchResult(
            raw_name=name,
            clean_name=clean_name,
            matched_player_id=winner[0],
            matched_player_name=winner[1],
            match_status="case_insensitive",
            match_confidence=0.98,
            needs_review=bool(extra_warnings),
            matched_via=winner[3],
            matched_alias=winner[2] if winner[3] == "alias" else None,
            warnings=extra_warnings,
        )

    # Tier 3: OCR-normalized + safe homoglyphs
    norm_q = normalize_for_ocr(clean_name)
    variants_q = _homoglyph_variants(norm_q)
    tier3 = [
        e for e in entries
        if variants_q & _homoglyph_variants(normalize_for_ocr(e[2]))
    ]
    if tier3:
        winner, extra_warnings = _select_best_exact_tier(tier3)
        return PlayerMatchResult(
            raw_name=name,
            clean_name=clean_name,
            matched_player_id=winner[0],
            matched_player_name=winner[1],
            match_status="ocr_normalized",
            match_confidence=0.92,
            needs_review=bool(extra_warnings),
            matched_via=winner[3],
            matched_alias=winner[2] if winner[3] == "alias" else None,
            warnings=extra_warnings,
        )

    # Tier 4: Fuzzy Damerau-Levenshtein
    scored: list[tuple[float, int, str, str, Literal["display_name", "alias"]]] = []
    for pid, disp, cand_text, via in entries:
        sim = damerau_levenshtein_similarity(norm_q, normalize_for_ocr(cand_text))
        if sim >= fuzzy_threshold:
            scored.append((sim, pid, disp, cand_text, via))

    if scored:
        max_sim = max(item[0] for item in scored)
        top_matches = [item for item in scored if abs(item[0] - max_sim) <= 1e-9]
        top_matches.sort(key=lambda item: (0 if item[4] == "display_name" else 1, item[1]))
        win_sim, win_pid, win_disp, win_cand, win_via = top_matches[0]

        distinct_top_ids = {item[1] for item in top_matches}
        near_tie_ids = {item[1] for item in scored if (max_sim - item[0]) <= 0.03}
        warnings_list: list[str] = ["fuzzy_match_needs_review"]
        if len(distinct_top_ids) > 1 or len(near_tie_ids) > 1:
            warnings_list.append("ambiguous_match")

        return PlayerMatchResult(
            raw_name=name,
            clean_name=clean_name,
            matched_player_id=win_pid,
            matched_player_name=win_disp,
            match_status="fuzzy_review",
            match_confidence=round(win_sim, 4),
            needs_review=True,
            matched_via=win_via,
            matched_alias=win_cand if win_via == "alias" else None,
            warnings=tuple(warnings_list),
        )

    return PlayerMatchResult(
        raw_name=name,
        clean_name=clean_name,
        matched_player_id=None,
        matched_player_name=None,
        match_status="unmatched",
        match_confidence=0.0,
        needs_review=True,
        warnings=("unmatched_player",),
    )


def _dedup_preserve_order(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def apply_review_flags(
    rows: Sequence[Mapping[str, Any]],
    *,
    low_confidence_threshold: float = LOW_OCR_CONFIDENCE_THRESHOLD,
) -> list[dict[str, Any]]:
    copied = [dict(row) for row in rows]
    player_counts = Counter(
        row["matchedPlayerId"]
        for row in copied
        if row.get("matchedPlayerId") is not None
    )

    for row in copied:
        warnings = list(row.get("warnings") or ())
        ocr_conf = float(row.get("ocrConfidence", 0.0))
        match_status = row.get("matchStatus", "unmatched")
        matched_pid = row.get("matchedPlayerId")

        if ocr_conf < low_confidence_threshold:
            warnings.append("low_ocr_confidence")
        if match_status == "fuzzy_review":
            warnings.append("fuzzy_match_needs_review")
        if match_status == "unmatched":
            warnings.append("unmatched_player")
        if matched_pid is not None and player_counts[matched_pid] > 1:
            warnings.append("duplicate_matched_player")

        deduped = _dedup_preserve_order(warnings)
        row["warnings"] = deduped
        row["needsReview"] = bool(
            ocr_conf < low_confidence_threshold
            or match_status in ("fuzzy_review", "unmatched")
            or "digit_repaired" in deduped
            or "ambiguous_match" in deduped
            or "duplicate_matched_player" in deduped
        )

    return copied
