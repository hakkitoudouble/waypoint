import struct, zlib, sys

BASE = 5

def unwrap(p):
    raw = open(p, "rb").read()
    return zlib.decompressobj().decompress(raw[32:])

def u32(d, rel):
    return struct.unpack_from("<I", d, BASE + rel)[0]

s = r"C:\Users\Maelo\Documents\Avalanche Studios\COTW\Saves\76561199084637132"
d = unwrap(s + r"\animal_population_16")

def_off, def_cnt, names_off = u32(d, 0x14), u32(d, 0x20), u32(d, 0x24)
print("defs [%d..%d] size=%d count=%d" % (def_off, names_off, names_off - def_off, def_cnt))

# Structure defs start with 1 and a plausible size; array defs with 3.
cands = []
for rel in range(def_off, names_off - 12):
    v = u32(d, rel)
    if v in (1, 3, 5):
        size = u32(d, rel + 4)
        h = u32(d, rel + 12)
        plausible = (size < 4096) and (h > 0x10000)
        cands.append((rel, v, size, h, plausible))

print("\n=== candidate definition starts ===")
prev = None
for rel, v, size, h, ok in cands:
    if not ok:
        continue
    gap = "" if prev is None else "   gap=+%d" % (rel - prev)
    print("   @%-6d (+%4d)  type=%d size=%-5d typeHash=%08X%s"
          % (rel, rel - def_off, v, size, h, gap))
    prev = rel

# How far does the root def extend if fields are 32 bytes each?
print("\n=== root def field slots (32 B each, first at +48) ===")
for i in range(8):
    rel = def_off + 48 + i * 32
    if rel + 16 > names_off:
        print("   field %d @%d  (past defs region)" % (i, rel))
        break
    print("   field %d @%-6d (+%3d)  %08X %08X %08X %08X"
          % (i, rel, rel - def_off, u32(d, rel), u32(d, rel + 4),
             u32(d, rel + 8), u32(d, rel + 12)))
