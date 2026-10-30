"""Write the final deliverable `work/scanner_fur_tables.json` and print a comparison digest.

Input : work/scanner_fur_tables_raw.json  (produced by tools/fur_extract.py)
        cotw/data/fur_catalogue.json
Output: work/scanner_fur_tables.json

Scanner probability = weight / block.totalWeight (what the exe itself computes and compares
against 0.001 / 0.01 to pick the rarity class).

Run:  python tools/fur_report.py
"""

from __future__ import annotations

import json
from collections import defaultdict

import fur_compare  # canonicalisation + alias table
import fur_pe

RAW = r"..\work\scanner_fur_tables_raw.json"
CAT = r"..\cotw\data\fur_catalogue.json"
OUT = r"..\work\scanner_fur_tables.json"

BINARY = (r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 "
          r"2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\AnimalPopulationScanner.exe")

SOURCES = [
    f"{BINARY} (PE x64, image base 0x140000000, .data section)",
    "fur table array: VA 0x1400CF170, file 0xCD370, 254 blocks x 0x1F0 bytes",
    "block header: {char* speciesRecord; u32 slot; u32 totalWeight} (0x10 bytes)",
    "block entry: {u32 bitIndex; u32 pad; char* furName; u32 stringId; u32 weight} (0x18 bytes, max 20)",
    "consumer code: 0x1400568A0-0x140056B60 (imul r9, rax, 0x1f0 / cmp edx, 0xfe)",
    "localization table rebuilt from the static initializer (VA 0x1400EF3A0, 359 slots)",
    "species records: VA 0x1400B08C0 + 0x3C0 stride (one at 0x1400B08C0, 135*0x10 hash table, "
    "then 127 records from 0x1400B14F0)",
]


def rarity_of(probability: float) -> str:
    """Mirror of the exe's own classification at 0x140056A4F / 0x140056A81."""
    if probability < 0.001:
        return "very_rare"
    if probability < 0.01:
        return "rare"
    return "common"


def main() -> int:
    raw = json.load(open(RAW, encoding="utf-8"))
    catalogue = json.load(open(CAT, encoding="utf-8"))
    blocks = raw["blocks"]
    secs = fur_pe.sections(fur_pe.load())
    data_size = len(fur_pe.load())

    # catalogue index per species
    cat_index = {species: {fur_compare.canon(v["name"]): v for v in payload["variants"]}
                 for species, payload in catalogue["species"].items()}

    species_out: dict[str, list[dict]] = {}
    names_used: dict[str, int] = {}
    block_summary = []
    for block in blocks:
        species = block["species"]
        # one key per (species name, species record): the two gender blocks are merged,
        # the two distinct Caribou records are kept apart
        group = (species, block["speciesRecordVa"])
        if group not in names_used:
            count = sum(1 for existing in species_out if existing.split(" #")[0] == species)
            names_used[group] = species if count == 0 else f"{species} #{count + 1}"
        key = names_used[group]
        total = block["totalWeight"] or 1
        entries = []
        for position, entry in enumerate(block["entries"]):
            probability = entry["weight"] / total
            file_offset = int(entry["offset"], 16)
            entries.append({
                "name": entry["name"],
                "weight": entry["weight"],
                "offset": entry["offset"],
                "va": f"0x{fur_pe.off_to_va(file_offset, secs):X}",
                "stringId": entry["stringId"],
                "bitIndex": entry["bitIndex"],
                "entryIndex": position,
                "slot": block["slot"],
                "gender": {1: "male", 2: "female"}.get(block["slot"], "?"),
                "blockIndex": block["index"],
                "speciesRecordVa": f"0x{block['speciesRecordVa']:X}",
                "totalWeight": total,
                "probability": round(probability, 9),
                "rarity": rarity_of(probability),
            })
        species_out.setdefault(key, []).extend(entries)
        block_summary.append({
            "blockIndex": block["index"],
            "blockVa": f"0x{block['blockVa']:X}",
            "blockFileOffset": f"0x{fur_pe.va_to_off(block['blockVa'], secs):X}",
            "species": key,
            "speciesStringId": block["speciesStringId"],
            "speciesRecordVa": f"0x{block['speciesRecordVa']:X}",
            "slot": block["slot"],
            "gender": {1: "male", 2: "female"}.get(block["slot"], "?"),
            "totalWeight": block["totalWeight"],
            "entryCount": len(block["entries"]),
        })

    deliverable = {
        "_meta": {
            "tool": "Animal Population Scanner 1.2.15.1 (2026-06-28), native x64",
            "probability": "weight / totalWeight of the same block (identical to the exe's own "
                           "divss at 0x140056A62)",
            "rarity": "the exe's own classes: p < 0.001 very_rare, p < 0.01 rare, else common "
                      "(0x140056A4F / 0x140056A81)",
            "slot": "1 = male, 2 = female (block slot compared against the animal's gender code "
                    "at [entry+0x10], set at 0x1400568F8-0x140056913)",
            "bitIndex": "per-species variant ordinal used by the block ordering",
            "offset": "file offset of the 0x18-byte entry inside AnimalPopulationScanner.exe",
            "coverage": "254 blocks / 126 species, every block's weights sum exactly to its "
                        "totalWeight",
        },
        "sources": SOURCES,
        "species": species_out,
        "blocks": block_summary,
    }
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(deliverable, handle, indent=1, ensure_ascii=False)
    print(f"written {OUT}: {len(species_out)} species keys, {len(blocks)} blocks, "
          f"{sum(len(v) for v in species_out.values())} entries")

    # ---- comparison digest for the notes -------------------------------------
    rows = []
    for block in blocks:
        species = block["species"]
        payload = cat_index.get(species)
        total = block["totalWeight"] or 1
        for entry in block["entries"]:
            probability = entry["weight"] / total
            match = payload.get(fur_compare.canon(entry["name"])) if payload else None
            if match is None:
                continue
            rows.append({
                "species": species,
                "slot": block["slot"],
                "name": entry["name"],
                "catalogueName": match["name"],
                "weight": entry["weight"],
                "total": total,
                "probability": probability,
                "catalogueProbability": match["probability"],
                "ratio": probability / match["probability"] if match["probability"] else None,
                "catalogueRarity": match.get("rarity"),
                "scannerRarity": rarity_of(probability),
            })
    matched = len(rows)
    exact = sum(1 for row in rows if abs(row["probability"] - row["catalogueProbability"]) <= 1e-9)
    print(f"matched entries: {matched}, identical to 1e-9: {exact}")
    worst = sorted(rows, key=lambda r: -abs((r["ratio"] or 1) - 1))[:10]
    print("largest relative deviations:")
    for row in worst:
        print(f"   {row['species']:<18} {row['name']:<16} scanner {row['probability']:.9f} "
              f"cat {row['catalogueProbability']:.9f} ratio {row['ratio']:.4f}")

    with open(r"..\work\scanner_fur_compare.json", "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
