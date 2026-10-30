"""Find ALL language variants of the runtime string table built at 0x1400EF3A0.
Each language is a contiguous run of `lea rax,[rip+str]; mov [rip+slot],rax` pairs."""
import sys, struct
from collections import defaultdict
sys.path.insert(0, r'C:\Users\Maelo\Documents\mods\cotw-pop\tools')
from pe import PE
from mem import Mem

EXE = r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\AnimalPopulationScanner.exe"
ARR = 0x1400EF3A0
N = 0x167

def collect(pe, m):
    b = pe.b
    text = [s for s in pe.sections if s.name == '.text'][0]
    lo, hi = text.rawptr, text.rawptr + text.rawsize
    nxt = {}
    hits = []   # (init_va, idx, str_va)
    o = lo
    while o < hi - 14:
        rex, op2, modrm = b[o], b[o + 1], b[o + 2]
        if rex in (0x48, 0x4C) and op2 == 0x8D and (modrm & 0xC7) == 0x05:
            disp = struct.unpack_from('<i', b, o + 3)[0]
            va = pe.off_to_va(o)
            reg = ((rex >> 1) & 4) | ((modrm >> 3) & 7)
            nxt[reg] = (va, va + 7 + disp)
            o += 7
            continue
        if rex in (0x48, 0x4C) and op2 == 0x89 and (modrm & 0xC7) == 0x05:
            disp = struct.unpack_from('<i', b, o + 3)[0]
            va = pe.off_to_va(o)
            tgt = va + 7 + disp
            reg = ((rex >> 1) & 4) | ((modrm >> 3) & 7)
            if ARR <= tgt < ARR + N * 8 and reg in nxt:
                hits.append((va, (tgt - ARR) // 8, nxt[reg][1]))
            o += 7
            continue
        o += 1
    return hits

def main():
    pe = PE(EXE); m = Mem(pe)
    hits = collect(pe, m)
    print("total store sites: %d" % len(hits))
    # group into clusters: new cluster when gap from previous hit VA > 0x3000
    hits.sort()
    clusters = []
    for h in hits:
        if clusters and h[0] - clusters[-1][-1][0] < 0x3000:
            clusters[-1].append(h)
        else:
            clusters.append([h])
    print("clusters: %d" % len(clusters))
    for ci, cl in enumerate(clusters):
        idxs = sorted(i for _, i, _ in cl)
        print("\n===== cluster %d : %d entries, %X..%X, idx %d..%d" % (
            ci, len(cl), cl[0][0], cl[-1][0], idxs[0], idxs[-1]))
        # samples
        for k in (0, 13, 26, 97, 127, 344):
            for _, i, s in cl:
                if i == k:
                    print("   idx %3d = %r" % (i, m.cstr(s, 60)))
                    break

if __name__ == '__main__':
    main()
