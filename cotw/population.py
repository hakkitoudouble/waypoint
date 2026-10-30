"""High-level scanning: population files and discovered need zones.

Two independent data sources feed the map:

* ``animal_population_<N>``  — which animals exist in a reserve, their sex, weight,
  trophy rating and fur. It carries a ``MapPosition`` field, but in every real save
  that field is ``(0, 0)``: individual animal positions are runtime-only and are
  never persisted. So population gives *what* is out there, not *where*.

* ``found_need_zones_adf``   — every need zone the player has discovered, with a
  world ``Vector3`` position in metres, the zone type (feed/drink/rest), its active
  hours, and the animal type. This is what gives *where* and *when*.

The overlay is therefore population × need zones, never a live animal tracker.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import adf, reserves, save, species
from .model import Animal, Population, WorldBounds

#: Need-zone type ids, as they appear in NeedZoneBaseData_3. The names are
#: INFERRED from the active hours (feed at dawn/dusk, drink around midday, rest
#: in between) and still need an in-game confirmation.
NEED_TYPE_NAMES = {1: "feed", 2: "drink", 3: "rest"}

#: hash -> species for need zones, produced by tools/solve_needzone_types.py.
_NEEDTYPE_FILE = Path(__file__).resolve().parent / "data" / "needzone_types.json"


def _needzone_species() -> dict[int, str]:
    """Load the constraint-solved need-zone animal type table, if present."""
    if not _NEEDTYPE_FILE.is_file():
        return {}
    try:
        raw = json.loads(_NEEDTYPE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[int, str] = {}
    for key, value in (raw.get("types") or {}).items():
        if isinstance(value, dict) and isinstance(value.get("species"), str):
            try:
                out[int(key, 16)] = value["species"]
            except ValueError:
                continue
    return out


@dataclass
class NeedZone:
    reserve_id: int
    x: float
    y: float  # altitude in metres — not a map axis
    z: float  # the second map axis
    need_type: int
    start_hour: float
    end_hour: float
    animal_type_hash: int
    animal_type: str | None = None
    zone_id: int | None = None

    @property
    def type_name(self) -> str:
        return NEED_TYPE_NAMES.get(self.need_type, f"type_{self.need_type}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "z": self.z,
            "altitude": self.y,
            "type": self.type_name,
            "need_type": self.need_type,
            "start_hour": self.start_hour,
            "end_hour": self.end_hour,
            "animal_type_hash": f"{self.animal_type_hash:08X}",
            "animal_type": self.animal_type,
        }


def _apply_relative_medals(animals: list[Animal]) -> None:
    """Fallback rarity ranking for species whose game thresholds are unknown.

    The game's medal depends on per-species trophy-rating thresholds, which are not
    present in the vendor binary (verified negative) and have to come from
    community data. Until those land, we rank each animal against the others of the
    same species *in this reserve* and derive a percentile. That is a genuinely
    useful number ("the biggest Red Deer you have here"), but it is NOT the game's
    medal, so ``medal_source`` is set to ``"relative"`` and the UI must label it.
    """
    from collections import defaultdict
    from bisect import bisect_left

    from .model import Medal
    from .species import thresholds

    known = thresholds()
    by_species: dict[str, list[tuple[float, Animal]]] = defaultdict(list)
    for animal in animals:
        if animal.species in known:
            continue  # real thresholds already decided this one
        # Rank on the trophy score only. Falling back to weight would mix two
        # different scales and let a heavy, scoreless female outrank a scored male.
        metric = animal.score or 0.0
        if metric > 0:
            by_species[animal.species].append((metric, animal))

    for species_name, rows in by_species.items():
        if len(rows) < 5:
            continue  # too few to rank meaningfully
        values = sorted(v for v, _ in rows)
        span = max(1, len(values) - 1)
        for value, animal in rows:
            percentile = bisect_left(values, value) / span
            animal.trophy_rating = round(min(1.0, max(0.0, percentile)), 4)
            if percentile >= 0.98:
                animal.medal = Medal.DIAMOND
            elif percentile >= 0.90:
                animal.medal = Medal.GOLD
            elif percentile >= 0.70:
                animal.medal = Medal.SILVER
            else:
                animal.medal = Medal.BRONZE
            animal.medal_source = "relative"


def scan_population(path: str | Path, *, want_positions: bool = True) -> Population:
    """Read one ``animal_population_<N>`` file into the domain model."""
    path = Path(path)
    container = save.read_container(path)
    doc = adf.parse_document(container.payload)
    root = doc.parse_entry(0)

    index = save.reserve_index(path)
    meta = reserves.lookup(index)

    animals: list[Animal] = []
    sequence = 0
    for population in root.get("Populations", []) or []:
        species_hash = population.get("NameHashId")
        for group_index, group in enumerate(population.get("Groups", []) or []):
            spawn_area = group.get("SpawnAreadId")
            for raw in group.get("Animals", []) or []:
                position = raw.get("MapPosition") or {}
                x = position.get("X")
                y = position.get("Y")
                # The game writes Id = 0 for every animal, so synthesise a stable
                # key: the UI needs one and "0000000000000000" repeated 4004 times
                # would collide in every list/map keyed by id.
                identifier = raw.get("Id")
                if not identifier:
                    identifier = f"a{sequence:05d}"
                sequence += 1
                animals.append(
                    species.build_animal(
                        {
                            "species_hash": species_hash,
                            "id": identifier,
                            "gender": raw.get("Gender"),
                            "weight": raw.get("Weight"),
                            "score": raw.get("Score"),
                            "is_scripted": raw.get("IsScripted"),
                            "seed": raw.get("VisualVariationSeed"),
                            "x": x if want_positions else None,
                            "y": y if want_positions else None,
                        },
                        group_index=group_index,
                        spawn_area=spawn_area,
                    )
                )

    _apply_relative_medals(animals)
    world = reserve_world(path.parent, index,
                          scan_need_zones(path.parent).get(index, []))
    return Population(
        reserve_index=index,
        reserve_name=meta.display_name or f"Reserve {index}",
        map_image=_map_asset(meta.map_image),
        world=world,
        animals=animals,
        source_file=path.name,
        generated_at=datetime.now(timezone.utc),
    )


def _map_asset(map_name: str | None) -> str:
    """Map a reserve's PNG name to the asset path the web UI serves."""
    if not map_name:
        return "assets/maps/map.png"
    return f"assets/maps/{map_name}"


def scan_need_zones(save_dir: str | Path) -> dict[int, list[NeedZone]]:
    """All discovered need zones, grouped by reserve id."""
    path = Path(save_dir) / "found_need_zones_adf"
    if not path.is_file():
        return {}
    doc = adf.parse_document(save.read_container(path).payload)
    root = doc.parse_entry(0)
    names = _needzone_species()

    out: dict[int, list[NeedZone]] = {}
    for bucket in root.get("NZData", []) or []:
        reserve_id = bucket.get("ReserveId")
        zones: list[NeedZone] = []
        for raw in bucket.get("NeedZoneData", []) or []:
            position = raw.get("Position") or {}
            x = position.get("X")
            y = position.get("Y")
            z = position.get("Z")
            if not all(isinstance(v, (int, float)) for v in (x, y, z)):
                continue
            zones.append(
                NeedZone(
                    reserve_id=int(reserve_id) if isinstance(reserve_id, int) else -1,
                    x=float(x),
                    y=float(y),
                    z=float(z),
                    need_type=int(raw.get("NeedType") or 0),
                    start_hour=float(raw.get("NeedZoneStartTimeHours") or 0.0),
                    end_hour=float(raw.get("NeedZoneEndTimeHours") or 0.0),
                    animal_type_hash=int(raw.get("AnimalTypeLocalizationName") or 0),
                    animal_type=names.get(int(raw.get("AnimalTypeLocalizationName") or 0)),
                    zone_id=raw.get("NeedZoneId"),
                )
            )
        if zones:
            out[int(reserve_id) if isinstance(reserve_id, int) else -1] = zones
    return out


def zone_world_bounds(zones: Iterable[NeedZone], pad: float = 400.0) -> WorldBounds:
    """Plain bounding box of the zones, with a fixed metre pad.

    Kept as a diagnostic only — use :func:`fitted_world` for plotting.
    """
    xs = [z.x for z in zones]
    zs = [z.z for z in zones]
    if not xs:
        return reserves.default_world()
    return WorldBounds(
        min_x=min(xs) - pad, max_x=max(xs) + pad,
        min_y=min(zs) - pad, max_y=max(zs) + pad,
    )


def fitted_world(
    zones: Iterable[NeedZone],
    pixel_size: tuple[int, int] | None = None,
    pad: float = 0.06,
    min_span: float = 6000.0,
) -> WorldBounds:
    """Per-reserve plotting box, fitted to where the player's zones actually are.

    Reserves are NOT centred on the world origin: measured zone centroids sit at
    (-7076, +10639) for Hirschfelden, (+7704, -8700) for Vurhonga, (+8229, +5427)
    for New England, and so on across all four quadrants. A single centred box
    therefore squeezes every reserve's zones into one corner of its own map.

    So the box is fitted per reserve: the zones' own extent plus a small margin,
    then widened on one axis so it matches the map image's aspect ratio — otherwise
    the markers would be stretched relative to the terrain.

    ``min_span`` stops a reserve with only a handful of zones (Vurhonga has four,
    spanning 1.7 km) from producing a tiny box that zooms the map in absurdly.
    """
    items = list(zones)
    xs = [z.x for z in items]
    zs = [z.z for z in items]
    if not xs:
        return reserves.default_world()

    x_min, x_max = min(xs), max(xs)
    z_min, z_max = min(zs), max(zs)
    span = max(x_max - x_min, z_max - z_min, 1.0)
    margin = span * pad
    x_min -= margin
    x_max += margin
    z_min -= margin
    z_max += margin

    # enforce a floor so sparse reserves still show recognisable terrain
    cur_span = max(x_max - x_min, z_max - z_min)
    if cur_span < min_span:
        grow = (min_span - cur_span) / 2.0
        x_min -= grow
        x_max += grow
        z_min -= grow
        z_max += grow

    if pixel_size:
        width, height = pixel_size
        if width > 0 and height > 0:
            target = width / height
            cur_w = x_max - x_min
            cur_h = z_max - z_min
            if cur_w / cur_h < target:
                extra = (cur_h * target - cur_w) / 2.0
                x_min -= extra
                x_max += extra
            else:
                extra = (cur_w / target - cur_h) / 2.0
                z_min -= extra
                z_max += extra

    return WorldBounds(x_min, x_max, z_min, z_max)


def reserve_world(save_dir: str | Path, index: int,
                  zones: Iterable[NeedZone] | None = None) -> WorldBounds:
    """The plotting box for one reserve.

    A measured georeference wins when one is stored (`cotw/data/map_geo.json`);
    otherwise fall back to the zone-fitted box, which is only a plausible-looking
    guess — it is built from the zones themselves, so it cannot be correct in
    absolute terms.
    """
    from . import mapgeo

    measured = mapgeo.for_reserve(index)
    if measured is not None:
        return WorldBounds(**{k: measured[k] for k in ("min_x", "max_x", "min_y", "max_y")})

    if zones is None:
        zones = scan_need_zones(save_dir).get(index, [])
    meta = reserves.lookup(index)
    return fitted_world(zones, meta.pixel_size)
