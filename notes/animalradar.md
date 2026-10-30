# AnimalRadar (outil chinois) — ce qu'on en a appris

Paquet étudié : `COTW AnimalRadar V1.0.0 1194 1`. Bundle **PyInstaller + PySide6**,
142 modules Python dont 75 applicatifs, bytecode CPython 3.12 (même version que nous,
donc désassemblable sans décompilateur tiers).

## Sa technique (lue dans ses propres fichiers `offsets/*.json`)

```
module_base + 40486008        → manager d'animaux
manager + 712   (0x2C8)       → vecteur d'entités
entité + 328    (0x148)       → position Vector3
entité + 40     (0x028)       → hash d'espèce
entité + 376/380              → hp max / hp
entité + 192                  → état ragdoll
entité + 412    (0x19C)       → poids
entité + 432    (0x1B0)       → seed d'apparence
camera_world + 48             → camera (matrice 4×4, 64 octets)
```

Notes de l'auteur : *est = +X, nord = -Z*, échelle métrique « seulement approchée ».

Validation en jeu documentée dans le paquet : poids/score/seed relevés sur 40 puis 39
animaux et appariés au fichier de population ; validation santé (cadavre → vivant) ;
validation du cap (cap 357.6°, virage à 87.8°).

## Le point décisif : il est verrouillé à un build

`memory/offsets.py` refuse de lire la mémoire si le SHA-256 de l'exécutable ne
correspond pas exactement à celui de la configuration :

```
attendu : 89dbab025114090c91a63ae7f0533ee84eee3c48f4b8543224b359c31b794c22  (build 25131233)
notre   : 33c8306e52c5541a5b87e4af576f4149f3da0c23b36775372ec6c41adbab73ca
```

**L'outil ne tourne donc pas sur notre build.** Nos offsets d'entité sont à
redécouvrir ; ce sont *les valeurs* qui sont spécifiques au build, pas la structure.

Test effectué : la chaîne `module+40486008` donne chez nous une table de descripteurs
`(begin, end, count)` sans rapport, et l'entité à `+328` ne contient pas de position.

## Ce qui était réutilisable immédiatement, et l'est maintenant

Le paquet embarque des données **MIT** dérivées du dépôt
[`Pure-Winter-hue/apc-pw`](https://github.com/Pure-Winter-hue/apc-pw), que nous avons
importées (`tools/import_community_data.py`) :

- **seuils de médaille complets**, bronze inclus — le binaire ne contient que argent /
  or / diamant, donc notre palier bronze était une approximation. **122 espèces sur 125**
  ont désormais un vrai seuil bronze.
- **catalogue de fourrures** : 123 espèces, 982 variantes, avec leur probabilité de
  tirage et un palier de rareté dérivé. C'est ce qui manquait pour colorer « fourrure
  rare », et qu'on ne pouvait tirer ni du binaire ni de la sauvegarde.

Concordance mesurée : **361 seuils identiques** (à 1 % près) entre binaire et
communauté, **20 désaccords** à vérifier en jeu — Pronghorn, Magpie Goose, European
Hare étant les plus marqués. Les valeurs binaires restent prioritaires, et un bronze
communautaire incohérent (supérieur à notre argent) est **rejeté** plutôt qu'importé :
c'est ce qui a fait échouer puis passer le banc `verify_thresholds`.

## Ce qui reste ouvert

Trouver, pour **notre** build, l'offset statique du manager et les offsets d'entité.
Méthode : chercher un objet dont le champ à `+offset` vaut un de nos 135 hashes
d'espèce **et** dont un Vector3 dans les bornes de la réserve se lit à `+328` ;
remonter ensuite les pointeurs vers le vecteur, puis déduire l'offset statique.
La recherche par hash d'espèce a été faite (609 occurrences) mais avec des bornes trop
larges : 65 candidats, tous faux. À refaire avec les bornes de Silver Ridge Peaks
(`x ∈ [-13000, 2000]`, `z ∈ [-14000, -4000]`, altitude 800–2000).
