# Waypoint 1.0.0

Population scanner and need-zone map for **theHunter: Call of the Wild** — a clean-room
replacement for the Animal Population Scanner, built from the save format up, with a real
map instead of a cramped fixed-size window.

**Portable Windows build.** Unzip anywhere and run `Waypoint.exe`: your browser opens on
`http://127.0.0.1:8765`. No Python, nothing installed into the game, saves are opened
read-only. Keep the console window open — it is the local server.

## What it shows

- **The population** — every animal in the save: species, sex, weight, trophy score,
  predicted medal (per-species thresholds) and the fur variant recomputed from its seed,
  with searchable filters and a sortable list of 4 000+ rows.
- **The map** — every discovered need zone (feed / drink / rest) in world metres, with its
  active hours, dimmed when inactive at the selected hour. The hour slider follows the
  in-game clock.
- **The live layer** — the animals actually simulated around you, read from game memory in
  read-only mode, with their distance, on the map and in a list. 500 m radius, because
  beyond it the game freezes their position.

## Highlights

- The page **follows the reserve the game is running**, and says so if you open another one.
- **New spawns in green**: the 5 most recent newcomers of the reserve stay highlighted,
  with a count next to the list title — and they survive a restart.
- Diamond / Great One alerts as soon as a new animal appears, plus proximity alerts and a
  delta of what appeared or disappeared since the previous scan.
- Hunting pressure overlay, observation trails, tour planner (nearest neighbour + 2-opt),
  distance/bearing measure, reserve comparison, CSV export, harvest log, daily history.
- **French and English**, dark/light theme, layout that adapts down to a phone.
- Hover tooltips everywhere, keyboard shortcuts (`+` `-` `0` `f`), reduced-motion support.

## Install

1. Download `Waypoint-1.0.0-win64.zip` below.
2. Unzip it wherever you like (Documents, `D:\Games`, …).
3. Run `Waypoint.exe`. Your browser opens on `http://127.0.0.1:8765`.
4. Keep the console window open; close it to stop the server.

`INSTALL.txt` inside the zip repeats this in French and English, including the portable
`--data-dir` option and what to do if Windows Defender flags the executable (the usual
PyInstaller heuristic false positive — the full source is in this repository).

## Requirements

Windows 10 or 11, 64-bit. theHunter: Call of the Wild installed, with the usual save folder
under `Documents\Avalanche Studios\COTW\Saves\<steamid>\`. Saves are never written to.

## Known limitations

- Animal positions are **not** in the save (`MapPosition` is always 0,0), so the harvest log
  cannot be placed on the map, and a live animal carries neither weight, score nor medal.
  The live layer gives its position, never its rank.
- Need zones are a snapshot of the last scan; they refresh when the game rewrites the file.
- Hunting pressure is only calibrated on Silver Ridge Peaks; other reserves warn that the
  placement is approximate.
- Species and reserve names are shown as the game files spell them.
- Map scale is fitted from your own discovered zones, so a half-explored reserve is slightly
  underestimated.

## Checksums

`SHA256SUMS.txt` is attached to this release.

---

Waypoint is not affiliated with Expansive Worlds, Avalanche Studios or THQ Nordic.
Code is MIT; the bundled map images, species icons and game tables remain their owners'
property — see `NOTICE.md`.
