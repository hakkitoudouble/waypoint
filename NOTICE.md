# Notice — third-party material

The MIT license in [LICENSE](LICENSE) covers the **source code** of Waypoint: the `cotw/`
package, `web/app.js`, `web/i18n.js`, `web/index.html`, `web/style.css`, `waypoint.py`,
`build.py` and the scripts under `tools/`.

It does **not** cover the game material bundled with or derived from
*theHunter: Call of the Wild*:

| what | where | why it is here |
|---|---|---|
| reserve map images | `web/assets/maps/*.png` | extracted from the game's map data |
| species icons | `web/assets/icons/*.png` | extracted from the game's UI atlas |
| medal thresholds, species hashes, fur variants, reserve metadata, need-zone types | `cotw/data/*.json` | recovered from the game files and the vendor binary |

That material remains the property of **Expansive Worlds / Avalanche Studios / THQ Nordic**.
It is redistributed on the same basis as any game mod, because the application cannot work
without it, and it is not relicensed by this project.

Waypoint is not affiliated with, endorsed by, or supported by Expansive Worlds, Avalanche
Studios or THQ Nordic. It only reads save files that the game has already written, and it
never modifies them.
