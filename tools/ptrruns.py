import sys, struct
sys.path.insert(0, r'C:\Users\Maelo\Documents\mods\cotw-pop\tools')
from pe import PE
from mem import Mem

EXE = r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\AnimalPopulationScanner.exe"

def main():
    pe = PE(EXE); m = Mem(pe); b = pe.b
    STRLO, STRHI = 0x140086000, 0x1400AF5A8   # .rdata
    runs = []
    for s in pe.sections:
        if s.name not in ('.data', '.rdata'):
            continue
        o = s.rawptr
        end = s.rawptr + s.rawsize - 8
        while o <= end:
            cur = []
            while o <= end:
                v = struct.unpack_from('<Q', b, o)[0]
                if STRLO <= v < STRHI:
                    cur.append((o, v)); o += 8
                else:
                    break
            if len(cur) >= 8:
                runs.append((s.name, cur))
            o += 8
    print('runs>=8:', len(runs))
    for sec, cur in runs:
        print('--- %s run at file %X (VA %016X) n=%d' % (sec, cur[0][0], pe.off_to_va(cur[0][0]), len(cur)))
        for o, v in cur[:300]:
            print('    %016X %r' % (v, m.cstr(v, 60)))

if __name__ == '__main__':
    main()
