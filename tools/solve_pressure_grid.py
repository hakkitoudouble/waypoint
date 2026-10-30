"""Solve the 256x256 grid mapping from two real in-game alert zones.

Two alert zones read off the game's map cursor:

    Z1 = (-7341.803, -13072.518)   "Alerte moyenne"
    Z2 = (-5992.380, -12637.570)   "Alerte basse"

Their world separation is known exactly. If we can identify the two pressure blobs they
correspond to in the grid, the ratio gives the cell size on each axis:

    cell_x = |Z2.x - Z1.x| / |col2 - col1|
    cell_z = |Z2.z - Z1.z| / |row2 - row1|

If cell_x == cell_z the cells are square (the game uses a uniform world grid) and the
current stretched mapping is wrong. If cell_x / cell_z == 1.316 — the map's aspect ratio —
then the stretched mapping is right and the error lies elsewhere.

Run:  python tools/solve_pressure_grid.py
"""

from __future__ import annotations

import math
import sys
from collections import deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cotw import adf, mapgeo, save  # noqa: E402

GRID = 256
Z1 = (-7341.803, -13072.518)
Z2 = (-5992.380, -12637.570)


def blobs(grid: np.ndarray) -> list[dict]:
    hot = grid > 0
    seen = np.zeros_like(hot)
    out = []
    for row in range(GRID):
        for col in range(GRID):
            if not hot[row, col] or seen[row, col]:
                continue
            queue = deque([(row, col)])
            seen[row, col] = True
            cells = []
            while queue:
                r, c = queue.popleft()
                cells.append((r, c))
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < GRID and 0 <= nc < GRID and hot[nr, nc] and not seen[nr, nc]:
                            seen[nr, nc] = True
                            queue.append((nr, nc))
            weights = [grid[r, c] for r, c in cells]
            total = sum(weights) or 1.0
            out.append({
                "cells": len(cells),
                "row": sum(r * w for (r, _), w in zip(cells, weights)) / total,
                "col": sum(c * w for (_, c), w in zip(cells, weights)) / total,
                "peak": max(weights),
                "mass": total,
            })
    out.sort(key=lambda b: -b["mass"])
    return out


def main() -> int:
    directory = save.find_save_dirs()[0]
    grid = np.array(
        [float(v) for v in adf.parse_document(
            save.read_container(directory / "animal_population_9").payload
        ).parse_entry(0)["HuntingPressureMap"]],
        dtype=np.float32,
    ).reshape(GRID, GRID)
    box = mapgeo.for_reserve(9)
    span_x = box["max_x"] - box["min_x"]
    span_z = box["max_y"] - box["min_y"]

    found = blobs(grid)
    print(f"{len(found)} blobs de pression")
    for index, blob in enumerate(found[:8]):
        print(f"  #{index}: {blob['cells']:>3} cellules  centre (ligne {blob['row']:5.1f}, "
              f"col {blob['col']:5.1f})  pic {blob['peak']:.0f}  masse {blob['mass']:.0f}")

    def cell_of(zone):
        return ((zone[1] - box["min_y"]) / span_z * GRID,
                (zone[0] - box["min_x"]) / span_x * GRID)

    r1, c1 = cell_of(Z1)
    r2, c2 = cell_of(Z2)
    print(f"\nZ1 {Z1} -> cellule (ligne {r1:.1f}, col {c1:.1f})")
    print(f"Z2 {Z2} -> cellule (ligne {r2:.1f}, col {c2:.1f})")

    world_dx = Z2[0] - Z1[0]
    world_dz = Z2[1] - Z1[1]
    world_distance = math.hypot(world_dx, world_dz)
    print(f"\necarte monde entre les deux zones : dx={world_dx:+.0f} m, dz={world_dz:+.0f} m, "
          f"distance {world_distance:.0f} m")

    print("\nmeilleure paire de blobs pour ces deux zones :")
    best = None
    for i, a in enumerate(found):
        for j, b in enumerate(found):
            if i == j:
                continue
            d_col = b["col"] - a["col"]
            d_row = b["row"] - a["row"]
            if abs(d_col) < 2 and abs(d_row) < 2:
                continue
            # orient the pair like the zones
            if d_col * world_dx < 0 or d_row * world_dz < 0:
                continue
            cell_x = abs(world_dx / d_col) if d_col else float("inf")
            cell_z = abs(world_dz / d_row) if d_row else float("inf")
            # prefer pairs close to the zones' own grid positions
            err = math.hypot(a["row"] - r1, a["col"] - c1) + math.hypot(b["row"] - r2, b["col"] - c2)
            score = err
            if best is None or score < best[0]:
                best = (score, a, b, cell_x, cell_z, d_col, d_row)
    if best is None:
        print("  aucune paire compatible — la grille ne peut pas être appariée ainsi")
        return 2
    _, a, b, cell_x, cell_z, d_col, d_row = best
    print(f"  blob A centre (ligne {a['row']:.1f}, col {a['col']:.1f})  <- Z1")
    print(f"  blob B centre (ligne {b['row']:.1f}, col {b['col']:.1f})  <- Z2")
    print(f"  ecart grille : dcol={d_col:+.1f}  drow={d_row:+.1f}")
    print(f"  => cellule_x = {cell_x:.1f} m   cellule_z = {cell_z:.1f} m")

    current_x = span_x / GRID
    current_z = span_z / GRID
    print(f"\ncelle actuelle : {current_x:.1f} x {current_z:.1f} m")
    print(f"ratio obtenu   : {cell_x / cell_z if cell_z else 0:.3f}")
    print(f"ratio de la carte (etirement suppose) : {current_x / current_z:.3f}")
    print(f"ratio 1.0 = cellules carrees")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
