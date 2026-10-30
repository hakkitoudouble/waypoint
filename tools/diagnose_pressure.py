"""Is the hunting-pressure grid aligned with the rest of the reserve data?

`HuntingPressureMap` is a 256x256 grid in the population file; `adf_fog_of_war_data_faster_N`
is a 256x256 mask in its own file. If they share the same layout, the pressure cells must
fall inside the explored part of the fog — you can only build pressure where you have been.

That is a much stronger test than "pressure sits on water", because it does not depend on
rendering choices.

Run:  python tools/diagnose_pressure.py [reserve]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cotw import adf, save  # noqa: E402

GRID = 256


def grid_from(path: Path, key: str) -> np.ndarray | None:
    if not path.is_file():
        return None
    try:
        root = adf.parse_document(save.read_container(path).payload).parse_entry(0)
    except Exception:  # noqa: BLE001
        return None
    raw = root.get(key)
    if not isinstance(raw, list) or len(raw) != GRID * GRID:
        return None
    return np.array([float(v) for v in raw], dtype=np.float32).reshape(GRID, GRID)


def main() -> int:
    reserve = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    directory = save.find_save_dirs()[0]
    pressure = grid_from(directory / f"animal_population_{reserve}", "HuntingPressureMap")
    fog = grid_from(directory / f"adf_fog_of_war_data_faster_{reserve}", "Mask")
    if pressure is None:
        print("FAIL: no pressure grid")
        return 1
    if fog is None:
        print("FAIL: no fog grid")
        return 1

    hot = pressure > 0
    explored = fog < 250
    print(f"reserve {reserve}")
    print(f"  pressure cells : {int(hot.sum())}  ({100 * hot.mean():.1f}% of the grid)")
    print(f"  explored cells : {int(explored.sum())}  ({100 * explored.mean():.1f}%)")
    print(f"  pressure inside explored : {100 * explored[hot].mean():.1f}%")
    print(f"  explored baseline        : {100 * explored.mean():.1f}%")

    if explored[hot].mean() > explored.mean() + 0.1:
        print("  => the pressure sits in explored territory, so both grids share a layout")

    # Where is the pressure centroid, in each grid, and where is the explored centroid?
    rows, cols = np.nonzero(hot)
    frows, fcols = np.nonzero(explored)
    print(f"\n  pressure centroid : col {cols.mean():.0f}, row {rows.mean():.0f}")
    print(f"  explored centroid : col {fcols.mean():.0f}, row {frows.mean():.0f}")
    print(f"  pressure bbox     : cols {cols.min()}..{cols.max()}, rows {rows.min()}..{rows.max()}")
    print(f"  explored bbox     : cols {fcols.min()}..{fcols.max()}, rows {frows.min()}..{frows.max()}")

    # try the eight dihedral layouts of the pressure grid against the fog
    variants = {
        "identity": lambda g: g,
        "flip rows": lambda g: g[::-1, :],
        "flip cols": lambda g: g[:, ::-1],
        "rot180": lambda g: g[::-1, ::-1],
        "transpose": lambda g: g.T,
        "transpose+flip rows": lambda g: g.T[::-1, :],
        "transpose+flip cols": lambda g: g.T[:, ::-1],
        "transpose rot180": lambda g: g.T[::-1, ::-1],
    }
    print("\n  overlap of pressure cells with explored territory, per layout:")
    best = ("", -1.0)
    for name, transform in variants.items():
        moved = transform(hot)
        value = float(explored[moved].mean())
        if value > best[1]:
            best = (name, value)
        print(f"    {name:<22} {100 * value:5.1f}%")
    print(f"  best layout: {best[0]} ({100 * best[1]:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
