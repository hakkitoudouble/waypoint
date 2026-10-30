"""Draw the Waypoint icon: the app icon (.ico) and the PNG masters.

The mark is the one the interface uses: a target/radar (two amber rings + four ticks)
with a green centre dot for the player. At 128 px and above, the three need-zone glyphs
of the map legend (feed = rounded square, drink = circle, rest = triangle) sit on the
ring, so the icon says "population scanner + need-zone map" without words.

Drawn at 4x and downsampled, so every size stays clean.

    python tools/make_icon.py                # writes assets/waypoint*.png + .ico
    python tools/make_icon.py --preview-only # just the 512 px PNG
"""

from __future__ import annotations

import argparse
import io
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICO = ASSETS / "waypoint.ico"
PNG_SIZES = (1024, 512, 256)
ICO_SIZES = (256, 128, 64, 48, 32, 24, 16)
SCALE = 4

#: the interface's own palette (style.css)
BG_TOP = (18, 27, 23)
BG_BOTTOM = (6, 9, 8)
AMBER = (232, 163, 61)
AMBER_HI = (255, 205, 130)
GREEN = (121, 208, 111)
BLUE = (92, 184, 255)
ORANGE = (255, 171, 94)
INK = (6, 10, 8)


def _rounded_mask(big: int) -> Image.Image:
    mask = Image.new("L", (big, big), 0)
    pad = big * 0.035
    ImageDraw.Draw(mask).rounded_rectangle(
        (pad, pad, big - pad, big - pad), radius=big * 0.225, fill=255
    )
    return mask


def _glyph(draw: ImageDraw.ImageDraw, kind: str, cx: float, cy: float, size: float) -> None:
    """One need-zone marker, with a dark rim so it reads on the amber ring."""
    rim = max(2, int(size * 0.16))
    if kind == "feed":
        box = (cx - size, cy - size, cx + size, cy + size)
        draw.rounded_rectangle(box, radius=size * 0.34, fill=GREEN + (255,),
                               outline=INK + (200,), width=rim)
    elif kind == "drink":
        box = (cx - size, cy - size, cx + size, cy + size)
        draw.ellipse(box, fill=BLUE + (255,), outline=INK + (200,), width=rim)
    else:  # rest
        points = [
            (cx, cy - size * 1.08),
            (cx + size * 1.06, cy + size * 0.82),
            (cx - size * 1.06, cy + size * 0.82),
        ]
        draw.polygon(points, fill=ORANGE + (255,))
        draw.line(points + [points[0]], fill=INK + (200,), width=rim, joint="curve")


def draw(size: int, detail: bool | None = None) -> Image.Image:
    """Render one frame at ``size`` px."""
    if detail is None:
        detail = size >= 128
    big = size * SCALE
    cx = cy = big / 2

    # ── background: vertical gradient, clipped to a rounded square ─────────
    gradient = Image.new("RGB", (big, big))
    pen = ImageDraw.Draw(gradient)
    for y in range(big):
        t = y / max(1, big - 1)
        colour = tuple(
            int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * (t ** 0.85)) for i in range(3)
        )
        pen.line([(0, y), (big, y)], fill=colour)
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    img.paste(gradient, (0, 0), _rounded_mask(big))

    # ── soft amber glow behind the mark ────────────────────────────────────
    glow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    r = big * 0.30
    ImageDraw.Draw(glow).ellipse((cx - r, cy - r, cx + r, cy + r), fill=AMBER + (70,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(big * 0.06)))

    draw = ImageDraw.Draw(img)

    # ── the four ticks, outside the outer ring ─────────────────────────────
    outer = big * 0.318
    tick_len = big * 0.062
    tick_w = max(2, int(big * 0.024))
    gap = outer + big * 0.028
    for angle in (0, 90, 180, 270):
        a = math.radians(angle - 90)
        dx, dy = math.cos(a), math.sin(a)
        draw.line(
            (cx + dx * gap, cy + dy * gap,
             cx + dx * (gap + tick_len), cy + dy * (gap + tick_len)),
            fill=AMBER_HI + (235,), width=tick_w,
        )

    # ── the two rings ──────────────────────────────────────────────────────
    draw.ellipse(
        (cx - outer, cy - outer, cx + outer, cy + outer),
        outline=AMBER + (150,), width=max(2, int(big * 0.019)),
    )
    inner = big * 0.192
    draw.ellipse(
        (cx - inner, cy - inner, cx + inner, cy + inner),
        outline=AMBER + (255,), width=max(2, int(big * 0.026)),
    )

    # ── the three zone glyphs, as badges on the outer ring ─────────────────
    if detail:
        badge_r = big * 0.062
        glyph_r = big * 0.032
        for kind, angle in (("feed", 45), ("drink", 165), ("rest", 285)):
            a = math.radians(angle - 90)
            bx = cx + math.cos(a) * outer
            by = cy + math.sin(a) * outer
            draw.ellipse(
                (bx - badge_r, by - badge_r, bx + badge_r, by + badge_r),
                fill=BG_BOTTOM + (255,), outline=AMBER + (190,),
                width=max(1, int(big * 0.008)),
            )
            _glyph(draw, kind, bx, by, glyph_r)

    # ── the player: green dot with a halo ──────────────────────────────────
    halo = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    hr = big * 0.105
    ImageDraw.Draw(halo).ellipse((cx - hr, cy - hr, cx + hr, cy + hr), fill=GREEN + (90,))
    img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(big * 0.025)))
    draw = ImageDraw.Draw(img)
    dot = big * 0.062
    draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=GREEN + (255,), outline=INK + (150,),
                 width=max(1, int(big * 0.006)))

    return img.resize((size, size), Image.LANCZOS)


def save_ico(path: Path, frames: list[Image.Image]) -> None:
    """Write a multi-resolution .ico with one PNG entry per frame.

    Pillow's own ICO writer downscales a *single* image for every size, which would
    throw away the small-size art (rings and dot only, no glyphs). Writing the
    container by hand keeps each size exactly as drawn; Windows Vista and later read
    PNG-compressed entries at any size.
    """
    blobs: list[bytes] = []
    for frame in frames:
        buffer = io.BytesIO()
        frame.save(buffer, format="PNG", optimize=True)
        blobs.append(buffer.getvalue())

    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries = b""
    for frame, blob in zip(frames, blobs):
        side = frame.width
        entries += struct.pack(
            "<BBBBHHII", side % 256, side % 256, 0, 0, 1, 32, len(blob), offset
        )
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview-only", action="store_true", help="skip the .ico")
    args = parser.parse_args(argv)

    ASSETS.mkdir(exist_ok=True)
    for size in PNG_SIZES:
        frame = draw(size)
        path = ASSETS / f"waypoint-{size}.png"
        frame.save(path)
        print(f"wrote {path} ({path.stat().st_size // 1024} KB)")

    if not args.preview_only:
        save_ico(ICO, [draw(size) for size in ICO_SIZES])
        print(f"wrote {ICO} ({ICO.stat().st_size // 1024} KB, {len(ICO_SIZES)} sizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
