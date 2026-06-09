#!/usr/bin/env python3
"""Render a title/ending card as a static PNG using Pillow.

Designed as the "cover" and "ending" PNG generators for meta-short-drama:
deterministic, free, no API, CJK-friendly font fallback. The output PNG
can then be fed to video-still-animator to become a short MP4 clip.

Usage:
    python render.py --text "咖啡店偶遇" --output cover.png \\
        [--subtitle "短剧"] [--background "#101018"] \\
        [--text-color "#ffffff"] [--font-size 96] \\
        [--width 720] [--height 1280]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_CJK_FONT_CANDIDATES = (
    # Windows
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Songti.ttc",
    # Linux common
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
)


def _pick_font(size: int, explicit: str | None = None):
    from PIL import ImageFont  # type: ignore
    if explicit:
        try:
            return ImageFont.truetype(explicit, size)
        except OSError:
            print(f"Warning: --font {explicit!r} not loadable; falling back.", file=sys.stderr)
    for candidate in _CJK_FONT_CANDIDATES:
        if os.path.isfile(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    # Final fallback — bundled bitmap; CJK characters render as tofu but doesn't crash.
    return ImageFont.load_default()


def _parse_color(spec: str) -> tuple[int, int, int]:
    s = spec.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"invalid color: {spec!r}")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _wrap_text(text: str, max_chars: int) -> list[str]:
    """Greedy line wrap that respects CJK (no spaces) and ASCII (whitespace)."""
    if not text:
        return [""]
    # If text already has explicit newlines, honour them.
    if "\n" in text:
        return text.split("\n")
    # For pure-ASCII strings, break on whitespace.
    if all(ord(c) < 0x4E00 for c in text):
        words = text.split()
        out: list[str] = []
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if len(candidate) <= max_chars:
                line = candidate
            else:
                if line:
                    out.append(line)
                line = word
        if line:
            out.append(line)
        return out or [text]
    # CJK / mixed: break at character count.
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True, help="Main headline text.")
    parser.add_argument("--output", "-o", required=True)
    parser.add_argument("--subtitle", default="", help="Smaller line under the headline.")
    parser.add_argument("--background", default="#101018", help="Hex color #RRGGBB.")
    parser.add_argument("--text-color", default="#ffffff")
    parser.add_argument("--subtitle-color", default="#c8c8d0")
    parser.add_argument("--font-size", type=int, default=80)
    parser.add_argument("--subtitle-size", type=int, default=32)
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument(
        "--max-chars-per-line", type=int, default=12,
        help="Soft wrap threshold for the headline (CJK char count). "
             "Subtitle uses 1.5× this value.",
    )
    parser.add_argument(
        "--auto-shrink", default="yes", choices=["yes", "no"],
        help="When rendered text exceeds 88%% of canvas width, shrink the font "
             "until it fits. Default yes.",
    )
    parser.add_argument("--font", default=None, help="Optional explicit font path.")
    args = parser.parse_args()

    try:
        from PIL import Image, ImageDraw  # type: ignore
    except ImportError as exc:
        print(f"Error: Pillow not installed ({exc}).", file=sys.stderr)
        return 1

    try:
        bg = _parse_color(args.background)
        fg = _parse_color(args.text_color)
        sfg = _parse_color(args.subtitle_color)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    img = Image.new("RGB", (args.width, args.height), color=bg)
    draw = ImageDraw.Draw(img)

    title_lines = _wrap_text(args.text, args.max_chars_per_line)
    sub_lines = (
        _wrap_text(args.subtitle, int(args.max_chars_per_line * 1.5))
        if args.subtitle else []
    )

    def _max_text_width(lines, font) -> int:
        widest = 0
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            widest = max(widest, bbox[2] - bbox[0])
        return widest

    def _fit_font(size: int, lines: list[str]) -> tuple[int, object]:
        max_safe = int(args.width * 0.88)
        font = _pick_font(size, args.font)
        if args.auto_shrink == "no" or not lines:
            return size, font
        # Shrink until rendered max line fits.
        while size > 12 and _max_text_width(lines, font) > max_safe:
            size = int(size * 0.92)
            font = _pick_font(size, args.font)
        return size, font

    title_size, font_title = _fit_font(args.font_size, title_lines)
    sub_size, font_sub = _fit_font(args.subtitle_size, sub_lines) if sub_lines else (args.subtitle_size, None)

    # Stack all lines, vertically centered, using the (potentially shrunken) sizes.
    line_gap_title = int(title_size * 0.25)
    line_gap_sub = int(sub_size * 0.25)
    pad_between_groups = int(title_size * 0.6)

    total_h = title_size * len(title_lines) + line_gap_title * max(0, len(title_lines) - 1)
    if sub_lines:
        total_h += pad_between_groups + sub_size * len(sub_lines) + line_gap_sub * max(0, len(sub_lines) - 1)
    y = (args.height - total_h) // 2

    def _draw_line(text: str, font, color, y_pos: int) -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        x = (args.width - text_w) // 2
        draw.text((x, y_pos), text, fill=color, font=font)

    for line in title_lines:
        _draw_line(line, font_title, fg, y)
        y += title_size + line_gap_title

    if sub_lines:
        y += pad_between_groups - line_gap_title
        for line in sub_lines:
            _draw_line(line, font_sub, sfg, y)
            y += sub_size + line_gap_sub

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
