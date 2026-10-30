# Changelog

## 1.0.0 — 2026-10-30

First public release. Clean-room replacement for the *Animal Population Scanner*,
built from the save format up, with a real map instead of a fixed-size window.

### Population

- Every animal in `animal_population_<N>`: species, sex, weight, trophy score,
  predicted medal (per-species thresholds) and computed fur variant + rarity.
- Filters: species (searchable), sex, medal tier, fur rarity, hide scripted animals,
  hide Great Ones. Counts follow the other filters, so a "0" always means empty.
- Virtualised list (4 000+ rows), sortable by species, weight, score, rating, medal.
- CSV export of the filtered list.

### Map

- Need zones (feed / drink / rest) placed in world metres, with their active hours and
  species, dimmed when inactive at the selected hour.
- In-game clock: the hour slider follows `playerinformation_adf` and can be taken over
  manually.
- Zoom / pan / fit, hover tooltip, legend, altitude, cursor coordinates.
- Hunting-pressure overlay (calibrated on Silver Ridge Peaks).
- Observation trails, tour planner (nearest neighbour + 2-opt), distance/bearing
  measure, per-reserve comparison for one species.

### Live layer

- Read-only memory scan: the animals currently simulated around you, with their
  distance, on the map and in a list. 500 m radius (beyond it the game freezes their
  position), phantom filter, continuous discovery.
- The page follows the reserve the game is running (`live_reserve`); opening another
  reserve explains the mismatch and links to the right one.

### Watchers and history

- Diamond / Great One alerts as soon as a new animal appears, plus a background-tab
  title flash.
- Delta: what appeared and what disappeared since the previous scan, keyed on
  `VisualVariationSeed`.
- The **5 most recent spawns per reserve** are highlighted in green in the list, and
  persisted so a restart does not lose them.
- Daily population history per reserve (total, diamonds, golds).
- Proximity alert (120 m, five-minute cooldown per animal).

### Interface

- French (reference) and English, switchable, with the whole table in `web/i18n.js`.
- Dark/light theme, responsive layout (three columns down to a phone-sized single map
  with bottom sheets), keyboard shortcuts (`+`/`-`/`0`/`f`), reduced-motion support.

### Packaging

- Portable Windows build (`Waypoint.exe`, no Python required), PyInstaller onedir.
- State (history, recent spawns, radar cache) in `%LOCALAPPDATA%\Waypoint`.
