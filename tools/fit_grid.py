"""Fit the 256x256 grid mapping using the fog of war, then check it against a real alert zone.

Three independent signals exist:

1. the fog of war (256x256) is where the player has been, so it must stay inside the
   playable terrain of the map image — not on the dark canvas outside the reserve;
2. the hunting pressure should not be everywhere either;
3. one real alert zone is known at (-7341.803, -13072.518), read off the game's own map
   cursor. It must land on a cell that carries pressure.

The fit below only uses (1), which is a big robust shape. Then it is scored against (3),
which was never used to build it. If both agree, the mapping is right.

Run:  python tools/fit_grid.py [reserve]
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
ALERT_ZONE = (-7341.803, -13072.518)   # read in game: "PISTE DE SILVESTRE" selection


def load(reserve: int):
    directory = save.find_save_dirs()[0]
    fog = adf.parse_document(
        save.read_container(directory / f"adf_fog_of_war_data_faster_{reserve}").payload
    ).parse_entry(0)["Mask"]
    pressure = adf.parse_document(
        save.read_container(directory / f"animal_population_{reserve}").payload
    ).parse_entry(0)["HuntingPressureMap"]
    explored = np.array([int(float(v)) < 250 for v in fog]).reshape(GRID, GRID)
    hot = np.array([float(v) for v in pressure], dtype=np.float32).reshape(GRID, GRID) > 0
    meta = reserves.lookup(reserve)
    image = np.asarray(Image.open(ROOT / "web" / "assets" / "maps" / meta.map_image).convert("L"),
                       dtype=np.float32)
    return explored, hot, image, meta.pixel_size


def project(cell, ox, oz, box, size):
    """Grid cell centres -> map image pixels, or None if they leave the image."""
    width, height = size
    span_x = box["max_x"] - box["min_x"]
    span_z = box["max_y"] - box["min_y"]
    def map_rows_cols(rows, cols):
        xs = ox + (cols + 0.5) * cell
        zs = oz + (rows + 0.5) * cell
        u = (xs - box["min_x"]) / span_x * width
        v = (zs - box["min_y"]) / span_z * height
        return u, v
    return map_rows_cols


def main() -> int:
    reserve = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    explored, hot, image, size = load(reserve)
    box = mapgeo.for_reserve(reserve)
    width, height = size
    dark = image < 40           # the canvas outside the playable terrain
    playable = ~dark
    print(f"reserve {reserve}: fog {int(explored.sum())} cells, pressure {int(hot.sum())} cells, "
          f"map {width}x{height}, playable {100 * playable.mean():.1f}%")

    ers, ecs = np.nonzero(explored)

    def fog_on_terrain(cell, ox, oz):
        project_ = project(cell, ox, oz, box, size)
        u, v = project_(ers, ecs)
        inside = (u >= 0) & (u < width) & (v >= 0) & (v < height)
        if inside.mean() < 0.9:
            return -1.0, 0.0
        good = playable[v[inside].astype(int), u[inside].astype(int)]
        return float(good.mean()), float(inside.mean())

    # baseline: the current assumption (grid stretched over the whole map box)
    base_score, _ = fog_on_terrain((box["max_x"] - box["min_x"]) / GRID,
                                   box["min_x"], box["min_y"])
    print(f"current mapping (stretched, { (box['max_x']-box['min_x'])/GRID:.1f} m cells): "
          f"{100 * base_score:.1f}% of the fog on playable terrain")

    print("\nfitting square cells on the fog alone...")
    best = (base_score, None, None, None)
    for cell in np.arange(26.0, 50.01, 1.0):
        for ox in np.arange(-12000, -6000, 50):
            for oz in np.arange(-16000, -10000, 50):
                value, inside = fog_on_terrain(cell, ox, oz)
                if value > best[0]:
                    best = (value, cell, ox, oz)
    score, cell, ox, oz = best
    print(f"  best: cell={cell:.0f} m, origin=({ox:.0f}, {oz:.0f})  "
          f"-> {100 * score:.1f}% of the fog on playable terrain "
          f"(+{100 * (score - base_score):.1f} points)")

    # Now the alert zone, which the fit never saw.
    def pressure_at(x, z):
        col = int((x - ox) / cell)
        row = int((z - oz) / cell)
        if not (0 <= row < GRID and 0 <= col < GRID):
            return None, row, col
        return bool(hot[row, col]), row, col

    print("\nchecking the known alert zone (not used for the fit) :")
    for label, params in (("current mapping",
                           ((box["max_x"] - box["min_x"]) / GRID, box["min_x"], box["min_y"])),
                          ("fitted square cells", (cell, ox, oz))):
        c, x0, z0 = params
        col = int((ALERT_ZONE[0] - x0) / c)
        row = int((ALERT_ZONE[1] - z0) / c)
        if 0 <= row < GRID and 0 <= col < GRID:
            value = bool(hot[row, col])
            print(f"  {label:<22} -> cell (row {row}, col {col})  pressure: {'YES' if value else 'no'}")
        else:
            print(f"  {label:<22} -> cell (row {row}, col {col})  OUTSIDE the grid")

    if score > base_score + 0.02:
        print(f"\n=> the grid spans {GRID * cell:.0f} m square, not the map rectangle; "
              f"cotw/pressure.py stretches it wrongly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
