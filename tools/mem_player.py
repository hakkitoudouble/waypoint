"""Locate the player's world position in memory, then look for entities around it.

The game UI shows the player's live position, so searching for those exact float32
values gives a unique anchor. Once we have the player's (x, altitude, z) we can look
in a radius around it for structures that also carry an animal seed — that is where
live animal positions would live, if they are persisted anywhere at all.

Read-only. Run:  python tools/mem_player.py <x> <z> [altitude]
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
    TH32CS_SNAPPROCESS = 0x00000002

    class PE(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
            ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
            ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
            ("szExeFile", wt.WCHAR * 260),
        ]

    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
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
        print("usage: mem_player.py <x> <z> [altitude]")
        return 1
    px, pz = float(sys.argv[1]), float(sys.argv[2])
    pat_x = struct.pack("<f", px)
    pat_z = struct.pack("<f", pz)
    found = find_pid()
    if not found:
        print("FAIL: game process not running")
        return 1
    pid, exe = found
    print(f"target {exe} pid={pid}  player=({px}, {pz})")
    print(f"  x bytes {pat_x.hex(' ')}   z bytes {pat_z.hex(' ')}")

    h = k.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        print("FAIL: open")
        return 1
    buf = ctypes.create_string_buffer(CHUNK)
    xs: list[int] = []
    zs: list[int] = []
    scanned = 0
    started = time.time()
    try:
        for base, size in regions(h):
            offset = 0
            while offset < size:
                want = min(CHUNK, size - offset)
                got = ctypes.c_size_t(0)
                if k.ReadProcessMemory(h, ctypes.c_void_p(base + offset), buf, want, ctypes.byref(got)) and got.value:
                    data = buf.raw[: got.value]
                    scanned += len(data)
                    for pattern, sink in ((pat_x, xs), (pat_z, zs)):
                        if len(sink) >= 60:
                            continue
                        start = 0
                        while len(sink) < 60:
                            i = data.find(pattern, start)
                            if i < 0:
                                break
                            sink.append(base + offset + i)
                            start = i + 1
                offset += want
                if got.value == 0:
                    break
    finally:
        pass
    print(f"scanned {scanned / 1024 / 1024:.0f} MiB in {time.time() - started:.0f}s")
    print(f"  x hits: {len(xs)}   z hits: {len(zs)}")

    print("\nadjacent x/z pairs (within 64 bytes):")
    pairs = 0
    for ax in xs:
        for az in zs:
            if abs(ax - az) <= 64:
                pairs += 1
                if pairs <= 8:
                    print(f"   x@0x{ax:X}  z@0x{az:X}  delta={az - ax:+d}")
    print(f"   total adjacent pairs: {pairs}")

    # read around the best pair: if the three floats are a Vector3 we see the altitude
    if pairs:
        ax = xs[0]
        for az in zs:
            if abs(ax - az) <= 16:
                start = min(ax, az) - 16
                rb = ctypes.create_string_buffer(64)
                gg = ctypes.c_size_t(0)
                if k.ReadProcessMemory(h, ctypes.c_void_p(start), rb, 64, ctypes.byref(gg)) and gg.value:
                    vals = struct.unpack_from("<16f", rb.raw[:64], 0)
                    print(f"\n   floats around 0x{start:X}:")
                    print("   " + "  ".join(f"{v:.2f}" for v in vals))
                break
    k.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
