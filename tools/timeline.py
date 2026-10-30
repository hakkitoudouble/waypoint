"""Timeline: save-file writes per index vs harvest events (unique species -> reserve)."""
import os
import re
from datetime import datetime, timezone

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\theHunterCotW\dropzone\ui"
SAVE = r"C:\Users\Maelo\Documents\Avalanche Studios\COTW\Saves\76561199084637132"
SINCE = 1688000000  # 2023-06-29


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


def ts(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M")


def main():
    species = load_species()
    reserves = load_reserves()
    sp2res = {}
    for rid, name, hs in reserves:
        for h in hs:
            sp2res.setdefault(h, set()).add((rid, name))

    events = []
    for f in os.listdir(SAVE):
        m = re.match(r"(animal_population_|adf_fog_of_war_data_faster_|found_icons_)(\d+)$", f)
        if not m:
            continue
        n = int(m.group(2))
        mt = os.path.getmtime(os.path.join(SAVE, f))
        if mt >= SINCE:
            events.append((mt, "WRITE", f"idx {n:>2} {m.group(1)[:6]} {f}"))

    for line in open(os.path.join(GAME, "cotwgc_history.txt"), encoding="utf-8-sig"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f = line.split()
        if f[0] == "h" and len(f) >= 7:
            t = int(f[4])
            if t < SINCE:
                continue
            sp = int(f[1])
            cands = sp2res.get(sp, set())
            label = species.get(sp, str(sp))
            tag = ""
            if len(cands) == 1:
                tag = "  <- UNIQUE: " + next(iter(cands))[1]
            events.append((t, "KILL", f"{label:<22}{tag}"))

    events.sort()
    for t, kind, msg in events:
        print(f"{ts(t)}  {kind:5} {msg}")


if __name__ == "__main__":
    main()
