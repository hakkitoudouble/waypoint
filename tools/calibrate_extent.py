"""Fit each reserve's map extent objectively, using hunting pressure as the anchor.

The world->pixel transform is under-determined by need zones alone: shrink the box and
the zones fill the map, grow it and they collapse into a corner, and both look
"possible". So we need an independent signal.

`AnimalPopulationReserveData_9.HuntingPressureMap` is a 256x256 grid over the whole
reserve recording where the player has actually hunted. Need zones are discovered by
walking around, so they should sit on cells with real pressure. Sweeping the extent
(and the four axis flips) and scoring by the mean pressure under the zones gives an
objective optimum instead of a guess.

Run:  python tools/calibrate_extent.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw import adf, population, reserves, save  # noqa: E402

GRID = 256
MAPS = Path(__file__).resolve().parent.parent / "web" / "assets" / "maps"
CANDIDATES = [h for h in range(3000, 17001, 250)]
FLIPS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]


def pressure_grid(path: Path) -> list[int]:
    doc = adf.parse_document(save.read_container(path).payload)
    root = doc.parse_entry(0)
    grid = root.get("HuntingPressureMap") or []
    return list(grid)


def score(grid: list[int], zones: list, half: float, flip: tuple[int, int]) -> tuple[float, int]:
    if not grid:
        return 0.0, 0
    fx, fz = flip
    total = 0.0
    inside = 0
    for z in zones:
        u = (z.x * fx + half) / (2 * half)
        v = (z.z * fz + half) / (2 * half)
        if not (0.0 <= u < 1.0 and 0.0 <= v < 1.0):
            continue
        cx = min(GRID - 1, int(u * GRID))
        cy = min(GRID - 1, int(v * GRID))
        total += grid[cy * GRID + cx]
        inside += 1
    if not inside:
        return 0.0, 0
    return total / inside, inside


def main() -> int:
    dirs = save.find_save_dirs()
    if not dirs:
        print("no save dir")
        return 1
    save_dir = dirs[0]
    zones = population.scan_need_zones(save_dir)

    for rid in sorted(zones):
        path = save_dir / f"animal_population_{rid}"
        if not path.is_file():
            print(f"reserve {rid}: no population file")
            continue
        try:
            grid = pressure_grid(path)
        except Exception as exc:  # noqa: BLE001
            print(f"reserve {rid}: pressure map unreadable ({exc})")
            continue
        if not grid:
            print(f"reserve {rid}: no pressure map")
            continue

        nonzero = sum(1 for v in grid if v)
        baseline = sum(grid) / len(grid)
        items = zones[rid]

        best = None
        for flip in FLIPS:
            for half in CANDIDATES:
                value, inside = score(grid, items, half, flip)
                if inside < 0.95 * len(items):
                    continue
                if best is None or value > best[0]:
                    best = (value, half, flip, inside)

        meta = reserves.lookup(rid)
        if best is None:
            print(f"reserve {rid:>2} {meta.display_name or '?':<28} "
                  f"zones={len(items):<4} pressure_cells={nonzero:<6} -> no fit")
            continue
        value, half, flip, inside = best
        lift = value / baseline if baseline else 0.0
        print(f"reserve {rid:>2} {meta.display_name or '?':<28} zones={len(items):<4} "
              f"pressure_cells={nonzero:<6} best half-extent={half:>6.0f} m  flip={flip}  "
              f"pressure x{lift:.2f} over baseline ({value:.2f} vs {baseline:.2f})")

    print("\nInterpretation: a large lift means the zones really do sit on hunted ground at")
    print("that extent. A lift near 1.0 means the pressure map is uninformative here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
