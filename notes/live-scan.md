# Scan mémoire : ce qui est prouvé, et où ça bloque

## MISE À JOUR 3 — la position du joueur ne vient pas de la mémoire

Retournement utile : la première app décompilée (Animal Population Scanner) connaît la
position du joueur quasi instantanément, et **elle ne lit pas la mémoire pour ça**. Le
binaire est natif x64, sans API de lecture de processus. La position est dans la
sauvegarde.

`playerinformation_adf` contient `LastPlayerPositions`, une table de hachage de la
dernière position connue **par réserve** :

```
reserve 0  ( -5710.34, 1040.71,  12764.17)
reserve 3  (  4685.95, 1031.10,  -8116.07)
reserve 4  ( -8359.24, 1203.81,   7823.66)
reserve 5  (  8187.46, 1032.41,   8214.57)
reserve 6  ( -7900.86, 1211.23, -11720.01)
reserve 8  ( -5941.30, 1094.98,   5286.58)
reserve 9  ( -7570.47, 1906.43, -13071.14)   <- Silver Ridge Peaks
reserve 14 ( 10703.00, 1071.44,   6042.22)
reserve 16 ( -6623.65, 1033.58,  -8520.99)
```

Deux recoupements : le joueur avait relevé `(-7583.511, -13065.611)` sur sa carte, soit
13 m d'écart — c'est la position au dernier enregistrement ; et le `Y = 1906.43` tombe
exactement dans la plage des altitudes d'entités relevées (1900–2020), donc les deux
systèmes partagent le même repère.

**Fraîcheur** : le jeu réécrit ce fichier toutes les quelques secondes à quelques
dizaines de secondes. Mesuré à 3 s puis à 32 s selon les moments. C'est ce qui donne
l'impression d'instantanéité.

Conséquence pratique : plus besoin de demander ses coordonnées au joueur. Le radar
utilise `player.position_for(reserve)` par défaut, avec `?x=&z=` en secours.

## MISE À JOUR 2 — offset confirmé par le joueur

L'offset correct est **`position = adresse_du_hash − 580`**, et il est *vérifié* contre
l'observation en jeu, pas déduit.

Test : joueur à `(-7583.511, -13065.611)` (relevé sur la carte du jeu), deux ours noirs
visibles à ~237 m et ~240 m.

```
dist     espèce       position
238.6 m  Black Bear   (-7345.9, 1901.3, -13043.7)
239.1 m  Black Bear   (-7346.1, 1901.3, -13037.6)
```

Deuxième confirmation indépendante : un candidat calculé à **1,2 m** du joueur, ce qui
recoupe le « 1,20 m » affiché par le jeu lui-même.

**Pourquoi je m'étais trompé** : mon histogramme d'écarts utilisait une fenêtre de
±512 octets autour du hash, ce qui **excluait mathématiquement** −580. Avec ±2048,
l'écart −580 gagne largement (59 entités contre 13).

Liste complète obtenue : 59 entités, 6 espèces (Mule Deer, Turkey, Black Bear, Puma,
Desert Bighorn Sheep, RM Elk), distances de 135 à 593 m.

### Les grappes sont des groupes, pas des doublons

Plusieurs espèces apparaissent en grappes serrées : 8 Mule Deer entre 194 et 214 m, 6
Turkeys entre 257 et 264 m, qui se déplacent ensemble. J'avais supposé un artefact de
LOD — **c'est faux** : ce sont de vrais groupes de plusieurs individus distincts. Le
joueur a corrigé cette lecture. Aucune déduplication à faire, chaque entité est un
animal.

### Reste à faire

- Le scan prend 160 s (7,4 Gio relus). Pour du temps réel il faut la chaîne de
  pointeurs : trouver qui pointe vers ces entités, remonter au vecteur puis à l'offset
  statique du module.
- Champs voisins non identifiés : poids, hp/hpmax, seed d'apparence (qui donnerait la
  fourrure des vivants).

---

## Session initiale du 30 octobre, réserve **Silver Ridge Peaks** (`theHunterCotW_F.exe`, pid 15292).

L'astuce qui a débloqué : au lieu de chercher une entité isolée (une paire
hash d'espèce + position plausible est trop peu sélective, on obtient des centaines de
faux positifs), on **histogramme l'écart** entre le hash d'espèce et une position
plausible à proximité, sur toutes les occurrences. Les vraies entités partagent le même
écart.

Résultat : un écart unique à **`position = adresse_du_hash − 276`**, soutenu par
15 entités, toutes regroupées autour du joueur. 641 occurrences de hash d'espèce au
total ; 17 écarts distincts, dont un seul est cohérent.

Radar obtenu (`tools/radar_live.py`), joueur à `(-7420, -13002)` :

```
dist m  espèce          x          y         z
   129  Mule Deer   -7543.8    1910.7  -13037.6
   137  Mule Deer   -7553.8    1912.4  -13031.6
   191  Turkey      -7597.1    1914.3  -13074.7
   192  Puma        -7599.3    1918.6  -13071.5
   192  Mule Deer   -7598.5    1918.3  -13074.3
   202  RM Elk      -7611.3    1925.9  -13067.4
   204  Turkey      -7617.0    1931.9  -13055.7
   293  Mule Deer   -7703.9    1968.5  -13076.9
   335  Black Bear  -7738.5    2021.2  -12898.1
```

5 espèces, toutes du roster de Silver Ridge Peaks, toutes entre 129 et 335 m du joueur.
C'est exactement la structure attendue — et c'est le contrôle qui rend le résultat
crédible plutôt que fortuit.

Deux réserves sur ce résultat : un faux positif à `x = 0` (mes bornes autorisent
`x ≤ 2000`, à resserrer par réserve), et deux entités à position identique
(Turkey et RM Elk à `-7617.0, 1931.9`) qui sont probablement deux objets superposés
plutôt qu'une erreur.

Limite actuelle : le scan prend **160 s** (7,2 Gio lus) car il repart de zéro à chaque
fois. Pour un radar temps réel il faut la chaîne de pointeurs (offset statique →
manager → vecteur), et donc retrouver qui pointe vers ces entités.

---

Session initiale du 30 octobre, réserve **Silver Ridge Peaks** (`theHunterCotW_F.exe`, pid 15292).

## Ce qui marche

**Lecture seule du processus** : `OpenProcess` + `VirtualQueryEx` + `ReadProcessMemory`.
7 234 Mio lisibles en 2 190 régions, 2 chunks illisibles sur 2 811. Aucune écriture,
aucune injection.

**Les animaux de la population sont bien en mémoire**, et leur layout est **identique
à la sauvegarde** : mêmes 32 octets, mêmes offsets.

```
Gender 1 | Weight 1085.829 | Score 179.131 | FeatureModifiers 0x00
         | IsScripted 0 | Seed 0x90D7E6BF | Id 0 | MapPosition (0, 0)
```

Un second emplacement contient le même animal avec un `Id` non nul (679) et une
structure légèrement décalée — probablement la copie « runtime ».

**Conséquence : `MapPosition` vaut `(0,0)` aussi en mémoire.** Les positions ne sont
donc pas dans les données de population, même en direct. Le jeu tient la population et
les entités du monde dans deux structures séparées. C'est un fait, pas une hypothèse.

## Validation croisée décisive

Le jeu affichait une zone **OURS NOIR** à `-7412.000, -12984.000`, active `04:00–08:00`.
Notre extraction contient exactement :

```
reserve 9 · Black Bear · drink · (-7412.0, -12984.0) · 4h-8h   écart = 0.0 m
```

Toute la chaîne — conteneur SAVE, parser ADF v4, need zones, attribution d'espèce par
contraintes — est donc **confirmée par le jeu en cours d'exécution**. C'est la
validation la plus forte obtenue sur ce projet.

## Où ça bloque : les coordonnées affichées ne sont pas les coordonnées internes

- `player_x` (-7420.183) apparaît **exactement une fois** en mémoire → c'est bien un
  float32 stocké.
- `player_z` (-13002.233) apparaît **zéro fois** en float32.

Et la structure qui contient le X du joueur est une série de **matrices 4×4** :

```
X: -7402.83  -7414.70  -7419.74  -7346.00
Y:  1696.54   1696.15   1695.52   1705.12
Z: -11725.2  -11710.1  -11710.7  -11725.6
```

Le Z y vaut ~-11710 alors que l'interface affiche -13002, et l'altitude ~1696 alors
qu'elle affiche 204. **Les coordonnées affichées par le jeu ne sont donc pas le repère
monde interne** : il y a une transformation (translation/rotation/échelle) entre les
deux, qu'il faut d'abord caractériser.

## Ce qu'il faudrait pour aller plus loin

1. **Trouver la liste des acteurs/entités** (classique : tableau de pointeurs, chaque
   acteur portant une matrice de transformation à offset fixe). Sans symboles, c'est
   un travail de reverse de plusieurs jours, pas d'une session.
2. **Caractériser la transformation écran ↔ monde** : avec deux points connus
   (position joueur + zone observée) et leurs coordonnées affichées, on peut poser une
   similitude à 6 inconnues. Il en faut au moins 3–4 pour la résoudre.
3. Une fois les entités trouvées, corréler par `Seed` (chaque animal en a un unique,
   on en connaît 2 078) pour nommer chaque entité.

## Pièges rencontrés

- Les valeurs mémoire **changent pendant le scan** : la position du joueur mesurée
  dans une capture n'est plus valable 60 s plus tard. Il faut chercher la valeur
  affichée au moment T, ou viser des structures stables.
- Un triplet de floats « plausible » n'est pas une position : `(0, 887, 155)` passe
  tous les filtres naïfs et n'est qu'un offset de zone de spawn. Exiger que **les deux
  composantes horizontales** soient grandes.
- Les seeds d'animaux apparaissent 4 à 5 fois chacun (copies sauvegarde + runtime).
  Trouver un seed ne signifie pas avoir trouvé l'entité.

## MISE À JOUR 4 — « le radar ne marche plus, tous les animaux sont statiques »

Symptôme rapporté après un redémarrage du serveur. Le radar serveur était intact : la
même requête, relancée à quatre secondes d'intervalle, montrait des positions qui
bougeaient (vérifié aussi **dans un vrai navigateur** via le protocole DevTools : la
liste des animaux proches change, le compteur passe de 42 à 33, l'horloge avance).

La cause était ailleurs : **la page n'était pas sur la réserve du jeu**. Les entités
vivantes n'existent qu'en un seul exemplaire en mémoire — celles de la réserve chargée.
Le serveur, lui, ancrait les distances sur la position sauvegardée de la réserve
**demandée**. Page sur Emerald Coast (16, le défaut du serveur : `files[-1]`), jeu sur
Silver Ridge Peaks (9) → toutes les entités à plus de 2 000 m de l'ancre → le filtre des
500 m les élimine toutes → panneau vide, et « le radar ne marche plus ».

Deux corrections :

1. `/api/radar` publie `live_reserve` / `live_reserve_name` : la réserve dont les entités
   expliquent le mieux les positions sauvegardées (`_best_saved_position`, minimisation de
   la distance médiane au troupeau — la fonction existait mais n'était atteignable que si
   `position_for(None)` renvoyait `None`, donc jamais). Sans `?reserve=`, le serveur ancre
   désormais sur cette réserve.
2. La page, ouverte sans `?reserve=`, demande `/api/radar` d'abord et charge la réserve
   annoncée. Et si l'utilisateur ouvre explicitement une autre réserve, le panneau
   « Animaux en direct » le dit et propose un lien (« Le jeu tourne sur Silver Ridge
   Peaks. Ouvrir cette réserve ») au lieu d'afficher un `0` muet.

À retenir : **la réserve de la page et celle du jeu doivent coïncider**, sinon le zéro
est un artefact de mesure, pas une absence d'animaux. Et un animal réellement immobile
(repos, alimentation) reste immobile : à l'échelle de la carte (≈ 8 m/px) un déplacement
de 0,5 m/s vaut 0,06 px/s, invisible à l'œil — c'est la liste, pas les points, qui montre
que ça vit.

## MISE À JOUR 5 — « le radar ne marche que sur Silver Ridge Peaks »

Symptôme : après être passé sur Emerald Coast, plus aucun animal en direct. L'intuition du
joueur (« tu n'as gardé que le fichier de Silver Ridge Peaks ») était presque juste : le
radar gardait **les adresses mémoire de la réserve précédente** et ne redécouvrait plus
rien.

La cause est un verrou en trois pièces, toutes dans `cotw/radar.py` :

1. `_interesting_sizes()` déduisait les tailles de régions « intéressantes » (les pools de
   16 Mio) **à partir des adresses connues**. Adresses périmées → aucun pool → le balayage
   de fond (`sweep_step`) ne scannait **rien**, sans erreur.
2. `rescan_entity_regions()` ne rescannait que les régions des adresses connues, c'est-à-dire
   les anciens heaps : la réserve suivante n'y est jamais.
3. Rien n'invalidait le cache quand le jeu changeait de réserve : `load_cache()` rechargeait
   les 93 adresses du scan précédent, `refresh()` les rejetait toutes (le hash d'espèce
   n'est plus là), et la boucle tournait à vide indéfiniment.

Mesuré : 93 adresses en cache, 0 valide, 0 après 65 s de `start_auto()`. Un scan complet
des 8 Gio lisibles trouvait 729 occurrences de hash, mais seulement 116 « entités » — toutes
des faux positifs (positions y=0, x≈0 : des tables de définitions d'espèces, pas des
animaux) parce que le test de plausibilité de `_scan` était beaucoup plus lâche que celui
de `refresh`.

Trois corrections :

- **le repli sur les pools** : sans adresse connue, `_interesting_sizes()` renvoie la taille
  de pool observée (16 Mio). Un démarrage à froid balaie donc 1,3 Gio au lieu de rien,
  soit ~10 s pour retrouver la réserve entière.
- **l'invalidation** : si `refresh()` ne valide plus aucune adresse deux cycles de suite,
  l'ensemble est jeté (la réserve a changé, ou la partie a été rechargée) ; le cache porte
  maintenant le **PID** du jeu, et un cache d'un autre processus est ignoré.
- **le même filtre partout** : `_scan()` applique désormais `MIN_ALTITUDE` /
  `MIN_HORIZONTAL` / `MAX_HORIZONTAL`, comme `refresh()`, au lieu des seuils lâches
  (−2000 < y < 4000, |x| < 30000). Les 116 faux positifs par scan disparaissent.

Vérifié après correction, jeu sur Emerald Coast : adresses périmées détectées à t+20 s,
**90 entités retrouvées à t+30 s**, `/api/radar` → 46 animaux dans les 500 m,
`live_reserve: 16`. Le mécanisme est donc « 20 à 30 s après un changement de réserve »,
sans redémarrage du serveur.

Corollaire pour les tests : `animal_population_16` est réécrit en cours de partie (4004
animaux le 30/10, 4006 le 01/11). Les ancres de layout de `verify_adf.py` et le compte de
`verify_pipeline.py` portent maintenant sur une **copie figée** du fichier
(`tools/fixtures/animal_population_16`), et le compte de zones du boot test vient de la
réponse de l'API au lieu d'être écrit en dur.
