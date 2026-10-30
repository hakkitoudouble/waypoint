"""Full candidate report for one species, to see what the radar missed.

The previous pass reported a single Black Bear at 335 m while the user saw two at about
240 m, so the pipeline is dropping entities somewhere. This dumps EVERY occurrence of a
Black Bear hash, every plausible position within +-1024 bytes of it, and the resulting
offset — no de-duplication and no single-delta assumption.

Run:  python tools/radar_bears.py [species] [player_x] [player_z]
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import math
import struct
import sys
import time
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
WINDOW = 4096
POSITION_HINT = -276

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
    target = sys.argv[1] if len(sys.argv) > 1 else "Black Bear"
    px = float(sys.argv[2]) if len(sys.argv) > 2 else -7420.183
    pz = float(sys.argv[3]) if len(sys.argv) > 3 else -13002.233

    table = species.hash_table()
    wanted_hashes = {h for h, name in table.items() if name == target}
    if not wanted_hashes:
        print(f"FAIL: no hashes for {target!r}")
        return 1
    print(f"target {target!r}: {len(wanted_hashes)} hash(es): "
          + ", ".join(f"{h:08X}" for h in sorted(wanted_hashes)))

    all_hashes = np.array(sorted(table), dtype=np.uint32)
    targets = np.array(sorted(wanted_hashes), dtype=np.uint32)

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
    target_hits: list[tuple[int, int]] = []
    total_hits = 0
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
                    words = np.frombuffer(data[: (len(data) // 4) * 4], dtype=np.uint32)
                    mask = np.isin(words, all_hashes)
                    for idx in np.nonzero(mask)[0]:
                        address = base + offset + int(idx) * 4
                        value = int(words[idx])
                        total_hits += 1
                        if value in wanted_hashes:
                            target_hits.append((address, value))
                offset += want
                if got.value == 0:
                    break
    finally:
        pass
    print(f"scanned {scanned / 1024 / 1024:.0f} MiB in {time.time() - started:.0f}s")
    print(f"species-hash hits: {total_hits}   {target} hits: {len(target_hits)}")

    import json

    cache = Path(__file__).resolve().parent.parent / "work" / f"hits_{target.replace(' ', '_')}.json"
    cache.write_text(json.dumps([[a, v] for a, v in target_hits]), encoding="utf-8")
    print(f"cached {len(target_hits)} hit(s) -> {cache}")

    print(f"\nraw position at delta {POSITION_HINT} for EVERY {target} hit (no bounds applied):")
    print(f"{'x':>11} {'y':>9} {'z':>11}   {'dist m':>7}  hash@")
    for address, _ in target_hits:
        blob = read(h, address + POSITION_HINT, 12)
        if len(blob) < 12:
            continue
        x, y, z = struct.unpack("<fff", blob)
        if not all(map(math.isfinite, (x, y, z))):
            continue
        if abs(x) < 1e-6 and abs(y) < 1e-6 and abs(z) < 1e-6:
            continue
        print(f"{x:>11.1f} {y:>9.1f} {z:>11.1f}   {math.hypot(x - px, z - pz):>7.0f}  0x{address:X}")

    print(f"\nevery plausible position within +-{WINDOW // 2} bytes of a {target} hash:")
    print(f"{'delta':>7}  {'x':>10} {'y':>8} {'z':>10}   {'dist m':>7}  hash@")
    rows = []
    for address, hash_id in target_hits:
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
            position_address = base + i * 4
            delta = position_address - address
            distance = math.hypot(x - px, z - pz)
            rows.append((delta, x, y, z, distance, address))
    rows.sort(key=lambda r: r[4])
    for delta, x, y, z, distance, address in rows:
        print(f"{delta:>+7}  {x:>10.1f} {y:>8.1f} {z:>10.1f}   {distance:>7.0f}  0x{address:X}")
    print(f"\n{len(rows)} candidate position(s); closest {rows[0][4]:.0f} m" if rows else "\nnone")
    k.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
