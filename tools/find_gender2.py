import struct, zlib, sys
import numpy as np

BASE = 5

def unwrap(p):
    raw = open(p, 'rb').read()
    return zlib.decompressobj().decompress(raw[32:])

path = sys.argv[1]
d = unwrap(path)
words = np.frombuffer(d, dtype=np.uint32, count=(len(d) - BASE) // 4, offset=BASE)

def longest_run(mask, win=120):
    """Return (max density over `win`, start index) using a rolling sum."""
    if mask.sum() < win:
        return 0.0, 0
    c = np.cumsum(np.concatenate(([0], mask.astype(np.int32))))
    s = c[win:] - c[:-win]
    i = int(np.argmax(s))
    return float(s[i]) / win, i

best = []
for S in (24, 32, 40, 48, 56, 64, 80, 96, 128, 192):
    Sw = S // 4
    for p in range(Sw):
        for c in range(Sw):
            idx = p + c + np.arange(len(words) // Sw) * Sw
            idx = idx[idx < len(words)]
            if len(idx) < 200:
                continue
            vals = words[idx]
            for lim, tag in ((2, "<=2"), (3, "<=3"), (8, "<=8")):
                dens, st = longest_run(vals <= lim)
                if dens > 0.97:
                    best.append((dens, S, p * 4, c * 4, tag, int(idx[st])))

best.sort(reverse=True)
print("=== long runs of a 0/1/2-ish field ===")
seen = set()
for dens, S, phase, col, tag, first in best:
    key = (S, phase, col)
    if key in seen:
        continue
    seen.add(key)
    print("   dens=%.3f stride=%3d phase=%3d col=%3d %s  first_elem_rel=%d"
          % (dens, S, phase, col, tag, first * S))
    if len(seen) >= 10:
        break
if not best:
    print("   (none found)")
