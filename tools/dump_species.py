import sys, struct, json
sys.path.insert(0, r'C:\Users\Maelo\Documents\mods\cotw-pop\tools')
from pe import PE
from mem import Mem

EXE = r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\AnimalPopulationScanner.exe"
TABLE = 0x1400B0C80
COUNT = 0x87

def load():
    pe = PE(EXE); m = Mem(pe)
    return pe, m

def entries(pe, m):
    out = []
    for i in range(COUNT):
        va = TABLE + 16 * i
        key = m.u32(va); pad = m.u32(va + 4); ptr = m.u64(va + 8)
        out.append((i, key, pad, ptr))
    return out

def main():
    pe, m = load()
    es = entries(pe, m)
    ptrs = sorted(set(p for _, _, _, p in es))
    print("unique record ptrs:", len(ptrs))
    print("gaps between consecutive record ptrs:")
    gaps = sorted(b - a for a, b in zip(ptrs, ptrs[1:]))
    from collections import Counter
    print(Counter(gaps).most_common(12))
    print()
    print("%3s %-8s %-6s %-10s %-6s %-6s %-34s %s" % ("i","hash","glob","recidx","f10","f14","icon","floats[+18..+44]"))
    for i, key, pad, ptr in es:
        icon = m.cstr(m.u64(ptr + 8), 64) if ptr else ''
        idx = m.i32(ptr)
        f10 = m.i32(ptr + 0x10); f14 = m.i32(ptr + 0x14)
        fl = [m.f32(ptr + 0x18 + 4 * k) for k in range(12)]
        print("%3d %08X %-6s %-7d %-6d %-6d %-34s %s" % (
            i, key, "G%d" % idx if idx else "-", idx, f10, f14,
            icon.replace('data/Icons/', ''),
            " ".join(("%g" % x) for x in fl)))

if __name__ == '__main__':
    main()
