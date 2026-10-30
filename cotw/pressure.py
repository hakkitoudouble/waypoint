"""Hunting pressure, read from the save.

Every population file carries `HuntingPressureMap`: a 256 x 256 grid of the reserve where
each cell holds how much hunting pressure has accumulated there (0-100). It is the same
information the game paints as blue "alert zones", the thing that pushes animals away.

Verified on a real save: reserve 9 has 318 non-zero cells out of 65 536, peaking at 100,
and they land on the map exactly where the player had been hunting once projected with
the recovered georeference (`cotw/data/map_geo.json`).

Cell (row, col) maps onto the reserve box as::

    x = min_x + (col + 0.5) / 256 * (max_x - min_x)
    z = min_y + (row + 0.5) / 256 * (max_y - min_y)

Only non-zero cells are returned, so the payload stays tiny (a few hundred entries).
"""

from __future__ import annotations

from pathlib import Path

from . import adf, mapgeo, reserves, save

GRID = 256

#: The grid does NOT span the map rectangle.
#:
#: Two alert zones were read off the game's own map cursor:
#:     (Alerte moyenne)  (-7341.803, -13072.518)
#:     (Alerte basse)    (-5992.380, -12637.570)
#: Under the naive "grid stretched over the map box" mapping the first one landed on a
#: cell holding **no pressure at all**, 505 m from the nearest active cell — the placement
#: was wrong, which is exactly what the player reported.
#:
#: Matching the two zones to their blobs in the grid and solving gives the transform below.
#: It puts both reference zones on cells that do carry pressure (80 and 115), which the old
#: mapping could not. The cell sizes come out anisotropic (30.7 x 39.2 m) and are therefore
#: fitted, not derived; two points fix four numbers exactly and leave no residual to test,
#: so this is provisional until a third zone confirms it.
CALIBRATION: dict[int, dict[str, float]] = {
    9: {"cell_x": 30.67, "cell_z": 39.18, "origin_x": -8620.7, "origin_z": -13636.8},
}


def read_pressure(directory: str | Path, reserve: int) -> dict:
    """Non-zero pressure cells for one reserve, with their world positions."""
    directory = Path(directory)
    filename = f"animal_population_{int(reserve)}"
    path = directory / filename
    if not path.is_file():
        return {"reserve": int(reserve), "grid": GRID, "cells": [], "max": 0.0, "count": 0}

    root = adf.parse_document(save.read_container(path).payload).parse_entry(0)
    raw = root.get("HuntingPressureMap")
    if not isinstance(raw, list) or len(raw) != GRID * GRID:
        return {"reserve": int(reserve), "grid": GRID, "cells": [], "max": 0.0, "count": 0}

    box = mapgeo.for_reserve(reserve)
    if box is None:
        meta = reserves.lookup(reserve)
        from . import population

        world = population.fitted_world(population.scan_need_zones(directory).get(reserve, []),
                                        meta.pixel_size)
        box = world.as_dict()
        box["min_y"], box["max_y"] = box.get("min_y"), box.get("max_y")

    measured = CALIBRATION.get(int(reserve))
    if measured:
        cell_x = measured["cell_x"]
        cell_z = measured["cell_z"]
        origin_x = measured["origin_x"]
        origin_z = measured["origin_z"]
    else:
        span_x = box["max_x"] - box["min_x"]
        span_z = box["max_y"] - box["min_y"]
        cell_x = span_x / GRID
        cell_z = span_z / GRID
        origin_x = box["min_x"]
        origin_z = box["min_y"]

    cells: list[list[float]] = []
    peak = 0.0
    for index, value in enumerate(raw):
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number <= 0:
            continue
        row, col = divmod(index, GRID)
        x = origin_x + (col + 0.5) * cell_x
        z = origin_z + (row + 0.5) * cell_z
        cells.append([round(x, 1), round(z, 1), round(number, 2)])
        peak = max(peak, number)

    return {
        "reserve": int(reserve),
        "grid": GRID,
        "max": peak,
        "count": len(cells),
        "calibrated": bool(measured),
        "cell": [round(cell_x, 2), round(cell_z, 2)],
        "origin": [round(origin_x, 1), round(origin_z, 1)],
        "cells": cells,
    }
