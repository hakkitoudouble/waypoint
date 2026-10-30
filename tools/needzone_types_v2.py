"""Try to pin need-zone animal types to species using reserve rosters.

Idea: a need zone's animal type must belong to a species that actually lives in
that reserve. The population files give each reserve's roster (decoded through the
known NameHashId table), so the rosters act as constraints.

If the need-zone `ReserveId` uses the same id space as the save slot, then every
reserve's set of zone types must be a subset of that reserve's roster. If it does
not, we look for which roster could contain each bucket instead.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw import population, save  # noqa: E402


def main() -> int:
    dirs = save.find_save_dirs()
    if not dirs:
        print("no save dir")
        return 1
    save_dir = dirs[0]

    rosters: dict[int, set[str]] = {}
    for path in save.list_population_files(save_dir):
        index = save.reserve_index(path)
        try:
            doc = population.scan_population(path)
        except Exception as exc:  # noqa: BLE001 - a broken reserve must not stop the scan
            print(f"  skip {path.name}: {exc}")
            continue
        names = {a.species for a in doc.animals if a.species and a.species != "Unknown"}
        if names:
            rosters[index] = names

    zones = population.scan_need_zones(save_dir)
    types: dict[int, set[int]] = {
        rid: {z.animal_type_hash for z in items} for rid, items in zones.items()
    }

    print("rosters:", {k: len(v) for k, v in sorted(rosters.items())})
    print("zone buckets:", {k: (len(v), len(types[k])) for k, v in sorted(zones.items())})
    print()

    print("=== does each bucket's type set fit the roster of the SAME slot? ===")
    for rid in sorted(types):
        roster = rosters.get(rid)
        if roster is None:
            print(f"  bucket {rid:>2}  no roster for this slot")
            continue
        # a type is 'explained' if we can assign it some species in the roster;
        # without the hash mapping we can only count how many types have at least
        # one candidate at all, so report the ratio of types to species
        print(f"  bucket {rid:>2}  {len(types[rid])} zone-types vs {len(roster)} species"
              f"  {'OK (types <= species)' if len(types[rid]) <= len(roster) else 'IMPOSSIBLE'}")

    print("\n=== per type: slots where it appears, and rosters containing listed species ===")
    seen: dict[int, list[int]] = defaultdict(list)
    for rid, hs in types.items():
        for h in hs:
            seen[h].append(rid)
    for h in sorted(seen):
        where = seen[h]
        shared = None
        for rid in where:
            roster = rosters.get(rid)
            if roster is None:
                continue
            shared = set(roster) if shared is None else (shared & roster)
        label = "no shared species" if not shared else f"{len(shared)} shared: {sorted(shared)[:4]}"
        print(f"  {h:08X} in {str(where):<22} {label}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
