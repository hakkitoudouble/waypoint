# La fourrure est-elle lisible dans une entité vivante ?

Investigation en **lecture seule** sur `theHunterCotW_F.exe` (pid 15292, même session que
`notes/live-scan.md` et `notes/animalradar.md`), le 30 octobre 2026 vers 18 h 30–18 h 50.

## Verdict court

**Non — une entité vivante n'expose pas la fourrure**, ni sous forme de hash résolu, ni sous
forme d'index, ni sous la forme du `VisualVariationSeed` de la population, dans tout ce qui
est atteignable autour d'elle.

Ce n'est pas une intuition : les trois représentations possibles ont été cherchées
explicitement, et les seuls champs « à faible cardinalité » de l'entité se sont révélés
**dynamiques** (ils changent en moins d'une minute), ce qu'une fourrure ne fait jamais.

Ce qui reste ouvert : la fourrure est peut-être dérivable **ailleurs** (côté population, à
partir du seed), ce qui est un problème différent — voir §10.4. Les notes `notes/fur-algorithm.md`
et `notes/fur-tables.md`, écrites en parallèle de celle-ci, établissent que la fourrure est
une **fonction déterministe du `VisualVariationSeed`** de la sauvegarde ; si c'est exact,
cela *explique* le résultat négatif ci-dessous : l'entité n'a aucune raison de stocker la
fourrure, et de fait elle ne stocke même pas le seed.

---

## 1. Corpus validé : 45 entités vivantes

Le cache `work/radar_entities.json` contient 77 adresses. Le filtre d'origine était
permissif (`|x| < 30000`, `y ∈ [-2000, 4000]`), ce qui laisse passer des triples de floats
dénormaux. Revalidation stricte (`work/furentity_step3_strict.py`) :

| catégorie | nombre | critère |
|---|---|---|
| entités valides | **45** | hash d'espèce résolu **et** `500 < |x|,|z| < 25 000` **et** `800 < y < 2500` |
| emplacements recyclés | 13 | le u32 à l'adresse n'est plus un hash d'espèce connu (0, `FFFFFFFE`, `00000054`…) |
| faux positifs du filtre large | 19 | hash valide mais « position » dénormale (`0, −0.00, 0.00`) |

Répartition : Turkey 18, Desert Bighorn Sheep 9, Mule Deer 8, Puma 4, Black Bear 3,
RM Elk 3.

Détail utile pour la suite : **les 45 entités sont à `region_base + 0x550`**, dans des
allocations de 0,6 à 16 Mio. La position reste à `hash − 580` (= `region_base + 0x30C`)
pour les 45, ce qui confirme l'offset établi.

> Attention : ces grosses allocations contiennent aussi d'autres choses, notamment les
> **tableaux de population** de la réserve (enregistrements de 32 octets). C'est ce qui
> explique que des seeds apparaissent « près » d'une entité à 100–800 Kio (§6) : ce ne sont
> pas les champs de l'entité.

## 2. Anatomie de l'enregistrement, vue par différentiel

Dump brut d'une entité (Mule Deer `0x2A811954550`, position `(-8052.78, 1985.99, -12496.92)`),
offsets **relatifs au hash d'espèce** :

```
 -640  10721C41 8BA9414B 00000000 A7F2FC52   CONSTANT pour tous les animaux, toutes espèces
 -608  B4C7EB18 00007FF6 00000001 00000000   {pointeur module, 1} — constant lui aussi
 -592  B4C7EB00 00007FF6 006A2DA4 C5FBA642   {pointeur module constant, u32 variable}, puis X
 -580  C5FBA642 44F83FAD C64343B2            X, Y (altitude), Z            <-- position
 -568  3D55E47B BE0EABA7 3BF08862 3F7D24B5   quaternion (x, y, z, w)
 -552  11DCBA20 000002A8                     pointeur tas (propre à l'individu)
 -544  00000001                              petit entier stable (1 ou 2)
 -464  B4C7EB30 00007FF6 00000020 00000000   {pointeur module, 0x20} — constant
 -448  01C1135E 1E02F600 3E135AE3 A9544FA2   famille d'identifiants DYNAMIQUES (§4)
 -336  11025700 000002A8 11025880 000002A8   pointeurs tas
 -192  00000001                              drapeau qui bat
 -144  118BA400 000002A8 1CFD7D20 000002A8   pointeurs vers un composant (§7)
 -112  42F00000 000007D0                    120.0f, 2000 — constant
    0  B0113E10                             hash d'espèce
  +64  00000000 00000000 B4C7DC70 00007FF6   {pointeur module, 0x40}
 +264  00000001                             petit entier stable, dépend de l'espèce
```

## 3. Différentiel Mule Deer (8 individus) — tableau principal

`work/furentity_report.py`, colonne = individu. « — » = identique pour les 8.

| offset | #1 `2A7F4C0C550` | #2 `2A811954550` | #3 `2A811D21550` | #4 `2A819B7D550` | #5 `2A81CDED550` | #6 `2A8216F0550` | #7 `2A822111550` | #8 `2A823073550` | interprétation |
|---|---|---|---|---|---|---|---|---|---|
| −640 (x4) | — | — | — | — | — | — | — | — | flottants partagés (état/animation d'espèce) |
| −608 | — | — | — | — | — | — | — | — | `{ptr module, 1}` partagé |
| −584 | 002316B1 | 006A2DA4 | 006A2DDD | 006A2D85 | 006A2DDD | 006A2D85 | 006A2DC1 | 006A2DC1 | inconnu ; partition **différente** de −448, donc variable distincte |
| −580/−576/−572 | −8053.4 / 1984.5 / −12459.3 | … | … | … | … | … | … | … | **position** (unique par individu) |
| −568…−553 | ✱ | ✱ | ✱ | ✱ | ✱ | ✱ | ✱ | ✱ | quaternion d'orientation |
| −552 | ✱ | ✱ | ✱ | ✱ | ✱ | ✱ | ✱ | ✱ | pointeur tas |
| −544 | 1 | 1 | 2 | 1 | 2 | 2 | 2 | 1 | inconnu, stable |
| −452 | 0 | 0 | 0 | 0 | 0 | 3 | C64B960A | FDF9A627 | inconnu, dynamique |
| **−448** | EFB1D1A7 | **01C1135E** | **1F716A7B** | **01C1135E** | **1F716A7B** | **1F716A7B** | 0253CEFC | **01C1135E** | **état dynamique** (§4) |
| −444 | 1E02F600 | 1E02F600 | 4E5774CE | 1E02F600 | 4E5774CE | 4E5774CE | 4E5774CE | 1E02F600 | idem |
| −440 | 3E135A00 | 3E135AE3 | 298C399C | 3E135AE3 | 298C399C | 298C399C | 46E328A3 | 3E135AE3 | idem |
| −436 | A9544FA2 | A9544FA2 | A9544FA2 | A9544FA2 | A9544FA2 | A9544FA2 | A9544FA2 | A9544FA2 | **constante** pour ces 8 |
| −432 | 01C1135E | 0 | 0 | 01C1135E | 01C1135E | 01C1135E | 01C1135E | 01C1135E | inconnu, **stable** (2 valeurs seulement) |
| −644 | D6309A00 | D6309A59 | 0E554F38 | D6309A59 | 0E554F38 | 0E554F38 | 0E554F38 | D6309A59 | idem famille (§4), dynamique |
| −192 | 0 | 1 | 0 | 1 | 0 | 1 | 1 | 1 | drapeau |
| +264 | 1 | 1 | 5 | 1 | 5 | 5 | 44F4F605 | 007F7F01 | inconnu |

✱ = valeur unique par individu (transformée ou pointeur).

Contrôle inter-espèces (3 Black Bears, `work/furentity_report.py`) :

| offset | Black Bear #1 `2A816424550` | #2 `2A8164C9550` | #3 `2A81696F550` | interprétation |
|---|---|---|---|---|
| −448 | 1F716A7B | 1F716A7B | 1F716A7B | idem famille |
| −444 | 4E5774CE | 4E5774CE | 4E5774CE | |
| −440 | 298C399C | 298C399C | 298C399C | |
| −436 | A9544FA2 | A9544FA2 | A9544FA2 | |

**Les 16 octets `1F716A7B 4E5774CE 298C399C A9544FA2` sont rigoureusement identiques chez
3 Ours noirs et 3 Mule Deer** (et les deux premiers dwords se retrouvent aussi chez
*Puma*). Une fourrure est un asset *par espèce* : elle ne peut pas être le même identifiant
chez deux espèces. C'est l'argument le plus direct contre l'hypothèse « ce champ est la
fourrure ».

## 4. Le seul champ « hash » variable est un état, pas une apparence

Trois preuves indépendantes.

**(a) Il change en quelques dizaines de secondes** (`work/furentity_stability.py`, même
adresses, même processus) :

| offset | changés après 38 s | changés après ~12 min |
|---|---|---|
| −448 | 11 / 45 | **19 / 45** |
| −644 | 4 / 45 | **9 / 45** |
| −440 | 2 / 45 | 2 / 45 |
| −444 | 1 / 45 | 0 / 45 |
| +264 | 1 / 45 | 6 / 45 |
| −452 | 0 / 45 | 0 / 45 |
| −600 | 0 / 45 | 0 / 45 |
| −436 | 0 / 45 | 0 / 45 |
| −432 | 0 / 45 | 0 / 45 |
| −192 (drapeau) | 39 / 45 | 37 / 45 |
| −184 (drapeau) | 15 / 45 | 16 / 45 |

Les valeurs ne font pas que changer : elles **permutent entre les mêmes quelques valeurs**
(`01C1135E`, `282A03D4`, `7AD711B8`, `A5A2CF5B`, `D6309A59`, `E557C856`…). C'est la
signature d'une énumération d'état (comportement / animation / pose), pas d'un attribut
d'apparence fixé au spawn.

**(b) Le partage inter-espèces** (§3) est incompatible avec une fourrure.

**(c) Les valeurs sont corrélées à l'espèce par paires inattendues** : `4EF76890` à −444
pour *Turkey* et *Desert Bighorn Sheep* (oiseau + ovidé), `4E5774CE`/`1E02F600` pour
*Black Bear*, *Puma*, *Mule Deer*, *RM Elk*. Rien de tel qu'une variante de fourrure.

Deux valeurs de la même famille varient d'un seul octet bas (`3E135AE3` vs `3E135A00`,
`D6309A59` vs `D6309A00`), ce qui suggère un champ voisin d'un octet (drapeau) plutôt qu'un
hash pur — cohérent avec un état.

## 5. Recherche des hashes de fourrure **connus** (scan global, 7 433 Mio en 63 s)

Les seuls hashes de variante authentiques dont on dispose viennent du journal de chasse
(`work/furentity_harvest_variations.py` — 20 prises, 6 valeurs distinctes) :

| hash | libellé connu | occurrences dans tout le processus | distance à l'entité la plus proche |
|---|---|---|---|
| `E6A4B966` | Ours noir / Noire (black) | 246 | 338 336 o |
| `7573495B` | Ours noir / Sombre (dark) | 106 | 340 176 o |
| `5EF18CE1` | Ours noir / Foncé (dusky) | 186 | 151 816 o |
| `61A8C4C8` | Renard roux A | 197 | 9 568 o |
| `A7A53749` | Javan Rusa A | 387 | 151 848 o |
| `420438EB` | Renard roux B | 83 | 151 808 o |

**Dans les fenêtres de ±12 Kio autour des 45 entités : zéro occurrence**
(`work/furentity_report.py`). Le minimum global (9 568 o) tombe dans une des tables de hash
décrites ci-dessous — pas dans une entité — et concerne le Renard roux à côté d'une dinde.

Où vivent ces hashes : dans des **tables `{u32 hash, u32 valeur}` au pas de 8 octets**
(1 205 occurrences réparties sur 168 pages de 64 Kio), par exemple à `0x2A75B511040` :

```
61A8C4C8 00000026  6BA8E3F6 00000009
7000D53F 00000005  7573495B 00000003
A7A53749 00000055  AEC8B66F 00000004
E6A4B966 00000028  E7010476 0000007F
420438EB 00000003  5EF18CE1 0000000C
```

Ce sont des **compteurs par hash** (le schéma de sauvegarde contient
`ValueOccurance { Ints, Bools, HashString }` et `ADF_HashTable_uint32_ValueOccurance`).
La nature exacte du petit entier n'est **pas** établie ici (probablement un compteur de
statistiques : les trois ours y valent 40 / 12 / 3 alors que le journal de chasse en
recense 8 / 3 / 5). Ce qui est établi : **ces tables ne sont pas des tables
hash → index de variante**, et **aucune entité ne pointe dessus ni ne les contient**.

## 6. Recherche du `VisualVariationSeed` (scan global des 2 079 seeds de la réserve 9)

`work/furentity_seed_scan2.py` — 17 671 occurrences trouvées (7 443 Mio lus en 177 s) :

* **0 occurrence à moins de 1 024 octets d'un hash d'espèce d'entité** ;
* 60 occurrences dans ±64 Kio, dont **59 sont des seeds rangés dans un tableau de
  population adjacent** (pas de 32 octets — ex. `−1536, −1504, −1472, −1440…` pour
  `0x2A7F4C0C550`) et 1 est le hash de Renard roux cité plus haut ;
* aucun décalage ne se reproduit d'une entité à l'autre : il n'existe **pas** de champ
  « seed » à offset fixe dans l'entité.

Recherche locale complémentaire (`work/furentity_local_seeds.py`, ±64 Kio, 45 entités) :
aucun **poids** ni **score** de la population n'apparaît hors de ces mêmes tableaux
adjacents. Autrement dit l'entité ne porte ni seed, ni poids, ni identifiant de population —
on ne peut donc même pas relier une entité à son enregistrement de population.

## 7. Hypothèses testées et écartées

| hypothèse | test | résultat |
|---|---|---|
| (a) hash de variante résolu | 6 hashes connus, scan global | **absent** (rien à moins de 9,5 Kio, aucun dans les fenêtres) |
| (b) index u8/u32 de variante | différentiel octet par octet et mot par mot, 6 espèces | **aucun champ stable** : soit booléens qui battent, soit la famille dynamique §4 |
| (c) seed u32 | scan global des 2 079 seeds | **absent** |
| (c′) seed ré-encodé | u32 inversé, xor/ajout avec le hash d'espèce, rotation 16, complément, moitié basse/haute d'un u64, double, float32, moitiés u16 (`work/furentity_encodings.py`) | seulement des coïncidences attendues (les hits u16 et double sont des collisions de sous-chaînes, pas des champs) |
| pointeur vers un asset d'apparence partagé | slots 8 octets, regroupement par cible, ±8 Kio (`work/furentity_ptrs.py`) | **aucun slot pointant vers une même cible heap pour un sous-groupe d'animaux** |
| index dans un sous-objet | différentiel par indirection sur tous les pointeurs de l'entité (`work/furentity_indirect.py`) | rien de réel : les seuls hits sont des **octets internes** de u32 plus grands (l'objet derrière `hash−144` contient des ids `0x0120…0x0671`, pas des indices de variante) |

## 8. Ce qui existe, ce qui n'existe pas

**Existe dans l'entité** (par individu) : position, orientation (quaternion), pointeurs vers
des composants, une famille d'identifiants d'état dynamiques, quelques drapeaux, le hash
d'espèce, et des descripteurs `{pointeur module, u32}` (dont un u32 à `−584`, variable par
individu mais selon une partition **différente** de celle de `−448`).

**N'existe pas dans l'entité** : seed d'apparence, poids, score, identifiant de population,
hash de variante, index de variante, pointeur vers un asset d'apparence partagé.

## 9. Verdict détaillé

* **(a) hash de variante résolu — NON.** Aucune des 6 valeurs authentiques n'apparaît à
  moins de 9,5 Kio d'une entité, et jamais dans les 45 fenêtres.
* **(b) petit index de variante — NON, avec réserve.** Aucun champ stable à faible
  cardinalité n'existe dans l'entité. La réserve est qu'un index pourrait être stocké dans
  un sous-objet atteint par une chaîne de pointeurs plus longue que celle explorée ici
  (on a suivi un seul niveau, sur tous les pointeurs de la fenêtre).
* **(c) seed sous une autre forme — NON.** Pas en u32 ; pas à offset fixe ; pas sous les
  encodages testés ; pas dans les 64 Kio autour, sauf tableaux de population adjacents.
* **(d) rien du tout — c'est la conclusion la plus probable** pour tout ce qui est
  directement lisible dans l'entité ou à un niveau de pointeur.

Fiabilité : les parties « aucun hash de fourrure » et « aucun seed » sont des **balayages
exhaustifs** de la mémoire du processus, pas des échantillonnages : elles sont solides. La
partie « pas d'index » est un différentiel sur 45 individus de 6 espèces. Elle ne pourrait
pas démontrer l'absence d'un champ, seulement l'absence de *champ qui varie* dans cet
échantillon ; or les variantes rares (≈0,1 %) n'y figurent probablement pas. C'est le test
de **stabilité temporelle** qui tranche : les quelques champs à faible cardinalité observés
changent en moins d'une minute, ce qui exclut une apparence. Un champ d'apparence, lui,
serait stable — et c'est précisément ce qu'on ne trouve pas.

## 10. Ce qu'il faudrait pour confirmer (ou renverser) le verdict

1. **Vérité terrain sur une variante rare** — le test décisif et le moins coûteux : que le
   joueur repère en jeu un animal à fourrure rare (albinos, mélanique, pie), se place à
   côté, et nous laisse lire son entité. On compare sa fenêtre à celle de 3 congénères de
   même espèce, et on ne retient que les offsets **stables dans le temps** (contrôle déjà
   outillé : `work/furentity_stability.py`). C'est la seule façon de distinguer un champ
   constant d'apparence d'un champ d'état.
2. **Suivre plus d'un niveau de pointeur** — élargir `work/furentity_indirect.py` à 2–3
   niveaux, en se limitant aux pointeurs stables dans le temps.
3. **Scan global du seed sous forme de double** — la variante globale (et non locale) de
   l'encodage `double` : 2 079 clés seulement, donc une passe d'une minute.
4. **Voie alternative, hors entité** : la fourrure n'est pas dans l'entité mais dérivable du
   `VisualVariationSeed` de la population, puisque l'outil chinois affiche la fourrure
   d'animaux vivants sans lire autre chose que la sauvegarde. Cette voie a été documentée
   **pendant cette session, en parallèle** de la nôtre : `notes/fur-algorithm.md` (tirage LCG
   sur le seed, table statique de 254 blocs à `VA 0x1400CF170`) et `notes/fur-tables.md`
   (les tables elles-mêmes, importées dans `cotw/data/fur_tables.json`).
   Si cette règle est bonne, elle rend la question de l'entité **sans objet** — et nos deux
   résultats négatifs (ni seed, ni fourrure dans l'entité) deviennent une explication
   cohérente : le jeu recalcule la variante à partir du seed de la population, il ne la
   stocke pas sur l'acteur.
5. **Recoupement utile** : la formule seed → variante devrait reproduire les 6
   `VariationName` observés dans le journal de chasse. C'est le contrôle qui validerait
   d'un coup cette note et `notes/fur-algorithm.md`.

   Les `VariationIndex` des trophées (`trophy_lodges_adf`, 28 trophées, indices 0 à 19,
   `work/furentity_trophy_index.py`) prouvent par ailleurs que la représentation canonique
   côté *jeu* est un petit entier — mais on n'en a trouvé aucune trace dans l'entité, ce qui
   est cohérent avec un recalcul à la volée.

## 11. Reproductibilité (scripts, tous dans `work/`, préfixe `furentity_`)

| script | rôle |
|---|---|
| `furentity_mem.py` | accès lecture seule (`OpenProcess`/`ReadProcessMemory`), chargement du cache |
| `furentity_step1_layout.py`, `furentity_step3_strict.py` | validation / revalidation des entités |
| `furentity_snapshot.py` | fige 45 fenêtres de ±12 Kio → `work/furentity_windows.json` (analyse hors-ligne) |
| `furentity_report.py` | tableaux différentiels, recherche des hashes connus |
| `furentity_candidates.py`, `furentity_byteindex.py` | classement des champs « à faible cardinalité » (mots puis octets) |
| `furentity_stability.py` | test de stabilité temporelle des candidats |
| `furentity_encodings.py`, `furentity_local_seeds.py` | encodages du seed, poids, recherche locale |
| `furentity_seed_scan2.py` | scan global des 2 079 seeds de la réserve |
| `furentity_furhash_scan.py` | scan global des 6 hashes de variante connus |
| `furentity_vartable.py`, `furentity_harvest_variations.py` | tables `{hash, compteur}` et vocabulaire des variantes |
| `furentity_ptrs.py`, `furentity_indirect.py` | pointeurs partagés, différentiel par indirection |
| `furentity_trophy_index.py` | `VariationIndex` des trophées |

Aucune écriture dans le processus : uniquement `PROCESS_VM_READ` + `ReadProcessMemory`.
