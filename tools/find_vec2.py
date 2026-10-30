import struct, zlib, sys
import numpy as np

BASE = 5

def unwrap(path):
    raw = open(path, 'rb').read()
    return zlib.decompressobj().decompress(raw[32:])

path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Maelo\Documents\Avalanche Studios\COTW\Saves\76561199084637132\animal_population_16"
d = unwrap(path)
n = len(d)
data = d

def f32(rel, o):
    return struct.unpack_from('<f', data, BASE + rel + o)[0]

results = []
for S in (64, 96, 128, 192):
    for phase in range(0, S, 4):
        for off in range(0, S - 7, 4):
            hits = 0
            tot = 0
            for i in range(400):
                rel = phase + i * S
                if rel + off + 8 > n - BASE:
                    break
                x = f32(rel, off)
                y = f32(rel, off + 4)
                tot += 1
                if abs(x) < 20000 and abs(y) < 20000 and (abs(x) > 0.01 or abs(y) > 0.01):
                    hits += 1
            if tot >= 300:
                results.append((hits / tot, hits, tot, S, phase, off))

results.sort(reverse=True)
print("=== best Vector2 candidates (hit%, hits, total, stride, phase, offset) ===")
for r in results[:15]:
    print("   %.3f  %3d/%3d  S=%3d phase=%3d off=%2d" % r)

if results:
    _, hits, tot, S, phase, off = results[0]
    print("\n=== sample of the winning array (S=%d phase=%d off=%d) ===" % (S, phase, off))
    shown = 0
    for i in range(400):
        rel = phase + i * S
        if rel + off + 8 > n - BASE:
            break
        x = f32(rel, off); y = f32(rel, off + 4)
        if abs(x) < 20000 and abs(y) < 20000 and (abs(x) > 0.01 or abs(y) > 0.01):
            print("   [%3d] rel=%-7d  X=%12.3f  Y=%12.3f" % (i, rel, x, y))
            shown += 1
            if shown >= 15:
                break
