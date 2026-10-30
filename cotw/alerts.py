"""Watch the population files and raise an alert when a diamond or a Great One appears.

What can be detected, and what cannot:

* The **live radar** cannot: a live entity carries neither the score nor a link to its
  population record, so the medal of an animal you are looking at is unknowable.
* The **save** can. When the game spawns new animals it rewrites the population file, so
  diffing successive snapshots reveals exactly which animals are new. A new animal whose
  trophy rating clears the diamond threshold, or whose species is the Great One
  placeholder record, is what this watcher reports.

Identity across snapshots is the `VisualVariationSeed`: the game writes `Id = 0` for every
animal, but the seed is unique in practice (2078 distinct seeds for 2079 animals in the
largest reserve), so `(reserve, species, gender, seed)` is a stable key.

The first pass over each file only records a baseline — otherwise every existing animal
would fire an alert on startup.

The snapshot also answers "what changed?" without a medal filter: every animal that
appeared **or disappeared** since the previous scan is reported, so the page can say
"3 new, 1 gone" instead of only celebrating trophies. The :data:`RECENT_SPAWNS` most
recent newcomers of each reserve are kept separately (``spawns``) — each record carrying
its ``VisualVariationSeed`` — and that shortlist is what the population list paints
green. It is a *rolling* list, not "the last scan cycle": a quiet scan changes nothing,
and a reserve that spawns ten animals keeps its five newest. It is also written to
:data:`SPAWNS_FILE` when the server enables it, so a restart does not erase it.
``data_version`` is a digest of the watched files' stats: it only changes when one of
them is rewritten, which is what lets the UI refresh the population without a page
reload. And once a day the watcher stores a small population trend in
:mod:`cotw.history` — total, diamonds, golds — which the ``/api/history`` endpoint
serves back.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import history, model, paths, population, save
from .history import history_for  # noqa: F401 - re-exported for callers that look here

#: species record the scanner reserves for Great Ones; it holds the six "Fabled" variants
GREAT_ONE_SPECIES = "???"

#: files smaller than this are empty reserve stubs
MIN_FILE_BYTES = 3000

#: how often the watcher looks for a changed save file
POLL_SECONDS = 20.0

#: keep this many alerts
MAX_ALERTS = 60

#: keep this many delta records in the internal history (the API only serves the last scan)
MAX_CHANGES = 200

#: how many of the most recent spawns stay marked, per reserve
RECENT_SPAWNS = 5

#: where those spawns are remembered between server runs (None disables persistence,
#: which is what tools and tests want: a simulated spawn must not leak into the app)
SPAWNS_FILE = paths.data_file("spawns.json")


# -- data version ---------------------------------------------------------
def population_stamps(directory: str | Path) -> list[tuple[str, float, int]]:
    """``(name, mtime, size)`` for every population file the watcher would look at.

    Sorted by name so the digest never depends on directory enumeration order, and
    every stat is guarded: a file deleted mid-walk must not abort the scan.
    """
    stamps: list[tuple[str, float, int]] = []
    for path in save.list_population_files(directory):
        try:
            stat = path.stat()
        except OSError:
            continue
        stamps.append((path.name, stat.st_mtime, stat.st_size))
    return stamps


def version_from_stamps(stamps: Iterable[tuple[str, float, int]]) -> str:
    """A short digest of the watched files' mtime and size.

    Deliberately not a hash of the content: the game rewrites these files in place and
    a stat is enough to know that the population the UI holds is stale. Empty when
    there is nothing to watch.
    """
    material = "\n".join(
        f"{name}:{mtime:.6f}:{size}" for name, mtime, size in sorted(stamps)
    )
    if not material:
        return ""
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def data_version(directory: str | Path) -> str:
    """The data version of a save folder right now."""
    return version_from_stamps(population_stamps(directory))


def _number(value: Any, digits: int) -> float | None:
    """Round a serialised number, mapping anything non-numeric to ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), digits)


class SeenPopulation(dict):
    """``key -> animal record`` for one reserve.

    The first version of the watcher stored only a ``set`` of keys, so tools and tests
    that simulate a spawn call ``seen[reserve].discard(key)``. Keeping the records must
    not break those, hence the one-method shim; iteration and ``in`` behave as the set
    did because iterating a dict yields its keys.
    """

    def discard(self, key: Any) -> None:
        """Forget one animal, as a set did."""
        self.pop(key, None)


@dataclass
class Alert:
    id: int
    reserve: int
    reserve_name: str
    species: str
    gender: str
    weight: float | None
    score: float | None
    medal: str
    fur: str | None
    fur_rarity: str | None
    seen_at: float
    reason: str

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "reserve": self.reserve,
            "reserve_name": self.reserve_name,
            "species": self.species,
            "gender": self.gender,
            "weight": round(self.weight, 2) if isinstance(self.weight, float) else None,
            "score": round(self.score, 3) if isinstance(self.score, float) else None,
            "medal": self.medal,
            "fur": self.fur,
            "fur_rarity": self.fur_rarity,
            "seen_at": self.seen_at,
            "reason": self.reason,
        }


@dataclass
class Watcher:
    """Diff the population files over time and keep a list of notable newcomers."""

    alerts: list[Alert] = field(default_factory=list)
    #: reserve -> {animal key: animal record}, so a vanished animal can still be named
    seen: dict[int, SeenPopulation] = field(default_factory=dict)
    mtimes: dict[int, float] = field(default_factory=dict)
    primed: set[int] = field(default_factory=set)
    #: bounded delta history, newest first; the API serves only `last_changes`
    changes: list[dict] = field(default_factory=list)
    last_changes: list[dict] = field(default_factory=list)
    #: reserve -> the RECENT_SPAWNS most recent newcomers, newest first. This is what the
    #: population list paints green: not "the last scan cycle" (which a single spawn
    #: would replace) but a rolling shortlist that survives quiet scans and restarts.
    recent_spawns: dict[int, list[dict]] = field(default_factory=dict)
    last_spawn_at: float = 0.0
    #: file used by load_spawns()/save_spawns(); None keeps everything in memory
    spawns_file: Path | None = None
    last_scan_at: float = 0.0
    last_poll: float = 0.0
    last_error: str | None = None
    data_version: str = ""
    _directory: Path | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _next_id: int = 1
    _thread: threading.Thread | None = None

    # -- identity ---------------------------------------------------------
    @staticmethod
    def _key(reserve: int, animal: dict) -> tuple:
        return (
            reserve,
            animal.get("species"),
            animal.get("gender"),
            animal.get("seed"),
        )

    # -- polling ----------------------------------------------------------
    def poll(self, directory: Path | None = None, force: bool = False) -> int:
        """Scan changed population files; returns how many alerts were raised."""
        if directory is None:
            found = save.find_save_dirs()
            if not found:
                self.last_error = "no save folder"
                return 0
            directory = found[0]
        directory = Path(directory)
        self._directory = directory

        # Stat every watched file once, up front: the UI polls this version even when
        # the watcher has nothing new to parse.
        self.data_version = version_from_stamps(population_stamps(directory)) or self.data_version

        raised = 0
        cycle_changes: list[dict] = []
        scanned_at = time.time()

        for path in save.list_population_files(directory):
            try:
                if path.stat().st_size < MIN_FILE_BYTES:
                    continue
                mtime = path.stat().st_mtime
            except OSError:
                continue
            reserve = save.reserve_index(path)
            if not force and self.mtimes.get(reserve) == mtime:
                continue

            try:
                contract = population.scan_population(path).as_contract()
            except Exception as exc:  # noqa: BLE001 - a half-written save must not crash us
                self.last_error = f"{path.name}: {exc}"
                continue

            animals = contract.get("animals", [])
            name = contract.get("reserve", {}).get("name") or f"Reserve {reserve}"
            current = SeenPopulation(
                (self._key(reserve, animal), animal) for animal in animals
            )
            previous = self.seen.get(reserve)
            self.seen[reserve] = current
            self.mtimes[reserve] = mtime

            # The daily trend is recorded even on the very first scan: today's point is
            # the seed tomorrow's comparison needs.
            self._record_history(reserve, animals)

            if reserve not in self.primed:
                # first sight of this file: baseline only
                self.primed.add(reserve)
                continue

            if previous is None:
                continue

            appeared = [a for a in animals if self._key(reserve, a) not in previous]
            disappeared = [a for key, a in previous.items() if key not in current]

            for animal in appeared:
                cycle_changes.append(self._change(reserve, name, animal, "appeared"))
                alert = self._qualify(reserve, name, animal)
                if alert is not None:
                    with self._lock:
                        self.alerts.insert(0, alert)
                        del self.alerts[MAX_ALERTS:]
                    raised += 1
            for animal in disappeared:
                cycle_changes.append(self._change(reserve, name, animal, "disappeared"))

        # One delta per scan cycle, even when it is empty: a fresh `since` with no
        # records is how the API says "the watcher looked, and nothing moved".
        # Newest first, so the bounded history reads as a feed.
        cycle_changes.sort(key=lambda change: change["seen_at"], reverse=True)
        spawned = [change for change in cycle_changes if change["direction"] == "appeared"]
        with self._lock:
            if cycle_changes:
                self.changes[0:0] = cycle_changes
                del self.changes[MAX_CHANGES:]
            self.last_changes = cycle_changes
            self.last_scan_at = scanned_at
        # Deliberately outside the lock: _remember_spawns takes it again.
        if spawned:
            self._remember_spawns(spawned)

        self.last_poll = time.time()
        return raised

    # -- the rolling "just spawned" shortlist -----------------------------
    def _remember_spawns(self, records: list[dict]) -> None:
        """Keep the RECENT_SPAWNS most recent newcomers, per reserve.

        One entry per animal, identified by ``(species, seed)`` like the delta itself.
        A reserve that spawns ten animals in one scan keeps the five newest; a quiet
        scan changes nothing, which is what makes the marking stable. This replaces the
        old "last scan cycle" rule, which a single new spawn used to wipe.
        """
        with self._lock:
            for record in records:
                reserve = int(record.get("reserve") or 0)
                bucket = [
                    kept for kept in self.recent_spawns.get(reserve, [])
                    if (kept.get("species"), kept.get("seed"))
                    != (record.get("species"), record.get("seed"))
                ]
                bucket.append(dict(record))
                bucket.sort(key=lambda kept: kept.get("seen_at") or 0, reverse=True)
                self.recent_spawns[reserve] = bucket[:RECENT_SPAWNS]
            newest = max((record.get("seen_at") or 0) for record in records)
            self.last_spawn_at = max(self.last_spawn_at, newest)
            self._save_spawns_locked()

    def load_spawns(self) -> int:
        """Restore the shortlist from :attr:`spawns_file`; returns how many loaded."""
        if self.spawns_file is None:
            return 0
        try:
            payload = json.loads(self.spawns_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        with self._lock:
            self.recent_spawns = {
                int(reserve): [dict(record) for record in records][:RECENT_SPAWNS]
                for reserve, records in (payload.get("reserves") or {}).items()
            }
            self.last_spawn_at = max(
                (kept.get("seen_at") or 0
                 for records in self.recent_spawns.values() for kept in records),
                default=0.0,
            )
        return sum(len(records) for records in self.recent_spawns.values())

    def _save_spawns_locked(self) -> None:
        """Write the shortlist. The caller holds the lock."""
        if self.spawns_file is None:
            return
        try:
            self.spawns_file.parent.mkdir(parents=True, exist_ok=True)
            self.spawns_file.write_text(
                json.dumps({
                    "saved": time.time(),
                    "reserves": {str(k): v for k, v in self.recent_spawns.items()},
                }, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass  # a read-only install must not break the watcher

    @staticmethod
    def _record_history(reserve: int, animals: list[dict]) -> None:
        """Store this UTC day's total / diamond / gold counts for the reserve."""
        history.record(
            reserve,
            total=len(animals),
            diamonds=sum(
                1 for a in animals if a.get("medal") == model.Medal.DIAMOND.value
            ),
            golds=sum(1 for a in animals if a.get("medal") == model.Medal.GOLD.value),
        )

    def _change(
        self, reserve: int, reserve_name: str, animal: dict, direction: str
    ) -> dict:
        """One delta record: the animal fields the changes feed exposes.

        ``seed`` is the animal's identity across scans (``Id`` is always 0), so the UI
        can match a delta record back to the row it drew in the population list.
        """
        return {
            "reserve": reserve,
            "reserve_name": reserve_name,
            "species": animal.get("species") or "?",
            "gender": animal.get("gender") or "unknown",
            "weight": _number(animal.get("weight"), 2),
            "score": _number(animal.get("score"), 3),
            "medal": animal.get("medal") or "none",
            "fur": animal.get("fur"),
            "fur_rarity": animal.get("fur_rarity"),
            "seed": animal.get("seed"),
            "seen_at": time.time(),
            "direction": direction,
        }

    def _qualify(self, reserve: int, reserve_name: str, animal: dict) -> Alert | None:
        medal = animal.get("medal") or "none"
        species_name = animal.get("species") or "?"
        is_great = species_name == GREAT_ONE_SPECIES
        fur_name = animal.get("fur")
        if not is_great and fur_name:
            lowered = str(fur_name).lower()
            is_great = "fabled" in lowered or lowered.startswith("great one")

        reason = None
        if is_great:
            reason = "great_one"
        elif medal == model.Medal.DIAMOND.value:
            reason = "diamond"
        if reason is None:
            return None

        with self._lock:
            identifier = self._next_id
            self._next_id += 1
        return Alert(
            id=identifier,
            reserve=reserve,
            reserve_name=reserve_name,
            species=species_name,
            gender=animal.get("gender") or "unknown",
            weight=animal.get("weight"),
            score=animal.get("score"),
            medal="great_one" if reason == "great_one" else medal,
            fur=fur_name,
            fur_rarity=animal.get("fur_rarity"),
            seen_at=time.time(),
            reason=reason,
        )

    # -- data version -----------------------------------------------------
    def _refresh_version(self) -> str:
        """Recompute the version from disk when the watched folder is known.

        Cheap (one stat per file) and independent of the scan cadence, so a UI polling
        this endpoint learns about a rewritten save even if the next scan is 20 s away.
        The folder is resolved here too: the very first ``/api/alerts`` can then carry
        a version even though the watcher thread has not finished its first scan.
        """
        directory = self._directory
        if directory is None:
            found = save.find_save_dirs()
            if found:
                directory = found[0]
                self._directory = directory
        if directory is not None:
            fresh = data_version(directory)
            if fresh:
                self.data_version = fresh
        return self.data_version

    # -- background thread ------------------------------------------------
    def start(self, seconds: float = POLL_SECONDS) -> None:
        if self._thread and self._thread.is_alive():
            return

        def loop() -> None:
            # prime immediately, then watch
            while True:
                try:
                    self.poll()
                except Exception as exc:  # noqa: BLE001 - never let the thread die
                    self.last_error = str(exc)
                time.sleep(seconds)

        self._thread = threading.Thread(target=loop, daemon=True, name="cotw-alerts")
        self._thread.start()

    def snapshot(self) -> dict:
        version = self._refresh_version()
        with self._lock:
            rows = [alert.as_dict() for alert in self.alerts]
            changes = [dict(change) for change in self.last_changes]
            spawns = [
                dict(record)
                for records in self.recent_spawns.values()
                for record in records
            ]
            spawn_at = self.last_spawn_at
            since = self.last_scan_at
        spawns.sort(key=lambda record: record.get("seen_at") or 0, reverse=True)
        return {
            "alerts": rows,
            "count": len(rows),
            "reserves_watched": len(self.primed),
            "last_poll": self.last_poll,
            "poll_seconds": POLL_SECONDS,
            "error": self.last_error,
            "spawns": {
                "at": spawn_at,
                "count": len(spawns),
                "animals": spawns,
                "per_reserve": RECENT_SPAWNS,
            },
            "rule": {
                "diamond": "a newly spawned animal whose trophy rating clears the "
                           "diamond threshold for its species",
                "great_one": "a newly spawned animal of the placeholder species "
                             f"'{GREAT_ONE_SPECIES}', or carrying a fabled fur",
                "caveat": "only new spawns are reported — the medal of a live animal "
                          "cannot be read from memory",
            },
            "data_version": version,
            "changes": {
                "appeared": [
                    c for c in changes if c.get("direction") == "appeared"
                ],
                "disappeared": [
                    c for c in changes if c.get("direction") == "disappeared"
                ],
                "since": since,
            },
        }
