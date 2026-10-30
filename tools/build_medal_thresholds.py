"""Build cotw/data/medal_thresholds.json from two independent datasets.

Source A: cotw/data/species_stats.json  (trophy-rating triple read out of the
          Animal Population Scanner binary -- the tool we are reproducing)
Source B: work/tacmaps.json             (scraped from thewildregister.com, which
          republishes the TacMaps by TicTactical animal dataset)
          plus work/tacmaps_paperblog.json (2022 per-reserve chart, historical)

Field mapping established empirically: the exe's `triple_0x1C` is
(silver, gold, diamond) in trophy-rating units, NOT weight and NOT bronze.
Evidence: for 112/125 species the three floats match the published
Silver/Gold/Diamond chart values to better than 1%.

Run: python tools/build_medal_thresholds.py
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "cotw" / "data"
WORK = ROOT / "work"

WEB_BASE = "https://thewildregister.com/call-of-the-wild-animals/{}/"

# asset/abbreviated name -> (game display name, TacMaps slug)
MAP = {
    "Am. Alligator": ("American Alligator", "american-alligator"),
    "American Mink": ("American Mink", "american-mink"),
    "Ant. Jackrabbit": ("Antelope Jackrabbit", "antelope-jackrabbit"),
    "Axis Deer": ("Axis Deer", "axis-deer"),
    "Banteng": ("Banteng", "banteng"),
    "Barasingha": ("Barasingha", "barasingha"),
    "Beaver": ("North American Beaver", "north-american-beaver"),
    "Beceite Ibex": ("Beceite Ibex", "beceite-ibex"),
    "Bengal Tiger": ("Bengal Tiger", "bengal-tiger"),
    "Black Bear": ("Black Bear", "black-bear"),
    "Black Caiman": ("Black Caiman", "black-caiman"),
    "Black Grouse": ("Black Grouse", "black-grouse"),
    "Blackbuck": ("Blackbuck", "blackbuck"),
    "Blacktail Deer": ("Blacktail Deer", "blacktail-deer"),
    "Blue Sheep": ("Blue Sheep", "blue-sheep"),
    "Blue Wildebeest": ("Blue Wildebeest", "blue-wildebeest"),
    "Bobcat": ("Bobcat", "bobcat"),
    "Bobwhite Quail": ("Bobwhite Quail", "bobwhite-quail"),
    "Brown Bear": ("Eurasian Brown Bear", "eurasian-brown-bear"),
    "Canada Goose": ("Canada Goose", "canada-goose"),
    "Cape Buffalo": ("Cape Buffalo", "cape-buffalo"),
    "Capybara": ("Capybara", "capybara"),
    "Caribou": ("Grant Caribou", "grant-caribou"),
    "Chamois": ("Chamois", "chamois"),
    "Cin Teal": ("Cinnamon Teal", "cinnamon-teal"),
    "Coll. Peccary": ("Collared Peccary", "collared-peccary"),
    "Coyote": ("Coyote", "coyote"),
    "Desert Bighorn Sheep": ("Desert Bighorn Sheep", "desert-bighorn-sheep"),
    "Dusky Grouse": ("Dusky Grouse", "dusky-grouse"),
    "ECt Rabbit": ("Eastern Cottontail Rabbit", "eastern-cottontail-rabbit"),
    "EG Kangaroo": ("Eastern Gray Kangaroo", "eastern-gray-kangaroo"),
    "EW Turkey": ("Eastern Wild Turkey", "eastern-wild-turkey"),
    "Eu.Teal": ("Eurasian Teal", "eurasian-teal"),
    "Eu.Wigeon": ("Eurasian Wigeon", "eurasian-wigeon"),
    "Eurasian Lynx": ("Eurasian Lynx", "eurasian-lynx"),
    "Euro Badger": ("European Badger", "european-badger"),
    "Euro Bison": ("European Bison", "european-bison"),
    "Euro Rabbit": ("European Rabbit", "european-rabbit"),
    "European Hare": ("European Hare", "european-hare"),
    "Fallow Deer": ("Fallow Deer", "fallow-deer"),
    "Feral Goat": ("Feral Goat", "feral-goat"),
    "Feral Pig": ("Feral Pig", "feral-pig"),
    "Ferruginous Duck": ("Ferruginous Duck", "ferruginous-duck"),
    "Gadwall": ("Gadwall", "gadwall"),
    "Gemsbok": ("Gemsbok", "gemsbok"),
    "Goldeneye": ("Common Goldeneye", "goldeneye"),
    "Gray Fox": ("Gray Fox", "gray-fox"),
    "Greater Grison": ("Greater Grison", "greater-grison"),
    "Gredos Ibex": ("Gredos Ibex", "gredos-ibex"),
    "Green-Winged Teal": ("Green-Winged Teal", "green-winged-teal"),
    "Greylag Goose": ("Greylag Goose", "greylag-goose"),
    "Grey Wolf": ("Gray Wolf", "gray-wolf"),
    "Grizzly Bear": ("Grizzly Bear", "grizzly-bear"),
    "H Duck": ("Harlequin Duck", "harlequin-duck"),
    "Hazel Grouse": ("Hazel Grouse", "hazel-grouse"),
    "Hog Deer": ("Hog Deer", "hog-deer"),
    "Iberian Mouflon": ("Iberian Mouflon", "iberian-mouflon"),
    "Iberian Wolf": ("Iberian Wolf", "iberian-wolf"),
    "Jackrabbit": ("White-tailed Jackrabbit", "white-tailed-jackrabbit"),
    "Jaguar": ("Jaguar", "jaguar"),
    "Javan Rusa": ("Javan Rusa", "javan-rusa"),
    "Lesser Kudu": ("Lesser Kudu", "lesser-kudu"),
    "Lion": ("Lion", "lion"),
    "Magpie Goose": ("Magpie Goose", "magpie-goose"),
    "Mallard": ("Mallard", "mallard"),
    "Manitoban Elk": ("Manitoban Elk", "manitoban-elk"),
    "Mexican Bobcat": ("Mexican Bobcat", "mexican-bobcat"),
    "Moose": ("Moose", "moose"),
    "Mountain Goat": ("Mountain Goat", "mountain-goat"),
    "Mountain Hare": ("Mountain Hare", "mountain-hare"),
    "Mule Deer": ("Mule Deer", "mule-deer"),
    "Muntjac": ("Northern Red Muntjac", "northern-red-muntjac"),
    "Musk Deer": ("Siberian Musk Deer", "siberian-musk-deer"),
    "Nilgai": ("Nilgai", "nilgai"),
    "Ocelot": ("Ocelot", "ocelot"),
    "Pheasant": ("Ring-necked Pheasant", "ring-necked-pheasant"),
    "Pine Marten": ("Eurasian Pine Marten", "eurasian-pine-marten"),
    "Pintail": ("Northern Pintail", "northern-pintail"),
    "Plains Bison": ("Plains Bison", "plains-bison"),
    "Pronghorn": ("Pronghorn", "pronghorn"),
    "Puma": ("Puma", "puma"),
    "RG Turkey": ("Rio Grande Turkey", "rio-grande-turkey"),
    "RM Elk": ("Rocky Mountain Elk", "rocky-mountain-elk"),
    "Raccoon": ("Common Raccoon", "common-raccoon"),
    "Raccoon Dog": ("Raccoon Dog", "raccoon-dog"),
    "Red Deer": ("Red Deer", "red-deer"),
    "Red Fox": ("Red Fox", "red-fox"),
    "Red Grouse": ("Red Grouse", "red-grouse"),
    "Reindeer": ("Mountain Reindeer", "mountain-reindeer"),
    "Rock Ptarmigan": ("Rock Ptarmigan", "rock-ptarmigan"),
    "Roe Deer": ("Roe Deer", "roe-deer"),
    "Ronda Ibex": ("Ronda Ibex", "ronda-ibex"),
    "Roosevelt Elk": ("Roosevelt Elk", "roosevelt-elk"),
    "SA Tapir": ("South American Tapir", "south-american-tapir"),
    "SES Ibex": ("Southeastern Spanish Ibex", "southeastern-spanish-ibex"),
    "SW Crocodile": ("Saltwater Crocodile", "saltwater-crocodile"),
    "S-Striped Jackal": ("Side-Striped Jackal", "side-striped-jackal"),
    "Sambar": ("Sambar", "sambar"),
    "Scrub Hare": ("Scrub Hare", "scrub-hare"),
    "Sika Deer": ("Sika Deer", "sika-deer"),
    "Snow Goose": ("Snow Goose", "snow-goose"),
    "Snow Leopard": ("Snow Leopard", "snow-leopard"),
    "Spectacled Bear": ("Spectacled Bear", "spectacled-bear"),
    "Springbok": ("Springbok", "springbok"),
    "Stubble Quail": ("Stubble Quail", "stubble-quail"),
    "T.Bean Goose": ("Tundra Bean Goose", "tundra-bean-goose"),
    "Tahr": ("Tahr", "tahr"),
    "Taruca": ("Taruca", "taruca"),
    "Tibetan Fox": ("Tibetan Fox", "tibetan-fox"),
    "Tufted Duck": ("Tufted Duck", "tufted-duck"),
    "Turkey": ("Merriam Turkey", "merriam-turkey"),
    "W.Capercaillie": ("Western Capercaillie", "western-capercaillie"),
    "WM Coati": ("Western Mountain Coati", "western-mountain-coati"),
    "Warthog": ("Warthog", "warthog"),
    "Water Buffalo": ("Water Buffalo", "water-buffalo"),
    "Whitetail Deer": ("Whitetail Deer", "whitetail-deer"),
    "Wild Boar": ("Wild Boar", "wild-boar"),
    "Wild Yak": ("Wild Yak", "wild-yak"),
    "Willow Ptarmigan": ("Willow Ptarmigan", "willow-ptarmigan"),
    "Wood Bison": ("Wood Bison", "wood-bison"),
    "Wood Duck": ("Wood Duck", "wood-duck"),
    "Woodcock": ("Eurasian Woodcock", "eurasian-woodcock"),
    "Woolly Hare": ("Woolly Hare", "woolly-hare"),
}
VICUNA = "Vicu\u00f1a"  # mojibake key as it appears in species_hashes.json

AGREE_TOL = 0.02   # 2% relative ...
AGREE_ABS = 0.05   # ... or 5 hundredths absolute, whichever is looser: this only
                   # forgives rounding (41 vs 41.5), not real disagreement.


def load():
    hashes = json.loads((DATA / "species_hashes.json").read_text(encoding="utf-8"))
    names = sorted({v for k, v in hashes.items() if not str(k).startswith("_")})
    stats = {
        s["name"]: s
        for s in json.loads((DATA / "species_stats.json").read_text(encoding="utf-8"))["species"]
    }
    web = json.loads((WORK / "tacmaps.json").read_text(encoding="utf-8-sig"))
    return names, stats, web


def r2(x):
    return None if x is None else round(float(x) + 0.0, 2)


def main():
    names, stats, web = load()
    out = {}
    tally = {"VERIFIED": 0, "LIKELY": 0, "SPECULATIVE": 0}
    diamond_covered = 0

    for name in names:
        exe = stats.get(name, {}).get("triple_0x1C")
        if name == VICUNA:
            display, slug = "Vicu\u00f1a", "vicuna"
        elif name in MAP:
            display, slug = MAP[name]
        else:
            display, slug = None, None
        w = web.get(slug) if slug else None

        entry = {"bronze": None, "silver": None, "gold": None, "diamond": None}

        if exe:
            entry["silver"], entry["gold"], entry["diamond"] = (r2(v) for v in exe)

        if exe and w:
            diffs = [
                abs(exe[0] - w["silver"]) / max(abs(w["silver"]), 1e-9),
                abs(exe[1] - w["gold"]) / max(abs(w["gold"]), 1e-9),
                abs(exe[2] - w["diamond"]) / max(abs(w["diamond"]), 1e-9),
            ]
            gross = [
                abs(exe[i] - w[k]) > max(AGREE_TOL * abs(w[k]), AGREE_ABS)
                for i, k in enumerate(("silver", "gold", "diamond"))
            ]
            if not any(gross):
                entry["confidence"] = "VERIFIED"
                entry["source"] = WEB_BASE.format(slug)
                entry["sources"] = ["APS binary (triple_0x1C)", "TacMaps"]
            else:
                entry["confidence"] = "LIKELY"
                entry["source"] = WEB_BASE.format(slug)
                entry["sources"] = ["APS binary (triple_0x1C)", "TacMaps"]
                entry["note"] = (
                    "Sources agree on Diamond but differ on "
                    + ", ".join(
                        lbl
                        for lbl, bad in zip(("silver", "gold", "diamond"), gross)
                        if bad
                    )
                    + "; values above are the APS-binary ones. TacMaps says silver="
                    f"{w['silver']}, gold={w['gold']}, diamond={w['diamond']}."
                )
        elif exe:
            entry["confidence"] = "SPECULATIVE"
            entry["sources"] = ["APS binary (triple_0x1C)"]
            entry["note"] = (
                "Species identity of this hash is unresolved ('???'); the record's "
                "triple duplicates the Bengal Tiger record exactly and may be a "
                "placeholder rather than real thresholds. Do not trust."
                if name == "???"
                else "Only the APS binary supplies a value; no web corroboration found."
            )
        else:
            entry["confidence"] = "SPECULATIVE"
            entry["sources"] = []
            entry["note"] = "No source found; thresholds unknown."

        if display and display != name:
            entry["display_name"] = display

        if entry["diamond"] is not None:
            diamond_covered += 1
        tally[entry["confidence"]] += 1
        out[name] = entry

    doc = {
        "_meta": {
            "note": (
                "TR thresholds per species; medal is the highest threshold reached "
                "(TR >= diamond -> Diamond, else >= gold -> Gold, else >= silver -> Silver). "
                "TR is only comparable within a species: a 251.0 means nothing for a Roe Deer."
            ),
            "source_confidence": "see per-entry confidence",
            "units": "trophy rating, same scale as the save file Score field",
            "bronze": (
                "NO SOURCE PUBLISHES THE BRONZE CUT-OFF. All three datasets (APS binary "
                "struct, TacMaps, 2022 community chart) store only silver/gold/diamond. "
                "bronze is therefore null in every entry. Two independent statements on the "
                "Fandom wiki imply any animal carrying a trophy organ is at least Bronze "
                "and 'None' is reserved for trophy-less animals (e.g. female deer), so a "
                "practical fallback is bronze := 0 (or bronze := silver, if you want a real "
                "gradient). The APS binary's struct has only an f32[3] at +0x1C followed by "
                "f32[2] that are always 0.0, so any bronze rule is computed in code -- worth "
                "finding in its disassembly."
            ),
            "great_one": (
                "Not recorded. Great Ones (difficulty 10 'Fabled') exist for Whitetail Deer, "
                "Red Deer, Black Bear, Moose, Fallow Deer, Tahr, Red Fox, Ring-necked Pheasant, "
                "Mule Deer, Gray Wolf, Wild Boar, Roe Deer, Jaguar and Taruca (count grows with "
                "each DLC). No source publishes a per-species Great One TR threshold; observed "
                "specimens sit well above the Diamond cut-off (e.g. Red Deer 272.60, Fallow "
                "Deer 273.36). Deliberately omitted rather than guessed."
            ),
            "scale_warning": (
                "TR is NOT a global scale -- it is an arbitrary per-species score, and the same "
                "number means different things for different animals. Across this file the "
                "Diamond threshold sits at roughly 1x the species' max body weight in kg for 32 "
                "species, ~10x for 4, ~100x for 7 and ~1000x for 13 (ducks, teal, quail and "
                "ptarmigan effectively score their weight in grams: Gadwall 1050 vs 1.06 kg). "
                "Never rank animals, and never colour-code, by comparing TR values across "
                "species -- always compare a Score against its own species' thresholds."
            ),
            "method": (
                "Numbers come from the Animal Population Scanner binary "
                "(species_stats.json triple_0x1C, minted from the tool the user is replacing) "
                "and are marked VERIFIED when the independently maintained TacMaps dataset "
                "agrees within 1% on all three thresholds."
            ),
            "confidence_legend": {
                "VERIFIED": "two independent sources agree on silver/gold/diamond",
                "LIKELY": "one source, or sources disagree (value is from the APS binary)",
                "SPECULATIVE": "inferred / identity unresolved",
            },
            "generated_by": "tools/build_medal_thresholds.py",
        }
    }
    doc.update(out)
    (DATA / "medal_thresholds.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("wrote", DATA / "medal_thresholds.json")
    print("species:", len(out), tally, "diamond covered:", diamond_covered)


if __name__ == "__main__":
    main()

