"""Verify save-index -> reserve mapping by matching species hashes in population files
against the per-reserve species lists published by the COTW Game Companion mod data.
"""
import os
import re
import struct

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\theHunterCotW\dropzone\ui"
DEC = r"C:\Users\Maelo\Documents\mods\cotw-pop\work\decompressed"


def load_species():
    sp = {}
    for line in open(os.path.join(GAME, "cotwgc_species.txt"), encoding="utf-8-sig"):
        line = line.strip()
        if not line:
            continue
        f = line.split("|")
        h = int(f[1])
        key = f[3].replace("animal_", "").replace("_name", "")
        sp[h] = key
    return sp


def load_reserves():
    out = []
    for line in open(os.path.join(GAME, "cotwgc_reserves.txt"), encoding="utf-8-sig"):
        line = line.strip()
        if not line:
            continue
        rid, name, hashes = line.split("|")
        hs = [int(x) for x in hashes.split(",")]
        out.append((int(rid), name, hs))
    return out


def present_hashes(data, hashes):
    found = set()
    for h in hashes:
        if struct.pack("<I", h) in data:
            found.add(h)
    return found


def main():
    species = load_species()
    reserves = load_reserves()
    all_hashes = list(species)

    print("== per save file: species found, best-matching reserves (by ordinal) ==")
    files = sorted(
        [f for f in os.listdir(DEC) if f.startswith("animal_population_")],
        key=lambda s: int(s.split("_")[-1].split(".")[0]),
    )
    for f in files:
        n = int(f.split("_")[-1].split(".")[0])
        data = open(os.path.join(DEC, f), "rb").read()
        found = present_hashes(data, all_hashes)
        names = sorted(species[h] for h in found)
        # score each reserve by fraction of its species present
        scores = []
        for rid, rname, hs in reserves:
            inter = len(found & set(hs))
            scores.append((inter / len(hs), inter, len(hs), rid, rname))
        scores.sort(reverse=True)
        # ordinal of the reserve entry (0-based position in list)
        best = scores[0]
        ordinal = [i for i, r in enumerate(reserves) if r[0] == best[3]][0]
        print(f"\nN={n:2d}  species={len(found):2d}  best={best[4]!r} (game_id={best[3]}, ordinal={ordinal}) "
              f"match={best[1]}/{best[2]}  species={names}")
        alt = scores[1]
        print(f"         2nd: {alt[4]!r} match={alt[1]}/{alt[2]}")


if __name__ == "__main__":
    main()
