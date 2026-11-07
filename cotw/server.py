"""Local HTTP server: serves the web UI and the population API.

Start with:  python -m cotw.server
then open http://127.0.0.1:8765

Endpoints
    GET /                     the single-page UI (web/index.html)
    GET /<static path>        files under web/
    GET /api/reserves         reserves that have a usable population file
    GET /api/population       scanned population for a reserve, UI JSON contract
                              optional query: ?reserve=<N>&file=<absolute path>
    GET /api/alerts           diamonds / Great Ones, appeared / disappeared deltas,
                              and a `data_version` that changes when a save is rewritten
    GET /api/history          daily population trend: ?reserve=<N>, defaults to reserve 9
"""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import os
import posixpath
import sys
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import paths, save, settings
from .model import Animal, Population, WorldBounds

WEB_ROOT = paths.resource_dir("web")

#: A reserve that has never been played still ships an ADF payload of exactly
#: 2110 bytes (no populations). Anything at or below this is treated as empty.
PRISTINE_MAX_BYTES = 3000

#: Fallback world box. COTW reserves are square and roughly centred on the
#: origin; this is only used until per-reserve metadata is known.
DEFAULT_WORLD = WorldBounds(min_x=-8192.0, max_x=8192.0, min_y=-8192.0, max_y=8192.0)


def _no_save_error() -> FileNotFoundError:
    """An error that says where we looked — the whole point of the message."""
    searched = [str(root) for root in save.save_roots()]
    return FileNotFoundError(
        "no COTW save folder found; looked in: " + " | ".join(searched)
    )


def _resolve_custom_save_dir(raw: str) -> tuple[Path | None, str | None]:
    """Turn whatever the user pasted into a folder that holds population files.

    Accepts the account folder itself, the Saves folder above it, the Documents folder
    above that, and the usual Explorer paste decorations: surrounding quotes,
    ``%USERPROFILE%``, a trailing backslash. When several account folders qualify, the
    most recently written one wins — the same rule as the automatic search.
    Returns ``(path, error)``.
    """
    text = (raw or "").strip().strip('"').strip("'").strip()
    if not text:
        return None, "empty path"
    try:
        expanded = os.path.expandvars(os.path.expanduser(text))
    except (OSError, RuntimeError):
        return None, "cannot read that path"
    base = Path(expanded)
    if not base.is_dir():
        return None, "that folder does not exist"

    def population_files(folder: Path) -> list[Path]:
        try:
            return save.list_population_files(folder)
        except OSError:
            return []

    # the folder itself, the two well-known layouts above it, then one level below each
    seen: list[Path] = []

    def add(folder: Path) -> None:
        try:
            if folder.is_dir() and folder not in seen:
                seen.append(folder)
        except OSError:
            pass

    add(base)
    add(base / save.SAVE_ROOT_RELATIVE)
    for folder in list(seen):
        try:
            for child in sorted(folder.iterdir()):
                add(child)
        except OSError:
            continue
    hits = [folder for folder in seen if population_files(folder)]
    if not hits:
        return None, "no animal_population_* file in that folder (or in the folders inside it)"
    return save.best_save_dir(hits) or hits[0], None


def _scan(path: Path) -> Population:
    """Parse one population file into the domain model."""
    from . import population as pop_module

    return pop_module.scan_population(path)


def _resolve_population_file(query: dict[str, list[str]], save_dir: Path | None) -> Path:
    """Pick the population file the UI asked for."""
    explicit = query.get("file", [None])[0]
    if explicit:
        candidate = Path(unquote(explicit))
        if not candidate.is_file():
            raise FileNotFoundError(f"no such population file: {candidate}")
        return candidate

    wanted = query.get("reserve", [None])[0]
    directory = save_dir
    if directory is None:
        directory = save.best_save_dir()
    if directory is None:
        raise _no_save_error()

    files = save.list_population_files(directory)
    if not files:
        raise FileNotFoundError(f"no animal_population_* files in {directory}")
    if wanted is not None:
        index = int(wanted)
        for path in files:
            if save.reserve_index(path) == index:
                return path
        raise FileNotFoundError(f"reserve {index} has no population file")
    return files[-1]


def _best_saved_position(radar, player_module):
    """The saved player position that best explains the live entities, or ``None``.

    The player is normally standing among the animals they are tracking, so the right
    reserve is the one whose last position minimises the median distance to the herd.
    This is how the server finds out **which reserve the game is actually running**,
    which matters because the entities in memory belong to that reserve and to nothing
    else: anchoring them on another reserve's saved position puts every animal past the
    500 m simulation radius, and the live layer then looks empty.

    Returns ``None`` when there is nothing to judge by (no save, or fewer than three
    entities), so callers can tell "we do not know" from "reserve 9".
    """
    positions = player_module.last_positions()
    if not positions:
        return None
    animals = radar.refresh(None) if radar is not None else []
    if len(animals) < 3:
        return None

    def median_distance(position) -> float:
        distances = sorted(
            math.hypot(a.x - position.x, a.z - position.z) for a in animals
        )
        return distances[len(distances) // 2]

    return min(positions.values(), key=median_distance)


def _closest_saved_position(radar, player_module):
    """Which reserve's saved player position best explains the animals we see?

    Falls back to the module default when there is nothing to compare against.
    """
    best = _best_saved_position(radar, player_module)
    if best is not None:
        return best
    return player_module.position_for(None)


class Handler(BaseHTTPRequestHandler):
    server_version = "COTWPopulation/0.1"

    save_dir: Path | None = None

    def log_message(self, fmt: str, *args) -> None:  # noqa: D102 - quieter default log
        sys.stderr.write("  %s\n" % (fmt % args))

    # -- helpers ---------------------------------------------------------
    def _send_bytes(self, body: bytes, status: int = 200, content_type: str = "application/octet-stream") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: object, status: int = 200) -> None:
        self._send_bytes(
            json.dumps(payload, indent=2).encode("utf-8"),
            status=status,
            content_type="application/json; charset=utf-8",
        )

    def _send_error_json(self, exc: Exception, status: int = 500) -> None:
        self._send_json(
            {"error": type(exc).__name__, "message": str(exc), "trace": traceback.format_exc()},
            status=status,
        )

    # -- routing ---------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        route = posixpath.normpath(unquote(parsed.path))
        query = parse_qs(parsed.query)

        try:
            if route == "/api/ping":
                # Cheap liveness probe: it tells the launcher whether Waypoint is
                # already running on the port, gives the version a name, and reports
                # which save folder the server settled on — the page shows a setup
                # panel when there is none.
                from . import __version__

                directory, source = self._effective_save_dir()
                usable = bool(directory is not None and save.list_population_files(directory))
                self._send_json({
                    "app": "waypoint",
                    "version": __version__,
                    "frozen": paths.frozen(),
                    "data_dir": str(paths.data_dir()),
                    # only reported when it really holds population files: the page shows
                    # its setup panel when this is null
                    "save_dir": str(directory) if usable else None,
                    "save_dir_source": source if usable else "none",
                    "save_dir_custom": bool(usable) and source in ("saved", "argument"),
                    "save_dir_configured": str(directory) if directory else None,
                    "searched": self._searched_roots(),
                })
                return
            if route == "/api/population":
                path = _resolve_population_file(query, self._effective_save_dir()[0])
                self._send_json(_scan(path).as_contract())
                return
            if route == "/api/needzones":
                self._send_json(self._need_zones(query))
                return
            if route == "/api/harvests":
                self._send_json(self._harvests())
                return
            if route == "/api/reserves":
                self._send_json(self._list_reserves())
                return
            if route == "/api/radar":
                self._send_json(self._radar_snapshot(query))
                return
            if route == "/api/furs":
                self._send_json(self._furs(query))
                return
            if route == "/api/pressure":
                self._send_json(self._pressure(query))
                return
            if route == "/api/compare":
                self._send_json(self._compare(query))
                return
            if route == "/api/alerts":
                self._send_json(Handler._watcher().snapshot())
                return
            if route == "/api/history":
                self._send_json(self._history(query))
                return
            self._serve_static(route)
        except FileNotFoundError as exc:
            self._send_error_json(exc, status=404)
        except ValueError as exc:
            # a bad query value (?reserve=abc) is the caller's mistake, not a crash
            self._send_error_json(exc, status=400)
        except Exception as exc:  # noqa: BLE001 - surface everything to the UI
            self._send_error_json(exc, status=500)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        route = posixpath.normpath(unquote(parsed.path))
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        if route == "/api/save-dir":
            # The interface's "where are my saves?" field. An empty path forgets the
            # custom folder and goes back to the automatic search.
            raw_path = payload.get("path")
            if raw_path in (None, ""):
                settings.update(save_dir=None)
                cls = type(self)
                cls.save_dir = None
                cls.save_dir_source = None
                directory, source = self._effective_save_dir()
                self._send_json({
                    "save_dir": str(directory) if directory else None,
                    "save_dir_source": source,
                })
                return
            resolved, error = _resolve_custom_save_dir(str(raw_path))
            if resolved is None:
                self._send_json({"error": "invalid", "message": error}, status=400)
                return
            cls = type(self)
            cls.save_dir = resolved
            cls.save_dir_source = "saved"
            settings.update(save_dir=str(resolved))
            self._send_json({
                "save_dir": str(resolved),
                "save_dir_source": "saved",
                "reserves": sum(
                    1 for path in save.list_population_files(resolved)
                    if save.read_container(path).unpacked_size > PRISTINE_MAX_BYTES
                ),
            })
            return
        if route == "/api/radar/player":
            try:
                x = float(payload["x"])
                z = float(payload["z"])
            except (KeyError, TypeError, ValueError):
                self._send_json({"error": "x and z are required numbers"}, status=400)
                return
            Handler._player = (x, z)
            self._send_json({"player": {"x": x, "z": z}})
            return
        self._send_json({"error": "Not Found", "message": route}, status=404)

    # -- radar -----------------------------------------------------------
    _radar = None
    _player: tuple[float, float] | None = None
    #: where the save folder came from: "argument" (--save-dir), "saved" (chosen in the
    #: interface once), "auto" (found automatically) or None when there is none
    save_dir_source: str | None = None

    @classmethod
    def _searched_roots(cls) -> list[str]:
        """The folders we would look in, so a failure can say where it looked."""
        if cls.save_dir is not None:
            return [str(cls.save_dir)]
        return [str(root) for root in save.save_roots()]

    @classmethod
    def _effective_save_dir(cls) -> tuple[Path | None, str]:
        """The folder holding ``animal_population_*`` files, and where it came from."""
        if cls.save_dir is not None:
            return cls.save_dir, (cls.save_dir_source or "argument")
        remembered = settings.get("save_dir")
        if remembered:
            candidate = Path(str(remembered))
            try:
                if candidate.is_dir() and save.list_population_files(candidate):
                    cls.save_dir = candidate
                    cls.save_dir_source = "saved"
                    return candidate, "saved"
            except OSError:
                pass
        best = save.best_save_dir()
        if best is None:
            return None, "none"
        return best, "auto"

    @classmethod
    def warm_radar(cls):
        """Create the radar and start its discovery, before anything asks for it.

        The first pass over the entity pools takes ~10 s, and it used to start on the
        first /api/radar call — i.e. when the page loaded, leaving a silent "0 animals"
        for the first half minute. Starting it with the server means the animals are
        usually there by the time the browser has finished loading.
        """
        from . import radar as radar_module

        if cls._radar is None:
            cls._radar = radar_module.Radar()
            cls._radar.load_cache()
            # Entities used to be discovered once and never again, so every animal that
            # spawned afterwards stayed invisible and the list could only shrink. Keep
            # discovering in the background.
            cls._radar.start_auto()
        return cls._radar

    def _radar_snapshot(self, query: dict[str, list[str]]) -> dict[str, object]:
        """Live animals. Distances come from the player's last saved position unless
        ?x=&z= override it; ?reserve=N picks which saved position to use."""
        import time as _time

        from . import player as player_module
        from . import reserves as reserve_tables

        Handler.warm_radar()

        reserve = None
        if "reserve" in query:
            reserve = int(query["reserve"][0])

        # Which reserve the live entities belong to. Independent of the one asked for:
        # the UI compares the two and warns when they differ, because a mismatch means
        # every animal is outside the simulation radius and the layer would look dead.
        best = _best_saved_position(Handler._radar, player_module)
        live_reserve = best.reserve if best is not None else None

        player = Handler._player
        source = "client"
        age = 0.0
        if "x" in query and "z" in query:
            player = (float(query["x"][0]), float(query["z"][0]))
            Handler._player = player
        else:
            if reserve is not None:
                saved = player_module.position_for(reserve)
            else:
                # No reserve asked for: anchor on the reserve the herd is in, not on a
                # hard-coded default. That is what makes the page follow the game.
                saved = best if best is not None else player_module.position_for(None)
            if saved is not None:
                player = (saved.x, saved.z)
                source = f"save:reserve{saved.reserve}"
                age = round(_time.time() - player_module.modified_at(), 1)

        if query.get("discover", ["0"])[0] in ("1", "true", "yes"):
            if not Handler._radar.discovering:
                Handler._radar.discover_async()

        snapshot = Handler._radar.snapshot(player)
        # "still looking" as opposed to "nothing around you": true while the first sweep
        # has not produced an address yet, unless the game is simply not running.
        snapshot["discovering"] = bool(Handler._radar.discovering) or (
            not Handler._radar.entity_addresses and not Handler._radar.last_error
        )
        snapshot["player_source"] = source if player else None
        snapshot["player_age_seconds"] = age if player else None
        snapshot["live_reserve"] = live_reserve
        if live_reserve is not None:
            snapshot["live_reserve_name"] = reserve_tables.lookup(live_reserve).display_name
        else:
            snapshot["live_reserve_name"] = None
        clock = player_module.game_clock()
        if clock is not None:
            info = clock.as_dict()
            info["age_seconds"] = player_module.age_seconds()
            snapshot["game_time"] = info
        else:
            snapshot["game_time"] = None
        snapshot["error"] = Handler._radar.last_error
        return snapshot

    # -- fur catalogue ---------------------------------------------------
    def _furs(self, query: dict[str, list[str]]) -> dict[str, object]:
        """Every known fur variant for the species present in a reserve.

        The save never stores a fur for a living animal — ``FeatureModifiers`` is zero
        for all 28 243 animals across the reference saves — and neither the population
        seed nor a fur hash appears in the live entity records, so a per-animal fur is
        not available. What *is* known is the vocabulary and drop probability per
        species, which is what this returns.
        """
        from . import species as species_module

        path = _resolve_population_file(query, self.save_dir)
        contract = _scan(path).as_contract()
        names = [entry.get("name") for entry in contract.get("species", []) if entry.get("name")]

        table: dict[str, object] = {}
        for name in names:
            variants = species_module.fur_variants(name)
            if variants:
                table[name] = [
                    {
                        "name": variant.get("name"),
                        "rarity": variant.get("rarity"),
                        "probability": variant.get("probability"),
                    }
                    for variant in variants
                ]
        return {
            "reserve": contract.get("reserve", {}).get("index"),
            "species_with_furs": len(table),
            "species": table,
        }

    # -- alerts -----------------------------------------------------------
    _alert_watcher = None

    @classmethod
    def _watcher(cls):
        """The population watcher, started once for the process."""
        if cls._alert_watcher is None:
            from . import alerts as alerts_module

            cls._alert_watcher = alerts_module.Watcher()
            # Keep the five most recent spawns per reserve across restarts: they are
            # what the population list paints green, and a server restart must not
            # silently erase them.
            cls._alert_watcher.spawns_file = alerts_module.SPAWNS_FILE
            cls._alert_watcher.load_spawns()
            cls._alert_watcher.start()
        return cls._alert_watcher

    # -- population history -----------------------------------------------
    def _history(self, query: dict[str, list[str]]) -> dict[str, object]:
        """The daily trend for one reserve: total animals, diamonds, golds.

        A missing history file is not an error — the app has simply not been watching
        long enough yet — so the endpoint answers with an empty list rather than a
        404/500. An unparseable ``?reserve=`` stays a 400, like every other handler.
        """
        from . import history as history_module

        reserve = int(query.get("reserve", ["9"])[0])
        return {"reserve": reserve, "points": history_module.history_for(reserve)}

    # -- hunting pressure -------------------------------------------------
    def _pressure(self, query: dict[str, list[str]]) -> dict[str, object]:
        """Non-zero hunting-pressure cells for a reserve, with world positions."""
        from . import pressure as pressure_module

        directory = self.save_dir
        if directory is None:
            found = save.find_save_dirs()
            if not found:
                return {"cells": [], "error": "no save folder found"}
            directory = found[0]
        reserve = int(query.get("reserve", ["9"])[0])
        return pressure_module.read_pressure(directory, reserve)

    # -- reserve comparison -----------------------------------------------
    _compare_cache: dict[str, object] | None = None
    _compare_stamp: float = 0.0

    def _compare(self, query: dict[str, list[str]]) -> dict[str, object]:
        """Medal counts per species per reserve, so "where should I hunt X?" is answerable."""
        import time as _time

        from . import model as model_module
        from . import reserves as reserve_tables

        directory = self.save_dir
        if directory is None:
            found = save.find_save_dirs()
            if not found:
                return {"species": {}, "error": "no save folder found"}
            directory = found[0]

        stamp = 0.0
        for path in save.list_population_files(directory):
            try:
                stamp = max(stamp, path.stat().st_mtime)
            except OSError:
                continue

        cache = Handler._compare_cache
        if cache is None or Handler._compare_stamp != stamp:
            table: dict[str, list[dict]] = {}
            for path in save.list_population_files(directory):
                index = save.reserve_index(path)
                name = reserve_tables.lookup(index).display_name or f"Reserve {index}"
                try:
                    contract = _scan(path).as_contract()
                except Exception:  # noqa: BLE001 - one bad file must not kill the endpoint
                    continue
                per_reserve: dict[str, dict[str, int]] = {}
                for animal in contract.get("animals", []):
                    species_name = animal.get("species")
                    if not species_name:
                        continue
                    bucket = per_reserve.setdefault(species_name, {})
                    medal = animal.get("medal") or "none"
                    bucket[medal] = bucket.get(medal, 0) + 1
                for species_name, medals in per_reserve.items():
                    table.setdefault(species_name, []).append({
                        "reserve": index,
                        "name": name,
                        "total": sum(medals.values()),
                        "medals": medals,
                    })
            for rows in table.values():
                rows.sort(key=lambda row: (-row["medals"].get("diamond", 0),
                                           -row["medals"].get("gold", 0),
                                           -row["total"]))
            cache = {"species": table}
            Handler._compare_cache = cache
            Handler._compare_stamp = stamp
        void = model_module  # keep the import meaningful for readers

        wanted = query.get("species", [None])[0]
        if wanted:
            rows = cache.get("species", {}).get(wanted) if isinstance(cache, dict) else None
            return {"species": wanted, "reserves": rows or []}
        return cache

    def _need_zones(self, query: dict[str, list[str]]) -> dict[str, object]:
        """Discovered need zones: the only world positions the save actually holds."""
        from . import population as pop_module
        from . import reserves as reserve_tables

        directory, source = self._effective_save_dir()
        if directory is None:
            return {"zones": [], "error": "no save folder found",
                    "searched": self._searched_roots()}

        zones = pop_module.scan_need_zones(directory)
        wanted = query.get("reserve", [None])[0]
        if wanted is not None:
            index = int(wanted)
            subset = zones.get(index, [])
            metadata = reserve_tables.lookup(index)
            plotting = pop_module.reserve_world(directory, index, subset)
            return {
                "reserve": {
                    "index": index,
                    "name": metadata.display_name,
                    "confidence": metadata.confidence,
                },
                # Fitted per reserve: reserves are not centred on the origin, so a
                # shared centred box would squeeze each reserve's zones into a corner.
                "world": plotting.as_dict(),
                "world_observed": pop_module.zone_world_bounds(subset).as_dict(),
                "zones": [z.as_dict() for z in subset],
            }
        return {
            "reserves": {
                str(index): {
                    "count": len(items),
                    "name": reserve_tables.lookup(index).display_name,
                }
                for index, items in sorted(zones.items())
            }
        }

    def _harvests(self) -> dict[str, object]:
        """Harvested animals. This is the only place the save records a fur variant:
        the population file stores FeatureModifiers = 0 for every living animal."""
        from . import harvest as harvest_module

        directory = self.save_dir
        if directory is None:
            found = save.find_save_dirs()
            if not found:
                return {"harvests": [], "error": "no save folder found"}
            directory = found[0]

        items = harvest_module.read_harvests(directory)
        return {
            "harvests": [h.as_dict() for h in items],
            "total": len(items),
            "with_fur": sum(1 for h in items if h.fur),
            "note": "furs are only recorded for harvested animals",
        }

    def _list_reserves(self) -> dict[str, object]:
        from . import reserves as reserve_tables

        directory, source = self._effective_save_dir()
        if directory is None:
            return {"reserves": [], "error": "no save folder found",
                    "save_dir": None, "save_dir_source": "none",
                    "searched": self._searched_roots()}

        entries = []
        for path in save.list_population_files(directory):
            index = save.reserve_index(path)
            try:
                container = save.read_container(path)
                size = container.unpacked_size
            except save.SaveFormatError:
                size = None
            metadata = reserve_tables.lookup(index)
            entries.append(
                {
                    "index": index,
                    "file": str(path),
                    "name": path.name,
                    "reserve": metadata.display_name,
                    "map": metadata.map_image,
                    "confidence": metadata.confidence,
                    "unpacked_size": size,
                    # a pristine reserve has no populations to show
                    "populated": size is not None and size > PRISTINE_MAX_BYTES,
                }
            )
        return {"save_dir": str(directory), "save_dir_source": source,
                "reserves": entries, "searched": self._searched_roots()}

    def _serve_static(self, route: str) -> None:
        if route in ("/", "."):
            target = WEB_ROOT / "index.html"
        else:
            relative = route.lstrip("/")
            target = (WEB_ROOT / relative).resolve()
            if not target.is_file() or WEB_ROOT.resolve() not in target.parents:
                self._send_bytes(b"not found", status=404, content_type="text/plain")
                return

        if not target.is_file():
            self._send_bytes(
                b"web UI not built yet: web/index.html is missing",
                status=404,
                content_type="text/plain; charset=utf-8",
            )
            return

        guessed, _ = mimetypes.guess_type(str(target))
        self._send_bytes(target.read_bytes(), content_type=guessed or "application/octet-stream")


def serve(port: int, save_dir: Path | None) -> None:
    Handler.save_dir = save_dir
    Handler.save_dir_source = "argument" if save_dir is not None else None
    # Start the memory scan now rather than on the first /api/radar hit: the first pass
    # over the entity pools takes ~10 s and the page would otherwise show an empty live
    # layer for half a minute after every launch.
    Handler.warm_radar()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"COTW population overlay  ->  http://127.0.0.1:{port}")
    if save_dir:
        print(f"save dir override: {save_dir}")
    print("Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=None,
        help="override the COTW save folder detected under Documents",
    )
    args = parser.parse_args(argv)
    serve(args.port, args.save_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
