"""Decisive test: join harvest-log entries (species + timestamp) with save-file mtimes.

For species that exist in only ONE reserve, a harvest at time T must correspond to the
save index whose animal_population_N / fog file was written around T.
"""
import os
import re
from datetime import datetime, timezone

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\theHunterCotW\dropzone\ui"
SAVE = r"C:\Users\Maelo\Documents\Avalanche Studios\COTW\Saves\76561199084637132"


def load_species():
    sp = {}
    for line in open(os.path.join(GAME, "cotwgc_species.txt"), encoding="utf-8-sig"):
        line = line.strip()
        if line:
            f = line.split("|")
            sp[int(f[1])] = f[3].replace("animal_", "").replace("_name", "")
    return sp


def load_reserves():
    out = []
    for line in open(os.path.join(GAME, "cotwgc_reserves.txt"), encoding="utf-8-sig"):
        line = line.strip()
        if line:
            rid, name, hashes = line.split("|")
            out.append((int(rid), name, [int(x) for x in hashes.split(",")]))
    return out


def save_mtimes():
    """index -> list of mtimes (from population + fog files)."""
    idx = {}
    for f in os.listdir(SAVE):
        m = re.match(r"(?:animal_population_|adf_fog_of_war_data_faster_|found_icons_)(\d+)$", f)
        if m:
            n = int(m.group(1))
            idx.setdefault(n, []).append(os.path.getmtime(os.path.join(SAVE, f)))
    return idx


def main():
    species = load_species()
    reserves = load_reserves()
    mtimes = save_mtimes()

    # species -> set of reserve names (by scanning lists); use internal id as key
    sp2res = {}
    for rid, name, hs in reserves:
        for h in hs:
            sp2res.setdefault(h, set()).add((rid, name))

    records = []
    for line in open(os.path.join(GAME, "cotwgc_history.txt"), encoding="utf-8-sig"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f = line.split()
        if f[0] == "h" and len(f) >= 7:
            records.append((int(f[1]), float(f[2]), int(f[4])))

    print(f"{'species':<22} {'time':<17} {'#save idx written within 2d':<12} candidate reserve(s)")
    print("-" * 110)
    stats = {}
    for sp, score, t in records:
        cands = sp2res.get(sp, set())
        if len(cands) != 1:
            continue
        rid, rname = next(iter(cands))
        near = [(n, min(abs(mt - t) for mt in ms)) for n, ms in mtimes.items()]
        near = [(n, d) for n, d in near if d <= 2 * 86400]
        ts = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M")
        idxs = sorted(n for n, d in near)
        print(f"{species.get(sp,sp):<22} {ts:<17} {str(idxs):<12} {rname}")
        for n in idxs:
            stats.setdefault(n, []).append((rid, rname))

    print("\n== tally: save index N  ->  reserve names of unique-species harvests in that window ==")
    for n in sorted(stats):
        names = {}
        for rid, rname in stats[n]:
            names[rname] = names.get(rname, 0) + 1
        # position of that id in the reserves list (ordinal hypothesis)
        print(f"  N={n:<3} {names}")


if __name__ == "__main__":
    main()
