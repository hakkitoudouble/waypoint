"""Read one animal record out of the live process and interpret it.

Given the address of a `Weight` float (found by mem_scan), the save layout says the
record starts 4 bytes earlier:

    +0x00 u8  Gender        +0x04 f32 Weight      +0x08 f32 Score
    +0x0C u8  FeatureMods   +0x0D u8 IsScripted   +0x10 u32 Seed
    +0x14 u32 Id            +0x18 f32 MapX        +0x1C f32 MapY

Read-only. Run:  python tools/mem_read.py <weight_address_hex> [more...]
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
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


def read(handle: int, address: int, size: int) -> bytes:
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got))
    if not ok or not got.value:
        return b""
    return buf.raw[: got.value]


def main() -> int:
    addresses = [int(a, 16) for a in sys.argv[1:]]
    if not addresses:
        print("usage: mem_read.py <hex address> [...]")
        return 1
    found = find_pid(("thehunter", "cotw"))
    if not found:
        print("FAIL: game process not running")
        return 1
    pid, exe = found
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        print(f"FAIL: OpenProcess denied ({ctypes.get_last_error()})")
        return 1
    try:
        for weight_addr in addresses:
            start = weight_addr - 4
            raw = read(handle, start, 32)
            print(f"=== weight @0x{weight_addr:X}  record @0x{start:X} ===")
            if len(raw) < 32:
                print("   unreadable")
                continue
            gender = raw[0]
            weight, score = struct.unpack_from("<ff", raw, 4)
            features, scripted = raw[12], raw[13]
            seed, ident = struct.unpack_from("<II", raw, 16)
            mapx, mapy = struct.unpack_from("<ff", raw, 24)
            print(f"   Gender          {gender}")
            print(f"   Weight          {weight:.4f}")
            print(f"   Score           {score:.4f}")
            print(f"   FeatureModifiers 0x{features:02X}")
            print(f"   IsScripted      {scripted}")
            print(f"   Seed            0x{seed:08X}")
            print(f"   Id              {ident}")
            print(f"   MapPosition     X={mapx:.3f}  Y={mapy:.3f}")
            print(f"   raw             {raw.hex(' ')}")
            plausible = abs(mapx) < 20000 and abs(mapy) < 20000 and (abs(mapx) > 0.01 or abs(mapy) > 0.01)
            print(f"   -> position looks {'PLAUSIBLE' if plausible else 'PLACEHOLDER/zero'}")
            print()
    finally:
        kernel32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
