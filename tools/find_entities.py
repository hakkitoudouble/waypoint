"""Find the live animal entities on THIS build, without relying on the published offsets.

AnimalRadar's offsets are tied to one exact game build (its own validation gate refuses
to run otherwise, and our exe hash differs). But the *shape* it documents is useful:

    entity + 40  -> species NameHashId   (an exact value from our 135-entry table)
    entity + 328 -> position Vector3

A 32-bit value drawn from a 135-entry set is a very specific signature: the chance of
a random dword matching is ~3e-8. So we scan memory for our species hashes, treat each
hit as living at +40, and accept it only if +328 reads back a world position inside the
reserve. That finds the entities without needing the build-specific static offset.

Run:  python tools/find_entities.py [reserve_index]
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

from cotw import species  # noqa: E402

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE = (0x02, 0x04, 0x20, 0x40)
CHUNK = 8 * 1024 * 1024

SPECIES_OFFSETS = (40, 44, 32, 48)   # candidate places for the species hash
POSITION_OFFSETS = (328, 320, 336)   # candidate places for the Vector3


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
    hashes = sorted(species.hash_table())
    print(f"species hashes: {len(hashes)}")
    wanted = np.array(hashes, dtype=np.uint32)

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
    hits: list[int] = []
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
                        hits.append(base + offset + int(idx) * 4)
                offset += want
                if got.value == 0:
                    break
    finally:
        pass

    print(f"scanned {scanned / 1024 / 1024:.0f} MiB in {time.time() - started:.0f}s")
    print(f"species-hash occurrences: {len(hits)}")

    # validate: treat each hit as living at +species_offset, look for a position
    results: list[tuple[int, str, float, float, float, int, int]] = []
    for address in hits:
        for species_offset in SPECIES_OFFSETS:
            entity = address - species_offset
            for position_offset in POSITION_OFFSETS:
                blob = read(h, entity + position_offset, 12)
                if len(blob) < 12:
                    continue
                x, y, z = struct.unpack("<fff", blob)
                if not (abs(x) < 30000 and abs(z) < 30000 and -2000 < y < 4000):
                    continue
                if abs(x) < 1 and abs(z) < 1:
                    continue
                hash_id = struct.unpack("<I", read(h, address, 4) or b"\0\0\0\0")[0]
                name = species.name_for_hash(hash_id) or f"0x{hash_id:08X}"
                results.append((entity, name, x, y, z, species_offset, position_offset))
                break
            else:
                continue
            break

    print(f"candidate entities: {len(results)}")
    for entity, name, x, y, z, so, po in results[:25]:
        print(f"  0x{entity:012X}  {name:<22} ({x:11.2f},{y:9.2f},{z:11.2f})  "
              f"species+{so} position+{po}")

    if results:
        import json
        cache = Path(__file__).resolve().parent.parent / "work" / "entities.json"
        cache.write_text(json.dumps([
            {"entity": e, "species": n, "x": x, "y": y, "z": z,
             "species_offset": so, "position_offset": po}
            for e, n, x, y, z, so, po in results
        ], indent=1), encoding="utf-8")
        print(f"\ncached -> {cache}")
    k.CloseHandle(h)
    return 0 if results else 2


if __name__ == "__main__":
    raise SystemExit(main())
