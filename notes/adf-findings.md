# ADF v4 — état des connaissances

Tout ce qui suit est **vérifié sur les fichiers réels** de
`C:\Users\Maelo\Documents\Avalanche Studios\COTW\Saves\76561199084637132\`.
Ce document est la référence durable : il prime sur tout raisonnement de conversation.

## 1. Conteneur SAVE

```
0x00  u32  "SAVE"
0x04  u32  version (0x00252517, 0x0026DD26, 0x0029F8FB, 0x0032D3C2, 0x00335D13 observés)
0x08  u32  taille décompressée attendue
0x0C  u32  0
0x10  u32  "COMP"
0x14  u8   ?
0x15  u8   ?
0x16  u32  taille décompressée (répétée)
0x1A  u32  0 / 0x1E u16 0
0x20  ...  flux zlib brut
```

Implémenté et testé : `cotw/save.py`, 16/16 fichiers, `tools/verify_save.py`.

Le payload décompressé **n'est pas** le document ADF : il est préfixé par **5 octets**
(`01 01 00 00 00`) et **tous les offsets internes de l'ADF sont relatifs à cette
frontière** : `position_fichier = 5 + offset_relatif`. Vérifié : le champ `size` de
l'en-tête ADF vaut toujours `payload_len - 5`.

## 2. En-tête ADF v4 (offsets relatifs, u32 LE)

```
0x00  magic 0x41444620 ('ADF ')
0x04  version == 4
0x08  1
0x0C  instance_table_offset
0x10  instance_count
0x14  definitions_offset
0x18  0
0x1C  0
0x20  definitions_count
0x24  names_offset
0x28  total_size
0x2C  0
0x30  1
```

Les données commencent à `0x40` ; le premier objet est une chaîne ASCII
(`"savegamedata_spec_imm.adf in THP "`), longueur 33 + NUL, puis padding à 4 octets.
Le **root object** se trouve à `rel 104` dans tous les fichiers observés.

## 3. Table d'instances

`instance_count` entrées de **24 octets** à `instance_table_offset` :

```
u32 NameHash, u32 TypeHash, u32 Offset, u32 Size, u32 pad, u32 pad
```

`Offset` = position du root object ; `Size` = nombre d'octets de cet objet.
Exemples : `achievements_adf` → `TypeHash=9BE860F7 Offset=104 Size=980` ;
`animal_population_16` → `TypeHash=480C5171 Offset=104 Size=306528`.

## 4. Tableaux

Un champ tableau occupe **8 octets** dans la structure parente :
`(u32 offset, u32 count)`, et **l'offset est relatif au champ `Offset` de l'instance**,
pas à la base ADF. Preuve : le root de la population porte `48` et `16` à `+8/+12`,
et `104 + 48 = 152` = début d'un tableau de 16 éléments bien formés.

## 5. Types natifs (autoritatif, Gibbed `NativeValueType`)

```
0x0CA2821D UInt8    0x075E4E4F UInt32
0x580D0A62 Int8     0x192FE633 Int32
0x86D152BD UInt16   0x7515A207 Float
0xD13FCF93 Int16    0x34B4DBF8 String
```

`DefinitionType` : `1=Structure`, `2=Unknown2`, `3=Array`, `4=Unknown4`, `5=Native`.

## 6. Pool de noms (à `names_offset`)

Table de longueurs en `u8`, puis les noms concaténés terminés par NUL, **dans l'ordre
des définitions** : pour chaque définition, son nom de type puis les noms de ses
champs. Les types tableau ont leur propre définition (`A[int32]`, `A[uint64]`, …).

En-tête du pool = `01` puis les longueurs, puis `30 00`. Vérifié sur 3 fichiers :
`01 19 10 11 30 00` + `AchievementsManagerData_1` (25) / `AlreadyConverted` (16) /
`DistanceTravelled` (17) — `0x19,0x10,0x11` = 25,16,17.

## 7. Enregistrements de champs — PARTIELLEMENT résolu

Fait solide, vérifié sur **3 fichiers indépendants** : dans une définition de
structure, les champs occupent des emplacements de **32 octets**, et le premier
champ commence **48 octets après le début de la définition**.

Chaque emplacement porte, à ses 3 premiers mots :

```
+0  u32 typeHash   (type natif, ou hash d'une structure/tableau défini ailleurs)
+4  u32 size       (taille en octets du champ)
+8  u32 offset     (offset du champ dans la structure parente)
+12 u32 0
+16 u32 0
+20 u32 0
+24 u32 / +28 u32  → observés (3, X) ; X = taille/élément de la définition suivante
```

### Root `AnimalPopulationReserveData_9` — table vérifiée

Définition à `def_off = 306664`, `type=1`, `size=48`, `typeHash=480C5171`.

| # | rel    | typeHash   | type   | size | offset |
|---|--------|------------|--------|------|--------|
| 0 | 306712 | `0CA2821D` | UInt8  | 1    | `0x00` |
| 1 | 306744 | `D72DDE68` | Array  | 8    | `0x08` |
| 2 | 306776 | `6F962A30` | —      | 8    | `0x18` |
| 3 | 306808 | `075E4E4F` | UInt32 | 4    | `0x28` |
| 4 | 306840 | `86D152BD` | UInt16 | 2    | `0x2C` |

Les offsets se recouvrent proprement et `max(offset+size) = 0x2E ≤ 48`. Le `size`
déclaré dans l'en-tête de définition est bien la taille de la structure.

`D72DDE68` = type de `Populations` (tableau) ; sa définition de type tableau suit
immédiatement, à `306864`, avec `type=3`.

### Longueur d'une définition de structure

Mesurée sur 3 fichiers : `48 + 32*(nfields-1) + 24`, soit `72 + 32*(nfields-1)`.

- `achievements_adf` : 2 champs → 104 octets. Région = 136..240 = **104** ✔
- `settings_adf` : 2 champs → 104 octets. Puis définition tableau à 1216 ✔
- `animal_population_16` : 5 champs → 200 octets. Définition tableau à 306864 ✔

Autrement dit : **chaque champ fait 24 octets utiles, et 8 octets séparent deux champs
consécutifs** — le dernier champ n'est pas suivi de ces 8 octets.

## 8. Ce qui reste ouvert

1. **Où est stocké le nombre de champs** d'une définition. Aucun candidat clair aux
   offsets `+16..+44` de l'en-tête (les valeurs `{1,0,0x8001|0x8000,0,0,2,2,0}` sont
   identiques dans plusieurs fichiers alors que les structures diffèrent).
   Piste de repli : dériver la fin d'une définition par un *walk* validé
   (les offsets des champs doivent couvrir `[0, size)` sans trou anormal).
2. **La taille de l'en-tête pour les définitions NON-structure** (`type=3` tableau,
   `type=5` natif). Les écarts de +36/+40 observés entre définitions suggèrent un
   en-tête bien plus court que 48 pour ces types ; un en-tête de 48 pour 43
   définitions coûterait 2064 octets, alors que la région n'en fait que 1584 —
   donc l'en-tête de 48 ne vaut **que** pour les structures à champs.
3. Le rôle exact du trailer `(3, X)` entre deux champs.

## 9. Pièges déjà rencontrés (ne pas les refaire)

- **Les zones de zéros faussent toute métrique de périodicité ou de « champ
  constant ».** Un padding satisfait « périodique à 100 % » et « valeur ≤ 2 ».
  Toujours exclure les octets nuls avant de scorer.
- Les offsets ADF se lisent **relativement à la base ADF (5)** pour l'en-tête et les
  tables, mais **relativement à `instance.Offset`** pour les tableaux.
- `species[14]` tombe à `rel 1496`, qui est aussi `104 + 1392` — coïncidence qui m'a
  fait croire à tort à deux niveaux d'imbrication. Vérifier les collisions d'offsets.
