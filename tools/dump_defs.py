import struct, zlib, sys, os

BASE = 5

def unwrap(path):
    raw = open(path, 'rb').read()
    return zlib.decompressobj().decompress(raw[32:])

def u32(d, rel):
    return struct.unpack_from('<I', d, BASE + rel)[0]

def analyze(path):
    d = unwrap(path)
    def_off = u32(d, 0x14)
    def_cnt = u32(d, 0x20)
    names_off = u32(d, 0x24)
    size = u32(d, 0x28)
    print("=" * 74)
    print("%s  defs[%d..%d]=%d bytes, count=%d -> %.2f B/def"
          % (os.path.basename(path), def_off, names_off, names_off - def_off,
             def_cnt, (names_off - def_off) / max(def_cnt, 1)))
    print("-" * 74)
    for rel in range(def_off, names_off, 4):
        v = u32(d, rel)
        tag = ""
        if 1 <= v <= 5:
            tag = "  <- small/type?"
        elif 0x10000 <= v <= 0xFFFFFFFF:
            tag = "  <-- HASH-LIKE"
        print("  %5d (0x%03X)  %08X %10d%s" % (rel, rel, v, v, tag))

for p in sys.argv[1:]:
    analyze(p)
