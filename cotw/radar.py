"""Live animal radar: two-tier refresh.

Scanning all 7.4 GiB of the process takes ~160 s, which is useless for a tracker. But
entity positions live at a fixed place inside each entity record and update in place:
re-reading 20 of them costs 0.1 ms. So the radar works in two tiers.

* ``discover()`` — one full memory scan for our species hashes, giving the address of
  every live entity. Slow, run in the background and cached to disk.
* ``refresh()`` — re-read each known entity's position. Sub-millisecond, safe at 10 Hz.

Entities that spawn or despawn are only picked up by a new ``discover()``, so the
caller should re-discover periodically.

The offset is verified: with the player at (-7583.511, -13065.611) the two Black Bears
they could see at ~237 m and ~240 m came out at 238.6 m and 239.1 m.
"""

from __future__ import annotations

import ctypes
import bisect
import ctypes.wintypes as wt
import json
import math
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import paths, species

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE = (0x02, 0x04, 0x20, 0x40)
CHUNK = 8 * 1024 * 1024

#: position sits this far BEFORE the species hash inside an entity record
POSITION_DELTA = -580

#: sanity bounds for a live position. Tight enough to reject the denormal/zero triples
#: that made 19 of 77 cached entities false positives, loose enough for every reserve
#: measured so far (altitudes 1000-2100 m, horizontal extent well under 15 km).
MIN_ALTITUDE = 200.0
MAX_ALTITUDE = 3000.0
MIN_HORIZONTAL = 300.0
MAX_HORIZONTAL = 30000.0

#: the game allocates its entity records in pools of exactly this size (measured: 83-84
#: regions of 16 MiB, 1.3 GiB against 8 GiB of readable address space). Used as the sweep
#: hint when no address is known yet, e.g. on a cold start or after a reserve change.
POOL_SIZE = 16 * 1024 * 1024

#: The game only simulates animals close to the player; beyond this the records stay in
#: memory with a frozen position, so a "live" tracker that shows them is lying — they look
#: tracked but never move. Keep only what is actually being simulated.
LIVE_RADIUS = 500.0

CACHE_DIR = paths.data_dir()
CACHE_FILE = CACHE_DIR / "radar_entities.json"

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.ReadProcessMemory.restype = wt.BOOL
kernel32.ReadProcessMemory.argtypes = (wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
kernel32.CloseHandle.argtypes = (wt.HANDLE,)


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong), ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wt.DWORD), ("__alignment1", wt.DWORD),
        ("RegionSize", ctypes.c_ulonglong), ("State", wt.DWORD), ("Protect", wt.DWORD),
        ("Type", wt.DWORD), ("__alignment2", wt.DWORD),
    ]


@dataclass
class LiveAnimal:
    species: str
    x: float
    y: float
    z: float
    hash_address: int
    distance: float = 0.0
    hash_id: int = 0
    fur: str | None = None
    fur_rarity: str | None = None

    def as_dict(self) -> dict:
        return {
            "species": self.species,
            "x": round(self.x, 1),
            "y": round(self.y, 1),
            "z": round(self.z, 1),
            "distance": round(self.distance, 1),
            "hash_id": f"{self.hash_id:08X}",
            "fur": self.fur,
            "fur_rarity": self.fur_rarity,
        }


@dataclass
class Radar:
    """Two-tier live tracker for the running game."""

    pid: int | None = None
    entity_addresses: dict[int, str] = field(default_factory=dict)
    last_discovery: float = 0.0
    last_error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _discovering: bool = False
    _cached_handle: int | None = None
    _auto: threading.Thread | None = None
    _sweep_index: int = 0

    # -- process ---------------------------------------------------------
    @staticmethod
    def find_process() -> tuple[int, str] | None:
        TH32CS_SNAPPROCESS = 0x00000002

        class PE(ctypes.Structure):
            _fields_ = [
                ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260),
            ]

        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap:
            return None
        entry = PE()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                name = str(entry.szExeFile)
                if any(s in name.lower() for s in ("thehunter", "cotw")):
                    return int(entry.th32ProcessID), name
                ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snap)
        return None

    def _handle(self) -> int | None:
        # Opening the process costs ~6 ms, which dominates a refresh. Keep the handle
        # and only reopen when a read fails (game restarted, process exited).
        if self._cached_handle:
            return self._cached_handle
        found = self.find_process()
        if not found:
            self.last_error = "game not running"
            return None
        pid, _ = found
        self.pid = pid
        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not handle:
            self.last_error = f"OpenProcess denied ({ctypes.get_last_error()})"
            return None
        self._cached_handle = handle
        self.last_error = None
        return handle

    def close(self) -> None:
        if self._cached_handle:
            kernel32.CloseHandle(self._cached_handle)
            self._cached_handle = None

    def _open(self) -> int | None:
        """A handle owned by the caller, who must close it.

        `_handle()` returns the cached handle used by the millisecond refreshes. Code that
        closes its handle must therefore open its own: the scan methods used to close the
        cached one, after which every refresh silently read nothing.
        """
        found = self.find_process()
        if not found:
            self.last_error = "game not running"
            return None
        pid, _ = found
        self.pid = pid
        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not handle:
            self.last_error = f"OpenProcess denied ({ctypes.get_last_error()})"
            return None
        return handle

    @staticmethod
    def _read(handle: int, address: int, size: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        if not kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buf, size,
                                          ctypes.byref(got)):
            return b""
        return buf.raw[: got.value]

    @staticmethod
    def _regions(handle: int) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        address = 0
        info = MEMORY_BASIC_INFORMATION64()
        while address < 0x7FFF_FFFF_FFFF:
            written = kernel32.VirtualQueryEx(handle, ctypes.c_void_p(address),
                                              ctypes.byref(info), ctypes.sizeof(info))
            if not written:
                break
            base, size = int(info.BaseAddress), int(info.RegionSize)
            if size <= 0:
                break
            if (info.State == MEM_COMMIT and (info.Protect & 0xFF) in READABLE
                    and not (info.Protect & PAGE_GUARD)
                    and not (info.Protect & PAGE_NOACCESS)):
                out.append((base, size))
            address = base + size
        return out

    # -- tier 1: discovery ----------------------------------------------
    @staticmethod
    def _looks_like_entity(handle: int, address: int) -> bool:
        """Reject hash occurrences that are not animal records.

        A real record has a vtable pointer 16 bytes before the species hash, then two small
        fields, and either zeros or plain floats just after it. A phantom — one that reads
        a plausible position but has no animal in the game — instead shows a neighbouring
        table of ``pointer, 0x2A8`` pairs and ASCII fragments such as ``@ins/Get``.

        Measured on a live session: the rule keeps 45 of 58 hits, keeps both bears the
        player could see, and drops the Bighorn Sheep reported at 25 m that did not exist.

        It is a heuristic, and it is not free: it also drops every Desert Bighorn Sheep
        hit, so a species whose records carry extra fields could be under-reported. That is
        the price of not showing phantom animals, which is worse — a fake animal at 20 m
        wastes a hunt.
        """
        before = Radar._read(handle, address - 16, 16)
        after = Radar._read(handle, address + 4, 12)
        if len(before) < 16 or len(after) < 12:
            return False
        if sum(32 <= byte < 127 for byte in before) > 6:
            return False
        if any(word == 0x2A8 for word in struct.unpack("<3I", after)):
            return False
        return True

    def _scan(self, handle: int, regions: list[tuple[int, int]]) -> dict[int, str]:
        """Find species hashes in the given regions and keep the ones that look live.

        Not every occurrence is an entity: the population arrays hold the same hashes in a
        different layout, and reading a position out of those yields garbage. Keep only
        hits that currently resolve to a sane world position.
        """
        table = species.hash_table()
        wanted = np.array(sorted(table), dtype=np.uint32)
        found: dict[int, str] = {}
        buffer = ctypes.create_string_buffer(CHUNK)
        for base, size in regions:
            offset = 0
            while offset < size:
                want = min(CHUNK, size - offset)
                got = ctypes.c_size_t(0)
                ok = kernel32.ReadProcessMemory(
                    handle, ctypes.c_void_p(base + offset), buffer, want,
                    ctypes.byref(got))
                if ok and got.value >= 4:
                    data = buffer.raw[: got.value]
                    words = np.frombuffer(data[: (len(data) // 4) * 4], dtype=np.uint32)
                    # searchsorted against the sorted table, not np.isin: same result,
                    # five times faster. Reading 7.9 GiB of memory takes 2 s, so the
                    # hash match was the real cost of a scan.
                    index = np.searchsorted(wanted, words)
                    np.clip(index, 0, len(wanted) - 1, out=index)
                    mask = wanted[index] == words
                    for hit in np.nonzero(mask)[0]:
                        found[base + offset + int(hit) * 4] = table[int(words[hit])]
                offset += want
                if got.value == 0:
                    break

        valid: dict[int, str] = {}
        for address, name in found.items():
            blob = self._read(handle, address + POSITION_DELTA, 12)
            if len(blob) < 12:
                continue
            x, y, z = struct.unpack("<fff", blob)
            # The same physical plausibility refresh() applies, and it matters: the game
            # keeps species hashes in other tables whose "position" is a scale or an
            # offset near the origin (y = 0, x = 2 ...). The old loose test here adopted
            # 116 of those per scan, filled the address set with junk, and — worse — made
            # the next sweep filter on their region sizes.
            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                continue
            if not (MIN_ALTITUDE < y < MAX_ALTITUDE):
                continue
            if not (MIN_HORIZONTAL <= abs(x) <= MAX_HORIZONTAL):
                continue
            if not (MIN_HORIZONTAL <= abs(z) <= MAX_HORIZONTAL):
                continue
            if not self._looks_like_entity(handle, address):
                continue
            valid[address] = name
        return valid

    def discover(self) -> int:
        """Full scan for species hashes. Slow (~160 s); returns entity count."""
        with self._lock:
            self._discovering = True
        started = time.time()
        try:
            handle = self._open()
            if not handle:
                return 0
            try:
                found = self._scan(handle, self._regions(handle))
                with self._lock:
                    self.entity_addresses = found
                    self.last_discovery = time.time()
                CACHE_DIR.mkdir(exist_ok=True)
                CACHE_FILE.write_text(json.dumps({
                    "saved": self.last_discovery,
                    "elapsed": round(time.time() - started, 1),
                    "entities": [[a, n] for a, n in found.items()],
                }), encoding="utf-8")
                self._save_cache()
                return len(found)
            finally:
                kernel32.CloseHandle(handle)
        finally:
            with self._lock:
                self._discovering = False

    def _save_cache(self) -> None:
        try:
            CACHE_DIR.mkdir(exist_ok=True)
            with self._lock:
                payload = {
                    "saved": self.last_discovery,
                    # Which game process these addresses belong to: after a restart the
                    # whole set is meaningless, and reusing it silently froze the radar.
                    "pid": self.pid,
                    "entities": [[a, n] for a, n in self.entity_addresses.items()],
                }
            CACHE_FILE.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass

    def entity_regions(self, handle: int,
                       regions: list[tuple[int, int]] | None = None) -> list[tuple[int, int]]:
        """The regions that currently hold an entity.

        New animals are almost always allocated from the same heaps as the existing ones,
        so rescanning these finds spawns without touching the other 7 GiB: 17 regions out
        of 2294, about 270 MiB instead of 7.6 GiB.
        """
        address_list = sorted(self.entity_addresses)
        if not address_list:
            return []
        pool = regions if regions is not None else self._regions(handle)
        wanted: list[tuple[int, int]] = []
        for base, size in pool:
            end = base + size
            # any entity inside this region?
            low = bisect.bisect_left(address_list, base)
            if low < len(address_list) and address_list[low] < end:
                wanted.append((base, size))
        return wanted

    def rescan_entity_regions(self) -> int:
        """Fast discovery pass over the heaps that already hold entities. Merges."""
        handle = self._open()
        if not handle:
            return 0
        try:
            regions = self.entity_regions(handle)
            if not regions:
                return 0
            found = self._scan(handle, regions)
            if not found:
                return 0
            added = 0
            with self._lock:
                for address, name in found.items():
                    if address not in self.entity_addresses:
                        self.entity_addresses[address] = name
                        added += 1
            if added:
                self._save_cache()
                self.last_discovery = time.time()
            return added
        finally:
            kernel32.CloseHandle(handle)

    def _interesting_sizes(self, regions: list[tuple[int, int]]) -> set[int]:
        """The region sizes that host entities.

        Every entity found so far sits in a region of exactly 16 MiB — the game's entity
        pools. Those 84 regions total 1.3 GiB, against 7.6 GiB for the whole address
        space, so sweeping only them is ~6x cheaper and still finds the animals the
        targeted rescan misses because they are in a pool that holds no entity yet.

        With **no address known** (cold start, or the game just changed reserve and the
        old set was dropped) the sizes cannot be derived from anything, so fall back to
        the pool size itself: that is what makes discovery recover instead of sweeping
        nothing at all.
        """
        sizes: set[int] = set()
        addresses = sorted(self.entity_addresses)
        if not addresses:
            return {POOL_SIZE}
        index = 0
        for base, size in regions:
            end = base + size
            if index < len(addresses) and addresses[index] < end:
                sizes.add(size)
                while index < len(addresses) and addresses[index] < end:
                    index += 1
        return sizes or {POOL_SIZE}

    def sweep_step(self, budget_bytes: int = 256 * 1024 * 1024) -> int:
        """One slice of a full sweep, so a whole pass costs nothing in one go.

        New animals can also appear in heaps that hold no entity yet; the targeted rescan
        misses those, so the sweep walks every region a slice at a time and finishes a
        complete pass every few minutes.
        """
        handle = self._open()
        if not handle:
            return 0
        try:
            regions = self._regions(handle)
            sizes = self._interesting_sizes(regions)
            if sizes:
                regions = [region for region in regions if region[1] in sizes]
            if self._sweep_index >= len(regions):
                self._sweep_index = 0
            taken: list[tuple[int, int]] = []
            used = 0
            while used < budget_bytes and self._sweep_index < len(regions):
                base, size = regions[self._sweep_index]
                self._sweep_index += 1
                taken.append((base, size))
                used += size
            if not taken:
                return 0
            found = self._scan(handle, taken)
            added = 0
            with self._lock:
                for address, name in found.items():
                    if address not in self.entity_addresses:
                        self.entity_addresses[address] = name
                        added += 1
            if added:
                self._save_cache()
                self.last_discovery = time.time()
            return added
        finally:
            kernel32.CloseHandle(handle)

    def start_auto(self, interval: float = 18.0) -> threading.Thread:
        """Keep the entity list current in the background.

        The live tracker used to be a one-shot: entities were discovered once, and every
        animal that spawned afterwards was invisible until a manual rescan — which the UI
        never asked for. The list could only shrink. This keeps it growing again.

        Cost: one pass over the 84 entity pools (1.3 GiB) takes about ten seconds of CPU,
        because the hash match uses searchsorted. Running it every ~30 s costs roughly a
        third of one core and keeps the whole reserve covered, so an animal that becomes
        simulated near the player shows up within half a minute instead of never.
        """
        if self._auto is not None and self._auto.is_alive():
            return self._auto

        misses = 0

        def loop() -> None:
            nonlocal misses
            while True:
                try:
                    # Every known address gone means the game changed reserve (or
                    # reloaded the save): the set is worthless, and keeping it made the
                    # sweep filter on the sizes of regions that no longer hold anything.
                    # Dropping it is what lets _interesting_sizes fall back to the pools.
                    if self.entity_addresses and not self.refresh(None):
                        misses += 1
                        if misses >= 2:
                            with self._lock:
                                self.entity_addresses = {}
                            misses = 0
                            self.last_error = None
                    else:
                        misses = 0
                    # budget larger than the pool set, so a single call is a full pass
                    self.sweep_step(budget_bytes=2 * 1024 * 1024 * 1024)
                    self.rescan_entity_regions()
                except Exception as exc:  # noqa: BLE001 - never let the thread die
                    self.last_error = str(exc)
                time.sleep(interval)

        self._auto = threading.Thread(target=loop, daemon=True, name="radar-auto")
        self._auto.start()
        return self._auto

    def load_cache(self) -> int:
        if not CACHE_FILE.is_file():
            return 0
        try:
            payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        cached_pid = payload.get("pid")
        found = self.find_process()
        if cached_pid is not None and found is not None and int(cached_pid) != found[0]:
            # Another game process wrote this cache: its addresses point nowhere now.
            return 0
        with self._lock:
            self.entity_addresses = {int(a): n for a, n in payload.get("entities", [])}
            self.last_discovery = float(payload.get("saved") or 0.0)
        return len(self.entity_addresses)

    def discover_async(self) -> threading.Thread:
        thread = threading.Thread(target=self.discover, daemon=True, name="radar-discover")
        thread.start()
        return thread

    @property
    def discovering(self) -> bool:
        return self._discovering

    # -- tier 2: refresh -------------------------------------------------
    def refresh(self, player: tuple[float, float] | None = None) -> list[LiveAnimal]:
        """Re-read every known entity's position. A millisecond for ~60 entities.

        Each entity is re-validated on every refresh, not just at discovery:

        * the species hash must still be at the address — the game recycles these
          slots, and a stale address then reads whatever moved in;
        * the position must be a plausible world point. The old test accepted any
          ``|x| < 30000``, which let through denormal triples such as ``(0, 0, 0)``;
          requiring a plausible altitude and non-trivial magnitudes drops them.
        """
        with self._lock:
            addresses = dict(self.entity_addresses)
        if not addresses:
            return []
        handle = self._handle()
        if not handle:
            return []
        px, pz = player if player else (0.0, 0.0)
        out: list[LiveAnimal] = []
        table = species.hash_table()
        stale: list[int] = []

        for address, name in addresses.items():
            raw_hash = self._read(handle, address, 4)
            if len(raw_hash) < 4:
                # A failed read is transient — the region may be momentarily unavailable
                # while the game streams. Dropping the address here used to erode the
                # known set a little on every poll, so the radar slowly forgot its animals.
                continue
            hash_id = struct.unpack("<I", raw_hash)[0]
            current = table.get(hash_id)
            if current is None:
                # read succeeded and the hash is not a species: the slot really was reused
                stale.append(address)
                continue
            if not self._looks_like_entity(handle, address):
                # a phantom that passed the older position test; also drop it from the set
                stale.append(address)
                continue

            blob = self._read(handle, address + POSITION_DELTA, 12)
            if len(blob) < 12:
                continue
            x, y, z = struct.unpack("<fff", blob)
            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                continue
            if not (MIN_ALTITUDE < y < MAX_ALTITUDE):
                continue
            if abs(x) < MIN_HORIZONTAL or abs(z) < MIN_HORIZONTAL:
                continue
            if abs(x) > MAX_HORIZONTAL or abs(z) > MAX_HORIZONTAL:
                continue
            distance = math.hypot(x - px, z - pz) if player else 0.0
            out.append(LiveAnimal(
                species=current, x=x, y=y, z=z, hash_address=address,
                distance=distance, hash_id=hash_id,
            ))

        if stale:
            with self._lock:
                for address in stale:
                    self.entity_addresses.pop(address, None)

        out.sort(key=lambda a: a.distance)
        return out

    def snapshot(self, player: tuple[float, float] | None = None) -> dict:
        animals = self.refresh(player)
        total = len(animals)
        if player:
            # Anything past the simulation radius has a frozen position in memory: it is
            # not a live animal any more, only a record. Showing it as tracked is exactly
            # the "they are static / not loaded" complaint.
            animals = [a for a in animals if a.distance <= LIVE_RADIUS]
        return {
            "player": {"x": player[0], "z": player[1]} if player else None,
            "count": len(animals),
            "radius": LIVE_RADIUS,
            "known": total,
            "discovered_at": self.last_discovery,
            "discovering": self.discovering,
            "animals": [a.as_dict() for a in animals],
        }
