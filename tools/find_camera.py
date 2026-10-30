"""Find the camera matrix in the game module — the key to an automatic player position.

AnimalRadar reads its camera at ``module_base + 41841396``, which is *inside* the module
image, so the camera lives in the module's static data rather than on the heap. That is
good news: the module is 42 MiB, so we can scan all of it in a second instead of the
2.5 minutes a full process scan costs.

A view matrix is recognisable without knowing any value in advance: its rotation part is
an orthonormal basis (three unit, mutually perpendicular vectors) and its fourth
component is (0, 0, 0, 1). Its translation is the camera position, which must fall
inside the reserve.

Run:  python tools/find_camera.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

X_MIN, X_MAX = -13000.0, 2000.0
Z_MIN, Z_MAX = -14000.0, -4000.0


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


k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = wt.HANDLE
k.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
k.ReadProcessMemory.restype = wt.BOOL
k.ReadProcessMemory.argtypes = (wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
k.CloseHandle.argtypes = (wt.HANDLE,)
k.CreateToolhelp32Snapshot.restype = wt.HANDLE


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


def main() -> int:
    found = find_pid()
    if not found:
        print("FAIL: game not running")
        return 1
    pid, exe = found
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    m = MODULEENTRY32W()
    m.dwSize = ctypes.sizeof(m)
    base = size = 0
    try:
        ok = k.Module32FirstW(snap, ctypes.byref(m))
        while ok:
            if str(m.szModule).lower() == exe.lower():
                base = ctypes.cast(m.modBaseAddr, ctypes.c_void_p).value or 0
                size = int(m.modBaseSize)
                break
            ok = k.Module32NextW(snap, ctypes.byref(m))
    finally:
        k.CloseHandle(snap)
    if not base:
        print("FAIL: module not found")
        return 1
    print(f"module base 0x{base:X}  size {size / 1024 / 1024:.0f} MiB")

    handle = k.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        print("FAIL: open")
        return 1
    blob = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t(0)
    k.ReadProcessMemory(handle, ctypes.c_void_p(base), blob, size, ctypes.byref(got))
    k.CloseHandle(handle)
    data = blob.raw[: got.value]
    print(f"read {len(data) / 1024 / 1024:.0f} MiB of module image")

    values = np.frombuffer(data[: (len(data) // 4) * 4], dtype="<f4")
    n = len(values)
    hits = []
    # scan every 4-byte aligned window of 16 floats
    for i in range(0, n - 16):
        block = values[i: i + 16]
        w = block[12:16]
        # fourth component must be (0, 0, 0, 1)
        if not (abs(w[0]) < 1e-4 and abs(w[1]) < 1e-4 and abs(w[2]) < 1e-4
                and abs(w[3] - 1.0) < 1e-4):
            continue
        r0 = block[0:3]
        r1 = block[4:7]
        r2 = block[8:11]
        norms = (np.linalg.norm(r0), np.linalg.norm(r1), np.linalg.norm(r2))
        if any(abs(v - 1.0) > 1e-3 for v in norms):
            continue
        if (abs(float(np.dot(r0, r1))) > 1e-3 or abs(float(np.dot(r0, r2))) > 1e-3
                or abs(float(np.dot(r1, r2))) > 1e-3):
            continue
        tx, ty, tz = float(block[12]), float(block[13]), float(block[14])
        if not (X_MIN < tx < X_MAX and Z_MIN < tz < Z_MAX):
            continue
        hits.append((base + i * 4, tx, ty, tz, float(np.linalg.det(np.array([r0, r1, r2])))))

    print(f"\ncandidate camera matrices: {len(hits)}")
    for address, tx, ty, tz, det in hits[:20]:
        print(f"  0x{address:X}  module+{address - base:<9} "
              f"pos=({tx:10.2f},{ty:9.2f},{tz:10.2f})  det={det:+.4f}")

    if hits:
        import json
        out = Path(__file__).resolve().parent.parent / "work" / "camera_candidates.json"
        out.write_text(json.dumps([
            {"address": a, "module_offset": a - base, "x": x, "y": y, "z": z, "det": d}
            for a, x, y, z, d in hits
        ], indent=1), encoding="utf-8")
        print(f"\ncached -> {out}")
    return 0 if hits else 2


if __name__ == "__main__":
    raise SystemExit(main())
