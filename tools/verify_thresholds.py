"""Validate cotw/data/medal_thresholds.json.

Checks
 1. the file parses
 2. every entry has bronze/silver/gold/diamond + confidence
 3. no negative values, no NaN
 4. thresholds are strictly increasing over the non-null run (bronze < silver < gold < diamond)
 5. every species key exists in species_hashes.json (extras are reported)
 6. coverage report: how many species have a Diamond value, split by confidence
 7. sanity check against species_stats.json (diamond magnitude must not be
    wildly out of line with the species' body weight / difficulty rating)

Exit code 0 = clean, 1 = at least one error.

Run: python tools/verify_thresholds.py
"""
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "cotw" / "data"
TARGET = DATA / "medal_thresholds.json"
KEYS = ("bronze", "silver", "gold", "diamond")
CONFIDENCES = ("VERIFIED", "LIKELY", "SPECULATIVE")

errors = []
warnings = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    # ---- 1. parse -------------------------------------------------------
    try:
        doc = load_json(TARGET)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: cannot parse {TARGET}: {exc}")
        return 1
    if not isinstance(doc, dict):
        print("FAIL: top level of medal_thresholds.json is not an object")
        return 1

    meta = doc.get("_meta")
    if not isinstance(meta, dict):
        err("missing _meta object")
        meta = {}

    entries = {k: v for k, v in doc.items() if not k.startswith("_")}
    if not entries:
        err("no species entries")

    # ---- species universe ----------------------------------------------
    hashes = load_json(DATA / "species_hashes.json")
    species = {v for k, v in hashes.items() if isinstance(v, str) and not k.startswith("_")}

    # ---- per-entry checks ----------------------------------------------
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            err(f"{name}: entry is not an object")
            continue

        for key in KEYS:
            if key not in entry:
                err(f"{name}: missing key '{key}'")
        if "confidence" not in entry:
            err(f"{name}: missing key 'confidence'")
        elif entry["confidence"] not in CONFIDENCES:
            err(f"{name}: confidence {entry['confidence']!r} not in {CONFIDENCES}")

        present = []
        for key in KEYS:
            if key not in entry:
                continue
            val = entry[key]
            if val is None:
                continue
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                err(f"{name}.{key}: non-numeric value {val!r}")
                continue
            if math.isnan(val) or math.isinf(val):
                err(f"{name}.{key}: NaN/Inf")
                continue
            if val < 0:
                err(f"{name}.{key}: negative value {val}")
            present.append((key, float(val)))

        # monotonicity over the present values, in declaration order
        for (k1, v1), (k2, v2) in zip(present, present[1:]):
            if not v1 < v2:
                err(f"{name}: {k1}={v1} is not < {k2}={v2}")
        # bronze is null everywhere by design (see _meta.bronze); only flag the
        # absence of values that the sources actually publish.
        missing = [k for k in ("silver", "gold", "diamond") if entry.get(k) is None]
        if missing:
            warn(f"{name}: null thresholds {missing}")

        src = entry.get("source")
        if src is not None and not (isinstance(src, str) and src.startswith("http")):
            err(f"{name}: source is not a URL: {src!r}")
        if entry.get("confidence") == "VERIFIED" and not entry.get("source"):
            warn(f"{name}: VERIFIED but no source URL")

        if name not in species:
            err(f"{name}: not present in species_hashes.json")

    # ---- coverage -------------------------------------------------------
    covered = [n for n, e in entries.items() if isinstance(e, dict) and e.get("diamond") is not None]
    by_conf = {c: 0 for c in CONFIDENCES}
    for n in covered:
        by_conf[entries[n]["confidence"]] += 1

    total = len(entries)
    print("=" * 68)
    print("medal_thresholds.json verification")
    print("=" * 68)
    print(f"entries                : {total}")
    print(f"species_hashes species : {len(species)}")
    print(f"has Diamond            : {len(covered)} / {len(species)} of the hash-file list")
    print(f"  VERIFIED             : {by_conf['VERIFIED']}")
    print(f"  LIKELY               : {by_conf['LIKELY']}")
    print(f"  SPECULATIVE          : {by_conf['SPECULATIVE']}")
    for key in ("silver", "gold", "bronze"):
        n = sum(1 for e in entries.values() if isinstance(e, dict) and e.get(key) is not None)
        print(f"has {key:<18}: {n}" + ("   (not published by any source; see _meta.bronze)"
                                      if key == "bronze" and n == 0 else ""))

    missing_species = sorted(species - set(entries))
    if missing_species:
        warn(f"{len(missing_species)} species from species_hashes.json absent from the file: "
             f"{missing_species}")
    extras = sorted(set(entries) - species)
    if extras:
        print(f"EXTRA names not in species_hashes.json: {extras}")

    # ---- sanity check vs species_stats.json ------------------------------
    stats_path = DATA / "species_stats.json"
    if stats_path.exists():
        stats = {s["name"]: s for s in load_json(stats_path)["species"]}
        # TR runs on an arbitrary per-species scale: antler/horn scores land near
        # 1-4x body weight, while many small species (ducks, quail, ptarmigan,
        # grouse, marten...) effectively score weight in grams, i.e. 100-1000x
        # their weight in kg. So only flag magnitudes that fit neither pattern.
        checked = 0
        scale_hits = {}
        for name, entry in entries.items():
            st = stats.get(name)
            if not st or entry.get("diamond") is None:
                continue
            weights = [w for w in st.get("series_0x30", []) if w > 0]
            if not weights:
                continue
            ratio = entry["diamond"] / max(weights)
            for factor in (1, 10, 100, 1000):
                if abs(ratio - factor) <= 0.15 * factor:
                    scale_hits[factor] = scale_hits.get(factor, 0) + 1
                    break
            if not (0.005 <= ratio <= 2500):
                warn(f"{name}: diamond {entry['diamond']} is {ratio:.2f}x max weight "
                     f"{max(weights)} kg -- implausible for any known TR scale")
            checked += 1
        print(f"sanity check vs weight: {checked} species compared; "
              f"diamond/weight scale near x1:{scale_hits.get(1,0)} x10:{scale_hits.get(10,0)} "
              f"x100:{scale_hits.get(100,0)} x1000:{scale_hits.get(1000,0)}")

        # known relative orderings that must hold for any sane dataset
        pairs = [
            ("Red Deer", "Roe Deer"),
            ("Moose", "Roe Deer"),
            ("Water Buffalo", "Springbok"),
            ("Lion", "Jackrabbit"),
            ("Whitetail Deer", "Cin Teal"),
            ("Cape Buffalo", "Springbok"),
        ]
        for big, small in pairs:
            b, s = entries.get(big, {}), entries.get(small, {})
            if b.get("diamond") is not None and s.get("diamond") is not None:
                if not b["diamond"] > s["diamond"]:
                    err(f"sanity: {big} diamond {b['diamond']} <= {small} diamond {s['diamond']}")

    # ---- report ---------------------------------------------------------
    print("-" * 68)
    if warnings:
        print(f"{len(warnings)} warning(s):")
        for w in warnings[:40]:
            print("  ! " + w)
        if len(warnings) > 40:
            print(f"  ... and {len(warnings) - 40} more")
    if errors:
        print(f"{len(errors)} ERROR(S):")
        for e in errors:
            print("  x " + e)
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS - all structural checks clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
