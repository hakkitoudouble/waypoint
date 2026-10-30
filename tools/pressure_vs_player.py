"""Compare the hunting-pressure centroid with the player's last saved position.

Hunting pressure builds where the player has been hunting, so on every reserve the
pressure should cluster near the player's last known position. Doing that comparison
across all reserves turns a subjective "it looks offset" into a measurement: if the
centroid is systematically displaced in the same direction, the grid mapping has a
constant bug; if the offsets point in all directions, the mapping is fine and the
difference is just where the player happened to hunt.

Run:  python tools/pressure_vs_player.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cotw import adf, mapgeo, player, reserves, save  # noqa: E402

GRID = 256


def main() -> int:
    directory = save.find_save_dirs()[0]
    positions = player.last_positions(directory)
    print(f"{'res':<4}{'reserve':<28}{'cells':>6}{'centroid (world)':>24}"
          f"{'player':>20}{'distance':>10}")
    print("-" * 96)

    offsets: list[tuple[float, float]] = []
    for path in save.list_population_files(directory):
        index = save.reserve_index(path)
        if index not in positions:
            continue
        try:
            root = adf.parse_document(save.read_container(path).payload).parse_entry(0)
        except Exception:  # noqa: BLE001
            continue
        raw = root.get("HuntingPressureMap")
        if not isinstance(raw, list) or len(raw) != GRID * GRID:
            continue
        grid = np.array([float(v) for v in raw], dtype=np.float32).reshape(GRID, GRID)
        hot = grid > 0
        if hot.sum() < 5:
            continue
        box = mapgeo.for_reserve(index)
        if box is None:
            continue
        rows, cols = np.nonzero(hot)
        weights = grid[rows, cols]
        col = float((cols * weights).sum() / weights.sum())
        row = float((rows * weights).sum() / weights.sum())
        x = box["min_x"] + (col + 0.5) / GRID * (box["max_x"] - box["min_x"])
        z = box["min_y"] + (row + 0.5) / GRID * (box["max_y"] - box["min_y"])
        target = positions[index]
        distance = math.hypot(x - target.x, z - target.z)
        offsets.append((x - target.x, z - target.z))
        name = (reserves.lookup(index).display_name or "?")[:27]
        print(f"{index:<4}{name:<28}{int(hot.sum()):>6}"
              f"({x:>8.0f},{z:>9.0f})  ({target.x:>7.0f},{target.z:>8.0f}){distance:>9.0f} m")

    print("-" * 96)
    if not offsets:
        print("no comparable reserve")
        return 0
    mean_x = sum(o[0] for o in offsets) / len(offsets)
    mean_z = sum(o[1] for o in offsets) / len(offsets)
    spread_x = math.sqrt(sum((o[0] - mean_x) ** 2 for o in offsets) / len(offsets))
    spread_z = math.sqrt(sum((o[1] - mean_z) ** 2 for o in offsets) / len(offsets))
    print(f"mean offset   : dx={mean_x:+.0f} m  dz={mean_z:+.0f} m")
    print(f"spread        : sd_x={spread_x:.0f} m  sd_z={spread_z:.0f} m")
    print()
    if abs(mean_x) > 0.5 * spread_x and abs(mean_z) < 0.5 * spread_x:
        print("=> a systematic offset on one axis: the grid mapping is probably wrong")
    else:
        print("=> the offsets point in no consistent direction: the mapping is sound, "
              "the pressure simply sits where the player hunted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
