import struct, zlib, sys
import numpy as np

BASE = 5

def unwrap(path):
    raw = open(path, 'rb').read()
    return zlib.decompressobj().decompress(raw[32:])

def find_period(d):
    """Find the size S of a repeating struct: data[i] == data[i+S] for many columns."""
    body = np.frombuffer(d, dtype=np.uint8)
    best = []
    for S in range(8, 513, 4):
        a = body[64:len(body) - S]
        b = body[64 + S:]
        if len(a) < 1000:
            continue
        m = float(np.mean(a == b))
        best.append((m, S))
    best.sort(reverse=True)
    return best

if __name__ == '__main__':
    path = sys.argv[1]
    d = unwrap(path)
    body = np.frombuffer(d, dtype=np.uint8)
    print("file:", path, "rel size:", len(d) - BASE)
    print("\n=== top autocorrelation periods (S, match fraction) ===")
    for m, S in find_period(d)[:15]:
        print("   S=%4d   match=%.4f" % (S, m))
