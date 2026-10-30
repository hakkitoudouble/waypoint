"""Test map-normalized coordinates (x,y in 0..1) against the *_bw map images.

Points = harvest positions from the COTW companion log, resolved to a reserve via the
harvest's reserve id (or a reserve-unique species). Water renders bright in the bw maps,
so a correct orientation should put very few points on water.
"""
import os

import numpy as np
from PIL import Image

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\theHunterCotW\dropzone\ui"
MAPS = r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\data\Maps"
OUT = r"C:\Users\Maelo\Documents\mods\cotw-pop\work\preview"

# companion reserve id -> map file
ID2MAP = {
    0: "MapHirsch_bw.png", 1: "MapLayton_bw.png", 2: "MapMedved_bw.png", 3: "MapVurhonga_bw.png",
    4: "MapParque_bw.png", 6: "MapYukon_bw.png", 8: "MapCuatro_bw.png", 9: "MapSRP_bw.png",
    10: "MapNZ_bw.png", 11: "MapRancho_bw.png", 12: "MapMississippi_bw.png", 13: "MapRevontuli_bw.png",
    14: "MapNewEngland_bw.png", 16: "EmeraldCoast_bw.png", 17: "MapSundarpatan_bw.png",
    18: "Salzwiesen_Park_bw.png", 19: "MapAskiyRidge_bw.png", 20: "MapScotland_bw.png",
    21: "MapPeru_bw.png",
}


def load_species():
    sp = {}
    for line in open(os.path.join(GAME, "cotwgc_species.txt"), encoding="utf-8-sig"):
        line = line.strip()
        if line:
            f = line.split("|")
            sp[int(f[1])] = f[3].replace("animal_", "").replace("_name", "")
    return sp


def load_reserves():
    out = {}
    for line in open(os.path.join(GAME, "cotwgc_reserves.txt"), encoding="utf-8-sig"):
        line = line.strip()
        if line:
            rid, name, hashes = line.split("|")
            out[int(rid)] = (name, [int(x) for x in hashes.split(",")])
    return out


def main():
    sp = load_species()
    res = load_reserves()
    sp2res = {}
    for rid, (name, hs) in res.items():
        for h in hs:
            sp2res.setdefault(h, set()).add(rid)

    trophies = {}
    positions = []
    for line in open(os.path.join(GAME, "cotwgc_history.txt"), encoding="utf-8-sig"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f = line.split()
        if f[0] == "t" and len(f) >= 7:
            trophies[(int(f[1]), int(f[4]))] = int(f[5])
        elif f[0] == "p" and len(f) >= 6:
            positions.append((int(f[1]), int(f[2]), float(f[4]), float(f[5])))

    pts = []
    for spid, t, x, y in positions:
        rid = trophies.get((spid, t))
        if rid is None:
            cands = sp2res.get(spid, set())
            if len(cands) == 1:
                rid = next(iter(cands))
        if rid is None or rid not in ID2MAP:
            continue
        pts.append((rid, x, y, sp.get(spid, str(spid))))

    print(f"usable points: {len(pts)}")
    names = ["identity", "flip_x", "flip_y", "rot180", "rot90", "rot270", "transpose", "anti"]
    results = {n: [0, 0] for n in names}  # land, total
    per_pt_detail = []
    for rid, x, y, spname in pts:
        p = os.path.join(MAPS, ID2MAP[rid])
        im = Image.open(p).convert("L")
        W, H = im.size
        a = np.asarray(im, dtype=np.uint8)
        variants = {
            "identity": (x, y),
            "flip_x": (1 - x, y),
            "flip_y": (x, 1 - y),
            "rot180": (1 - x, 1 - y),
            "rot90": (1 - y, x),
            "rot270": (y, 1 - x),
            "transpose": (y, x),
            "anti": (1 - y, 1 - x),
        }
        for nm, (px, py) in variants.items():
            ix = min(W - 1, max(0, int(px * W)))
            iy = min(H - 1, max(0, int(py * H)))
            # sample a small neighbourhood (median) to be robust
            win = a[max(0, iy - 2):iy + 3, max(0, ix - 2):ix + 3]
            val = float(np.median(win))
            results[nm][1] += 1
            if val < 140:  # dark = land
                results[nm][0] += 1
        per_pt_detail.append((rid, ID2MAP[rid], x, y, spname))

    print("\norientation -> fraction of points on land")
    for nm, (land, tot) in sorted(results.items(), key=lambda kv: -kv[1][0]):
        print(f"  {nm:<10} {land}/{tot} = {land/tot:.1%}")

    # overlay identity mapping for one well-sampled reserve
    from collections import Counter
    cnt = Counter(p[0] for p in per_pt_detail)
    rid = cnt.most_common(1)[0][0]
    base = Image.open(os.path.join(MAPS, ID2MAP[rid])).convert("RGB")
    W, H = base.size
    draw = np.asarray(base).copy()
    for r, m, x, y, spname in per_pt_detail:
        if r != rid:
            continue
        ix, iy = int(x * W), int(y * H)
        draw[max(0, iy - 4):iy + 5, max(0, ix - 4):ix + 5] = [255, 40, 40]
    Image.fromarray(draw).resize((600, int(600 * H / W))).save(
        os.path.join(OUT, f"overlay_reserve{rid}.png"))
    print(f"\noverlay written for reserve id {rid} ({ID2MAP[rid]}) with {cnt[rid]} points")


if __name__ == "__main__":
    main()
