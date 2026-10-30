"""Daily population history: one point per reserve per UTC day.

The save only ever shows the present, so a trend has to be built by watching. The
watcher in :mod:`cotw.alerts` records ``total``, ``diamonds`` and ``golds`` the first
time it scans a reserve on a given UTC day, and refreshes that day's point when a later
scan sees a changed population — one point per calendar day, never two.

The store is a small JSON document under ``work/``, capped at :data:`MAX_DAYS` points
per reserve so it stays small forever. Two promises matter to every caller, including
the HTTP handler that serves it:

* a missing, corrupt or unreadable history file is normal — :func:`history_for`
  returns an empty list instead of raising;
* writing never raises. History is a nicety, and a read-only or locked ``work``
  folder must not be able to take the watcher thread down.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import paths

#: Where the trend lives: alongside the other state the app derives from the save.
HISTORY_PATH = paths.data_file("population_history.json")

#: Roughly half a year of points per reserve; older days are pruned on write.
MAX_DAYS = 180

#: Serialise writers inside this process so two scans cannot interleave a
#: read-modify-write of the same file.
_LOCK = threading.Lock()


def _as_count(value: Any) -> int:
    """Coerce a stored counter, treating anything unusable as zero."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _clean_point(raw: dict) -> dict[str, Any]:
    """Normalise one stored point to the public shape."""
    return {
        "date": str(raw.get("date") or ""),
        "total": _as_count(raw.get("total")),
        "diamonds": _as_count(raw.get("diamonds")),
        "golds": _as_count(raw.get("golds")),
    }


def _load(path: Path) -> dict[int, list[dict[str, Any]]]:
    """Read the store, tolerating every kind of damage. Missing file -> empty store."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    # Accept both the wrapped document we write and a bare {reserve: points} map.
    source = raw.get("reserves")
    if not isinstance(source, dict):
        source = raw

    store: dict[int, list[dict[str, Any]]] = {}
    for key, value in source.items():
        try:
            reserve = int(key)
        except (TypeError, ValueError):
            continue  # "version", "updated", or some future metadata key
        if not isinstance(value, list):
            continue
        store[reserve] = [
            _clean_point(point) for point in value if isinstance(point, dict)
        ]
    return store


def _write(path: Path, store: dict[int, list[dict[str, Any]]]) -> None:
    """Replace the store atomically so a crash never leaves half a JSON document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated": time.time(),
        "reserves": {str(reserve): points for reserve, points in sorted(store.items())},
    }
    handle, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=".population_history.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=1)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def history_for(reserve: int, path: str | Path | None = None) -> list[dict[str, Any]]:
    """Sorted daily points for one reserve, oldest first.

    Returns ``[]`` when the file does not exist, cannot be read, or simply has no
    entry for this reserve: "no history yet" is a normal state, not an error.
    """
    target = Path(path) if path is not None else HISTORY_PATH
    try:
        points = _load(target).get(int(reserve), [])
    except Exception:  # noqa: BLE001 - the endpoint must never 500 over history
        return []
    return sorted(
        (dict(point) for point in points if point.get("date")),
        key=lambda point: point["date"],
    )


def record(
    reserve: int,
    total: int,
    diamonds: int = 0,
    golds: int = 0,
    *,
    path: str | Path | None = None,
    day: str | None = None,
) -> dict[str, Any] | None:
    """Write (or refresh) this UTC day's point for one reserve.

    ``day`` is ``YYYY-MM-DD`` and defaults to today in UTC. Passing it explicitly is
    what makes back-fills and the pruning test possible. Returns the point written,
    or ``None`` if the store could not be updated — a failure the caller should be
    free to ignore.
    """
    target = Path(path) if path is not None else HISTORY_PATH
    stamp = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    point = {
        "date": stamp,
        "total": _as_count(total),
        "diamonds": _as_count(diamonds),
        "golds": _as_count(golds),
    }
    try:
        with _LOCK:
            store = _load(target)
            points = [p for p in store.get(int(reserve), []) if p.get("date") != stamp]
            points.append(point)
            points.sort(key=lambda p: p["date"])
            store[int(reserve)] = points[-MAX_DAYS:]
            _write(target, store)
        return dict(point)
    except Exception:  # noqa: BLE001 - history must never break a scan
        return None
