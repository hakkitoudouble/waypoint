"""Find the live animal entities by consistency of offsets, not by single hits.

A single (species hash, plausible position) pair is weak — random floats hit the bounds
often enough to produce hundreds of false positives. Real entities, though, share the
*same* offset between the species hash and the position. So we histogram that delta
across every species-hash hit and keep the offset that many entities agree on.

Bounds are Silver Ridge Peaks specific: its need zones span x[-10159..1047],
z[-13192..-5624], so an animal position must sit near that box.

Run:  python tools/find_entities2.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
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
#: The first pass used 1024, which structurally EXCLUDED the real offset of -580.
#: Confirmed against the user's in-game distances: two Black Bears at 239.3 m and
#: 238.6 m from (-7583.511, -13065.611), and the player's own record at 1.2 m.
WINDOW = 4096  # bytes read around each species-hash hit

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


def main() -> int:
    wanted = np.array(sorted(species.hash_table()), dtype=np.uint32)
    found = find_pid()
    if not found:
        print("FAIL: game not running")
        return 1
    pid, exe = found
    print(f"process {exe} pid={pid}")

    h = k.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        print("FAIL: open")
        return 1

    buf = ctypes.create_string_buffer(CHUNK)
    hits: list[tuple[int, int]] = []  # (address, species hash)
    scanned = 0
    started = time.time()
    try:
        for base, size in regions(h):
            offset = 0
            while offset < size:
                want = min(CHUNK, size - offset)
                got = ctypes.c_size_t(0)
                if k.ReadProcessMemory(h, ctypes.c_void_p(base + offset), buf, want,
                                       ctypes.byref(got)) and got.value >= 4:
                    data = buf.raw[: got.value]
                    scanned += len(data)
                    words = np.frombuffer(data[: (len(data) // 4) * 4], dtype=np.uint32)
                    mask = np.isin(words, wanted)
                    for idx in np.nonzero(mask)[0]:
                        hits.append((base + offset + int(idx) * 4, int(words[idx])))
                offset += want
                if got.value == 0:
                    break
    finally:
        pass
    print(f"scanned {scanned / 1024 / 1024:.0f} MiB in {time.time() - started:.0f}s")
    print(f"species-hash occurrences: {len(hits)}")

    # histogram the offset between a species hash and any plausible position nearby
    deltas: Counter[int] = Counter()
    evidence: dict[int, list[tuple[int, str, float, float, float]]] = {}
    for address, hash_id in hits:
        base = address - WINDOW // 2
        blob = read(h, base, WINDOW)
        if len(blob) < WINDOW:
            continue
        values = np.frombuffer(blob, dtype="<f4")
        n = len(values)
        for i in range(n - 2):
            x, y, z = float(values[i]), float(values[i + 1]), float(values[i + 2])
            if not (X_MIN < x < X_MAX and Z_MIN < z < Z_MAX and Y_MIN < y < Y_MAX):
                continue
            delta = (base + i * 4) - address
            deltas[delta] += 1
            evidence.setdefault(delta, []).append(
                (address, species.name_for_hash(hash_id) or f"0x{hash_id:08X}", x, y, z)
            )

    print(f"\ndistinct deltas: {len(deltas)}")
    print("top deltas (species hash -> position):")
    for delta, count in deltas.most_common(10):
        print(f"   delta={delta:>+6}   {count} pair(s)")

    best = deltas.most_common(1)
    if not best or best[0][1] < 5:
        print("\nno delta is supported by enough entities — layout not found")
        k.CloseHandle(h)
        return 2

    delta, count = best[0]
    print(f"\nwinner delta={delta} with {count} entities")
    print(f"{'species':<22} {'position':<38} entity")
    for address, name, x, y, z in evidence[delta][:20]:
        print(f"{name:<22} ({x:10.2f},{y:8.2f},{z:10.2f})  0x{address - WINDOW // 2:X}")

    import json
    out = Path(__file__).resolve().parent.parent / "work" / "entities2.json"
    out.write_text(json.dumps({
        "delta": delta,
        "count": count,
        "entities": [
            {"species": n, "x": x, "y": y, "z": z, "hash_address": a}
            for a, n, x, y, z in evidence[delta]
        ],
    }, indent=1), encoding="utf-8")
    print(f"\ncached -> {out}")
    k.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
