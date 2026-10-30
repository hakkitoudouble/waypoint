"""Import the community animal dataset (MIT, Pure-Winter-hue/apc-pw) into our tables.

That dataset adds three things we did not have:

* complete medal bands **including bronze** (the vendor binary only carries
  silver/gold/diamond, which is why our bronze tier was a guess);
* the per-species **fur vocabulary with probabilities**, which is what "rare fur"
  actually means — and which we could not recover from either the binary or the save;
* per-gender score/weight ranges, useful as sanity checks.

Everything is cross-checked against our binary-derived thresholds before it is used:
where the two disagree we keep the binary value and record the community one.

Run:  python tools/import_community_data.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "cotw" / "data"
SOURCE = ROOT / "work" / "radar" / "animal_details.json"

SOURCE_URL = (
    "https://github.com/Pure-Winter-hue/apc-pw/blob/"
    "8f297b5a9d36cfa826a18977dc4bd8c129bfc6ce/apc/config/animal_details.json"
)

#: rarity buckets by drop probability, mirroring the in-game vocabulary
RARITY_BANDS = (
    (0.0002, "super_rare"),
    (0.0010, "very_rare"),
    (0.0050, "rare"),
    (0.0500, "uncommon"),
    (1.0001, "common"),
)

PREFIXES = ("coll", "eg", "sw", "eur", "eu", "ew", "ec", "w", "e", "m", "s", "g")

#: community key -> our asset-style species name. Our table keeps the game's
#: abbreviated asset names ("Am. Alligator", "EG Kangaroo"), the community file uses
#: full English, and a few differ by spelling ("gray" vs "grey").
OVERRIDES = {
    "american_alligator": "Am. Alligator",
    "cinnamon_teal": "Cin Teal",
    "collared_peccary": "Coll. Peccary",
    "eastern_cottontail_rabbit": "ECt Rabbit",
    "eastern_grey_kangaroo": "EG Kangaroo",
    "eu_bison": "Euro Bison",
    "eu_hare": "European Hare",
    "eu_rabbit": "Euro Rabbit",
    "eurasian_teal": "Eu.Teal",
    "eurasian_wigeon": "Eu.Wigeon",
    "european_badger": "Euro Badger",
    "gray_wolf": "Grey Wolf",
    "eastern_wild_turkey": "EW Turkey",
    "rio_grande_turkey": "RG Turkey",
    "western_capercaillie": "W.Capercaillie",
    "white_morph_coati": "WM Coati",
    "green_wing_teal": "Green-Winged Teal",
    "harlequin_duck": "H Duck",
    "rockymountain_elk": "RM Elk",
    "saltwater_crocodile": "SW Crocodile",
    "sidestriped_jackal": "S-Striped Jackal",
    "south_american_tapir": "SA Tapir",
    "southeastern_ibex": "SES Ibex",
    "tundra_bean_goose": "T.Bean Goose",
    "vicuna": "Vicu\u00f1a",
    "western_mountain_coati": "WM Coati",
}


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def rarity_of(probability: float, name: str = "") -> str:
    # Great One variants are not a probability bucket: they are their own tier,
    # and the dataset lists them as the sub-variants of one Fabled specimen.
    if "great_one" in name.lower() or "fabled" in name.lower():
        return "great_one"
    for cut, label in RARITY_BANDS:
        if probability <= cut:
            return label
    return "common"


def match_species(community: dict, ours: list[str]) -> dict[str, str]:
    """community key -> our species name."""
    by_norm = {norm(name): name for name in ours}
    mapping: dict[str, str] = {}
    for key in community:
        if key in OVERRIDES and OVERRIDES[key] in by_norm.values():
            mapping[key] = OVERRIDES[key]
            continue
        target = norm(key)
        if target in by_norm:
            mapping[key] = by_norm[target]
            continue
        # try dropping a leading abbreviation from OUR name ("egkangaroo" -> "kangaroo")
        hit = None
        for our_norm, our_name in by_norm.items():
            for prefix in PREFIXES:
                if our_norm.startswith(prefix) and len(our_norm) > len(prefix) + 3:
                    if our_norm[len(prefix):] == target:
                        hit = our_name
                        break
            if hit:
                break
        if hit is None:
            # last resort: one contains the other and is long enough
            for our_norm, our_name in by_norm.items():
                shorter = min(len(our_norm), len(target))
                if shorter >= 6 and (our_norm in target or target in our_norm):
                    hit = our_name
                    break
        if hit:
            mapping[key] = hit
    return mapping


def main() -> int:
    if not SOURCE.is_file():
        print(f"FAIL: {SOURCE} missing (download it first)")
        return 1
    community = json.loads(SOURCE.read_text(encoding="utf-8"))

    hashes = json.loads((DATA / "species_hashes.json").read_text(encoding="utf-8"))
    ours = sorted({
        v for k, v in hashes.items()
        if isinstance(v, str) and re.fullmatch(r"[0-9A-Fa-f]{8}", str(k))
    })
    mapping = match_species(community, ours)
    print(f"community species: {len(community)}   ours: {len(ours)}   matched: {len(mapping)}")
    unmatched = [k for k in community if k not in mapping]
    if unmatched:
        print(f"unmatched community keys ({len(unmatched)}): {', '.join(unmatched[:12])}")

    # ---- medal bands -------------------------------------------------------
    existing = json.loads((DATA / "medal_thresholds.json").read_text(encoding="utf-8"))
    merged = dict(existing)
    agree = disagree = added_bronze = 0
    disputes: list[tuple[str, str, float, float]] = []

    for key, name in mapping.items():
        trophy = community[key].get("trophy") or {}
        if not trophy:
            continue
        entry = dict(merged.get(name) or {})
        entry.setdefault("confidence", "LIKELY")
        for band in ("bronze", "silver", "gold", "diamond"):
            cut = (trophy.get(band) or {}).get("score_low")
            if not isinstance(cut, (int, float)):
                continue
            current = entry.get(band)
            if isinstance(current, (int, float)):
                # the two sources round differently (2.80 vs 2.89); anything within
                # 1% is agreement, not a conflict
                tolerance = max(0.05, abs(current) * 0.01)
                if abs(current - cut) <= tolerance:
                    agree += 1
                else:
                    disagree += 1
                    disputes.append((name, band, current, float(cut)))
            else:
                # never import a value that would break the band ordering: the two
                # sources disagree badly for a few species (Pronghorn: community
                # bronze 53.3 sits above our binary silver 36.65), and a bronze
                # above silver would silently mislabel animals.
                silver = entry.get("silver")
                if band == "bronze" and isinstance(silver, (int, float)) and cut >= silver:
                    disputes.append((name, "bronze(rejected)", cut, float(silver)))
                    continue
                entry[band] = float(cut)
                if band == "bronze":
                    added_bronze += 1
                entry.setdefault("community_source", SOURCE_URL)
                entry.setdefault("community_confidence", "COMMUNITY")
        merged[name] = entry

    print(f"\nthresholds: agree={agree}  disagree={disagree}  bronze added={added_bronze}")
    for name, band, our_value, their_value in disputes[:12]:
        print(f"   {name:<22} {band:<8} ours={our_value:>8.2f}  community={their_value:>8.2f}")

    header = {
        "_meta": existing.get("_meta", {}),
        "_community": {
            "note": "bronze thresholds and missing bands merged from a MIT-licensed "
                    "community dataset; binary-derived values win where they conflict",
            "source": SOURCE_URL,
            "agreements": agree,
            "disagreements": disagree,
        },
    }
    payload = {**header}
    payload.update({k: v for k, v in merged.items() if not k.startswith("_")})
    (DATA / "medal_thresholds.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {DATA / 'medal_thresholds.json'}")

    # ---- fur catalogue -----------------------------------------------------
    catalogue: dict[str, dict] = {}
    for key, name in mapping.items():
        genders = community[key].get("gender") or {}
        variants: dict[str, dict] = {}
        for gender, payload_g in genders.items():
            furs = payload_g.get("furs") or {}
            total = payload_g.get("fur_total_probability") or 0
            for fur_name, weight in furs.items():
                probability = (weight / total) if total else 0.0
                slot = variants.setdefault(
                    fur_name,
                    {"name": fur_name, "probability": 0.0, "genders": []},
                )
                slot["probability"] = max(slot["probability"], round(probability, 6))
                if gender not in slot["genders"]:
                    slot["genders"].append(gender)
        if variants:
            for slot in variants.values():
                slot["rarity"] = rarity_of(slot["probability"], slot["name"])
            catalogue[name] = {
                "variants": sorted(variants.values(), key=lambda v: v["probability"]),
                "ammo_class": community[key].get("ammo_class"),
                "truracs": community[key].get("truracs", False),
            }

    out = {
        "_meta": {
            "note": "per-species fur vocabulary with drop probabilities and a rarity "
                    "bucket derived from them; MIT-licensed community data",
            "source": SOURCE_URL,
            "rarity_bands": {label: cut for cut, label in RARITY_BANDS},
            "species": len(catalogue),
        },
        "species": catalogue,
    }
    (DATA / "fur_catalogue.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    total_variants = sum(len(v["variants"]) for v in catalogue.values())
    print(f"wrote {DATA / 'fur_catalogue.json'}  ({len(catalogue)} species, {total_variants} variants)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
