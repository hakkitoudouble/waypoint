"""Read the player position from the HUD's own coordinate text.

Every other approach needs to know the position before it can find it. This one does
not: the game formats the player coordinates as text ("-7583.511, -13065.611") for the
map screen, so we can scan memory for that *shape* with a regex and parse whatever is
currently there. That makes player tracking independent of any prior measurement.

Both narrow (ASCII/UTF-8) and wide (UTF-16LE) encodings are searched, since Qt strings
are UTF-16 while cheaper paths use UTF-8.

Run:  python tools/find_hud.py [min_x max_x min_z max_z]
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import re
import sys
import time
from pathlib import Path

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE = (0x02, 0x04, 0x20, 0x40)
CHUNK = 8 * 1024 * 1024

#: "-7583.511, -13065.611"
NARROW = re.compile(rb"-(\d{3,5})\.(\d{3}), ?-(\d{3,5})\.(\d{3})")
#: same, each character followed by a NUL (UTF-16LE)
WIDE = re.compile(
    rb"-\x00((?:\d\x00){3,5})\.\x00((?:\d\x00){3}),\x00 ?\x00-"
    rb"\x00((?:\d\x00){3,5})\.\x00((?:\d\x00){3})"
)


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


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


def find_pid():
    snap = k.CreateToolhelp32Snapshot(2, 0)
    e = PROCESSENTRY32W()
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


def decode(groups: tuple[bytes, ...]) -> float:
    digits = b"".join(groups)
    return -float(digits.decode("latin-1"))


def decode_wide(groups: tuple[bytes, ...]) -> float:
    digits = b"".join(groups).replace(b"\x00", b"")
    return -float(digits.decode("latin-1"))


def main() -> int:
    lo_x, hi_x = -13000.0, 2000.0
    lo_z, hi_z = -14000.0, -4000.0
    if len(sys.argv) >= 5:
        lo_x, hi_x, lo_z, hi_z = (float(sys.argv[1]), float(sys.argv[2]),
                                  float(sys.argv[3]), float(sys.argv[4]))

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
    matches: list[tuple[int, float, float, str]] = []
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
                    for regex, wide in ((NARROW, False), (WIDE, True)):
                        for match in regex.finditer(data):
                            try:
                                if wide:
                                    x = decode_wide((match.group(1), match.group(2)))
                                    z = decode_wide((match.group(3), match.group(4)))
                                else:
                                    x = decode((match.group(1), match.group(2)))
                                    z = decode((match.group(3), match.group(4)))
                            except (ValueError, UnicodeDecodeError):
                                continue
                            matches.append((base + offset + match.start(), x, z,
                                            "wide" if wide else "narrow"))
                offset += want
                if got.value == 0:
                    break
    finally:
        k.CloseHandle(h)

    print(f"scanned {scanned / 1024 / 1024:.0f} MiB in {time.time() - started:.0f}s")
    in_bounds = [m for m in matches if lo_x < m[1] < hi_x and lo_z < m[2] < hi_z]
    print(f"coordinate-shaped strings: {len(matches)}   inside the reserve box: {len(in_bounds)}")

    seen: dict[tuple[float, float], list[tuple[int, str]]] = {}
    for address, x, z, kind in in_bounds:
        seen.setdefault((x, z), []).append((address, kind))
    print(f"\ndistinct positions: {len(seen)}")
    for (x, z), where in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        kinds = {"narrow": 0, "wide": 0}
        for _, kind in where:
            kinds[kind] += 1
        print(f"  ({x:10.3f}, {z:10.3f})  {len(where):>3} copy/copies "
              f"(narrow {kinds['narrow']}, wide {kinds['wide']})  e.g. 0x{where[0][0]:X}")

    out = Path(__file__).resolve().parent.parent / "work" / "hud_positions.json"
    out.write_text(json.dumps([
        {"address": a, "x": x, "z": z, "encoding": kind} for a, x, z, kind in in_bounds
    ], indent=1), encoding="utf-8")
    print(f"\ncached -> {out}")
    return 0 if in_bounds else 2


if __name__ == "__main__":
    raise SystemExit(main())
