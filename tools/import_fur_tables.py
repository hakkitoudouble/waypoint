"""Copy the scanner's recovered fur tables into the engine's data directory.

Source: `work/scanner_fur_tables.json`, extracted by tools/fur_extract.py from
`AnimalPopulationScanner.exe` (array at VA 0x1400CF170, 254 blocks of 0x1F0 bytes).

The scanner keeps **one table per species and per gender**, because the draw is made
against the animal's gender. Our older catalogue kept a single probability per variant,
which is why a few species disagreed: for 41 of 125 species the male and female totals
differ, so the same variant has two different probabilities.

Output layout (compact, engine friendly):

    { "_meta": {...},
      "species": { "Black Bear": { "1": {"total": 74926,
                                          "entries": [["Blonde", 38], ...]}, "2": {...} } } }

Usable genders are 1 (male) and 2 (female) — the same codes the save stores.

Run:  python tools/import_fur_tables.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "work" / "scanner_fur_tables.json"
TARGET = ROOT / "cotw" / "data" / "fur_tables.json"


def main() -> int:
    if not SOURCE.is_file():
        print(f"FAIL: {SOURCE} missing — run tools/fur_extract.py first")
        return 1
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    species_raw = raw.get("species") or {}

    species: dict[str, dict] = {}
    entries = 0
    for name, variants in species_raw.items():
        blocks: dict[str, dict] = {}
        for variant in variants:
            slot = variant.get("slot")
            weight = variant.get("weight")
            label = variant.get("name")
            if slot not in (1, 2) or not isinstance(weight, int) or not label:
                continue
            block = blocks.setdefault(str(slot), {
                "total": int(variant.get("totalWeight") or 0),
                "entries": [],
            })
            block["entries"].append([label, weight])
        if not blocks:
            continue
        for slot, block in blocks.items():
            if not block["total"]:
                block["total"] = sum(weight for _, weight in block["entries"])
        species[name] = blocks
        entries += sum(len(b["entries"]) for b in blocks.values())

    payload = {
        "_meta": {
            "note": "per-species, per-gender fur draw tables recovered from "
                    "AnimalPopulationScanner.exe; the fur is a deterministic function of "
                    "the save's VisualVariationSeed",
            "source": "AnimalPopulationScanner.exe array at VA 0x1400CF170",
            "draw": "state = (seed * 0x343FD + 0x269EC3) mod 2^32; "
                    "u = ((state >> 16) & 0x7FFF) / 32768; "
                    "roll = int(u * totalWeight); first entry whose cumulative weight "
                    "exceeds roll wins",
            "genders": {"1": "male", "2": "female"},
            "species": len(species),
            "entries": entries,
        },
        "species": species,
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"{len(species)} especes, {entries} entrees -> {TARGET}")
    for name in ("Black Bear", "Whitetail Deer", "Red Deer"):
        blocks = species.get(name)
        if not blocks:
            continue
        for slot, block in sorted(blocks.items()):
            total = block["total"]
            head = ", ".join(f"{n}={w}" for n, w in block["entries"][:4])
            print(f"  {name:<16} slot {slot}: total={total:<7} {head} ...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
