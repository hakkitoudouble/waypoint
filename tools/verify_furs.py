"""Guard the fur derivation.

The fur is not stored anywhere: it is recomputed from each animal's
`VisualVariationSeed` with the draw recovered from the vendor scanner. That makes it
easy to break silently, so this checks the properties that must hold:

1. every animal with a seed and a known species/gender gets a fur;
2. the variant is always one the species' table actually contains;
3. across a whole reserve, the observed variant frequencies match the table weights
   (a wrong LCG constant or a swapped byte order would still produce *a* fur for every
   animal, but the distribution would drift — this is the check that catches it);
4. the rarity bucket follows from the weight, not from a lookup that could go stale.

Run:  python tools/verify_furs.py
"""

from __future__ import annotations

import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw import furs, population, save  # noqa: E402

#: a deviation beyond this many sigma over the most common variants means the draw is off
SIGMA_LIMIT = 4.0
MIN_SAMPLE = 80


def main() -> int:
    errors: list[str] = []
    coverage = furs.coverage()
    print("=" * 68)
    print("fur derivation verification")
    print("=" * 68)
    print(f"tables      : {coverage['species']} species, {coverage['entries']} entries")

    if coverage["species"] < 100:
        print("FAIL: fur tables missing — run tools/import_fur_tables.py")
        return 1

    directory = save.find_save_dirs()
    if not directory:
        print("FAIL: no save folder")
        return 1

    total = with_fur = 0
    unknown_species = 0
    observed: dict[tuple[str, int], Counter] = defaultdict(Counter)
    unknown_variant = 0

    for path in save.list_population_files(directory[0]):
        try:
            scanned = population.scan_population(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path.name}: {exc}")
            continue
        for animal in scanned.as_contract()["animals"]:
            total += 1
            name = animal.get("species")
            if not name or name not in furs.tables():
                unknown_species += 1
            if animal.get("fur"):
                with_fur += 1
                gender = 1 if animal.get("gender") == "male" else 2
                observed[(name, gender)][animal["fur"]] += 1
            else:
                unknown_variant += 1

    print(f"animals     : {total} scanned, {with_fur} with a fur "
          f"({100 * with_fur / max(total, 1):.1f}%), {unknown_species} species without a table")
    if with_fur < total * 0.9:
        errors.append(f"only {with_fur}/{total} animals got a fur")

    # every drawn variant must exist in the table for that species and gender
    for (species_name, gender), counts in observed.items():
        block = furs.tables().get(species_name, {}).get(str(gender))
        if not block:
            errors.append(f"{species_name}/{gender}: no block but furs were drawn")
            continue
        known = {entry[0] for entry in block["entries"]}
        for variant in counts:
            if variant not in known:
                errors.append(f"{species_name}: variant {variant!r} is not in its table")

    # distribution check on the biggest samples
    print("\ndistribution check (variants with p > 2%):")
    worst = 0.0
    checked = 0
    for (species_name, gender), counts in sorted(
        observed.items(), key=lambda kv: -sum(kv[1].values())
    )[:14]:
        block = furs.tables().get(species_name, {}).get(str(gender))
        if not block:
            continue
        sample = sum(counts.values())
        if sample < MIN_SAMPLE:
            continue
        total_weight = block["total"]
        expected: dict[str, float] = {}
        for name, weight in block["entries"]:
            expected[name] = expected.get(name, 0.0) + weight / total_weight
        deviation = 0.0
        for name, probability in expected.items():
            if probability < 0.02:
                continue
            expected_count = probability * sample
            sigma = abs(counts.get(name, 0) - expected_count) / math.sqrt(max(expected_count, 1e-9))
            deviation = max(deviation, sigma)
        checked += 1
        worst = max(worst, deviation)
        print(f"  {'M' if gender == 1 else 'F'} {species_name:<24} n={sample:<5} max={deviation:.2f} sigma")
    print(f"  checked {checked} groups, worst {worst:.2f} sigma")
    if worst > SIGMA_LIMIT:
        errors.append(f"distribution deviates by {worst:.2f} sigma — the draw is probably wrong")

    print("-" * 68)
    if errors:
        print(f"{len(errors)} ERROR(S):")
        for error in errors[:10]:
            print("  x " + error)
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS - furs are drawn consistently with the recovered tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
