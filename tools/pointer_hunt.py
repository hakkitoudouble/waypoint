"""Find who points at a memory range — the building block for a stable pointer chain.

Scanning 7 GiB on every refresh is unusable (2.5 minutes). The fix is to resolve the
chain once: static module offset -> manager -> std::vector -> entity pointers, then a
refresh costs a handful of reads.

This tool is the middle step: given an address range that holds entity records, find
every qword that points into it. Those pointers live in the vector's backing array, and
their addresses tell us where that array sits.

Run:  python tools/pointer_hunt.py <lo_hex> <hi_hex>
      python tools/pointer_hunt.py --from-entity   (uses work/entities2.json)
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import struct
import sys
import time
from collections import Counter
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
        print("usage: pointer_hunt.py <lo_hex> <hi_hex>")
        return 1
    lo, hi = int(sys.argv[1], 16), int(sys.argv[2], 16)
    print(f"hunting qwords in [0x{lo:X}, 0x{hi:X}]  (span {hi - lo} B)")

    found = find_pid()
    if not found:
        print("FAIL: game not running")
        return 1
    pid, exe = found
    h = k.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        print("FAIL: open")
        return 1

    addresses: list[int] = []
    values: list[int] = []
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
                                       ctypes.byref(got)) and got.value >= 8:
                    data = buf.raw[: got.value]
                    scanned += len(data)
                    words = np.frombuffer(data[: (len(data) // 8) * 8], dtype=np.uint64)
                    mask = (words >= lo) & (words <= hi)
                    for idx in np.nonzero(mask)[0]:
                        addresses.append(base + offset + int(idx) * 8)
                        values.append(int(words[idx]))
                offset += want
                if got.value == 0:
                    break
    finally:
        k.CloseHandle(h)

    print(f"scanned {scanned / 1024 / 1024:.0f} MiB in {time.time() - started:.0f}s")
    print(f"pointers found: {len(addresses)}")

    if not addresses:
        return 2

    # the vector's backing array is a dense run of such pointers
    addresses.sort()
    runs: list[tuple[int, int]] = []
    start = addresses[0]
    previous = addresses[0]
    for address in addresses[1:]:
        if address - previous <= 64:
            previous = address
        else:
            runs.append((start, previous))
            start = previous = address
    runs.append((start, previous))
    runs.sort(key=lambda r: -(r[1] - r[0]))
    print("\ndensest runs of pointer slots (candidate vectors):")
    for first, last in runs[:8]:
        print(f"   0x{first:X} .. 0x{last:X}   {last - first + 8} B "
              f"~ {(last - first) // 8 + 1} slots")

    out = Path(__file__).resolve().parent.parent / "work" / "pointer_hits.json"
    out.write_text(json.dumps({"range": [lo, hi], "hits": addresses}), encoding="utf-8")
    print(f"\ncached -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
