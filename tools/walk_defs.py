"""Walk the ADF v4 definitions region using the field-slot model established in
notes/adf-findings.md, and report the layout of every definition.

Model (validated on 3 files):
  structure definition: 48-byte header, then field slots of 32 bytes with the
  field triple (typeHash, size, offset) at slot+0/+4/+8, and the first slot at +48.
  Total length = 72 + 32*(nfields-1).
  array definition: 40 bytes.
"""

import struct
import sys
import zlib

BASE = 5
HDR = 48
SLOT = 32

NATIVE = {
    0x0CA2821D: "u8", 0x580D0A62: "i8", 0x86D152BD: "u16", 0xD13FCF93: "i16",
    0x075E4E4F: "u32", 0x192FE633: "i32", 0x7515A207: "f32", 0x34B4DBF8: "str",
}


def unwrap(path):
    raw = open(path, "rb").read()
    return zlib.decompressobj().decompress(raw[32:])


def u32(d, rel):
    return struct.unpack_from("<I", d, BASE + rel)[0]


def parse_structure(d, start, struct_size, limit):
    """Read field slots while they stay sane, return (fields, end_offset)."""
    fields = []
    prev_off = -1
    slot = start + HDR
    while slot + 12 <= limit:
        th = u32(d, slot)
        size = u32(d, slot + 4)
        off = u32(d, slot + 8)
        if size > struct_size or off + size > struct_size or off < prev_off:
            break
        fields.append({"slot": slot, "type_hash": th, "size": size, "offset": off})
        prev_off = off
        slot += SLOT
    length = 72 + SLOT * (len(fields) - 1) if fields else HDR
    return fields, start + length


def walk(d, def_off, def_cnt, names_off):
    out = []
    rel = def_off
    for i in range(def_cnt):
        if rel + 16 > names_off:
            out.append({"index": i, "error": "ran past defs region", "at": rel})
            break
        typ = u32(d, rel)
        size = u32(d, rel + 4)
        th = u32(d, rel + 12)
        if typ == 1:
            fields, end = parse_structure(d, rel, size, names_off)
            out.append({"index": i, "at": rel, "type": typ, "size": size,
                        "type_hash": th, "fields": fields, "len": end - rel})
            rel = end
        elif typ == 3:
            out.append({"index": i, "at": rel, "type": typ, "size": size,
                        "type_hash": th, "len": 40})
            rel += 40
        else:
            out.append({"index": i, "at": rel, "type": typ, "size": size,
                        "type_hash": th, "len": None})
            break
    return out, rel


def main(path):
    d = unwrap(path)
    def_off = u32(d, 0x14)
    def_cnt = u32(d, 0x20)
    names_off = u32(d, 0x24)
    print("defs [%d..%d] size=%d count=%d" % (def_off, names_off, names_off - def_off, def_cnt))

    defs, end = walk(d, def_off, def_cnt, names_off)
    for e in defs:
        if "error" in e:
            print("  !! %s at %d" % (e["error"], e["at"]))
            continue
        if e["type"] == 1:
            print("  #%-2d @%-6d STRUCT size=%-4d hash=%08X fields=%-2d len=%-4d"
                  % (e["index"], e["at"], e["size"], e["type_hash"],
                     len(e["fields"]), e["len"]))
            for f in e["fields"]:
                nm = NATIVE.get(f["type_hash"], "%08X" % f["type_hash"])
                print("        +0x%02X  %-8s size=%-3d" % (f["offset"], nm, f["size"]))
        else:
            print("  #%-2d @%-6d ARRAY  size=%-4d hash=%08X len=%s"
                  % (e["index"], e["at"], e["size"], e["type_hash"], e["len"]))
    print("\nended at %d, names_off=%d, delta=%d" % (end, names_off, names_off - end))


if __name__ == "__main__":
    main(sys.argv[1])
