"""Extract each language's runtime string table (0x1400EF3A0) as ordered runs."""
import sys, struct, json
sys.path.insert(0, r'C:\Users\Maelo\Documents\mods\cotw-pop\tools')
from pe import PE
from mem import Mem
from nametable2 import collect, ARR, N, EXE

def main():
    pe = PE(EXE); m = Mem(pe)
    hits = sorted(collect(pe, m))
    runs = []
    cur = {}
    for va, idx, s in hits:
        cur[idx] = (va, s)
        if idx == N - 1:
            runs.append(dict(cur))
            cur = {}
    if cur:
        runs.append(dict(cur))
    print("runs: %d  (sizes %s)" % (len(runs), [len(r) for r in runs]))
    out = {}
    for ri, r in enumerate(runs):
        sample = [m.cstr(r[k][1], 40) for k in (26, 97, 127, 344) if k in r]
        print("run %d: idx26=%r idx97=%r idx127=%r idx344=%r" % (ri, *sample))
        out["run%d" % ri] = {str(k): m.cstr(v[1], 90) for k, v in r.items()}
    json.dump(out, open(r'C:\Users\Maelo\Documents\mods\cotw-pop\notes\langtables.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print("wrote langtables.json")

if __name__ == '__main__':
    main()
