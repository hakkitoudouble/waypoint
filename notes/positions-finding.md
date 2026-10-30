# Où sont les positions ? — conclusion vérifiée

## Ce qui NE marche pas : les positions par animal

`AnimalData_5` déclare bien un champ `MapPosition: Vector2 {X, Y}`, mais dans les
sauvegardes réelles **il vaut toujours `(0.000, 0.000)`**.

Preuve : sur `animal_population_16` (Emerald Coast), enregistrements réels à
`rel 11080` :

```
[ 0] g=2 w= 28.914 s=  0.000 seed=A9460D3B  pos=(0.0, 0.0)
[ 1] g=2 w= 31.790 s=  0.000 seed=A0899C9E  pos=(0.0, 0.0)
[ 2] g=1 w= 45.983 s= 89.071 seed=D4AD04C0  pos=(0.0, 0.0)
[ 6] g=2 w= 28.514 s=  0.000 seed=AC1EDA77  pos=(0.0, 0.0)
...
```

22 enregistrements valides sur 24 ont `pos=(0,0)`. Les 2 valeurs non nulles
appartiennent à des emplacements de bruit (`g=149`, `g=244`, poids absurdes).

Recoupement indépendant : un scan global par signature (genre plausible + poids
plausible + position finie et **non nulle**) ne trouve que 70 candidats épars sur
308 905 octets, sans périodicité — c'est du bruit, pas un tableau.

**Conclusion : les positions des animaux ne sont pas persistées.** Elles
n'existent qu'en mémoire du jeu, pendant la partie. Un overlay « où est chaque
animal en direct » exige donc de lire la mémoire du processus, pas le fichier.

## Correction importante : les animaux font 64 octets, pas 32

La définition `AnimalData_5` déclare `size=32`, mais les enregistrements réels
sont **espacés de 64 octets** (`11080, 11144, 11208, 11272…`). Les slots
intermédiaires (décalage +32) sont du bruit. Champs observés à ces offsets :

```
+0x00 u8  Gender          (observé : 0, 1, 2 — pas seulement 0/1)
+0x04 f32 Weight          (28.9, 31.8, 45.9, 44.3 kg … crédibles)
+0x08 f32 Score           (89.07, 75.23 …)
+0x10 u32 VisualVariationSeed
+0x18 f32 MapPosition.X   (toujours 0)
+0x1C f32 MapPosition.Y   (toujours 0)
```

Le `size=32` de la définition est donc l'empreinte « utile » et non le pas réel
du tableau. À reprendre.

## Ce qui marche : les need zones

`found_need_zones_adf` parse proprement avec le parser ADF v4. Schéma :

```
NeedZoneSave_3              { AlreadyConverted, NZData: A[NeedZoneReserveData_3] }
NeedZoneReserveData_3       { ReserveId: u64, NeedZoneData: A[NeedZoneBaseData_3] }
NeedZoneBaseData_3 (64 o)   { Position: Vector3, NeedZoneId: i32, NeedType: i32,
                              MapIconId: u64, NeedZoneStartTimeHours: f32,
                              NeedZoneEndTimeHours: f32,
                              AnimalTypeLocalizationName: u32,
                              NeedZoneScheduleIndex: i8,
                              DiscoveredGroups: A[uint32] }
Vector3_1                   { X: f32, Y: f32, Z: f32 }   (Y = altitude)
```

Données réelles (168 zones, 7 réserves : 14, 9, 16, 6, 8, 3, 4) :

```
Position: X=10761.0  Y=1068.54  Z=6179.0     ← mètres, monde réel
NeedType: 1 | 2 | 3                          ← nourriture / eau / repos
NeedZoneStartTimeHours: 7.0  End: 10.0       ← plage horaire active
ReserveId, MapIconId, NeedZoneScheduleIndex
```

Étendues mesurées : X `[-11984 .. 10761]`, Z `[-12512 .. 8528]`,
altitude Y `[1025 .. 1403]`. Répartition `NeedType` : 1 → 74, 3 → 55, 2 → 39.

**C'est la source de données à utiliser pour une carte.** Elle donne, par espèce,
où l'animal se nourrit / boit / se repose et à quelles heures — c'est-à-dire
exactement ce qu'un chasseur veut savoir, sans lire la mémoire du jeu.

## Le point ouvert : nommer l'espèce d'une need zone

`AnimalTypeLocalizationName` (u32) contient 33 valeurs distinctes. Une seule
résout contre `cotw/data/species_hashes.json` : `C500A572` → **Coll. Peccary**.

Indices :
- Les deux espaces de hash sont donc *différents* — `AnimalTypeLocalizationName`
  n'est pas un `NameHashId` d'asset.
- Testé sans succès : `crc32`, `fnv1a`, `joaat` sur les 359 chaînes de la table
  de localisation anglaise → 0 correspondance.
- Piste la plus prometteuse : `notes/localization-en.json` contient 359 chaînes
  avec des **ids numériques**, et `species_stats.json` associe un `stringId` à
  chaque espèce. Si le champ est l'id localisation *encodé*, la conversion est
  directe ; sinon, tester un hash de la clé de localisation (pas du libellé).

## Conséquence produit

La fonctionnalité « positions en direct de chaque animal » **n'est pas réalisable
depuis la sauvegarde**. En revanche le couple :

> population (quels animaux existent, poids / score / fourrure / médaille)
> × need zones (où aller, pour quelle espèce, à quelle heure)

donne l'essentiel de la valeur de chasse, de façon légale et robuste aux patchs.
