#!/usr/bin/env python3
"""Render a brief's beats into a contact-sheet PNG.

The publish path in references/publishing.md tells you to commit a poster next
to the animated HTML, because GitHub renders an image inline in a PR comment
but not an .html file. This script is how that poster gets made: brief JSON in,
one PNG out, pure stdlib. No headless browser, no ImageMagick, no Pillow, no
ffmpeg. The animation is the HTML; the poster is the thing a reviewer sees
without leaving the thread.

Usage
-----
    poster.py brief.json --out pr-123-contact-sheet.png

The sheet is a 2-column grid, one card per beat, in the brief's own order. A
seven-beat brief fills seven cells; the eighth carries the gate verdict so the
image states why this diff earned an explainer at all.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

# Poster geometry, in pixels. Sized for legibility in a GitHub comment column
# (roughly 640px wide there) rather than for a browser viewport.
COLS = 2
CELL_W = 620
CELL_H = 260
PAD = 20
HEADER_H = 96
BG = (14, 17, 23)
CARD_BG = (22, 27, 34)
FG = (226, 232, 240)
DIM = (148, 163, 184)
RULE = (48, 54, 61)

# Beat accent colours, matched to PALETTE in render.py so the poster and the
# animation read as the same artifact.
ACCENT = {
    "problem": (251, 113, 133),
    "before": (148, 163, 184),
    "change": (34, 211, 238),
    "after": (52, 211, 153),
    "proof": (167, 139, 250),
    "cost": (251, 191, 36),
    "recap": (251, 146, 60),
}
DEFAULT_ACCENT = (148, 163, 184)

# --- 5x7 bitmap font ------------------------------------------------------
# One byte per column, low bit at the top. Only the glyphs that appear in beat
# copy are defined; anything else renders as a hollow box rather than silently
# vanishing, so a missing glyph is visible in the poster instead of becoming a
# mysteriously short line.
_FONT = {
    " ": (0x00, 0x00, 0x00, 0x00, 0x00), "!": (0x00, 0x00, 0x5F, 0x00, 0x00),
    '"': (0x00, 0x07, 0x00, 0x07, 0x00), "#": (0x14, 0x7F, 0x14, 0x7F, 0x14),
    "$": (0x24, 0x2A, 0x7F, 0x2A, 0x12), "%": (0x23, 0x13, 0x08, 0x64, 0x62),
    "&": (0x36, 0x49, 0x55, 0x22, 0x50), "'": (0x00, 0x05, 0x03, 0x00, 0x00),
    "(": (0x00, 0x1C, 0x22, 0x41, 0x00), ")": (0x00, 0x41, 0x22, 0x1C, 0x00),
    "*": (0x14, 0x08, 0x3E, 0x08, 0x14), "+": (0x08, 0x08, 0x3E, 0x08, 0x08),
    ",": (0x00, 0x50, 0x30, 0x00, 0x00), "-": (0x08, 0x08, 0x08, 0x08, 0x08),
    ".": (0x00, 0x60, 0x60, 0x00, 0x00), "/": (0x20, 0x10, 0x08, 0x04, 0x02),
    "0": (0x3E, 0x51, 0x49, 0x45, 0x3E), "1": (0x00, 0x42, 0x7F, 0x40, 0x00),
    "2": (0x42, 0x61, 0x51, 0x49, 0x46), "3": (0x21, 0x41, 0x45, 0x4B, 0x31),
    "4": (0x18, 0x14, 0x12, 0x7F, 0x10), "5": (0x27, 0x45, 0x45, 0x45, 0x39),
    "6": (0x3C, 0x4A, 0x49, 0x49, 0x30), "7": (0x01, 0x71, 0x09, 0x05, 0x03),
    "8": (0x36, 0x49, 0x49, 0x49, 0x36), "9": (0x06, 0x49, 0x49, 0x29, 0x1E),
    ":": (0x00, 0x36, 0x36, 0x00, 0x00), ";": (0x00, 0x56, 0x36, 0x00, 0x00),
    "<": (0x08, 0x14, 0x22, 0x41, 0x00), "=": (0x14, 0x14, 0x14, 0x14, 0x14),
    ">": (0x00, 0x41, 0x22, 0x14, 0x08), "?": (0x02, 0x01, 0x51, 0x09, 0x06),
    "@": (0x32, 0x49, 0x79, 0x41, 0x3E),
    "A": (0x7E, 0x11, 0x11, 0x11, 0x7E), "B": (0x7F, 0x49, 0x49, 0x49, 0x36),
    "C": (0x3E, 0x41, 0x41, 0x41, 0x22), "D": (0x7F, 0x41, 0x41, 0x22, 0x1C),
    "E": (0x7F, 0x49, 0x49, 0x49, 0x41), "F": (0x7F, 0x09, 0x09, 0x01, 0x01),
    "G": (0x3E, 0x41, 0x49, 0x49, 0x7A), "H": (0x7F, 0x08, 0x08, 0x08, 0x7F),
    "I": (0x00, 0x41, 0x7F, 0x41, 0x00), "J": (0x20, 0x40, 0x41, 0x3F, 0x01),
    "K": (0x7F, 0x08, 0x14, 0x22, 0x41), "L": (0x7F, 0x40, 0x40, 0x40, 0x40),
    "M": (0x7F, 0x02, 0x0C, 0x02, 0x7F), "N": (0x7F, 0x04, 0x08, 0x10, 0x7F),
    "O": (0x3E, 0x41, 0x41, 0x41, 0x3E), "P": (0x7F, 0x09, 0x09, 0x09, 0x06),
    "Q": (0x3E, 0x41, 0x51, 0x21, 0x5E), "R": (0x7F, 0x09, 0x19, 0x29, 0x46),
    "S": (0x46, 0x49, 0x49, 0x49, 0x31), "T": (0x01, 0x01, 0x7F, 0x01, 0x01),
    "U": (0x3F, 0x40, 0x40, 0x40, 0x3F), "V": (0x1F, 0x20, 0x40, 0x20, 0x1F),
    "W": (0x7F, 0x20, 0x18, 0x20, 0x7F), "X": (0x63, 0x14, 0x08, 0x14, 0x63),
    "Y": (0x03, 0x04, 0x78, 0x04, 0x03), "Z": (0x61, 0x51, 0x49, 0x45, 0x43),
    "[": (0x00, 0x7F, 0x41, 0x41, 0x00), "\\": (0x02, 0x04, 0x08, 0x10, 0x20),
    "]": (0x41, 0x41, 0x7F, 0x00, 0x00), "_": (0x40, 0x40, 0x40, 0x40, 0x40),
    "|": (0x00, 0x00, 0x77, 0x00, 0x00),
    "a": (0x20, 0x54, 0x54, 0x54, 0x78), "b": (0x7F, 0x48, 0x44, 0x44, 0x38),
    "c": (0x38, 0x44, 0x44, 0x44, 0x20), "d": (0x38, 0x44, 0x44, 0x48, 0x7F),
    "e": (0x38, 0x54, 0x54, 0x54, 0x18), "f": (0x08, 0x7E, 0x09, 0x01, 0x02),
    "g": (0x0C, 0x52, 0x52, 0x52, 0x3E), "h": (0x7F, 0x08, 0x04, 0x04, 0x78),
    "i": (0x00, 0x44, 0x7D, 0x40, 0x00), "j": (0x20, 0x40, 0x44, 0x3D, 0x00),
    "k": (0x7F, 0x10, 0x28, 0x44, 0x00), "l": (0x00, 0x41, 0x7F, 0x40, 0x00),
    "m": (0x7C, 0x04, 0x18, 0x04, 0x78), "n": (0x7C, 0x08, 0x04, 0x04, 0x78),
    "o": (0x38, 0x44, 0x44, 0x44, 0x38), "p": (0x7C, 0x14, 0x14, 0x14, 0x08),
    "q": (0x08, 0x14, 0x14, 0x18, 0x7C), "r": (0x7C, 0x08, 0x04, 0x04, 0x08),
    "s": (0x48, 0x54, 0x54, 0x54, 0x20), "t": (0x04, 0x3F, 0x44, 0x40, 0x20),
    "u": (0x3C, 0x40, 0x40, 0x20, 0x7C), "v": (0x1C, 0x20, 0x40, 0x20, 0x1C),
    "w": (0x3C, 0x40, 0x30, 0x40, 0x3C), "x": (0x44, 0x28, 0x10, 0x28, 0x44),
    "y": (0x0C, 0x50, 0x50, 0x50, 0x3C), "z": (0x44, 0x64, 0x54, 0x4C, 0x44),
    "~": (0x08, 0x04, 0x08, 0x10, 0x08),
}
_MISSING = (0x7F, 0x41, 0x41, 0x41, 0x7F)

GLYPH_W, GLYPH_H = 5, 7


def text_width(s: str, scale: int) -> int:
    return len(s) * (GLYPH_W + 1) * scale


class Canvas:
    """A minimal RGB raster. Painting is the only operation the poster needs."""

    def __init__(self, w: int, h: int, bg: tuple[int, int, int] = BG) -> None:
        self.w, self.h = w, h
        self.px = bytearray(w * h * 3)
        self.fill_rect(0, 0, w, h, bg)

    def fill_rect(self, x: int, y: int, w: int, h: int,
                  color: tuple[int, int, int]) -> None:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + w), min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            off = (yy * self.w + x0) * 3
            self.px[off:off + len(row)] = row

    def draw_text(self, x: int, y: int, s: str, color: tuple[int, int, int],
                  scale: int = 2) -> None:
        cx = x
        for ch in s:
            glyph = _FONT.get(ch, _MISSING)
            for col, bits in enumerate(glyph):
                for row in range(GLYPH_H):
                    if not (bits >> row) & 1:
                        continue
                    self.fill_rect(cx + col * scale, y + row * scale, scale, scale, color)
            cx += (GLYPH_W + 1) * scale

    def to_png(self) -> bytes:
        """Encode as a truecolour PNG: signature, IHDR, IDAT, IEND."""
        raw = bytearray()
        stride = self.w * 3
        for yy in range(self.h):
            raw.append(0)  # filter type 0 (None)
            raw += self.px[yy * stride:(yy + 1) * stride]

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def plain(s: str) -> str:
    """Strip markdown the same way render.py does, so both artifacts agree,
    then fold to the font's ASCII range. The 5x7 face has no accented or CJK
    glyphs; leaving them in renders a row of hollow boxes that reads like a
    rendering bug rather than the text it replaced."""
    import re
    import unicodedata
    t = (s or "").replace("`", "")
    t = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", t)
    t = re.sub(r"^#+\s*", "", t)
    t = re.sub(r"^[-*+]\s+", "", t)
    # common typographic characters -> ASCII equivalents before dropping the rest
    for src, dst in (("\u2014", "-"), ("\u2013", "-"), ("\u2026", "..."),
                     ("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'),
                     ("\u201d", '"'), ("\u00a0", " ")):
        t = t.replace(src, dst)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.encode("ascii", "ignore").decode("ascii")
    return " ".join(t.split())


def wrap(s: str, cols: int) -> list[str]:
    """Greedy wrap. The 5x7 font is monospaced, so character count is width."""
    words, lines, cur = s.split(), [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if len(cand) <= cols:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            # a single word longer than the column is hard-split, and the tail
            # carries an ellipsis so the cut is visible rather than looking typed
            cur = w[:cols - 3] + "..." if len(w) > cols else w
    if cur:
        lines.append(cur)
    return lines or [""]


def fit_cols(px: int, scale: int) -> int:
    """How many monospaced glyphs fit in px. Wrapping in characters instead of
    pixels is how a headline ends up wider than the card it sits in."""
    return max(8, px // ((GLYPH_W + 1) * scale))


def fit(s: str, cols: int, rows: int) -> list[str]:
    """Wrap then ellipsize, so a card never spills past its own box."""
    lines = wrap(s, cols)
    if len(lines) <= rows:
        return lines
    out = lines[:rows]
    out[-1] = out[-1][:cols - 1].rstrip() + "..."
    return out


def sheet(brief: dict) -> bytes:
    beats = brief.get("beats") or []
    verdict = brief.get("verdict") or {}
    src = brief.get("source") or {}
    cells = [(b.get("name") or "", plain(b.get("headline") or ""),
              plain(b.get("detail") or "")) for b in beats]
    # The gate card earns its cell: it states why this diff was worth animating.
    byline = f"#{src['pr']}" if src.get("pr") else (src.get("range") or "")
    cells.append(("gate", plain(byline),
                  "; ".join(plain(r) for r in (verdict.get("reasons") or [])[:3])))

    rows = (len(cells) + COLS - 1) // COLS
    width = COLS * CELL_W + (COLS + 1) * PAD
    height = HEADER_H + rows * CELL_H + (rows + 1) * PAD

    c = Canvas(width, height)
    title = plain(src.get("title") or "PR motion explainer")
    c.draw_text(PAD, PAD + 6, title[:fit_cols(width - 2 * PAD, 4)], FG, scale=4)
    stats = (f"{verdict.get('changed_lines', 0)} lines"
             f" / {len(verdict.get('files_meaningful') or [])} files"
             f" / {len(beats)} beats")
    c.draw_text(PAD, PAD + 52, stats, DIM, scale=2)
    c.fill_rect(PAD, HEADER_H - 10, width - 2 * PAD, 2, RULE)

    for i, (name, headline, detail) in enumerate(cells):
        cx = PAD + (i % COLS) * (CELL_W + PAD)
        cy = HEADER_H + PAD + (i // COLS) * (CELL_H + PAD)
        c.fill_rect(cx, cy, CELL_W, CELL_H, CARD_BG)
        accent = ACCENT.get(name, DEFAULT_ACCENT)
        c.fill_rect(cx, cy, 6, CELL_H, accent)
        c.draw_text(cx + 22, cy + 18, name.upper()[:14], accent, scale=2)
        y = cy + 50
        for line in fit(headline, fit_cols(CELL_W - 44, 3), 3):
            c.draw_text(cx + 22, y, line, FG, scale=3)
            y += 26
        y += 8
        for line in fit(detail, fit_cols(CELL_W - 44, 2), 3):
            c.draw_text(cx + 22, y, line, DIM, scale=2)
            y += 18
    return c.to_png()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("brief", help="brief JSON from pr_brief.py")
    ap.add_argument("--out", required=True, help="output PNG path")
    args = ap.parse_args()

    data = json.loads(Path(args.brief).read_text())
    if not data.get("beats"):
        sys.stderr.write("brief has no beats (trivial PR? re-run with --force)\n")
        return 3
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    png = sheet(data)
    out.write_bytes(png)
    print(f"{args.out}: contact sheet, {len(data['beats'])} beats, {len(png)} bytes",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())