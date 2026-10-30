"""Build the definitive species table: hash -> (stringId, English name, icon, stat arrays)."""
import sys, struct, json, io
sys.path.insert(0, r'C:\Users\Maelo\Documents\mods\cotw-pop\tools')
from pe import PE
from mem import Mem
from nametable2 import collect, ARR, N, EXE

TABLE = 0x1400B0C80
COUNT = 0x87
RECSZ = 0x3C0

def english(pe, m):
    hits = sorted(collect(pe, m))
    cur = {}
    for va, idx, s in hits:
        cur[idx] = s
        if idx == N - 1:
            return {k: m.cstr(v, 200) for k, v in cur.items()}
    return {k: m.cstr(v, 200) for k, v in cur.items()}

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    pe = PE(EXE); m = Mem(pe)
    en = english(pe, m)
    print("### English string table (%d entries)" % len(en))
    for i in range(N):
        print("%3d  %r" % (i, en.get(i)))

if __name__ == '__main__':
    main()
