"""Build final deliverables: species_hashes.json, species_stats.json, localization-en.json."""
import sys, os, struct, json, glob, zlib, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'C:\Users\Maelo\Documents\mods\cotw-pop\tools')
from pe import PE
from mem import Mem
from nametable2 import collect, ARR, N

EXE = r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\AnimalPopulationScanner.exe"
SAVEDIR = r"C:\Users\Maelo\Documents\Avalanche Studios\COTW\Saves\76561199084637132"
OUT = r"C:\Users\Maelo\Documents\mods\cotw-pop"
TABLE = 0x1400B0C80
COUNT = 0x87
RECSZ = 0x3C0


def english_table(pe, m):
    hits = sorted(collect(pe, m))
    cur = {}
    for va, idx, s in hits:
        cur[idx] = s
        if idx == N - 1:
            break
    return {k: m.cstr(v, 250) for k, v in cur.items()}


def record_fields(m, p):
    return dict(
        stringId=m.i32(p + 0x00),
        icon=m.cstr(m.u64(p + 0x08), 96),
        maxDifficultyRating=m.i32(p + 0x10),
        field_0x14=m.i32(p + 0x14),
        field_0x18=m.f32(p + 0x18),
        triple_0x1C=[round(m.f32(p + 0x1C + 4 * k), 6) for k in range(3)],
        field_0x28=[m.f32(p + 0x28), m.f32(p + 0x2C)],
        series_0x30=[round(m.f32(p + 0x30 + 4 * k), 6) for k in range(8)],
        field_0x50=m.i32(p + 0x50),
        field_0x54=m.i32(p + 0x54),
    )


def main():
    pe = PE(EXE); m = Mem(pe)
    en = english_table(pe, m)

    # ---- walk the hash table, grouping by record pointer ----
    by_rec = {}
    hash_to_name = {}
    for i in range(COUNT):
        va = TABLE + 16 * i
        h = m.u32(va); ptr = m.u64(va + 8)
        f = record_fields(m, ptr)
        name = en.get(f['stringId'], '?<%s>' % f['icon'])
        hash_to_name["%08X" % h] = name
        rec = by_rec.setdefault(ptr, dict(f, name=name, hashes=[]))
        rec['hashes'].append("%08X" % h)

    # ---- which hashes appear in real save files (pure byte search) ----
    seen = {}
    for fp in glob.glob(os.path.join(SAVEDIR, 'animal_population_*')):
        raw = open(fp, 'rb').read()
        if raw[:4] != b'SAVE' or raw[16:20] != b'COMP':
            continue
        try:
            data = zlib.decompressobj().decompress(raw[32:])
        except Exception:
            continue
        if len(data) < 5000:
            continue
        base = os.path.basename(fp)
        for i in range(COUNT):
            h = m.u32(TABLE + 16 * i)
            if data.count(struct.pack('<I', h)):
                seen.setdefault("%08X" % h, []).append(base)

    # ---- species_hashes.json ----
    j = {"_hashfn": None}
    j.update(hash_to_name)
    j["_note"] = ("Mapping extracted from the exe's own hash->species lookup table at "
                  "VA 0x1400B0C80 (file offset 0xAEE80), 135 entries of "
                  "{u32 nameHashId; u32 pad; u64 speciesRecord}, each compared with "
                  "`cmp dword ptr [rcx], ebx` in the resolver at VA 0x140057055. "
                  "The hash FUNCTION was not recovered; the table is the ground truth.")
    j["_hashfn_status"] = ("NOT CRACKED. Tried CRC32/CRC32C/FNV-1a/FNV-1/"
                           "XXH32/Murmur2/Murmur3/joaat/djb2/sdbm/java/ELF/PJW/"
                           "Avalanche-style shift variants over ~120 spelling "
                           "templates derived from icon stems and English names "
                           "(case, snake, camel, space, hyphen, prefix/suffix, "
                           "asset-path forms). Zero matches on all 135 pairs.")
    j["_verifiedInSaves"] = seen
    json.dump(j, open(os.path.join(OUT, 'cotw', 'data', 'species_hashes.json'), 'w',
                      encoding='utf-8'), ensure_ascii=False, indent=1)

    # ---- species_stats.json ----
    species = []
    for ptr, rec in by_rec.items():
        rec = dict(rec)
        rec.pop('hashes') if False else None
        rec['hashes'] = sorted(rec['hashes'])
        rec['hashesSeenInSaves'] = sorted(h for h in rec['hashes'] if h in seen)
        species.append(rec)
    species.sort(key=lambda r: r['stringId'])
    stats = {
        "_schema": {
            "description": ("Per-species constants read out of the Animal Population "
                            "Scanner exe. One object per species record "
                            "(struct size 0x3C0, array VA 0x1400B08C0..0x1400CED70, "
                            "126 live records)."),
            "record_layout": {
                "+0x00": "i32 stringId -> index into the runtime localization table "
                         "(English names in notes/localization-en.json)",
                "+0x08": "char* iconPath",
                "+0x10": "i32 maxDifficultyRating (1..9)",
                "+0x14": "i32 unknown (0..9)",
                "+0x18": "f32 always 0.0",
                "+0x1C": "f32[3] ascending per-species triple (semantics not proven)",
                "+0x28": "f32[2] always 0.0",
                "+0x30": "f32[8] ascending series, zero-padded; magnitude matches "
                         "species body weight in kg",
                "+0x50": "i32 always 1",
                "+0x54": "i32 usually 0",
            },
            "difficultyLevelNames": ["Trivial", "Minor", "Very Easy", "Easy",
                                     "Medium", "Hard", "Very Hard", "Mythical",
                                     "Legendary", "Fabled"],
            "confidence": {
                "name / hash mapping": "VERIFIED (see notes/exe-data.md)",
                "maxDifficultyRating": "LIKELY (magnitudes and known COTW ratings agree)",
                "series_0x30 as weight kg": "LIKELY",
                "triple_0x1C": "SPECULATIVE (min/typical/max weight or TR; ambiguous)",
                "field_0x14": "UNKNOWN",
            },
        },
        "species": species,
    }
    json.dump(stats, open(os.path.join(OUT, 'cotw', 'data', 'species_stats.json'), 'w',
                          encoding='utf-8'), ensure_ascii=False, indent=1)

    # ---- localization-en.json ----
    loc = {"%d" % k: v for k, v in sorted(en.items())}
    json.dump({"_note": "English runtime string table, materialised at VA 0x1400EF3A0 "
                        "by the initializer at VA 0x140040497..0x14004832C. Index is the "
                        "shared UI+species string ID used by species record +0x00.",
               "strings": loc},
              open(os.path.join(OUT, 'notes', 'localization-en.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    print("species records: %d" % len(species))
    print("hashes: %d, verified in saves: %d" % (len(hash_to_name), len(seen)))
    print("wrote species_hashes.json, species_stats.json, localization-en.json")


if __name__ == '__main__':
    main()
