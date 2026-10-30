# COTW save-slot → reserve mapping

Working dir: `C:\Users\Maelo\Documents\mods\cotw-pop`
Outputs: [`cotw/data/reserves.json`](../cotw/data/reserves.json), this file.
Scripts: [`tools/`](../tools/) (all read-only against the save folder and the scanner folder).

---

## TL;DR

The save slot number in `animal_population_<N>` is **not** a contiguous reserve counter.
It is the game's **internal reserve id**, and that id space contains **three phantom slots
(5, 7, 15)** that hold no reserve. Because of those holes, everything from slot 5 upward is
shifted relative to a naive release-order list — which is exactly what the scanner's help
text does, so **its labels are wrong for N ≥ 5**.

Verified mapping (strongest evidence marked ✔):

| slot | reserve | map image | confidence |
|---:|---|---|---|
| 0 | Hirschfelden Hunting Reserve ✔ | `MapHirsch_bw.png` | VERIFIED |
| 1 | Layton Lake District | `MapLayton_bw.png` | VERIFIED |
| 2 | Medved-Taiga National Park | `MapMedved_bw.png` | LIKELY |
| 3 | Vurhonga Savanna ✔ | `MapVurhonga_bw.png` | VERIFIED |
| 4 | Parque Fernando ✔ | `MapParque_bw.png` | VERIFIED |
| 5 | **unknown phantom slot** | — | SPECULATIVE |
| 6 | Yukon Valley ✔ | `MapYukon_bw.png` | VERIFIED |
| 7 | **unknown phantom slot** | — | SPECULATIVE |
| 8 | Cuatro Colinas ✔ | `MapCuatro_bw.png` | VERIFIED |
| 9 | Silver Ridge Peaks ✔ | `MapSRP_bw.png` | VERIFIED |
| 10 | Te Awaroa National Park | `MapNZ_bw.png` | LIKELY |
| 11 | Rancho del Arroyo | `MapRancho_bw.png` | LIKELY |
| 12 | Mississippi Acres Preserve | `MapMississippi_bw.png` | LIKELY |
| 13 | Revontuli Coast | `MapRevontuli_bw.png` | LIKELY |
| 14 | New England Mountains ✔ | `MapNewEngland_bw.png` | VERIFIED |
| 15 | **no such slot** (no files, no table entry) | — | — |
| 16 | Emerald Coast Australia ✔ | `EmeraldCoast_bw.png` | VERIFIED |
| 17 | Sundarpatan Nepal | `MapSundarpatan_bw.png` | LIKELY |
| 18 | Salzwiesen Park | `Salzwiesen_Park_bw.png` | LIKELY |
| 19 | Askiy Ridge | `MapAskiyRidge_bw.png` | LIKELY |
| 20 | Tòrr nan Sìthean (Scotland) | `MapScotland_bw.png` | LIKELY |
| 21 | Intisuyu Hunting Preserve (Peru) | `MapPeru_bw.png` | LIKELY |

19 reserves exist; slots above 21 do not exist. This profile only owns/installs the
reserves behind slots **0–14 and 16** (DLCs for 17–21 are absent → no save files).

---

## 1. Evidence sources

| # | source | what it gives | weight |
|---|---|---|---|
| A | the save files themselves | which slots are real, when they were played, decompressed payload sizes | ground truth for *existence/activity* |
| B | `AnimalPopulationScanner.exe` | its own `-r <index>` help table + ordered list of 19 map PNGs | medium (see §5) |
| C | `cotwgc_*.txt` shipped in the **game** folder (`dropzone/ui/`) | the COTW Game Companion mod's reserve list with **game reserve ids**, per-reserve species hash lists, full species hash→name table, and a harvest history with timestamps + reserve ids + normalized map positions | high (real game ids and real user data) |
| D | web (Wikipedia / official posts / SteamDB) | 19 reserves exist; release years; Scotland update 2025-12-09; Revontuli 2022-06-28 | corroboration |

Key realisation: the population/fog/icon files are `SAVE`+`COMP` (zlib) containers. They
decompress to ADF payloads (`tools/decompress_all_saves.py`). The ADF payloads carry the
schema names (`AnimalPopulationReserveData`, `NeedZoneSave_3`, …) and, for
`found_need_zones_adf`, 64-byte zone records with world positions — see §6 — but **no
reserve name string and no readable species name** (species are numeric hashes).

## 2. The decisive test: harvest sessions vs. the population file the game wrote

No naming table is involved here. For each play session I took the *species* of the kills
(unique species pin the reserve) from the companion harvest log, and looked at which
`animal_population_<N>` the game wrote when that session ended.

| session (UTC) | species killed | only-in | file written | ⇒ slot |
|---|---|---|---|---|
| 2023-07-27 21:27 | Caribou | Yukon Valley | `animal_population_6` 22:04 | **6 = Yukon** |
| 2023-07-28 16:13–17:36 | Beceite/Ronda Ibex, Iberian Wolf, European Hare | Cuatro Colinas | `animal_population_8` 17:49 | **8 = Cuatro** |
| 2023-11-05 02:18–03:11 | Lion, Blue Wildebeest, Gemsbok, Scrub Hare | Vurhonga | `animal_population_3` 03:23 | **3 = Vurhonga** |
| 2024-05-18 11:13–11:41 | Whitetail Deer + Moose | New England | `found_icons_14` 11:44, fog 05-19, `animal_population_14` 05-25 | **14 = New England** |
| 2024-05-26 10:36–12:30 | Axis Deer, Puma, Collared Peccary | Parque Fernando | `animal_population_4` 12:50 | **4 = Parque** |
| 2024-05-29 13:28–16:30 | European Bison | Hirschfelden | `found_icons_0` 15:25, fog 17:39 | **0 = Hirschfelden** |
| 2026-10-27 13:17–14:39 | Rocky Mountain Elk, Pronghorn | Silver Ridge Peaks | `animal_population_9` 10-30 14:33 | **9 = SRP** |
| 2026-10-28/29 | Kangaroo, Sambar, Banteng, Saltwater Croc, Hog Deer | Emerald Coast | `animal_population_16` 10-29 18:24 | **16 = Emerald** |

Eight independent correlations, all consistent. Slot 14 is also a hard falsification of the
contiguous-release-order reading: it was written on **2024-05-18/25**, before Sundarpatan
(2024) shipped, and its session was Whitetail + Moose (New England), not Nepal species.

Independent cross-check: `cotwgc_challenges.txt` stores a "reserve written last at" epoch per
reserve, and six of them equal the byte-exact mtimes of the population files
(`w 3`=`pop_3` 2024-05-15 14:48:40, `w 4`=`pop_4` 2024-05-26 14:50:21, `w 8`=`pop_8`
2023-07-28 17:49:04, `w 14`=`pop_14` 2024-05-25 11:21:40, `w 5`=`pop_5` 2026-10-25 17:46:03,
`w 16`=`pop_16` 2026-10-29 19:24:16). The companion's `w` index space is therefore the save
slot space, and its *other* column (the reserve id) is what `t` harvest records and
`reserves.txt` use.

## 3. Why slots 5, 7 and 15 are holes

The companion reserve list is:

```
0 Hirschfelden      1 Layton        2 Medved          3 Vurhonga      4 Parque Fernando
6 Yukon Valley      8 Cuatro Colinas 9 Silver Ridge   10 Te Awaroa    11 Rancho del Arroyo
12 Mississippi      13 Revontuli    14 New England    16 Emerald      17 Sundarpatan
18 Salzwiesen       19 Askiy Ridge  20 Tòrr nan Sìthean  21 Intisuyu (Peru)
```

The shift grows by exactly one at Yukon (6 vs 5), at Cuatro (8 vs 6) and at Emerald
(16 vs 13) — i.e. at ids **5, 7 and 15**. So the game's reserve table contains three ids
that are not among the 19 released reserves (cut/placeholder content, or slots reserved and
later abandoned). The save system still emits population/fog files for ids 5 and 7, but for
this profile **id 15 has no file at all** — the game build simply has no entry there, which
is why there is no `animal_population_15` while both 14 and 16 exist.

This also explains the odd stub batch: on 2022-12-17 06:38:40 the game created stubs for
slots 0–13 in one go (14 slots — including the phantom 5 and 7), i.e. the profile's reserve
table had 14 entries at that time.

**Is slot 5 really a reserve?** No name can be attached to it. It is definitely a *live*
slot: `animal_population_5` was rewritten 2026-10-25 and its fog file was last touched
2024-05-29, yet `found_icons_5` is still the 542-byte stub (no need zone ever discovered) and
its decompressed population is only **67,974 B** versus 200–363 kB for real reserves
(stub = 2,110 B). A small/session-only map, or a mostly-empty slot the game touches on save,
fits all of that. Slot 7 is the same kind of hole but has never been played (all three files
are stubs). Both stay **UNKNOWN** in the JSON rather than being guessed — a wrong name here
would silently show the wrong map.

## 4. Owned vs. visited (save-file evidence)

Decompressed sizes (zlib-stripped) and mtimes:

| slot | pop file | decompressed | last pop write | fog | visited |
|---:|---:|---:|---|---|---|
| 0 | 104,333 | 285,838 | 2026-10-22 | 9,558 | yes |
| 1 | 881 stub | 2,110 | 2022-12-17 | 569 | never |
| 2 | 881 stub | 2,110 | 2022-12-17 | 569 | never |
| 3 | 92,002 | 264,410 | 2024-05-15 | 1,992 | yes |
| 4 | 104,191 | 286,754 | 2024-05-26 | 10,845 | yes |
| 5 | 1,425 | 67,974 | 2026-10-25 | 14,009 | odd (see §3) |
| 6 | 108,145 | 294,126 | 2023-07-27 | 2,356 | yes |
| 7 | 881 stub | 2,110 | 2022-12-17 | 569 | never |
| 8 | 87,573 | 248,774 | 2023-07-28 | 3,525 | yes |
| 9 | 66,065 | 201,462 | 2026-10-30 | 15,353 | yes |
| 10–13 | 881 stub | 2,110 | 2022-12-17 | 569 | never |
| 14 | 140,884 | 363,306 | 2024-05-25 | 7,045 | yes |
| 16 | 112,482 | 308,910 | 2026-10-29 | 15,314 | yes |
| 17–21 | absent | — | — | — | DLC not installed |

A population file is therefore **not** proof that a reserve is playable: the game writes
stubs for every table entry, holes included.

## 5. Warning: the scanner's index labels are shifted

`AnimalPopulationScanner.exe` contains one ordered table (19 map paths, release order with
the holes removed) and a usage text generated from it:

```
0 Hirschfelden  1 Layton Lakes  2 Medved Taiga  3 Vurhonga Savanna  4 Parque Fernando
5 Yukon Valley  6 Quatro Colinas  7 Silver Ridge Lakes  8 Te Awarora  9 Rancho del Arroyo
10 Mississippi Acres  11 Revontuli Coast  12 New England  13 Australia  14 Sundarpatan Nepal
15 Salzwiesen Park  16 Askiy Ridge  17 Scotland  17 Peru        <- note "17" twice
```

Those numbers are a contiguous renumbering, so for slot ≥ 5 they are one, two and finally
three slots too low (the duplicated `17` is the author's own slip: Scotland is 20, Peru 21).
Practical consequence: **treat the tool's reserve *name* as unreliable for a given
`animal_population_N`.** Cheap check: open `animal_population_16` in the scanner — it should
list Australian species (Axis Deer, Sambar, Banteng, Saltwater Crocodile, Kangaroo, Hog Deer,
Magpie Goose, Stubble Quail). If instead it shows Askiy Ridge species (Tahr, Snow Leopard,
Blue Sheep, Wild Yak, Barasingha) the tool's numbering is being used for display.

## 6. Map background → world coordinates (calibration hint)

* The save's need-zone records (`found_need_zones_adf`) store `Position` as **Vector3 in
  metres**: `Y` is altitude (observed 1022–2232 m) and the 2D map plane is **X/Z**, pooled
  range X −12136…11465, Z −13192…13184. So the world is **centred on the origin** and each
  reserve spans roughly 6–13 km per axis.
* The companion mod stores harvest positions as **normalized 0..1** (`p` records, e.g.
  `0.7558763 0.25439`), i.e. `u = (X − minX)/(maxX − minX)`, `v = (Z − minZ)/(maxZ − minZ)`.
  That is the space the map PNGs are drawn in.
* `animal_population_*.bin` declares a `MapPosition` `Vector2` per animal, but I found **no**
  float pair in either the metre range or a plausible 0..1 distribution (only 12 of ~250k
  aligned float pairs fall in 0.01–0.99 on both axes), so the population file most likely does
  not persist live animal XY — plan on deriving positions from need zones / world items, not
  from `MapPosition`, unless a real ADF parser says otherwise.
* **Orientation test was inconclusive.** Using 45 companion harvest points resolved to a
  reserve and all 8 dihedral transforms of the map images: water-hit rate is 0–4 % and
  "solid land" rate 44–67 % for *every* transform (the bw maps are only ~2–4 % water), so no
  transform is distinguishable. Identity (x→right, y→down) is the default because the images
  read as north-up topo maps and the companion plots y downward.
* Do not reuse one extent for all reserves: fit `(minX,maxX,minZ,maxZ)` (or a full affine)
  per reserve from many known points, then verify that the fitted box reproduces partner
  known landmark/need-zone positions.

Per-map pixel sizes (read with Pillow from `data/Maps`):

| map file | pixels | aspect | reserve (slot) |
|---|---|---|---|
| `MapHirsch_bw.png` | 1023 × 1152 | 0.888 | Hirschfelden (0) |
| `MapLayton_bw.png` | 1155 × 1136 | 1.017 | Layton Lake (1) |
| `MapMedved_bw.png` | 1170 × 1125 | 1.040 | Medved-Taiga (2) |
| `MapVurhonga_bw.png` | 1115 × 1053 | 1.059 | Vurhonga (3) |
| `MapParque_bw.png` | 1226 × 1202 | 1.020 | Parque Fernando (4) |
| `MapYukon_bw.png` | 1215 × 1070 | 1.136 | Yukon Valley (6) |
| `MapCuatro_bw.png` | 1212 × 1249 | 0.970 | Cuatro Colinas (8) |
| `MapSRP_bw.png` | 1343 × 1020 | 1.317 | Silver Ridge Peaks (9) |
| `MapNZ_bw.png` | 1143 × 968 | 1.181 | Te Awaroa (10) |
| `MapRancho_bw.png` | 1130 × 1097 | 1.030 | Rancho del Arroyo (11) |
| `MapMississippi_bw.png` | 1007 × 1098 | 0.917 | Mississippi Acres (12) |
| `MapRevontuli_bw.png` | 1159 × 1107 | 1.047 | Revontuli Coast (13) |
| `MapNewEngland_bw.png` | 954 × 1052 | 0.907 | New England Mts (14) |
| `EmeraldCoast_bw.png` | 1150 × 1110 | 1.036 | Emerald Coast (16) |
| `MapSundarpatan_bw.png` | 1339 × 1134 | 1.181 | Sundarpatan (17) |
| `Salzwiesen_Park_bw.png` | 1184 × 1113 | 1.064 | Salzwiesen Park (18) |
| `MapAskiyRidge_bw.png` | 1446 × 1467 | 0.986 | Askiy Ridge (19) |
| `MapScotland_bw.png` | 1300 × 1233 | 1.054 | Scotland (20) |
| `MapPeru_bw.png` | 1500 × 1468 | 1.022 | Peru (21) |

## 7. Residual risks / what would raise confidence

1. **Slots 5 and 7** — genuinely unidentified. If a future ADF parser can read
   `AnimalPopulationReserveData.ReserveSeed`/`NameHashId`, or if the game's `gameN.arc`
   block archives are unpacked, the ids there should name them (or prove they are placeholders).
2. **Slots 10–13** are placed only by bracketing between verified 9 and 14 plus the companion
   table; a save file played on one of them (currently all stubs) would settle it instantly.
3. **17–21** rest on the companion table alone (no local files). Order and names are otherwise
   consistent with the 19-reserve release schedule.
4. **Orientation/scale** — needs an actual fit, not a guess; the images carry no georeference.

## 8. How to re-run

```powershell
$py = "C:\Users\Maelo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
& $py tools\decompress_all_saves.py      # SAVE/COMP -> work\save_decompressed\*.bin
& $py tools\timeline.py                  # save writes vs. harvest events  (the decisive test)
& $py tools\build_reserves_json.py       # regenerates cotw\data\reserves.json
& $py tools\match_fog_to_map.py          # fog-vs-map correlation (inconclusive, kept for reference)
& $py tools\calib_test.py                # orientation test (inconclusive) + overlay preview
```

Intermediate artefacts: `work/strings.json` (scanner strings), `work/game_strings.json`
(game exe strings), `work/preview/` (map thumbnails, fog masks, a harvest overlay).

---

## CORRECTION — orientation de la carte (30 oct. 2026)

Le test d'orientation de 45 points de récolte était resté **non concluant**, et le code
avait tranché pour « +Z pointe au nord, donc on inverse l'axe vertical ». **C'était faux.**

Preuve directe : le joueur se tient à `z ≈ -13071` sur Silver Ridge Peaks, soit à 7 % du
bord `min_y`, et il rapporte être en **haut à gauche** de la carte. Seule la projection
identité (`v = (z - min_y) / (max_y - min_y)`, petit z en haut) le place là. L'ancienne
projection le dessinait en bas à gauche.

Signal indépendant : avec la projection identité, les zones d'abreuvement tombent mieux
sur les taches claires (eau) de la carte — luminosité moyenne 128.5 contre 119.1.

`Y_AXIS_FLIPPED` vaut désormais **false**. Si une réserve s'affiche à l'envers, c'est ce
seul constante qu'il faut basculer : la transformation directe, l'inverse (lecture du
curseur) et le test de survol en dérivent tous.

---

## GÉORÉFÉRENCE DES CARTES — récupérée par désassemblage (30 oct. 2026)

Le scanner sait placer les zones sur ses cartes. Le code a été retrouvé par les
identifiants ImGui de la fenêtre (`MapDrag`, `MapBox`), puis désassemblé avec Capstone
(`tools/scanner_disasm.py`). La fonction contient :

```
pixel_x = (world_x - origin_x) * width * scale / 800
pixel_z = (world_z - origin_z) * width * scale / 800
```

avec une table de **trois flottants par réserve** à VA `0xB0040` (offset fichier
`0xAE240`) : `origin_x`, `origin_z`, `scale`. Le même facteur sert aux deux axes, donc la
projection est **isotrope**.

### Pourquoi c'est fiable

* Les indices 5, 7 et 15 de la table valent `(1, 1, 1)` — exactement les emplacements de
  réserve que nous avions identifiés comme inconnus. L'alignement des indices est donc
  confirmé par une donnée indépendante.
* Le facteur `width * scale / 800` vaut **0.1246–0.1253 px/m sur 15 des 19 réserves**,
  soit 8 m par pixel. Cette invariance n'a aucune raison d'émerger par hasard : le
  scanner garde une résolution au sol uniforme et ajuste `scale` selon la largeur d'image.
* **100 % des zones tombent dans leur propre emprise**, sur les 19 réserves.
* Sur Silver Ridge Peaks, le joueur `(-7570.5, -13071.9)` tombe à 20.5 % de la gauche et
  **3.8 % du haut** : le coin haut-gauche, au bord du lac — conforme à ce qu'il observe.
* Zones d'abreuvement sur l'eau : 32 % contre 4 % pour le nourrissage (le masque d'eau
  n'est exploitable que sur les cartes à taches claires ; ailleurs les lacs sont rendus
  différemment, d'où des scores nuls sans que cela invalide la géoréférence).

### Mise en œuvre

`tools/import_map_geo.py` lit la table et écrit `cotw/data/map_geo.json`.
`population.reserve_world()` préfère cette valeur mesurée à la boîte déduite des zones.
L'ancien `fitted_world` reste en repli pour une réserve sans table.
