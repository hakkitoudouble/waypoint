"""Try to crack the NameHashId hash function using the 135 known (hash, species) pairs."""
import sys, struct, zlib, itertools
sys.path.insert(0, r'C:\Users\Maelo\Documents\mods\cotw-pop\tools')
from pe import PE
from mem import Mem

EXE = r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\AnimalPopulationScanner.exe"
TABLE = 0x1400B0C80
COUNT = 0x87

M32 = 0xFFFFFFFF

# ---------------- hash functions ----------------
def crc32(b):      return zlib.crc32(b) & M32
def crc32_bz(b):   return zlib.crc32(b) & M32
_CRC32C_TAB = None
def _c32c_tab():
    global _CRC32C_TAB
    if _CRC32C_TAB is None:
        t = []
        for i in range(256):
            c = i
            for _ in range(8):
                c = (c >> 1) ^ (0x82F63B78 if c & 1 else 0)
            t.append(c)
        _CRC32C_TAB = t
    return _CRC32C_TAB
def crc32c(b):
    t = _c32c_tab(); c = M32
    for x in b: c = t[(c ^ x) & 0xFF] ^ (c >> 8)
    return c ^ M32

def fnv1a32(b):
    h = 0x811C9DC5
    for x in b: h = ((h ^ x) * 0x01000193) & M32
    return h
def fnv132(b):
    h = 0x811C9DC5
    for x in b: h = (h * 0x01000193) & M32; h ^= x
    return h
def joaat(b):
    h = 0
    for x in b:
        h = (h + x) & M32
        h = (h + (h << 10)) & M32
        h ^= h >> 6
    h = (h + (h << 3)) & M32
    h ^= h >> 11
    h = (h + (h << 15)) & M32
    return h
def djb2(b):
    h = 5381
    for x in b: h = ((h * 33) + x) & M32
    return h
def djb2x(b):
    h = 5381
    for x in b: h = ((h * 33) ^ x) & M32
    return h
def sdbm(b):
    h = 0
    for x in b: h = (x + (h << 6) + (h << 16) - h) & M32
    return h
def java(b):
    h = 0
    for x in b: h = ((h * 31) + x) & M32
    return h
def elf(b):
    h = 0
    for x in b:
        h = ((h << 4) + x) & M32
        g = h & 0xF0000000
        if g: h ^= g >> 24
        h &= ~g & M32
    return h
def pjw(b):
    h = 0
    for x in b:
        h = ((h << 4) + x) & M32
        g = h & 0xF0000000
        if g: h = (h ^ (g >> 24)) & M32; h &= ~g & M32
    return h
def avalanche_shift(b):
    """Avalanche-ish: h = (h<<5) + h + c"""
    h = 0
    for x in b: h = ((h << 5) + h + x) & M32
    return h
def avalanche_shift2(b):
    h = 0
    for x in b: h = (x + (h << 5) + (h >> 2)) & M32
    return h
def avalanche_shift3(b):
    h = 0
    for x in b: h = (x + (h << 5) - h) & M32
    return h

def rotl32(x, r): return ((x << r) | (x >> (32 - r))) & M32
def murmur3_32(data, seed=0):
    c1, c2 = 0xCC9E2D51, 0x1B873593
    h = seed; n = len(data); nblocks = n // 4
    for i in range(nblocks):
        k = struct.unpack_from('<I', data, i * 4)[0]
        k = (k * c1) & M32; k = rotl32(k, 15); k = (k * c2) & M32
        h ^= k; h = rotl32(h, 13); h = (h * 5 + 0xE6546B64) & M32
    tail = data[nblocks * 4:]; k = 0
    if len(tail) >= 3: k ^= tail[2] << 16
    if len(tail) >= 2: k ^= tail[1] << 8
    if len(tail) >= 1:
        k ^= tail[0]; k = (k * c1) & M32; k = rotl32(k, 15); k = (k * c2) & M32; h ^= k
    h ^= n
    h ^= h >> 16; h = (h * 0x85EBCA6B) & M32
    h ^= h >> 13; h = (h * 0xC2B2AE35) & M32
    h ^= h >> 16
    return h

def murmur2_32(data, seed=0):
    m, r = 0x5BD1E995, 24
    h = (seed ^ len(data)) & M32
    i = 0; n = len(data)
    while n - i >= 4:
        k = struct.unpack_from('<I', data, i)[0]
        k = (k * m) & M32; k ^= k >> r; k = (k * m) & M32
        h = (h * m) & M32; h ^= k
        i += 4
    rem = n - i
    if rem == 3: h ^= data[i+2] << 16
    if rem >= 2: h ^= data[i+1] << 8
    if rem >= 1:
        h ^= data[i]; h = (h * m) & M32
    h ^= h >> 13; h = (h * m) & M32; h ^= h >> 15
    return h

def xxh32(data, seed=0):
    P1, P2, P3, P4, P5 = 0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F, 0x165667B1
    n = len(data); i = 0
    if n >= 16:
        v1 = (seed + P1 + P2) & M32; v2 = (seed + P2) & M32
        v3 = seed; v4 = (seed - P1) & M32
        while i <= n - 16:
            for k, v in enumerate((v1, v2, v3, v4)):
                x = struct.unpack_from('<I', data, i + 4 * k)[0]
                v = (v + x * P2) & M32; v = rotl32(v, 13); v = (v * P1) & M32
                if k == 0: v1 = v
                elif k == 1: v2 = v
                elif k == 2: v3 = v
                else: v4 = v
            i += 16
        h = (rotl32(v1, 1) + rotl32(v2, 7) + rotl32(v3, 12) + rotl32(v4, 18)) & M32
    else:
        h = (seed + P5) & M32
    h = (h + n) & M32
    while i <= n - 4:
        h = (h + struct.unpack_from('<I', data, i)[0] * P3) & M32
        h = rotl32(h, 17) * P4 & M32
        i += 4
    while i < n:
        h = (h + data[i] * P5) & M32
        h = rotl32(h, 11) * P1 & M32
        i += 1
    h ^= h >> 15; h = (h * P2) & M32; h ^= h >> 13
    h = (h * P3) & M32; h ^= h >> 16
    return h

HASHES = {
    'crc32': crc32, 'crc32c': crc32c,
    'fnv1a32': fnv1a32, 'fnv132': fnv132,
    'joaat': joaat, 'djb2': djb2, 'djb2x': djb2x, 'sdbm': sdbm,
    'java': java, 'elf': elf, 'pjw': pjw,
    'aval_s5p1': avalanche_shift, 'aval_s5r2': avalanche_shift2, 'aval_31': avalanche_shift3,
    'murmur3_0': lambda b: murmur3_32(b, 0),
    'murmur3_ff': lambda b: murmur3_32(b, 0xFFFFFFFF),
    'murmur3_1': lambda b: murmur3_32(b, 1),
    'murmur2_0': lambda b: murmur2_32(b, 0),
    'xxh32_0': lambda b: xxh32(b, 0),
}

def load_pairs():
    pe = PE(EXE); m = Mem(pe)
    pairs = []
    for i in range(COUNT):
        va = TABLE + 16 * i
        key = m.u32(va); ptr = m.u64(va + 8)
        icon = m.cstr(m.u64(ptr + 8), 64)
        pairs.append((key, icon.replace('data/Icons/', '').replace('_frame.png', '')))
    return pairs

def variants(name):
    """Generate plausible asset-name spellings from an icon stem or English name."""
    out = set()
    base = name
    # split camel-ish: 'Reddeer' -> no; 'HogDeer' -> 'Hog','Deer'
    out.add(base)
    out.add(base.lower())
    out.add(base.upper())
    # space-separated words version: try inserting space before capitals
    words = []
    cur = ''
    for ch in base:
        if ch.isupper() and cur:
            words.append(cur); cur = ch
        else:
            cur += ch
    if cur: words.append(cur)
    camel = ''.join(w[:1].upper() + w[1:].lower() for w in words if w)
    out.add(camel)
    out.add(camel.lower())
    out.add('_'.join(w.lower() for w in words if w))
    out.add('_'.join(w.lower() for w in words if w).replace('_', ''))
    out.add('-'.join(w.lower() for w in words if w))
    out.add(' '.join(w.lower() for w in words if w))
    return {v for v in out if v}

def expand(stem):
    """Templates around a base spelling."""
    bases = variants(stem)
    out = set()
    for b in bases:
        out.add(b)
        low = b.lower()
        for t in ['animal_%s', 'Animal_%s', 'animal%s', '%s_animal', '%sAnimal',
                  'animals/%s', '/animals/%s', 'animals/%s/%s', '%s.adf', '%s_01',
                  '%s_01.adf', 'Animals/%s', 'ANIMAL_%s', '%s_species', 'species_%s',
                  '/animals/%s/adult', '%s/']:
            try:
                out.add(t % (low, low))
            except TypeError:
                out.add(t % low)
    return out

def main():
    pairs = load_pairs()
    uniq = {}
    for h, ic in pairs:
        uniq.setdefault(h, ic)
    print("unique hashes: %d" % len(uniq))
    best = []
    for hn, fn in HASHES.items():
        matches = {}
        for h, stem in uniq.items():
            for cand in expand(stem):
                for c in (cand, cand.lower(), cand.upper()):
                    b = c.encode('utf-8', 'ignore')
                    if fn(b) == h:
                        matches.setdefault(h, []).append((cand, c))
        if matches:
            best.append((len(matches), hn, matches))
            print("  %-12s matched %d/%d" % (hn, len(matches), len(uniq)))
    if not best:
        print("no matches for any candidate function / spelling")
        return
    best.sort(reverse=True)
    n, hn, matches = best[0]
    print("\nBEST: %s with %d matches" % (hn, n))
    for h, lst in list(matches.items())[:40]:
        print("  %08X -> %s (stem %s)" % (h, lst[0][0], uniq[h]))

if __name__ == '__main__':
    main()
