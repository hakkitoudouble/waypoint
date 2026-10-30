"""Draw the application icon (assets/waypoint.ico).

The look matches the UI's brand mark: a near-black rounded square, two amber rings,
four tick marks and a green centre dot (the "zone feed" colour). Drawn at 4x and
downsampled so the small sizes stay clean.

Run only when the icon needs to change; the .ico is committed so the build does not
depend on Pillow:

    python tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "waypoint.ico"

SIZES = [256, 128, 64, 48, 32, 24, 16]
SCALE = 4

BG = (11, 18, 16, 255)
AMBER = (232, 163, 61)
GREEN = (121, 208, 111)


def draw(size: int) -> Image.Image:
    """One frame, drawn at ``size * SCALE`` and resampled down."""
    big = size * SCALE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # rounded square background
    pad = big * 0.045
    radius = big * 0.22
    draw.rounded_rectangle(
        (pad, pad, big - pad, big - pad), radius=radius, fill=BG,
        outline=(196, 236, 214, 40), width=max(1, int(big * 0.006)),
    )

    cx = cy = big / 2
    # outer ring
    outer = big * 0.335
    draw.ellipse(
        (cx - outer, cy - outer, cx + outer, cy + outer),
        outline=AMBER + (72,), width=max(2, int(big * 0.022)),
    )
    # inner ring
    inner = big * 0.205
    draw.ellipse(
        (cx - inner, cy - inner, cx + inner, cy + inner),
        outline=AMBER + (170,), width=max(2, int(big * 0.024)),
    )
    # four ticks, outside the outer ring
    tick_len = big * 0.055
    tick_w = max(2, int(big * 0.026))
    gap = outer + big * 0.02
    for (x0, y0, x1, y1) in (
        (cx, cy - gap - tick_len, cx, cy - gap),
        (cx, cy + gap, cx, cy + gap + tick_len),
        (cx - gap - tick_len, cy, cx - gap, cy),
        (cx + gap, cy, cx + gap + tick_len, cy),
    ):
        draw.line((x0, y0, x1, y1), fill=AMBER + (215,), width=tick_w)

    # centre dot with a soft halo
    dot = big * 0.088
    halo = big * 0.16
    draw.ellipse((cx - halo, cy - halo, cx + halo, cy + halo), fill=GREEN + (38,))
    draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=GREEN + (255,))

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    frames = [draw(size) for size in SIZES]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, sizes: {', '.join(map(str, SIZES))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
