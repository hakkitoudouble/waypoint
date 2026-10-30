"""Strict hunt for AnimalData_5-shaped records.

Learned the hard way: a zero-filled padding region satisfies almost any
"plausible value" test, because 0 is finite, in range and co-located with itself.
Every predicate here therefore requires a NON-degenerate value.

AnimalData_5 (32 bytes) should be:
    +0x00 u8 Gender | +0x04 f32 Weight | +0x08 f32 Score | +0x0C u8 feature flags
    +0x0D u8 IsScripted | +0x10 u32 seed | +0x14 u32 unknown | +0x18 f32 X | +0x1C f32 Y
"""

from __future__ import annotations

import math
import struct
import sys
import zlib

BASE = 5


def unwrap(path):
    raw = open(path, "rb").read()
    return zlib.decompressobj().decompress(raw[32:])


def main(path):
    d = unwrap(path)
    total = len(d) - BASE

    def u8(rel):
        return d[BASE + rel]

    def u32(rel):
        return struct.unpack_from("<I", d, BASE + rel)[0]

    def f32(rel):
        return struct.unpack_from("<f", d, BASE + rel)[0]

    print("document size:", total)

    records = []
    for rel in range(0, total - 32, 4):
        g = u8(rel)
        w = f32(rel + 4)
        s = f32(rel + 8)
        x = f32(rel + 24)
        y = f32(rel + 28)
        if g not in (0, 1):
            continue
        if not (math.isfinite(w) and 0.5 < w < 2500.0):
            continue
        if not (math.isfinite(s) and 0.0 <= s < 5000.0):
            continue
        if not (math.isfinite(x) and math.isfinite(y) and abs(x) < 20000 and abs(y) < 20000):
            continue
        # the anti-zero clause: a real animal has a real position or a real weight
        if abs(x) < 0.01 and abs(y) < 0.01:
            continue
        records.append((rel, g, w, s, x, y))

    print("strict hits:", len(records))
    if not records:
        return

    offsets = [r[0] for r in records]
    from collections import Counter
    mods = Counter(o % 32 for o in offsets)
    print("hit offset mod 32:", mods.most_common())
    print("hit offset mod 16:", Counter(o % 16 for o in offsets).most_common())

    print("\nfirst 20 hits:")
    for rel, g, w, s, x, y in records[:20]:
        print("   @%-7d g=%d w=%9.3f s=%9.3f x=%10.3f y=%10.3f" % (rel, g, w, s, x, y))


if __name__ == "__main__":
    main(sys.argv[1])
