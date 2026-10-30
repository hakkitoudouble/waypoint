"""Prove the diamond / Great One alert actually fires.

The watcher only reports *new* animals, and the save on this machine does not happen to
spawn anything new while we test, so the detection path is exercised by removing one
diamond from the watcher's baseline: on the next poll it looks like a fresh spawn.

That checks the whole chain — identity key, diff, medal qualification, alert payload —
without needing the game to spawn a diamond on demand.

Run:  python tools/verify_alerts.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw import alerts as alerts_module  # noqa: E402
from cotw import save  # noqa: E402


def main() -> int:
    errors: list[str] = []
    print("=" * 68)
    print("diamond / great one alert verification")
    print("=" * 68)

    watcher = alerts_module.Watcher()
    watcher.poll()
    print(f"reserves primed : {len(watcher.primed)}")
    if not watcher.primed:
        print("FAIL: nothing to watch — no populated save found")
        return 1

    # find a diamond in the baseline so we can pretend it just spawned
    victim = None
    for reserve, keys in watcher.seen.items():
        for key in keys:
            if len(key) == 4 and isinstance(key[3], int):
                victim = (reserve, key)
                break
        if victim:
            break
    if victim is None:
        print("FAIL: could not find an animal key to work with")
        return 1
    reserve, key = victim
    print(f"target          : reserve {reserve}, species={key[1]}, gender={key[2]}, seed=0x{key[3]:08X}")

    # A diamond is needed to prove the qualification, so pick one deliberately.
    from cotw import population

    directory = save.find_save_dirs()[0]
    path = next(p for p in save.list_population_files(directory)
                if save.reserve_index(p) == reserve)
    diamonds = [a for a in population.scan_population(path).as_contract()["animals"]
                if a.get("medal") == "diamond"]
    print(f"diamonds in reserve {reserve}: {len(diamonds)}")
    if not diamonds:
        print("FAIL: this reserve has no diamond to test with")
        return 1
    target = diamonds[0]
    target_key = (reserve, target["species"], target["gender"], target.get("seed"))
    print(f"testing with    : {target['species']} TR={target.get('score')}")

    watcher.seen[reserve].discard(target_key)
    raised = watcher.poll(force=True)
    print(f"alerts raised   : {raised}")

    mine = [a for a in watcher.alerts if a.reserve == reserve]
    if not mine:
        errors.append("no alert was raised for the removed diamond")
    else:
        alert = mine[0]
        print(f"alert           : [{alert.reason}] {alert.species} "
              f"TR={alert.score:.2f} in {alert.reserve_name}")
        if alert.reason != "diamond":
            errors.append(f"expected reason 'diamond', got {alert.reason!r}")
        if alert.species != target["species"]:
            errors.append(f"alert species {alert.species!r} != {target['species']!r}")
        if alert.medal != "diamond":
            errors.append(f"alert medal {alert.medal!r} != 'diamond'")

    # the same baseline must not fire twice
    before = len(watcher.alerts)
    watcher.poll(force=True)
    if len(watcher.alerts) != before:
        errors.append("the same animal alerted twice")
    else:
        print("re-poll         : no duplicate, as expected")

    # a Great One must be recognised by its species record
    fake = {"species": alerts_module.GREAT_ONE_SPECIES, "gender": "female",
            "weight": 0.0, "score": 0.0, "medal": "none", "fur": None,
            "fur_rarity": None, "seed": 1}
    great = watcher._qualify(reserve, "test", fake)
    if great is None or great.reason != "great_one":
        errors.append("a Great One species was not recognised")
    else:
        print("great one       : recognised by species record")

    # and by a fabled fur, for robustness
    fake_fur = dict(fake, species="Black Bear", fur="great_one_black_bear_fabled_glacier")
    fabled = watcher._qualify(reserve, "test", fake_fur)
    if fabled is None or fabled.reason != "great_one":
        errors.append("a fabled fur was not recognised as a Great One")
    else:
        print("great one       : recognised by fabled fur")

    print("-" * 68)
    if errors:
        for error in errors:
            print("  x " + error)
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS - alerts fire on new diamonds and great ones, and only once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
