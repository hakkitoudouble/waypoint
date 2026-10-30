"""Per-reserve georeference for the map images.

The plotting box used by the map is currently *derived from the zones themselves*
(`population.fitted_world`): it takes their bounding box, pads it 6 % and corrects the
aspect. That is circular — it guarantees the zones fill the image edge to edge no matter
where the reserve actually sits on its texture, so a zone 124 m from the player can be
drawn 1000 m away.

A real georeference needs at least two (world position, image pixel) pairs: two points
fix the scale and the offset in both axes, and with them the orientation. This module
stores those calibrations, and `population.reserve_world` prefers them over the fitted
box whenever one exists.

File layout (`cotw/data/map_geo.json`):

    {
      "9": {
        "min_x": -13250.0, "max_x": 2100.0,
        "min_z": -15200.0, "max_z": -4800.0,
        "flip_z": false,
        "pixel_size": [1343, 1020],
        "source": "calibrated:corners",
        "confidence": "measured"
      }
    }
"""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "map_geo.json"


def load() -> dict[str, dict]:
    if not DATA.is_file():
        return {}
    try:
        payload = json.loads(DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in payload.items() if isinstance(v, dict)}


def for_reserve(index: int | None) -> dict | None:
    if index is None:
        return None
    entry = load().get(str(int(index)))
    if not entry:
        return None
    try:
        box = {
            "min_x": float(entry["min_x"]),
            "max_x": float(entry["max_x"]),
            "min_y": float(entry["min_z"]),
            "max_y": float(entry["max_z"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
    if box["max_x"] <= box["min_x"] or box["max_y"] <= box["min_y"]:
        return None
    box["flip_z"] = bool(entry.get("flip_z", False))
    box["source"] = entry.get("source", "calibrated")
    return box


def save(index: int, box: dict, pixel_size: tuple[int, int] | None = None,
         source: str = "calibrated:corners") -> None:
    payload = load()
    payload[str(int(index))] = {
        "min_x": round(float(box["min_x"]), 2),
        "max_x": round(float(box["max_x"]), 2),
        "min_z": round(float(box["min_y"]), 2),
        "max_z": round(float(box["max_y"]), 2),
        "flip_z": bool(box.get("flip_z", False)),
        "pixel_size": list(pixel_size) if pixel_size else None,
        "source": source,
        "confidence": "measured",
    }
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def calibrate_from_corners(index: int,
                           top_left: tuple[float, float],
                           bottom_right: tuple[float, float],
                           pixel_size: tuple[int, int],
                           flip_z: bool = False) -> dict:
    """Build a box from the reserve's map corners.

    `top_left` and `bottom_right` are the world (x, z) coordinates of the map image's
    own top-left and bottom-right pixels, as read off the in-game map cursor.
    With `flip_z`, z grows downward on the image (the identity mapping); without it,
    z grows upward and the two z values are swapped.
    """
    (tl_x, tl_z), (br_x, br_z) = top_left, bottom_right
    if tl_x > br_x:
        tl_x, br_x = br_x, tl_x
    if flip_z:
        min_z, max_z = tl_z, br_z
    else:
        min_z, max_z = tl_z, br_z
        if min_z > max_z:
            min_z, max_z = max_z, min_z
    box = {
        "min_x": tl_x,
        "max_x": br_x,
        "min_y": min(tl_z, br_z),
        "max_y": max(tl_z, br_z),
        "flip_z": flip_z,
    }
    save(index, box, pixel_size)
    return box
