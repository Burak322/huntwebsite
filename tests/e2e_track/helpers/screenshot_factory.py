"""Deterministic real PNG/JPG leaderboard screenshot factory using Pillow."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

TURKISH_SAMPLE_CHARS = "ğüşöçıİĞÜŞÖÇ"

_REGULAR_WINDOWS_FONTS = (
    "segoeui.ttf",
    "tahoma.ttf",
    "arial.ttf",
    "calibri.ttf",
    "verdana.ttf",
    "consola.ttf",
)
_BOLD_WINDOWS_FONTS = (
    "segoeuib.ttf",
    "tahomabd.ttf",
    "arialbd.ttf",
    "calibrib.ttf",
    "verdanab.ttf",
    "consolab.ttf",
)

_THEMES: dict[str, dict[str, tuple[int, int, int]]] = {
    "dark": {
        "bg": (20, 24, 34),
        "row_even": (28, 34, 48),
        "row_odd": (23, 28, 40),
        "header_bg": (36, 44, 62),
        "border": (52, 63, 86),
        "text": (242, 246, 252),
        "header_text": (203, 213, 225),
        "title_text": (248, 250, 252),
    },
    "light": {
        "bg": (248, 250, 252),
        "row_even": (255, 255, 255),
        "row_odd": (241, 245, 249),
        "header_bg": (226, 232, 240),
        "border": (203, 213, 225),
        "text": (15, 23, 42),
        "header_text": (30, 41, 59),
        "title_text": (15, 23, 42),
    },
}


@dataclass(frozen=True, slots=True)
class LeaderboardRowSpec:
    """Single row specification for a rendered clan leaderboard screenshot."""

    name: str
    score: str
    rank: int | None = None
    clan_tag: str | None = None


def _resolve_font(
    font_size: int, *, bold: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Resolve a Turkish-capable TrueType font with deterministic Windows priority."""
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = _BOLD_WINDOWS_FONTS if bold else _REGULAR_WINDOWS_FONTS
    for filename in candidates:
        font_path = windir / filename
        if font_path.is_file():
            return ImageFont.truetype(str(font_path), size=font_size)

    fallback_name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(fallback_name, size=font_size)
    except OSError:
        pass

    try:
        return ImageFont.load_default(size=font_size)
    except TypeError:
        return ImageFont.load_default()


def _measure_text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> tuple[int, int]:
    """Return (width, height) in pixels for text rendered with font."""
    if not text:
        return (0, 0)
    bbox = draw.textbbox((0, 0), text, font=font)
    return (max(0, int(bbox[2] - bbox[0])), max(0, int(bbox[3] - bbox[1])))


def _draw_aligned_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    *,
    fill: tuple[int, int, int],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    anchor: str,
) -> None:
    """Draw text with middle-aligned anchor, falling back safely for bitmap fonts."""
    try:
        draw.text(xy, text, fill=fill, font=font, anchor=anchor)
    except ValueError:
        w, h = _measure_text_size(draw, text, font)
        x, y = xy
        adjusted_x = x - w if anchor.startswith("r") else x
        adjusted_y = y - (h / 2)
        draw.text((adjusted_x, adjusted_y), text, fill=fill, font=font)


def _format_player_label(row: LeaderboardRowSpec) -> str:
    if row.clan_tag and row.clan_tag.strip():
        return f"{row.clan_tag.strip()} {row.name}"
    return row.name


def generate_leaderboard_image(
    path: Path,
    rows: list[LeaderboardRowSpec],
    *,
    theme: str = "dark",
    fmt: str = "PNG",
    title: str | None = None,
    headers: list[str] | None = None,
    width: int = 900,
    font_size: int = 28,
) -> Path:
    """Render a realistic clan duel leaderboard screenshot to PNG/JPG/WEBP."""
    theme_key = theme.strip().lower()
    if theme_key not in _THEMES:
        raise ValueError(f"Unsupported theme: {theme!r} (expected 'dark' or 'light')")
    palette = _THEMES[theme_key]

    fmt_key = fmt.strip().upper()
    if fmt_key == "JPG":
        fmt_key = "JPEG"
    if fmt_key not in {"PNG", "JPEG", "WEBP"}:
        raise ValueError(f"Unsupported image format: {fmt!r}")

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    body_font = _resolve_font(font_size, bold=False)
    bold_font = _resolve_font(font_size, bold=True)
    title_font = _resolve_font(max(12, int(round(font_size * 1.15))), bold=True)

    scratch = Image.new("RGB", (64, 64), color=palette["bg"])
    scratch_draw = ImageDraw.Draw(scratch)

    _, sample_h = _measure_text_size(
        scratch_draw,
        f"{TURKISH_SAMPLE_CHARS}Agjpqy0123456789",
        body_font,
    )
    row_h = max(int(round(font_size * 1.9)), sample_h + 24)
    title_h = (int(round(row_h * 1.15)) + 12) if title else 0
    header_h = int(round(row_h * 0.95)) if headers else 0

    pad_x = 36
    pad_y = 28
    cell_pad = 16
    rank_gap = 32
    score_gap = 48

    has_rank = any(row.rank is not None for row in rows) or (
        headers is not None and len(headers) >= 3
    )

    max_rank_w = 0
    if has_rank:
        rank_samples = [f"{row.rank}." for row in rows if row.rank is not None]
        if not rank_samples:
            rank_samples = ["99."]
        if headers and len(headers) >= 3:
            rank_samples.append(headers[0])
        max_rank_w = max(_measure_text_size(scratch_draw, s, bold_font)[0] for s in rank_samples)

    name_samples = [_format_player_label(row) for row in rows] or ["Oyuncu"]
    if headers:
        if len(headers) >= 3:
            name_samples.append(headers[1])
        elif len(headers) >= 1:
            name_samples.append(headers[0])
    max_name_w = max(_measure_text_size(scratch_draw, s, body_font)[0] for s in name_samples)

    score_samples = [row.score for row in rows] or ["0"]
    if headers:
        if len(headers) >= 3:
            score_samples.append(headers[2])
        elif len(headers) >= 2:
            score_samples.append(headers[1])
    max_score_w = max(_measure_text_size(scratch_draw, s, bold_font)[0] for s in score_samples)

    title_w = _measure_text_size(scratch_draw, title, title_font)[0] if title else 0

    columns_w = (
        pad_x * 2
        + cell_pad * 2
        + (max_rank_w + rank_gap if has_rank else 0)
        + max_name_w
        + score_gap
        + max_score_w
    )
    title_req_w = pad_x * 2 + cell_pad * 2 + title_w
    canvas_w = max(width, columns_w, title_req_w)
    canvas_h = pad_y * 2 + title_h + header_h + max(1, len(rows)) * row_h

    img = Image.new("RGB", (canvas_w, canvas_h), color=palette["bg"])
    draw = ImageDraw.Draw(img)

    rank_x = pad_x + cell_pad
    name_x = rank_x + (max_rank_w + rank_gap if has_rank else 0)
    score_x = canvas_w - pad_x - cell_pad

    cursor_y = pad_y

    if title:
        title_box_h = int(round(row_h * 1.15))
        _draw_aligned_text(
            draw,
            (rank_x, cursor_y + title_box_h / 2),
            title,
            fill=palette["title_text"],
            font=title_font,
            anchor="lm",
        )
        cursor_y += title_h

    if headers:
        draw.rectangle(
            [pad_x, cursor_y, canvas_w - pad_x, cursor_y + header_h],
            fill=palette["header_bg"],
            outline=palette["border"],
            width=1,
        )
        header_mid_y = cursor_y + header_h / 2
        if has_rank and len(headers) >= 3:
            _draw_aligned_text(
                draw,
                (rank_x, header_mid_y),
                headers[0],
                fill=palette["header_text"],
                font=bold_font,
                anchor="lm",
            )
            _draw_aligned_text(
                draw,
                (name_x, header_mid_y),
                headers[1],
                fill=palette["header_text"],
                font=bold_font,
                anchor="lm",
            )
            _draw_aligned_text(
                draw,
                (score_x, header_mid_y),
                headers[2],
                fill=palette["header_text"],
                font=bold_font,
                anchor="rm",
            )
        elif len(headers) >= 2:
            _draw_aligned_text(
                draw,
                (name_x, header_mid_y),
                headers[0],
                fill=palette["header_text"],
                font=bold_font,
                anchor="lm",
            )
            _draw_aligned_text(
                draw,
                (score_x, header_mid_y),
                headers[1],
                fill=palette["header_text"],
                font=bold_font,
                anchor="rm",
            )
        elif len(headers) == 1:
            _draw_aligned_text(
                draw,
                (name_x, header_mid_y),
                headers[0],
                fill=palette["header_text"],
                font=bold_font,
                anchor="lm",
            )
        cursor_y += header_h

    for idx, row in enumerate(rows):
        row_bg = palette["row_even"] if idx % 2 == 0 else palette["row_odd"]
        draw.rectangle(
            [pad_x, cursor_y, canvas_w - pad_x, cursor_y + row_h],
            fill=row_bg,
            outline=palette["border"],
            width=1,
        )
        row_mid_y = cursor_y + row_h / 2

        if row.rank is not None:
            _draw_aligned_text(
                draw,
                (rank_x, row_mid_y),
                f"{row.rank}.",
                fill=palette["text"],
                font=bold_font,
                anchor="lm",
            )

        _draw_aligned_text(
            draw,
            (name_x, row_mid_y),
            _format_player_label(row),
            fill=palette["text"],
            font=body_font,
            anchor="lm",
        )
        _draw_aligned_text(
            draw,
            (score_x, row_mid_y),
            row.score,
            fill=palette["text"],
            font=bold_font,
            anchor="rm",
        )
        cursor_y += row_h

    save_kwargs: dict[str, Any] = {"format": fmt_key}
    if fmt_key == "JPEG":
        img = img.convert("RGB")
        save_kwargs["quality"] = 95
        save_kwargs["subsampling"] = 0

    img.save(out_path, **save_kwargs)
    return out_path


def generate_corrupt_or_blank_image(path: Path, *, mode: str = "blank") -> Path:
    """Generate edge-case images for negative OCR testing: blank, corrupt_bytes, or no_scores."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    mode_key = mode.strip().lower()
    if mode_key == "blank":
        img = Image.new("RGB", (800, 400), color=(248, 250, 252))
        img.save(out_path, format="PNG")
        return out_path

    if mode_key == "corrupt_bytes":
        out_path.write_bytes(b"\x89PNG\r\n\x1a\nCORRUPT_E2E_PAYLOAD_INVALID_IMAGE\x00\xff\xfe")
        return out_path

    if mode_key == "no_scores":
        palette = _THEMES["light"]
        img = Image.new("RGB", (800, 400), color=palette["bg"])
        draw = ImageDraw.Draw(img)
        title_font = _resolve_font(30, bold=True)
        body_font = _resolve_font(24, bold=False)

        lines = [
            ("Klan Toplantı Duyurusu", title_font, 72),
            ("Bu akşam sesli sohbet odasında buluşuyoruz.", body_font, 160),
            ("Katılım gönüllülük esasına dayanmaktadır.", body_font, 230),
            ("Yeni sezon stratejileri konuşulacaktır.", body_font, 300),
        ]
        for text, font, y in lines:
            _draw_aligned_text(
                draw,
                (56, y),
                text,
                fill=palette["text"],
                font=font,
                anchor="lm",
            )
        img.save(out_path, format="PNG")
        return out_path

    raise ValueError(f"Unsupported mode: {mode!r} (expected 'blank', 'corrupt_bytes', or 'no_scores')")
