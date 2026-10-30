"""Validate the exe's 135 species NameHashIds against real COTW population files.
Only decompresses and byte-searches; no ADF parsing."""
import sys, struct, zlib, os, glob
sys.path.insert(0, r'C:\Users\Maelo\Documents\mods\cotw-pop\tools')
from pe import PE
from mem import Mem

EXE = r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\AnimalPopulationScanner.exe"
SAVEDIR = r"C:\Users\Maelo\Documents\Avalanche Studios\COTW\Saves\76561199084637132"
TABLE = 0x1400B0C80
COUNT = 0x87


def load_table():
    pe = PE(EXE); m = Mem(pe)
    ents = []
    for i in range(COUNT):
        va = TABLE + 16 * i
        key = m.u32(va); ptr = m.u64(va + 8)
        icon = m.cstr(m.u64(ptr + 8), 64)
        sid = m.i32(ptr)
        ents.append((key, sid, icon.replace('data/Icons/', '').replace('_frame.png', '')))
    return ents, pe, m


def unwrap(raw):
    if raw[:4] != b'SAVE':
        return None, 'not SAVE'
    if raw[16:20] != b'COMP':
        return None, 'no COMP'
    usize = struct.unpack_from('<I', raw, 8)[0]
    d = zlib.decompressobj()
    try:
        out = d.decompress(raw[32:])
    except Exception as e:
        return None, 'zlib: %s' % e
    return out, 'ok(%d/%d)' % (len(out), usize)


def main():
    ents, pe, m = load_table()
    files = sorted(glob.glob(os.path.join(SAVEDIR, 'animal_population_*')))
    print("population files: %d" % len(files))
    allhits = {}
    for f in files:
        raw = open(f, 'rb').read()
        data, st = unwrap(raw)
        name = os.path.basename(f)
        if data is None:
            print("%-24s %8d  %s" % (name, len(raw), st)); continue
        hits = []
        for h, sid, icon in ents:
            le = struct.pack('<I', h)
            be = struct.pack('>I', h)
            n = data.count(le)
            nb = data.count(be)
            if n or nb:
                hits.append((h, sid, icon, n, nb))
        uniq = sorted(set((h, sid, icon) for h, sid, icon, _, _ in hits))
        print("%-24s %8d -> %8d  species-hits=%d" % (name, len(raw), len(data), len(uniq)))
        for h, sid, icon in uniq:
            allhits.setdefault(h, []).append(name)
    print("\n=== hashes found in at least one real save: %d of %d ===" % (len(allhits), len(ents)))
    for h, sid, icon in [(h, s, i) for h, s, i in ents]:
        if h in allhits:
            print("  %08X  sid=%-4d %-22s  in %d files" % (h, sid, icon, len(allhits[h])))


if __name__ == '__main__':
    main()
