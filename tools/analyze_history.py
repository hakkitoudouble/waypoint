"""Parse COTW companion harvest history: verify reserve index -> species set, and collect
normalized map positions per reserve.
"""
import os
import re

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\theHunterCotW\dropzone\ui"


def load_species():
    sp = {}
    for line in open(os.path.join(GAME, "cotwgc_species.txt"), encoding="utf-8-sig"):
        line = line.strip()
        if not line:
            continue
        f = line.split("|")
        sp[int(f[1])] = f[3].replace("animal_", "").replace("_name", "")
    return sp


def load_reserves():
    out = []
    for line in open(os.path.join(GAME, "cotwgc_reserves.txt"), encoding="utf-8-sig"):
        line = line.strip()
        if not line:
            continue
        rid, name, hashes = line.split("|")
        out.append((int(rid), name, [int(x) for x in hashes.split(",")]))
    return out


def main():
    species = load_species()
    reserves = load_reserves()
    harvests = []   # (species, score, rank, time, reserve, fur)
    positions = {}  # (species, time) -> (rank, x, y)
    counts = {}
    for line in open(os.path.join(GAME, "cotwgc_history.txt"), encoding="utf-8-sig"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f = line.split()
        tag = f[0]
        counts[tag] = counts.get(tag, 0) + 1
        try:
            if tag in ("t", "h") and len(f) >= 7:
                harvests.append((int(f[1]), float(f[2]), int(f[3]), int(f[4]), int(f[5])))
            elif tag == "p" and len(f) >= 6:
                positions[(int(f[1]), int(f[2]))] = (int(f[3]), float(f[4]), float(f[5]))
        except ValueError:
            continue

    print("record tags:", counts)
    print("harvests:", len(harvests), "positions:", len(positions))

    by_res = {}
    for sp, score, rank, time, res in harvests:
        by_res.setdefault(res, []).append((sp, time))

    print("\n== observed species per reserve index (from user's harvest log) ==")
    print(f"{'N':>3} {'#species':>8} {'#kills':>6}  species                       | reserves.txt name (by ordinal)")
    for n in sorted(by_res):
        sps = {s for s, _ in by_res[n]}
        names = sorted(species.get(s, str(s)) for s in sps)
        ordinal_name = reserves[n][1] if n < len(reserves) else "??"
        inside = len(sps & set(reserves[n][2])) if n < len(reserves) else 0
        print(f"{n:>3} {len(sps):>8} {len(by_res[n]):>6}  {','.join(names)[:58]:<58}| {ordinal_name[:38]}  ({inside}/{len(reserves[n][2])} match)")

    print("\n== species observed at each index that are NOT in reserves.txt list for that ordinal ==")
    for n in sorted(by_res):
        if n >= len(reserves):
            continue
        sps = {s for s, _ in by_res[n]}
        extra = sps - set(reserves[n][2])
        if extra:
            print(f"  N={n}: unexpected {[species.get(s, s) for s in extra]}")

    print("\n== normalized map positions per reserve (joined t<->p on species+time) ==")
    geo = {}
    for sp, score, rank, time, res in harvests:
        p = positions.get((sp, time))
        if p:
            geo.setdefault(res, []).append((p[1], p[2]))
    for n in sorted(geo):
        xs = [a for a, b in geo[n]]
        ys = [b for a, b in geo[n]]
        print(f"  N={n:>2}: n={len(xs):>3} x=[{min(xs):.4f},{max(xs):.4f}] y=[{min(ys):.4f},{max(ys):.4f}]")


if __name__ == "__main__":
    main()
