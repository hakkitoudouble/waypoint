"""Match fog-of-war masks to map images.

Explored area = higher fog values; players cannot walk on water, and water renders bright
in the *_bw maps, so the correct (fog, map) pair should show a NEGATIVE correlation between
fog value and map brightness, robust across the 8 dihedral orientations.
"""
import glob
import os

import numpy as np
from PIL import Image

MAPS = r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\data\Maps"
FOG = r"C:\Users\Maelo\Documents\mods\cotw-pop\work\save_decompressed"
SZ = 128
IDX = [0, 3, 4, 5, 6, 8, 9, 14, 16]


def transforms(a):
    out = []
    for k in range(4):
        r = np.rot90(a, k)
        out.append(r)
        out.append(np.fliplr(r))
    return out


def main():
    maps = {}
    for p in sorted(glob.glob(os.path.join(MAPS, "*.png"))):
        g = Image.open(p).convert("L").resize((SZ, SZ), Image.LANCZOS)
        a = np.asarray(g, dtype=np.float64)
        maps[os.path.basename(p)] = (a - a.mean()) / (a.std() + 1e-9)

    print("fog index -> best-matching maps by most-negative correlation (fog vs brightness)\n")
    results = {}
    for n in IDX:
        d = open(os.path.join(FOG, f"adf_fog_of_war_data_faster_{n}.bin"), "rb").read()
        m = np.frombuffer(d[0:65536], dtype=np.uint8).reshape(256, 256).astype(np.float64)
        m = np.asarray(Image.fromarray(m.astype(np.uint8)).resize((SZ, SZ), Image.BILINEAR),
                       dtype=np.float64)
        m = (m - m.mean()) / (m.std() + 1e-9)
        scores = {}
        for name, mp in maps.items():
            vals = [float(np.mean(t * mp)) for t in transforms(m)]
            scores[name] = min(vals)
        ranked = sorted(scores.items(), key=lambda kv: kv[1])
        results[n] = ranked
        print(f"N={n:>2}: " + "  ".join(f"{k.replace('_bw.png','').replace('Map','')}={v:+.3f}"
                                        for k, v in ranked[:4]))
        print(f"      worst: " + "  ".join(f"{k.replace('_bw.png','').replace('Map','')}={v:+.3f}"
                                           for k, v in ranked[-2:]))

    print("\n== rank position of each candidate map within each fog's ranking ==")
    print("(a correct pairing should rank #1 for its own fog)")
    return results


if __name__ == "__main__":
    main()
