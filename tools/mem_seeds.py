"""Find the world entities by scanning for each animal's VisualVariationSeed.

The population array in memory is byte-identical to the save and its `MapPosition` is
`(0,0)`, so positions are not there. But the world entity for an animal should carry
the same seed. If we find a seed occurrence that is *not* one of the population copies
and that has a plausible `(x, altitude, z)` triple nearby, we have found the entities.

One pass over memory using numpy, so 200 seeds cost the same as one.

Run:  python tools/mem_seeds.py [reserve_index]
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw import adf, save, species  # noqa: E402

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE = (0x02, 0x04, 0x20, 0x40)
CHUNK = 8 * 1024 * 1024


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong), ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wt.DWORD), ("__alignment1", wt.DWORD),
        ("RegionSize", ctypes.c_ulonglong), ("State", wt.DWORD), ("Protect", wt.DWORD),
        ("Type", wt.DWORD), ("__alignment2", wt.DWORD),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.VirtualQueryEx.argtypes = (wt.HANDLE, ctypes.c_void_p,
                                    ctypes.POINTER(MEMORY_BASIC_INFORMATION64), ctypes.c_size_t)
kernel32.ReadProcessMemory.restype = wt.BOOL
kernel32.ReadProcessMemory.argtypes = (wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
kernel32.CloseHandle.argtypes = (wt.HANDLE,)
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE


def find_pid(substrings):
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
            ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
            ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
            ("szExeFile", wt.WCHAR * 260),
        ]

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            name = str(entry.szExeFile)
            if any(s in name.lower() for s in substrings):
                return int(entry.th32ProcessID), name
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return None


def readable_regions(handle):
    out = []
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
                and not (info.Protect & PAGE_GUARD) and not (info.Protect & PAGE_NOACCESS)):
            out.append((base, size))
        address = base + size
    return out


def plausible_position(data: bytes, base_addr: int) -> tuple[int, float, float, float] | None:
    """Look for 3 consecutive float32 that could be a world (x, altitude, z).

    The first version of this accepted almost anything: a triple of `(0, 887, 155)`
    passed because only one component had to be non-trivial, and those are spawn-area
    offsets, not coordinates. Silver Ridge Peaks spans roughly x[-10159..1047] and
    z[-13192..-5624], so require both horizontal components to be genuinely large.
    """
    n = len(data) // 4
    if n < 3:
        return None
    values = np.frombuffer(data[: n * 4], dtype="<f4")
    for i in range(0, n - 2):
        x, y, z = float(values[i]), float(values[i + 1]), float(values[i + 2])
        if not (800.0 < y < 3500.0):
            continue
        if not (abs(x) > 200.0 and abs(z) > 500.0):
            continue
        if abs(x) > 15000.0 or abs(z) > 15000.0:
            continue
        return (base_addr + i * 4, x, y, z)
    return None


def main() -> int:
    reserve = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    dirs = save.find_save_dirs()
    doc = adf.parse_document(save.read_container(dirs[0] / f"animal_population_{reserve}").payload)
    root = doc.parse_entry(0)

    seeds: dict[int, str] = {}
    for pop in root.get("Populations", []) or []:
        name = species.name_for_hash(pop.get("NameHashId")) or "?"
        for group in pop.get("Groups", []) or []:
            for animal in group.get("Animals", []) or []:
                seed = animal.get("VisualVariationSeed")
                weight = animal.get("Weight")
                if isinstance(seed, int) and seed and isinstance(weight, float):
                    seeds.setdefault(seed, f"{name} w={weight:.1f}")

    wanted = dict(list(seeds.items())[:400])
    seed_array = np.array(sorted(wanted), dtype=np.uint32)
    print(f"reserve {reserve}: {len(seeds)} distinct seeds, scanning for {len(seed_array)}")

    found = find_pid(("thehunter", "cotw"))
    if not found:
        print("FAIL: game process not running")
        return 1
    pid, exe = found
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        print("FAIL: OpenProcess denied")
        return 1

    hits: list[tuple[int, int]] = []
    buffer = ctypes.create_string_buffer(CHUNK)
    scanned = 0
    started = time.time()
    try:
        for base, size in readable_regions(handle):
            offset = 0
            while offset < size:
                want = min(CHUNK, size - offset)
                got = ctypes.c_size_t(0)
                ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(base + offset),
                                                buffer, want, ctypes.byref(got))
                if ok and got.value >= 4:
                    data = buffer.raw[: got.value]
                    scanned += len(data)
                    words = np.frombuffer(data[: (len(data) // 4) * 4], dtype=np.uint32)
                    mask = np.isin(words, seed_array)
                    for index in np.nonzero(mask)[0]:
                        hits.append((base + offset + int(index) * 4, int(words[index])))
                offset += want
                if got.value == 0:
                    break
    finally:
        pass

    elapsed = time.time() - started
    print(f"scanned {scanned / 1024 / 1024:.0f} MiB in {elapsed:.0f}s")
    print(f"seed occurrences: {len(hits)}")

    # cache the hits so the analysis can be iterated without rescanning 7 GiB
    import json

    cache = Path(__file__).resolve().parent.parent / "work" / f"mem_seed_hits_{reserve}.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"reserve": reserve, "hits": hits, "seeds": {str(k): v for k, v in wanted.items()}}),
        encoding="utf-8",
    )
    print(f"cached hits -> {cache}")

    # group hits by rough address band to see how many distinct copies exist
    bands: dict[str, int] = {}
    for address, _ in hits:
        bands[f"0x{address >> 24:X}"] = bands.get(f"0x{address >> 24:X}", 0) + 1
    print("by address band:", dict(sorted(bands.items(), key=lambda kv: -kv[1])[:8]))

    # inspect the neighbourhood of hits that are NOT the known population copies
    print("\nlooking for plausible (x, altitude, z) near each seed occurrence:")
    candidates = 0
    read_buf = ctypes.create_string_buffer(1024)
    for address, seed in hits[:400]:
        start = address - 512
        got = ctypes.c_size_t(0)
        if start < 0:
            continue
        ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(start), read_buf, 1024,
                                        ctypes.byref(got))
        if not ok or got.value < 12:
            continue
        data = read_buf.raw[: got.value]
        position = plausible_position(data, start)
        if position:
            candidates += 1
            if candidates <= 12:
                where, x, y, z = position
                print(f"   seed 0x{seed:08X} ({wanted.get(seed, '?')}) @0x{address:X}")
                print(f"      vec3 @0x{where:X}  x={x:.1f} alt={y:.1f} z={z:.1f}")
    kernel32.CloseHandle(handle)
    print(f"\ncandidates with a nearby position triple: {candidates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
