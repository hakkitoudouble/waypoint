# AnimalPopulationScanner.exe — static reverse-engineering notes

Target: `AnimalPopulationScanner.exe` v1.2.15.1 (2026-06-28), 1,176,576 bytes
Path: `C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\AnimalPopulationScanner.exe`

Companion artifacts produced by this analysis (all under `cotw-pop\`):

| file | contents |
|---|---|
| `notes\exe-strings.txt` | full annotated string dump (8,829 ASCII + 45 UTF-16LE runs, with file offset, VA, section) |
| `notes\strings-uniq.json` | sorted-unique string list |
| `notes\localization-en.json` | the exe's 359-entry English UI+species string table, id → text |
| `notes\langtables.json` | the same table for the other six language blocks (imperfectly split, informational) |
| `cotw\data\species_hashes.json` | **`NameHashId` → species name**, 135 entries |
| `cotw\data\species_stats.json` | per-species constants (difficulty rating, float arrays, icon, hashes) |
| `tools\*.py` | the analysis scripts (PE parser, string dumper, xref engine, extractor, validator) |

Confidence tags used below: **VERIFIED** (read directly out of the binary and independently cross-checked), **LIKELY** (strong convergent evidence, not proven), **SPECULATIVE** (plausible reading), **UNKNOWN**.

---

## 1. PE layout (VERIFIED)

Parsed by `tools\pe.py`. Image base `0x140000000`, x64, native, subsystem 2 (GUI), entry point
`VA 0x140080AE8`, timestamp `0x6A412E03` = **2026-06-28 14:21:55 UTC**, no debug directory with
symbols, no CLR directory.

| section | VA | file offset | virtual size | raw size | notes |
|---|---|---|---|---|---|
| `.text` | `0x140001000` | `0x400` | `0x84750` | `0x84800` | R-X |
| `.rdata` | `0x140086000` | `0x84C00` | `0x295A8` | `0x29600` | R-- ; strings, IAT, x64 unwind-free const data |
| `.data` | `0x1400B0000` | `0xAE200` | `0x40338` | `0x3E600` | RW- ; **raw covers RVA 0xB0000–0xEE600 only** |
| `.pdata` | `0x1400F1000` | `0xEC800` | `0x5760` | `0x5800` | R-- |
| `.rsrc` | `0x1400F7000` | `0xF2000` | `0x2BA20` | `0x2BC00` | R-- |
| `.reloc` | `0x140123000` | `0x11DC00` | `0x1698` | `0x1800` | R-- |

Conversion rules used throughout (getting this wrong is the classic trap):

```
file_offset = section.rawptr + (VA - image_base - section.vaddr)     # only if inside raw range
rva         = VA - 0x140000000
```

**Important consequence:** `.data` has a *zero-filled tail* from RVA `0xEE600` to `0xF0338`
(VA `0x1400EE600`–`0x1400F0338`). Anything that lands there reads as zero from the file but is
written at runtime. Section-alignment: 0x1000 virtual / 0x200 file.

Relocation table (70 blocks, RVA `0x123000`) covers `.rdata` pages `0x086000–0x0A0000`,
`0x098000–0x09A000` and `.data` pages `0x0B0000–0x0EE000`. There are **no** relocations at or
above RVA `0x0EE4D0`, i.e. nothing in the `.data` zero-filled tail is an initialised pointer.

---

## 2. The `NameHashId` → species mapping  — **VERIFIED**

### 2.1 There *is* an explicit table, and it is in `.data`, not `.rdata`

**Location: VA `0x1400B0C80`, file offset `0xAEE80`** (RVA `0xB0C80`).

* 135 entries (`0x87`), stride **16 bytes**, total `0x870` bytes (`0xAEE80`–`0xAF6F0`).
* Record layout: `struct { uint32 nameHashId; uint32 padding; uint64 speciesRecordPtr; }`
* All `padding` fields are 0. All `speciesRecordPtr` values are absolute VAs into `.data`.

First four entries (raw bytes at file `0xAEE80`), so the layout is unambiguous:

```
61 15 5d 1a  00 00 00 00  c0 08 0b 40 01 00 00 00   -> hash 0x1A5D1561, rec 0x1400B08C0
5d 6c fa c5  00 00 00 00  30 10 0c 40 01 00 00 00   -> hash 0xC5FA6C5D, rec 0x1400C1030
90 44 80 7d  00 00 00 00  70 39 0c 40 01 00 00 00   -> hash 0x7D804490, rec 0x1400C3970
d1 af 27 85  00 00 00 00  70 39 0c 40 01 00 00 00   -> hash 0x8527AFD1, rec 0x1400C3970
```

### 2.2 The resolver (linear scan, not a hash map)

Function region `VA 0x140056ED0`…`0x1400576CC`. The lookup is at `0x140056F49`–`0x140056F6B`
(file `0x56349`–`0x5636B`):

```asm
140056F49  33 C0                 xor   eax, eax                  ; i = 0
140056F4B  48 8D 3D 2E 9D 05 00  lea   rdi, [rip+0x59D2E]        ; rdi = 0x1400B0C80  (table base)
140056F52  48 8B CF              mov   rcx, rdi
140056F55  39 19                 cmp   dword ptr [rcx], ebx      ; table[i].hash == wantedHash ?
140056F57  74 0F                 je    0x140056F68
140056F59  FF C0                 inc   eax
140056F5B  48 83 C1 10           add   rcx, 0x10                 ; stride 16
140056F5F  3D 87 00 00 00        cmp   eax, 0x87                 ; 135 entries
140056F64  72 EF                 jb    0x140056F55
140056F66  EB 31                 jmp   0x140056F99                ; not found
140056F68  48 03 C0              add   rax, rax                  ; rax = 2*i
140056F6B  48 8B 7C C7 08        mov   rdi, [rdi+rax*8+8]        ; rdi = table[i].ptr  (== base + 16*i + 8)
```

Notes:
* `0x87` (135) is a literal count control, so the table length is exact.
* `ebx` (the wanted hash) is read little-endian from the population file, byte by byte, just
  before the loop (`0x140056F23`–`0x140056F47`) — i.e. the save stores the hash as a plain LE u32.
* If the hash is not found, the code falls through to the sentinel checks at `0x140056F70` /
  `0x140056F8D` and then to the "unknown species" path, which logs
  `"Unknown species (ID:0x%x) - skipping"` / `"Unknown species ID: "` (strings at
  `VA 0x140098FE8` / `0x140098FD0`, referenced from `0x140056FE8` / `0x140056FA7`).
* A second resolver exists that behaves identically; the same table base appears again, so the
  table is the single source of truth.

### 2.3 126 unique species records (VERIFIED)

Records are `0x3C0` bytes apart, first at **VA `0x1400B08C0`** (file `0xAEAC0`), last at
`0x1400CED70`; 126 live records (the 135 hashes collapse onto 126 records — several species carry
2–3 different `NameHashId`s).

Record layout (confirmed by full 0x3C0-byte dumps of several records):

| offset | type | meaning | confidence |
|---|---|---|---|
| `+0x000` | `i32` | **stringId** → index into the runtime localization table (see §3) | VERIFIED |
| `+0x004` | `i32` | padding, always 0 | VERIFIED |
| `+0x008` | `char*` | icon path, e.g. `"data/Icons/Reddeer_frame.png"` | VERIFIED |
| `+0x010` | `i32` | max difficulty rating, values 1…9 | LIKELY |
| `+0x014` | `i32` | unknown, values {0,1,2,3,4,8,9} | UNKNOWN |
| `+0x018` | `f32` | always `0.0` | VERIFIED |
| `+0x01C` | `f32[3]` | ascending per-species triple | SPECULATIVE (§6) |
| `+0x028` | `f32[2]` | always `0.0` | VERIFIED |
| `+0x030` | `f32[8]` | ascending series, zero-padded; **exactly 2, 4 or 8** non-zero entries | LIKELY weight (§6) |
| `+0x050` | `i32` | 0 or 1 | UNKNOWN |
| `+0x054` | `i32` | small ints {0,1,2,3,4,6,8,11,12,13,14,16,17,21} | UNKNOWN |
| rest | — | all zero in every record (verified: only `+0x54` is ever non-zero above `+0x50`) | VERIFIED |

### 2.4 How the display name is obtained — no `(hash, char*)` table exists

Negative results first, stated plainly:

* **There is no `(uint32 hash, char* name)` pair table in `.rdata`.** The hash table in `.data`
  stores a *pointer to a struct*, never a name pointer.
* **There is no static array of name pointers anywhere in the file.** I scanned every 8-byte
  aligned and unaligned qword in all sections for runs of ≥16 pointers into the image; the only
  contiguous pointer array in `.rdata` is zlib's `z_errmsg` at `VA 0x140089750`. Searching for a
  pointer to any of the species-name literals (e.g. `"Red Deer"` `VA 0x14008F420`,
  `"Axis Deer"` `VA 0x14008EEE8`, `"Rothirsch"` `VA 0x140090968`) returns **zero hits** anywhere
  in the file. The literals are only ever reached by RIP-relative `lea` inside `.text`.

The actual mechanism (VERIFIED):

1. Species names — and every UI string — are plain NUL-terminated ASCII literals in `.rdata`
   (the English block sits roughly at `VA 0x14008ED00`–`0x140090A00`; German, Spanish, Portuguese
   and French blocks follow, e.g. `"Axishirsch"` @ `0x1400904E0`, `"Ciervo Axis"` @ `0x140093E10`,
   `"Lobo Cinzento"` @ `0x1400969A0`, `"Cerf de l'Axe"` @ `0x140097670`).
2. At start-up the exe materialises a **359-entry `char*` table into `.data`'s BSS at
   `VA 0x1400EF3A0`** (RVA `0xEF3A0`, size `0x167*8 = 0xB38`, file offset *none* — zero-fill tail).
   It does this with ~2,342 inline `lea rax,[rip+literal]` / `mov [rip+slot],rax` pairs spanning
   `VA 0x140040497`–`0x14004832C`, one 359-entry block per UI language. **The English block is the
   first one, starting at `VA 0x140040497`.**
3. A separate routine at `VA 0x140040070` iterates that array with a hard-coded count
   `mov ebx, 0x167` (`0x1400400E6`) to pre-compute text widths — this is what pins the array
   length at **359**.
4. Species record `+0x000` is an index into that array. The consumer at `0x1400570AE`:

```asm
1400570AE  48 63 07              movsxd r8, dword ptr [rdi]     ; rdi = species record; r8 = stringId
1400570B1  48 8D 15 E8 82 09 00  lea    rdx, [rip+0x982E8]      ; rdx = 0x1400EF3A0
1400570B8  48 8B 14 C2           mov    rdx, [rdx+r8*8]         ; rdx = names[stringId]
1400570BC  4C 8D 0D A5 7C 03 00  lea    r9, [rip+0x37CA5]       ; r9 = "<missing>"  (0x14008ED68)
1400570C3  48 85 D2              test   rdx, rdx
1400570C6  4C 0F 45 CA           cmovne r9, rdx
...
1400570CA  48 8D 15 3F 1F 04 00  lea    rdx, [rip+0x41F3F]      ; fmt = "...ate entry for 0x%x (%s)!\n"
1400570D8  E8 53 8A FB FF        call   0x14000FB30             ; log(fmt, hash, name)
```

The string at `VA 0x14008ED68` really is the literal `"<missing>"`, and the log format string at
`VA 0x140099017` is `"te entry for 0x%x (%s)!\n"` (continuation of a longer message), confirming
that argument 2 is a human-readable species name.

**So the full chain is: save `NameHashId` → 135-entry table → species record → `stringId` →
`names[stringId]` → English display name.** This is why the ID space is shared between UI strings
and species names (e.g. id 26 = `"Axis Deer"` but id 36 = `"Can't open file"`) — it is one
localization enum.

Extracted English table (`notes/localization-en.json`, 359 entries) — the species part:

```
26 Axis Deer          27 Beceite Ibex        28 Bighorn Sheep       29 Desert Bighorn Sheep
30 RM Bighorn Sheep   31 Black Bear          32 Blackbuck           33 Blacktail Deer
34 Blue Wildebeest    35 Brown Bear          37 Canada Goose        38 Cape Buffalo
39 Caribou            40 Chamois             41 Cin Teal            48 Coyote
53 Eurasian Lynx      54 Euro Bison          55 Euro Rabbit         56 European Hare
57 Fallow Deer        58 Feral Goat          59 Feral Pig           62 Gemsbok
63 Gredos Ibex        64 Grey Wolf           65 Grizzly Bear        67 H Duck
69 Iberian Mouflon    70 Iberian Wolf        72 Jackrabbit          75 Lesser Kudu
77 Lion               83 Mallard             85 Moose               86 Mountain Goat
87 Mountain Lion      88 Mule Deer           89 Musk Deer           93 Plains Bison
94 Pronghorn          95 Puma                96 RM Elk              97 Red Deer
98 Red Fox            99 Reindeer           104 Roe Deer           105 Ronda Ibex
106 Roosevelt Elk     107 S-Striped Jackal   108 SES Ibex           110 Scrub Hare
112 Sika Deer         116 Springbok          123 Turkey             125 Warthog
126 Water Buffalo     127 Whitetail Deer     128 Wild Boar          129 Wild Hog
168 Pheasant          169 RG Turkey          170 Mexican Bobcat     171 Ant. Jackrabbit
172 Coll. Peccary     174 Bobwhite Quail     175 EW Turkey          176 ECt Rabbit
177 Raccoon           178 Gray Fox           179 Am. Alligator     198 Eu.Wigeon
199 T.Bean Goose      200 Eu.Teal            201 Black Grouse       202 Goldeneye
203 Hazel Grouse      204 W.Capercaillie      205 Tufted Duck        206 Rock Ptarmigan
207 Willow Ptarmigan  208 Greylag Goose      209 Mountain Hare      210 Raccoon Dog
223 Green-Winged Teal 224 Bobcat             226 EG Kangaroo        227 SW Crocodile
228 Banteng           229 Javan Rusa         230 Hog Deer           231 Magpie Goose
232 Sambar            233 Stubble Quail      236 Bengal Tiger       237 Snow Leopard
238 Wild Yak          239 Muntjac            240 Tibetan Fox        241 Nilgai
242 Tahr              243 Barasingha        244 Blue Sheep         245 Woolly Hare
256 Gadwall           257 Ferruginous Duck   302 Beaver             303 Wood Bison
304 Manitoban Elk     305 Dusky Grouse       306 Pintail            307 Wood Duck
308 Snow Goose        309 Caribou            325 Euro Badger        327 American Mink
328 Pine Marten       329 Woodcock           330 Red Grouse         335 SA Tapir
336 Ocelot            337 Greater Grison     338 WM Coati           339 Vicuña
340 Capybara          341 Spectacled Bear     342 Jaguar             343 Black Caiman
344 Taruca
```

Only four animal-looking ids in that range are **not** used by any record: 28 `Bighorn Sheep`,
30 `RM Bighorn Sheep`, 87 `Mountain Lion`, 129 `Wild Hog` (aliases of 29, 29, 95, 128).

Caveat worth knowing: the record with icon `Bighornsheep_frame.png` carries `stringId 29`
= *"Desert Bighorn Sheep"*, even though it shows up in the save that also contains Mountain Goat /
Plains Bison / RM Elk (a Rocky-Mountain-bighorn roster). Either the author used one record for both
bighorn species or the label is a misnomer. Treat names as *the tool's* labels, not gospel taxonomy.
Similarly `Rooseveltelk_frame.png` is shared by id 96 (`RM Elk`) and id 106 (`Roosevelt Elk`),
`WillowPtarmigan_frame.png` by id 206 (`Rock Ptarmigan`) and 207 (`Willow Ptarmigan`),
`Turkey_frame.png` by ids 123/169/175, `Bobcat_frame.png` by 170/224, `EurasianTeal_frame.png`
by 200/223.

### 2.5 Independent validation against the real save files — VERIFIED

`tools\validate_saves.py`: decompress each `animal_population_*` (SAVE → zlib) and do a plain
4-byte little-endian byte search for each of the 135 hash values. No ADF parsing involved.

* **73 of 135** hashes occur verbatim in at least one real population file.
* No hash ever appears in a file whose reserve roster it does not belong to (checked by hand
  against the per-file species lists below).
* The 62 unmatched hashes are simply species the player has not generated populations for yet.

The decisive check: converting the per-file hash sets to names reproduces the exact, well-known
COTW reserve rosters.

| save file | decompressed | species found (tool names) | reserve this must be |
|---|---|---|---|
| `animal_population_0` | 285,838 | Canada Goose, Euro Bison, Euro Rabbit, Fallow Deer, Red Deer, Red Fox, Roe Deer, Wild Boar, Pheasant | **Hirschfelden** |
| `animal_population_3` | 264,410 | Blue Wildebeest, Cape Buffalo, Gemsbok, Lesser Kudu, Lion, S-Striped Jackal, Scrub Hare, Springbok, Warthog, Eu.Wigeon | **Vurhonga Savanna** |
| `animal_population_4` | 286,754 | Axis Deer, Blackbuck, Cin Teal, Mule Deer, Puma, Red Deer, Water Buffalo, Coll. Peccary | **Parque Fernando** |
| `animal_population_6` | 294,126 | Canada Goose, Caribou, Grey Wolf, Grizzly Bear, H Duck, Moose, Plains Bison, Red Fox | **Yukon Valley** |
| `animal_population_8` | 248,774 | Beceite Ibex, European Hare, Gredos Ibex, Iberian Mouflon, Iberian Wolf, Red Deer, Roe Deer, Ronda Ibex, SES Ibex, Wild Boar, Pheasant | **Cuatro Colinas** |
| `animal_population_9` | 201,462 | Desert Bighorn Sheep, Black Bear, Blacktail Deer, Mountain Goat, Mule Deer, Plains Bison, Pronghorn, Puma, RM Elk, Turkey | **Silver Ridge Peaks** (LIKELY) |
| `animal_population_14` | 363,306 | Black Bear, Coyote, Mallard, Moose, Red Fox, Whitetail Deer, Pheasant, Bobwhite Quail, EW Turkey, ECt Rabbit, Raccoon, Gray Fox, Goldeneye, Green-Winged Teal, Bobcat | **New England Mountains** |
| `animal_population_16` | 308,910 | Axis Deer, Fallow Deer, Feral Goat, Feral Pig, Red Deer, Red Fox, EG Kangaroo, SW Crocodile, Banteng, Javan Rusa, Hog Deer, Magpie Goose, Sambar, Stubble Quail | **Emerald Coast Australia** |

Reserve *identification* is LIKELY (roster match); the species-per-file lists themselves are
VERIFIED. This gives a free bonus: the population-file index `N` in `animal_population_<N>`
corresponds to the reserve order used by the tool. Confirmed pairs: 0→Hirschfelden,
3→Vurhonga Savanna, 4→Parque Fernando, 6→Yukon Valley, 8→Cuatro Colinas, 9→Silver Ridge Peaks,
14→New England Mountains, 16→Emerald Coast Australia. The exe's reserve list (18 entries, from the
same string table) is: Hirschfelden[68], Layton Lake[74], Medved Taiga[84], Parque Fernando[91],
Silver Ridge Peaks[113], Te Awaroa[119], Vurhonga Savanna[124], Yukon Valley[131], Rancho del
Arroyo[167], Mississippi Acres[173], Revontuli Coast[197], New England Mountains[222], Emerald
Coast Australia[225], Sundarpatan Nepal[235], Salzwiesen Park[255], Askiy Ridge[301],
Tòrr nan Sithean Scotland[326], Intisuyu Peru[334] — but only 17 save slots exist (0…16), so
`saveIndex → reserve` is not simply `reserveIndex`; do not assume it without more data.

### 2.6 The hash function — **NOT CRACKED** (negative result)

I could not derive the hash function, and the exe does not contain one for this purpose (it only
consumes the hashes), so a table is the only recoverable ground truth.

What was tried (`tools\crack.py`), against all 135 pairs:

* Hash functions: CRC32 (zlib poly), CRC32C, FNV-1a-32, FNV-1-32, XXH32(seed 0),
  MurmurHash3_x86_32(seeds 0, 1, 0xFFFFFFFF), MurmurHash2_32(seed 0), Jenkins one-at-a-time,
  djb2, djb2-xor, sdbm, Java `hashCode`, ELF hash, PJW hash, and three Avalanche-style
  `h = (h<<5) ± h + c` / `h = c + (h<<5) + (h>>2)` variants.
* Input spellings, generated from both the icon stem and the English name: as-is, lower, upper,
  CamelCase, snake_case (`red_deer`), collapsed (`reddeer`), hyphen, space, and 16
  prefix/suffix/path templates (`animal_%s`, `animals/%s`, `/animals/%s/%s`, `%s.adf`, `%s_01`,
  `%sAnimal`, `Animals/%s`, …), each also tried lower/upper.
* Result: **zero matches** on all 135 hashes for every (function, spelling) combination.

Additional observation that constrains any future attempt: several species have **two or three
different** `NameHashId`s pointing at the same species (Red Deer `0xD8B6A893` + `0x1998199C`,
Wild Boar `0x08CBEB4A` + `0x5DA156C9`, Moose `0x0941ABE8` + `0x6C0365E2`, Red Fox `0x7D804490` +
`0x8527AFD1` + `0x833A5EC5`, Fallow Deer `0x2F9AC7B7` + `0x08D561A7`, Roe Deer `0x7A5DC096` +
`0x9BAE9443`, Mallard `0x7193A92E` + `0x02B03AA7`, Bighorn `…`, Peccary `0x6B20CB0D` +
`0xC500A572`, Feral Pig/Wild Boar share `0x2D774864` vs `0x08CBEB4A`). So the hashed string is
**not** a one-to-one species name — it is per-*asset* (per sex variant, per DLC release, or per
game version). That makes pure dictionary brute force much less likely to succeed.

**Best next step:** ask the parent to run our ADF parser over a population file and dump the raw
`NameHashId` u32s together with `SpawnAreadId` and `NeedZonePathGuids`; then check whether a
`NameHashId` correlates with a need-zone path GUID prefix, or with `SpawnAreadId`, which would
tell us the hashed string's family. Failing that, treat `species_hashes.json` as the lookup table —
it is complete for the species the tool supports and is what the tool itself uses.

---

## 3. Complete `NameHashId` → species table (VERIFIED)

See `cotw\data\species_hashes.json`. Format:

```json
{ "_hashfn": null,
  "1A5D1561": "Euro Rabbit",
  "C5FA6C5D": "Canada Goose",
  ...
  "_note": "...", "_hashfn_status": "...", "_verifiedInSaves": { "1A5D1561": ["animal_population_0"], ... } }
```

All 135 keys are bare uppercase hex of the u32 (no `0x`), exactly as the save stores it
little-endian. `_verifiedInSaves` lists which real population files each hash was found in.

Representative rows (full list in the JSON):

| hash | species | hash | species |
|---|---|---|---|
| `08CBEB4A` | Wild Boar | `1998199C` | Red Deer |
| `0941ABE8` | Moose | `1A5D1561` | Euro Rabbit |
| `0AF54EC2` | Blue Wildebeest | `2D30B3CE` | Pronghorn |
| `2F9AC7B7` | Fallow Deer | `2FDCAF40` | S-Striped Jackal |
| `3EFC8F2B` | Euro Bison | `4471AF29` | Gemsbok |
| `4AEF8190` | Desert Bighorn Sheep | `4AE050AB` | H Duck |
| `5DA156C9` | Wild Boar | `6B20CB0D` | Coll. Peccary |
| `7193A92E` | Mallard | `7A5DC096` | Roe Deer |
| `82770585` | Lion | `9119DA8D` | Black Bear |
| `B0113E10` | Mule Deer | `B54E5E8B` | Coyote |
| `C55BB24F` | Cape Buffalo | `CB0DA701` | Axis Deer |
| `D8B6A893` | Red Deer | `E53D3987` | Whitetail Deer |
| `F243B31E` | Springbok | `FB4C7AD6` | Tahr |

---

## 4. Difficulty-rating vocabulary (VERIFIED)

Function at **VA `0x140040330`**, file offset `0x3F730`:

```asm
140040330  FF C9                    dec   ecx                ; input is 1-based
140040332  83 F9 09                 cmp   ecx, 9
140040335  0F 87 0D 01 00 00        ja    0x140040448        ; -> default
14004033B  48 8D 15 BE FC FB FF     lea   rdx, [rip-0x40342] ; rdx = 0x140000000 (jump-table base bias)
140040342  8B 8C 8A 60 04 04 00     mov   ecx, [rdx+rcx*4+0x40460]
140040349  48 03 CA                 add   rcx, rdx
14004034C  FF E1                    jmp   rcx
```

Jump table: 10 dwords at **RVA `0x40460`** (VA `0x140040460`, file `0x3F860`); case *i* loads
`names[i+1]` from the runtime string table. Therefore:

| rating | name | rating | name |
|---|---|---|---|
| 1 | **Trivial** | 6 | **Hard** |
| 2 | **Minor** | 7 | **Very Hard** |
| 3 | **Very Easy** | 8 | **Mythical** |
| 4 | **Easy** | 9 | **Legendary** |
| 5 | **Medium** | 10 | **Fabled** |

Anything outside 1…10 returns `names[0]` = `"???"`. Note *Fabled* exists only in this tool — it is
how the tool labels Great Ones, which is consistent with the `"You might have a Great One %s in
your population file (#%X)"` message (English `VA 0x14008F638`).

Species record `+0x010` holds a value in 1…9 which matches the known COTW difficulty ceiling for
that species (Bison 9/Legendary, Moose 8/Mythical, Brown Bear 7/Very Hard, Red Deer 6/Hard,
Fallow/Whitetail/Blacktail/Mountain Goat 4/Easy, Roe Deer/Pronghorn 3/Very Easy, Coyote/Red Fox
2/Minor, Jackrabbit/Mallard/Turkey/Pheasant 1/Trivial). **LIKELY** = max difficulty rating.

---

## 5. Fur / variant vocabulary (`FeatureModifiers`) (names VERIFIED, bit mapping NOT FOUND)

The full fur vocabulary lives in the same localization enum. Names are **space-padded to a fixed
width** in the exe (the padding is part of the literal, so trim before comparing):

| string ids | names |
|---|---|
| 138–147 | `Albino`, `Piebald`, `Piebald1`, `Piebald2`, `Piebald-Wht.`, `Melanistic`, `LG Leucist.`, `Light Grey`, `Bald Leucistic`, `Leucistic` |
| 148–162 | `Red`, `Crowned`, `Gold`, `Gold`, `Dark Brown`, `Blonde`, `Egg White`, `Brown`, `Winter`, `Light Brown`, `Black`, `BlackSpots`, `BlackSpots1`, `BlackSpots2`, `Pink` |
| 180–196 | `Piebald-Grey`, `Piebald-Blnd`, `Cinnamon`, `Grey`, `Blackgold`, `Dusky`, `Redbrown`, `Beige`, `Dilute`, `Orange`, `Dark`, `Olive`, `Mixed`, `Spotted Red`, `Blue`, `Ochre`, `Combined` |
| 211–218 | `Eclipse`, `Hybrid`, `Hybrid Green`, `Hybrid Blue`, `Pale`, `Cream`, `White`, `Molting` |
| 246–247 | `Smoke`, `Sand` |
| 258–300 | `Mottled`, `Bright`, `Grey Brown`, `Bicolor`, `Spirit`, `Black Brown`, `Black White`, `Blue Grey`, `Bronze`, `Brown Hybrid`, `Buff`, `Caramel`, `Chestnut`, `Chocolate`, `Dark Green`, `Dark Grey`, `Dark Red`, `D Red Brown`, `Dark Spotted`, `Dusky Gradient`, `Eggwhite`, `Honeytones`, `Jet Black`, `Jet Brown`, `Light Bronze`, `Light Green`, `Lightbuff`, `Maroon`, `Mocha`, `Pristine`, `Ps Melanistic`, `Ps Mela Wht`, `Slate Grey`, `Spotted`, `Spotted Dark`, `Straw`, `Tan`, `Tawny`, `Two Tones`, `White Brown`, `Wht Stripeless`, `Yellow`, `Snow` |
| 310–324 | `Erythristic`, `Dilute Silver`, `Erythr. Gold`, `Blue Morph`, `Interm. Morph`, `White Morph`, `Brown Maned`, `Reddish Brown`, `Ginger`, `Ginger Split`, `Standard`, `White Hybrid`, `Acromelanistic`, `Melanistic Charc.`, `Mosaic` |
| 331–333 | `Erythr. Red`, `Silver`, `Purple Grey` |
| 345–358 | `X-Markings`, `Bold`, `Rosetted`, `Glasses`, `Chaotic`, `Minimalistic`, `No Markings`, `Fine`, `Erythr. Isabel.`, `Messy`, `Abundant`, `Blond-Faced`, `Brown-Grey`, `Erythr. Choc.` |

Category / UI labels: `137 Rare Fur Types`, `219 Rare Fur Types`, `220 Very Rare Fur Types`,
`135 Hiding`, `165 TBD` (used where a species has no data).

Note the plain, non-`Erythr.` spellings the task listed — `Red`, `Black`, `BlackSpots`,
`BlackSpots1`, `BlackSpots2`, `Blackgold`, `Redbrown`, `White`, `Black Brown`, `Black White`,
`White Brown`, `White Morph` — are **all present**, at ids 148, 158, 159, 160, 161, 184, 186, 217,
263, 264, 297, 315 respectively. The task's `Placeholder` corresponds to the asset
`data/Icons/Placeholder.png` and to strings `165 "TBD"` / `164 "None"`, not to a fur name.

**Negative result, stated plainly: I did not find a (bit index → fur name) table.**
Evidence for that conclusion:

* `.data` contains only the 126 species records (up to RVA `0xCE0F0`) plus the 135-entry hash
  table; everything after RVA `0xEE600` is the zero-filled BSS tail with no relocations. Scanned
  `.data` for any run of ≥14 u32s in `[1,360]` that could be a 32-entry stringId table — **0 hits**.
* `.rdata` contains exactly 7 such numeric runs and all are zlib tables (`extra-bits`, `base`,
  `dist` tables around `VA 0x14008E6D0`–`0x14008E8E0`) or ImGui constants.
* The localization array at `0x1400EF3A0` is referenced by only **six** `lea` sites in the whole
  `.text` (`0x1400400DF` init loop, `0x1400570B1`, `0x140057FE5`, `0x1400587BD`, `0x1400588B5`,
  `0x140063522`). All of them fetch a name by dereferencing a `stringId` that is reached via a
  pointer at `[struct+0x338]` (or via `[rsp+0x6c]`) — i.e. the tool always looks the name up from
  a *record pointer*, never from a bit index. A `FeatureModifiers`-bit decoder therefore does not
  live in a table; if it exists at all it must be inside the ingest path
  (`0x140056B80` / `0x140056ED0`) or produced elsewhere in the animal-entry struct.

**Best next step for the bit mapping:** take a real `AnimalData_5.FeatureModifiers` value from a
save together with the fur name the tool displays for that animal; run the tool on the same file
and read the label it shows. Two or three such (value, label) pairs per species pin the bit
assignment empirically and unambiguously, which is much cheaper than chasing the decoder. Also note
that a single u32 cannot index ~150 names, so `FeatureModifiers` is almost certainly a *bitfield*
with per-species semantics, and the names above are grouped in the enum in DLC/release order
(138–162, 180–196, 211–218, 246–247, 258–300, 310–324, 331–333, 345–358) which strongly suggests
the underlying `enum FurType` was extended with each DLC.

---

## 6. Per-species numeric tables (`cotw\data\species_stats.json`)

Everything below is read out of the 126 species records at the documented offsets. **No guessing
is applied inside the JSON** — the raw values are there; interpretation is in this section only.

Schema (see `_schema` in the JSON):

```json
{ "_schema": { "record_layout": {...}, "difficultyLevelNames": [...], "confidence": {...} },
  "species": [
    { "stringId": 97, "name": "Red Deer", "icon": "data/Icons/Reddeer_frame.png",
      "maxDifficultyRating": 6, "field_0x14": 1,
      "field_0x18": 0.0, "triple_0x1C": [90.5, 182.2, 251.0], "field_0x28": [0.0, 0.0],
      "series_0x30": [147.5, 167.0, 177.0, 186.4, 197.5, 207.8, 218.2, 228.33],
      "field_0x50": 1, "field_0x54": 0,
      "hashes": ["1998199C", "D8B6A893"], "hashesSeenInSaves": ["1998199C", "D8B6A893"] },
    ... ] }
```

### 6.1 `series_0x30` — **LIKELY the weight breakpoints (kg) used for Difficulty Rating**

* Always strictly ascending, always zero-padded, and the non-zero count is **exactly 2, 4 or 8**
  (58 species have 4, 38 have 2, 30 have 8).
* The magnitudes match the real body weight of the species in kilograms across dozens of
  independent cases, which is the strongest available evidence:

| species | `series_0x30` | real weight | verdict |
|---|---|---|---|
| Grey Wolf | 33.6, 42.2, 48, 53, 57.82, 63.1 | 30–60 kg | fits |
| Roosevelt Elk | 325, 360, 400, 470 | 300–500 kg | fits |
| Plains Bison | 550, 750, 930, 1100 | 550–1100 kg | fits |
| Water Buffalo | 650, 730, 785, 858.7, 935, 1011 | 600–1000 kg | fits |
| Wild Boar | 82.3, 124, 168.7, 217 | 80–200 kg | fits |
| Coll. Peccary | 19.5, 22.22, 25.8, 29.7 | 15–25 kg | fits |
| Wild Yak | 600, 700, 800, 900, 960, 1018 | 350–1000 kg | fits |
| Jaguar | 67, 73.7, 80.3, 90, 94, 99.5 | 60–100 kg | fits |
| Snow Leopard | 33, 37.7, 42, 47.5, 53, 58.63 | 30–60 kg | fits |
| Capybara | 43.2, 49, 58.1, 65.75 | 35–66 kg | fits |
| Pheasant | 1.62, 2.74 | 1–2 kg | fits |
| Mallard | 1.36, 1.95 | 0.7–1.6 kg | fits |
| Greylag Goose | 2.8, 3.18, 3.5, 3.85 | 2.5–4 kg | fits |
| Turkey | 8.1, 9.71 / 8.44, 10.49 | 5–10 kg | fits |

* Caveat: the 2/4/8 counts do **not** correspond 1:1 to the number of difficulty levels
  (`maxDifficultyRating`), so these are checkpoints the author sampled, not a complete 9-boundary
  table. Also, weights look like *male* weights (Red Deer starts at 147.5 kg, above the female
  range), which is consistent with difficulty being reported for a trophy animal.

### 6.2 `triple_0x1C` — **SPECULATIVE**

Three ascending floats, present in every record, magnitudes in the same family as `series_0x30`
but not always consistent with it:

* Red Deer `[90.5, 182.2, 251.0]`, Wild Boar `[37.5, 98.5, 144.25]`, Grey Wolf `[32, 36, 39]`,
  Lion `[38, 44, 48.5]` — all look like (min, typical, max) **body weight in kg**.
* But Coll. Peccary carries `[37.5, 98.5, 144.2]` — byte-identical to Wild Boar / Feral Pig, and far
  too heavy for a 20 kg peccary. So this field has at least one copy-paste artefact.
* And for the ducks it is clearly *not* weight (Eurasian Wigeon `[590, 770, 905]`,
  Tufted Duck `[704, 852, 963]`, Goldeneye `[740, 1020, 1230]`, Eurasian Teal `[312, 336, 354]`) —
  those read like **grams**, or like Trophy-Rating values.
* Reading: most likely *(min, typical, max) weight* with the author mixing units/TR for small
  birds. **Do not rely on it.** Flagged SPECULATIVE.

### 6.3 Medal (bronze/silver/gold/diamond) thresholds — **NOT FOUND as a table**

I could not locate a per-species TR→medal threshold table, and I looked hard:

* All 126 records are fully mapped; the only fields with data are the ones listed in §2.3.
  Verified by scanning every record for non-zero dwords above `+0x50`: only `+0x54` is ever
  non-zero. So there is no extra 4-float medal array hiding in a record's unused space.
* `.data` after the records (RVA `0xCE0F0` onward) is all zero up to the BSS tail.
* `.rdata` has only 21 ascending-float runs of length ≥4, and 17 of them are clearly the zlib /
  ImGui constant pools around `VA 0x14009C134`. The four remaining candidates are at
  `VA 0x14008E3B8` = `[130.5, 150, 184, 210]`, `VA 0x14008E3E0` =
  `[650, 740, 845, 950, 1000, 1050, 1100, 1150]`, `VA 0x14008E4A8` = `[39.1, 43.5, 47.4, 62]`,
  `VA 0x14008E4D8` = `[8.25, 9.55, 10.8, 11.7, 12.5, 13.3, 14.1, 14.9]` — only four series for 126
  species, so these are not the medal table (they sit adjacent to the zlib tables and may be
  unrelated const data).
* The medal UI does exist: strings `221 "Diamond"`, `122 "Trophy Rating"`, `15 "TR"`,
  `18 "Max TR"`, `16 "Average TR"`, `17 "Diamond with Score"`, `50 "Difficulty Rating"`,
  `19 "Max Weight"`, `22 "Weight"`, `76 "Level Distribution"`. The tooltip code around
  `VA 0x140066C90`–`0x140066F60` formats `"##Trophy Rating (Males)"` (string `VA 0x140099980`)
  from a float array at `[entry+0x8C]` with a count at `[entry+0xCC]`, and
  `"##Trophy Rating (Females)"` (`VA 0x140099998`) from `[entry+0xD8]` / count at `[entry+0x118]`.
  Block stride is `0x4C`, so the entry keeps **16 floats per sex**, plus a count — which is a
  different (aggregated/runtime) structure than the 8-float record series.

**Best next step:** the medal thresholds are probably derived from the TR values the tool itself
prints. Dump `[entry+0x8C..]` at runtime (or the equivalent `TR` numbers from a save) and fit them
against known medal boundaries; or simply observe the tool: for one species, note the printed TR at
which it switches Bronze→Silver→Gold→Diamond and derive 3 thresholds per species empirically.

### 6.4 Other useful facts about the animal entry struct (observed, partial)

From the logging/tooltip code (`VA 0x1400587B0`–`0x140058900`, `0x140063522`):

* `[entry+0x1C]` is a `float` printed as a number (weight).
* `[entry+0x28]` is 0/1/2 and selects a FontAwesome glyph: `\uf5c0`, `\uf005`, `\uf3a5`
  (`VA 0x1400990D8`, `0x1400990DC`, `0x1400990E4`) — i.e. **gender** (male/female/unknown),
  matching `AnimalData_5.Gender`.
* `[entry+0x48]` is the difficulty rating passed to `0x140040330`.
* `[entry+0x338]` is a pointer to the species record's `stringId` (i.e. into the record itself).

---

## 7. Other recovered constants worth reusing

* Localization has **7 language blocks** in `.text` (English, German, French, Spanish, Portuguese
  and two more, plus partial reuse). English block base = `VA 0x140040497`.
* `0x1400EF3A0 + 0x167*8` = end of the runtime string table; `0x167` = 359 is hard-coded at
  `VA 0x1400400E6`.
* Fallback name string when a slot is NULL: `"<missing>"` at `VA 0x14008ED68`.
* Log prefix `"Starting scan of population file = "` (`VA 0x140099xxx`), `"Magic number mismatch"`,
  `"Error while decompressing file"`, `"This population file is empty"`,
  `"Element in illegal state after initial scan"` — useful for a clean-room reimplementation's
  diagnostics.
* The tool's live-monitoring opt-out list (from `README.txt`) is Geese, Mallards and Cinnamon Teal.

---

## 8. How a reimplementation should consume this

```python
import json
H = json.load(open("cotw/data/species_hashes.json"))
def species_name(name_hash_id: int):
    return H.get("%08X" % (name_hash_id & 0xFFFFFFFF))   # None -> "Unknown species"
```

That is the entire hash-resolution problem solved for `AnimalPopulationData_8.NameHashId`
(and it is also used for the per-group species hash inside `AnimalGroupData_5`).
`None` should render as the tool's own fallback wording
(`"Unknown species (ID:0x%x) - skipping"`).

Two independent records share the name `Caribou` (stringId 39 and 309, different weights/hashes);
key off the stringId, not the name, if you need to distinguish them. 125 distinct names for 126
records.

## 9. Summary of confidence

| finding | confidence |
|---|---|
| PE layout, section RVAs/file offsets | **VERIFIED** |
| 135-entry `{u32 hash, u64 record}` table at VA `0x1400B0C80` / file `0xAEE80` | **VERIFIED** |
| 126 species records, stride `0x3C0`, layout of `+0x00/+0x08` | **VERIFIED** |
| `hash → species name` mapping (all 135) | **VERIFIED** — corroborated because it reproduces exact real reserve rosters from 8 real save files |
| 359-entry English localization table (incl. all species names) | **VERIFIED** |
| Difficulty words Trivial…Fabled and the 1..10 switch | **VERIFIED** |
| `+0x010` = max difficulty rating | LIKELY |
| `series_0x30` = weight breakpoints in kg | LIKELY |
| `triple_0x1C` semantics | SPECULATIVE / partly inconsistent |
| `+0x014`, `+0x050`, `+0x054` semantics | UNKNOWN |
| Fur-type vocabulary (names, string ids) | **VERIFIED** |
| Fur-type → `FeatureModifiers` bit mapping | **NOT FOUND** |
| Per-species medal (TR) thresholds | **NOT FOUND** |
| `NameHashId` hash function | **NOT CRACKED** |
| save-file index → reserve name | LIKELY (8 pairs confirmed by roster match) |
