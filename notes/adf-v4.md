# Avalanche ADF version 4 — binary grammar

Reverse engineered from `AnimalPopulationScanner.exe` (Animal Population Scanner
41, 1.2.15.1, PE32+ x64, MSVC release, image base `0x140000000`, `.text` RVA
`0x1000` size `0x84750`) and validated against the 68 ADF documents in
`Documents/Avalanche Studios/COTW/Saves/76561199084637132`.

Parser: [`cotw/adf.py`](../cotw/adf.py). Verification:
[`tools/verify_adf.py`](../tools/verify_adf.py) (10 checks, exit 0 on success).

> **Status: cracked.** Every one of the 68 documents parses end to end with no
> heuristics: the definition region tiles with *zero* residue, the name pool
> consumes its region exactly, and every value tree matches the game's layout
> (including the 65536-byte hunting pressure map and 4004 animals in
> `animal_population_16`).

---

## 1. Container pipeline

```
file[0x00]  "SAVE"
file[0x08]  u32 = length of the decompressed payload      (asserted)
file[0x10]  "COMP"
file[0x20]  raw zlib stream -> payload
payload[0:5] = 01 01 00 00 00                            (opaque wrapper)
payload[5:]  = the ADF document
```

Every offset stored inside the ADF document is relative to `payload + 5`, i.e.
`file_position_in_payload = 5 + adf_offset`.

**Binary evidence**

| VA | instruction | meaning |
| --- | --- | --- |
| `0x14005B6CF`/`0x14005B6E7` | `mov r8d, 4` … `call memcmp` on `buf+0` vs `"SAVE"` | container magic |
| `0x14005B710`/`0x14005B72E` | `lea rcx, [r13+0x10]`, `mov r8d, 4`, `memcmp` vs `"COMP"` | block tag at 0x10 |
| `0x14009 9228` / `0x140099244` (`.rdata`) | `"SAVE"`, `"COMP"` literals | the compared strings |
| `0x14005B831` | `lea r12, [r13+5]` | **ADF base = payload + 5** |
| `0x14005A4D9`, `0x14005AD82` | `lea rbx, [rdi+5]` | same +5 base in the two sibling readers |

## 2. Header (64 bytes)

| off | type | field | notes |
| --- | --- | --- | --- |
| 0x00 | u32 | magic | `0x41444620` = `'ADF '` |
| 0x04 | u32 | version | `4` |
| 0x08 | u32 | unknown | always `1` |
| 0x0C | u32 | `instances_offset` | start of the instance table |
| 0x10 | u32 | **`definition_count`** | number of 40-byte Definition records |
| 0x14 | u32 | `definitions_offset` | start of the definition table |
| 0x18 | u32 | 0 | |
| 0x1C | u32 | 0 | |
| 0x20 | u32 | **`name_count`** | name pool slots *including* the dummy slot 0 |
| 0x24 | u32 | `names_offset` | start of the name pool |
| 0x28 | u32 | `total_size` | `== len(document)` |
| 0x2C | u32 | 0 | |
| 0x30 | u32 | 1 | |
| 0x34 | 12 B | 0 | |
| 0x40 | | descriptive ASCII string, NUL terminated, e.g. `"savegamedata_spec_imm.adf in THP "` | |

> The earlier working note called 0x10 the *instance* count. It is not: the
> u32 at 0x10 equals the number of records in the definition table for all 68
> documents, while the instance table is always exactly 24 bytes.

**Binary evidence**

* Magic compare: `0x14005B85B` `cmp ecx, 0x41444620` (the same immediate also at
  `0x14005A507` and `0x14005ADB0`); the raw little-endian bytes `20 46 44 41`
  occur only at those three sites in `.text`.
* The header fields are read by `0x140055FB0`, a fully inlined 13 × u32 reader:
  it is called with `rcx = r12+4` and `rdx = rdi+8`, and copies
  `file[0x04..0x37]` into parser-struct offsets `+0x08 .. +0x38`. Therefore
  struct offset `X` holds file offset `X - 4`. The front-end confirms it:
  `0x14005B898` `mov r8d,[rdi+8]` / `0x14005B89C` `mov [rdi],r8d` copies the
  version to struct offset 0.
* Direct uses in the front-end (`0x14005B85D`…):
  * `0x14005B89F` `mov edx,[rdi+0x10]` → file `0x0C` → `add rdx, r12` → the
    instance table. **Confirms 0x0C.**
  * `0x14005B946` `mov edx,[rdi+0x24]` → file `0x20` → loop count of the name
    pool. **Confirms 0x20 is the name count.**
  * `0x14005B949`/`0x14005B960` `mov ebx,[rdi+0x28]` → file `0x24` → name pool
    offset. **Confirms 0x24.**
* There is **no** version check: a scan of all 73 instructions of the form
  `cmp …, 4` in `.text` finds none adjacent to the version load, and the parser
  struct never reads `+8` again after the copy. The scanner trusts the magic
  alone.
* `[rdi+0x14]` (file 0x10) and `[rdi+0x18]` (file 0x14) are **never read** in
  the `0x14005xxxx` ADF code — this binary does not walk the definition table,
  it uses hardcoded layouts per root type. See §5.

## 3. Instance table

The table is the byte gap between `instances_offset` and `definitions_offset`.
In every document produced by the game the gap is exactly 24 bytes, i.e. a
single instance: the root object.

```
+0  u32 name_hash   always 0x00D7146E ("savegamedata")
+4  u32 type_hash   -> Definition.type_hash of the root object
+8  u32 offset      root object offset, relative to the ADF base
+12 u32 size        root object size in bytes
+16 u32 0
+20 u32 0
```

The root offset follows the descriptive string but is **not** derivable from it
(98 → 100 in `achievements_adf`, 98 → 104 in `settings_adf`); always read it
from this table. Observed values: 96, 100, 104.

**Binary evidence**: `0x14005B898`…`0x14005B932` reads exactly four dwords from
`base + header[0x0C]` into struct `+0x10C .. +0x118`; `0x140056ED0` iterates the
table with `add r12, 0x18` (`0x14005713B`), i.e. a 24-byte stride.

## 4. Name pool

```
names_offset                       name_count × u8      name lengths
names_offset + name_count          name_count × char[]  NUL terminated strings
```

`name_count` is header[0x20]. Slot 0 is a **dummy**: its length byte is `1` and
its single character is the `'0'` that precedes the first real name, so

```
name_id 0 = unnamed
name_id 1 = first real name
```

and the pool for `achievements_adf` decodes as
`["0", "AchievementsManagerData_1", "AlreadyConverted", "DistanceTravelled"]`
(`names_offset` 240, `name_count` 4, region 240..307).

Names are stored in *first use* order and are deduplicated: `AnimalGroupData_5`
has fields `SpawnAreadId, NeedZonePathGuids, Animals, Id`, and `AnimalData_5`
reuses the ids of `Gender/Weight/Score` when `AnimalRepopulateData_1` re-declares
the same field names. That is why 46 schema nodes share only 42 names in
`animal_population_16`.

**Binary evidence**

* `0x14005B946` `mov edx,[rdi+0x24]` (count) and `0x14005B949`
  `mov ebx,[rdi+0x28]` (names offset) followed by `0x14005B94C` `add ebx, edx`
  and `0x14005B94E` `add rbx, r12` → **the strings start at
  `base + names_offset + name_count`**.
* Loop body `0x14005B960`…`0x14005BA38`: `length = *(u8*)(base+names_offset+i)`
  (`0x14005B968`), `strlen(cursor)` (`0x14005B990`),
  `cursor += length + 1` (`0x14005BA28`–`0x14005BA30`),
  `i < count` (`0x14005BA35`). This is order-and-count-exact, no markers.

## 5. Definition table

`definition_count` records of 40 bytes, each followed by `field_count` field
records of 32 bytes.

### Definition (40 bytes)

| off | type | field | notes |
| --- | --- | --- | --- |
| 0 | u32 | `type` | 1 Structure, 2 Pointer, 3 Array, 4 InlineArray, 5 Native, 7 DefaultedNative |
| 4 | u32 | `size` | byte size of one instance of the type |
| 8 | u32 | `unknown08` | 1 / 4 / 8 … — never needed when reading |
| 12 | u32 | `type_hash` | |
| 16 | u32 | `name_id` | pool index; 0 = unnamed |
| 20 | u32 | 0 | |
| 24 | u32 | `flags` | `0x8000 | {0,1,2,3}` (type 7 also sets bit 16) |
| 28 | u32 | `element_type_hash` | Array / InlineArray / Pointer only, else 0 |
| 32 | u32 | `unknown58` | InlineArray: element count; DefaultedNative: default value |
| 36 | u32 | `field_count` | Structure: number of field records. Pointer: 16. Others: 0 |

### Field ("DefinitionValue", 32 bytes)

| off | type | field | notes |
| --- | --- | --- | --- |
| 0 | u32 | `name_id` | pool index; 0 = unnamed |
| 4 | u32 | 0 | |
| 8 | u32 | `type_hash` | |
| 12 | u32 | `size` | advisory for structure/array/pointer types — use the target Definition |
| 16 | u32 | `offset` | byte offset inside the parent Structure |
| 20 | u32 | 0 | |
| 24 | u32 | `default_raw` | auxiliary; 0 except for 57 fields across the corpus |
| 28 | u32 | 0 | |

This is Gibbed's ADF v1 `Definition`/`DefinitionValue` with the inline
`name[64]`/`name[32]` arrays replaced by a `u32 name_id` + `u32 pad`, and names
moved to the shared pool — which is exactly the compact shape the v1 reference
implies.

### How the field layout was pinned down

The scanner never walks this table (§2), so the layout was recovered by
constraint solving over all documents and then confirmed against the data:

1. `definition_count` (header 0x10) is known from the header.
2. The three reference regions are 104 / 144 / 1584 bytes for 1 / 2 / 14
   definitions. `40·D + 32·F` (D definitions, F field records) tiles them
   exactly: `40 + 32·2 = 104`, `40·2 + 32·2 = 144`, `40·14 + 32·32 = 1584`.
3. The word at `+36` of each 40-byte record equals the number of 32-byte records
   that follow it, for structures, and 0/16 otherwise — so it *is* a count, and
   the 1584-byte region walks from `definitions_offset` to `names_offset` with
   no residue in all 68 documents.
4. The words at `+8/+12/+16` of each 32-byte record are `type_hash, size,
   offset`: `ReserveSeed` = `(0x075E4E4F, 4, 40)`, `AtypicalsCooldownTime` =
   `(0x86D152BD, 2, 44)` — contiguous and consistent with the 48-byte parent.
5. The word at `+0` of each record is a pool index whose resolution reproduces
   the documented schema in definition order (`AnimalPopulationReserveData_9`,
   `AlreadyConverted`, `Populations`, `HuntingPressureMap`, …) with no gaps and
   no name left unused in any of the 68 documents.

### Definition types

| value | meaning | payload |
| --- | --- | --- |
| 1 | Structure | `field_count` × 32-byte field records; fields inline in the parent |
| 2 | Pointer (`uint16*`, `ADF_HashTable_…_Chain*`) | 8 bytes in the parent; runtime hash-table internals, count word at +36 is always 16 |
| 3 | Array (`A[T]`) | 16-byte slot in the parent (see §6) |
| 4 | InlineArray (`IA[T]`) | `unknown58` elements stored *at* the field offset, `size == elem_size × unknown58` |
| 5 | Native | referenced by hash only, never emitted as a Definition in these saves |
| 7 | DefaultedNative (`uint16: 1`) | like Native, `unknown58` holds the default value |

Type 4 checks out arithmetically: `IA[uint8]` size 65536 / count 65536;
`IA[uint32]` size 128 / count 32; `IA[PPSlot_1]` size 256 / count 16 with
`PPSlot_1.size == 16`.

## 6. Value layer

A Structure's fields are at `object_offset + field.offset`.

### Array and Pointer slots are 16 bytes, not 8

```
+0  u32 offset    relative to the *instance* base (not to the parent!)
+4  u32 capacity  allocation hint; skip it
+8  u32 count     number of elements      <-- the real count
+12 u32 0
```

An Array field's declared `size` is 8, but it occupies 16 bytes in the parent.
Any reader that stops after 8 bytes never sees the count; any reader that takes
the *second* dword as the count gets the capacity instead.

Array elements are contiguous, `element_definition.size` bytes each, starting at
`instance_offset + slot.offset`. InlineArray elements live at the field offset
itself.

### Proof of the count word

`animal_population_16` root at 104, size 306528 (data region 104..306632):

| field | slot | payload |
| --- | --- | --- |
| `Populations` | `(48, 16, 14, 0)` | 14 × 96 B at 152..**1496** |
| `HuntingPressureMap` | `(240992, 32, 65536, 0)` | 65536 B at 241096 = `instance_end − 65536` |
| `ReserveSeed` | `0x0CA3` = 3235 (plain u32 at 144) | |
| `AtypicalsCooldownTime` | 0 (plain u16 at 148) | |

* `152 + 14·96 = 1496`, and 1496 is **exactly** where population 0's group array
  begins (`Groups` slot `(1392, 16, 199, 0)` → `104 + 1392 = 1496`). If the count
  were the capacity (16), the population array would run to 1688 and the last two
  "populations" would be `AnimalGroupData_5` records — their `Groups` slots read
  as `(…, out-of-range)` and do not parse. **So the count is 14, not 16.**
* `241096 + 65536 = 306632 = instance_end`, and the bytes there are a smooth
  14-level grid (`mean|Δbyte| = 0.12`) — a 256 × 256 hunting pressure map. The
  `adf_fog_of_war_data_faster_*` documents independently use `IA[uint8]` with
  `size = 65536`, confirming the element count.
* `RepopulateData` = `(25248, 80, 3, 0)` → 3 × 12 B = 36 B at 25352..25388,
  immediately followed by population 1's group array at 25392.

**Binary evidence** (`0x140057700`, the per-instance dispatcher):

```
0x140057709  movzx eax, byte ptr [rdx+0xa] ...   ; u32 at root+8  -> edi (array offset)
0x140057717  movzx r9d, byte ptr [rdx+0x13] ...  ; u32 at root+0x10 -> r9d (element count)
0x140057804  mov eax, [rbp+0x110]                ; root TypeHash
0x140057818  cmp eax, 0x480c5171                 ; AnimalPopulationReserveData_9
0x14005782D  mov ebx, 0x48 / 0x38 / 0x50 / 0x60  ; per-type element stride
0x140057870  mov r8d, edi ; call 0x140056ed0
0x14005787E  add edi, ebx                        ; next element
```

The scanner reads the array offset from slot `+0`, the element count from slot
`+8`, **never touches slot `+4`**, and strides elements by a hardcoded size —
`0x60` (96) for `AnimalPopulationReserveData_9`, which equals
`AnimalPopulationData_8.size` from the definition table. That independently
confirms the 16-byte slot, the count position and the element size.

### Native value types

| hash | type | size |
| --- | --- | --- |
| `0x0CA2821D` | UInt8 | 1 |
| `0x580D0A62` | Int8 | 1 |
| `0x86D152BD` | UInt16 | 2 |
| `0xD13FCF93` | Int16 | 2 |
| `0x075E4E4F` | UInt32 | 4 |
| `0x192FE633` | Int32 | 4 |
| `0xA139E01F` | **UInt64** | 8 |
| `0x7515A207` | Float | 4 |
| `0x34B4DBF8` | String | variable |

The first eight are Gibbed's `NativeValueType` enum. `0xA139E01F` is not in that
enum; it is proven to be 64-bit by the `A[uint64]` definition in the animal
population schema, whose `element_type_hash` is exactly `0xA139E01F`, and by its
use for ids/timestamps (`IconData_1.Id`, `ReserveId`, `TrackingID`,
`TimeStamp`, `NeedZoneBaseData_3.MapIconId`) at `size == 8`.

`0x34B4DBF8` (String) never appears as a field type in any of the 68 documents,
so its encoding (`(offset, length)` pair) is implemented but unverified here.

## 7. The animal population schema

`animal_population_16`, root `AnimalPopulationReserveData_9` (hash `0x480C5171`,
size 48) at 104:

```
AnimalPopulationReserveData_9 {            AnimalData_5 (size 32) {
  +0  AlreadyConverted        u8   @0      +0  Gender               u8  @0
  +8  Populations             A[AnimalPopulationData_8]  @8    +4  Weight        f32 @4
  +24 HuntingPressureMap      A[uint8]  (65536)  @24            +8  Score         f32 @8
  +40 ReserveSeed             u32  @40                          +12 FeatureModifiers struct @12
  +44 AtypicalsCooldownTime   u16  @44                          +13 IsScripted    u8  @13
}                                                               +16 VisualVariationSeed u32 @16
AnimalPopulationData_8 (size 96) {                              +20 Id            u32 @20
  +0  NameHashId u32          <- species hash                   +24 MapPosition   Vector2 @24
  +8  Groups      A[AnimalGroupData_5]                          }
  +24 RepopulateData A[AnimalRepopulateData_1]
  +40 InitialTotalScore f32      AnimalGroupData_5 (size 48) {
  +44 InitialNumAnimals i32        +0  SpawnAreadId        i32
  +48 Revision u32                 +8  NeedZonePathGuids   A[uint32]
  +56 GroupToWarrenId A[uint64]    +24 Animals             A[AnimalData_5]
  +72 RepopulationSkipCounter u16  +40 Id                  u32
  +80 ConditionsFulfilled A[uint32] }
}
```

Result for the reference save: 14 species, 4004 animals, 65536-byte pressure map.

### `MapPosition` is a placeholder

`MapPosition` (`Vector2_1`, X@24, Y@28) and `Id` (@20) are present in the schema
and are **always zero**: across all 16 `animal_population_*` files, 28243
animals, not one has a non-zero `Id`, `MapPosition.X` or `MapPosition.Y`. The
whole 32-byte record is accounted for by the eight fields, so no hidden position
exists — the population simulation stores weights, scores, genders and variation
seeds, but not world positions. A map view cannot get coordinates from these
documents.

## 8. Loose ends, honestly

These details are recorded but not needed to read any document:

1. **`default_raw` at field `+24`.** 0 except for 57 fields across the corpus,
   where it holds a plausible runtime default: `1065353216` (= 1.0f for
   `Bond`, `Focus`, `CurrentPrimaryJobXP`), `1` (`Level`), `255`
   (`NeedZoneScheduleIndex`). For `DogProfileData_3.DogName` and
   `TraitsOwned` it holds values that look like stale ASLR pointers
   (`2563769542`, `2304290611`). Treat it as auxiliary, not semantics.
2. **Field `offset` high byte.** 5 records (`Dirty`, of type `uint16: 1`, in
   `leaderboard_adf`, `missions_missiondata_adf`,
   `achievements_progress_missiondata_adf`, `playerinformation_adf`,
   `trophy_lodges_adf`) store `0x0100001A` instead of `0x1A`. The parser masks
   the low 24 bits (`offset & 0x00FFFFFF`) and keeps `offset_raw`. Note this
   makes `Dirty` share offset 26 with `UserAllocated`, which suggests the writer
   OR-ed a flag (the type's default value is 1) into the offset word; these are
   in-memory hash-table internals, not game data, so it does not matter.
3. **Type 2 (Pointer) payloads.** `uint16*` / `…_Chain*` fields point at the
   game's runtime hash-table structures, which are serialised as-is. They are
   parsed as arrays when the target resolves cleanly and otherwise returned as
   `{"kind": "pointer", "offset": …, "count": …}`.
4. **`unknown08`** (definition `+8`) and **`unknown58`** are recorded verbatim;
   `unknown58` is understood for InlineArray (element count) and
   DefaultedNative (default value) but not for the other types.
5. **`flags`** is always `0x8000 | {0,1,2,3}`; type 7 also sets bit 16
   (`0x00018001`). Bits 0 and 1 correlate with "this type appears as an inline
   member" but nothing in the reader depends on them.

## 9. Corrections to the earlier working notes

| Earlier note | Corrected |
| --- | --- |
| header `0x10` = instance count | `0x10` = **definition** count; the instance table is the 24-byte gap to `definitions_offset` |
| header `0x20` = definitions count | `0x20` = **name pool slot count** (real names + 1 for the dummy slot 0) |
| both roots have `Offset == 104` | `achievements_adf` root is at **100**, `settings_adf` and `animal_population_16` at 104; read it from the instance table |
| `animal_population_16` has 16 populations | **14**; 16 is the slot's *capacity*, and the 15th/16th "populations" would be `AnimalGroupData_5` records |
| array field is 8 bytes `(offset, count)` | the field's declared size is 8 but it occupies a **16-byte** slot `(offset, capacity, count, 0)`; the count is the third dword |
| v1 `Definition` had `unknown50 / elementTypeHash / unknown58 / count` | confirmed, mapped to `flags / element_type_hash / unknown58 / field_count` at v4 offsets 24/28/32/36 |
| version 4 is compared in the reader | it is not; only the magic is validated |

## 10. Reproducing the analysis

Scratch scripts live in `work/adf-re/` (`common.py` loads and unwraps a save;
`w3.py` walks the definition table; `proto.py`/`tol.py` were the constraint
solver and the tolerant walker used to find the record shapes; `dis*.py` drive
Capstone over `.text`). Capstone 5.0.x is vendored at `tools/vendor`.
