# Fiche GitHub — textes à copier-coller

Tout ce qui se remplit à la main sur GitHub, prêt à coller. Le README, la licence, le
workflow et les notes de version sont déjà dans le dépôt.

---

## 1. Description du dépôt (champ « About », 350 caractères max)

**Anglais** (recommandé, cohérent avec le README ; 140 caractères, donc jamais tronqué
dans l'en-tête du dépôt) :

```
Population scanner and need-zone map for theHunter: Call of the Wild. Read-only save scan, live animal radar, FR/EN, portable Windows build.
```

**Français** (si tu préfères — 213 caractères, il tient dans le champ About mais peut être
raccourci à l'affichage) :

```
Scanner de population et carte des zones de besoin pour theHunter: Call of the Wild. Population lue dans la sauvegarde, radar d'animaux en direct (lecture seule), FR/EN, build Windows portable.
```

## 2. Sujets (topics, 20 max, minuscules et tirets)

```
thehunter-cotw
thehunter
call-of-the-wild
cotw
mod
population-scanner
need-zones
hunting
game-tool
save-parser
adf
radar
offline
python
pyinstaller
windows
french
english
reverse-engineering
```

## 3. Réglages de la page

| champ | valeur |
|---|---|
| Website | l'URL de ta page Nexus Mods (sinon laisse vide) |
| Licence | MIT — GitHub la détecte depuis `LICENSE` |
| Social preview | `assets/waypoint-1024.png`, ou une capture de `assets/screenshots/` |
| Releases | générées par le workflow au tag (`.github/release-notes.md` sert de corps) |
| Discussions | utile pour les retours de joueurs, mais les Issues suffisent |

## 4. Titre et corps de la release

**Titre** : `Waypoint 1.0.0`

**Corps** : le fichier [.github/release-notes.md](.github/release-notes.md) est déjà
utilisé par le workflow (`body_path`). Version française si tu publies la release à la
main :

```markdown
# Waypoint 1.0.0

Scanner de population et carte des zones de besoin pour **theHunter: Call of the Wild** —
remplacement propre de l'Animal Population Scanner, reconstruit depuis le format de
sauvegarde, avec une vraie carte au lieu d'une petite fenêtre fixe.

**Build Windows portable.** Dézippe où tu veux et lance `Waypoint.exe` : le navigateur
s'ouvre sur `http://127.0.0.1:8765`. Aucun Python, rien d'installé dans le jeu, les
sauvegardes sont ouvertes en lecture seule. Garde la fenêtre noire ouverte : c'est le
serveur local.

## Ce que ça montre

- **La population** — tous les animaux de la sauvegarde : espèce, sexe, poids, score,
  médaille pronostiquée et fourrure recalculée depuis la graine, avec filtres et tri.
- **La carte** — toutes les zones de besoin découvertes, en mètres monde, avec leurs
  horaires ; l'heure suit l'horloge du jeu.
- **La couche directe** — les animaux réellement simulés autour de toi, lus dans la
  mémoire du jeu en lecture seule, avec leur distance (rayon 500 m).

## À retenir

- La page **suit la réserve dans laquelle tu joues**.
- **Nouveaux spawns en vert** : les 5 derniers arrivants restent surlignés, et survivent
  à un redémarrage.
- Alertes diamant / Great One dès qu'un animal apparaît, alerte de proximité, delta des
  apparitions et disparitions.
- Pression de chasse, traces, tournée, mesure, comparateur de réserves, export CSV,
  tableau de chasse, historique quotidien.
- **Français et anglais**, thème sombre/clair, interface adaptative jusqu'au téléphone.

## Installation

1. Télécharge `Waypoint-1.0.0-win64.zip`.
2. Dézippe-le où tu veux.
3. Lance `Waypoint.exe`, le navigateur s'ouvre.

`INSTALL.txt` dans l'archive reprend tout, en français et en anglais (dont l'option
portable `--data-dir` et le faux positif possible de Defender).

## Prérequis

Windows 10 ou 11, 64 bits. Le jeu installé, avec le dossier de sauvegarde habituel sous
`Documents\Avalanche Studios\COTW\Saves\<steamid>\`. Les sauvegardes ne sont jamais
modifiées.

## Limites connues

- La position des animaux **n'est pas** dans la sauvegarde : le tableau de chasse n'est
  pas plaçable sur la carte, et un animal vivant ne porte ni poids, ni score, ni médaille.
- Les zones de besoin sont un instantané du dernier scan.
- La pression de chasse n'est calée que sur Silver Ridge Peaks.
- Les noms d'espèces et de réserves restent tels que les fichiers du jeu les écrivent.

## Empreintes

`SHA256SUMS.txt` est joint à cette release.

---

Waypoint n'est pas affilié à Expansive Worlds, Avalanche Studios ou THQ Nordic. Le code est
sous MIT ; les cartes, icônes et tables de jeu restent la propriété de leurs auteurs (voir
`LICENSE`).
```

## 5. Pousser le dépôt

Dépôt : **https://github.com/hakkitoudouble/waypoint** (le remote `origin` est déjà
configuré en local ; si tu choisis un autre nom de dépôt que `waypoint`, corrige-le avec
`git remote set-url origin …` et remplace les trois URLs du README).

```powershell
cd C:\Users\Maelo\Documents\mods\cotw-pop
git push -u origin main

# la release : le workflow construit le zip et l'attache
git tag v1.0.0
git push --tags
```

Le workflow (`.github/workflows/build.yml`) lance `tools/check_ui.py`, `tools/check_i18n.py`,
puis `python build.py` sur `windows-latest`, et attache `Waypoint-<version>-win64.zip` +
`SHA256SUMS.txt` à la release. Tu peux aussi le déclencher à la main depuis l'onglet
*Actions* (sans tag : il produit juste un artefact, sans publier).
