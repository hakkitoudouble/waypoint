"""Walk the game's live animal list using the pointer chain published by AnimalRadar.

The published offsets (offsets/field_test_25131233.json) are:

    module_base + 40486008      -> animal manager
    manager + 712                 -> std::vector<Animal*>  (begin, end, cap)
    animal + 328   (0x148)        -> position Vector3
    animal + 40    (0x028)        -> species hash
    animal + 376   (0x178)        -> hp max
    animal + 380   (0x17C)        -> hp
    animal + 412   (0x19C)        -> weight
    animal + 432   (0x1B0)        -> visual seed

Those offsets are build-specific, so everything here is validated before use: we
check that the manager looks like a pointer, that the vector's begin/end/cap are
sane, and that each element yields a position inside the reserve.

Read-only. Run:  python tools/radar_offsets.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw import species  # noqa: E402

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

#: offsets from the AnimalRadar release
OFF = {
    "animals": 40486008,
    "manager_vector": 712,
    "position": 328,
    "species": 40,
    "hpmax": 376,
    "hp": 380,
    "ragdoll": 192,
    "weight": 412,
    "seed": 432,
}

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = wt.HANDLE
k.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
k.ReadProcessMemory.restype = wt.BOOL
k.ReadProcessMemory.argtypes = (wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
k.CloseHandle.argtypes = (wt.HANDLE,)
k.CreateToolhelp32Snapshot.restype = wt.HANDLE


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)), ("modBaseSize", wt.DWORD),
        ("hModule", wt.HMODULE), ("szModule", wt.WCHAR * 256), ("szExePath", wt.WCHAR * 260),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


def find_pid() -> tuple[int, str] | None:
    snap = k.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    try:
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            name = str(e.szExeFile)
            if any(s in name.lower() for s in ("thehunter", "cotw")):
                return int(e.th32ProcessID), name
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return None


def module_base(pid: int, exe_hint: str) -> tuple[int, int]:
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    m = MODULEENTRY32W()
    m.dwSize = ctypes.sizeof(m)
    base = size = 0
    try:
        ok = k.Module32FirstW(snap, ctypes.byref(m))
        while ok:
            name = str(m.szModule)
            if name.lower() == exe_hint.lower() or (base == 0 and "thehunter" in name.lower()):
                base = ctypes.cast(m.modBaseAddr, ctypes.c_void_p).value or 0
                size = int(m.modBaseSize)
                print(f"module {name}: base=0x{base:X} size={size / 1024 / 1024:.0f} MiB")
                if name.lower() == exe_hint.lower():
                    break
            ok = k.Module32NextW(snap, ctypes.byref(m))
    finally:
        k.CloseHandle(snap)
    return base, size


def read(handle: int, address: int, size: int) -> bytes:
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t(0)
    if not k.ReadProcessMemory(handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got)):
        return b""
    return buf.raw[: got.value]


def u64(handle: int, address: int) -> int | None:
    raw = read(handle, address, 8)
    return struct.unpack("<Q", raw)[0] if len(raw) == 8 else None


def main() -> int:
    found = find_pid()
    if not found:
        print("FAIL: game not running")
        return 1
    pid, exe = found
    print(f"process {exe} pid={pid}")
    base, size = module_base(pid, exe)
    if not base:
        print("FAIL: module base not found")
        return 1

    handle = k.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        print("FAIL: open")
        return 1
    try:
        manager_slot = base + OFF["animals"]
        print(f"manager slot @0x{manager_slot:X}  (module+{OFF['animals']})")
        raw = read(handle, manager_slot, 32)
        if not raw:
            print("  unreadable — the offset does not fit this build")
            return 2
        print("  bytes:", raw[:32].hex(" "))
        manager = struct.unpack_from("<Q", raw, 0)[0]
        print(f"  -> manager = 0x{manager:X}")
        if not (0x10000 < manager < 0x7FFF_FFFF_FFFF):
            print("  manager does not look like a pointer; trying the slot as inline data")
            manager = manager_slot

        vector = manager + OFF["manager_vector"]
        vec = read(handle, vector, 24)
        if len(vec) < 24:
            print("  vector unreadable")
            return 2
        begin, end, cap = struct.unpack("<QQQ", vec)
        print(f"  vector @0x{vector:X}: begin=0x{begin:X} end=0x{end:X} cap=0x{cap:X}")
        if not (begin and end >= begin):
            print("  vector does not look like begin/end pointers")
            return 2
        count = (end - begin) // 8
        print(f"  entries: {count}")
        if count > 20000:
            print("  implausible count, aborting")
            return 2

        raw_ptrs = read(handle, begin, count * 8)
        pointers = list(struct.unpack(f"<{len(raw_ptrs) // 8}Q", raw_ptrs[: (len(raw_ptrs) // 8) * 8]))
        print(f"  read {len(pointers)} entity pointers")

        good = 0
        shown = 0
        print(f"\n{'#':>4}  {'position (x, y, z)':<40} {'species':<22} hp")
        for index, pointer in enumerate(pointers):
            if not (0x10000 < pointer < 0x7FFF_FFFF_FFFF):
                continue
            blob = read(handle, pointer, 0x1B8)
            if len(blob) < 0x1B8:
                continue
            x, y, z = struct.unpack_from("<fff", blob, OFF["position"])
            species_hash = struct.unpack_from("<I", blob, OFF["species"])[0]
            hp, hpmax = struct.unpack_from("<ff", blob, OFF["hp"]), struct.unpack_from("<ff", blob, OFF["hpmax"])
            if not (abs(x) < 30000 and abs(z) < 30000 and -5000 < y < 5000):
                continue
            good += 1
            if shown < 24:
                name = species.name_for_hash(species_hash) or f"0x{species_hash:08X}"
                print(f"{index:>4}  ({x:11.2f},{y:9.2f},{z:11.2f})  {name:<22} "
                      f"{hp[0]:.0f}/{hpmax[0]:.0f}")
                shown += 1
        print(f"\nentities with a sane position: {good}")
        return 0 if good else 2
    finally:
        k.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
