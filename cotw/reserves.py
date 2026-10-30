"""Reserve metadata: save slot index -> display name, map image and world bounds.

The index in ``animal_population_<N>`` is the game's internal reserve id, and that
id space contains holes (5, 7, 15). The mapping here comes from
``cotw/data/reserves.json``, which another pass established by correlating the
harvest log with the population file the game wrote at the end of each session —
*not* from the vendor tool, whose own numbering is shifted by up to 3 from slot 5
onward and is therefore wrong for most reserves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .model import WorldBounds

DATA_FILE = Path(__file__).resolve().parent / "data" / "reserves.json"

#: Default half-extent of a reserve, in metres. COTW reserves are square grids
#: centred on the origin; pooling every need-zone position across the eight
#: visited reserves gives x in [-12136, 11465] and z in [-13192, 13184], so
#: 13200 covers the whole playable area with a small margin. This is a global
#: default, not a per-reserve fit — see notes/calibration-open.md.
DEFAULT_HALF_EXTENT = 13200.0

#: No reserve identity could be established for these slots; they are real save
#: slots but the reserve is unknown, so we must not guess a map.
UNKNOWN = None


@dataclass(frozen=True)
class Reserve:
    index: int
    display_name: str | None
    internal_name: str | None
    map_image: str | None
    icon: str | None
    dlc: str | None
    confidence: str
    pixel_size: tuple[int, int] | None
    world: WorldBounds | None

    @property
    def known(self) -> bool:
        return self.display_name is not None and self.map_image is not None


@lru_cache(maxsize=1)
def _raw() -> dict[str, dict]:
    if not DATA_FILE.is_file():
        return {}
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _world(entry: dict) -> WorldBounds | None:
    """A per-reserve extent, but only if it was actually fitted.

    The metadata carries a ROUGH 12 km guess per reserve, which is *smaller* than
    the coordinates the game really writes (need zones reach +-13200 m), so using
    it would clip markers off the map. Anything not explicitly fitted is ignored
    in favour of the measured global default.
    """
    meta = entry.get("map_meta") or {}
    extents = meta.get("world_extent_guess") or {}
    if str(extents.get("confidence", "")).upper() == "ROUGH":
        return None
    width = extents.get("width_m")
    height = extents.get("height_m")
    if not (isinstance(width, (int, float)) and isinstance(height, (int, float))):
        return None
    if not extents.get("centred_at_origin", True):
        return None
    return WorldBounds(
        min_x=-width / 2.0, max_x=width / 2.0,
        min_y=-height / 2.0, max_y=height / 2.0,
    )


def lookup(index: int) -> Reserve:
    """Metadata for a reserve slot; ``known`` is False when the slot is a hole."""
    entry = _raw().get(str(index))
    if not entry:
        return Reserve(index, None, None, None, None, None, "UNKNOWN", None, None)

    meta = entry.get("map_meta") or {}
    pixel_size = meta.get("pixel_size")
    return Reserve(
        index=index,
        display_name=entry.get("display"),
        internal_name=entry.get("internal"),
        map_image=entry.get("map"),
        icon=entry.get("icon"),
        dlc=entry.get("dlc"),
        confidence=entry.get("confidence", "UNKNOWN"),
        pixel_size=(int(pixel_size[0]), int(pixel_size[1])) if pixel_size else None,
        world=_world(entry) or default_world(),
    )


def default_world() -> WorldBounds:
    """The fallback square every reserve is plotted in until it is calibrated."""
    half = DEFAULT_HALF_EXTENT
    return WorldBounds(-half, half, -half, half)


def known_reserves() -> list[Reserve]:
    out = []
    for key in sorted(_raw(), key=lambda k: int(k)):
        reserve = lookup(int(key))
        if reserve.known:
            out.append(reserve)
    return out
