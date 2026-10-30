"""Solve the need-zone animal type -> species mapping as a constraint problem.

The need zones store an opaque 32-bit `AnimalTypeLocalizationName`. The population
files give each reserve's species roster, so a type that appears in reserve R must
map to a species that lives in R. Two extra constraints make this tractable:

* a type must map to a species present in EVERY reserve where that type appears;
* within one reserve, two different types cannot be the same species (a species
  has one animal type), so the assignment is injective per reserve.

We backtrack over the domains, enumerate solutions, and report the values that are
identical in all of them — those are proven without ever cracking the hash.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw import population, save  # noqa: E402

MAX_SOLUTIONS = 500


def build() -> tuple[dict[int, set[str]], dict[int, set[int]]]:
    dirs = save.find_save_dirs()
    if not dirs:
        raise SystemExit("no save dir")
    save_dir = dirs[0]

    rosters: dict[int, set[str]] = {}
    for path in save.list_population_files(save_dir):
        index = save.reserve_index(path)
        try:
            scanned = population.scan_population(path)
        except Exception:  # noqa: BLE001
            continue
        names = {a.species for a in scanned.animals if a.species and a.species != "Unknown"}
        if names:
            rosters[index] = names

    zones = population.scan_need_zones(save_dir)
    types: dict[int, set[int]] = {
        rid: {z.animal_type_hash for z in items} for rid, items in zones.items()
    }
    return rosters, types


def domains(rosters: dict[int, set[str]], types: dict[int, set[int]]) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for rid, hs in types.items():
        roster = rosters.get(rid)
        if roster is None:
            continue
        for h in hs:
            out.setdefault(h, set()).update(roster)
    # narrow to the intersection over every reserve the type appears in
    for h in list(out):
        for rid, hs in types.items():
            if h in hs and rid in rosters:
                out[h] &= rosters[rid]
    return out


def solve(domains: dict[int, set[str]], types: dict[int, set[int]]) -> tuple[int, dict[int, set[str]]]:
    """Enumerate solutions; return (solution_count, {type: values seen})."""
    # which types share a reserve (they must map to different species)
    neighbours: dict[int, set[int]] = defaultdict(set)
    for hs in types.values():
        for a in hs:
            if a not in domains:
                continue
            for b in hs:
                if a != b and b in domains:
                    neighbours[a].add(b)

    seen: dict[int, set[str]] = defaultdict(set)
    count = 0
    order = sorted((h for h in domains if domains[h]), key=lambda h: len(domains[h]))
    assignment: dict[int, str] = {}

    def backtrack(i: int) -> None:
        nonlocal count
        if count >= MAX_SOLUTIONS:
            return
        if i == len(order):
            count += 1
            for h, value in assignment.items():
                seen[h].add(value)
            return
        h = order[i]
        for candidate in sorted(domains[h]):
            if any(assignment.get(n) == candidate for n in neighbours[h]):
                continue
            assignment[h] = candidate
            backtrack(i + 1)
            del assignment[h]
            if count >= MAX_SOLUTIONS:
                return
        return

    backtrack(0)
    return count, seen


def main() -> int:
    rosters, types = build()
    doms = domains(rosters, types)
    print(f"{len(doms)} distinct animal types across {len(types)} reserves")

    empty = [h for h, d in doms.items() if not d]
    if empty:
        print(f"  {len(empty)} type(s) have an EMPTY domain — a roster is incomplete")

    count, seen = solve(doms, types)
    capped = " (capped)" if count >= MAX_SOLUTIONS else ""
    print(f"solutions found: {count}{capped}\n")

    resolved = {h: next(iter(v)) for h, v in seen.items() if len(v) == 1}
    ambiguous = {h: v for h, v in seen.items() if len(v) > 1}
    print(f"uniquely determined: {len(resolved)}/{len(doms)}")
    for h, name in sorted(resolved.items()):
        print(f"   {h:08X} -> {name}")

    if ambiguous:
        print(f"\nstill ambiguous: {len(ambiguous)}")
        for h, v in sorted(ambiguous.items()):
            print(f"   {h:08X} -> {sorted(v)[:6]}{'...' if len(v) > 6 else ''}")

    # Persist the mapping. Unresolved types are written as null on purpose: a
    # guess here would silently put the wrong animal on the map.
    import json

    out = {
        "_meta": {
            "note": (
                "Need-zone AnimalTypeLocalizationName -> species, derived by constraint "
                "solving over reserve rosters (a type must belong to a species present in "
                "every reserve where the type appears, and types within one reserve are "
                "distinct). The hash function itself is NOT cracked; these assignments are "
                "proven only up to consistency with the rosters in the scanned saves."
            ),
            "method": "constraint-solving_over_rosters",
            "reserves_used": sorted(types),
            "solutions_enumerated": count,
            "resolved": len(resolved),
            "unresolved": len(ambiguous),
        },
        "types": {
            f"{h:08X}": {"species": name, "confidence": "CONSTRAINED"}
            for h, name in sorted(resolved.items())
        },
        "unresolved": {
            f"{h:08X}": {"candidates": sorted(v), "confidence": "AMBIGUOUS"}
            for h, v in sorted(ambiguous.items())
        },
    }
    target = Path(__file__).resolve().parent.parent / "cotw" / "data" / "needzone_types.json"
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
