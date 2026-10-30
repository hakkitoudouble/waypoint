"""Compare the scanner's extracted fur weights with the community catalogue.

scanner probability = weight / block.totalWeight  (that is exactly what the exe computes at
VA 0x140056A62: `divss xmm1, xmm2` then compares against 0.001 / 0.01 for the rarity class).

Name matching: both sides are reduced to lowercase alphanumerics, then a small alias table
maps the scanner's own spellings (`Ps Melanistic`, `MelanistiCC`, `Piebald-Blnd`, ...) onto
the catalogue's names.

Run:  python tools/fur_compare.py
"""

from __future__ import annotations

import json
import re
import sys

RAW = r"..\work\scanner_fur_tables_raw.json"
CAT = r"..\cotw\data\fur_catalogue.json"
OUT = r"..\work\scanner_fur_compare.json"

ALIASES = {
    "psmelanistic": "pseudomelanistic",
    "psmelawht": "pseudomelanisticwhite",
    "psmelanisticwhite": "pseudomelanisticwhite",
    "whtstripeless": "whitestripeless",
    "whitestripeless": "whitestripeless",
    "melanisticc": "melanisticcharcoal",
    "erythrisabel": "erythristicisabelline",
    "erythristicisabelline": "erythristicisabelline",
    "erythrchoc": "erythristicchocolate",
    "erythrgold": "erythristicgolden",
    "erythrred": "erythristicred",
    "piebaldblnd": "piebaldblonde",
    "piebaldwht": "piebaldwhite",
    "dgreybrown": "graybrown",
    "realspotted": "spotted",
    "dredbrown": "darkredbrown",
    "two tones": "twotones",
}


def canon(name: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    return ALIASES.get(key, key)


def main() -> int:
    raw = json.load(open(RAW, encoding="utf-8"))
    catalogue = json.load(open(CAT, encoding="utf-8"))

    cat_index = {}
    for species, payload in catalogue["species"].items():
        cat_index[species] = {canon(v["name"]): v for v in payload["variants"]}

    blocks = raw["blocks"]
    # group blocks per species name
    per_species: dict[str, list[dict]] = {}
    for block in blocks:
        per_species.setdefault(block["species"], []).append(block)

    report = {}
    for species, species_blocks in sorted(per_species.items()):
        payload = cat_index.get(species)
        rows = []
        for block in species_blocks:
            total = block["totalWeight"] or 1
            for entry in block["entries"]:
                probability = entry["weight"] / total
                row = {
                    "slot": block["slot"],
                    "blockIndex": block["index"],
                    "name": entry["name"],
                    "stringId": entry["stringId"],
                    "bitIndex": entry["bitIndex"],
                    "weight": entry["weight"],
                    "totalWeight": total,
                    "probability": round(probability, 9),
                    "offset": entry["offset"],
                }
                if payload is not None:
                    match = payload.get(canon(entry["name"]))
                    if match is not None:
                        row["catalogueName"] = match["name"]
                        row["catalogueProbability"] = match["probability"]
                        row["catalogueRarity"] = match.get("rarity")
                        if match["probability"]:
                            row["ratio"] = round(probability / match["probability"], 4)
                rows.append(row)
        report[species] = rows

    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1, ensure_ascii=False)

    # console summary
    total = matched = 0
    for species, rows in report.items():
        for row in rows:
            total += 1
            matched += 1 if "catalogueProbability" in row else 0
    print(f"scanner entries: {total}, matched to catalogue: {matched} "
          f"({100.0 * matched / total:.1f}%)")

    for species in ("Reindeer", "Whitetail Deer", "Red Deer", "Pintail", "Moose"):
        rows = report.get(species)
        if not rows:
            continue
        print(f"\n--- {species}")
        for row in rows:
            extra = ""
            if "catalogueProbability" in row:
                extra = (f"  cat {row['catalogueProbability']:.6f} "
                         f"({row['catalogueName']}) ratio {row.get('ratio')}")
            else:
                extra = "  -- not in catalogue"
            print(f"   slot{row['slot']} bit{row['bitIndex']:<2} {row['name']!r:<26} "
                  f"w={row['weight']:<6} p={row['probability']:.6f}{extra}")
    print(f"\nwritten {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
