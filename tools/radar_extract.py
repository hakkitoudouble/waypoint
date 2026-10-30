"""Extract the Python code objects from the PyInstaller bundle of AnimalRadar.

The tool ships as a PyInstaller one-file/one-dir bundle built with CPython 3.12 — the
same version this project runs on, so we can unmarshal its code objects and
disassemble them without a third-party decompiler.

This is for understanding the technique (which pointer chain, which offsets, which
fallbacks), not for copying their code.

Run:  python tools/radar_extract.py <bundle.exe> [outdir]
"""

from __future__ import annotations

import marshal
import struct
import sys
import zlib
from pathlib import Path

MAGIC = b"MEI\014\013\012\013\016"
PYZ_MAGIC = b"PYZ\0"


def find_cookie(data: bytes) -> int:
    return data.rfind(MAGIC)


def parse_carchive(data: bytes) -> list[dict]:
    """Return the archive table of contents."""
    pos = find_cookie(data)
    if pos < 0:
        raise SystemExit("FAIL: PyInstaller cookie not found")
    # cookie: magic(8) pkgLen(u32) tocOff(u32) tocLen(u32) pyver(u32) pylib(64)
    pkg_len, toc_off, toc_len, py_ver = struct.unpack_from("!IIII", data, pos + 8)
    base = pos + 8 + 24 + 64  # cookie size counted backwards from the magic
    start = pos - toc_len
    toc: list[dict] = []
    cursor = start
    end = start + toc_len
    while cursor < end:
        entry_len = struct.unpack_from("!i", data, cursor)[0]
        if entry_len <= 0:
            break
        offset, comp_len, uncomp_len = struct.unpack_from("!III", data, cursor + 4)
        compress_flag, type_code = struct.unpack_from("!Bc", data, cursor + 16)
        name_raw = data[cursor + 18: cursor + entry_len]
        name = name_raw.split(b"\0")[0].decode("utf-8", "replace")
        toc.append({
            "name": name,
            "offset": offset,
            "compressed": comp_len,
            "uncompressed": uncomp_len,
            "flag": compress_flag,
            "type": type_code.decode("latin-1"),
        })
        cursor += entry_len
    return toc


def read_entry(data: bytes, entry: dict) -> bytes:
    blob = data[entry["offset"]: entry["offset"] + entry["compressed"]]
    if entry["flag"]:
        blob = zlib.decompress(blob)
    return blob


def parse_pyz(blob: bytes) -> dict[str, tuple[int, int, int]]:
    # PyInstaller PYZ header: 4-byte .pyc magic, then b"PYZ\0", then u32 BE TOC offset
    if blob[4:8] != PYZ_MAGIC:
        raise SystemExit(f"FAIL: not a PYZ archive (prefix {blob[:12]!r})")
    toc_offset = struct.unpack_from("!I", blob, 8)[0]
    return marshal.loads(blob[toc_offset:])


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: radar_extract.py <bundle.exe> [outdir]")
        return 1
    exe = Path(sys.argv[1])
    outdir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("work/radar")
    outdir.mkdir(parents=True, exist_ok=True)

    data = exe.read_bytes()
    print(f"bundle: {exe.name} ({len(data) / 1024 / 1024:.1f} MiB)")
    toc = parse_carchive(data)
    print(f"archive entries: {len(toc)}")
    for entry in toc[:12]:
        print(f"   {entry['type']}  {entry['name']:<40} {entry['uncompressed']:>9}")

    pyz = next((e for e in toc if e["name"].endswith(".pyz")), None)
    if not pyz:
        print("FAIL: no PYZ entry")
        return 2
    modules = parse_pyz(read_entry(data, pyz))
    print(f"\nPYZ modules: {len(modules)}")
    names = sorted(modules)
    interesting = [n for n in names if not n.startswith(("encodings", "importlib", "collections",
                                                         "email", "json", "xml", "urllib",
                                                         "http", "unittest", "logging"))]
    print("non-stdlib modules:")
    for name in interesting:
        print(f"   {name}")

    (outdir / "modules.txt").write_text("\n".join(names), encoding="utf-8")
    print(f"\nmodule list -> {outdir / 'modules.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
