# Waypoint — COTW population & need-zone companion (web UI)

A single-page, offline, zero-build web UI for a *theHunter: Call of the Wild*
save scanner. Two layers, one screen:

* **Need zones (the map)** — every discovered feed / drink / rest spot, in world
  metres, with the hours it is active. This is where you actually go.
* **Population (the list)** — every animal in the save: species, sex, weight,
  score, trophy medal and fur rarity. Animal positions are **not** stored in
  save files, so they are never plotted.

No framework, no bundler, no npm, no network:

```
web/
  index.html        markup + inline SVG icon sprite (English source, data-i18n tags)
  style.css         design tokens, layout, components, themes
  i18n.js           translation table (FR) + t() / apply() / split(); loaded first
  app.js            data loading, filters, hour slider, canvas map, list
  fixture.js        window.FIXTURE_DATA + window.FIXTURE_ZONES (offline sample)
  assets/maps/*.png 19 reserve maps (greyscale)
  assets/icons/*.png species icons
  README.md
```

## Running it

**With the scanner server.** Serve this folder and answer two endpoints:

```js
fetch("/api/population")                 // population layer
fetch("/api/needzones?reserve=16")       // map layer, per reserve
```

Any static server rooted at `web/` works (e.g. `python -m http.server` inside
`web/`) as long as those two paths are routed to the scanner.

**Without a server.** Open `index.html` straight from disk. `file://` cannot
answer the API, so the app skips the request and uses `window.FIXTURE_DATA` +
`window.FIXTURE_ZONES` from `fixture.js`, which `index.html` loads before
`app.js`. A "Sample data" badge always shows which source is live.

Scripts are classic `<script>` tags, not ES modules, precisely so the
double-click-from-disk path keeps working (modules are blocked by CORS on
`file://`).

### Fallback rules

| population | need zones | result |
| --- | --- | --- |
| live | live | full app, live data |
| live | fails | map + list, a persistent "need zones unavailable" note |
| fails | — | both come from the bundled sample (never mixed with real data) |

Sample zones are **only** ever paired with the sample population: mixing fake
zones into a real save would be misleading.

### Language

The UI ships in **French** (reference) and **English** (source); the `FR` / `EN`
button next to the theme toggle switches, and the choice is remembered.

* `index.html` holds the English text plus `data-i18n*` attributes; `i18n.js`
  rewrites those nodes before the first paint and removes the `i18n-pending`
  guard class.
* `app.js` resolves its labels once at load time (`TYPE_LABEL`, `MEDAL_LABEL`, …)
  and calls `t("English source")` for anything it builds. A missing entry
  degrades to English, never to a key.
* Switching **reloads the page** — see `notes/i18n.md`. The filter selection is
  persisted (`cotw.filters`, only the unchecked entries) so the reload costs
  nothing.
* Numbers follow the language: `48,2 kg` / `48.2 kg`, and `scanned 30 Oct` /
  `scanné 30 oct.`.
* Species and reserve names are **not** translated: they come from the save and
  from `/api/reserves`.

`tools/check_i18n.py` cross-checks the table, the markup and `app.js`;
`work/uiboot/boot.js` boots the real page in either language.

## Data contracts

### `GET /api/population`

```jsonc
{
  "schema": 1,
  "generated_at": "2026-06-28T18:40:00Z",
  "reserve": { "index": 16, "name": "Emerald Coast Australia",
               "map": "EmeraldCoast_bw.png",
               "map_image": "assets/maps/EmeraldCoast_bw.png" },
  "world": { "min_x": -12661, "max_x": -3787, "min_y": -12523, "max_y": -3957 },
  "species": [{ "name": "Sambar", "icon": "Sambar", "great_one": true, "count": 7 }],
  "animals": [{
    "id": "a00000", "species": "Sambar", "gender": "male",
    "weight": 282.8, "score": 188.4, "trophy_rating": 0.96,
    "medal": "diamond", "medal_source": "game",
    "fur": "Albino", "fur_rarity": "super_rare", "is_scripted": false,
    "x": 0, "y": 0
  }]
}
```

`x`/`y` are always `0` on real saves and are ignored by the UI.

### `GET /api/needzones?reserve=<index>`

```jsonc
{
  "reserve": { "index": 16, "name": "Emerald Coast Australia", "confidence": "VERIFIED" },
  "world": { "min_x": -12661, "max_x": -3787, "min_y": -12523, "max_y": -3957 },
  "world_observed": { "...": "raw zone bbox — reference only, never plotted" },
  "zones": [{
    "x": -7888, "z": -4560, "altitude": 1198.6,
    "type": "drink", "need_type": 2,
    "start_hour": 6, "end_hour": 10,
    "animal_type_hash": "26FA9F96", "animal_type": "Red Deer"
  }]
}
```

Everything is treated as untrusted: missing arrays, null numbers, unknown
medals/furs/zone types, a broken `world` box and non-numeric coordinates are all
handled. `GET /api/needzones` without a query (the reserve index) is not needed
by this frontend.

## Coordinate mapping (the decision you should know about)

Zones carry `(x, z)` plus a separate `altitude` axis. **Altitude never feeds the
transform** — only x and z do:

```
u = (x - min_x) / (max_x - min_x)          left → right
v = (max_y - z) / (max_y - min_y)          top  → bottom   ← Z IS FLIPPED
image_px = (u * imageWidth, v * imageHeight)
screen_px = image_px * camera.scale + camera.offset
```

Game-world +Z points north (up) while image rows grow downward, so the vertical
axis is flipped. If a reserve's zones turn out to be stored top-down, flip the
single constant `Y_AXIS_FLIPPED` at the top of `app.js`.

`world` is fitted **per reserve** by the backend (zone extent + margin, widened
to the map image's aspect ratio). The UI uses `zones.world` as the authoritative
box, never `population.world` (they are equal, but zones win), and never
`world_observed`. It never re-fits the box itself and never clamps markers to the
image.

## The map

* One `<img>` transformed with `translate(tx, ty) scale(s)`; one `<canvas>` above
  it drawing every zone in the same CSS-pixel space. No DOM node per zone.
* Canvas backing store = CSS size × DPR (capped, plus a ~16 MP budget), context
  pre-scaled, so zones stay sharp on Retina.
* Redraws only on camera / filter / hour changes — the map is completely idle
  between interactions.
* Hover hit-testing is one O(n) nearest-zone search over the positions cached in
  the last draw (~200 zones → microseconds).
* Drag to pan, wheel to zoom at the cursor, pinch-zoom + two-finger pan on touch,
  double-click / `0` / the reset button to fit the whole map, "Fit zones" to
  frame the filtered zones, arrows to pan, `+`/`-` to zoom, `f` to fit zones.

### Zone markers

Colour and shape encode the **zone type** (never the species — 15 species hues
would fight the medal palette):

| Type | Colour | Shape |
| --- | --- | --- |
| feed | green | rounded square |
| drink | blue | circle |
| rest | amber | triangle |

Each zone also has a fixed, data-independent ring. Zones are deliberately
quieter than trophy glyphs: small, no glow, inactive ones at ~30 % opacity so
the player keeps context instead of the map blinking.

**Species filter → zones.** Selecting species prunes the zone layer as well as
the list, so "Sambar + 07:00" answers *where do I go right now*. Zones whose
animal type is unknown (`null`, or a species missing from the scanned roster) are
**kept and drawn hollow with a dashed ring** instead of being hidden — silently
dropping an unattributed hotspot would be worse than showing it as uncertain.

**Hour filter.** A 0–24 slider (15-minute steps). A zone is active when the hour
falls in `[start_hour, end_hour)`, wrapping past midnight when
`end_hour < start_hour`; `start_hour === end_hour` (and `0 → 24`) means all day.
Inactive zones stay on the map at ~30 % opacity. The readout shows
`hh:mm` plus `N / M active`, where M is the number of zones left after the type
and species filters.

## Population list

* Rarity colours are the medal tier: Great One star, Diamond rhombus, Gold circle,
  Silver triangle, Bronze square, None **hollow muted ring**. `none` is the
  majority of a real reserve (no trophy score at all), so it must not look like a
  low medal.
* `medal_source: "relative"` renders as `Diamond (relative)` with an explanatory
  tooltip; `"game"` renders plainly. `"none"` animals have no trophy score.
* A medal tier with **zero** animals in the scan is hidden from the filter and the
  legend instead of showing a dead "0" row (bronze today, because no reliable
  bronze cut-off exists yet).
* The list is virtualised: 4 000+ rows scroll smoothly because only the visible
  window (± 4 rows) is in the DOM. Row height is fixed at 50 px
  (`LIST_ROW_H` in `app.js` must match `.animal-row` + gap in `style.css`).
* Sortable by species, weight, score, trophy rating and medal tier; unknowns sort
  last. Sort choice and the hour persist in `localStorage`.
* **New spawns are green.** The save has no spawn timestamp, so `app.js` uses the
  watcher's diff: `/api/alerts` carries `spawns`, a rolling shortlist of the **5 most
  recent newcomers per reserve** (each with its `VisualVariationSeed` and its own
  `seen_at`). Rows whose seed is in that shortlist get a green tint, a green edge and a
  dot, and the list header shows `1 nouvel animal` / `5 nouveaux animaux` /
  `5 new animals`. A quiet scan never clears it, a batch of ten keeps the five newest,
  and the shortlist is persisted in `work/spawns.json`, so neither a removal nor a
  server restart erases it. Identity is the seed because `id` is `0` for every animal
  in the save.

### Live reserve

The entities read from game memory belong to **one** reserve: the loaded one. So
`/api/radar` publishes `live_reserve` (and its display name), the reserve whose saved
player position best explains the herd. Opened without `?reserve=`, the page asks the
radar first and loads that reserve — the only one whose animals are actually simulated.
If the page is on another reserve, the live panel says so and links to the right one
instead of showing an unexplained `0`. Animals beyond the 500 m simulation radius are
filtered out (their in-memory position is frozen, i.e. not live at all).

## Layout

| Width | Layout |
| --- | --- |
| ≥ 1280px | filters · map · list, three columns |
| 1000–1279 landscape | same three columns, narrower rails |
| 1000–1279 portrait | filters · (map above list) |
| 900–999px | filters · (map above list) |
| < 900px | map full-bleed; filters and list are bottom sheets behind a tab bar |

Typography, spacing and radii use `clamp()`; columns are `minmax(0, 1fr)` with
truncating text, so nothing ever scrolls horizontally from 320px to 2560px. Dark
is the default theme; the toggle persists (`cotw.theme`) and is applied before
first paint. All animation is disabled under `prefers-reduced-motion`.

## Limitations

* `weight`/`score` units are whatever the save uses (kg / points assumed for
  display only).
* Altitude is shown in the tooltip but is not a map axis.
* The PNG is soft past ~4× its native resolution; markers stay crisp because they
  are vector-drawn.
* Zone toasts/tooltips are English; the "individual positions unavailable" notice
  is French (product copy supplied by the backend author).
* Tested in Chromium (headless screenshots at 320 / 360 / 768 / 900 / 1024 / 1280
  / 1440 / 2560) against current Firefox/Safari features (`inert` degrades to no
  focus trap when unsupported).
