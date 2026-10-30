"""Locate the live player position in memory, using the coordinates the HUD shows.

We know from the radar test that the game's displayed coordinates are float32 values
that exist in memory: the player's X at -7583.511 was found exactly once. The Z at
-13065.611 was NOT found earlier for a different position, so this scan records every
occurrence of both values and reports how close they are to each other — if X and Z sit
within a few dozen bytes, we have the player's transform.

Run:  python tools/find_player.py <x> <z>
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time
from pathlib import Path

import numpy as np

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


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: find_player.py <x> <z>")
        return 1
    px, pz = float(sys.argv[1]), float(sys.argv[2])
    pat_x = struct.pack("<f", px)
    pat_z = struct.pack("<f", pz)
    print(f"looking for x={px} ({pat_x.hex(' ')}) and z={pz} ({pat_z.hex(' ')})")

    found = find_pid()
    if not found:
        print("FAIL: game not running")
        return 1
    pid, exe = found
    h = k.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        print("FAIL: open")
        return 1

    xs: list[int] = []
    zs: list[int] = []
    buf = ctypes.create_string_buffer(CHUNK)
    scanned = 0
    started = time.time()
    try:
        for base, size in regions(h):
            offset = 0
            while offset < size:
                want = min(CHUNK, size - offset)
                got = ctypes.c_size_t(0)
                if k.ReadProcessMemory(h, ctypes.c_void_p(base + offset), buf, want,
                                       ctypes.byref(got)) and got.value:
                    data = buf.raw[: got.value]
                    scanned += len(data)
                    for pattern, sink in ((pat_x, xs), (pat_z, zs)):
                        start = 0
                        while True:
                            i = data.find(pattern, start)
                            if i < 0:
                                break
                            sink.append(base + offset + i)
                            start = i + 1
                offset += want
                if got.value == 0:
                    break
    finally:
        k.CloseHandle(h)

    print(f"scanned {scanned / 1024 / 1024:.0f} MiB in {time.time() - started:.0f}s")
    print(f"  x occurrences: {len(xs)}  -> {[hex(a) for a in xs[:8]]}")
    print(f"  z occurrences: {len(zs)}  -> {[hex(a) for a in zs[:8]]}")

    print("\nclosest x/z pairs:")
    pairs = []
    for ax in xs:
        for az in zs:
            pairs.append((abs(ax - az), ax, az))
    pairs.sort()
    for gap, ax, az in pairs[:10]:
        print(f"   gap={gap:>5} B   x@0x{ax:X}   z@0x{az:X}")

    if pairs and pairs[0][0] <= 64:
        gap, ax, az = pairs[0]
        print(f"\nPLAYER TRANSFORM LIKELY at 0x{min(ax, az) - 8:X} (x@0x{ax:X}, z@0x{az:X})")
    else:
        print("\nno close pair: the displayed Z is not stored as float32 near the X")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
