"""Parse found_need_zones_adf: 64-byte zone records grouped under a ReserveId.

Field layout inferred from hexdump:
  rec+0  : uint32 ReserveId (constant within a group)
  rec+16 : float NeedZoneStartTimeHours
  rec+20 : float NeedZoneEndTimeHours
  rec+24 : uint32 AnimalType hash (matches cotwgc_species ids)
  rec+28 : uint32 NeedZoneScheduleIndex
"""
import os
import struct
import collections

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\theHunterCotW\dropzone\ui"
NZ = r"C:\Users\Maelo\Documents\mods\cotw-pop\work\save_decompressed\found_need_zones_adf.bin"
FOUND = r"C:\Users\Maelo\Documents\mods\cotw-pop\work\save_decompressed"


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


def main():
    sp = load_species()
    reserves = load_reserves()
    d = open(NZ, "rb").read()

    hits = []
    for h in sp:
        pat = struct.pack("<I", h)
        i = d.find(pat)
        while i != -1:
            hits.append(i)
            i = d.find(pat, i + 1)
    hits.sort()

    # split into runs of stride 64
    runs, cur = [], [hits[0]]
    for a, b in zip(hits, hits[1:]):
        if b - a == 64:
            cur.append(b)
        else:
            runs.append(cur)
            cur = [b]
    runs.append(cur)

    print(f"runs={len(runs)}  total hits={len(hits)}")
    by_res = collections.defaultdict(list)
    for run in runs:
        start = run[0] - 24
        if start < 0:
            continue
        rid = struct.unpack_from("<I", d, start)[0]
        names = []
        for off in run:
            h = struct.unpack_from("<I", d, off)[0]
            names.append(sp.get(h, hex(h)))
        by_res[rid].extend(names)

    print("\nreserve_id(from zone record) -> zone count, species")
    for rid in sorted(by_res):
        names = by_res[rid]
        uniq = sorted(set(names))
        print(f"  id={rid:<3} zones={len(names):<4} species({len(uniq)})={','.join(uniq)[:110]}")

    print("\n== consistency check vs cotwgc_reserves species lists ==")
    rmap = {rid: (name, set(hs)) for rid, name, hs in reserves}
    for rid in sorted(by_res):
        if rid not in rmap:
            continue
        name, hs = rmap[rid]
        obs = {h for h in []}  # placeholder
        obs_names = set(by_res[rid])
        exp_names = {sp.get(h, "") for h in hs}
        print(f"  id={rid:<3} {name[:44]:<44} observed={len(obs_names)} expected={len(exp_names)} "
              f"missing={sorted(exp_names - obs_names)[:4]} extra={sorted(obs_names - exp_names)[:4]}")

    print("\n== found_icons sizes (bytes) ==")
    for f in sorted(os.listdir(FOUND)):
        if f.startswith("found_icons_"):
            n = int(f.split("_")[-1].split(".")[0])
            print(f"  found_icons_{n:<3} {os.path.getsize(os.path.join(FOUND, f)):>6}")


if __name__ == "__main__":
    main()
