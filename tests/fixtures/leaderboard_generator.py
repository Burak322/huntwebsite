from __future__ import annotations

import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal, Sequence

from PIL import Image, ImageDraw, ImageFont

_REGULAR_TTF_CANDIDATES = (
    "tahoma.ttf",
    "segoeui.ttf",
    "arial.ttf",
    "calibri.ttf",
    "verdana.ttf",
    "consola.ttf",
    "DejaVuSans.ttf",
    "LiberationSans-Regular.ttf",
    "NotoSans-Regular.ttf",
)

_BOLD_TTF_CANDIDATES = (
    "tahomabd.ttf",
    "segoeuib.ttf",
    "arialbd.ttf",
    "calibrib.ttf",
    "verdanab.ttf",
    "consolab.ttf",
    "DejaVuSans-Bold.ttf",
    "LiberationSans-Bold.ttf",
    "NotoSans-Bold.ttf",
)

_COLOR_PALETTE = (
    (250, 204, 21),   # gold
    (56, 189, 248),   # cyan
    (248, 113, 113),  # coral
    (74, 222, 128),   # mint
)


@dataclass(frozen=True, slots=True)
class LeaderboardRow:
    name: str
    score: str
    rank: int | None = None
    clan_tag: str | None = None
    extra_cols: tuple[str, ...] = ()


def resolve_ttf_font(
    size: int,
    *,
    bold: bool = False,
    font_name: str | None = None,
    require_turkish: bool = True,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    fonts_dir = windir / "Fonts"

    search_names: list[str] = []
    if font_name:
        search_names.append(font_name)
    search_names.extend(_BOLD_TTF_CANDIDATES if bold else _REGULAR_TTF_CANDIDATES)

    for candidate in search_names:
        cand_path = Path(candidate)
        paths_to_try = [cand_path] if cand_path.is_absolute() else [fonts_dir / candidate, cand_path]
        for path in paths_to_try:
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue

    if require_turkish:
        raise RuntimeError(
            "No TrueType font with Turkish glyph support found in Windows Fonts or system font paths."
        )
    return ImageFont.load_default(size=size)


def _save_image_bytes(img: Image.Image, fmt: str, output_path: Path | None = None) -> bytes:
    normalized_fmt = fmt.upper()
    pil_fmt = "JPEG" if normalized_fmt in ("JPG", "JPEG") else normalized_fmt
    buf = BytesIO()
    if pil_fmt == "JPEG":
        img.convert("RGB").save(buf, format="JPEG", quality=92)
    elif pil_fmt == "WEBP":
        img.convert("RGB").save(buf, format="WEBP", quality=92)
    else:
        img.convert("RGB").save(buf, format="PNG")
    data = buf.getvalue()
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
    return data


def generate_leaderboard_image(
    rows: Sequence[LeaderboardRow],
    *,
    theme: Literal["dark", "light", "colored_small"] = "dark",
    fmt: Literal["PNG", "JPG", "JPEG", "WEBP"] = "PNG",
    title: str | None = None,
    headers: list[str] | None = None,
    width: int = 860,
    font_size: int = 26,
    font_name: str | None = None,
    require_turkish: bool = True,
    output_path: Path | None = None,
) -> bytes:
    if theme == "colored_small" and font_size == 26:
        font_size = 17

    if theme == "light":
        bg_color = (246, 248, 252)
        title_color = (22, 28, 42)
        header_color = (75, 85, 105)
        row_bg_even = (236, 240, 247)
        row_bg_odd = (246, 248, 252)
        text_color = (24, 30, 44)
        score_color = (20, 70, 175)
        rank_color = (90, 100, 120)
        divider_color = (205, 212, 224)
    else:
        bg_color = (20, 24, 34)
        title_color = (244, 247, 252)
        header_color = (156, 168, 192)
        row_bg_even = (28, 34, 48)
        row_bg_odd = (22, 27, 38)
        text_color = (240, 244, 250)
        score_color = (250, 204, 21)
        rank_color = (170, 182, 204)
        divider_color = (48, 56, 76)

    font = resolve_ttf_font(
        font_size,
        bold=False,
        font_name=font_name,
        require_turkish=require_turkish,
    )
    bold_font = resolve_ttf_font(
        font_size + 2 if title else font_size,
        bold=True,
        font_name=font_name,
        require_turkish=require_turkish,
    )
    header_font = resolve_ttf_font(
        max(14, font_size - 3),
        bold=True,
        font_name=font_name,
        require_turkish=require_turkish,
    )

    padding_x = 36
    padding_y = 28
    row_height = max(36, int(font_size * 1.9))
    title_h = (font_size + 26) if title else 0
    header_h = (font_size + 18) if headers else 0
    height = max(140, padding_y * 2 + title_h + header_h + len(rows) * row_height + 16)

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    y = padding_y
    if title:
        draw.text((padding_x, y), title, fill=title_color, font=bold_font)
        y += title_h

    has_ranks = any(r.rank is not None for r in rows)
    max_extra = max((len(r.extra_cols) for r in rows), default=0)

    rank_x = padding_x
    name_x = padding_x + (86 if has_ranks else 0)
    score_right_x = width - padding_x

    extra_xs: list[int] = []
    if max_extra > 0:
        extra_zone_end = score_right_x - 180
        extra_zone_start = max(name_x + 280, extra_zone_end - max_extra * 130)
        step = max(100, (extra_zone_end - extra_zone_start) // max_extra)
        for i in range(max_extra):
            extra_xs.append(extra_zone_start + i * step)

    if headers:
        header_positions: list[tuple[int, str, str]] = []
        if has_ranks and len(headers) >= 3 + max_extra:
            header_positions.append((rank_x, headers[0], "lm"))
            header_positions.append((name_x, headers[1], "lm"))
            for i in range(max_extra):
                header_positions.append((extra_xs[i], headers[2 + i], "lm"))
            header_positions.append((score_right_x, headers[-1], "rm"))
        elif len(headers) == 2:
            header_positions.append((name_x, headers[0], "lm"))
            header_positions.append((score_right_x, headers[1], "rm"))
        else:
            step = (score_right_x - padding_x) // max(1, len(headers) - 1)
            for idx, h_text in enumerate(headers):
                hx = score_right_x if idx == len(headers) - 1 else padding_x + idx * step
                anchor = "rm" if idx == len(headers) - 1 else "lm"
                header_positions.append((hx, h_text, anchor))

        hy = y + header_h // 2
        for hx, h_text, anchor in header_positions:
            draw.text((hx, hy), h_text, fill=header_color, font=header_font, anchor=anchor)
        draw.line([(padding_x, y + header_h - 4), (width - padding_x, y + header_h - 4)], fill=divider_color, width=1)
        y += header_h + 6

    for idx, row in enumerate(rows):
        row_top = y + idx * row_height
        row_bg = row_bg_even if idx % 2 == 0 else row_bg_odd
        draw.rectangle(
            [(padding_x - 10, row_top + 2), (width - padding_x + 10, row_top + row_height - 4)],
            fill=row_bg,
        )
        cy = row_top + row_height // 2

        if theme == "colored_small":
            row_name_color = _COLOR_PALETTE[idx % len(_COLOR_PALETTE)]
            row_score_color = _COLOR_PALETTE[(idx + 1) % len(_COLOR_PALETTE)]
        else:
            row_name_color = text_color
            row_score_color = score_color

        if row.rank is not None:
            draw.text((rank_x, cy), f"{row.rank}.", fill=rank_color, font=font, anchor="lm")

        full_name = f"{row.clan_tag} {row.name}".strip() if row.clan_tag else row.name
        draw.text((name_x, cy), full_name, fill=row_name_color, font=font, anchor="lm")

        for col_idx, col_val in enumerate(row.extra_cols):
            if col_idx < len(extra_xs):
                draw.text((extra_xs[col_idx], cy), col_val, fill=rank_color, font=font, anchor="lm")

        draw.text((score_right_x, cy), row.score, fill=row_score_color, font=font, anchor="rm")

    return _save_image_bytes(img, fmt=fmt, output_path=output_path)


def generate_blank_image(
    width: int = 640,
    height: int = 320,
    color: tuple[int, int, int] = (245, 247, 250),
    *,
    fmt: Literal["PNG", "JPG", "JPEG", "WEBP"] = "PNG",
) -> bytes:
    img = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40, 40), (width - 40, height - 40)], outline=(210, 216, 226), width=2)
    return _save_image_bytes(img, fmt=fmt)


def generate_non_leaderboard_image(
    width: int = 760,
    height: int = 280,
    *,
    font_name: str | None = None,
    fmt: Literal["PNG", "JPG", "JPEG", "WEBP"] = "PNG",
) -> bytes:
    img = Image.new("RGB", (width, height), (24, 28, 38))
    draw = ImageDraw.Draw(img)
    title_font = resolve_ttf_font(26, bold=True, font_name=font_name, require_turkish=True)
    body_font = resolve_ttf_font(20, bold=False, font_name=font_name, require_turkish=True)
    draw.text((40, 40), "Klan Toplantı Duyurusu", fill=(240, 244, 250), font=title_font)
    draw.text(
        (40, 100),
        "Akşam saatlerinde genel strateji değerlendirmesi yapılacaktır.",
        fill=(195, 205, 220),
        font=body_font,
    )
    draw.text(
        (40, 145),
        "Tüm üyelerin sesli sohbet kanalında hazır bulunması beklenmektedir.",
        fill=(195, 205, 220),
        font=body_font,
    )
    return _save_image_bytes(img, fmt=fmt)


def generate_corrupt_image_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\nCORRUPT_M3_TEST_PAYLOAD\x00\xff\xfe"
