import struct, zlib, sys
import numpy as np

BASE = 5

def unwrap(p):
    raw = open(p, 'rb').read()
    return zlib.decompressobj().decompress(raw[32:])

path = sys.argv[1]
d = unwrap(path)
n = len(d) - BASE
body = np.frombuffer(d, dtype=np.uint8)

def u32_at(rel):
    return np.frombuffer(d, dtype=np.uint32, count=1, offset=BASE + rel)[0]

# u32 view of the whole payload, rel 0 maps to element 0 of this array
words = np.frombuffer(d, dtype=np.uint32, count=(len(d) - BASE) // 4, offset=BASE)

print("word count:", len(words))

best = []
for S in (48, 64, 96, 128, 192):
    Sw = S // 4
    for p in range(0, Sw):
        for c in range(0, Sw):
            idx = p + c + np.arange(1500) * Sw
            idx = idx[idx < len(words)]
            if len(idx) < 800:
                continue
            vals = words[idx]
            frac = np.mean(vals <= 2)
            if frac > 0.90:
                best.append((float(frac), S, p * 4, c * 4, len(idx)))

best.sort(reverse=True)
print("\n=== columns that are almost always 0/1/2 (Gender-like) ===")
for frac, S, phase, col, cnt in best[:12]:
    print("   frac=%.3f  stride=%3d  phase=%3d  col=%3d  n=%d" % (frac, S, phase, col, cnt))

if best:
    frac, S, phase, col, cnt = best[0]
    print("\n=== sample of that column (stride=%d phase=%d col=%d) ===" % (S, phase, col))
    Sw = S // 4
    base_rel = phase + col
    for i in range(20):
        rel = base_rel + i * S
        try:
            v = struct.unpack_from('<I', d, BASE + rel)[0]
        except Exception:
            break
        print("   [%3d] rel %6d  %10d" % (i, rel, v))
