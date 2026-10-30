"""Locate the per-species records in `.data` and the fur-table array that points at them.

Step 1: a species record starts with `i32 stringId; i32 0; char* iconPath`. Scan `.data`
        for that shape (stringId in the localization range, icon literal readable) and
        derive the array base/stride from the addresses found.
Step 2: the fur array sits later in `.data`: one fixed-size block per species, whose first
        qword is a pointer to a species record. Verify the candidate start/stride against
        the pointer set, then dump blocks.

Run:  python tools/fur_records.py
"""

from __future__ import annotations

import json
import struct

import fur_pe
import fur_ids

DATA_LO_VA = 0x1400B0000
DATA_HI_VA = 0x1400EE600


def scan_records(data: bytes, secs, table: dict[int, str]) -> dict[int, dict]:
    records: dict[int, dict] = {}
    for va in range(DATA_LO_VA, DATA_HI_VA - 16, 4):
        offset = fur_pe.va_to_off(va, secs)
        if offset is None:
            continue
        string_id, pad = struct.unpack_from("<ii", data, offset)
        if not (0 <= string_id < 359) or pad != 0:
            continue
        icon_ptr = struct.unpack_from("<Q", data, offset + 8)[0]
        icon = fur_pe.cstring(data, secs, icon_ptr)
        if icon is None or not icon.startswith("data/Icons/"):
            continue
        records[va] = {"stringId": string_id, "name": table.get(string_id), "icon": icon}
    return records


def main() -> int:
    data = fur_pe.load()
    secs = fur_pe.sections(data)
    table = fur_ids.recover(data, secs)
    records = scan_records(data, secs, table)
    print(f"species-record candidates: {len(records)}")
    addresses = sorted(records)
    print(f"  first 0x{addresses[0]:X} last 0x{addresses[-1]:X}")
    deltas: dict[int, int] = {}
    for a, b in zip(addresses, addresses[1:]):
        deltas[b - a] = deltas.get(b - a, 0) + 1
    top = sorted(deltas.items(), key=lambda kv: -kv[1])[:6]
    print("  address deltas (delta: count):", [(hex(d), c) for d, c in top])
    for va in addresses[:6]:
        print(f"   0x{va:X} id={records[va]['stringId']} {records[va]['name']!r} {records[va]['icon']}")
    print("  ...")
    for va in addresses[-6:]:
        print(f"   0x{va:X} id={records[va]['stringId']} {records[va]['name']!r} {records[va]['icon']}")

    with open(r"..\work\scanner_species_records.json", "w", encoding="utf-8") as handle:
        json.dump({f"0x{va:X}": records[va] for va in addresses}, handle,
                  indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
