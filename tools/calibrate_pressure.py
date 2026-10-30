"""Where does the 256x256 hunting-pressure grid actually sit on the map image?

`cotw/pressure.py` maps cell (row, col) onto the reserve box assuming the grid spans the
whole map rectangle. That was an assumption, and the pressure blobs look offset from the
features they should sit on. This measures it: take the non-zero cells, and search for the
translation (and optionally the scale) that puts them best over the water pixels — hunting
pressure builds where animals are hunted, and drinking zones are at water.

Run:  python tools/calibrate_pressure.py [reserve]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cotw import adf, mapgeo, reserves, save  # noqa: E402

GRID = 256


def load_grid(reserve: int) -> np.ndarray | None:
    directory = save.find_save_dirs()[0]
    path = directory / f"animal_population_{reserve}"
    if not path.is_file():
        return None
    root = adf.parse_document(save.read_container(path).payload).parse_entry(0)
    raw = root.get("HuntingPressureMap")
    if not isinstance(raw, list) or len(raw) != GRID * GRID:
        return None
    return np.array([float(v) for v in raw], dtype=np.float32).reshape(GRID, GRID)


def water_mask(reserve: int) -> tuple[np.ndarray, tuple[int, int]] | None:
    meta = reserves.lookup(reserve)
    if not meta.map_image:
        return None
    path = ROOT / "web" / "assets" / "maps" / meta.map_image
    if not path.is_file():
        return None
    image = Image.open(path).convert("L")
    array = np.asarray(image, dtype=np.float32)
    return (array > 168).astype(np.float32), image.size


def score(mask: np.ndarray, water: np.ndarray, dx: float, dy: float, scale: float) -> float:
    """Mean water value under the non-zero pressure cells."""
    cells = np.argwhere(mask > 0)
    if not len(cells):
        return 0.0
    height, width = water.shape
    total = 0.0
    count = 0
    for row, col in cells:
        # grid -> image, with an offset in cells and a scale on the grid
        u = (col + 0.5) * scale + dx
        v = (row + 0.5) * scale + dy
        if not (0 <= u < width - 1 and 0 <= v < height - 1):
            continue
        total += water[int(v), int(u)]
        count += 1
    return total / count if count else 0.0


def main() -> int:
    reserve = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    grid = load_grid(reserve)
    if grid is None:
        print("FAIL: no pressure grid for this reserve")
        return 1
    loaded = water_mask(reserve)
    if loaded is None:
        print("FAIL: no map image")
        return 1
    water, (width, height) = loaded
    print(f"reserve {reserve}: grid {GRID}x{GRID}, map {width}x{height}, "
          f"{int((grid > 0).sum())} pressure cells, water {100 * water.mean():.1f}%")

    base_scale = width / GRID  # what pressure.py assumes
    print(f"assumed cell size: {base_scale:.2f} px  (grid covers the whole map)")
    start = score(grid > 0, water, 0.0, 0.0, base_scale)
    print(f"score with the current assumption : {start:.3f}")

    best = (start, 0.0, 0.0, base_scale)
    for scale in np.arange(base_scale * 0.9, base_scale * 1.1, base_scale * 0.01):
        for dx in np.arange(-24, 25, 2.0):
            for dy in np.arange(-24, 25, 2.0):
                value = score(grid > 0, water, dx, dy, scale)
                if value > best[0]:
                    best = (value, dx, dy, scale)

    print(f"best translation : dx={best[1]:+.0f} cells, dy={best[2]:+.0f} cells, "
          f"scale={best[3]:.2f} px  -> score {best[0]:.3f}")

    if best[0] > start + 0.02:
        print(f"\n=> the grid is offset by ({best[1]:+.0f}, {best[2]:+.0f}) cells "
              f"from the assumption in cotw/pressure.py")
        span_x = width / best[3]
        span_z = height / best[3]
        box = mapgeo.for_reserve(reserve)
        print(f"   implied world span: {span_x:.0f} x {span_z:.0f} m")
        if box:
            print(f"   map box           : {box['max_x'] - box['min_x']:.0f} x "
                  f"{box['max_y'] - box['min_y']:.0f} m")
    else:
        print("\n=> no meaningful offset found; the current mapping looks right")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
