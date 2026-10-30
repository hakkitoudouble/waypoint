"""Extract the species name table that is materialised at runtime into BSS
at 0x1400EF3A0 by a long sequence of `lea rax,[rip+str]` + `mov [rip+slot],rax` pairs."""
import sys, struct
sys.path.insert(0, r'C:\Users\Maelo\Documents\mods\cotw-pop\tools')
from pe import PE
from mem import Mem

EXE = r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\AnimalPopulationScanner.exe"
ARR = 0x1400EF3A0
N = 0x167

def main():
    pe = PE(EXE); m = Mem(pe); b = pe.b
    text = [s for s in pe.sections if s.name == '.text'][0]
    lo, hi = text.rawptr, text.rawptr + text.rawsize
    nxt = {}   # reg -> (va, value) from most recent lea
    table = {}
    o = lo
    while o < hi - 14:
        rex, op2, modrm = b[o], b[o + 1], b[o + 2]
        # lea r64, [rip+disp32] : REX.W 8D modrm(mod=00 rm=101)
        if rex in (0x48, 0x4C) and op2 == 0x8D and (modrm & 0xC7) == 0x05:
            disp = struct.unpack_from('<i', b, o + 3)[0]
            va = pe.off_to_va(o)
            tgt = va + 7 + disp
            reg = ((rex >> 1) & 4) | ((modrm >> 3) & 7)
            nxt[reg] = (va, tgt)
            o += 7
            continue
        # mov [rip+disp32], r64 : REX.W 89 modrm(mod=00 rm=101)
        if rex in (0x48, 0x4C) and op2 == 0x89 and (modrm & 0xC7) == 0x05:
            disp = struct.unpack_from('<i', b, o + 3)[0]
            va = pe.off_to_va(o)
            tgt = va + 7 + disp
            reg = ((rex >> 1) & 4) | ((modrm >> 3) & 7)
            if ARR <= tgt < ARR + N * 8 and reg in nxt:
                idx = (tgt - ARR) // 8
                table[idx] = (nxt[reg][1], va)
            o += 7
            continue
        o += 1
    print("entries found: %d" % len(table))
    missing = [i for i in range(N) if i not in table]
    print("missing indices: %s%s" % (missing[:20], '...' if len(missing) > 20 else ''))
    for i in range(N):
        if i in table:
            sva, iva = table[i]
            print("%3d  str=%016X  init=%016X  %r" % (i, sva, iva, m.cstr(sva, 80)))
        else:
            print("%3d  <missing>" % i)

if __name__ == '__main__':
    main()
