import struct, zlib, sys, os

def unwrap(raw):
    """SAVE container -> zlib -> payload"""
    if raw[:4] != b'SAVE':
        raise ValueError("not a SAVE container")
    usize = struct.unpack_from('<I', raw, 8)[0]
    off = 32
    if raw[16:20] != b'COMP':
        raise ValueError("no COMP block at 16")
    d = zlib.decompressobj()
    out = d.decompress(raw[off:])
    return out, usize

def dump(path):
    raw = open(path, 'rb').read()
    print("=" * 78)
    print("FILE:", os.path.basename(path), "disk=%d" % len(raw))
    print("raw header:", raw[:40].hex(' '))
    data, usize = unwrap(raw)
    print("decompressed=%d (expected %d) %s" % (len(data), usize, "OK" if len(data) == usize else "MISMATCH"))
    print("-" * 78)
    for o in range(0, len(data), 16):
        row = data[o:o+16]
        print("%06X  %-47s  %s" % (o, row.hex(' '), ''.join(chr(c) if 32 <= c < 127 else '.' for c in row)))
    return data

if __name__ == '__main__':
    for p in sys.argv[1:]:
        dump(p)
