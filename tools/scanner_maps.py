"""Follow the map-filename string pointers to the struct that owns them.

The scanner's map names sit in a string table; a C++ table of per-reserve records would
hold pointers to those strings, with the numeric fields right next to them. So: find the
virtual address of one map name, search the image for pointers to it, and dump whatever
surrounds each pointer as floats and integers.

Run:  python tools/scanner_maps.py
"""

from __future__ import annotations

import struct
from pathlib import Path

EXE = Path(
    r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 "
    r"2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\AnimalPopulationScanner.exe"
)


def sections(data: bytes) -> list[tuple[str, int, int, int, int]]:
    """(name, virtual address, virtual size, raw offset, raw size)"""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    table = pe + 24 + opt_size
    out = []
    for index in range(count):
        entry = table + index * 40
        name = data[entry: entry + 8].rstrip(b"\0").decode("latin-1")
        vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", data, entry + 8)
        out.append((name, va, vsize, raw_ptr, raw_size))
    return out


def offset_to_va(offset: int, secs) -> int | None:
    for _, va, vsize, raw_ptr, raw_size in secs:
        if raw_ptr <= offset < raw_ptr + raw_size:
            return va + (offset - raw_ptr)
    return None


def main() -> int:
    data = EXE.read_bytes()
    secs = sections(data)
    print("sections:", [s[0] for s in secs])

    for needle in (b"MapSRP_bw.png", b"MapHirsch_bw.png", b"data/Maps/MapSRP_bw.png"):
        offset = data.find(needle)
        if offset < 0:
            continue
        va = offset_to_va(offset, secs)
        print(f"\n{needle.decode():<28} file 0x{offset:X}  va 0x{va:X}")
        if va is None:
            continue
        packed = struct.pack("<Q", va)
        hits = []
        cursor = 0
        while True:
            found = data.find(packed, cursor)
            if found < 0:
                break
            hits.append(found)
            cursor = found + 1
        print(f"  pointeurs vers cette chaine: {len(hits)} -> {[hex(h) for h in hits[:6]]}")
        for hit in hits[:4]:
            start = max(0, hit - 64)
            print(f"  --- autour de 0x{hit:X} ---")
            for delta in range(0, 128, 8):
                position = start + delta
                if position < 0:
                    continue
                qword = struct.unpack_from("<Q", data, position)[0]
                as_float = struct.unpack_from("<f", data, position)[0]
                as_int = struct.unpack_from("<i", data, position)[0]
                mark = " <-- pointeur" if position == hit else ""
                note = ""
                if 500 < abs(as_float) < 40000:
                    note = f"  float={as_float:.1f}"
                if 100 < abs(as_int) < 40000:
                    note += f"  int={as_int}"
                print(f"    0x{position:06X}  q=0x{qword:016X}{note}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
