"""Extract the scanner's per-species fur tables from `.data`.

Layout found by inspection and confirmed by the weights summing to the block header:

    fur table array   VA 0x1400CF170 .. 0x1400EE4F0, stride 0x1F0 (496 bytes)
    block header      0x10 bytes:  char* speciesRecord; u32 slot; u32 totalWeight
    block entry       0x18 bytes:  u32 bitIndex; u32 0; char* furName; u32 stringId; u32 weight

The `char*` fields are absolute 64-bit pointers (present in the file, with .reloc entries),
not RVAs. `bitIndex` gaps mean the block only lists the furs that species uses.

Run:  python tools/fur_extract.py
"""

from __future__ import annotations

import json
import struct

import fur_pe
import fur_ids

ARRAY_BASE_VA = 0x1400CF170
ARRAY_HI_VA = 0x1400EE600
BLOCK_SIZE = 0x1F0
HEADER_SIZE = 0x10
ENTRY_SIZE = 0x18
MAX_ENTRIES = (BLOCK_SIZE - HEADER_SIZE) // ENTRY_SIZE

DATA_LO_VA = 0x1400B0000


def read_species_records(data: bytes, secs, table: dict[int, str]) -> dict[int, dict]:
    records: dict[int, dict] = {}
    for va in range(DATA_LO_VA, 0x1400CF140, 4):
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
    records = read_species_records(data, secs, table)
    print(f"species records: {len(records)}")

    blocks = []
    va = ARRAY_BASE_VA
    index = 0
    while va < ARRAY_HI_VA:
        offset = fur_pe.va_to_off(va, secs)
        if offset is None:
            break
        species_ptr, slot, total = struct.unpack_from("<QII", data, offset)
        # trailing region: stop when the block no longer looks like a header
        if species_ptr not in records or slot > 8:
            print(f"  block {index} @0x{va:X} not a valid header "
                  f"(ptr 0x{species_ptr:X}, slot {slot}) -> stop")
            break
        entries = []
        weight_sum = 0
        for position in range(MAX_ENTRIES):
            entry_offset = offset + HEADER_SIZE + position * ENTRY_SIZE
            bit, pad, name_ptr, string_id, weight = struct.unpack_from("<IIQII", data, entry_offset)
            if not (name_ptr or bit or string_id or weight):
                break
            name = fur_pe.cstring(data, secs, name_ptr)
            if name is None:
                name = None
            weight_sum += weight
            entries.append({
                "bitIndex": bit,
                "name": name,
                "stringId": string_id,
                "weight": weight,
                "offset": f"0x{entry_offset:X}",
                "file": f"0x{entry_offset:X}",
            })
        blocks.append({
            "index": index,
            "blockVa": va,
            "species": records[species_ptr]["name"],
            "speciesStringId": records[species_ptr]["stringId"],
            "speciesRecordVa": species_ptr,
            "slot": slot,
            "totalWeight": total,
            "weightSum": weight_sum,
            "entries": entries,
        })
        va += BLOCK_SIZE
        index += 1

    good = [b for b in blocks if b["weightSum"] == b["totalWeight"]]
    print(f"blocks parsed: {len(blocks)}, weight-sum matches header: {len(good)}")
    bad = [b for b in blocks if b["weightSum"] != b["totalWeight"]]
    for block in bad[:10]:
        print(f"  MISMATCH block {block['index']} @0x{block['blockVa']:X} "
              f"{block['species']}: total {block['totalWeight']} vs sum {block['weightSum']}")

    # sanity: stringId must agree with the literal
    mismatched = 0
    for block in blocks:
        for entry in block["entries"]:
            expected = table.get(entry["stringId"])
            if expected is not None and entry["name"] is not None and \
                    expected.strip() != entry["name"].strip():
                mismatched += 1
    print(f"entries whose stringId disagrees with its char*: {mismatched}")

    with open(r"..\work\scanner_fur_tables_raw.json", "w", encoding="utf-8") as handle:
        json.dump({"arrayBaseVa": f"0x{ARRAY_BASE_VA:X}", "blockSize": BLOCK_SIZE,
                   "blocks": blocks}, handle, indent=1, ensure_ascii=False)
    print("written ..\\work\\scanner_fur_tables_raw.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
