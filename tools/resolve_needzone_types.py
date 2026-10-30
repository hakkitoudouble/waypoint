"""Resolve need-zone `AnimalTypeLocalizationName` hashes WITHOUT the hash function.

The need zones carry an opaque 32-bit animal type. The population files carry the
species roster of each reserve, decoded through the known NameHashId table. Both
are keyed by the same reserve id, so the rosters act as constraints: a type hash
seen in reserve R must map to a species that actually lives in R. Intersecting
those constraints across every reserve pins the mapping down.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw import adf, save  # noqa: E402

SAVES = Path.home() / "Documents" / "Avalanche Studios" / "COTW" / "Saves"
DATA = Path(__file__).resolve().parent.parent / "cotw" / "data"


def load_species_table() -> dict[int, str]:
    raw = json.loads((DATA / "species_hashes.json").read_text(encoding="utf-8"))
    return {int(k, 16): v for k, v in raw.items() if len(k) == 8}


def reserve_species(save_dir: Path, table: dict[int, str]) -> dict[int, set[str]]:
    """reserve index -> set of species names, read through the real definitions."""
    out: dict[int, set[str]] = {}
    for path in save.list_population_files(save_dir):
        index = save.reserve_index(path)
        try:
            doc = adf.parse_document(save.read_container(path).payload)
        except Exception:
            continue
        root_def, base = doc.root()
        pop_field = next((f for f in root_def.fields if f.name == "Populations"), None)
        if pop_field is None:
            continue
        array_def = doc.by_hash.get(pop_field.type_hash)
        element = doc.by_hash.get(array_def.element_type_hash) if array_def else None
        if element is None:
            continue

        try:
            offset, count = struct.unpack(
                "<II", doc._bytes(base + pop_field.offset, 8)  # noqa: SLF001 - internal by design
            )
        except adf.AdfError:
            continue

        names: set[str] = set()
        misses = 0
        for i in range(count):
            try:
                raw = struct.unpack_from(
                    "<I", doc.payload, doc.base + base + offset + i * element.size
                )[0]
            except struct.error:
                break
            name = table.get(raw)
            if name:
                names.add(name)
                misses = 0
            else:
                misses += 1
                if misses >= 2:
                    break
        if names:
            out[index] = names
    return out


def need_zone_types(save_dir: Path) -> dict[int, set[int]]:
    """reserve index -> set of opaque animal type hashes in that reserve's need zones."""
    doc = adf.parse_document(save.read_container(save_dir / "found_need_zones_adf").payload)
    root_def, base = doc.root()
    buckets = doc.parse_object(root_def, base)["NZData"]
    out: dict[int, set[int]] = {}
    for bucket in buckets:
        rid = bucket["ReserveId"]
        out[rid] = {z["AnimalTypeLocalizationName"] for z in bucket["NeedZoneData"]}
    return out


def main() -> int:
    dirs = save.find_save_dirs()
    if not dirs:
        print("no save dir")
        return 1
    save_dir = dirs[0]
    table = load_species_table()
    species = reserve_species(save_dir, table)
    types = need_zone_types(save_dir)

    print("reserves with a population roster:", sorted(species))
    print("reserves with need zones        :", sorted(types))
    print()

    # candidate species per opaque type: intersect the rosters of every reserve
    # in which that type appears
    candidates: dict[int, set[str]] = {}
    for rid, hashes in types.items():
        roster = species.get(rid, set())
        for h in hashes:
            candidates.setdefault(h, set()).update(roster)

    # narrow: a type must be in the roster of EVERY reserve it appears in
    for h in candidates:
        seen_in = [rid for rid, hs in types.items() if h in hs]
        allowed = None
        for rid in seen_in:
            roster = species.get(rid)
            if roster is None:
                continue
            allowed = set(roster) if allowed is None else (allowed & roster)
        candidates[h] = allowed if allowed is not None else set()

    print("=== constraints per opaque type hash ===")
    for h in sorted(candidates):
        cs = candidates[h]
        label = ", ".join(sorted(cs)) if 0 < len(cs) <= 6 else ("<none>" if not cs else f"{len(cs)} candidates")
        print("  %08X  seen in %-12s -> %s"
              % (h, str([r for r, hs in types.items() if h in hs]), label))

    unique = {h: next(iter(cs)) for h, cs in candidates.items() if len(cs) == 1}
    print("\nuniquely determined: %d/%d" % (len(unique), len(candidates)))
    for h, name in sorted(unique.items()):
        print("   %08X -> %s" % (h, name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
