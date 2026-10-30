import struct, zlib, sys, os

BASE = 5  # ADF document starts after a 5-byte wrapper prefix

def unwrap(raw):
    usize = struct.unpack_from('<I', raw, 8)[0]
    out = zlib.decompressobj().decompress(raw[32:])
    assert len(out) == usize
    return out

def load(path):
    return unwrap(open(path, 'rb').read())

def hdr(d):
    u = lambda rel: struct.unpack_from('<I', d, BASE + rel)[0]
    return dict(magic=d[BASE:BASE+4], version=u(0x04), unk08=u(0x08),
                data_off=u(0x0C), data_cnt=u(0x10),
                def_off=u(0x14), unk18=u(0x18), unk1C=u(0x1C),
                def_cnt=u(0x20), names_off=u(0x24), size=u(0x28),
                unk2C=u(0x2C), unk30=u(0x30))

def show(path):
    d = load(path)
    h = hdr(d)
    print("=" * 70)
    print(os.path.basename(path), "size_rel=%d actual=%d" % (h['size'], len(d) - BASE))
    for k, v in h.items():
        print("   %-9s %s" % (k, ("%d (0x%X)" % (v, v)) if isinstance(v, int) else v))

    def region(name, a, b):
        print("\n-- %s rel[%d:%d] (%d bytes) --" % (name, a, b, b - a))
        for rel in range(a, b, 16):
            chunk = d[BASE+rel:BASE+min(rel+16, b)]
            print("  %04X  %-47s  %s" % (rel, chunk.hex(' '),
                  ''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk)))

    region("entries", h['data_off'], h['def_off'])
    region("definitions", h['def_off'], h['names_off'])
    region("names", h['names_off'], h['size'])

    print("\n-- entries as 6 u32 --")
    for i in range(h['data_cnt']):
        rel = h['data_off'] + i * 24
        vals = struct.unpack_from('<6I', d, BASE + rel)
        print("  #%d rel=%4d  NameHash=%08X TypeHash=%08X Off=%d Size=%d z=%08X %08X"
              % (i, rel, vals[0], vals[1], vals[2], vals[3], vals[4], vals[5]))

    print("\n-- definitions region as u32 --")
    a, b = h['def_off'], h['names_off']
    for rel in range(a, b, 16):
        vals = []
        for k in range(0, 16, 4):
            if rel + k + 4 <= b:
                vals.append("%08X" % struct.unpack_from('<I', d, BASE + rel + k)[0])
        print("  %4d  %s" % (rel, " ".join(vals)))

for p in sys.argv[1:]:
    show(p)
