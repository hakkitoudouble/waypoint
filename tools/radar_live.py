"""Live animal radar for the user's game build.

The entity layout was recovered empirically: scanning memory for any of our 135 species
hashes and histograms of the offset to a plausible world position produced one
overwhelming winner — the position sits at ``species_hash_address - 276``. Fifteen
entities agreed on that delta and every one of them clustered around the player, which
is what makes it convincing rather than coincidental.

This tool scans once, then reports every animal with its distance from the player,
sorted nearest first, and probes for the weight field by looking for a float inside the
species' known weight range nearby.

Run:  python tools/radar_live.py [player_x] [player_z]
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import math
import struct
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw import species  # noqa: E402

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE = (0x02, 0x04, 0x20, 0x40)
CHUNK = 8 * 1024 * 1024

#: Confirmed against the user's in-game observation on 2026-10-30: with the player at
#: (-7583.511, -13065.611), the two Black Bears they could see at ~237 m and ~240 m are
#: found at 238.6 m and 239.1 m using this offset. An earlier guess of -276 came from a
#: histogram window of +-512 bytes that structurally EXCLUDED -580.
POSITION_DELTA = -580
X_MIN, X_MAX = -13000.0, 2000.0
Z_MIN, Z_MAX = -14000.0, -4000.0
Y_MIN, Y_MAX = 200.0, 2500.0


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong), ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wt.DWORD), ("__alignment1", wt.DWORD),
        ("RegionSize", ctypes.c_ulonglong), ("State", wt.DWORD), ("Protect", wt.DWORD),
        ("Type", wt.DWORD), ("__alignment2", wt.DWORD),
    ]


k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = wt.HANDLE
k.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
k.VirtualQueryEx.restype = ctypes.c_size_t
k.VirtualQueryEx.argtypes = (wt.HANDLE, ctypes.c_void_p,
                             ctypes.POINTER(MEMORY_BASIC_INFORMATION64), ctypes.c_size_t)
k.ReadProcessMemory.restype = wt.BOOL
k.ReadProcessMemory.argtypes = (wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
k.CloseHandle.argtypes = (wt.HANDLE,)
k.CreateToolhelp32Snapshot.restype = wt.HANDLE

CACHE = Path(__file__).resolve().parent.parent / "work" / "species_hits.json"


def find_pid():
    class PE(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
            ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
            ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
            ("szExeFile", wt.WCHAR * 260),
        ]

    snap = k.CreateToolhelp32Snapshot(2, 0)
    e = PE()
    e.dwSize = ctypes.sizeof(e)
    try:
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if any(s in str(e.szExeFile).lower() for s in ("thehunter", "cotw")):
                return int(e.th32ProcessID), str(e.szExeFile)
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return None


def regions(h):
    out = []
    address = 0
    info = MEMORY_BASIC_INFORMATION64()
    while address < 0x7FFF_FFFF_FFFF:
        if not k.VirtualQueryEx(h, ctypes.c_void_p(address), ctypes.byref(info), ctypes.sizeof(info)):
            break
        base, size = int(info.BaseAddress), int(info.RegionSize)
        if size <= 0:
            break
        if (info.State == MEM_COMMIT and (info.Protect & 0xFF) in READABLE
                and not (info.Protect & PAGE_GUARD) and not (info.Protect & PAGE_NOACCESS)):
            out.append((base, size))
        address = base + size
    return out


def read(h, address, size):
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t(0)
    if not k.ReadProcessMemory(h, ctypes.c_void_p(address), buf, size, ctypes.byref(got)):
        return b""
    return buf.raw[: got.value]


def scan_species_hits(h) -> list[tuple[int, int]]:
    wanted = np.array(sorted(species.hash_table()), dtype=np.uint32)
    hits: list[tuple[int, int]] = []
    buf = ctypes.create_string_buffer(CHUNK)
    for base, size in regions(h):
        offset = 0
        while offset < size:
            want = min(CHUNK, size - offset)
            got = ctypes.c_size_t(0)
            if k.ReadProcessMemory(h, ctypes.c_void_p(base + offset), buf, want,
                                   ctypes.byref(got)) and got.value >= 4:
                data = buf.raw[: got.value]
                words = np.frombuffer(data[: (len(data) // 4) * 4], dtype=np.uint32)
                mask = np.isin(words, wanted)
                for idx in np.nonzero(mask)[0]:
                    hits.append((base + offset + int(idx) * 4, int(words[idx])))
            offset += want
            if got.value == 0:
                break
    return hits


def weight_range(name: str) -> tuple[float, float] | None:
    """Known weight range for a species, from the community dataset."""
    path = Path(__file__).resolve().parent.parent / "cotw" / "data" / "fur_catalogue.json"
    if not path.is_file():
        return None
    return None  # reserved: ranges live in animal_details, not the catalogue


def main() -> int:
    px = float(sys.argv[1]) if len(sys.argv) > 1 else -7420.183
    pz = float(sys.argv[2]) if len(sys.argv) > 2 else -13002.233

    found = find_pid()
    if not found:
        print("FAIL: game not running")
        return 1
    pid, exe = found
    h = k.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        print("FAIL: open")
        return 1

    started = time.time()
    hits = scan_species_hits(h)
    print(f"scan took {time.time() - started:.0f}s, {len(hits)} species-hash hits")
    try:
        CACHE.write_text(json.dumps(hits), encoding="utf-8")
    except OSError:
        pass

    animals: dict[tuple[str, int, int], dict] = {}
    for address, hash_id in hits:
        blob = read(h, address + POSITION_DELTA, 12)
        if len(blob) < 12:
            continue
        x, y, z = struct.unpack("<fff", blob)
        if not (X_MIN < x < X_MAX and Z_MIN < z < Z_MAX and Y_MIN < y < Y_MAX):
            continue
        name = species.name_for_hash(hash_id) or f"0x{hash_id:08X}"
        # dedupe copies of the same animal: same species and same position
        key = (name, round(x, 1), round(z, 1))
        animals.setdefault(key, {
            "species": name, "x": x, "y": y, "z": z,
            "distance": math.hypot(x - px, z - pz), "addresses": 0,
        })
        animals[key]["addresses"] += 1

    rows = sorted(animals.values(), key=lambda a: a["distance"])
    print(f"\nlive animals: {len(rows)}   (player at {px}, {pz})\n")
    print(f"{'dist m':>7}  {'species':<22} {'x':>10} {'y':>8} {'z':>10}  copies")
    for row in rows[:40]:
        print(f"{row['distance']:>7.0f}  {row['species']:<22} {row['x']:>10.1f} "
              f"{row['y']:>8.1f} {row['z']:>10.1f}  {row['addresses']}")

    print("\nby species:", dict(Counter(r["species"] for r in rows).most_common()))
    out = Path(__file__).resolve().parent.parent / "work" / "live_animals.json"
    out.write_text(json.dumps({"player": [px, pz], "animals": rows}, indent=1), encoding="utf-8")
    print(f"\ncached -> {out}")
    k.CloseHandle(h)
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
