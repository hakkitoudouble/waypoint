"""Scan the running game's memory for the animal array, read-only.

Signature: the save stores `Weight` at +0x04 and `Score` at +0x08 of a 32-byte
`AnimalData_5`. That makes the pair of float32 values adjacent in memory, which is a
very specific 8-byte pattern — we take exact values from the save so there is no
rounding ambiguity.

Run:  python tools/mem_scan.py [reserve_index]
Prints where each pattern was found and, for each hit, the surrounding bytes.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time
from pathlib import Path

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
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wt.DWORD),
        ("__alignment1", wt.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
        ("__alignment2", wt.DWORD),
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


def find_pid(substrings: tuple[str, ...]) -> tuple[int, str] | None:
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


def readable_regions(handle: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
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


def scan(handle: int, patterns: dict[bytes, str]) -> dict[str, list[int]]:
    hits: dict[str, list[int]] = {label: [] for label in patterns.values()}
    overlap = max(len(p) for p in patterns) - 1
    buffer = ctypes.create_string_buffer(CHUNK + overlap)
    scanned = 0
    started = time.time()
    regions = readable_regions(handle)
    read_ok = 0
    read_fail = 0

    for base, size in regions:
        offset = 0
        while offset < size:
            want = min(CHUNK, size - offset)
            got = ctypes.c_size_t(0)
            ok = kernel32.ReadProcessMemory(
                handle, ctypes.c_void_p(base + offset), buffer, want, ctypes.byref(got)
            )
            if ok and got.value:
                data = buffer.raw[: got.value]
                scanned += len(data)
                read_ok += 1
                for pattern, label in patterns.items():
                    if len(hits[label]) >= 12:
                        continue
                    start = 0
                    while True:
                        index = data.find(pattern, start)
                        if index < 0:
                            break
                        hits[label].append(base + offset + index)
                        start = index + 1
                        if len(hits[label]) >= 12:
                            break
            else:
                read_fail += 1
            offset += want
            if got.value == 0:
                break

    elapsed = time.time() - started
    print(f"scanned {scanned / 1024 / 1024:.0f} MiB in {elapsed:.1f}s "
          f"({read_ok} chunks ok, {read_fail} unreadable)")
    return hits


def main() -> int:
    reserve = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    dirs = save.find_save_dirs()
    if not dirs:
        print("no save dir")
        return 1

    doc = adf.parse_document(save.read_container(dirs[0] / f"animal_population_{reserve}").payload)
    root = doc.parse_entry(0)

    # pick the heaviest animals of the reserve: their (weight, score) pair is the
    # most distinctive 8 bytes we can look for
    candidates: list[tuple[float, float, str]] = []
    for pop in root.get("Populations", []) or []:
        name = species.name_for_hash(pop.get("NameHashId")) or "?"
        for group in pop.get("Groups", []) or []:
            for animal in group.get("Animals", []) or []:
                weight = animal.get("Weight")
                score = animal.get("Score")
                if isinstance(weight, float) and isinstance(score, float) and score > 0:
                    candidates.append((weight, score, name))
    candidates.sort(key=lambda c: -c[0])

    patterns: dict[bytes, str] = {}
    for weight, score, name in candidates[:6]:
        pattern = struct.pack("<ff", weight, score)
        patterns[pattern] = f"{name} w={weight:.2f} s={score:.2f}"

    found = find_pid(("thehunter", "cotw"))
    if not found:
        print("FAIL: game process not running")
        return 1
    pid, exe = found
    print(f"target: {exe} (pid {pid})")
    print(f"patterns from reserve {reserve}: {len(patterns)}")
    for label in patterns.values():
        print(f"   {label}")

    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        print(f"FAIL: OpenProcess denied (error {ctypes.get_last_error()})")
        return 1
    try:
        hits = scan(handle, patterns)
    finally:
        kernel32.CloseHandle(handle)

    print()
    total = 0
    for label, addresses in hits.items():
        total += len(addresses)
        print(f"{label}: {len(addresses)} hit(s)")
        for address in addresses[:6]:
            print(f"    0x{address:012X}")
    print()
    print("TOTAL hits:", total)
    return 0 if total else 2


if __name__ == "__main__":
    raise SystemExit(main())
