import struct, zlib, sys

BASE = 5

NATIVE = {
    0x0CA2821D: "UInt8", 0x580D0A62: "Int8",
    0x86D152BD: "UInt16", 0xD13FCF93: "Int16",
    0x075E4E4F: "UInt32", 0x192FE633: "Int32",
    0x7515A207: "Float", 0x34B4DBF8: "String",
}

def unwrap(p):
    raw = open(p, "rb").read()
    return zlib.decompressobj().decompress(raw[32:])

def u32(d, rel):
    return struct.unpack_from("<I", d, BASE + rel)[0]

s = r"C:\Users\Maelo\Documents\Avalanche Studios\COTW\Saves\76561199084637132"

for name in ("achievements_adf", "settings_adf", "animal_population_16"):
    d = unwrap(s + "\\" + name)
    def_off, def_cnt = u32(d, 0x14), u32(d, 0x20)
    names_off = u32(d, 0x24)

    hits = []
    for rel in range(def_off, names_off - 3):
        v = u32(d, rel)
        if v in NATIVE:
            hits.append((rel, NATIVE[v]))

    print("=" * 70)
    print("%s  defs[%d..%d] n=%d" % (name, def_off, names_off, def_cnt))
    last = None
    for rel, nm in hits:
        gap = "" if last is None else "  gap=+%d" % (rel - last)
        print("   @%-6d (+%4d from def_off)  %-7s%s" % (rel, rel - def_off, nm, gap))
        last = rel
    if not hits:
        print("   (no native hashes)")
