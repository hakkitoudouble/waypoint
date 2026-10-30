"""Generate cotw/data/reserves.json from the verified mapping + live PNG dimensions."""
import json
import os

from PIL import Image

SCANNER = r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner"
MAPS = os.path.join(SCANNER, "data", "Maps")
OUT = r"C:\Users\Maelo\Documents\mods\cotw-pop\cotw\data\reserves.json"

BASE = "2017-02-16"

# slot -> (display, map png, icon png, dlc, release_year, release_date, confidence, evidence)
ROWS = {
    0: ("Hirschfelden Hunting Reserve", "MapHirsch_bw.png", "Hirschfelden_hunting_reserve.png",
        "Base game", 2017, BASE, "VERIFIED",
        "pop_0 written right after an all-European-Bison session (bison are Hirschfelden-only) on 2024-05-29; id 0 in both external tables"),
    1: ("Layton Lake District", "MapLayton_bw.png", "Layton_lake_district.png",
        "Base game", 2017, BASE, "VERIFIED",
        "remaining base-game reserve; slot 0 independently verified as Hirschfelden; scanner table and companion reserve-id table agree"),
    2: ("Medved-Taiga National Park", "MapMedved_bw.png", "Medved_taiga_national_park.png",
        "Medved-Taiga DLC", 2017, None, "LIKELY",
        "both external tables agree (id 2 / label 2); no local play activity to correlate (stub files only)"),
    3: ("Vurhonga Savanna", "MapVurhonga_bw.png", "Vurhonga_savanna_reserve_icon.png",
        "Vurhonga Savanna DLC", 2018, None, "VERIFIED",
        "pop_3 written right after a Lion / Blue Wildebeest / Gemsbok session on 2023-11-05 (Vurhonga-unique species)"),
    4: ("Parque Fernando", "MapParque_bw.png", "Fernando.png",
        "Parque Fernando DLC", 2018, None, "VERIFIED",
        "pop_4 written after the 2024-05-26 session with Axis Deer / Puma / Collared Peccary; both tables also give 4"),
    5: (None, None, None, None, None, None, "SPECULATIVE",
        "reserve-table slot with NO reserve identity in either the scanner table or the companion reserve-id table; save files exist (pop 1.4 KB, fog 14 KB, written 2026-10-25) but the decompressed population is only ~68 KB vs 250-360 KB for real reserves"),
    6: ("Yukon Valley", "MapYukon_bw.png", "Yukon.png",
        "Yukon Valley DLC", 2019, None, "VERIFIED",
        "pop_6 written right after the 2023-07-27 Caribou kill (Caribou are Yukon-unique); companion id 6 = Yukon"),
    7: (None, None, None, None, None, None, "SPECULATIVE",
        "reserve-table slot with no reserve identity in either table; 881 B / 569 B / 313 B stub files = never visited"),
    8: ("Cuatro Colinas Game Reserve", "MapCuatro_bw.png", "Cuatrocolinas.png",
        "Cuatro Colinas DLC", 2019, None, "VERIFIED",
        "pop_8 written right after the 2023-07-28 Iberian Wolf / Beceite Ibex / Ronda Ibex / European Hare session (all Cuatro-only)"),
    9: ("Silver Ridge Peaks", "MapSRP_bw.png", "SilverRidgeLogo.png",
        "Silver Ridge Peaks DLC", 2020, None, "VERIFIED",
        "pop_9 written after the 2026-10-27 Rocky Mountain Elk / Pronghorn / Black Bear session (Rocky Mountain Elk are SRP-only)"),
    10: ("Te Awaroa National Park", "MapNZ_bw.png", "TeAwaroa.png",
         "Te Awaroa DLC", 2020, None, "LIKELY",
         "bracketed between verified slots 9 (SRP) and 14 (New England); both external tables agree on id 10"),
    11: ("Rancho del Arroyo", "MapRancho_bw.png", "Rancho.png",
         "Rancho del Arroyo DLC", 2021, None, "LIKELY",
         "bracketed between verified slots 9 and 14; companion id 11 = Rancho"),
    12: ("Mississippi Acres Preserve", "MapMississippi_bw.png", "Mississippi.png",
         "Mississippi Acres DLC", 2021, None, "LIKELY",
         "bracketed between verified slots 9 and 14; companion id 12 = Mississippi Acres"),
    13: ("Revontuli Coast", "MapRevontuli_bw.png", "Revontuli.png",
         "Revontuli Coast DLC", 2022, "2022-06-28", "LIKELY",
         "bracketed between verified slots 9 and 14; companion id 13 = Revontuli (its trophy log shows Brown Bear + Raccoon Dog, both Revontuli species)"),
    14: ("New England Mountains", "MapNewEngland_bw.png", "NewEngland.png",
         "New England Mountains DLC", 2022, None, "VERIFIED",
         "pop_14 written 2024-05-18/19 and 2024-05-25, during Whitetail Deer + Moose sessions, i.e. BEFORE Sundarpatan existed (June 2024) - rules out Sundarpatan"),
    15: (None, None, None, None, None, None, "SPECULATIVE",
         "no save files at all for this index and no entry in the companion reserve-id table: the slot does not exist in this game build"),
    16: ("Emerald Coast Australia", "EmeraldCoast_bw.png", "Emerald_Coast.png",
         "Emerald Coast DLC", 2023, None, "VERIFIED",
         "pop_16 written 2026-10-29 right after Kangaroo / Sambar / Banteng / Saltwater Crocodile / Hog Deer / Magpie Goose session (all Emerald-only)"),
    17: ("Sundarpatan Nepal Hunting Reserve", "MapSundarpatan_bw.png", "Sundarpatan.png",
         "Sundarpatan Nepal DLC", 2024, None, "LIKELY",
         "companion reserve-id table (id 17); no local save file (DLC not installed on this profile)"),
    18: ("Salzwiesen Park", "Salzwiesen_Park_bw.png", "SalzwiesenPark.png",
         "Salzwiesen Park DLC", 2024, None, "LIKELY",
         "companion reserve-id table (id 18); no local save file (DLC not installed)"),
    19: ("Askiy Ridge Hunting Reserve", "MapAskiyRidge_bw.png", "AskiyRidge.png",
         "Askiy Ridge DLC", 2025, None, "LIKELY",
         "companion reserve-id table (id 19); no local save file (DLC not installed)"),
    20: ("Torr nan Sithean (Scotland)", "MapScotland_bw.png", "Scotland.png",
         "Scotland DLC", 2025, "2025-12-09", "LIKELY",
         "companion reserve-id table (id 20); Steam update 2025-12-09; no local save file"),
    21: ("Intisuyu Hunting Preserve (Peru)", "MapPeru_bw.png", "Peru.png",
         "Peru DLC", 2026, None, "LIKELY",
         "companion reserve-id table (id 21); no local save file"),
}

EXTENT = {
    "width_m": 12000,
    "height_m": 12000,
    "centred_at_origin": True,
    "vertical_axis": "Y = altitude in metres (not a map axis); the 2D map uses X and Z",
    "basis": "need-zone Position values in found_need_zones_adf: x -12136..11465, z -13192..13184, y 1022..2232 (pooled over the 8 visited reserves)",
    "confidence": "ROUGH",
    "fit_advice": "fit per reserve: track (X,Z) min/max over many animals/zones, or fit affine from known landmarks; do not reuse one extent for all reserves",
}


def main():
    out = {}
    for slot, (disp, mapf, icon, dlc, year, date, conf, ev) in ROWS.items():
        entry = {
            "internal": None if disp is None else disp.lower()
                        .replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "")
                        .replace("_/_", "_").replace(".", ""),
            "display": disp,
            "map": mapf,
            "icon": icon,
            "dlc": dlc,
            "released": disp is not None,
            "release_year": year,
            "release_date": date,
            "game_reserve_id": slot,
            "confidence": conf,
            "evidence": ev,
            "map_meta": None,
        }
        if mapf:
            im = Image.open(os.path.join(MAPS, mapf))
            w, h = im.size
            entry["map_meta"] = {
                "pixel_size": [w, h],
                "aspect": round(w / h, 4),
                "world_extent_guess": dict(EXTENT),
                "north_up": True,
                "image_y_axis": "down",
                "map_coord_space": "unknown between metres (centred at origin) and normalized 0..1; test both",
                "confidence": "SPECULATIVE",
            }
        out[str(slot)] = entry

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("wrote", OUT, os.path.getsize(OUT), "bytes")
    for k, v in out.items():
        print(f"  {k:>2} {str(v['display']):<40} {str(v['map']):<26} {v['confidence']}")


if __name__ == "__main__":
    main()
