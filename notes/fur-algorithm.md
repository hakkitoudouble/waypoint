# Algorithme de fourrure de `AnimalPopulationScanner.exe` — récupéré

Cible : `AnimalPopulationScanner.exe` v1.2.15.1 (2026-06-28T14-37Z), PE x64 natif, 1 176 576 octets,
image base `0x140000000`, sha256 `11A373D11538F70DF6A653629C7583713E55F31BE084411251835A6AE7305134`
(PDB interne : `F:\Development\PopulationScanner\x64\Release\AnimalPopulationScanner.pdb`).

**Conclusion en une phrase :** la fourrure n'est pas stockée dans la sauvegarde, elle est **tirée
au sort** par le scanner à partir de `VisualVariationSeed` (u32 à `AnimalData+0x10`), avec **un seul
tour de LCG MSVC** (`x = seed*214013 + 2531011`), dont 15 bits donnent un flottant dans `[1,2)` qui
sert de variable aléatoire uniforme ; cette valeur est multipliée par le `totalWeight` d'un bloc
`(espèce, sexe)` puis comparée à une somme cumulée de poids dans une table statique de **254 blocs
× 0x1F0 octets à `VA 0x1400CF170`**. La rareté affichée est une classe à 3 niveaux déduite de
`poids / totalWeight` (seuils 0,1 % et 1 %).

Toutes les adresses ci-dessous sont données en **RVA** (à ajouter à `0x140000000` pour la VA) ;
l'offset fichier est obtenu par `file = 0x400 + (rva - 0x1000)` pour `.text` et
`file = 0x84C00 + (rva - 0x86000)` pour `.rdata`, `file = 0xAE200 + (rva - 0xB0000)` pour `.data`.

---

## 1. Où est le code, et pourquoi c'est bien là

### 1.1 La fonction de tirage

| élément | valeur |
|---|---|
| fonction | **RVA `0x568A0`** (`VA 0x1400568A0`), bornes `.pdata` `0x568A0`–`0x56B72` (722 octets) |
| appelant | **RVA `0x56D50`** (boucle sur les `AnimalData` d'un `AnimalGroupData`), `call 0x568A0` en `0x56DA3` |
| entrées | `rcx` = contexte de lecture, `rdx` = pointeur sur l'enregistrement `AnimalData` brut, `r8` = structure de sortie (0x60 octets) |

Le contexte de lecture (`[rcx+0x110]`) contient un magic word comparé à `0x84225F1C` : il sélectionne
la **taille d'enregistrement**. C'est la preuve directe que l'enregistrement est bien celui qui porte
le seed (extrait, RVA `0x56C58`–`0x56C80`) :

```asm
140056C58  B9 1C 00 00 00           mov  ecx, 0x1C                     ; pas = 0x1C (ancien format)
140056C70  B8 20 00 00 00           mov  eax, 0x20                     ; pas = 0x20 (format courant)
140056C75  41 81 BF 10 01 00 00 1C 5F 22 84   cmp dword ptr [r15+0x110], 0x84225F1C
140056C80  0F 45 C8                 cmovne ecx, eax
...
140056D62  8B D6                    mov  edx, esi                      ; edx = index de l'animal
140056D64  0F AF D1                 imul edx, ecx                      ; edx = index * pas
140056D84  41 03 D6                 add  edx, r14d                     ; + offset du tableau
140056D8E  49 03 D1                 add  rdx, r9                       ; + base du fichier  => rdx = &record
140056DA3  E8 F8 FA FF FF           call 0x1400568A0
```

### 1.2 Le seed (extrait, RVA `0x56976`)

```asm
140056976  69 C2 FD 43 03 00        imul eax, edx, 0x343FD             ; eax  = seed * 214013
14005697C  89 53 2C                 mov  dword ptr [rbx+0x2C], edx     ; entry+0x2C = seed (mémorisé)
14005697F  05 C3 9E 26 00           add  eax, 0x269EC3                 ; eax += 2531011
140056984  C1 E8 08                 shr  eax, 8
140056987  25 00 FF 7F 00           and  eax, 0x7FFF00                 ; ne garde que 15 bits de mantisse
14005698C  0D 00 00 80 3F           or   eax, 0x3F800000               ; -> float32 dans [1.0, 2.0)
140056991  89 43 30                 mov  dword ptr [rbx+0x30], eax     ; entry+0x30 = u
140056994  0F 2F 73 30              comiss xmm6, dword ptr [rbx+0x30]  ; xmm6 = 1.0f  (littéral 0x3F800000 @ .rdata 0x9C19C)
140056998  76 0C                    jbe  0x1400569A6                 ; saute le log "Got one\n"
```

`0x343FD` / `0x269EC3` sont exactement les constantes du `rand()` de la CRT MSVC. C'est le **seul**
site du binaire qui contienne des constantes de générateur pseudo-aléatoire (voir §7 : ni xorshift,
ni mulberry32, ni MT, ni LCG 64 bits).

> Remarque : la branche `Got one\n` (chaîne `.rdata` `0x98FC0`) est **inatteignable** : `u ≥ 1.0`
> par construction, donc `jbe` est toujours pris. C'est du code de débogage mort ; il ne faut pas
> s'appuyer dessus.

### 1.3 Recherche du bloc et tirage (extraits, RVA `0x569B1`–`0x56A4D`)

```asm
1400569BB  48 8B 43 08              mov  rax, qword ptr [rbx+8]        ; contexte / propriétaire
1400569BF  48 8D 0D B2 87 07 00     lea  rcx, [rip+0x787B2]             ; rcx = 0x1400CF178 = bloc[0]+8
1400569C8  4C 8B 80 38 03 00 00     mov  r8,  qword ptr [rax+0x338]     ; r8 = enregistrement d'espèce
1400569D0  4C 39 41 F8              cmp  qword ptr [rcx-8], r8          ; bloc[i].species == espèce ?
1400569D6  8B 43 10                 mov  eax, dword ptr [rbx+0x10]      ; slot (= code de sexe)
1400569D9  39 01                    cmp  dword ptr [rcx], eax           ; bloc[i].slot == slot ?
1400569DB  74 16                    je   0x1400569F3                    ; trouvé
1400569DD  FF C2                    inc  edx
1400569DF  48 81 C1 F0 01 00 00     add  rcx, 0x1F0                     ; bloc suivant (496 octets)
1400569E6  81 FA FE 00 00 00        cmp  edx, 0xFE                      ; 254 blocs
1400569EC  72 E2                    jb   0x1400569D0
```

Puis, sur le bloc trouvé (`r9 = index * 0x1F0`, et `r10 = 0` grâce à l'idiome
`lea r10,[rip-0x569FF]` en `0x569F8` qui vaut zéro, ce qui rend les adresses absolues lisibles) :

```asm
1400569F3  F3 0F 10 43 30           movss   xmm0, dword ptr [rbx+0x30]  ; u
1400569F8  4C 8D 15 01 96 FA FF     lea     r10, [rip-0x569FF]          ; r10 = 0
1400569FF  8B C2                    mov     eax, edx                    ; eax = index du bloc
140056A01  F3 0F 5C C6              subss   xmm0, xmm6                  ; u - 1.0
140056A05  4C 69 C8 F0 01 00 00     imul    r9, rax, 0x1F0              ; r9 = bloc * 496
140056A19  43 8B 84 11 7C F1 0C 00  mov     eax, dword ptr [r9+r10+0xCF17C] ; eax = totalWeight
140056A21  F3 48 0F 2A D0           cvtsi2ss xmm2, rax                 ; xmm2 = (float)totalWeight
140056A28  F3 0F 59 C2              mulss   xmm0, xmm2                  ; (u-1.0) * totalWeight
140056A2C  F3 4C 0F 2C C0           cvttss2si r8, xmm0                 ; r8 = roll = troncature
140056A31  8B 11                    mov     edx, dword ptr [rcx]        ; poids de la variante courante
140056A33  85 D2                    test    edx, edx
140056A35  0F 84 8A 00 00 00        je      0x140056AC5                 ; poids 0 => fin du bloc
140056A3B  03 FA                    add     edi, edx                    ; cumul += poids
140056A3D  44 3B C7                 cmp     r8d, edi
140056A40  72 0D                    jb      0x140056A4F                 ; roll < cumul => variante retenue
140056A42  FF C0                    inc     eax
140056A44  48 83 C1 18              add     rcx, 0x18                   ; entrée suivante (24 octets)
140056A48  83 F8 14                 cmp     eax, 0x14                   ; au plus 20 entrées
140056A4B  72 E4                    jb      0x140056A31
```

### 1.4 Classe de rareté et nom (extraits, RVA `0x56A4F`–`0x56AC1`)

```asm
140056A4F  F3 0F 10 05 D1 56 04 00  movss   xmm0, dword ptr [rip+0x456D1]  ; 0.001f  (.rdata 0x9C128)
140056A57  48 8D 0C 40              lea     rcx, [rax+rax*2]               ; rax = index de variante
140056A5B  0F 57 C9                 xorps   xmm1, xmm1
140056A5E  49 8D 14 C9              lea     rdx, [r9+rcx*8]                ; &entrée retenue
140056A62  42 8B 84 12 94 F1 0C 00  mov     eax, dword ptr [rdx+r10+0xCF194] ; eax = poids
140056A6A  F3 48 0F 2A C8           cvtsi2ss xmm1, rax
140056A6F  F3 0F 5E CA              divss   xmm1, xmm2                     ; p = poids / totalWeight
140056A73  0F 2F C1                 comiss  xmm0, xmm1                     ; 0.001 vs p
140056A76  76 09                    jbe     0x140056A81
140056A78  C7 43 48 02 00 00 00     mov     dword ptr [rbx+0x48], 2        ; p < 0.001  -> classe 2
140056A7F  EB 14                    jmp     0x140056A95
140056A81  F3 0F 10 05 A7 56 04 00  movss   xmm0, dword ptr [rip+0x456A7]  ; 0.01f   (.rdata 0x9C130)
140056A89  0F 2F C1                 comiss  xmm0, xmm1                     ; 0.01 vs p
140056A8C  76 07                    jbe     0x140056A95
140056A8E  C7 43 48 01 00 00 00     mov     dword ptr [rbx+0x48], 1        ; 0.001 <= p < 0.01 -> classe 1
140056A95  4A 63 84 12 90 F1 0C 00  movsxd  rax, dword ptr [rdx+r10+0xCF190] ; entry.stringId
140056A9D  85 C0                    test    eax, eax
140056A9F  74 18                    je      0x140056AB9                    ; id == 0 -> nom brut
140056AA1  49 8B 8C C2 A0 F3 0E 00  mov     rcx, qword ptr [r10+rax*8+0xEF3A0] ; names[stringId]
140056AA9  48 8D 05 B8 82 03 00     lea     rax, [rip+0x382B8]             ; "<missing>" (0x8ED68)
140056AB0  48 85 C9                 test    rcx, rcx
140056AB3  48 0F 45 C1              cmovne  rax, rcx
140056AB7  EB 08                    jmp     0x140056AC1
140056AB9  4A 8B 84 12 88 F1 0C 00  mov     rax, qword ptr [rdx+r10+0xCF188] ; sinon pointeur brut
140056AC1  48 89 43 50              mov     qword ptr [rbx+0x50], rax      ; entry+0x50 = nom de fourrure
```

Au tout début de la fonction, `[rbx+0x50]` reçoit `"???"` (littéral `.rdata` `0x8ED74`) : c'est la
valeur de repli quand aucune branche n'aboutit.

**Cas où le tirage est court-circuité** (RVA `0x5692D`–`0x56949`) : si le format n'est pas l'ancien,
un `u32` supplémentaire est lu en `record+0x0C` ; sa **première valeur d'octet** (testée comme
`byte <= 0`) est un drapeau « pas de variante » :

```asm
14005692D  81 79 10 1C 5F 22 84     cmp  dword ptr [rcx+0x110], 0x84225F1C
140056937  74 17                    je   0x140056950
140056939  48 8B C6                 mov  rax, rsi
14005693C  48 83 C6 04              add  rsi, 4                       ; +4 octets => le seed passe de +0x0C à +0x10
140056940  38 38                    cmp  byte ptr [rax], dil
140056943  76 0B                    jbe  0x140056950
140056945  C6 43 3C 01              mov  byte ptr [rbx+0x3C], 1
140056949  C6 81 20 01 00 00 01     mov  byte ptr [rcx+0x120], 1
...
1400569B1  80 7B 3C 00              cmp  byte ptr [rbx+0x3C], 0
1400569B5  0F 85 0A 01 00 00        jne  0x140056AC5                 ; drapeau => on garde "???"
```

Dans tous nos fichiers réels ce `u32` vaut `0`, donc la branche n'est jamais prise.

---

## 2. L'algorithme exact

```c
// entrées : species = pointeur de l'enregistrement d'espèce de l'animal
//           gender  = AnimalData.Gender (1 ou 2)
//           seed    = AnimalData.VisualVariationSeed (u32)

// (a) le caller mappe le code de sexe : 0->0, 1->1, 2->2, autre->3   (RVA 0x568EA..0x56916)
slot = (gender <= 2) ? gender : 3;

// (b) recherche linéaire du bloc (254 blocs, pas 0x1F0)              (RVA 0x569D0..0x569EC)
for (i = 0; i < 254; i++)
    if (blocks[i].species == species && blocks[i].slot == slot) { block = blocks[i]; break; }
if (!found) return;                       // nom = "???" et sortie

// (c) une seule étape de LCG MSVC, puis 15 bits de mantisse           (RVA 0x56976..0x56991)
x = (seed * 214013u + 2531011u) & 0xFFFFFFFFu;          // 0x343FD, 0x269EC3
m = (x >> 16) & 0x7FFF;                                 // 0 <= m <= 32767
u = 1.0f + m / 32768.0f;                                // float32, toujours dans [1,2)

// (d) tirage uniforme entier                                         (RVA 0x56A19..0x56A2C)
roll = (uint32_t)truncf((u - 1.0f) * (float)block.totalWeight);

// (e) marche sur les poids                                            (RVA 0x56A31..0x56A4D)
cum = 0;
for (j = 0; j < 20; j++) {
    FurEntry *e = &block.entries[j];
    if (e->weight == 0) return;                         // fin du bloc, nom = "???"
    cum += e->weight;
    if (roll < cum) { chosen = e; goto found; }
}
return;                                                 // nom = "???"

found:
// (f) rareté                                                         (RVA 0x56A4F..0x56A93)
p = (float)chosen->weight / (float)block.totalWeight;
entry->rarity = (p < 0.001f) ? 2 : (p < 0.01f) ? 1 : 0; // 0 est la valeur pré-positionnée

// (g) nom affiché                                                    (RVA 0x56A95..0x56AC1)
entry->furName = chosen->stringId ? names[chosen->stringId] : chosen->name;
```

Forme purement entière, **équivalente en pratique** (vérifié : 0 divergence sur 13 350 animaux
réels ; le `roll` ne diffère que d'au plus 1, sur 0,1 % à 0,6 % des seeds selon le `totalWeight` —
`work/fur_precision.py`) :

```
roll = (m * totalWeight) >> 15
```

Précision : `m` n'a que **15 bits**, donc `roll` ne peut prendre que 32 768 valeurs distinctes.
Pour un `totalWeight` de 299 100 (Mountain Goat), le pas du peigne vaut ≈ 9,1 : la probabilité
réalisée d'une variante est un multiple de 1/32768, ce qui peut s'écarter de `poids/total` de
quelques pour cent en relatif sur les variantes très rares (les poids restent la bonne mesure en
espérance).

### Ce que l'algorithme n'est **pas** (écarté par le code)

* pas `seed % totalWeight`, ni `(seed >> 8) % totalWeight` : le code fait un tour de LCG puis une
  conversion en flottant, il n'y a aucun `div`/`idiv` dans la fonction ;
* pas un PRNG réamorcé (`srand`/`mt19937`) : aucune constante de générateur ailleurs, et un seul
  tour est appliqué ;
* pas une lecture d'un champ « fourrure » de la sauvegarde : la fourrure n'existe pas dans le
  fichier (voir §5), et la seule entrée est le seed ;
* pas `FeatureModifiers` (masque de bits) : le tirage n'utilise que `(espèce, sexe, seed)`.

---

## 3. Comment le seed est obtenu (offset exact, vérifié)

`VisualVariationSeed` est un `u32` dans l'enregistrement `AnimalData_5` :

| format | taille d'enregistrement | offset du seed |
|---|---|---|
| ADF v4 / format courant (magic `[ctx+0x110] != 0x84225F1C`) | **0x20** | **`+0x10`** |
| ancien format (magic `== 0x84225F1C`) | 0x1C | `+0x0C` |

Déroulé du pointeur dans la fonction (RVA `0x568B4`–`0x56976`) : `rsi = record+0` → `+4` après le
`u32` d'état, puis `+8` après deux `float32`, puis `+4` pour le champ supplémentaire du format
courant ⇒ `rsi = record+0x10`, et le seed est lu là.

**Vérification directe sur une sauvegarde réelle** (`animal_population_9`, 2 079 animaux) :
`work/fur_reclayout.py` retrouve chaque seed dans le payload décompressé et vérifie les 4 champs
autour :

```
gender=1 weight=50.9050 score=60.8791 seed=0x2D32A942 | dwords@rec = 0x1 0x424B9EAF 0x42738434 0x0 0x2D32A942 0x0 0x0 0x0
records où +0x00 gender / +0x04 weight / +0x08 score concordent : 2079/2079
```

Autrement dit, la disposition est :

```
struct AnimalData_5 {        // 0x20 octets
  u32   Gender;              // +0x00  1 = mâle, 2 = femelle (jamais 0 ni 3 dans nos fichiers)
  float Weight;              // +0x04
  float Score;               // +0x08
  u32   field_0x0C;          // +0x0C  toujours 0 ; sauf si l'octet bas est > 0 => pas de tirage
  u32   VisualVariationSeed; // +0x10  <-- l'entrée du tirage
  u32   field_0x14;          // +0x14
  u32   field_0x18;          // +0x18
  u32   field_0x1C;          // +0x1C
};
```

`Gender` est bien le `slot` de la table : 1 = mâle, 2 = femelle, confirmé statistiquement sur les
sauvegardes (`work/fur_resolve.py`, sauvegarde 9) — les animaux `gender=1` sont les plus lourds et
les seuls à porter un score de trophée, p. ex. Mule Deer : `g1` 153,3 kg / score 184 vs `g2`
90,4 kg / score 0 ; RM Elk `g1` 380,6 kg / 308 vs `g2` 223,4 kg / 0.

---

## 4. La table de poids (où elle vit, comment elle est faite)

| élément | valeur |
|---|---|
| tableau | **RVA `0xCF170`** (`VA 0x1400CF170`, offset fichier `0xCD370`), section `.data` |
| blocs | **254** (constante `0xFE` comparée en `0x569E6`), pas **`0x1F0`** = 496 octets |
| fin | `0xCF170 + 254*0x1F0` = `0xEE030` |
| entrées | **1 665** au total (20 emplacements max par bloc) |

```c
struct FurBlock {                 // 0x1F0 octets
    const SpeciesRecord *species; // +0x00  adresse absolue 64 bits
    uint32_t slot;                // +0x08  1 = mâle, 2 = femelle
    uint32_t totalWeight;         // +0x0C  == somme exacte des poids du bloc
    FurEntry entries[20];         // +0x10
};

struct FurEntry {                 // 0x18 octets
    uint32_t bitIndex;            // +0x00  ordinal de la variante dans l'espèce (non utilisé par le tirage)
    uint32_t pad;                 // +0x04  toujours 0
    const char *name;             // +0x08  littéral .rdata (nom « asset », non rembourré)
    uint32_t stringId;            // +0x10  index dans la table de localisation (0xEF3A0, 359 entrées)
    uint32_t weight;              // +0x14  0 => fin du bloc
};
```

`(0x1F0 - 0x10) / 0x18 = 20` emplacements, ce que confirme le `cmp eax, 0x14` du code.
`species` pointe sur un enregistrement `{i32 stringId; u32 pad; char* icon; ...}` (l'icône
`data/Icons/*.png` sert d'ancrage de contrôle).

**Intégrité :** `work/fur_export.py` vérifie que, pour les 254 blocs, la somme des poids égale
exactement `totalWeight` — **254/254**, 0 anomalie, 1 665 entrées.

### 4.1 Les quatre espèces demandées

Les poids sont ceux du binaire ; `p = poids / totalWeight` ; la classe est celle calculée par le
scanner (`very_rare` < 0,1 %, `rare` < 1 %, sinon `common`).

**Black Bear** — bloc mâle `VA 0x1400DF8F0` (fichier `0xDDAF0`), `total = 74 926` ;
bloc femelle `VA 0x1400DFAE0` (fichier `0xDDCE0`), `total = 74 926`.

| bitIndex | variante | stringId | poids (M) | p (M) | classe | poids (F) | p (F) |
|---|---|---|---|---|---|---|---|
| 0 | Blonde | 153 | 38 | 0,0507 % | very_rare | 38 | 0,0507 % |
| 1/5 | Black | 158 | 24 900 | 33,233 % | common | 24 900 | 33,233 % |
| 2 | Brown | 155 | 38 | 0,0507 % | very_rare | 38 | 0,0507 % |
| 3/4 | Dusky | 185 | 24 900 | 33,233 % | common | 24 900 | 33,233 % |
| 6/7 | Dark | 190 | 24 900 | 33,233 % | common | 24 900 | 33,233 % |
| 8 | Cinnamon | 182 | 150 | 0,2002 % | rare | 150 | 0,2002 % |

**Whitetail Deer** — mâle `VA 0x1400D7CF0` (`0xD5EF0`), femelle `VA 0x1400D7EE0` (`0xD60E0`),
`total = 75 226` pour les deux.

| bitIndex | variante | stringId | poids (M) | p (M) | classe | poids (F) | p (F) |
|---|---|---|---|---|---|---|---|
| 0 | Piebald | 139 | 150 | 0,1994 % | rare | 150 | 0,1994 % |
| 2 / – | Tan | 294 | 25 000 | 33,233 % | common | – | – |
| 3 / 1 | Brown | 155 | 25 000 | 33,233 % | common | 25 000 | 33,233 % |
| 4 | Melanistic | 143 | 38 | 0,0505 % | very_rare | 38 | 0,0505 % |
| 6 | Albino | 138 | 38 | 0,0505 % | very_rare | 38 | 0,0505 % |
| 7 / 5 | Dark Brown | 152 | 25 000 | 33,233 % | common | 25 000 | 33,233 % |
| – / 8 | Redbrown | 186 | – | – | – | 25 000 | 33,233 % |

**Red Deer** — mâle `VA 0x1400D9FD0` (`0xD81D0`), femelle `VA 0x1400DA1C0` (`0xD83C0`),
`total = 50 151`.

| bitIndex | variante | stringId | poids (M) | p (M) | classe | poids (F) | p (F) |
|---|---|---|---|---|---|---|---|
| 0 et 3 | Piebald | 139 | 100 + 100 | 0,1994 % ×2 | rare | 100 + 100 | 0,1994 % ×2 |
| 2 | Albino | 138 | 25 | 0,0498 % | very_rare | 25 | 0,0498 % |
| 4 / 11 | Light Brown | 157 | 16 617 | 33,134 % | common | 16 617 | 33,134 % |
| 5 | Leucistic | 147 | 25 | 0,0498 % | very_rare | 25 | 0,0498 % |
| 6 | Erythristic | 310 | 25 | 0,0498 % | very_rare | 25 | 0,0498 % |
| 7 / 1 | Dark Brown | 152 | 16 617 | 33,134 % | common | 16 617 | 33,134 % |
| 8 | Melanistic | 143 | 25 | 0,0498 % | very_rare | 25 | 0,0498 % |
| 9 / 10 | Brown | 155 | 16 617 | 33,134 % | common | 16 617 | 33,134 % |

(Deux entrées « Piebald » distinctes de poids 100 chacune : la table « lisible » de l'auteur les
additionne et affiche 0,40 %.)

**Mule Deer** — mâle `VA 0x1400ECA30` (`0xEAC30`), femelle `VA 0x1400ECC20` (`0xEAE20`),
`total = 100 150`, listes **identiques** pour les deux sexes :

| bitIndex | variante | stringId | poids | p | classe |
|---|---|---|---|---|---|
| 0 | Melanistic | 143 | 25 | 0,0250 % | very_rare |
| 1 | Mosaic | 324 | 25 | 0,0250 % | very_rare |
| 2 | Grey | 183 | 25 000 | 24,963 % | common |
| 3 | Leucistic | 147 | 25 | 0,0250 % | very_rare |
| 4 | Albino | 138 | 25 | 0,0250 % | very_rare |
| 5 | Brown | 155 | 37 350 | 37,294 % | common |
| 6 | Dilute | 188 | 200 | 0,1997 % | rare |
| 7 et 11 | Piebald | 139 | 50 + 50 | 0,0499 % ×2 | very_rare |
| 8 | Blonde | 153 | 37 350 | 37,294 % | common |
| 9 | Erythr. Isabel. | 353 | 25 | 0,0250 % | very_rare |
| 10 | Erythr. Red | 331 | 25 | 0,0250 % | very_rare |

**Les 254 blocs (127 couples espèce × sexe, dont un bloc factice `???` d'id 0) sont dumpés
intégralement** dans `work/fur_draw_model.json` (clé `draw_blocks`) et dans
`work/scanner_fur_tables.json` (clés `draw_blocks` / `blocks` / `species`). Chaque entrée porte son
`bitIndex`, son `stringId`, son littéral, son poids, sa probabilité, sa classe et son offset fichier.

Particularités relevées : certaines espèces ont des variantes **homonymes** (Red Deer ×2 Piebald,
Am. Alligator ×5 Piebald, Javan Rusa ×2 Piebald, Mule Deer ×2 Piebald) et certains blocs
mâle/femelle ont des **totaux différents** (H Duck 99 800 / 112 288 ; Feral Pig 100 000 / 25 200),
donc les probabilités d'une même variante diffèrent selon le sexe.

---

## 5. La classification de rareté

* `entry+0x48` (dword) reçoit `2` si `p < 0.001`, `1` si `0.001 <= p < 0.01`, et reste à `0` sinon
  (`0` est écrit par l'appelant avant l'appel).
* Le binaire ne contient que deux libellés de groupe : **`Rare Fur Types`** (ids de localisation
  **219** et **137**) et **`Very Rare Fur Types`** (**id 220**). Le panneau correspondant est dessiné
  par la fonction `RVA 0x6A9C0` : titre `Fur Rarity Groups` (`lea rcx,[rip+0x2E6E2]` en `0x6B52F`,
  littéral `.rdata 0x99C18`), puis boucle sur `speciesRecord+0x310` (voir §6).
* **Lecture retenue (LIKELY) :** classe 2 = « Very Rare », classe 1 = « Rare », classe 0 = commun.
  C'est cohérent avec la pratique communautaire (Albino/Melanistic à 0,05 % = très rare,
  Piebald à 0,2 % = rare) et avec les deux seuls libellés existants. Le code, lui, ne prouve que
  les **nombres** 1 et 2 et leurs seuils : l'association 1↔« Rare » n'est pas écrite noir sur blanc
  dans le binaire.

La table étant triée par poids décroissant dans la plupart des blocs, l'ordre du parcours n'est pas
un ordre de rareté : ce qui compte est la position du `roll` dans la somme cumulée.

---

## 6. La table « lisible » à `speciesRecord+0x310` (et sa concordance)

Chaque enregistrement d'espèce porte, à **`+0x310`**, un second tableau, purement documentaire :
jusqu'à 10 entrées de 0x10 octets `{u32 stringId; u32 pad; char* pct}` terminées par `stringId == 0`,
rempli par un initialiseur statique par espèce (fonctions entre RVA `0x11A0` et `0xFAA9`, qui
contiennent chacune des `lea` vers les littéraux `0.01%`…`1.00%`, `.rdata 0x9A32C`–`0x9B5E4`).
C'est ce que le panneau « Fur Rarity Groups » imprime : `names[stringId]` + le texte du pourcentage
(boucle en `RVA 0x6B670` : test de fin `cmp dword ptr [r14-8],0` en `0x6B670`, entrée courante
`lea r14,[rbx+0x318]` + `add r14, i*0x10` en `0x6B65C`, résolution du nom en `0x6B70A`–`0x6B71D`).

Exemple, Euro Rabbit (`VA 0x1400B08C0`), extrait par `work/fur_readable.py` :
`Light Grey 0.10 % / Melanistic 0.10 % / Leucistic 0.05 % / Albino 0.05 %`.
La table de poids du même animal donne 100/100000, 100/100000, 50/100000, 50/100000 — **identique**.

**Concordance globale : 336 des 362 entrées** de la table lisible coïncident à ±0,02 point avec
`somme(poids) / somme(totalWeight)` (les deux sexes cumulés). Les 26 écarts se répartissent en :

* **8 artefacts de nommage** : le lisible distingue `Piebald1`/`Piebald2` là où la table de poids
  n'a que `Piebald` (Roe Deer, American Mink ×2, Pine Marten ×2, RM Elk ×2) et Mule Deer
  `Erythristic` là où les poids disent `Erythr. Isabel.`/`Erythr. Red` ;
* **2 entrées du bloc factice `???`** (id d'espèce 0), sans espèce réelle en face ;
* **16 vraies divergences de saisie** : Fallow Deer Piebald 0,20 vs 0,25 ; Sika Deer Albino
  0,20 vs 0,10 et Spotted Red 0,10 vs 0,20 ; RM Elk Albino 0,03 vs 0,10 ; Reindeer Leucistic et
  Piebald 0,16 vs 0,10 ; Turkey Leucistic 0,16 vs 0,20 ; Caribou Piebald 0,10 vs 0,16 ;
  Greylag Goose Leucistic 0,05 vs 0,09 ; Muntjac Leucistic 0,07 vs 0,13 ; Desert Bighorn
  Leucistic 0,17 vs 0,12 ; Gemsbok `Brown` 0,10 vs absent de la table de poids ; Nilgai Piebald
  0,10 vs 0,20 ; Iberian Mouflon Grey 0,20 vs 0,24.

Conclusion : la table `+0x310` est un **résumé rédigé à la main**, pas la source du tirage ; la
source est la table de poids de `0xCF170`. Cette comparaison reste une validation croisée forte,
puisque les deux tableaux ont été produits par deux chemins de code totalement différents.

---

## 7. Vérifications effectuées

1. **Intégrité structurelle** — 254 blocs, 1 665 entrées, `somme(poids) == totalWeight` pour
   **254/254** (`work/fur_export.py`). Le compte 1 665 est retrouvé indépendamment par l'analyse
   concurrente de la table (`notes/fur-tables.md`).
2. **Uniformité du tirage** — pour 200 000 seeds par bloc, les fréquences empiriques des variantes
   collent à `poids/total` à moins de 3 % de bruit d'échantillonnage (`work/fur_verify.py`).
3. **Marges sur données réelles** — `animal_population_0/3/9/14` (13 350 animaux dont l'espèce et le
   sexe ont un bloc) :

   | classe | observé | attendu (somme des p) |
   |---|---|---|
   | common | 13 313 | 13 308,8 |
   | rare | 24 | 26,7 |
   | very_rare | 13 | 14,5 |

   *Limite honnête* : cette statistique ne dépend pas du mapping choisi (n'importe quel tirage
   uniforme donnerait les mêmes marges). Elle valide les tables et les seuils de rareté, **pas** la
   formule `seed → roll`, qui n'est établie que par le désassemblage.
4. **Exemples concrets** (`work/fur_resolve.py`, implémentation de référence) : New England,
   4 420 animaux ⇒ 4 408 communs, 9 rares, 3 très rares, p. ex. Whitetail Deer mâle
   seed `0x…` → *Melanistic* (très rare), Raccoon femelle → *Piebald-Blnd*, Bobcat mâle → *Blue*.
5. **Seed/offset** — voir §3, 2 079/2 079 enregistrements conformes.
6. **Recherche d'autres générateurs** (`work/fur_rng.py`) : balayage de `.text` pour `0x41C64E6D`,
   `0x5DEECE66D`, `0x6C078965`, `0x8088405`, `0x19660D`, `0x5BD1E995`, `0x9E3779B9`, `0x85EBCA6B`,
   `0xC2B2AE35`, `0x27D4EB2F`, `0x1000193`… ⇒ **une seule** famille trouvée, le LCG MSVC, chaque
   constante n'apparaissant qu'une fois dans tout `.text` (`0x343FD` en RVA `0x56978`, `0x269EC3`
   en `0x56980`). Aucun xorshift, aucune constante de hachage de fourrure.
   Par ailleurs la fonction de tirage ne contient **aucun `div`/`idiv`**.
7. **`imul r64, r64, 0x1F0` / `cmp edx, 0xFE`** : uniques, donc un seul consommateur de la table.

---

## 8. Ce qui reste incertain (et ce qui a été écarté)

**Prouvé par le code** : l'existence et l'emplacement des deux tables ; les offsets `+0x10` (seed),
`+0x08` (slot), `+0x0C` (totalWeight), `+0x00/0x08/0x10/0x14` des entrées ; la formule
`roll = trunc(((seed*214013+2531011)>>16 & 0x7FFF)/32768 * totalWeight)` ; la marche cumulée et sa
borne de 20 ; les seuils de rareté 0,001 / 0,01 ; l'écriture du nom en `entry+0x50` avec repli
`"???"`.

**Inféré, non écrit explicitement dans le binaire** :

* la correspondance **1 = « Rare », 2 = « Very Rare »** (§5) ;
* le fait que `entry+0x48` soit bien le champ *affiché* comme rareté : le champ est écrit par la
  fonction de tirage et vaut par défaut 0, mais je n'ai pas trouvé le site d'affichage qui le
  consomme (l'UI passe par une structure recopiée dont je n'ai pas reconstruit tous les offsets) ;
* la raison de la présence du magic `0x84225F1C` (absent de nos fichiers de population et des
  en-têtes `SAVE`) : il sélectionne un format d'enregistrement plus ancien, mais je ne sais pas de
  quel jeu/version il provient.

**Non résolu** :

* l'ordre exact des entrées dans chaque bloc suit un `bitIndex` interne à l'espèce (0…18) qui
  ressemble à un ordinal d'énumération `FurType` du jeu ; je n'ai pas la table `bitIndex → nom`
  officielle, seulement l'ordre et les noms du scanner. Cela n'a **aucun** effet sur le tirage,
  qui n'utilise que l'ordre de stockage et les poids ;
* l'attribution bloc → espèce passe par un pointeur vers un enregistrement dont le `+0x338` vaut 0
  dans le fichier (écrit au runtime) ; l'identité de l'espèce a donc été établie par le `stringId`
  et l'icône de l'enregistrement, ce qui est cohérent sur 254/254 blocs mais reste une lecture
  indirecte ;
* les 21 espèces qui ont un bloc de poids mais **aucune** entrée dans la table lisible `+0x310`
  (leur initialiseur est plus court) : rien n'indique une différence de tirage, seulement un
  affichage absent.

**Pistes écartées, pour éviter de les refaire** : chercher un masque de bits (`FeatureModifiers`)
ou un hash de nom de fourrure dans la sauvegarde — la fourrure n'y est pas ; chercher une table
`(uint32 hash, char* nom)` — il n'y en a pas ; chercher des pointeurs 64 bits statiques vers les
noms de fourrures — il n'y en a pas non plus hors de la table `0xCF170` (dont les 1 919 pointeurs
sont couverts par `.reloc`).

---

## 9. Reproduire

```powershell
$py = 'C:\Users\Maelo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py work\fur_export.py        # -> work/fur_draw_model.json   (254 blocs, 1 665 entrées)
& $py work\fur_verify.py        # intégrité + uniformité + exemple travaillé
& $py work\fur_readable.py      # -> work/fur_readable_tables.json (table +0x310)
& $py work\fur_reclayout.py "…\animal_population_9"   # vérifie l'offset du seed sur un vrai fichier
& $py work\fur_resolve.py       # implémentation de référence + démo sur une sauvegarde
& $py work\fur_precision.py     # float32 vs arithmétique entière
& $py work\fur_merge_json.py    # fusionne le tout dans work/scanner_fur_tables.json
```

Scripts d'exploration utilisés (tous sous `work\`, préfixe `fur_`) : `fur_disasm.py` (désassembleur
annoté générique, xrefs RIP-relatifs robustes), `fur_field.py` (accès à un offset de structure),
`fur_pctxref.py` (xrefs vers les littéraux de pourcentage), `fur_strings.py` / `fur_range.py`
(inventaire des chaînes), `fur_table.py`, `fur_globals2.py`, `fur_enmap.py`.

## 10. Fichiers produits

| fichier | contenu |
|---|---|
| `notes/fur-algorithm.md` | ce rapport |
| `work/fur_draw_model.json` | **extraction de référence** : algorithme + 254 blocs + 1 665 entrées (nom, stringId, bitIndex, poids, p, classe, offset) |
| `work/scanner_fur_tables.json` | dump partagé : blocs, `species`, plus les clés `algorithm`, `draw_blocks`, `curated_0x310`, `verification` |
| `work/fur_readable_tables.json` | la table lisible `speciesRecord+0x310` (106 espèces) |
| `work/fur_resolve.py` | implémentation de référence `fur_for(species, gender, seed) → (nom, rareté)` |
