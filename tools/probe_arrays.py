import struct, zlib, sys

BASE = 5

def unwrap(path):
    raw = open(path, 'rb').read()
    return zlib.decompressobj().decompress(raw[32:])

def u32(d, rel):
    return struct.unpack_from('<I', d, BASE + rel)[0]

s = r"C:\Users\Maelo\Documents\Avalanche Studios\COTW\Saves\76561199084637132"

# ---------- settings: root struct ----------
d = unwrap(s + r"\settings_adf")
data_off, data_cnt = u32(d, 0x0C), u32(d, 0x10)
print("settings: data_off=%d data_cnt=%d" % (data_off, data_cnt))
for i in range(data_cnt):
    rel = data_off + i * 24
    nh, th, off, size, z1, z2 = struct.unpack_from('<6I', d, BASE + rel)
    print("  instance #%d: NameHash=%08X TypeHash=%08X Offset=%d Size=%d pad=%08X %08X"
          % (i, nh, th, off, size, z1, z2))

print("\n--- root struct candidate rel 1088..1136 as u32 ---")
for rel in range(1088, 1136, 4):
    print("   rel %5d  %08X %12d" % (rel, u32(d, rel), u32(d, rel)))

# ---------- population: root instance ----------
d2 = unwrap(s + r"\animal_population_16")
d_off, d_cnt = u32(d2, 0x0C), u32(d2, 0x10)
print("\npopulation: instance table at rel %d, count %d" % (d_off, d_cnt))
for i in range(min(d_cnt, 6)):
    rel = d_off + i * 24
    nh, th, off, size, z1, z2 = struct.unpack_from('<6I', d2, BASE + rel)
    print("  instance #%2d: NameHash=%08X TypeHash=%08X Offset=%7d Size=%d"
          % (i, nh, th, off, size))

print("\n--- first 12 u32 of the printed instance[0] Offset ---")
nh, th, off0, size0, z1, z2 = struct.unpack_from('<6I', d2, BASE + d_off)
for k in range(12):
    rel = off0 + k * 4
    print("   +%3d  rel %7d  %08X %12d" % (k * 4, rel, u32(d2, rel), u32(d2, rel)))
