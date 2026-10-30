# Cadrage carte : ce qui est établi, ce qui ne l'est pas

## Fait établi : les réserves NE sont PAS centrées à l'origine

Mon hypothèse initiale (« chaque réserve est un carré centré sur 0,0 ») est **fausse**.
Centroïdes des need zones mesurés sur les sauvegardes réelles :

| réserve | centroïde (x, z) |
|---|---|
| Hirschfelden | (−7076, +10639) |
| Vurhonga | (+7704, −8700) |
| Parque Fernando | (−8654, +6762) |
| Yukon | (−6742, −11537) |
| Cuatro Colinas | (−5845, +7153) |
| Silver Ridge Peaks | (−3138, −9126) |
| New England | (+8229, +5427) |
| Emerald Coast | (−8123, −7642) |

Les huit sont loin de l'origine et se répartissent dans les quatre quadrants. Donc :

- une boîte **centrée** unique (`±13 200`) tasse les zones de chaque réserve dans un
  coin de sa propre carte — c'est l'artefact qu'on voyait ;
- la bonne approche est une **boîte ajustée par réserve**.

## Méthode retenue (`cotw.population.fitted_world`)

1. boîte englobante des zones de la réserve ;
2. marge de 6 % de l'étendue ;
3. élargissement d'un axe pour respecter le **ratio de l'image** (sinon les marqueurs
   sont étirés par rapport au terrain).

Vérification : sur Emerald Coast les zones couvrent `u[0.07..0.93] v[0.05..0.95]`, et
les zones d'eau (`drink`) suivent visiblement les rivières et la côte sur
`notes/preview_emerald_fit.png`. C'est un contrôle qualitatif fort : l'eau est le seul
type de zone qu'on peut vérifier contre le terrain.

## Ce qui reste non identifiable

La **taille absolue** de la boîte reste une déduction, pas une mesure : ajuster aux
zones suppose que le joueur a exploré toute la réserve. Si une réserve est à moitié
explorée, sa boîte sera sous-estimée d'autant.

Tentatives d'ancrage objectif :

- **pression de chasse** (`HuntingPressureMap`, grille 256×256 dans le fichier de
  population) : les zones tombent bien sur des cellules 10 à 65× au-dessus de la
  moyenne, ce qui prouve qu'elles sont sur du terrain chassé — mais le critère est
  **unilatéral** : agrandir la boîte tasse les zones sur la zone la plus chassée et
  augmente artificiellement le score. Optimum dégénéré, donc inutilisable seul
  (`tools/calibrate_extent.py`, conservé pour la trace).
- **fog of war** : même limite, la grille ne donne pas l'échelle en mètres.

Piste pour une vraie calibration : ancrer sur un repère externe (coordonnées d'un lac
ou d'un point connu publiées par la communauté), puis ajuster une similitude
(translation + échelle) par moindres carrés.

## Piège à ne pas refaire

Une métrique de « plausibilité » qui accepte `0` est piégée par le remplissage à zéro.
Rencontré trois fois : périodicité (padding parfaitement périodique), champ `Gender`
(valeur 0 ≤ 2), position (`(0,0)` est fini et dans les bornes). Toujours exiger une
valeur **non dégénérée**.
