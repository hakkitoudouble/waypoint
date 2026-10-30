"""Shared PE helpers for the fur-table extraction.

Sections, offset<->VA conversion, string search. Nothing here guesses: everything is
read straight out of the file bytes.

Run `python tools/fur_pe.py` for a section dump + resource-directory overview.
"""

from __future__ import annotations

import struct
from pathlib import Path

EXE = Path(
    r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 "
    r"2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\AnimalPopulationScanner.exe"
)
IMAGE_BASE = 0x140000000


def load() -> bytes:
    return EXE.read_bytes()


def sections(data: bytes) -> list[dict]:
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    table = pe + 24 + opt_size
    out = []
    for index in range(count):
        entry = table + index * 40
        name = data[entry: entry + 8].rstrip(b"\0").decode("latin-1")
        vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", data, entry + 8)
        out.append({"name": name, "rva": va, "vsize": vsize,
                    "raw": raw_ptr, "raw_size": raw_size,
                    "va": IMAGE_BASE + va})
    return out


def va_to_off(va: int, secs) -> int | None:
    for section in secs:
        start = IMAGE_BASE + section["rva"]
        if start <= va < start + max(section["vsize"], section["raw_size"]):
            delta = va - start
            if delta >= section["raw_size"]:
                return None  # zero-filled tail
            return section["raw"] + delta
    return None


def off_to_va(offset: int, secs) -> int | None:
    for section in secs:
        if section["raw"] <= offset < section["raw"] + section["raw_size"]:
            return IMAGE_BASE + section["rva"] + (offset - section["raw"])
    return None


def section_of(va: int, secs) -> str:
    for section in secs:
        start = IMAGE_BASE + section["rva"]
        if start <= va < start + max(section["vsize"], section["raw_size"]):
            return section["name"]
    return "?"


def cstring(data: bytes, secs, va: int, limit: int = 96) -> str | None:
    offset = va_to_off(va, secs)
    if offset is None:
        return None
    end = data.find(b"\0", offset, offset + limit)
    if end < 0:
        return None
    raw = data[offset:end]
    if not raw or any(c < 0x20 for c in raw):
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def main() -> int:
    data = load()
    secs = sections(data)
    print(f"file size 0x{len(data):X} ({len(data)})")
    for section in secs:
        print(f"  {section['name']:<8} va 0x{section['va']:X} rva 0x{section['rva']:X} "
              f"vsize 0x{section['vsize']:X} raw 0x{section['raw']:X} rawsize 0x{section['raw_size']:X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
