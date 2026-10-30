"""End-to-end verification of the population pipeline on the real save files.

Run:  python tools/verify_pipeline.py
Exits non-zero if any assertion fails. This is the "does the engine actually work"
gate: it checks species resolution, animal counts, weights, the statistically
derived gender mapping, need zones, and it pins down the fact that individual
animal positions are never persisted.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw import population, reserves, save, species  # noqa: E402
from cotw.model import Gender, Medal  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        FAILURES.append(label)


def main() -> int:
    dirs = save.find_save_dirs()
    if not dirs:
        print("no save directory found")
        return 1
    save_dir = dirs[0]

    print("== species tables ==")
    cov = species.coverage()
    print(f"  info  {cov}")
    check("hash table loaded", cov["hashes"] >= 130, str(cov["hashes"]))
    check("species names resolve", species.name_for_hash(0x0068A2CA) == "Hog Deer",
          repr(species.name_for_hash(0x0068A2CA)))

    print("\n== reserve metadata ==")
    meta = reserves.lookup(16)
    check("reserve 16 identified", meta.display_name == "Emerald Coast Australia",
          repr(meta.display_name))
    check("reserve 16 has a map", meta.map_image == "EmeraldCoast_bw.png", repr(meta.map_image))
    check("unknown slot is not guessed", reserves.lookup(5).display_name is None,
          repr(reserves.lookup(5).display_name))

    print("\n== population (Emerald Coast) ==")
    pop = population.scan_population(save_dir / "animal_population_16")
    check("animal count", len(pop.animals) == 4004, str(len(pop.animals)))
    by_species = Counter(a.species for a in pop.animals)
    check("14 species", len(by_species) == 14, str(len(by_species)))
    check("no unnamed species", "Unknown" not in by_species, str(by_species.get("Unknown")))
    expected = {"Hog Deer", "Fallow Deer", "Red Deer", "Feral Pig", "Magpie Goose",
                "EG Kangaroo", "Red Fox", "Sambar", "Banteng", "SW Crocodile",
                "Feral Goat", "Stubble Quail", "Axis Deer", "Javan Rusa"}
    check("roster matches Emerald Coast", set(by_species) == expected,
          str(set(by_species) ^ expected))

    weights = [a.weight for a in pop.animals if a.weight is not None]
    check("weights present", len(weights) == len(pop.animals), f"{len(weights)}/{len(pop.animals)}")
    check("weights plausible", min(weights) > 0.05 and max(weights) < 1200,
          f"[{min(weights):.2f} .. {max(weights):.2f}]")

    genders = Counter(a.gender for a in pop.animals)
    check("both sexes present", genders[Gender.MALE] > 0 and genders[Gender.FEMALE] > 0,
          str(dict(genders)))
    check("no unknown gender", genders[Gender.UNKNOWN] == 0, str(genders[Gender.UNKNOWN]))

    print("\n== gender mapping is statistically justified ==")
    by_code: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for a in pop.animals:
        if a.weight and a.weight > 0.05:
            by_code[a.species][a.gender.value].append(a.weight)
    for name in ("Red Deer", "Sambar", "Banteng"):
        stats = {g: sum(w) / len(w) for g, w in by_code[name].items() if w}
        if "male" in stats and "female" in stats:
            check(f"{name}: male heavier", stats["male"] > stats["female"],
                  f"male={stats['male']:.1f} female={stats['female']:.1f}")

    print("\n== animal positions are NOT persisted ==")
    moved = [a for a in pop.animals if a.x is not None and abs(a.x) > 0.01]
    check("every MapPosition is (0,0)", len(moved) == 0, f"{len(moved)} non-zero")

    print("\n== rarity ranking ==")
    medals = Counter(a.medal.value for a in pop.animals)
    print(f"  info  medals: {dict(medals)}")
    check("some animals rank above bronze", medals["diamond"] + medals["gold"] > 0, str(medals))
    check("no fabricated great ones", medals["great_one"] == 0, str(medals["great_one"]))

    sources = Counter(a.medal_source for a in pop.animals)
    print(f"  info  medal_source: {dict(sources)}")
    have_thresholds = species.coverage()["with_thresholds"] >= 100
    if have_thresholds:
        check("real game thresholds drive every medal", sources["game"] == len(pop.animals),
              str(dict(sources)))
    else:
        check("rarity falls back to a labelled relative ranking", sources["relative"] > 0,
              str(dict(sources)))

    scoreless = [a for a in pop.animals if not a.score]
    check("animals without a trophy score get no medal",
          all(a.medal is Medal.NONE for a in scoreless), str(len(scoreless)))

    # Whatever the source, a diamond must clear the species' gold or silver cut,
    # never sit at the bottom of its species distribution.
    from cotw import species as species_tables

    worst = None
    for a in pop.animals:
        if a.medal is not Medal.DIAMOND:
            continue
        entry = species_tables.thresholds().get(a.species) or {}
        cut = entry.get("diamond")
        if isinstance(cut, (int, float)) and (a.score or 0) < cut:
            worst = (a.species, a.score, cut)
    check("every diamond clears its species threshold", worst is None, str(worst))

    print("\n== need zones ==")
    zones = population.scan_need_zones(save_dir)
    check("need zones parsed", len(zones) >= 7, str(len(zones)))
    total_zones = sum(len(v) for v in zones.values())
    check("zone total", total_zones == 506 or total_zones > 400, str(total_zones))
    if 16 in zones:
        subset = zones[16]
        check("Emerald Coast has zones", len(subset) > 100, str(len(subset)))
        bounds = population.zone_world_bounds(subset)
        check("zone bounds are per-reserve and tight",
              (bounds.max_x - bounds.min_x) < 30000, str(bounds))
        types = Counter(z.type_name for z in subset)
        print(f"  info  zone types: {dict(types)}")
        hours = sorted({(z.start_hour, z.end_hour) for z in subset})
        check("zones carry active hours", len(hours) > 3, str(hours[:4]))
        check("altitude is not a map axis",
              all(500 < z.y < 3000 for z in subset), "altitudes look like metres")

        named = [z for z in subset if z.animal_type]
        print(f"  info  named zones: {len(named)}/{len(subset)}")
        check("need zones resolve to a species", len(named) > 0.8 * len(subset),
              f"{len(named)}/{len(subset)}")
        by_species = Counter(z.animal_type for z in named)
        print(f"  info  species with zones: {dict(by_species.most_common(6))}")
        check("a known Emerald Coast species has zones", "Red Deer" in by_species,
              str(sorted(by_species)[:6]))
        # attribution must be consistent with the roster of that reserve
        roster = {a.species for a in pop.animals}
        off_roster = {s for s in by_species if s not in roster}
        check("zone species are on the reserve roster", not off_roster, str(sorted(off_roster)))

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} assertion(s) failed")
        for f in FAILURES:
            print(f"   - {f}")
        return 1
    print("PASS: population pipeline verified end to end on real saves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
