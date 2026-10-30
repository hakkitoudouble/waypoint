"""Prove the appeared / disappeared delta feed and the data version.

The game cannot be asked to spawn or remove an animal on cue, so the diff is exercised
against the watcher's own baseline:

* removing one key from the seeded ``seen`` state makes that animal look freshly
  spawned -> exactly one ``appeared`` record, and nothing disappeared;
* adding one key the population file does not contain makes it look like an animal that
  vanished -> exactly one ``disappeared`` record, and nothing appeared;
* the very first scan of a file produces neither — it is a baseline.

``data_version`` is checked through its internal stamp helper with a *fabricated* mtime:
the app is read-only, and touching a real save would be a destructive way to prove it
changes. The history store is exercised against throwaway files under the system temp
folder, so the test never invents days in the real trend; the watcher's own polls do
legitimately add the current UTC day's point for the reserves they scan.

Run:  python tools/verify_delta.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw import alerts as alerts_module  # noqa: E402
from cotw import history, save, server  # noqa: E402

#: the exact record the API promises for one delta
CHANGE_FIELDS = {
    "reserve",
    "reserve_name",
    "species",
    "gender",
    "weight",
    "score",
    "medal",
    "fur",
    "fur_rarity",
    "seed",
    "seen_at",
    "direction",
}

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        FAILURES.append(label)


def _rounds(value: object, digits: int) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), digits)


def main() -> int:
    print("=" * 68)
    print("delta / data version / history verification")
    print("=" * 68)

    watcher = alerts_module.Watcher()
    raised = watcher.poll()
    snapshot = watcher.snapshot()

    print(f"reserves primed : {len(watcher.primed)}")
    if not watcher.primed:
        print("FAIL: nothing to watch — no populated save found")
        return 1

    # -- 1. the baseline ----------------------------------------------------
    print("\n== baseline ==")
    check("baseline raises no alert", raised == 0, str(raised))
    check("baseline alerts list is empty", snapshot["alerts"] == [], str(snapshot["alerts"][:1]))
    check("baseline reports no appeared", snapshot["changes"]["appeared"] == [],
          str(snapshot["changes"]["appeared"]))
    check("baseline reports no disappeared", snapshot["changes"]["disappeared"] == [],
          str(snapshot["changes"]["disappeared"]))
    check("baseline still stamps `since`", snapshot["changes"]["since"] > 0,
          str(snapshot["changes"]["since"]))
    check("baseline keeps no delta records at all", watcher.changes == [],
          str(len(watcher.changes)))
    check("baseline keeps no spawn batch", snapshot["spawns"]["animals"] == [],
          str(snapshot["spawns"]["animals"][:1]))
    check("baseline stamps no spawn time", snapshot["spawns"]["at"] == 0.0,
          str(snapshot["spawns"]["at"]))

    # -- 1b. the /api/alerts payload stays backward compatible -------------
    print("\n== /api/alerts payload ==")
    legacy = {"alerts", "count", "reserves_watched", "last_poll", "poll_seconds",
              "error", "rule"}
    check("every legacy key is still there", legacy <= set(snapshot),
          str(sorted(legacy - set(snapshot))))
    check("the changes body has appeared / disappeared / since",
          set(snapshot["changes"]) == {"appeared", "disappeared", "since"},
          str(sorted(snapshot["changes"])))
    check("data_version is part of the payload", "data_version" in snapshot,
          str(sorted(snapshot)))
    check("the spawns block has at / count / animals / per_reserve",
          set(snapshot["spawns"]) == {"at", "count", "animals", "per_reserve"},
          str(sorted(snapshot["spawns"])))
    sample_alert = watcher._qualify(next(iter(sorted(watcher.primed))), "test", {
        "species": "Red Deer", "gender": "male", "weight": 200.0, "score": 999.0,
        "medal": "diamond", "fur": None, "fur_rarity": None, "seed": 1,
    })
    check("an alert row still has exactly the old fields",
          sample_alert is not None and set(sample_alert.as_dict()) == {
              "id", "reserve", "reserve_name", "species", "gender", "weight",
              "score", "medal", "fur", "fur_rarity", "seen_at", "reason"},
          "alert row keys changed")

    # pick one real animal to work with
    target = None
    for index, population_seen in sorted(watcher.seen.items()):
        for key, animal in population_seen.items():
            if len(key) == 4 and isinstance(key[3], int) and animal.get("species"):
                target = (index, key, animal)
                break
        if target is not None:
            break
    if target is None:
        print("FAIL: could not find an animal record in the baseline")
        return 1
    reserve, victim_key, victim = target
    print(f"target          : reserve {reserve}, {victim['species']} "
          f"{victim.get('gender')}, seed=0x{victim_key[3]:08X}")

    # -- 2. one appeared ----------------------------------------------------
    print("\n== appeared ==")
    # The old `seen` was a set of keys; `discard` must still work on the new mapping.
    watcher.seen[reserve].discard(victim_key)
    watcher.poll(force=True)
    snapshot = watcher.snapshot()
    appeared = snapshot["changes"]["appeared"]
    # The game may be running while this test runs, so a reserve it rewrites can
    # legitimately report deltas of its own. Everything here is scoped to the one
    # reserve whose seeded state was manipulated.
    ours = [change for change in appeared if change["reserve"] == reserve]
    elsewhere = [change for change in appeared if change["reserve"] != reserve]
    if elsewhere:
        print(f"  info  {len(elsewhere)} delta record(s) came from other reserves "
              f"(the game is writing saves while we run)")
    check("removing one key gives exactly one appeared", len(ours) == 1,
          f"{len(ours)} for reserve {reserve}")
    check("that same scan reports nothing disappeared for it",
          [c for c in snapshot["changes"]["disappeared"] if c["reserve"] == reserve] == [],
          str(snapshot["changes"]["disappeared"][:1]))
    if len(ours) == 1:
        record = ours[0]
        print(f"  info  {record}")
        check("the record has exactly the documented fields", set(record) == CHANGE_FIELDS,
              str(sorted(set(record) ^ CHANGE_FIELDS)))
        check("direction is 'appeared'", record["direction"] == "appeared", record["direction"])
        check("it names its reserve", record["reserve"] == reserve and bool(record["reserve_name"]),
              f"{record['reserve']} {record['reserve_name']!r}")
        check("its species / gender match the animal",
              record["species"] == victim["species"]
              and record["gender"] == victim["gender"],
              f"{record['species']} {record['gender']}")
        check("its medal matches the animal",
              record["medal"] == (victim.get("medal") or "none"), record["medal"])
        check("its weight is a float rounded to 2 dp",
              record["weight"] == _rounds(victim.get("weight"), 2), str(record["weight"]))
        check("its score is a float rounded to 3 dp",
              record["score"] == _rounds(victim.get("score"), 3), str(record["score"]))
        check("its fur fields survive", record["fur"] == victim.get("fur")
              and record["fur_rarity"] == victim.get("fur_rarity"),
              f"{record['fur']} / {record['fur_rarity']}")
        check("it carries the seed the list will match on",
              record["seed"] == victim_key[3], str(record["seed"]))

    # -- 2b. the rolling "just spawned" shortlist the list paints green ------
    print("\n== spawn shortlist ==")
    batch = snapshot["spawns"]
    check("count matches the list", batch["count"] == len(batch["animals"]),
          f"{batch['count']} vs {len(batch['animals'])}")
    check("the shortlist is stamped when it was seen", batch["at"] > 0, str(batch["at"]))
    check("the payload announces the per-reserve cap", batch.get("per_reserve") == 5,
          str(batch.get("per_reserve")))
    ours_spawn = [s for s in batch["animals"] if s["reserve"] == reserve]
    check("the animal that just appeared is in the shortlist", len(ours_spawn) == 1,
          f"{len(ours_spawn)} for reserve {reserve}")
    if ours_spawn:
        check("the shortlist record is the delta record",
              ours_spawn[0] == ours[0], f"{ours_spawn[0]} != {ours[0]}")

    # -- 2c. it keeps the five newest, newest first, once each --------------
    print("\n== five most recent ==")
    now = time.time()
    probe_reserve = 4242
    for i in range(8):
        watcher._remember_spawns([{
            "reserve": probe_reserve, "reserve_name": "Probe", "species": "Red Deer",
            "gender": "male", "weight": 200.0 + i, "score": 100.0 + i, "medal": "gold",
            "fur": None, "fur_rarity": None, "seed": 1000 + i,
            "seen_at": now + i, "direction": "appeared",
        }])
    rolling = watcher.snapshot()["spawns"]["animals"]
    mine = [record for record in rolling if record["reserve"] == probe_reserve]
    check("only the five newest are kept", len(mine) == 5, f"{len(mine)} kept")
    check("they are the five newest, newest first",
          [record["seed"] for record in mine] == [1007, 1006, 1005, 1004, 1003],
          str([record["seed"] for record in mine]))
    watcher._remember_spawns([dict(mine[0])])
    again = [record for record in watcher.snapshot()["spawns"]["animals"]
             if record["reserve"] == probe_reserve]
    check("the same animal is not recorded twice", len(again) == 5, f"{len(again)} kept")
    check("another reserve keeps its own shortlist",
          [record for record in rolling if record["reserve"] == reserve] != [],
          "the probe's spawns wiped the real reserve's entries")

    # -- 2d. the shortlist survives a restart -------------------------------
    print("\n== shortlist persistence ==")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "spawns.json"
        writer = alerts_module.Watcher()
        writer.spawns_file = path
        for i in range(6):
            writer._remember_spawns([{
                "reserve": 7, "reserve_name": "Test", "species": "Mule Deer",
                "gender": "female", "weight": 90.0 + i, "score": 80.0 + i,
                "medal": "silver", "fur": None, "fur_rarity": None, "seed": 700 + i,
                "seen_at": now + i, "direction": "appeared",
            }])
        check("the shortlist is written to disk", path.is_file(), str(path))
        restored = alerts_module.Watcher()
        restored.spawns_file = path
        loaded = restored.load_spawns()
        restored_snapshot = restored.snapshot()["spawns"]
        check("a fresh watcher reloads it", loaded == 5, f"loaded {loaded}")
        check("the reloaded shortlist is the same five",
              [record["seed"] for record in restored_snapshot["animals"]]
              == [705, 704, 703, 702, 701],
              str([record["seed"] for record in restored_snapshot["animals"]]))
        check("a watcher without a file writes nothing",
              alerts_module.Watcher().spawns_file is None, "default must stay in memory")

    # -- 3. one disappeared -------------------------------------------------
    print("\n== disappeared ==")
    current_keys = {key[3] for key in watcher.seen[reserve]}
    fake_seed = 0xFEEDF00D
    while fake_seed in current_keys:
        fake_seed = (fake_seed + 1) & 0xFFFFFFFF
    fake = dict(victim, seed=fake_seed)
    fake_key = (reserve, fake.get("species"), fake.get("gender"), fake_seed)
    watcher.seen[reserve][fake_key] = fake

    watcher.poll(force=True)
    snapshot = watcher.snapshot()
    appeared = snapshot["changes"]["appeared"]
    disappeared = snapshot["changes"]["disappeared"]
    ours = [change for change in disappeared if change["reserve"] == reserve]
    check("a key the file does not contain gives exactly one disappeared",
          len(ours) == 1, f"{len(ours)} for reserve {reserve}")
    check("that same scan reports nothing appeared for it",
          [c for c in appeared if c["reserve"] == reserve] == [],
          str([c for c in appeared if c["reserve"] == reserve][:1]))
    if len(ours) == 1:
        record = ours[0]
        print(f"  info  {record}")
        check("the record has exactly the documented fields", set(record) == CHANGE_FIELDS,
              str(sorted(set(record) ^ CHANGE_FIELDS)))
        check("direction is 'disappeared'", record["direction"] == "disappeared",
              record["direction"])
        check("it still carries the vanished animal's details",
              record["species"] == fake["species"]
              and record["medal"] == (fake.get("medal") or "none")
              and record["weight"] == _rounds(fake.get("weight"), 2),
              str(record))
        check("it names its reserve", record["reserve"] == reserve and bool(record["reserve_name"]),
              f"{record['reserve']} {record['reserve_name']!r}")

    # A scan that only saw removals must not clear the green marking.
    spawned_this_cycle = list(appeared)
    if spawned_this_cycle:
        print(f"  info  {len(spawned_this_cycle)} spawn(s) landed during this scan "
              f"(the game is writing saves) — the batch check is skipped")
    else:
        check("a removal-only scan keeps the previous spawn batch",
              [s for s in snapshot["spawns"]["animals"] if s["reserve"] == reserve] != [],
              "the batch was erased by a scan that only saw removals")

    # -- 4. the bounded internal history -----------------------------------
    print("\n== change history ==")
    check("the internal delta history is bounded",
          len(watcher.changes) <= alerts_module.MAX_CHANGES, str(len(watcher.changes)))
    check("it is newest first",
          all(a["seen_at"] >= b["seen_at"]
              for a, b in zip(watcher.changes, watcher.changes[1:])),
          str([c["seen_at"] for c in watcher.changes]))
    watcher.poll()  # no forced rescan: only files that changed on disk are looked at
    idle = watcher.snapshot()["changes"]
    check("an idle poll still stamps a fresh `since`", idle["since"] > 0, str(idle["since"]))
    check("an idle poll invents no delta for the target reserve",
          [c for c in idle["appeared"] + idle["disappeared"] if c["reserve"] == reserve] == [],
          str(idle))

    # -- 5. data version ----------------------------------------------------
    print("\n== data_version ==")
    directory = save.find_save_dirs()[0]
    stamps = alerts_module.population_stamps(directory)
    version = alerts_module.version_from_stamps(stamps)
    print(f"  info  {version!r} over {len(stamps)} population file(s)")
    check("data_version is a 16-char hex digest",
          isinstance(version, str) and len(version) == 16
          and all(ch in "0123456789abcdef" for ch in version), repr(version))
    check("the same stamps give the same version (nothing changed)",
          version == alerts_module.version_from_stamps(list(stamps)), repr(version))

    # The watcher's snapshot must publish the digest of the files on disk. Comparing a
    # digest sampled at the watcher's last poll with one recomputed now is a race while
    # the game is running: it can rewrite a save between the two. So force a poll first,
    # then require the file stamps not to move during the comparison — and only then
    # assert equality. If the game keeps writing through every attempt, say so instead of
    # reporting a failure the code does not deserve; the digest function's determinism and
    # its sensitivity to mtime/size are already proven below.
    snap_version = current = ""
    comparable = False
    for _attempt in range(4):
        watcher.poll(force=True)
        before = alerts_module.population_stamps(directory)
        snap_version = watcher.snapshot()["data_version"]
        after = alerts_module.population_stamps(directory)
        current = alerts_module.version_from_stamps(after)
        if before == after:
            comparable = True
            break
    if comparable:
        check("the watcher publishes the on-disk digest",
              snap_version == current, f"{snap_version!r} vs {current!r}")
    else:
        print("  info  the game kept rewriting a save during the check; "
              "the watcher digest could not be compared live")

    # Fabricate an mtime bump: the real save is never touched.
    bumped = [(name, mtime + 60.0, size) for name, mtime, size in stamps]
    bumped_version = alerts_module.version_from_stamps(bumped)
    check("touching one file's mtime changes the version",
          bumped_version != version, f"{bumped_version} vs {version}")
    check("a fabricated version is deterministic too",
          bumped_version == alerts_module.version_from_stamps(bumped))
    check("a fabricated size change also changes it",
          alerts_module.version_from_stamps(
              [(name, mtime, size + 1) for name, mtime, size in stamps]) != version)
    check("no watched files means no version",
          alerts_module.version_from_stamps([]) == "")

    # The stat path itself, exercised on disposable copies in the temp folder.
    with tempfile.TemporaryDirectory() as temporary:
        copies = Path(temporary)
        for index in range(3):
            (copies / f"animal_population_{index}").write_bytes(b"\0" * 16)
        first = alerts_module.data_version(copies)
        check("the file-stat path is stable on untouched files",
              bool(first) and first == alerts_module.data_version(copies), repr(first))
        touched = copies / "animal_population_1"
        later = touched.stat().st_mtime + 60.0
        os.utime(touched, (later, later))
        check("a real mtime touch changes it",
              alerts_module.data_version(copies) != first, repr(first))

    # -- 6. daily history ---------------------------------------------------
    print("\n== daily population history ==")
    points = history.history_for(reserve)
    check("the watched reserve has a history point", bool(points), str(points[-1:]))
    check("points are sorted by date",
          [p["date"] for p in points] == sorted(p["date"] for p in points),
          str([p["date"] for p in points]))
    check("there is at most one point per calendar day",
          len({p["date"] for p in points}) == len(points), str(len(points)))
    if points:
        utc_today = datetime.now(timezone.utc).date().isoformat()
        check("today (UTC) has a point", any(p["date"] == utc_today for p in points),
              utc_today)
        check("every point has the documented shape",
              all(set(p) == {"date", "total", "diamonds", "golds"}
                  and all(isinstance(p[k], int) for k in ("total", "diamonds", "golds"))
                  for p in points),
              str(points))
        check("counts are consistent with the population",
              points[-1]["total"] >= points[-1]["diamonds"] + points[-1]["golds"],
              str(points[-1]))
    check("an unwatched reserve has no history", history.history_for(4242) == [])
    missing = Path("work") / "definitely-not-a-history-file.json"
    check("a missing history file is empty, not an error",
          history.history_for(9, path=missing) == [])

    # the store must keep one point per day, stay sorted, and be capped
    with tempfile.TemporaryDirectory() as temporary:
        store = Path(temporary) / "population_history.json"
        written = history.record(9, total=100, diamonds=2, golds=10, path=store,
                                 day="2026-01-01")
        check("a point can be written", written is not None
              and written["total"] == 100 and written["diamonds"] == 2,
              str(written))
        history.record(9, total=120, diamonds=3, golds=11, path=store, day="2026-01-01")
        same_day = history.history_for(9, path=store)
        check("a later scan refreshes today's point instead of duplicating it",
              len(same_day) == 1 and same_day[0]["total"] == 120, str(same_day))

        capped = Path(temporary) / "capped_history.json"
        start = date(2025, 1, 1)
        for offset in range(history.MAX_DAYS + 20):
            history.record(5, total=offset, diamonds=0, golds=0, path=capped,
                           day=(start + timedelta(days=offset)).isoformat())
        pruned = history.history_for(5, path=capped)
        check(f"the store is capped at {history.MAX_DAYS} days",
              len(pruned) == history.MAX_DAYS, str(len(pruned)))
        first_kept = (start + timedelta(days=20)).isoformat()
        check("the oldest days are the ones pruned",
              bool(pruned) and pruned[0]["date"] == first_kept,
              str(pruned[0]["date"] if pruned else None))

    # -- 7. the HTTP handler's contract (no socket needed) ------------------
    print("\n== /api/history contract ==")
    handler = object.__new__(server.Handler)
    default = handler._history({})
    check("defaults to reserve 9",
          default.get("reserve") == 9 and isinstance(default.get("points"), list),
          str(default.get("reserve")))
    explicit = handler._history({"reserve": ["16"]})
    check("honours ?reserve=N", explicit.get("reserve") == 16
          and isinstance(explicit.get("points"), list), str(explicit.get("reserve")))

    print("-" * 68)
    if FAILURES:
        for failure in FAILURES:
            print("  x " + failure)
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS - baseline is silent, one removal/appearance is one record,")
    print("               data_version tracks the files, and history is capped per day")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
