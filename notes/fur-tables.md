# Tables de fourrures dans `AnimalPopulationScanner.exe`

Cible : `AnimalPopulationScanner.exe` v1.2.15.1 (2026-06-28), PE x64 natif, 1 176 576 octets,
image base `0x140000000`.
Sortie de l'extraction : [`work/scanner_fur_tables.json`](../work/scanner_fur_tables.json).

Conclusion en une phrase : **le scanner embarque bien ses propres tables de fourrures, une par
espèce et par sexe, sous forme de tableaux de structures `{char* nom; u32 id; u32 poids}` dans
`.data` à partir de `VA 0x1400CF170`; les 254 blocs sont intégralement récupérables et leurs
probabilités reproduisent notre catalogue au dix-millième près.**

---

## 1. Disposition trouvée

### 1.1 Le tableau des blocs

| élément | valeur |
|---|---|
| début du tableau | `VA 0x1400CF170` — offset fichier `0xCD370` — RVA `0xCF170` |
| nombre de blocs | **254** (constante `0xFE` comparée dans le code, voir §2) |
| pas d'un bloc | **`0x1F0` = 496 octets** (`imul r9, rax, 0x1f0`) |
| fin du tableau | `VA 0x1400EDD90` (= `0x1400CF170 + 254*0x1F0`), immédiatement suivi d'un blob RTTI sans rapport |
| entrées au total | **1 665** |

Chaque bloc fait 496 octets et se termine par du remplissage à zéro. Il contient au maximum
20 entrées : `(0x1F0 - 0x10) / 0x18 = 20`, ce que le code confirme avec `cmp eax, 0x14`.

### 1.2 En-tête de bloc (0x10 octets)

```c
struct FurTableBlock {          // 0x1F0 octets, aligné
    const SpeciesRecord *species;   // +0x00  pointeur absolu 64 bits (VA)
    uint32_t slot;                  // +0x08  1 = mâle, 2 = femelle
    uint32_t totalWeight;           // +0x0C  somme exacte des poids du bloc
    FurEntry entries[20];           // +0x10
};
```

### 1.3 Entrée de variante (0x18 = 24 octets)

```c
struct FurEntry {               // 0x18 octets
    uint32_t bitIndex;          // +0x00  0..18, ordinal de la variante dans l'espèce
    uint32_t pad;               // +0x04  toujours 0
    const char *name;           // +0x08  pointeur absolu vers un littéral de .rdata
    uint32_t stringId;          // +0x10  id dans la table de localisation (0x1400EF3A0)
    uint32_t weight;            // +0x14  poids entier du tirage
};
```

Exemple réel, première entrée du premier bloc (Pintail, mâle) — offset fichier `0xCD380` :

```
00 00 00 00  00 00 00 00   50 B6 09 40 01 00 00 00   D3 00 00 00  D4 30 00 00
bitIndex=0   pad=0         name=0x14009B650 ("Eclipse")  id=211      poids=12500
```

et le bloc lui-même (`0xCD370`) :

```
70 D0 0B 40 01 00 00 00  01 00 00 00  E6 C3 00 00  00 00 00 00  00 00 00 00
species=0x1400BD070      slot=1       total=50150     (padding)
```

### 1.4 Forme des pointeurs

Les deux champs `char*` sont des **adresses absolues 64 bits déjà présentes dans le fichier**
(pas des RVA, pas de reconstruction RIP-relative) : `0x1400BD070`, `0x14009B650`, …
La table de relocation `.reloc` les couvre toutes. Vérification indépendante :

* relocations `IMAGE_REL_BASED_DIR64` dont la cible tombe dans `[0x1400CF170, 0x1400EDD90)` :
  **1 919**
* attendu : 254 pointeurs d'espèce + 1 665 pointeurs de nom = **1 919** ✔
* aucune entrée sans relocation, aucun pointeur d'espèce sans relocation (0 anomalie).

C'est ce qui distingue cette table des noms de réserves/cartes, qui ne sont atteints que par des
`lea` RIP-relatifs dans `.text`.

### 1.5 Les noms de fourrures

Deux jeux de littéraux coexistent dans `.rdata`, et il faut les distinguer :

1. **les libellés rembourrés** (table de localisation, ids 137…358), p. ex. `"Albino       "`,
   `"Piebald      "` à `VA 0x14008F6F0` et suivants, pas de 16 octets ;
2. **les noms « asset » non rembourrés** utilisés par nos tables, p. ex. `"Eclipse"`,
   `"Melanistic"`, `"Pseudo Melanistic"`, `"MelanistiCC"` répartis sur
   `VA 0x140090098…0x1400900C0` et `VA 0x14009B650…0x14009B77F`.

Les blocs utilisent le jeu 2 ; l'id stocké à `+0x10` renvoie au jeu 1. Le consommateur affiche
`names[stringId]` si l'id est non nul, sinon le littéral du jeu 2 (`0x140056A95` → `0x140056AC1`,
repli `"<missing>"` à `0x14008ED68`). Les deux jeux ne s'accordent pas toujours sur l'orthographe :
111 entrées sur 1 665 divergent (`Ps Melanistic` vs `Pseudo Melanistic`, `MelanistiCC` vs
`Melanistic Charc.`, `Wht Stripeless` vs `White Stripeless`, `Purplegrey` vs `Purple Grey`, …).
C'est le littéral qui est la donnée d'origine, l'id le libellé d'affichage.

### 1.6 À quoi les blocs raccrochent l'espèce

Le pointeur `+0x00` désigne un **enregistrement d'espèce** : `{i32 stringId; i32 0; char* icone;
…}`, 128 enregistrements de `0x3C0` octets dans `.data` — 1 à `VA 0x1400B08C0`, la table de
hachage `NameHashId` de 135 × 0x10 octets à `VA 0x1400B0C80`, puis 127 enregistrements à partir
de `VA 0x1400B14F0`. On lit donc l'espèce d'un bloc par `stringId` (→ table de localisation
reconstruite) et par le nom d'icône (`data/Icons/…_frame.png`).

Détail honnête : le code de consommation ne compare pas directement `bloc.species` à
l'enregistrement ; il compare à `[[entree_animal+8]+0x338]` (`0x1400569BB`–`0x1400569D0`). Ce
champ `+0x338` vaut **0 dans le fichier** (écrit au runtime). L'attribution bloc → espèce reste
certaine pour une autre raison : le pointeur du bloc désigne un enregistrement dont le `stringId`
et l'icône nomment l'espèce, et les probabilités qui en découlent reproduisent exactement les
valeurs de notre catalogue pour cette espèce (voir §5) — un hasard sur 126 espèces est exclu.

### 1.7 Juste avant le tableau

`VA 0x1400CF140` (offset `0xCD340`), soit `0x30` octets avant la première entrée, contient un
blob séparé : `{u32 = 15; u32 = 0; f32[8] = 1.0, 0.698, 0.698, 0.902, 0.502, 1.0, 0.502, 0.8}`
puis deux zéros. Il n'est **pas** référencé par le consommateur de fourrures (seuls des
aides d'écriture de logs le lisent, `0x14000FBC0`). Il ne fait pas partie du tableau : la
première entrée du tableau est bien à `0x1400CF170`, ce que confirment les quatre accès
`0xCF170 + 0x…` du code (§2) et la borne `254 × 0x1F0`.

---

## 2. Preuve par le code consommateur

Fonction `0x1400568A0` – `0x140056B60`. Le passage utile, commenté (désassemblage annoté fourni
par `tools/fur_disasm.py`) :

```asm
; --- recherche linéaire du bloc : espèce + sexe ---------------------------------
1400569BB  mov  rax, [rbx+8]            ; rax = enregistrement d'espèce de l'animal
1400569BF  lea  rcx, [rip+0x787b2]      ; rcx = 0x1400CF178 = &bloc[0].slot
1400569C8  mov  r8, [rax+0x338]
1400569D0  cmp  [rcx-8], r8             ; bloc.species == clé de l'espèce ?
1400569D4  jne  next
1400569D6  mov  eax, [rbx+0x10]         ; code 0/1/2/3 venant de la sauvegarde
1400569D9  cmp  [rcx], eax              ; bloc.slot == ce code ?
1400569DB  je   found
1400569DD  inc  edx
1400569DF  add  rcx, 0x1F0              ; pas de 496
1400569E6  cmp  edx, 0xFE               ; 254 blocs
1400569EC  jb   loop

; --- tirage uniforme puis accumulation des poids --------------------------------
1400569F3  movss xmm0, [rbx+0x30]       ; flottant [1,2) dérivé d'une graine de la sauvegarde
1400569F8  lea  r10, [rip-0x569ff]      ; r10 = 0x140000000 (base image)
140056A01  subss xmm0, xmm6             ; xmm6 = 1.0  -> u dans [0,1)
140056A05  imul r9, rax, 0x1F0          ; r9 = bloc * 496
140056A0F  lea  rcx, [r10+0xCF194]      ; = bloc + 0x24 = &entries[0].weight
140056A16  add  rcx, r9
140056A19  mov  eax, [r9+r10+0xCF17C]   ; eax = bloc.totalWeight (+0x0C)
140056A21  cvtsi2ss xmm2, rax
140056A28  mulss xmm0, xmm2
140056A2C  cvttss2si r8, xmm0           ; r8 = floor(u * totalWeight)
140056A31  mov  edx, [rcx]              ; poids de l'entrée courante
140056A3B  add  edi, edx                ; cumul
140056A3D  cmp  r8d, edi
140056A40  jb   hit                     ; cumul > tirage -> variante retenue
140056A42  inc  eax
140056A44  add  rcx, 0x18               ; pas de 24
140056A48  cmp  eax, 0x14               ; 20 entrées max
```

Puis la classification de rareté et l'affichage :

```asm
140056A4F  movss xmm0, [0x14009C128]    ; 0.001
140056A6F  divss xmm1, xmm2             ; p = poids / totalWeight
140056A73  comiss xmm0, xmm1
140056A76  jbe  +                      ; p >= 0.001 -> tester 0.01
140056A78  mov  dword [rbx+0x48], 2     ; p <  0.001  -> "very rare"
140056A81  movss xmm0, [0x14009C130]    ; 0.01
140056A8E  mov  dword [rbx+0x48], 1     ; 0.001 <= p < 0.01 -> "rare", sinon 0
140056A95  movsxd rax, [rdx+r10+0xCF190] ; stringId (+0x10)
140056AA1  mov  rcx, [r10+rax*8+0xEF3A0] ; names[stringId]
140056AB9  mov  rax, [rdx+r10+0xCF188]   ; sinon le char* (+0x08)
140056AC1  mov  [rbx+0x50], rax
```

Trois conséquences importantes :

* la probabilité est **exactement** `weight / totalWeight` du bloc, calculée en `float` ;
* la classe de rareté est celle du scanner : `p < 0.001` → `very rare`, `p < 0.01` → `rare`,
  sinon commun — nos trois niveaux `very_rare` / `rare` / `common` du catalogue ;
* `bitIndex` (+0x00) et `pad` (+0x04) ne sont **jamais lus** par ce code : le champ est une
  donnée d'auteur (l'index de variante côté jeu), pas une clé de décodage.

Le code lit aussi, juste avant, le « code 0/1/2/3 » de la sauvegarde pour le stocker en
`[animal+0x10]` (`0x1400568F8`–`0x140056913` : 1 → 1, 2 → 2, 0 → 0, autre → 3). C'est ce même
champ qui sert de `slot`. Les blocs n'existant que pour 1 et 2, les animaux au code 0 ou 3 ne
reçoivent aucune fourrure rare.

---

## 3. Méthode d'extraction

1. `tools/fur_pe.py` — lecteur PE minimal (sections, `va_to_off` / `off_to_va`, `cstring`).
2. `tools/fur_strings.py` — repérage du bloc de chaînes des fourrures et des deux jeux de
   littéraux ; première constatation : aucun pointeur vers les libellés rembourrés.
3. `tools/fur_ids.py` — reconstruction de la table de localisation (359 entrées) en émulant
   l'initialiseur statique : appariement `lea reg,[rip+littéral]` / `mov [rip+0x1400EF3A0+8i],reg`,
   suivi par registre, en gardant le premier magasin de chaque slot (bloc anglais). Résultat :
   353/359 ids ; les 6 manquants sont des libellés non ASCII (icônes FontAwesome, `Tòrr nan
   Sithean`, `Vicuña`) et n'interviennent pas ici.
4. `tools/fur_records.py` — découverte des enregistrements d'espèce par leur forme
   `{i32 stringId; i32 0; char* "data/Icons/…"}` : 128 enregistrements, pas `0x3C0`.
5. `tools/fur_xref.py` — toutes les références RIP-relatives et tous les pointeurs absolus vers
   la zone `0x1400CD000…0x1400EF500`, ce qui a révélé que la zone n'est atteinte que par
   `lea`/`mov` avec des décalages `0xCF17C`, `0xCF188`, `0xCF190`, `0xCF194` — d'où la base.
6. `tools/fur_disasm.py` — désassemblage annoté de la fonction consommatrice (bornes `0xFE`,
   `0x1F0`, `0x18`, `0x14`) : c'est la preuve du schéma ci-dessus.
7. `tools/fur_extract.py` — parcours des 254 blocs, contrôle `somme(poids) == totalWeight`,
   écriture de `work/scanner_fur_tables_raw.json`.
8. `tools/fur_compare.py` + `tools/fur_report.py` — normalisation des noms, comparaison au
   catalogue, écriture de la livraison `work/scanner_fur_tables.json`.

Contrôles de cohérence obtenus :

* `somme(poids) == totalWeight` pour **254 / 254** blocs (aucune exception) ;
* 1 919 relocations = 254 + 1 665 (§1.4) ;
* `stringId` et littéral concordent (même fourrure) sur 1 554 / 1 665 entrées, les 111 autres
  n'étant que des variantes d'orthographe listées au §1.5.

---

## 4. Sémantique des champs et ordre des variantes

### 4.1 `slot` = sexe (1 = mâle, 2 = femelle)

Preuve empirique, indépendante du code : en croisant les blocs avec les tags `genders` de notre
catalogue (qui vient d'une autre source), **les 98 variantes marquées `male` uniquement tombent
toutes dans un bloc `slot = 1`, et les 61 marquées `female` uniquement dans un bloc `slot = 2`**
— zéro contradiction. Exemples : Pintail `Eclipse`/`Grey` (mâle) vs `Brown`/`Bright` (femelle) ;
Reindeer `Dark Brown`/`Light Brown` (mâle) vs `Brown`/`Tan` (femelle) ; Ronda Ibex
`Brown Hybrid`/`Grey` (mâle) vs `Light Brown`/`Buff` (femelle).

Couverture : 126 espèces effectives = 125 × 2 blocs + `Caribou` qui possède **deux
enregistrements d'espèce distincts** (ids 39 et 309) donc 4 blocs. Sur 128 enregistrements,
un seul n'a pas de table : celui d'icône `data/Icons/Placeholder.png` (`VA 0x1400BD430`).

### 4.2 `bitIndex` = ordinal de variante par espèce

L'union des deux blocs d'une même espèce donne des indices contigus `0…N-1` pour 121 des 126
espèces ; les 5 exceptions (Jaguar, Moose, Brown Bear, Iberian Wolf, `???`) ont des trous
(par ex. Jaguar `0,1,2,3,8,9,10,12`). Un même indice porte toujours le même nom à l'intérieur
d'une espèce (les quatre-vingt-dix-huit variantes rares communes aux deux sexes partagent donc
le même `bitIndex` dans les deux blocs), mais **pas** d'une espèce à l'autre : l'indice 0 vaut
`Melanistic` pour 41 blocs, `Albino` pour 33, `Piebald` pour 20… C'est donc un ordinal
local à l'espèce, pas un enum global.

C'est cet ordre (`bitIndex` croissant, puis `slot`) qu'il faut utiliser pour interpréter un
index calculé par le scanner : l'ordre physique des entrées dans un bloc suit d'ailleurs
toujours `bitIndex` croissant (vérifié sur les 254 blocs).

### 4.3 L'enregistrement « `???` » contient les Great Ones

Le bloc 186/187 (enregistrement `VA 0x1400B14F0`, `stringId 0` = `"???"`, icône
`data/Icons/Unknown.png`, total 150) liste six noms sans équivalent localisé
(`stringId = 0`) :

```
bit 1  Crested_Blond            bit 6   Furry_Tawny
bit 3  Furry_Charred_Cinnamon   bit 10  Bald_Calico
bit 4  Crested_Brown           bit 11  Bald_Spotted
```

six variantes à `p = 25/150 = 0,166667` — c'est la vocabulaire « Great One » du scanner,
qu'aucune espèce nommée ne porte.

---

## 5. Comparaison avec `cotw/data/fur_catalogue.json`

### 5.1 Appariement

Après réduction des deux côtés en minuscules alphanumériques et une table d'alias
(`Ps Melanistic` → `pseudo_melanistic`, `MelanistiCC` → `melanisticcharcoal`, `Piebald-Blnd` →
`piebaldblonde`, `D Red Brown` → `darkredbrown`, …) :

* **1 573 / 1 665** entrées du scanner (94,5 %) retrouvent une variante de même nom ;
* **66 espèces** ont *toutes* leurs entrées appariées et un écart relatif maximal < 0,1 %
  (le plus souvent ≤ 1e-6, c'est-à-dire les mêmes poids entiers) ;
* 3 noms d'espèces du scanner n'existent pas dans le catalogue : `RM Bighorn Sheep`,
  `Ant. Jackrabbit`, `???` (le catalogue range probablement ces bêtes sous d'autres libellés).

### 5.2 Tableau comparatif (poids et probabilités lus dans le binaire vs catalogue)

`p_scanner = poids / totalWeight` du bloc indiqué. « sexe » = slot du bloc.

| espèce | variante | sexe | poids | total | p_scanner | p_catalogue | verdict |
|---|---|---|---|---|---|---|---|
| Pintail | Albino | M+F | 25 | 50150 | 0,000499 | 0,000499 | identique |
| Pintail | Piebald | M+F | 200 | 50150 | 0,003988 | 0,003988 | identique |
| Pintail | Eclipse | M | 12500 | 50150 | 0,249252 | 0,249252 | identique |
| Pintail | Grey | M | 37350 | 50150 | 0,744766 | 0,744766 | identique |
| Pintail | Brown | F | 37350 | 50150 | 0,744766 | 0,744766 | identique |
| Reindeer | Albino | M+F | 38 | 74926 | 0,000507 | 0,000507 | identique |
| Reindeer | Piebald | M+F | 75 | 74926 | 0,001001 | 0,001001 | identique |
| Reindeer | Dark Brown | M | 37350 | 74926 | 0,498492 | 0,498492 | identique |
| Reindeer | Tan | F | 37350 | 74926 | 0,498492 | 0,498492 | identique |
| Whitetail Deer | Albino | M+F | 38 | 75226 | 0,000505 | 0,000505 | identique |
| Whitetail Deer | Piebald | M+F | 150 | 75226 | 0,001994 | 0,001994 | identique |
| Whitetail Deer | Brown | M | 25000 | 75226 | 0,332332 | 0,333165 | **écart 0,25 %** |
| Whitetail Deer | Red Brown | F | 25000 | 75226 | 0,332332 | 0,332332 | identique |
| Red Deer | Albino | M+F | 25 | 50151 | 0,000498 | 0,000498 | identique |
| Red Deer | Piebald (×2 bits) | M+F | 100 | 50151 | 0,001994 | 0,001994 | identique |
| Red Deer | Light Brown | M | 16617 | 50151 | 0,331339 | 0,331339 | identique |
| Moose | Albino | M | 33 | 50150 | 0,000658 | 0,000659 | écart 0,15 % |
| Moose | Tan | M | 16617 | 50150 | 0,331346 | 0,332008 | écart 0,20 % |
| Moose | Tan | F | 16617 | 50050 | 0,332008 | 0,332008 | identique (= femelle) |
| Roe Deer | Albino | M | 38 | 75114 | 0,000506 | 0,000507 | écart 0,20 % |
| Roe Deer | Albino | F | 38 | 74964 | 0,000507 | 0,000507 | identique (= femelle) |
| Greylag Goose | Leucistic (×5 bits) | M+F | 17 | 100000 | 0,000170 | 0,000170 | identique |
| Greylag Goose | Hybrid | M+F | 17 | 100000 | 0,000170 | 0,000170 | identique |
| Greylag Goose | Brown | M+F | 74898 | 100000 | 0,748980 | 0,748980 | identique |
| Blackbuck | Beige | M | 6647 | 66767 | 0,099555 | 0,578375 | **×5,8 (catalogue = femelle)** |
| Blackbuck | Beige | F | 33234 | 57461 | 0,578375 | 0,578375 | identique (= femelle) |
| Blackbuck | Brown | M | 23928 | 66767 | 0,358381 | 0,416422 | écart (catalogue = femelle) |
| Blackbuck | Dark Brown | M | 35893 | 66767 | 0,537586 | 0,537586 | identique (mâle seul) |

### 5.3 Divergences, énoncées clairement

1. **Le catalogue n'est pas une probabilité « par animal ».** Le scanner gère deux tables par
   espèce (mâle / femelle) et **41 des 125 espèces** ont des totaux de poids différents entre
   les deux sexes ; pour ces espèces, **136 variantes communes ont deux probabilités
   distinctes** (aucune n'est égale). Le catalogue n'en stocke qu'une seule : sur les 132 cas
   vérifiables, 37 fois la valeur mâle, 95 fois la valeur femelle, jamais une moyenne.
   Conséquence pratique : une probabilité du catalogue doit être lue comme la probabilité
   *d'un sexe donné*, et l'écart peut être important — Blackbuck `Beige` vaut 9,96 % chez le
   mâle et 57,84 % chez la femelle (le catalogue retient 57,84 %).
2. **Écarts résiduels de valeur** pour quelques espèces : Whitetail Deer `Brown`/`Tan`/
   `Dark Brown` 0,332332 (scanner) vs 0,333165 (catalogue), soit 0,25 % — les poids entiers
   sont les mêmes (25000) mais le dénominateur diffère (75226 vs ≈75041). Même phénomène chez
   Moose et Roe Deer. Chez Feral Goat le nom `White Brown` porte 0,186752 au bit 1 **et**
   0,083331 au bit 4, alors que le catalogue range 0,083331 sous `white_brown` et 0,186752 sous
   `dark_brown` : signature d'une table plus ancienne où ces deux bits portaient d'autres noms.
   Le catalogue ne provient donc pas exactement de cette build.
3. **Granularité des noms.** Le scanner répète parfois le même nom à plusieurs `bitIndex`
   (Greylag Goose : cinq `Leucistic`, Red Deer : deux `Piebald`, Feral Goat : deux
   `White Brown`) ; le catalogue déplie ces répétitions en `_2`, `_3`, … (`leucistic` …
   `leucistic_5`), ce qui rend l'appariement par nom partiel mais cohérent.
4. **Great Ones.** Le catalogue contient des entrées `great_one_*` (probabilités 1,0 ou 1/6)
   que les tables n'expriment pas ; côté binaire elles n'apparaissent que comme les six noms
   sans libellé du §4.3. Inversement, six noms du scanner (`Crested_Blond`, `Furry_Tawny`, …)
   sont absents du catalogue.
5. **Ce qui concorde sans réserve** : toutes les variantes rares (albino, melanistic,
   leucistic, piebald, erythristic, etc.) portent exactement les mêmes poids dans les deux
   sources, et la classification de rareté du scanner (0,001 / 0,01) coïncide exactement avec
   les étiquettes `very_rare`/`rare`/`common` du catalogue pour **1 419 des 1 573 entrées
   appariées** ; 24 de plus concordent si l'on rapproche `super_rare` du catalogue de
   `very_rare` du scanner. Les 130 désaccords restants portent sur des variantes situées à
   moins de 1 % d'un seuil (le catalogue les classe `very_rare` là où le scanner dit `rare`,
   ou l'inverse), jamais sur les poids.

---

## 6. Limites de l'extraction

* Tout ce qui est dans le fichier a été lu : 254 blocs, 1 665 entrées, aucune zone « devinée ».
  Aucun bloc n'est partiellement récupérable.
* `bitIndex` est une donnée d'auteur que le code ne consomme pas : son sens exact (index dans
  l'enum de variantes du jeu) est une hypothèse raisonnable, pas une preuve ; ce qui est
  certain, c'est qu'il ordonne les entrées et qu'il est propre à chaque espèce.
* Le lien `bloc → espèce` passe en exécution par `[enregistrement+0x338]`, champ nul dans le
  fichier (écrit au runtime). Nous identifions l'espèce par le `stringId`/l'icône de
  l'enregistrement pointé, ce qui est cohérent sur les 126 espèces et confirmé par les
  probabilités.
* Les six ids de localisation non récupérés (132, 133, 134, 166, 326, 339) n'apparaissent dans
  aucune entrée de fourrure.

---

## 7. Reproduire

```bat
cd C:\Users\Maelo\Documents\mods\cotw-pop
set PY=C:\Users\Maelo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe
%PY% tools\fur_extract.py     REM work\scanner_fur_tables_raw.json
%PY% tools\fur_report.py      REM work\scanner_fur_tables.json + work\scanner_fur_compare.json
%PY% tools\fur_disasm.py 0x1400568A0 0x140056B60
```

Fichiers créés (aucun fichier existant de `cotw\`, `web\` ou `tools\` n'a été modifié) :

| fichier | rôle |
|---|---|
| `tools/fur_pe.py` | lecteur PE, conversions VA ↔ offset |
| `tools/fur_strings.py` | inventaire des littéraux de fourrures |
| `tools/fur_ids.py` | reconstruction de la table de localisation par émulation de l'init |
| `tools/fur_records.py` | découverte des 128 enregistrements d'espèce |
| `tools/fur_xref.py` | références vers la zone `.data` des tables |
| `tools/fur_disasm.py` | désassemblage annoté |
| `tools/fur_extract.py` | extraction des 254 blocs |
| `tools/fur_compare.py` | normalisation des noms + comparaison |
| `tools/fur_report.py` | livraison JSON + statistiques |
| `work/scanner_fur_tables.json` | livraison (§ forme demandée) |
| `work/scanner_fur_tables_raw.json` | dump brut, un objet par bloc |
| `work/scanner_fur_compare.json` | une ligne par entrée appariée |
