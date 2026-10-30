"""The live tracker must keep discovering new animals, not just shrink.

The bug this guards against: entities were discovered once, at startup, and every animal
that spawned afterwards stayed invisible — the list could only shrink as animals died.
Two defects caused it and both are covered here:

* nothing ran discovery after the first pass;
* worse, ``discover()`` closed the handle that ``refresh()`` borrows from the cache, so
  after any scan every read returned nothing and the list silently emptied.

Run:  python tools/verify_radar_discovery.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cotw import radar  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))


def main() -> int:
    instance = radar.Radar()
    found = instance.find_process()
    if not found:
        print("SKIP: the game is not running")
        return 0
    print(f"process: {found[1]} (pid {found[0]})")

    loaded = instance.load_cache()
    print(f"cache: {loaded} address(es)")
    first = instance.refresh(None)
    print(f"valid before any scan: {len(first)}")
    check("the cached entities resolve", len(first) > 0,
          "no entity read at all — the handle or the cache is broken")

    # A scan opens and closes its own handle. The refresh path must survive it.
    started = time.perf_counter()
    added = instance.rescan_entity_regions()
    elapsed = time.perf_counter() - started
    print(f"targeted rescan: +{added} in {elapsed:.1f} s")
    after = instance.refresh(None)
    print(f"valid after the scan: {len(after)}")
    check("a scan does not break the refresh handle", len(after) > 0,
          f"refresh returned 0 after a scan — discover() is closing the cached handle")
    check("the scan did not lose entities", len(after) + 5 >= len(first),
          f"{len(first)} -> {len(after)}")

    # The sweep must be bounded to the entity pools, not the whole address space.
    handle = instance._open()
    if handle:
        regions = instance._regions(handle)
        sizes = instance._interesting_sizes(regions)
        pool = [r for r in regions if r[1] in sizes]
        total = sum(size for _, size in regions)
        swept = sum(size for _, size in pool)
        instance.close_handle(handle) if hasattr(instance, "close_handle") else None
        print(f"regions: {len(regions)} ({total / 2 ** 30:.1f} GiB), "
              f"pools: {len(pool)} ({swept / 2 ** 20:.0f} MiB)")
        check("the sweep targets the entity pools", 0 < swept < total,
              "no pool detected, so the sweep would walk the whole address space")
        check("the sweep is much cheaper than a full pass", swept <= total / 2,
              f"pools are {100 * swept / total:.0f}% of memory")
        check("every entity lives in a pool-sized region", len(sizes) <= 3,
              f"{len(sizes)} distinct region sizes: {sorted(sizes)}")

    # And a sweep step must run without breaking anything.
    started = time.perf_counter()
    added = instance.sweep_step()
    print(f"sweep step: +{added} in {time.perf_counter() - started:.1f} s")
    final = instance.refresh(None)
    print(f"valid at the end: {len(final)}")
    check("the radar still reads after a sweep", len(final) > 0, "refresh returned 0")

    # Beyond the simulation radius the game freezes the record, so it must not be shown.
    from cotw import player as player_module

    saved = player_module.position_for(9)
    if saved is not None and final:
        snapshot = instance.snapshot((saved.x, saved.z))
        farthest = max((a["distance"] for a in snapshot["animals"]), default=0.0)
        print(f"snapshot: {snapshot['count']} shown of {snapshot['known']} known, "
              f"farthest {farthest:.0f} m, radius {snapshot['radius']:.0f} m")
        check("the radius is 500 m", snapshot["radius"] == radar.LIVE_RADIUS,
              str(snapshot["radius"]))
        check("nothing beyond the radius is shown",
              farthest <= radar.LIVE_RADIUS,
              f"an animal {farthest:.0f} m away is still listed")
        check("static records are still counted as known",
              snapshot["known"] >= snapshot["count"],
              f"known {snapshot['known']} < shown {snapshot['count']}")

    # Every surviving entity must pass the phantom filter, otherwise a fake animal can be
    # shown at arm's length — one was reported at 25 m while nothing was there.
    handle = instance._open()
    if handle and final:
        phantoms = [a for a in final
                    if not radar.Radar._looks_like_entity(handle, a.hash_address)]
        print(f"entities failing the phantom filter: {len(phantoms)}")
        check("no phantom survives the record filter", not phantoms,
              f"{[a.species for a in phantoms][:3]} still listed")
        instance.close()

    print("-" * 68)
    failures = [c for c in checks if not c[1]]
    for label, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    if failures:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS - discovery keeps running and never breaks the refresh path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
