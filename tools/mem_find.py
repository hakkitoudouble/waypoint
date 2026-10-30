"""Locate specific world coordinates in the live process.

We now have ground truth straight from the game UI: a Black Bear drink zone at
(-7412.0, -12984.0) active 04:00-08:00, and the player standing at
(-7419.738, -13004.455). Finding those floats in memory gives us a hard anchor —
and the player position in particular lets us look for the entities clustered around
him, which is where live animal positions would be.

Read-only. Run:  python tools/mem_find.py
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

#: values the game displayed, so their presence in memory is not a guess
TARGETS = {
    "needzone_x": -7412.0,
    "needzone_z": -12984.0,
    "player_x": -7419.738,
    "player_z": -13004.455,
}


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


def main() -> int:
    patterns = {name: struct.pack("<f", value) for name, value in TARGETS.items()}
    found = find_pid(("thehunter", "cotw"))
    if not found:
        print("FAIL: game process not running")
        return 1
    pid, exe = found
    print(f"target: {exe} (pid {pid})")
    for name, value in TARGETS.items():
        print(f"   {name:<12} {value}  bytes={patterns[name].hex(' ')}")

    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        print("FAIL: OpenProcess denied")
        return 1

    hits: dict[str, list[int]] = {name: [] for name in TARGETS}
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
                if ok and got.value:
                    data = buffer.raw[: got.value]
                    scanned += len(data)
                    for name, pattern in patterns.items():
                        if len(hits[name]) >= 40:
                            continue
                        start = 0
                        while len(hits[name]) < 40:
                            index = data.find(pattern, start)
                            if index < 0:
                                break
                            hits[name].append(base + offset + index)
                            start = index + 1
                offset += want
                if got.value == 0:
                    break
    finally:
        kernel32.CloseHandle(handle)

    print(f"\nscanned {scanned / 1024 / 1024:.0f} MiB in {time.time() - started:.0f}s")
    for name, addresses in hits.items():
        print(f"{name:<12} {len(addresses)} hit(s)")
        for address in addresses[:8]:
            print(f"    0x{address:012X}")

    # the interesting case: a hit for needzone_x with needzone_z within a few bytes
    cache = Path(__file__).resolve().parent.parent / "work" / "mem_find_hits.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    import json

    cache.write_text(json.dumps({k: v for k, v in hits.items()}), encoding="utf-8")
    print(f"\ncached -> {cache}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
