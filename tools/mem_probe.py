"""Read-only reconnaissance of the running game process.

Step 1 of the live scan: find the process, open it for reading, and map its memory.
Nothing is written and nothing is injected — we only ask Windows for region metadata.

Run:  python tools/mem_probe.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010

MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
READABLE = (0x02, 0x04, 0x20, 0x40)  # RO, RW, EXEC_R, EXEC_RW

#: substrings that identify the game's executable
CANDIDATES = ("thehunter", "cotw", "thehuntercotw")


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
kernel32.VirtualQueryEx.argtypes = (
    wt.HANDLE,
    ctypes.c_void_p,
    ctypes.POINTER(MEMORY_BASIC_INFORMATION64),
    ctypes.c_size_t,
)
kernel32.CloseHandle.argtypes = (wt.HANDLE,)


def list_processes() -> list[tuple[int, str]]:
    """Return (pid, exe name) for every process we can query."""
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD),
            ("cntUsage", wt.DWORD),
            ("th32ProcessID", wt.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wt.DWORD),
            ("cntThreads", wt.DWORD),
            ("th32ParentProcessID", wt.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wt.DWORD),
            ("szExeFile", wt.WCHAR * 260),
        ]

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wt.HANDLE(-1).value:
        return []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    out: list[tuple[int, str]] = []
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            out.append((int(entry.th32ProcessID), str(entry.szExeFile)))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return out


def regions(handle: int) -> list[tuple[int, int, int]]:
    """(base, size, protect) for committed, readable, guard-free regions."""
    out: list[tuple[int, int, int]] = []
    address = 0
    info = MEMORY_BASIC_INFORMATION64()
    limit = 0x7FFF_FFFF_FFFF
    while address < limit:
        written = kernel32.VirtualQueryEx(
            handle, ctypes.c_void_p(address), ctypes.byref(info), ctypes.sizeof(info)
        )
        if not written:
            break
        base = int(info.BaseAddress)
        size = int(info.RegionSize)
        if size <= 0:
            break
        if (
            info.State == MEM_COMMIT
            and (info.Protect & 0xFF) in READABLE
            and not (info.Protect & PAGE_GUARD)
            and not (info.Protect & PAGE_NOACCESS)
        ):
            out.append((base, size, int(info.Protect)))
        address = base + size
    return out


def main() -> int:
    procs = list_processes()
    matches = [(pid, name) for pid, name in procs if any(c in name.lower() for c in CANDIDATES)]
    if not matches:
        print("FAIL: no COTW process found. Running processes containing 'thehunter'/'cotw': none")
        print("      (run the game, leave it in a reserve, then retry)")
        return 1

    for pid, name in matches:
        print(f"process: {name} (pid {pid})")
        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not handle:
            err = ctypes.get_last_error()
            print(f"  FAIL: OpenProcess denied (error {err}). "
                  "A protected process needs elevation or a different access path.")
            continue
        try:
            regs = regions(handle)
            total = sum(size for _, size, _ in regs)
            biggest = sorted(regs, key=lambda r: -r[1])[:6]
            print(f"  readable regions: {len(regs)}")
            print(f"  addressable bytes: {total:,} ({total / 1024 / 1024:.0f} MiB)")
            print("  largest regions:")
            for base, size, protect in biggest:
                print(f"    0x{base:012X}  {size / 1024 / 1024:8.1f} MiB  protect=0x{protect:03X}")
        finally:
            kernel32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
