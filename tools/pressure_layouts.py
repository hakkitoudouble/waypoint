"""Which layout of the 256x256 pressure grid matches the water on the map?

The game paints its hunting-pressure zones over the map, and on the reference screenshots
they sit on the lakes. Our blobs do not. A transposition or a flip would explain that and
would NOT show up as a translation, so test all eight dihedral layouts of the grid against
the water pixels of the map image.

Run:  python tools/pressure_layouts.py [reserve]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cotw import adf, mapgeo, reserves, save  # noqa: E402

GRID = 256

LAYOUTS = {
    "identity": lambda g: g,
    "flip rows": lambda g: g[::-1, :],
    "flip cols": lambda g: g[:, ::-1],
    "rot 180": lambda g: g[::-1, ::-1],
    "transpose": lambda g: g.T,
    "transpose + flip rows": lambda g: g.T[::-1, :],
    "transpose + flip cols": lambda g: g.T[:, ::-1],
    "transpose + rot 180": lambda g: g.T[::-1, ::-1],
}


def water_field(reserve: int) -> np.ndarray | None:
    """Smoothed water likelihood over the map image."""
    meta = reserves.lookup(reserve)
    if not meta.map_image:
        return None
    path = ROOT / "web" / "assets" / "maps" / meta.map_image
    if not path.is_file():
        return None
    array = np.asarray(Image.open(path).convert("L"), dtype=np.float32)
    mask = (array > 168).astype(np.float32) * 255
    big = Image.fromarray(mask.astype(np.uint8)).filter(ImageFilter.GaussianBlur(6))
    wide = np.asarray(big, dtype=np.float32)
    field = Image.fromarray(wide.astype(np.uint8)).filter(ImageFilter.GaussianBlur(18))
    return np.asarray(field, dtype=np.float32) / 255.0


def main() -> int:
    reserve = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    directory = save.find_save_dirs()[0]
    root = adf.parse_document(
        save.read_container(directory / f"animal_population_{reserve}").payload
    ).parse_entry(0)
    raw = root.get("HuntingPressureMap")
    if not isinstance(raw, list) or len(raw) != GRID * GRID:
        print("FAIL: no pressure grid")
        return 1
    grid = np.array([float(v) for v in raw], dtype=np.float32).reshape(GRID, GRID)
    field = water_field(reserve)
    if field is None:
        print("FAIL: no map image")
        return 1
    height, width = field.shape

    print(f"reserve {reserve}: {int((grid > 0).sum())} pressure cells, "
          f"map {width}x{height}, water covers {100 * (field > 0.5).mean():.1f}%")
    print()
    print(f"{'layout':<24}{'on water':>10}{'mean field':>12}")
    print("-" * 46)

    results = []
    for name, transform in LAYOUTS.items():
        moved = transform(grid)
        rows, cols = np.nonzero(moved > 0)
        if not len(rows):
            continue
        u = ((cols + 0.5) / GRID * width).astype(int).clip(0, width - 1)
        v = ((rows + 0.5) / GRID * height).astype(int).clip(0, height - 1)
        values = field[v, u]
        results.append((float(values.mean()), name,
                        float((values > 0.5).mean())))
    results.sort(reverse=True)
    for mean_field, name, on_water in results:
        print(f"{name:<24}{100 * on_water:>9.0f}%{mean_field:>12.3f}")

    print("-" * 46)
    best = results[0]
    base = next(r for r in results if r[1] == "identity")
    print(f"best : {best[1]}  ({100 * best[2]:.0f}% of cells on water, field {best[0]:.3f})")
    print(f"identity : {100 * base[2]:.0f}% on water, field {base[0]:.3f}")
    if best[1] != "identity" and best[0] > base[0] * 1.5:
        print(f"\\n=> the grid is stored as '{best[1]}'; cotw/pressure.py assumes identity")
    else:
        print("\\n=> identity is already the best layout; the misplacement is not a flip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
