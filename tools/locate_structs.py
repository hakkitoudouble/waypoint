import struct, zlib, sys
import numpy as np

BASE = 5
S = 96

def unwrap(path):
    raw = open(path, 'rb').read()
    return zlib.decompressobj().decompress(raw[32:])

path = sys.argv[1]
d = unwrap(path)
body = np.frombuffer(d, dtype=np.uint8)
n = len(body) - BASE

# Ignore pure-zero padding: only score windows with real content.
head = body[:n - S].astype(np.int32)
tail = body[S:n].astype(np.int32)
nonzero = ((head != 0) | (tail != 0)).astype(np.float32)
match = ((head == tail) & (nonzero > 0)).astype(np.float32)

W = S * 8  # window of 8 structs
kernel = np.ones(W, dtype=np.float32)
nz_dens = np.convolve(nonzero, kernel, mode='valid') / W
mt_dens = np.convolve(match, kernel, mode='valid') / W
# real arrays: plenty of non-zero bytes AND high match among those
dens = np.where(nz_dens > 0.15, mt_dens * nz_dens, 0.0)

# top non-overlapping peaks
order = np.argsort(dens)[::-1]
peaks = []
for idx in order:
    if all(abs(int(idx) - p) > W for p in peaks):
        peaks.append(int(idx))
    if len(peaks) >= 6:
        break

print("file:", path.split('\\')[-1], " rel size:", n)
print("\n=== densest periodic windows (stride %d) ===" % S)
for p in peaks:
    print("   start_rel=%-7d density=%.3f" % (p, dens[p]))

# take the densest window, align start to a struct boundary
best = peaks[0]
start = best
print("\n=== 6 structs @ rel %d, stride %d, interpreted as 24 x f32 ===" % (start, S))
for i in range(6):
    rel = start + i * S
    if rel + S > n:
        break
    vals = struct.unpack_from('<24f', d, BASE + rel)
    line = " ".join("%9.3f" % v if abs(v) < 1e7 else "%9.3g" % v for v in vals)
    print("  #%d rel=%-7d %s" % (i, rel, line))

print("\n=== same, as 24 x u32 ===")
for i in range(6):
    rel = start + i * S
    if rel + S > n:
        break
    vals = struct.unpack_from('<24I', d, BASE + rel)
    print("  #%d %s" % (i, " ".join("%08X" % v for v in vals)))
