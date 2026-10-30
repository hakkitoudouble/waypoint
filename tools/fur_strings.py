"""Dump the fur-name string blob and look for anything pointing at it.

Prints the raw blob around the fur vocabulary (NAMED/PADDED strings), then scans the
whole image for
  * 8-byte absolute pointers into the blob,
  * 4-byte RVAs into the blob,
and dumps the neighbourhood of every hit.

Run:  python tools/fur_strings.py
"""

from __future__ import annotations

import struct

import fur_pe

BLOB_LO = 0x14008E000
BLOB_HI = 0x140090800


def main() -> int:
    data = fur_pe.load()
    secs = fur_pe.sections(data)

    lo = fur_pe.va_to_off(BLOB_LO, secs)
    hi = fur_pe.va_to_off(BLOB_HI, secs)
    print(f"blob dump VA 0x{BLOB_LO:X}..0x{BLOB_HI:X} (file 0x{lo:X}..0x{hi:X})")
    cursor = lo
    while cursor < hi:
        end = data.find(b"\0", cursor)
        if end < 0:
            break
        raw = data[cursor:end]
        text = "".join(chr(c) if 32 <= c < 127 else "." for c in raw)
        print(f"  0x{cursor:06X}  va 0x{fur_pe.off_to_va(cursor, secs) or 0:011X}  len={len(raw):<3} {text!r}")
        cursor = end + 1
        # skip alignment padding
        while cursor < hi and data[cursor] == 0:
            cursor += 1

    print("\n--- pointers / RVAs into the blob ---")
    blob_lo_file = lo
    blob_hi_file = hi
    # collect string VAs inside the blob for reference
    names: dict[int, str] = {}
    cursor = lo
    while cursor < hi:
        end = data.find(b"\0", cursor)
        if end <= cursor:
            break
        raw = data[cursor:end]
        if raw and all(32 <= c < 127 for c in raw):
            va = fur_pe.off_to_va(cursor, secs)
            names[va] = raw.decode()
        cursor = end + 1

    qhits = []
    for offset in range(0, len(data) - 8):
        value = struct.unpack_from("<Q", data, offset)[0]
        if BLOB_LO <= value < BLOB_HI:
            qhits.append((offset, value))
    print(f"qword pointers into blob: {len(qhits)}")
    for offset, value in qhits[:40]:
        sec = fur_pe.section_of(fur_pe.off_to_va(offset, secs) or 0, secs)
        print(f"  0x{offset:06X} ({sec}) -> 0x{value:X} {names.get(value, '?')!r}")

    dhits = []
    for offset in range(0, len(data) - 4):
        value = struct.unpack_from("<I", data, offset)[0]
        if 0x8E000 <= value < 0x90800:
            dhits.append((offset, value))
    print(f"\ndword RVAs into blob RVA 0x8E000..0x90800: {len(dhits)}")
    for offset, value in dhits[:60]:
        sec = fur_pe.section_of(fur_pe.off_to_va(offset, secs) or 0, secs)
        target_va = fur_pe.IMAGE_BASE + value
        print(f"  0x{offset:06X} ({sec}) rva 0x{value:X} va 0x{target_va:X} "
              f"{names.get(target_va, '?')!r}")

    print(f"\ndistinct strings in blob: {len(names)}")
    print(f"blob file range 0x{blob_lo_file:X}..0x{blob_hi_file:X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
