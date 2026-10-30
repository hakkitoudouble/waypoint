"""Where the player is, and what time it is, from the save file.

Reading the live player position out of process memory turned out to be unreliable (its X
is findable but its Z is not stored as a float32 matching the display), so both facts come
from ``playerinformation_adf``, which the game rewrites every few seconds:

* ``LastPlayerPositions`` — the last saved position per reserve;
* ``TimeOfDay`` — the in-game clock, in decimal hours.

Verified against a real observation: reserve 9 gave (-7570.47, 1906.43, -13071.14) while
the player read (-7583.5, -13065.6) off their in-game map — 13 m apart, i.e. the position
as of the game's last save. The altitude also matches the entity altitudes (1900-2020 on
Silver Ridge Peaks), which confirms both sit in the same coordinate frame.

The file is parsed at most once per modification, so polling it at 1.4 Hz costs nothing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from . import adf, save

#: reserve key used when nothing else is known
DEFAULT_RESERVE = 9


@dataclass(frozen=True)
class PlayerPosition:
    reserve: int
    x: float
    y: float
    z: float

    def as_dict(self) -> dict:
        return {"reserve": self.reserve, "x": self.x, "y": self.y, "z": self.z}


@dataclass(frozen=True)
class GameClock:
    hour: float
    weather_time: float | None = None

    def as_dict(self) -> dict:
        total = self.hour % 24.0
        return {
            "hour": round(total, 4),
            "hhmm": f"{int(total):02d}:{int((total - int(total)) * 60):02d}",
        }


@dataclass
class _Snapshot:
    mtime: float
    positions: dict[int, PlayerPosition]
    clock: GameClock | None


_cache: dict[str, _Snapshot] = {}


def _save_dir(directory: Path | None = None) -> Path | None:
    if directory is not None:
        return directory
    found = save.find_save_dirs()
    return found[0] if found else None


def _snapshot(directory: Path | None = None) -> _Snapshot | None:
    base = _save_dir(directory)
    if base is None:
        return None
    path = base / "playerinformation_adf"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None

    key = str(path)
    cached = _cache.get(key)
    if cached is not None and cached.mtime == mtime:
        return cached

    root = adf.parse_document(save.read_container(path).payload).parse_entry(0)

    positions: dict[int, PlayerPosition] = {}
    memory = root.get("LastPlayerPositions_Memory") or {}
    for entry in memory.get("ChainMemory") or []:
        if not isinstance(entry, dict):
            continue
        key_value = entry.get("Key")
        value = entry.get("Value")
        if not isinstance(key_value, int) or not isinstance(value, dict):
            continue
        try:
            positions[key_value] = PlayerPosition(
                reserve=key_value,
                x=float(value["X"]),
                y=float(value["Y"]),
                z=float(value["Z"]),
            )
        except (KeyError, TypeError, ValueError):
            continue

    clock: GameClock | None = None
    tod = root.get("TimeOfDay")
    if isinstance(tod, (int, float)):
        weather = root.get("WeatherTime")
        clock = GameClock(hour=float(tod),
                          weather_time=float(weather) if isinstance(weather, (int, float)) else None)

    snapshot = _Snapshot(mtime=mtime, positions=positions, clock=clock)
    _cache[key] = snapshot
    return snapshot


def last_positions(directory: Path | None = None) -> dict[int, PlayerPosition]:
    """Last known player position for every reserve the player has visited."""
    snapshot = _snapshot(directory)
    return dict(snapshot.positions) if snapshot else {}


def position_for(reserve: int | None = None,
                 directory: Path | None = None) -> PlayerPosition | None:
    """Last saved position for a reserve."""
    table = last_positions(directory)
    if not table:
        return None
    if reserve is not None and int(reserve) in table:
        return table[int(reserve)]
    if reserve is not None:
        return None
    return table.get(DEFAULT_RESERVE) or table[sorted(table)[0]]


def game_clock(directory: Path | None = None) -> GameClock | None:
    """The in-game time of day, in decimal hours."""
    snapshot = _snapshot(directory)
    return snapshot.clock if snapshot else None


def modified_at(directory: Path | None = None) -> float:
    """Unix mtime of the player information file, i.e. how fresh it is."""
    snapshot = _snapshot(directory)
    return snapshot.mtime if snapshot else 0.0


def age_seconds(directory: Path | None = None) -> float:
    stamp = modified_at(directory)
    return round(time.time() - stamp, 1) if stamp else 0.0
