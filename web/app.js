/* =============================================================================
 * Waypoint — theHunter: Call of the Wild companion
 * -----------------------------------------------------------------------------
 * Two layers, two sources:
 *
 *   POPULATION   GET /api/population              what exists on the reserve
 *                species / sex / weight / score / trophy / fur rarity
 *   NEED ZONES   GET /api/needzones?reserve=<id>  where to go, and when
 *                discovered feed / drink / rest spots in world metres with an
 *                active hour window
 *
 * Individual animal positions are NOT stored in save files (every
 * AnimalData_5.MapPosition is 0,0), so the map draws need zones only. The
 * population side keeps its filters, rarity colours and sortable list.
 *
 * Classic script (no ES modules) on purpose: index.html can be opened straight
 * from disk (file://), where modules are blocked by CORS. When the local API is
 * unreachable, window.FIXTURE_DATA / window.FIXTURE_ZONES from fixture.js (which
 * index.html loads first) stand in for both endpoints.
 *
 * ── COORDINATE TRANSFORM ────────────────────────────────────────────────────
 * A zone carries (x, z) in world metres plus a separate `altitude` axis.
 * Altitude is NEVER a map coordinate — only x and z feed the transform.
 *
 *   u = (x - min_x) / (max_x - min_x)         left → right
 *   v = (z - min_y) / (max_y - min_y)         top  → bottom   ← IDENTITY, NOT FLIPPED
 *   image_px = (u * imageWidth, v * imageHeight)
 *   screen_px = image_px * camera.scale + camera.offset
 *
 * `world` is delivered per reserve and is fitted from that reserve's own zones;
 * it is never shared between reserves. The world box's second axis is called
 * `min_y` / `max_y` by the API even though it holds z values.
 *
 * ORIENTATION IS IDENTITY, verified against the player's own position. On Silver
 * Ridge Peaks the player stands at z ≈ -13071, near `min_y`, and reports being at
 * the TOP-LEFT of the reserve map; only the identity mapping (small z at the top)
 * puts them there. An earlier version assumed "+Z points north, so flip" and drew
 * the player in the bottom-left corner instead. Drink zones landing on the bright
 * water patches also score better with the identity mapping (mean brightness
 * 128.5 vs 119.1). If a reserve ever renders upside down, flip this one constant:
 * the forward transform, the inverse transform (cursor readout) and hit testing
 * all derive from it.
 *
 * ── HIT TESTING ─────────────────────────────────────────────────────────────
 * No DOM node per zone. Every draw caches each visible zone's screen position in
 * `state.hits`; a pointermove does one O(n) nearest-zone search. ~200 zones cost
 * microseconds.
 *
 * ── HiDPI ───────────────────────────────────────────────────────────────────
 * The canvas backing store is CSS size × devicePixelRatio (capped, and further
 * capped by a total-pixel budget). The 2D context is pre-scaled by the DPR once
 * per frame, so all drawing code keeps thinking in CSS pixels.
 * ========================================================================== */

(function () {
  "use strict";

  /* ======================================================================== *
   * 1. Constants
   * ======================================================================== */

  /** See the COORDINATE TRANSFORM note above. Identity, verified in game. */
  var Y_AXIS_FLIPPED = false;

  /*
   * Every visible label goes through t() so the interface speaks the language
   * picked in i18n.js. The table is resolved ONCE, at load time: switching the
   * language reloads the page (see i18n.js) rather than trying to re-render a
   * pipeline that is built on these constants.
   */
  var TYPES = ["feed", "drink", "rest"];
  var TYPE_LABEL = { feed: t("Feed zone"), drink: t("Drink zone"), rest: t("Rest zone") };
  var TYPE_SHORT = { feed: t("Feed"), drink: t("Drink"), rest: t("Rest") };
  var TYPE_NEED = { feed: 1, drink: 2, rest: 3 };
  var NEED_TYPE = { 1: "feed", 2: "drink", 3: "rest" };

  var MEDALS = ["great_one", "diamond", "gold", "silver", "bronze", "none"];
  var MEDAL_LABEL = {
    great_one: t("Great One"),
    diamond: t("Diamond"),
    gold: t("Gold"),
    silver: t("Silver"),
    bronze: t("Bronze"),
    none: t("None")
  };
  var MEDAL_Z = { none: 0, bronze: 1, silver: 2, gold: 3, diamond: 4, great_one: 5 };

  var FUR_TIERS = ["common", "uncommon", "rare", "very_rare", "super_rare", "great_one"];
  var FUR_LABEL = {
    common: t("Common"),
    uncommon: t("Uncommon"),
    rare: t("Rare"),
    very_rare: t("Very rare"),
    super_rare: t("Super rare"),
    great_one: t("Great One")
  };
  var FUR_HALO = { rare: true, very_rare: true, super_rare: true, great_one: true };

  var GENDERS = { male: t("Male"), female: t("Female"), unknown: t("Unknown") };
  var SEX_GLYPH = { male: "\u2642", female: "\u2640", unknown: "?" };

  var SORT_KEYS = { species: 1, weight: 1, score: 1, trophy: 1, medal: 1 };
  /* The sort bar's own wording, so its aria-label reads like the button. */
  var SORT_LABEL = {
    species: t("species"),
    weight: t("weight"),
    score: t("score"),
    trophy: t("trophy rating"),
    medal: t("medal tier")
  };

  var TAU = Math.PI * 2;
  var STORE_THEME = "cotw.theme";
  var STORE_SORT = "cotw.sort";
  var STORE_HOUR = "cotw.hour";
  var STORE_CLOCK = "cotw.clock";
  var STORE_FILTERS = "cotw.filters";
  var DEFAULT_MAP = { w: 1150, h: 1110 };
  var MAX_CANVAS_PIXELS = 16e6;
  var LIST_ROW_H = 50;              // must match .animal-row height in style.css
  var DEFAULT_HOUR = 9.5;

  /* ======================================================================== *
   * 2. Tiny helpers
   * ======================================================================== */

  function $(id) { return document.getElementById(id); }
  /** Translate one interface string. i18n.js is a hard dependency of index.html;
   *  without it the app degrades to the English source strings, never to keys. */
  function t(key, vars) { return window.I18N ? window.I18N.t(key, vars) : key; }
  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
  function fin(v) {
    if (typeof v === "number") return isFinite(v) ? v : null;
    if (typeof v === "string" && v.trim() !== "") {
      var n = Number(v);
      return isFinite(n) ? n : null;
    }
    return null;
  }
  function str(v) {
    return typeof v === "string" && v.trim() !== "" ? v.trim() : null;
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function svgIcon(id) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "ico");
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#" + id);
    svg.appendChild(use);
    return svg;
  }
  function pad2(n) { return n < 10 ? "0" + n : String(n); }
  function thousands(n) {
    return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, "\u2009");
  }
  function num(v, digits) {
    if (v == null || !isFinite(v)) return "\u2014";
    var text = digits == null ? String(v) : v.toFixed(digits);
    var sep = window.I18N ? window.I18N.decimal() : ".";
    return sep === "." ? text : text.replace(".", sep);
  }
  function plural(n, one, many) { return n === 1 ? one : many; }

  /* Colour maths for canvas: accept #rgb / #rrggbb / rgb() / rgba(). */
  var rgbCache = Object.create(null);
  function parseColor(input) {
    if (!input) return null;
    var key = input.trim();
    if (rgbCache[key]) return rgbCache[key];
    var out = null;
    if (key.charAt(0) === "#") {
      var hex = key.slice(1);
      if (hex.length === 3) hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
      if (hex.length === 6 || hex.length === 8) {
        out = [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];
      }
    } else {
      var m = key.match(/rgba?\(([^)]+)\)/i);
      if (m) {
        var parts = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
        if (parts.length >= 3) out = [parts[0], parts[1], parts[2]];
      }
    }
    if (out) rgbCache[key] = out;
    return out;
  }
  function rgba(color, alpha) {
    var c = parseColor(color);
    if (!c) return "rgba(255,255,255," + alpha + ")";
    return "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + alpha + ")";
  }

  /* ── hours ──────────────────────────────────────────────────────────────── */

  function formatHour(h) {
    if (h == null || !isFinite(h)) return "\u2014";
    if (h >= 24) return "24:00";
    var hh = Math.floor(h);
    var mm = Math.round((h - hh) * 60);
    if (mm === 60) { mm = 0; hh = (hh + 1) % 24; }
    return pad2(hh) + ":" + pad2(mm);
  }

  /** 0..24, keeping 24 as 24 (a window may legitimately end at midnight). */
  function clampHour(h) {
    if (h == null || !isFinite(h)) return null;
    if (h === 24) return 24;
    var v = ((h % 24) + 24) % 24;
    return v;
  }

  /**
   * Is a zone active at `hour`?
   *  - [start, end) with end > start is a plain daytime window
   *  - end < start wraps past midnight (22 → 2 is active 22:00–24:00 and 00:00–02:00)
   *  - start === end means "all day" (also used when the window is missing)
   */
  function isActiveAt(zone, hour) {
    var s = zone.start;
    var e = zone.end;
    if (s == null || e == null) return true;
    var h = clampHour(hour);
    if (h == null) return true;
    if (s === e) return true;
    if (e === 24) return h >= s || h === 0 && s === 0;
    if (e < s) return h >= s || h < e;
    return h >= s && h < e;
  }

  function windowText(zone) {
    if (zone.start == null || zone.end == null) return t("All day");
    if (zone.start === zone.end) return t("All day");
    if (zone.start === 0 && zone.end === 24) return t("All day");
    return formatHour(zone.start) + " \u2013 " + formatHour(zone.end);
  }

  /* ======================================================================== *
   * 3. State
   * ======================================================================== */

  var state = {
    mode: "live",                  // population source: live | fixture
    zoneMode: "live",              // zones source: live | fixture | missing
    reserve: { index: null, name: t("Unknown reserve"), confidence: null },
    generatedAt: null,
    world: { minX: -12448, maxX: -4000, minY: -12464, maxY: -4016 },
    img: { w: DEFAULT_MAP.w, h: DEFAULT_MAP.h },
    imgReady: false,
    imgFailed: false,
    animals: [],
    species: [],
    byId: Object.create(null),
    zones: [],
    visibleZones: [],
    activeCount: 0,
    activeByType: { feed: 0, drink: 0, rest: 0 },
    speciesFilterActive: false,
    iconByName: Object.create(null),
    speciesByLower: Object.create(null),
    hour: DEFAULT_HOUR,
    filters: null,
    counts: { species: {}, medals: {}, furs: {}, zones: { feed: 0, drink: 0, rest: 0 } },
    filtered: [],
    listItems: [],
    listStart: -1,
    listEnd: -1,
    view: { w: 1, h: 1 },
    dpr: 1,
    ctx: null,
    cam: { scale: 1, tx: 0, ty: 0, fit: 1, min: 0.05, max: 8 },
    live: {
      on: false, animals: [], player: null, source: null, age: null,
      error: null, count: 0, timer: 0, busy: false, colors: Object.create(null),
      /* true while the scanner is still looking (first sweep after a launch) */
      discovering: false,
      /* which reserve the entities in memory belong to, and whether this page is on it */
      reserve: null, reserveName: null
    },
    furs: null,
    followClock: true,
    showPressure: false,
    showTrails: false,
    pressure: null,
    trails: null,
    compare: null,
    harvests: null,
    lastAlertId: null,
    titleAlert: null,
    /* "just spawned" marking: seed key -> spawn timestamp, filled from /api/alerts */
    newSpawns: Object.create(null),
    spawnAt: 0,
    baseTitle: null,
    route: null,
    measure: null,
    nearby: false,
    nearbySeen: null,
    playerTrail: null,
    refreshing: false,
    dataVersion: null,
    proj: { kx: 1, ky: 1, ox: 0, oy: 0, flip: Y_AXIS_FLIPPED },
    tween: null,
    hits: [],
    hovered: null,
    sort: { key: "species", dir: "asc" },
    reducedMotion: false,
    userMoved: false,
    sheet: null,
    lastDpr: 1,
    fatal: false,
    persistentNote: "",
    /* /api/ping: version, data dir, and where the save folder was found */
    app: null,
    needsSetup: false
  };

  var PAL = {
    feed: "#79d06f",
    drink: "#5cb8ff",
    rest: "#ffab5e",
    great_one: "#c96bff",
    diamond: "#8ef2ff",
    gold: "#ffcf63",
    silver: "#c9d5da",
    bronze: "#d08a56",
    none: "#8a8a84",
    rare: "#5fb6ff",
    very_rare: "#a97bff",
    super_rare: "#ff77c8",
    great_one_fur: "#ffd166",
    ink: "rgba(0,0,0,.72)",
    edge: "rgba(255,255,255,.55)",
    accent: "#f2b45c",
    text: "#e9f2ec",
    dim: "#9db1a6",
    panel: "#0f1714",
    border: "rgba(196,236,214,.26)"
  };

  var els = {};
  var mqCompact = window.matchMedia("(max-width: 899px)");
  var mqMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  var rafId = 0;
  var listRaf = 0;
  var ttSize = { w: 0, h: 0 };
  var noteTimer = 0;

  /* ======================================================================== *
   * 4. Palette (the canvas mirrors the CSS custom properties)
   * ======================================================================== */

  function readPalette() {
    var cs = getComputedStyle(document.documentElement);
    function v(name, fallback) {
      var raw = cs.getPropertyValue(name).trim();
      return raw || fallback;
    }
    PAL.feed = v("--zone-feed", PAL.feed);
    PAL.drink = v("--zone-drink", PAL.drink);
    PAL.rest = v("--zone-rest", PAL.rest);
    PAL.great_one = v("--medal-great-one", PAL.great_one);
    PAL.diamond = v("--medal-diamond", PAL.diamond);
    PAL.gold = v("--medal-gold", PAL.gold);
    PAL.silver = v("--medal-silver", PAL.silver);
    PAL.bronze = v("--medal-bronze", PAL.bronze);
    PAL.none = v("--medal-none", PAL.none);
    PAL.rare = v("--fur-rare", PAL.rare);
    PAL.very_rare = v("--fur-very-rare", PAL.very_rare);
    PAL.super_rare = v("--fur-super-rare", PAL.super_rare);
    PAL.great_one_fur = v("--fur-great-one", PAL.great_one_fur);
    PAL.ink = v("--marker-ink", PAL.ink);
    PAL.edge = v("--marker-edge", PAL.edge);
    PAL.accent = v("--accent", PAL.accent);
    PAL.text = v("--text", PAL.text);
    PAL.dim = v("--dim", PAL.dim);
    PAL.panel = v("--surface", PAL.panel);
    PAL.border = v("--line-3", PAL.border);
    rgbCache = Object.create(null);
  }

  /* ======================================================================== *
   * 5. Data loading
   * ======================================================================== */

  function fetchJson(url) {
    try {
      return fetch(url, { cache: "no-store", headers: { Accept: "application/json" } })
        .then(function (res) {
          if (!res.ok) throw new Error("HTTP " + res.status + " for " + url);
          return res.json();
        });
    } catch (err) {
      return Promise.reject(err);
    }
  }

  /** POST JSON, and keep the server's own message when it answers 4xx. */
  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body)
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (payload) {
        if (!res.ok) {
          var message = (payload && payload.message) || ("HTTP " + res.status);
          var error = new Error(message);
          error.payload = payload;
          throw error;
        }
        return payload;
      });
    });
  }

  function normaliseAnimal(raw, i) {
    var id = str(raw.id) || ("row-" + i);
    var gender = raw.gender === "male" || raw.gender === "female" ? raw.gender : "unknown";
    var medal = MEDALS.indexOf(raw.medal) >= 0 ? raw.medal : "none";
    var furRarity = FUR_TIERS.indexOf(raw.fur_rarity) >= 0 ? raw.fur_rarity : null;
    var tr = fin(raw.trophy_rating);
    if (tr != null) tr = clamp(tr, 0, 1);
    /* "game" = real per-species thresholds, "relative" = percentile fallback
       (same colour, but the UI must say so), "none" = no trophy score. */
    var medalSource = raw.medal_source === "relative" || raw.medal_source === "game"
      ? raw.medal_source
      : (medal === "none" ? "none" : "game");
    return {
      id: id,
      species: str(raw.species) || t("Unknown"),
      gender: gender,
      weight: fin(raw.weight),
      score: fin(raw.score),
      trophy: tr,
      medal: medal,
      medalSource: medalSource,
      fur: str(raw.fur),
      furRarity: furRarity,
      scripted: !!raw.is_scripted,
      /* VisualVariationSeed: the only stable identity across scans (Id is always 0),
         so it is what links a row to the watcher's "just spawned" records. */
      seed: raw.seed == null ? null : String(raw.seed)
    };
  }

  function medalText(a) {
    return MEDAL_LABEL[a.medal] + (a.medalSource === "relative" ? " " + t("(relative)") : "");
  }

  function normalisePopulation(raw) {
    var src = raw && typeof raw === "object" ? raw : {};

    var wsrc = src.world && typeof src.world === "object" ? src.world : {};
    var minX = fin(wsrc.min_x), maxX = fin(wsrc.max_x);
    var minY = fin(wsrc.min_y), maxY = fin(wsrc.max_y);
    if (minX == null || maxX == null || !(maxX > minX)) { minX = -8192; maxX = 8192; }
    if (minY == null || maxY == null || !(maxY > minY)) { minY = -8192; maxY = 8192; }

    var rsrc = src.reserve && typeof src.reserve === "object" ? src.reserve : {};
    var reserve = {
      index: fin(rsrc.index),
      name: str(rsrc.name) || t("Unknown reserve"),
      map: str(rsrc.map_image) || str(rsrc.map) || null
    };

    var animalsRaw = Array.isArray(src.animals) ? src.animals : [];
    var animals = [];
    var seenIds = Object.create(null);
    for (var i = 0; i < animalsRaw.length; i++) {
      var a = animalsRaw[i];
      if (!a || typeof a !== "object") continue;
      var n = normaliseAnimal(a, i);
      if (seenIds[n.id]) n.id = n.id + "#" + i;
      seenIds[n.id] = true;
      animals.push(n);
    }

    var speciesSrc = Array.isArray(src.species) ? src.species : [];
    var species = [];
    var seen = Object.create(null);
    function addSpecies(name, icon, greatOne) {
      if (!name || seen[name]) return;
      seen[name] = true;
      species.push({ name: name, icon: icon || null, greatOne: !!greatOne, count: 0 });
    }
    for (var s = 0; s < speciesSrc.length; s++) {
      var sp = speciesSrc[s];
      if (!sp || typeof sp !== "object") continue;
      addSpecies(str(sp.name), str(sp.icon), sp.great_one);
    }
    for (var k = 0; k < animals.length; k++) addSpecies(animals[k].species, null, false);
    var byName = Object.create(null);
    for (var q = 0; q < species.length; q++) byName[species[q].name] = species[q];
    for (var c = 0; c < animals.length; c++) {
      var target = byName[animals[c].species];
      if (target) target.count++;
    }

    return {
      schema: fin(src.schema),
      generatedAt: str(src.generated_at),
      reserve: reserve,
      world: { minX: minX, maxX: maxX, minY: minY, maxY: maxY },
      species: species,
      animals: animals
    };
  }

  function normaliseZones(raw, fallbackWorld) {
    var src = raw && typeof raw === "object" ? raw : {};
    var reserveRaw = src.reserve && typeof src.reserve === "object" ? src.reserve : {};
    var zonesSrc = Array.isArray(src.zones) ? src.zones : [];
    var world;

    var worldSrc = src.world && typeof src.world === "object" ? src.world : {};
    var minX = fin(worldSrc.min_x), maxX = fin(worldSrc.max_x);
    var minY = fin(worldSrc.min_y), maxY = fin(worldSrc.max_y);
    var hasWorld = minX != null && maxX != null && minY != null && maxY != null && maxX > minX && maxY > minY;

    var zones = [];
    var dropped = 0;
    var bx0 = Infinity, bx1 = -Infinity, by0 = Infinity, by1 = -Infinity;

    for (var i = 0; i < zonesSrc.length; i++) {
      var z = zonesSrc[i];
      if (!z || typeof z !== "object") { dropped++; continue; }

      /* (x, z) are the map axes. `altitude` is a separate axis and is ignored
         here on purpose; `y` is only accepted as a legacy fallback for z. */
      var x = fin(z.x);
      var zz = fin(z.z);
      if (zz == null) zz = fin(z.y);
      if (x == null || zz == null) { dropped++; continue; }

      var type = str(z.type);
      if (type) {
        type = type.toLowerCase();
        if (type === "food") type = "feed";
        if (type === "water") type = "drink";
      }
      if (TYPES.indexOf(type) < 0) {
        type = NEED_TYPE[fin(z.need_type)] || null;
      }
      if (!type) type = "rest";        // unknown types still get drawn, conservatively

      var start = clampHour(fin(z.start_hour));
      var end = clampHour(fin(z.end_hour));

      zones.push({
        x: x,
        z: zz,
        altitude: fin(z.altitude),
        type: type,
        typeRaw: str(z.type),
        needType: fin(z.need_type),
        start: start,
        end: end,
        hash: str(z.animal_type_hash) || (fin(z.animal_type_hash) != null
          ? ("0000000" + (fin(z.animal_type_hash) >>> 0).toString(16).toUpperCase()).slice(-8)
          : null),
        animal: str(z.animal_type),
        rosterName: null,          // resolved against the scanned roster at boot
        inScope: true,             // passes the species facet
        dim: false,                // drawn hollow/dimmed (unknown species + filter on)
        active: true
      });

      if (x < bx0) bx0 = x;
      if (x > bx1) bx1 = x;
      if (zz < by0) by0 = zz;
      if (zz > by1) by1 = zz;
    }

    /* Per-reserve box: use the delivered one, else derive it from this
       reserve's own zones (never borrow another reserve's box). */
    if (hasWorld) {
      world = { minX: minX, maxX: maxX, minY: minY, maxY: maxY };
    } else if (isFinite(bx0) && bx1 > bx0 && by1 > by0) {
      var padX = (bx1 - bx0) * 0.06 + 1;
      var padY = (by1 - by0) * 0.06 + 1;
      world = { minX: bx0 - padX, maxX: bx1 + padX, minY: by0 - padY, maxY: by1 + padY };
    } else if (fallbackWorld) {
      world = fallbackWorld;
    } else {
      world = { minX: -8192, maxX: 8192, minY: -8192, maxY: 8192 };
    }

    return {
      reserve: {
        index: fin(reserveRaw.index),
        name: str(reserveRaw.name),
        confidence: str(reserveRaw.confidence)
      },
      world: world,
      zones: zones,
      dropped: dropped
    };
  }

  function mapSrc(path) {
    if (!path) return "assets/maps/map.png";
    if (/^(?:https?:|data:|blob:|\/)/i.test(path)) return path;
    if (/\.[a-z0-9]{2,5}$/i.test(path)) return path;
    return "assets/maps/" + path;
  }

  function iconSrc(slug) {
    if (!slug) return null;
    if (/\.[a-z0-9]{2,5}$/i.test(slug)) {
      return slug.indexOf("/") >= 0 ? slug : "assets/icons/" + slug;
    }
    if (slug.indexOf("/") >= 0) return slug;
    return "assets/icons/" + slug.charAt(0).toUpperCase() + slug.slice(1) + "_frame.png";
  }

  /* ======================================================================== *
   * 6. Filters
   * ======================================================================== */

  function defaultFilters(speciesList) {
    var sp = Object.create(null);
    for (var i = 0; i < speciesList.length; i++) sp[speciesList[i].name] = true;
    var med = Object.create(null);
    for (var m = 0; m < MEDALS.length; m++) med[MEDALS[m]] = true;
    var fur = Object.create(null);
    for (var f = 0; f < FUR_TIERS.length; f++) fur[FUR_TIERS[f]] = true;
    var zt = Object.create(null);
    for (var ti = 0; ti < TYPES.length; ti++) zt[TYPES[ti]] = true;
    return {
      species: sp,
      medals: med,
      furs: fur,
      zoneTypes: zt,
      gender: "all",
      hideScripted: false,
      hideGreatOnes: false,
      search: ""
    };
  }

  function furBucket(a) { return a.furRarity || "common"; }

  function basePass(a, f) {
    if (f.gender !== "all" && a.gender !== f.gender) return false;
    if (f.hideScripted && a.scripted) return false;
    if (f.hideGreatOnes && a.medal === "great_one") return false;
    return true;
  }

  /* ── population facet ───────────────────────────────────────────────────── */

  function applyPopulationFilters() {
    var f = state.filters;
    var speciesCounts = Object.create(null);
    var medalCounts = Object.create(null);
    var furCounts = Object.create(null);
    var filtered = [];

    for (var i = 0; i < state.animals.length; i++) {
      var a = state.animals[i];
      var base = basePass(a, f);
      var bySpecies = f.species[a.species] === true;
      var byMedal = f.medals[a.medal] === true;
      var byFur = f.furs[furBucket(a)] === true;

      if (base && byMedal && byFur) speciesCounts[a.species] = (speciesCounts[a.species] || 0) + 1;
      if (base && bySpecies && byFur) medalCounts[a.medal] = (medalCounts[a.medal] || 0) + 1;
      if (base && bySpecies && byMedal) {
        var fb = furBucket(a);
        furCounts[fb] = (furCounts[fb] || 0) + 1;
      }
      if (base && bySpecies && byMedal && byFur) filtered.push(a);
    }

    state.filtered = filtered;
    state.counts.species = speciesCounts;
    state.counts.medals = medalCounts;
    state.counts.furs = furCounts;

    renderSpeciesCounts();
    renderMedalCounts();
    renderFurCounts();
    renderList(true);
    renderSummary();
    renderBadges();
    /* The planner panels follow whichever single species is ticked. */
    if (typeof renderHours === "function") renderHours();
    if (typeof renderCompare === "function") renderCompare();
    saveFilters();
  }

  /* ── helpers shared by both layers ──────────────────────────────────────── */

  /** Species drives BOTH layers: the animal list and the need zones. */
  function applySpeciesFilters() {
    applyPopulationFilters();
    applyZoneFilters();
    renderBadges();
    renderSpeciesSummary();
  }

  function renderSpeciesSummary() {
    var f = state.filters;
    var selected = 0;
    for (var i = 0; i < state.species.length; i++) {
      if (f.species[state.species[i].name]) selected++;
    }
    els.speciesTotal.textContent = selected + "/" + state.species.length;
    els.speciesTotal.title = t("{n} of {total} species selected — applies to the list and the map",
      { n: selected, total: state.species.length });
  }

  function activeFilterCount() {
    var f = state.filters;
    var n = 0;
    var allSpecies = true, allMedals = true, allFurs = true, allZoneTypes = true;
    for (var i = 0; i < state.species.length; i++) if (!f.species[state.species[i].name]) allSpecies = false;
    for (var m = 0; m < MEDALS.length; m++) if (!f.medals[MEDALS[m]]) allMedals = false;
    for (var u = 0; u < FUR_TIERS.length; u++) if (!f.furs[FUR_TIERS[u]]) allFurs = false;
    for (var ti = 0; ti < TYPES.length; ti++) if (!f.zoneTypes[TYPES[ti]]) allZoneTypes = false;
    if (!allSpecies) n++;
    if (!allMedals) n++;
    if (!allFurs) n++;
    if (!allZoneTypes) n++;
    if (f.gender !== "all") n++;
    if (f.hideScripted) n++;
    if (f.hideGreatOnes) n++;
    return n;
  }

  /* ── zone facet + hour ──────────────────────────────────────────────────── */

  function computeSpeciesFilterActive() {
    var f = state.filters;
    for (var i = 0; i < state.species.length; i++) {
      if (!f.species[state.species[i].name]) return true;
    }
    return false;
  }

  function applyZoneFilters() {
    var f = state.filters;
    var speciesActive = computeSpeciesFilterActive();
    var counts = { feed: 0, drink: 0, rest: 0 };
    var visible = [];

    for (var i = 0; i < state.zones.length; i++) {
      var z = state.zones[i];

      /* Species filter, applied to the zone layer as well.
         Zones whose animal type is unknown (null, or a species missing from the
         scanned roster) are deliberately KEPT and drawn hollow/dimmed instead of
         being dropped: silently hiding an unattributed hotspot would be worse
         than showing it as uncertain. */
      var attributed = !!(z.animal && z.rosterName);
      var inScope = !speciesActive || !attributed || f.species[z.rosterName] === true;
      z.inScope = inScope;
      z.dim = speciesActive && !attributed;

      if (!inScope) continue;
      counts[z.type]++;
      if (f.zoneTypes[z.type]) visible.push(z);
    }

    state.visibleZones = visible;
    state.speciesFilterActive = speciesActive;
    state.counts.zones = counts;
    renderZoneCounts();
    updateHour(state.hour);
    renderMapEmpty();
    saveFilters();
  }

  function updateHour(hour, persist) {
    var h = clamp(hour, 0, 24);
    state.hour = h;

    /* Activeness is computed for every zone so the sidebar counts stay right
       even for zones the type filter currently hides. */
    var activeByType = { feed: 0, drink: 0, rest: 0 };
    for (var i = 0; i < state.zones.length; i++) {
      var z = state.zones[i];
      z.active = isActiveAt(z, h);
      if (z.inScope && z.active) activeByType[z.type]++;
    }

    var active = 0;
    var side = state.visibleZones;
    for (var j = 0; j < side.length; j++) if (side[j].active) active++;

    state.activeCount = active;
    state.activeByType = activeByType;

    var label = formatHour(h);
    els.hourReadout.textContent = label;
    if (els.hourSlider.value !== String(h)) els.hourSlider.value = String(h);
    els.hourSlider.setAttribute("aria-valuetext", label);
    els.activeCount.textContent = String(active);
    els.zoneCount.textContent = String(side.length);
    els.timebarCount.classList.toggle("is-zero", active === 0);

    updateZoneRowTitles();
    if (persist !== false) {
      try { localStorage.setItem(STORE_HOUR, String(h)); } catch (e) { /* ignore */ }
    }
    scheduleDraw();
  }

  /* ======================================================================== *
   * 7. Sidebar UI
   * ======================================================================== */

  function makeCheckRow(kind, value, labelText) {
    var row = el("label", "check");
    row.dataset.kind = kind;
    row.dataset.value = value;
    row.dataset.countKey = value;

    var input = el("input");
    input.type = "checkbox";
    input.checked = true;
    input.value = value;
    input.setAttribute("aria-label", labelText);

    var box = el("span", "box");
    box.setAttribute("aria-hidden", "true");
    box.appendChild(svgIcon("i-check"));

    row.appendChild(input);
    row.appendChild(box);
    return row;
  }

  function buildZoneTypeList() {
    els.zoneTypeList.textContent = "";
    var frag = document.createDocumentFragment();
    TYPES.forEach(function (type) {
      var row = makeCheckRow("zone", type, TYPE_LABEL[type]);
      var glyph = el("i", "zglyph");
      glyph.dataset.zone = type;
      glyph.setAttribute("aria-hidden", "true");
      row.appendChild(glyph);
      row.appendChild(el("span", "label", TYPE_LABEL[type]));
      row.appendChild(el("span", "count", "0"));
      frag.appendChild(row);
    });
    els.zoneTypeList.appendChild(frag);
  }

  function buildSpeciesList() {
    els.speciesList.textContent = "";
    var frag = document.createDocumentFragment();
    state.species.forEach(function (sp) {
      var row = makeCheckRow("species", sp.name, sp.name);
      var icon = iconSrc(sp.icon);
      var thumb;
      if (icon) {
        thumb = new Image(21, 21);
        thumb.className = "sp-ico";
        thumb.alt = "";
        thumb.loading = "lazy";
        thumb.decoding = "async";
        thumb.src = icon;
        thumb.addEventListener("error", function () {
          if (!thumb.parentNode) return;
          var letter = el("span", "sp-ico", sp.name.charAt(0));
          letter.style.display = "grid";
          letter.style.placeItems = "center";
          letter.style.fontSize = "0.7rem";
          letter.style.fontWeight = "700";
          letter.style.color = "var(--dim)";
          thumb.parentNode.replaceChild(letter, thumb);
        }, { once: true });
      } else {
        thumb = el("span", "sp-ico", sp.name.charAt(0));
        thumb.style.display = "grid";
        thumb.style.placeItems = "center";
        thumb.style.fontSize = "0.7rem";
        thumb.style.fontWeight = "700";
        thumb.style.color = "var(--dim)";
      }
      row.appendChild(thumb);
      row.appendChild(el("span", "label", sp.name));
      row.appendChild(el("span", "count", "0"));
      frag.appendChild(row);
    });
    els.speciesList.appendChild(frag);
  }

  function buildMedalList() {
    els.medalList.textContent = "";
    var frag = document.createDocumentFragment();
    MEDALS.forEach(function (m) {
      var row = makeCheckRow("medal", m, MEDAL_LABEL[m]);
      var glyph = el("i", "glyph");
      glyph.dataset.medal = m;
      glyph.setAttribute("aria-hidden", "true");
      row.appendChild(glyph);
      row.appendChild(el("span", "label", MEDAL_LABEL[m]));
      row.appendChild(el("span", "count", "0"));
      frag.appendChild(row);
    });
    els.medalList.appendChild(frag);
  }

  function buildFurList() {
    els.furList.textContent = "";
    var frag = document.createDocumentFragment();
    FUR_TIERS.forEach(function (tier) {
      var row = makeCheckRow("fur", tier, FUR_LABEL[tier]);
      var dot = el("i", "fur-dot");
      dot.dataset.fur = tier;
      dot.setAttribute("aria-hidden", "true");
      dot.style.width = "10px";
      dot.style.height = "10px";
      dot.style.flex = "none";
      dot.style.borderRadius = "50%";
      dot.style.margin = "0 5px 0 3px";
      var furVar = {
        rare: "--fur-rare",
        very_rare: "--fur-very-rare",
        super_rare: "--fur-super-rare",
        great_one: "--fur-great-one"
      }[tier];
      dot.style.background = furVar ? "var(" + furVar + ")" : "var(--faint)";
      if (!FUR_HALO[tier]) dot.style.opacity = tier === "uncommon" ? "0.7" : "0.5";
      row.appendChild(dot);
      row.appendChild(el("span", "label", FUR_LABEL[tier]));
      row.appendChild(el("span", "count", "0"));
      frag.appendChild(row);
    });
    els.furList.appendChild(frag);
  }

  function eachRow(container, cb) {
    var rows = container.querySelectorAll(".check");
    for (var i = 0; i < rows.length; i++) cb(rows[i], rows[i].dataset.value, rows[i].querySelector(".count"));
  }

  function renderSpeciesCounts() {
    eachRow(els.speciesList, function (row, name, countEl) {
      var n = state.counts.species[name] || 0;
      countEl.textContent = String(n);
      row.classList.toggle("is-zero", n === 0);
    });
  }
  function renderMedalCounts() {
    eachRow(els.medalList, function (row, name, countEl) {
      var n = state.counts.medals[name] || 0;
      countEl.textContent = String(n);
      row.classList.toggle("is-zero", n === 0);
    });
  }
  function renderFurCounts() {
    eachRow(els.furList, function (row, name, countEl) {
      var n = state.counts.furs[name] || 0;
      countEl.textContent = String(n);
      row.classList.toggle("is-zero", n === 0);
    });
  }
  function renderZoneCounts() {
    eachRow(els.zoneTypeList, function (row, type, countEl) {
      var n = state.counts.zones[type] || 0;
      countEl.textContent = String(n);
      row.classList.toggle("is-zero", n === 0);
    });
    els.zoneTotal.textContent = String(state.zones.length);
    els.popTotal.textContent = String(state.animals.length);
  }

  /**
   * Medal tiers with no animals in this scan (bronze, today, because the backend
   * has no reliable bronze cut-off) are hidden instead of showing a dead "0"
   * filter row. Legend entries follow the same rule.
   */
  function applyMedalAvailability() {
    var totals = { great_one: 0, diamond: 0, gold: 0, silver: 0, bronze: 0, none: 0 };
    for (var i = 0; i < state.animals.length; i++) {
      var m = state.animals[i].medal;
      if (totals[m] == null) totals[m] = 0;
      totals[m]++;
    }
    eachRow(els.medalList, function (row, medal) {
      var empty = (totals[medal] || 0) === 0;
      row.hidden = empty;
      row.title = empty
        ? t("No “{medal}” animals in this scan", { medal: MEDAL_LABEL[medal] })
        : "";
    });
    var legendItems = els.legend ? els.legend.querySelectorAll(".legend-medals .glyph") : [];
    for (var k = 0; k < legendItems.length; k++) {
      var tier = legendItems[k].dataset.medal;
      legendItems[k].parentNode.hidden = (totals[tier] || 0) === 0;
    }
  }

  function updateZoneRowTitles() {
    eachRow(els.zoneTypeList, function (row, type) {
      var active = (state.activeByType && state.activeByType[type]) || 0;
      var total = state.counts.zones[type] || 0;
      row.title = t("{active} of {total} active at {hour}",
        { active: active, total: total, hour: formatHour(state.hour) });
    });
  }

  function bindFilterInputs() {
    els.sidebar.addEventListener("change", function (e) {
      var input = e.target;
      if (!(input instanceof HTMLInputElement)) return;

      if (input.type === "checkbox") {
        var row = input.closest(".check");
        if (row) {
          var kind = row.dataset.kind;
          var value = row.dataset.value;
          if (kind === "zone") {
            state.filters.zoneTypes[value] = input.checked;
            applyZoneFilters();
            renderBadges();
          } else if (kind === "species") {
            state.filters.species[value] = input.checked;
            applySpeciesFilters();
          } else if (kind === "medal") {
            state.filters.medals[value] = input.checked;
            applyPopulationFilters();
            renderBadges();
          } else if (kind === "fur") {
            state.filters.furs[value] = input.checked;
            applyPopulationFilters();
            renderBadges();
          }
          return;
        }
        if (input.id === "hideScripted") {
          state.filters.hideScripted = input.checked;
          applyPopulationFilters();
          renderBadges();
          return;
        }
        if (input.id === "hideGreatOnes") {
          state.filters.hideGreatOnes = input.checked;
          applyPopulationFilters();
          renderBadges();
          return;
        }
      }
    });

    els.genderSegment.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-gender]");
      if (btn) setGender(btn.dataset.gender);
    });

    els.sidebar.querySelectorAll("[data-species-action]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var all = btn.dataset.speciesAction === "all";
        state.species.forEach(function (sp) { state.filters.species[sp.name] = all; });
        syncFilterInputs();
        applySpeciesFilters();
      });
    });
    els.sidebar.querySelectorAll("[data-medal-action]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var all = btn.dataset.medalAction === "all";
        MEDALS.forEach(function (m) { state.filters.medals[m] = all; });
        syncFilterInputs();
        applyPopulationFilters();
        renderBadges();
      });
    });
    els.sidebar.querySelectorAll("[data-fur-action]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var all = btn.dataset.furAction === "all";
        FUR_TIERS.forEach(function (tier) { state.filters.furs[tier] = all; });
        syncFilterInputs();
        applyPopulationFilters();
        renderBadges();
      });
    });
    els.sidebar.querySelectorAll("[data-zone-action]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var all = btn.dataset.zoneAction === "all";
        TYPES.forEach(function (zoneType) { state.filters.zoneTypes[zoneType] = all; });
        syncFilterInputs();
        applyZoneFilters();
        renderBadges();
      });
    });

    els.btnResetFilters.addEventListener("click", resetFilters);
    els.btnEmptyClear.addEventListener("click", function () {
      TYPES.forEach(function (zoneType) { state.filters.zoneTypes[zoneType] = true; });
      syncFilterInputs();
      applyZoneFilters();
      renderBadges();
    });

    els.speciesSearch.addEventListener("input", function () {
      state.filters.search = els.speciesSearch.value;
      filterSpeciesRows();
    });
    els.btnClearSearch.addEventListener("click", function () {
      els.speciesSearch.value = "";
      state.filters.search = "";
      filterSpeciesRows();
      els.speciesSearch.focus();
    });

    els.genderSegment.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      var order = ["all", "male", "female"];
      var idx = order.indexOf(state.filters.gender);
      if (e.key === "ArrowRight") idx = (idx + 1) % order.length;
      else idx = (idx + order.length - 1) % order.length;
      setGender(order[idx]);
      var next = els.genderSegment.querySelector('[data-gender="' + order[idx] + '"]');
      if (next) next.focus();
      e.preventDefault();
    });
  }

  function setGender(g) {
    if (state.filters.gender === g) return;
    state.filters.gender = g;
    syncFilterInputs();
    applyPopulationFilters();
    renderBadges();
  }

  function syncFilterInputs() {
    var f = state.filters;
    eachRow(els.zoneTypeList, function (row, type) {
      var input = row.querySelector("input");
      if (input) input.checked = f.zoneTypes[type] === true;
    });
    eachRow(els.speciesList, function (row, name) {
      var input = row.querySelector("input");
      if (input) input.checked = f.species[name] === true;
    });
    eachRow(els.medalList, function (row, name) {
      var input = row.querySelector("input");
      if (input) input.checked = f.medals[name] === true;
    });
    eachRow(els.furList, function (row, name) {
      var input = row.querySelector("input");
      if (input) input.checked = f.furs[name] === true;
    });
    els.hideScripted.checked = f.hideScripted;
    els.hideGreatOnes.checked = f.hideGreatOnes;
    els.genderSegment.querySelectorAll("[data-gender]").forEach(function (btn) {
      var on = btn.dataset.gender === f.gender;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-checked", on ? "true" : "false");
    });
    var n = activeFilterCount();
    els.btnResetFilters.disabled = n === 0;
    els.btnResetFilters.style.opacity = n === 0 ? "0.5" : "";
    renderSpeciesSummary();
  }

  function filterSpeciesRows() {
    var q = els.speciesSearch.value.trim().toLowerCase();
    var shown = 0;
    eachRow(els.speciesList, function (row, name) {
      var match = !q || name.toLowerCase().indexOf(q) >= 0;
      row.hidden = !match;
      if (match) shown++;
    });
    els.speciesEmpty.hidden = shown > 0;
    setSpeciesEmptyTerm(els.speciesSearch.value.trim());
    els.btnClearSearch.hidden = els.speciesSearch.value === "";
    saveFilters();
  }

  /** "No species match “<b>term</b>”." — the term stays real markup, the rest is
     translated, and the quote marks come from the translation itself. */
  function setSpeciesEmptyTerm(term) {
    var parts = window.I18N
      ? window.I18N.split("No species match “{term}”.", "term")
      : ["No species match “", "”."];
    els.speciesEmptyLead.textContent = parts[0];
    els.speciesEmptyTerm.textContent = term;
    els.speciesEmptyTail.textContent = parts[1];
  }

  function resetFilters() {
    state.filters = defaultFilters(state.species);
    els.speciesSearch.value = "";
    els.btnClearSearch.hidden = true;
    filterSpeciesRows();
    syncFilterInputs();
    applyPopulationFilters();
    applyZoneFilters();
    renderBadges();
    renderSpeciesSummary();
  }

  /* ======================================================================== *
   * 8. Summary, badges, empty states
   * ======================================================================== */

  function renderSummary() {
    var list = state.filtered;
    var diamonds = 0, greatOnes = 0, rareFurs = 0;
    var byMedal = { great_one: 0, diamond: 0, gold: 0, silver: 0, bronze: 0, none: 0 };
    for (var i = 0; i < list.length; i++) {
      var m = list[i].medal;
      if (byMedal[m] == null) byMedal[m] = 0;
      byMedal[m]++;
      if (m === "great_one") greatOnes++;
      else if (m === "diamond") diamonds++;
      if (list[i].furRarity && FUR_HALO[list[i].furRarity]) rareFurs++;
    }

    var line = els.summaryLine;
    line.textContent = "";

    var main = el("span", "sum-main");
    main.appendChild(el("b", null, thousands(list.length)));
    main.appendChild(document.createTextNode(" " + plural(list.length, t("animal"), t("animals"))));
    line.appendChild(main);

    function item(cls, value, label) {
      line.appendChild(el("span", "sum-sep", "\u00a0\u00b7\u00a0"));
      var wrap = el("span", "sum-item");
      if (cls === "diamond") {
        var mark = el("span", "sum-mark");
        mark.dataset.medal = "diamond";
        wrap.appendChild(mark);
      } else if (cls === "great_one") {
        var glow = el("span", "sum-mark");
        glow.dataset.medal = "great_one";
        wrap.appendChild(glow);
      } else if (cls === "fur") {
        wrap.appendChild(el("span", "sum-furmark"));
      }
      wrap.appendChild(el("b", null, thousands(value)));
      wrap.appendChild(document.createTextNode(" " + label));
      line.appendChild(wrap);
    }

    item("diamond", diamonds, plural(diamonds, t("diamond"), t("diamonds")));
    item("great_one", greatOnes, plural(greatOnes, t("great one"), t("great ones")));
    item("fur", rareFurs, plural(rareFurs, t("rare fur"), t("rare furs")));

    if (state.animals.length && list.length !== state.animals.length) {
      line.appendChild(el("span", "sum-note",
        t("{n} of {total}", { n: list.length, total: state.animals.length })));
    }

    if (list.length) {
      var strip = el("span", "sum-dist");
      strip.setAttribute("aria-hidden", "true");
      var title = [];
      for (var q = 0; q < MEDALS.length; q++) {
        var key = MEDALS[q];
        if (!byMedal[key]) continue;
        var seg = el("i");
        seg.dataset.medal = key;
        seg.style.flexGrow = String(byMedal[key]);
        if (seg.style) strip.appendChild(seg);
        title.push(byMedal[key] + " " + MEDAL_LABEL[key].toLowerCase());
      }
      strip.title = title.join(" \u00b7 ");
      line.appendChild(strip);
    }
  }

  function renderBadges() {
    var n = activeFilterCount();
    [els.filterBadge, els.tabFiltersCount].forEach(function (badge) {
      if (!badge) return;
      badge.textContent = String(n);
      badge.hidden = n === 0;
    });
    var total = state.filtered.length;
    els.listCount.textContent = String(total);
    els.tabAnimalsCount.textContent = String(total);
    renderSpawnBadge();
  }

  /* ── animals that just spawned ────────────────────────────────────────────
   * The save stores no spawn timestamp, so "new" can only come from a diff: the
   * server watcher compares two scans of the population file and reports what
   * appeared (identity = VisualVariationSeed, since Id is always 0). It keeps the
   * last batch that contained newcomers, and the list paints those rows green
   * until a newer batch replaces them.
   * ---------------------------------------------------------------------- */

  function spawnKey(species, seed) {
    return String(species) + "\u0000" + String(seed);
  }

  function isNewSpawn(animal) {
    if (animal.seed == null) return false;
    return !!state.newSpawns[spawnKey(animal.species, animal.seed)];
  }

  /** "Spawned 30 oct., 21:03" — the only honest timestamp we have: when the save
   *  was first seen carrying that animal. `ms` is that animal's own time. */
  function spawnTitle(ms) {
    var stamp = ms || state.spawnAt;
    if (!stamp) return t("New");
    var when;
    try {
      when = new Date(stamp).toLocaleString(
        window.I18N ? window.I18N.dateLocale() : undefined,
        { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
    } catch (err) {
      when = new Date(stamp).toISOString().slice(11, 16);
    }
    return t("Spawned {when}", { when: when });
  }

  function applySpawns(spawns) {
    var next = Object.create(null);
    var batchAt = spawns && typeof spawns.at === "number" && spawns.at > 0 ? spawns.at * 1000 : 0;
    var rows = (spawns && spawns.animals) || [];
    var reserve = state.reserve ? state.reserve.index : null;
    var newest = 0;
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (!row || row.seed == null) continue;
      /* The watcher covers every reserve; this page shows one. */
      if (reserve != null && row.reserve != null && row.reserve !== reserve) continue;
      /* Each record carries its own spawn time (the shortlist mixes several scans). */
      var at = typeof row.seen_at === "number" && row.seen_at > 0 ? row.seen_at * 1000 : batchAt;
      next[spawnKey(row.species, row.seed)] = at;
      if (at > newest) newest = at;
    }
    var changed = Object.keys(next).length !== Object.keys(state.newSpawns).length;
    if (!changed) {
      for (var key in next) {
        if (!(key in state.newSpawns)) { changed = true; break; }
      }
    }
    state.newSpawns = next;
    state.spawnAt = newest || batchAt;
    if (changed) {
      /* Restyle the rows on screen; the selection and the scroll position stay put. */
      renderListWindow(true);
      renderSpawnBadge();
    }
  }

  function renderSpawnBadge() {
    if (!els.listNew || !els.listNewText) return;
    var n = 0;
    for (var i = 0; i < state.filtered.length; i++) {
      if (isNewSpawn(state.filtered[i])) n++;
    }
    els.listNew.hidden = n === 0;
    if (!n) return;
    els.listNewText.textContent = n === 1
      ? t("{n} new animal", { n: n })
      : t("{n} new animals", { n: n });
    els.listNew.title = spawnTitle();
  }

  /* ── "where are my saves?" ────────────────────────────────────────────────
   * The save folder is the one thing the app cannot guess on every machine
   * (Documents is often redirected to OneDrive). When the server reports that it
   * found none, this panel takes over the map area: one field, one button, and the
   * list of folders that were searched, so the user can fix it without a terminal.
   * ─────────────────────────────────────────────────────────────────────────── */

  function paintSetup() {
    if (!els.setupPanel) return;
    els.setupPanel.hidden = !state.needsSetup;
    if (!state.needsSetup) return;
    if (els.mapEmpty) els.mapEmpty.hidden = true;
    if (els.mapLoading) els.mapLoading.hidden = true;
    els.saveDirSearched.textContent = "";
    var roots = (state.app && state.app.searched) || [];
    for (var i = 0; i < roots.length; i++) {
      els.saveDirSearched.appendChild(el("li", null, roots[i]));
    }
  }

  function showSetupError(message) {
    if (!els.saveDirError) return;
    els.saveDirError.textContent = message;
    els.saveDirError.hidden = false;
  }

  /** The server answers in English on purpose (it is shared by the CLI); translate the
   *  three cases a user can actually hit. */
  function setupErrorText(err) {
    var raw = (err && err.message) || "";
    if (/does not exist/.test(raw)) return t("That folder does not exist.");
    if (/no animal_population_/.test(raw)) {
      return t("There is no animal_population_* file in that folder, or in the folder inside it.");
    }
    if (/empty path/.test(raw)) return t("Paste the folder path first.");
    return t("That folder was refused.") + (raw ? " (" + raw + ")" : "");
  }

  function bindSetup() {
    if (!els.saveDirApply) return;

    function apply() {
      var path = els.saveDirInput.value.trim();
      els.saveDirError.hidden = true;
      if (!path) {
        showSetupError(t("Paste the folder path first."));
        return;
      }
      els.saveDirApply.disabled = true;
      postJson("/api/save-dir", { path: path })
        .then(function () {
          els.saveDirApply.textContent = t("Folder accepted — reloading…");
          window.location.reload();
        })
        .catch(function (err) {
          els.saveDirApply.disabled = false;
          showSetupError(setupErrorText(err));
        });
    }

    els.saveDirApply.addEventListener("click", apply);
    els.saveDirInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        apply();
      }
    });
  }

  function renderMapEmpty() {
    /* The setup panel owns the map area while the save folder is unknown. */
    if (state.needsSetup) {
      els.mapEmpty.hidden = true;
      return;
    }
    var visible = state.visibleZones.length;
    els.mapEmpty.hidden = visible > 0;
    if (visible > 0) return;

    if (state.zoneMode === "missing") {
      els.emptyTitle.textContent = t("Need zones unavailable");
      els.emptyText.textContent = t("The zone endpoint did not answer. The reserve map and the population list are still shown.");
      els.btnEmptyClear.hidden = true;
      return;
    }
    if (state.zones.length === 0) {
      els.emptyTitle.textContent = t("No need zones found");
      els.emptyText.textContent = t("Discover food, water and rest spots in game, then scan again — they will appear here.");
      els.btnEmptyClear.hidden = true;
      return;
    }
    var anyInScope = false;
    for (var i = 0; i < state.zones.length; i++) {
      if (state.zones[i].inScope) { anyInScope = true; break; }
    }
    if (state.speciesFilterActive && !anyInScope) {
      els.emptyTitle.textContent = t("No zones for the selected species");
      els.emptyText.textContent = t("These species have no discovered need zones on this reserve yet. Widen the species filter to see the rest.");
      els.btnEmptyClear.hidden = true;
      return;
    }
    els.emptyTitle.textContent = t("All zone types are hidden");
    els.emptyText.textContent = t("Enable feed, drink or rest zones in the filters to see them again.");
    els.btnEmptyClear.hidden = false;
  }

  function renderListEmpty() {
    var empty = state.filtered.length === 0;
    els.listEmpty.hidden = !empty;
    if (!empty) return;
    els.listEmptyText.textContent = state.animals.length === 0
      ? t("No animals in this reserve.")
      : t("No animals match the current filters.");
  }

  /* ======================================================================== *
   * 9. Population list (virtualised: 4 000+ rows must scroll smoothly)
   * ======================================================================== */

  function sortValue(a, key) {
    switch (key) {
      case "weight": return a.weight;
      case "score": return a.score;
      case "trophy": return a.trophy;
      case "medal": return MEDAL_Z[a.medal];
      default: return a.species;
    }
  }

  function compareAnimals(a, b) {
    var key = state.sort.key;
    var dir = state.sort.dir === "asc" ? 1 : -1;
    var va = sortValue(a, key);
    var vb = sortValue(b, key);
    var aNull = va == null || (typeof va === "number" && !isFinite(va));
    var bNull = vb == null || (typeof vb === "number" && !isFinite(vb));
    if (aNull && bNull) return a.id < b.id ? -1 : 1;
    if (aNull) return 1;
    if (bNull) return -1;
    var r;
    if (typeof va === "string") r = va.localeCompare(vb);
    else r = va < vb ? -1 : va > vb ? 1 : 0;
    if (r === 0) return a.id < b.id ? -1 : 1;
    return r * dir;
  }

  function iconElement(a) {
    var wrap = el("span", "row-ico");
    var src = iconSrc(a.icon);
    if (src) {
      var img = new Image(26, 26);
      img.alt = "";
      img.loading = "lazy";
      img.decoding = "async";
      img.src = src;
      img.addEventListener("error", function () {
        if (!img.parentNode) return;
        img.parentNode.replaceChild(el("span", "row-letter", a.species.charAt(0)), img);
      }, { once: true });
      wrap.appendChild(img);
    } else {
      wrap.appendChild(el("span", "row-letter", a.species.charAt(0)));
    }
    return wrap;
  }

  function buildRow(a) {
    var li = el("li", "animal-row");
    li.dataset.id = a.id;
    var fresh = isNewSpawn(a);
    if (fresh) {
      li.classList.add("is-new");
      li.title = spawnTitle(state.newSpawns[spawnKey(a.species, a.seed)]);
    }

    li.appendChild(iconElement(a));

    var main = el("div", "row-main");
    var top = el("div", "row-top");
    top.appendChild(el("span", "row-species", a.species));
    if (fresh) {
      var dot = el("i", "row-new");
      dot.setAttribute("aria-hidden", "true");
      dot.title = t("New");
      top.appendChild(dot);
    }
    top.appendChild(el("span", "row-sex", SEX_GLYPH[a.gender] || "?"));
    if (a.fur) {
      var fur = el("span", "row-fur", a.fur);
      fur.dataset.fur = a.furRarity || "common";
      fur.title = a.fur + (a.furRarity ? " \u00b7 " + FUR_LABEL[a.furRarity] : "");
      top.appendChild(fur);
    }
    if (a.scripted) {
      var flag = el("span", "row-flag", "S");
      flag.title = t("Scripted animal");
      top.appendChild(flag);
    }
    main.appendChild(top);

    var sub = el("div", "row-sub");
    var glyph = el("i", "glyph");
    glyph.dataset.medal = a.medal;
    glyph.setAttribute("aria-hidden", "true");
    sub.appendChild(glyph);
    var medalName = el("span", "row-medal-name", medalText(a));
    if (a.medalSource === "relative") {
      medalName.title = t("Percentile within this reserve — no per-species trophy thresholds for this species");
    }
    sub.appendChild(medalName);
    sub.appendChild(el("span", "row-sep", "\u00b7"));
    sub.appendChild(el("span", null, a.weight == null ? "\u2014 kg" : num(a.weight, 1) + " kg"));
    sub.appendChild(el("span", "row-sep", "\u00b7"));
    sub.appendChild(el("span", null, num(a.score, a.score != null && a.score < 100 ? 2 : 1)));
    if (a.trophy != null) {
      sub.appendChild(el("span", "row-sep", "\u00b7"));
      sub.appendChild(el("span", null, Math.round(a.trophy * 100) + "%"));
    }
    main.appendChild(sub);

    li.appendChild(main);
    li.appendChild(el("span", "row-id", a.id));
    return li;
  }

  function renderList(resetScroll) {
    state.listItems = state.filtered.slice().sort(compareAnimals);
    if (resetScroll) els.listScroll.scrollTop = 0;
    els.animalList.style.height = (state.listItems.length * LIST_ROW_H) + "px";
    state.listStart = -1;
    state.listEnd = -1;
    renderListWindow(true);
    renderListEmpty();
  }

  function renderListWindow(force) {
    var items = state.listItems;
    var n = items.length;
    if (!n) {
      els.animalList.textContent = "";
      state.listStart = state.listEnd = 0;
      return;
    }
    var top = els.listScroll.scrollTop;
    var height = els.listScroll.clientHeight || 600;
    var start = Math.max(0, Math.floor(top / LIST_ROW_H) - 4);
    var end = Math.min(n, Math.ceil((top + height) / LIST_ROW_H) + 4);
    if (!force && start === state.listStart && end === state.listEnd) return;
    state.listStart = start;
    state.listEnd = end;

    var frag = document.createDocumentFragment();
    for (var i = start; i < end; i++) {
      var row = buildRow(items[i]);
      row.style.top = (i * LIST_ROW_H) + "px";
      frag.appendChild(row);
    }
    els.animalList.textContent = "";
    els.animalList.appendChild(frag);
  }

  function onListScroll() {
    if (listRaf) return;
    listRaf = window.requestAnimationFrame(function () {
      listRaf = 0;
      renderListWindow(false);
    });
  }

  function setSort(key) {
    if (!SORT_KEYS[key]) return;
    if (state.sort.key === key) state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
    else {
      state.sort.key = key;
      state.sort.dir = key === "species" ? "asc" : "desc";
    }
    saveSort();
    syncSortBar();
    renderList(true);
  }

  function syncSortBar() {
    els.sortbar.querySelectorAll("[data-sort]").forEach(function (btn) {
      var on = btn.dataset.sort === state.sort.key;
      btn.classList.toggle("is-active", on);
      btn.dataset.dir = on ? state.sort.dir : "";
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.setAttribute("aria-label",
        t("Sort by {key}", { key: SORT_LABEL[btn.dataset.sort] || btn.dataset.sort }) +
        (on ? (state.sort.dir === "asc" ? t(", ascending") : t(", descending")) : ""));
    });
  }

  function saveSort() {
    try { localStorage.setItem(STORE_SORT, state.sort.key + ":" + state.sort.dir); } catch (e) { /* ignore */ }
  }
  function loadSort() {
    try {
      var raw = localStorage.getItem(STORE_SORT);
      if (!raw) return;
      var parts = raw.split(":");
      if (SORT_KEYS[parts[0]] && (parts[1] === "asc" || parts[1] === "desc")) {
        state.sort.key = parts[0];
        state.sort.dir = parts[1];
      }
    } catch (e) { /* ignore */ }
  }
  function loadHour() {
    try {
      var raw = localStorage.getItem(STORE_HOUR);
      var h = fin(raw);
      if (h != null && h >= 0 && h <= 24) return h;
    } catch (e) { /* ignore */ }
    return DEFAULT_HOUR;
  }

  function loadFollowClock() {
    try {
      return localStorage.getItem(STORE_CLOCK) !== "0";
    } catch (e) { /* ignore */ }
    return true;
  }

  /* The filter selection is part of "the view", so it survives a reload — and the
     language switch reloads on purpose. Only the FALSE entries are stored, so a
     species that shows up in a later scan still arrives ticked. */
  function saveFilters() {
    var f = state.filters;
    if (!f) return;
    try {
      localStorage.setItem(STORE_FILTERS, JSON.stringify({
        species: f.species,
        medals: f.medals,
        furs: f.furs,
        zoneTypes: f.zoneTypes,
        gender: f.gender,
        hideScripted: f.hideScripted,
        hideGreatOnes: f.hideGreatOnes,
        search: f.search
      }));
    } catch (e) { /* storage full or blocked: filtering keeps working */ }
  }

  function loadFilters(filters) {
    var saved = null;
    try {
      saved = JSON.parse(localStorage.getItem(STORE_FILTERS) || "null");
    } catch (e) {
      saved = null;
    }
    if (!saved || typeof saved !== "object") return filters;
    ["species", "medals", "furs", "zoneTypes"].forEach(function (kind) {
      var bag = saved[kind];
      if (!bag || typeof bag !== "object") return;
      for (var key in filters[kind]) if (bag[key] === false) filters[kind][key] = false;
    });
    if (saved.gender === "male" || saved.gender === "female" || saved.gender === "all") {
      filters.gender = saved.gender;
    }
    filters.hideScripted = saved.hideScripted === true;
    filters.hideGreatOnes = saved.hideGreatOnes === true;
    if (typeof saved.search === "string") filters.search = saved.search;
    return filters;
  }

  /* ======================================================================== *
   * 10. Camera + projection
   * ======================================================================== */

  function setView(w, h) {
    state.view.w = Math.max(1, w);
    state.view.h = Math.max(1, h);
  }

  function updateProjection() {
    var s = state.cam.scale;
    var w = state.world;
    var img = state.img;
    var kx = s * img.w / (w.maxX - w.minX);
    var ky = s * img.h / (w.maxY - w.minY);
    state.proj.kx = kx;
    state.proj.ky = ky;
    state.proj.flip = Y_AXIS_FLIPPED;
    state.proj.ox = state.cam.tx - w.minX * kx;
    state.proj.oy = Y_AXIS_FLIPPED
      ? state.cam.ty + w.maxY * ky
      : state.cam.ty - w.minY * ky;
  }

  function screenOf(x, z) {
    var p = state.proj;
    return { x: x * p.kx + p.ox, y: p.flip ? p.oy - z * p.ky : z * p.ky + p.oy };
  }

  function worldAt(sx, sy) {
    var p = state.proj;
    if (!p.kx || !p.ky) return { x: 0, z: 0 };
    return {
      x: (sx - p.ox) / p.kx,
      z: p.flip ? (p.oy - sy) / p.ky : (sy - p.oy) / p.ky
    };
  }

  function clampPan(scale, tx, ty) {
    var W = state.img.w * scale;
    var H = state.img.h * scale;
    var vw = state.view.w;
    var vh = state.view.h;
    return {
      tx: W <= vw ? (vw - W) / 2 : clamp(tx, vw - W, 0),
      ty: H <= vh ? (vh - H) / 2 : clamp(ty, vh - H, 0)
    };
  }

  function applyCamera() {
    var pan = clampPan(state.cam.scale, state.cam.tx, state.cam.ty);
    state.cam.tx = pan.tx;
    state.cam.ty = pan.ty;
  }

  function setLimits() {
    var fit = Math.min(state.view.w / state.img.w, state.view.h / state.img.h);
    if (!isFinite(fit) || fit <= 0) fit = 0.1;
    state.cam.fit = fit;
    state.cam.min = Math.max(fit * 0.55, 0.02);
    state.cam.max = Math.min(Math.max(fit * 12, 1.2), 10);
  }

  function fitMap(animate) {
    setLimits();
    var scale = clamp(state.cam.fit, state.cam.min, state.cam.max);
    var tx = (state.view.w - state.img.w * scale) / 2;
    var ty = (state.view.h - state.img.h * scale) / 2;
    if (animate) { animateCamera(scale, tx, ty, 320); return; }
    state.cam.scale = scale;
    state.cam.tx = tx;
    state.cam.ty = ty;
    applyCamera();
    scheduleDraw();
  }

  function fitZones() {
    var zones = state.visibleZones;
    if (!zones.length) { fitMap(true); return; }
    var w = state.world, img = state.img;
    var kx = img.w / (w.maxX - w.minX);
    var ky = img.h / (w.maxY - w.minY);
    var x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (var i = 0; i < zones.length; i++) {
      var z = zones[i];
      var ix = (z.x - w.minX) * kx;
      var iy = Y_AXIS_FLIPPED ? (w.maxY - z.z) * ky : (z.z - w.minY) * ky;
      if (ix < x0) x0 = ix;
      if (ix > x1) x1 = ix;
      if (iy < y0) y0 = iy;
      if (iy > y1) y1 = iy;
    }
    var bw = Math.max(x1 - x0, 24);
    var bh = Math.max(y1 - y0, 24);
    var pad = clamp(Math.min(state.view.w, state.view.h) * 0.1, 24, 80);
    var scale = Math.min((state.view.w - pad * 2) / bw, (state.view.h - pad * 2) / bh);
    scale = clamp(scale, state.cam.min, state.cam.max);
    var cx = (x0 + x1) / 2;
    var cy = (y0 + y1) / 2;
    var pan = clampPan(scale, state.view.w / 2 - cx * scale, state.view.h / 2 - cy * scale);
    animateCamera(scale, pan.tx, pan.ty, 420);
    state.userMoved = true;
    hideHint();
  }

  function zoomAt(factor, cx, cy) {
    var target = clamp(state.cam.scale * factor, state.cam.min, state.cam.max);
    if (Math.abs(target - state.cam.scale) < 1e-6) return;
    var k = target / state.cam.scale;
    var pan = clampPan(target, cx - (cx - state.cam.tx) * k, cy - (cy - state.cam.ty) * k);
    state.cam.scale = target;
    state.cam.tx = pan.tx;
    state.cam.ty = pan.ty;
    state.userMoved = true;
    scheduleDraw();
  }

  function panBy(dx, dy) {
    var pan = clampPan(state.cam.scale, state.cam.tx + dx, state.cam.ty + dy);
    state.cam.tx = pan.tx;
    state.cam.ty = pan.ty;
    state.userMoved = true;
    scheduleDraw();
  }

  function animateCamera(scale, tx, ty, ms) {
    if (state.reducedMotion) {
      state.cam.scale = scale;
      state.cam.tx = tx;
      state.cam.ty = ty;
      state.tween = null;
      scheduleDraw();
      return;
    }
    state.tween = {
      t0: performance.now(),
      dur: Math.max(120, ms || 320),
      from: { scale: state.cam.scale, tx: state.cam.tx, ty: state.cam.ty },
      to: { scale: scale, tx: tx, ty: ty }
    };
    scheduleDraw();
  }

  function stepTween(now) {
    var tw = state.tween;
    if (!tw) return;
    var k = clamp((now - tw.t0) / tw.dur, 0, 1);
    var e = 1 - Math.pow(1 - k, 3);
    state.cam.scale = Math.exp(Math.log(tw.from.scale) + (Math.log(tw.to.scale) - Math.log(tw.from.scale)) * e);
    state.cam.tx = tw.from.tx + (tw.to.tx - tw.from.tx) * e;
    state.cam.ty = tw.from.ty + (tw.to.ty - tw.from.ty) * e;
    applyCamera();
    if (k >= 1) state.tween = null;
  }

  /* ======================================================================== *
   * 11. Canvas rendering (need zones only)
   * ======================================================================== */

  function scheduleDraw() {
    if (!rafId) rafId = window.requestAnimationFrame(frame);
  }

  function frame(now) {
    rafId = 0;
    if (state.tween) stepTween(now);
    render(now);
    if (state.tween) rafId = window.requestAnimationFrame(frame);
  }

  function resizeCanvas() {
    var rect = els.mapWrap.getBoundingClientRect();
    var w = Math.max(1, Math.round(rect.width));
    var h = Math.max(1, Math.round(rect.height));
    setView(w, h);

    var dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    if (w * h * dpr * dpr > MAX_CANVAS_PIXELS) {
      dpr = Math.max(1, Math.sqrt(MAX_CANVAS_PIXELS / (w * h)));
    }
    state.dpr = dpr;

    var bw = Math.round(w * dpr);
    var bh = Math.round(h * dpr);
    if (els.canvas.width !== bw) els.canvas.width = bw;
    if (els.canvas.height !== bh) els.canvas.height = bh;

    setLimits();
    if (!state.userMoved) fitMap(false);
    else applyCamera();
    scheduleDraw();
  }

  /** Zone glyphs are scenery: a near-fixed screen size, independent of zoom. */
  function zoneRadius() {
    var ui = clamp(Math.sqrt(state.view.w / 1400), 0.85, 1.5);
    return clamp(3.7 * ui, 3.2, 5.6);
  }

  function roundRectPath(ctx, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  function zonePath(ctx, type, r) {
    if (type === "feed") {
      roundRectPath(ctx, -r * 0.86, -r * 0.86, r * 1.72, r * 1.72, r * 0.3);
    } else if (type === "drink") {
      ctx.beginPath();
      ctx.arc(0, 0, r * 0.95, 0, TAU);
    } else {
      ctx.beginPath();
      ctx.moveTo(0, -r * 1.02);
      ctx.lineTo(r * 1.02, r * 0.74);
      ctx.lineTo(-r * 1.02, r * 0.74);
      ctx.closePath();
    }
  }

  function drawZone(ctx, sx, sy, zone, r, active, dim) {
    var color = PAL[zone.type] || PAL.rest;
    var ring = r + 4.2;
    ctx.save();
    ctx.translate(sx, sy);
    /* Inactive zones dim to ~30 %; unattributed zones (species filter on) are
       softened AND get a dashed ring so they read as "species unknown" rather
       than simply "off". */
    ctx.globalAlpha = (active ? 1 : 0.3) * (dim ? 0.7 : 1);

    /* Zen ring: fixed size, no data drives it. */
    if (dim) ctx.setLineDash([2, 2.5]);
    ctx.beginPath();
    ctx.arc(0, 0, ring, 0, TAU);
    ctx.strokeStyle = rgba(color, active ? 0.55 : 0.42);
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.setLineDash([]);

    zonePath(ctx, zone.type, r);
    ctx.lineJoin = "round";
    ctx.lineWidth = Math.max(1.3, r * 0.4);
    ctx.strokeStyle = PAL.ink;
    ctx.stroke();

    if (dim) {
      /* hollow: "species not attributed" */
      ctx.lineWidth = Math.max(1.1, r * 0.3);
      ctx.strokeStyle = rgba(color, 0.95);
      ctx.stroke();
    } else {
      ctx.fillStyle = color;
      ctx.fill();
      ctx.lineWidth = 0.9;
      ctx.strokeStyle = PAL.edge;
      ctx.stroke();
    }
    ctx.restore();
    return ring;
  }

  function render() {
    var ctx = state.ctx;
    if (!ctx || state.fatal) return;
    var w = state.view.w;
    var h = state.view.h;

    ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    updateProjection();

    var transform = "translate(" + state.cam.tx.toFixed(2) + "px," + state.cam.ty.toFixed(2) + "px) scale(" +
      state.cam.scale.toFixed(5) + ")";
    if (els.mapImg.style.transform !== transform) els.mapImg.style.transform = transform;
    if (els.placeholder.style.transform !== transform) els.placeholder.style.transform = transform;

    var zoomText = Math.round((state.cam.scale / (state.cam.fit || 1)) * 100) + "%";
    if (els.zoomReadout.textContent !== zoomText) els.zoomReadout.textContent = zoomText;

    var r = zoneRadius();
    var hits = state.hits;
    hits.length = 0;
    var visible = state.visibleZones;
    var proj = state.proj;

    /* Data layers sit underneath the zones so the scenery stays readable. */
    drawPressure(ctx, w, h);
    drawTrails(ctx, w, h);
    drawPlayerTrail(ctx, w, h);

    /* Two passes so the zones that are active right now sit on top. */
    for (var pass = 0; pass < 2; pass++) {
      var wantActive = pass === 1;
      for (var i = 0; i < visible.length; i++) {
        var z = visible[i];
        if (z.active !== wantActive) continue;
        var sx = z.x * proj.kx + proj.ox;
        var sy = proj.flip ? proj.oy - z.z * proj.ky : z.z * proj.ky + proj.oy;
        if (sx < -30 || sy < -30 || sx > w + 30 || sy > h + 30) continue;
        var ring = drawZone(ctx, sx, sy, z, r, z.active, z.dim);
        if (wantActive) hits.push({ sx: sx, sy: sy, r: r, ring: ring, zone: z });
      }
    }

    /* Live animals sit above the zone scenery but below the hover ring, so the
       need-zone layer stays readable while animals track in real time. */
    drawLive(ctx, w, h);
    drawRoute(ctx, w, h);
    drawMeasure(ctx, w, h);
    if (state.hovered) {
      var hsx = state.hovered.x * proj.kx + proj.ox;
      var hsy = proj.flip ? proj.oy - state.hovered.z * proj.ky : state.hovered.z * proj.ky + proj.oy;
      var hr = r + 7.5;
      ctx.beginPath();
      ctx.arc(hsx, hsy, hr, 0, TAU);
      ctx.strokeStyle = rgba(PAL.text, 0.85);
      ctx.lineWidth = 1.4;
      ctx.stroke();
    }
  }

  /* ======================================================================== *
   * 12. Hit testing + tooltip
   * ======================================================================== */

  function hitTest(mx, my) {
    var best = null;
    var bestD = Infinity;
    var hits = state.hits;
    for (var i = 0; i < hits.length; i++) {
      var h = hits[i];
      var dx = h.sx - mx;
      var dy = h.sy - my;
      var d2 = dx * dx + dy * dy;
      var pick = Math.max(15, h.ring + 7);
      if (d2 <= pick * pick && d2 < bestD) {
        bestD = d2;
        best = h;
      }
    }
    return best;
  }

  function showTooltip(zone, mx, my) {
    var active = isActiveAt(zone, state.hour);
    var known = !!zone.animal;

    els.ttGlyph.dataset.zone = zone.type;
    els.ttType.textContent = known ? zone.animal : t("Unknown animal type");
    els.ttType.classList.toggle("is-unknown", !known);
    els.ttState.textContent = active ? t("active now") : t("inactive now");
    els.ttState.dataset.state = active ? "on" : "off";
    els.ttWindow.textContent = (TYPE_LABEL[zone.type] || t("Zone")) + " \u00b7 " + windowText(zone);
    els.ttAlt.textContent = zone.altitude == null ? "\u2014" : thousands(zone.altitude) + " m";

    /* Honest degradation: an unmapped type hash is shown as a hash, never as an
       invented species. */
    if (known) {
      els.ttAnimal.hidden = true;
    } else {
      els.ttAnimal.hidden = false;
      els.ttAnimal.textContent = zone.hash
        ? t("Type hash {hash}", { hash: zone.hash })
        : t("No animal type in this scan");
    }

    var icon = zone.rosterName ? state.iconByName[zone.rosterName] : null;
    if (icon) {
      if (els.ttIcon.getAttribute("src") !== icon) els.ttIcon.src = icon;
      els.ttIcon.hidden = false;
    } else {
      els.ttIcon.hidden = true;
    }

    els.tooltip.hidden = false;
    ttSize.w = els.tooltip.offsetWidth;
    ttSize.h = els.tooltip.offsetHeight;
    positionTooltip(mx, my);
  }

  function positionTooltip(mx, my) {
    var x = mx + 18;
    var y = my + 18;
    if (x + ttSize.w > state.view.w - 8) x = mx - ttSize.w - 18;
    if (y + ttSize.h > state.view.h - 8) y = my - ttSize.h - 18;
    x = clamp(x, 8, Math.max(8, state.view.w - ttSize.w - 8));
    y = clamp(y, 8, Math.max(8, state.view.h - ttSize.h - 8));
    els.tooltip.style.transform = "translate3d(" + Math.round(x) + "px," + Math.round(y) + "px,0)";
  }

  function hideTooltip() {
    els.tooltip.hidden = true;
  }

  /* ======================================================================== *
   * 13. Map input
   * ======================================================================== */

  function localPoint(e) {
    var rect = els.mapWrap.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function hideHint() {
    if (!els.mapHint.classList.contains("is-hidden")) els.mapHint.classList.add("is-hidden");
  }

  function resetView() {
    state.hovered = null;
    hideTooltip();
    fitMap(true);
  }

  var pointers = [];
  var drag = null;
  var pinch = null;

  function startPinch() {
    var a = pointers[0];
    var b = pointers[1];
    var rect = els.mapWrap.getBoundingClientRect();
    pinch = {
      dist: Math.hypot(a.x - b.x, a.y - b.y) || 1,
      mx: (a.x + b.x) / 2 - rect.left,
      my: (a.y + b.y) / 2 - rect.top,
      scale: state.cam.scale,
      tx: state.cam.tx,
      ty: state.cam.ty
    };
    state.hovered = null;
    hideTooltip();
  }

  function updatePinch() {
    if (!pinch || pointers.length < 2) return;
    var a = pointers[0];
    var b = pointers[1];
    var rect = els.mapWrap.getBoundingClientRect();
    var dist = Math.hypot(a.x - b.x, a.y - b.y) || 1;
    var mx = (a.x + b.x) / 2 - rect.left;
    var my = (a.y + b.y) / 2 - rect.top;
    var scale = clamp(pinch.scale * (dist / pinch.dist), state.cam.min, state.cam.max);
    var k = scale / pinch.scale;
    var tx = pinch.mx - (pinch.mx - pinch.tx) * k + (mx - pinch.mx);
    var ty = pinch.my - (pinch.my - pinch.ty) * k + (my - pinch.my);
    var pan = clampPan(scale, tx, ty);
    state.cam.scale = scale;
    state.cam.tx = pan.tx;
    state.cam.ty = pan.ty;
    state.userMoved = true;
    scheduleDraw();
  }

  function bindMap() {
    els.mapWrap.addEventListener("pointerdown", function (e) {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      hideTooltip();
      hideHint();
      try { els.mapWrap.setPointerCapture(e.pointerId); } catch (err) { /* not fatal */ }
      pointers = pointers.filter(function (p) { return p.id !== e.pointerId; });
      pointers.push({ id: e.pointerId, x: e.clientX, y: e.clientY });

      if (pointers.length === 1) {
        drag = { x: e.clientX, y: e.clientY, tx: state.cam.tx, ty: state.cam.ty, moved: false };
        els.mapWrap.classList.add("is-panning");
      } else if (pointers.length === 2) {
        startPinch();
        drag = null;
      }
      if (document.activeElement !== els.mapWrap) {
        try { els.mapWrap.focus({ preventScroll: true }); } catch (err) { els.mapWrap.focus(); }
      }
      e.preventDefault();
    });

    els.mapWrap.addEventListener("pointermove", function (e) {
      var local = localPoint(e);
      var slot = null;
      for (var i = 0; i < pointers.length; i++) {
        if (pointers[i].id === e.pointerId) { slot = pointers[i]; break; }
      }
      if (slot) { slot.x = e.clientX; slot.y = e.clientY; }

      if (pointers.length === 2) { updatePinch(); return; }

      if (drag && (drag.moved || e.buttons || e.pointerType !== "mouse")) {
        var dx = e.clientX - drag.x;
        var dy = e.clientY - drag.y;
        if (!drag.moved && Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        var pan = clampPan(state.cam.scale, drag.tx + dx, drag.ty + dy);
        state.cam.tx = pan.tx;
        state.cam.ty = pan.ty;
        state.userMoved = true;
        if (state.hovered) state.hovered = null;
        if (!els.tooltip.hidden) hideTooltip();
        els.mapWrap.style.cursor = "grabbing";
        scheduleDraw();
        return;
      }

      var hit = hitTest(local.x, local.y);
      var zone = hit ? hit.zone : null;
      if (zone !== state.hovered) {
        state.hovered = zone;
        if (zone) showTooltip(zone, local.x, local.y);
        else hideTooltip();
        scheduleDraw();
      } else if (zone) {
        positionTooltip(local.x, local.y);
      }
      els.mapWrap.style.cursor = zone ? "pointer" : "grab";

      if (!els.coords.hidden) {
        updateProjection();
        var wp = worldAt(local.x, local.y);
        els.coords.textContent = "x " + Math.round(wp.x) + "  z " + Math.round(wp.z);
      }
    });

    function endPointer(e) {
      pointers = pointers.filter(function (p) { return p.id !== e.pointerId; });
      if (pointers.length < 2) pinch = null;
      if (pointers.length === 0) {
        drag = null;
        els.mapWrap.classList.remove("is-panning");
        els.mapWrap.style.cursor = "grab";
      } else if (pointers.length === 1) {
        drag = { x: pointers[0].x, y: pointers[0].y, tx: state.cam.tx, ty: state.cam.ty, moved: true };
      }
    }
    els.mapWrap.addEventListener("pointerup", endPointer);
    els.mapWrap.addEventListener("pointercancel", endPointer);

    els.mapWrap.addEventListener("pointerleave", function () {
      if (state.hovered) { state.hovered = null; scheduleDraw(); }
      hideTooltip();
      els.coords.textContent = "\u2014";
    });

    els.mapWrap.addEventListener("wheel", function (e) {
      e.preventDefault();
      hideHint();
      hideTooltip();
      var local = localPoint(e);
      var d = e.deltaY;
      if (e.deltaMode === 1) d *= 16;
      else if (e.deltaMode === 2) d *= 100;
      zoomAt(clamp(Math.exp(-d * 0.0016), 1 / 1.6, 1.6), local.x, local.y);
    }, { passive: false });

    els.mapWrap.addEventListener("dblclick", function (e) {
      e.preventDefault();
      resetView();
    });

    els.mapWrap.addEventListener("keydown", function (e) {
      var step = e.shiftKey ? 160 : 48;
      var handled = true;
      switch (e.key) {
        case "ArrowLeft": panBy(step, 0); break;
        case "ArrowRight": panBy(-step, 0); break;
        case "ArrowUp": panBy(0, step); break;
        case "ArrowDown": panBy(0, -step); break;
        case "+": case "=": zoomAt(1.25, state.view.w / 2, state.view.h / 2); break;
        case "-": case "_": zoomAt(1 / 1.25, state.view.w / 2, state.view.h / 2); break;
        case "0": resetView(); break;
        case "f": case "F": fitZones(); break;
        case "Escape": hideTooltip(); break;
        default: handled = false;
      }
      if (handled) e.preventDefault();
    });

    var toolbar = els.mapWrap.querySelector(".map-toolbar");
    if (toolbar) toolbar.addEventListener("pointerdown", function (e) { e.stopPropagation(); });

    els.btnZoomIn.addEventListener("click", function () { zoomAt(1.35, state.view.w / 2, state.view.h / 2); hideHint(); });
    els.btnZoomOut.addEventListener("click", function () { zoomAt(1 / 1.35, state.view.w / 2, state.view.h / 2); hideHint(); });
    els.btnFitMap.addEventListener("click", function () { fitMap(true); hideHint(); });
    els.btnFitZones.addEventListener("click", fitZones);
    els.btnResetMap.addEventListener("click", resetView);
  }

  /* ======================================================================== *
   * 14. Chrome: theme, hour slider, sheets, notes
   * ======================================================================== */

  function applyTheme(theme) {
    var next = theme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem(STORE_THEME, next); } catch (e) { /* ignore */ }
    var label = next === "dark" ? t("Switch to light theme") : t("Switch to dark theme");
    els.btnTheme.setAttribute("aria-label", label);
    els.btnTheme.setAttribute("title", label);
    readPalette();
    scheduleDraw();
  }

  function bindChrome() {
    els.btnTheme.addEventListener("click", function () {
      var current = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
      applyTheme(current === "light" ? "dark" : "light");
    });

    els.hourSlider.addEventListener("input", function () {
      var v = parseFloat(els.hourSlider.value);
      if (!isFinite(v)) return;
      /* Dragging the slider takes over from the game clock. */
      if (state.followClock) setFollowClock(false);
      updateHour(v);
    });

    if (els.btnClock) {
      els.btnClock.addEventListener("click", function () {
        setFollowClock(!state.followClock);
      });
    }

    els.btnOpenFilters.addEventListener("click", function () {
      openSheet(state.sheet === "filters" ? null : "filters");
    });
    els.tabAnimals.addEventListener("click", function () {
      openSheet(state.sheet === "list" ? null : "list");
    });
    els.tabFilters.addEventListener("click", function () {
      openSheet(state.sheet === "filters" ? null : "filters");
    });
    els.btnCloseFilters.addEventListener("click", function () { openSheet(null); });
    els.btnCloseList.addEventListener("click", function () { openSheet(null); });
    els.scrim.addEventListener("click", function () { openSheet(null); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && state.sheet) openSheet(null);
    });

    els.listScroll.addEventListener("scroll", onListScroll, { passive: true });

    if (mqCompact.addEventListener) mqCompact.addEventListener("change", syncCompact);
    else if (mqCompact.addListener) mqCompact.addListener(syncCompact);

    if (mqMotion.addEventListener) {
      mqMotion.addEventListener("change", function (e) { state.reducedMotion = e.matches; scheduleDraw(); });
    } else if (mqMotion.addListener) {
      mqMotion.addListener(function (e) { state.reducedMotion = e.matches; scheduleDraw(); });
    }

    if (window.ResizeObserver) {
      var ro = new ResizeObserver(function () { resizeCanvas(); });
      ro.observe(els.mapWrap);
    } else {
      window.addEventListener("resize", resizeCanvas);
    }
    window.addEventListener("orientationchange", function () { setTimeout(resizeCanvas, 120); });
    window.addEventListener("resize", function () {
      if (window.devicePixelRatio !== state.lastDpr) {
        state.lastDpr = window.devicePixelRatio;
        resizeCanvas();
      }
    });
  }

  function setInert(node, on) {
    if (!node) return;
    if ("inert" in node) node.inert = !!on;
  }

  function openSheet(which) {
    state.sheet = which || null;
    var filtersOpen = state.sheet === "filters";
    var listOpen = state.sheet === "list";
    els.sidebar.classList.toggle("is-open", filtersOpen);
    els.listPanel.classList.toggle("is-open", listOpen);
    els.scrim.hidden = !state.sheet;
    els.tabFilters.classList.toggle("is-active", filtersOpen);
    els.tabAnimals.classList.toggle("is-active", listOpen);
    els.btnOpenFilters.setAttribute("aria-expanded", String(filtersOpen));
    els.tabFilters.setAttribute("aria-expanded", String(filtersOpen));
    els.tabAnimals.setAttribute("aria-expanded", String(listOpen));

    if (mqCompact.matches) {
      setInert(els.sidebar, !filtersOpen);
      setInert(els.listPanel, !listOpen);
      if (which) {
        var panel = which === "filters" ? els.sidebar : els.listPanel;
        try { panel.focus({ preventScroll: true }); } catch (err) { panel.focus(); }
        if (listOpen) renderListWindow(true);
      } else {
        els.btnOpenFilters.focus();
      }
    }
  }

  function syncCompact() {
    if (!mqCompact.matches) {
      state.sheet = null;
      els.sidebar.classList.remove("is-open");
      els.listPanel.classList.remove("is-open");
      els.scrim.hidden = true;
      els.tabFilters.classList.remove("is-active");
      els.tabAnimals.classList.remove("is-active");
      setInert(els.sidebar, false);
      setInert(els.listPanel, false);
    } else {
      setInert(els.sidebar, state.sheet !== "filters");
      setInert(els.listPanel, state.sheet !== "list");
    }
    renderListWindow(true);
    scheduleDraw();
  }

  function showNote(text, ms) {
    if (state.persistentNote) return;
    els.mapNoteText.textContent = text;
    els.mapNote.hidden = false;
    if (noteTimer) window.clearTimeout(noteTimer);
    if (ms) {
      noteTimer = window.setTimeout(function () {
        noteTimer = 0;
        if (!state.persistentNote) els.mapNote.hidden = true;
      }, ms);
    }
  }

  function showPersistentNote(text) {
    state.persistentNote = text;
    els.mapNoteText.textContent = text;
    els.mapNote.hidden = false;
  }

  /* ======================================================================== *
   * 15. Boot
   * ======================================================================== */

  function cacheDom() {
    els.reserveName = $("reserveName");
    els.generatedAt = $("generatedAt");
    els.dataBadge = $("dataBadge");
    els.dataBadgeText = $("dataBadgeText");
    els.btnTheme = $("btnTheme");
    els.btnOpenFilters = $("btnOpenFilters");
    els.filterBadge = $("filterBadge");

    els.sidebar = $("sidebar");
    els.btnCloseFilters = $("btnCloseFilters");
    els.zoneTypeList = $("zoneTypeList");
    els.zoneTotal = $("zoneTotal");
    els.speciesTotal = $("speciesTotal");
    els.popTotal = $("popTotal");
    els.posNotice = $("posNotice");
    els.speciesSearch = $("speciesSearch");
    els.btnClearSearch = $("btnClearSearch");
    els.speciesList = $("speciesList");
    els.speciesEmpty = $("speciesEmpty");
    els.speciesEmptyLead = $("speciesEmptyLead");
    els.speciesEmptyTerm = $("speciesEmptyTerm");
    els.speciesEmptyTail = $("speciesEmptyTail");
    els.genderSegment = $("genderSegment");
    els.medalList = $("medalList");
    els.furList = $("furList");
    els.hideScripted = $("hideScripted");
    els.hideGreatOnes = $("hideGreatOnes");
    els.btnResetFilters = $("btnResetFilters");

    els.mapWrap = $("mapWrap");
    els.mapImg = $("mapImg");
    els.placeholder = $("mapPlaceholder");
    els.canvas = $("zoneCanvas");
    els.zoomReadout = $("zoomReadout");
    els.coords = $("coords");
    els.btnZoomIn = $("btnZoomIn");
    els.btnZoomOut = $("btnZoomOut");
    els.btnFitMap = $("btnFitMap");
    els.btnFitZones = $("btnFitZones");
    els.btnResetMap = $("btnResetMap");
    els.mapHint = $("mapHint");
    els.mapNote = $("mapNote");
    els.mapNoteText = $("mapNoteText");
    els.btnLive = $("btnLive");
    els.btnPressure = $("btnPressure");
    els.btnTrails = $("btnTrails");
    els.hoursPanel = $("hoursPanel");
    els.hoursList = $("hoursList");
    els.hoursSpecies = $("hoursSpecies");
    els.hoursHint = $("hoursHint");
    els.comparePanel = $("comparePanel");
    els.compareList = $("compareList");
    els.compareHint = $("compareHint");
    els.harvestPanel = $("harvestPanel");
    els.harvestList = $("harvestList");
    els.harvestCount = $("harvestCount");
    els.harvestHint = $("harvestHint");
    els.alertsPanel = $("alertsPanel");
    els.alertsList = $("alertsList");
    els.alertsCount = $("alertsCount");
    els.alertsMeta = $("alertsMeta");
    els.alertToast = $("alertToast");
    els.alertTitle = $("alertTitle");
    els.alertDetail = $("alertDetail");
    els.alertClose = $("alertClose");
    els.btnNearby = $("btnNearby");
    els.changesList = $("changesList");
    els.changesHint = $("changesHint");
    els.historyPanel = $("historyPanel");
    els.historyList = $("historyList");
    els.historyCount = $("historyCount");
    els.historyHint = $("historyHint");
    els.btnRoute = $("btnRoute");
    els.btnMeasure = $("btnMeasure");
    els.btnCsv = $("btnCsv");
    els.liveCard = $("liveCard");
    els.liveCount = $("liveCount");
    els.liveMeta = $("liveMeta");
    els.liveHint = $("liveHint");
    els.liveHintText = $("liveHintText");
    els.liveHintLink = $("liveHintLink");
    els.liveList = $("liveList");
    els.tooltip = $("tooltip");
    els.ttGlyph = $("ttGlyph");
    els.ttIcon = $("ttIcon");
    els.ttType = $("ttType");
    els.ttState = $("ttState");
    els.ttWindow = $("ttWindow");
    els.ttAlt = $("ttAlt");
    els.ttAnimal = $("ttAnimal");
    els.mapEmpty = $("mapEmpty");
    els.emptyTitle = $("emptyTitle");
    els.emptyText = $("emptyText");
    els.btnEmptyClear = $("btnEmptyClear");
    els.mapLoading = $("mapLoading");
    els.setupPanel = $("setupPanel");
    els.saveDirInput = $("saveDirInput");
    els.saveDirApply = $("saveDirApply");
    els.saveDirError = $("saveDirError");
    els.saveDirSearched = $("saveDirSearched");
    els.legend = $("legend");

    els.hourSlider = $("hourSlider");
    els.btnClock = $("btnClock");
    els.hourReadout = $("hourReadout");
    els.timebarCount = $("timebarCount");
    els.activeCount = $("activeCount");
    els.zoneCount = $("zoneCount");

    els.summaryLine = $("summaryLine");
    els.listPanel = $("listPanel");
    els.btnCloseList = $("btnCloseList");
    els.listCount = $("listCount");
    els.listNew = $("listNew");
    els.listNewText = $("listNewText");
    els.sortbar = $("sortbar");
    els.listScroll = $("listScroll");
    els.animalList = $("animalList");
    els.listEmpty = $("listEmpty");
    els.listEmptyText = $("listEmptyText");

    els.tabAnimals = $("tabAnimals");
    els.tabAnimalsCount = $("tabAnimalsCount");
    els.tabFilters = $("tabFilters");
    els.tabFiltersCount = $("tabFiltersCount");
    els.scrim = $("scrim");

    var missing = [];
    for (var key in els) if (els[key] == null) missing.push(key);
    if (missing.length) throw new Error("Markup is missing required nodes: " + missing.join(", "));
  }

  function bindImage() {
    els.mapImg.addEventListener("load", function () {
      if (!els.mapImg.naturalWidth) return;
      state.img = { w: els.mapImg.naturalWidth, h: els.mapImg.naturalHeight };
      state.imgReady = true;
      els.mapImg.style.width = state.img.w + "px";
      els.mapImg.style.height = state.img.h + "px";
      els.placeholder.style.width = state.img.w + "px";
      els.placeholder.style.height = state.img.h + "px";
      if (!state.userMoved) fitZones();
      else { setLimits(); applyCamera(); }
      scheduleDraw();
    });

    els.mapImg.addEventListener("error", function () {
      state.imgFailed = true;
      els.mapImg.hidden = true;
      els.placeholder.hidden = false;
      state.img = { w: DEFAULT_MAP.w, h: DEFAULT_MAP.h };
      els.placeholder.style.width = state.img.w + "px";
      els.placeholder.style.height = state.img.h + "px";
      showPersistentNote(t("Reserve map image missing — plotting on a schematic grid"));
      if (!state.userMoved) { setLimits(); fitZones(); }
      scheduleDraw();
    });
  }

  /* The sort bar existed and was styled, but nothing ever listened to it. */
  function bindSortBar() {
    if (!els.sortbar) return;
    els.sortbar.addEventListener("click", function (ev) {
      var btn = ev.target && ev.target.closest ? ev.target.closest("[data-sort]") : null;
      if (!btn || !els.sortbar.contains(btn)) return;
      ev.preventDefault();
      setSort(btn.dataset.sort);
    });
  }

  /* Reserve switching. The API is asked which reserves exist, so the menu shows
     the real display names and marks empty slots instead of letting the user pick
     a reserve that would render nothing. A reload keeps the map image and canvas
     setup simple and avoids stale state. */
  function bindReservePicker() {
    var btn = els.reserveName;
    var menu = $("reserveMenu");
    if (!btn || !menu) return;
    var loaded = false;

    function close() {
      menu.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    }
    function open() {
      menu.hidden = false;
      btn.setAttribute("aria-expanded", "true");
      if (loaded) return;
      loaded = true;
      fetchJson("/api/reserves")
        .then(function (res) {
          var list = (res && res.reserves) || [];
          menu.textContent = "";
          if (!list.length) {
            menu.textContent = t("No reserves found");
            return;
          }
          list.forEach(function (r) {
            var item = document.createElement("button");
            item.type = "button";
            item.className = "reserve-item";
            item.setAttribute("role", "option");
            item.dataset.index = String(r.index);
            var current = state.reserve && r.index === state.reserve.index;
            if (current) {
              item.classList.add("is-current");
              item.setAttribute("aria-selected", "true");
            }
            if (!r.populated) item.classList.add("is-empty");

            var name = document.createElement("span");
            name.className = "reserve-item-name";
            name.textContent = r.reserve || t("Reserve {n}", { n: r.index });

            var meta = document.createElement("span");
            meta.className = "reserve-item-meta";
            meta.textContent = r.populated ? "" : t("not played");

            item.appendChild(name);
            item.appendChild(meta);
            item.addEventListener("click", function () {
              var url = new URL(window.location.href);
              url.searchParams.set("reserve", String(r.index));
              window.location.href = url.toString();
            });
            menu.appendChild(item);
          });
        })
        .catch(function () {
          menu.textContent = t("Could not load reserves");
        });
    }

    btn.addEventListener("click", function (ev) {
      ev.preventDefault();
      if (menu.hidden) open();
      else close();
    });
    document.addEventListener("click", function (ev) {
      if (menu.hidden) return;
      if (menu.contains(ev.target) || btn.contains(ev.target)) return;
      close();
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && !menu.hidden) close();
    });
  }

  function setHeader() {
    var confidence = state.reserve.confidence
      ? t(" · zones {confidence}", { confidence: state.reserve.confidence })
      : "";
    els.reserveName.textContent = state.reserve.name;
    els.reserveName.title = state.reserve.name +
      (state.reserve.index != null ? " " + t("(index {n})", { n: state.reserve.index }) : "") +
      confidence;

    var when = null;
    if (state.generatedAt) {
      var date = new Date(state.generatedAt);
      if (!isNaN(date.getTime())) {
        try {
          when = date.toLocaleString(window.I18N ? window.I18N.dateLocale() : undefined,
            { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
        } catch (err) { when = state.generatedAt; }
      }
    }
    els.generatedAt.textContent = when ? t("scanned {when}", { when: when }) : "";

    els.dataBadge.dataset.mode = state.mode === "fixture" ? "fixture" : "live";
    els.dataBadgeText.textContent = state.mode === "fixture" ? t("Sample data") : t("Live save");
    els.dataBadge.title = state.mode === "fixture"
      ? t("The local API was not reachable, so the bundled sample reserve is shown.")
      : t("Population loaded from the scanner.");

    if (state.zoneMode === "fixture") {
      els.timebarCount.title = t("Sample need zones · {confidence}",
        { confidence: state.reserve.confidence });
    } else if (state.zoneMode === "missing") {
      els.timebarCount.title = t("Need zone endpoint unavailable");
    } else {
      els.timebarCount.title = t("Need zones from the save scan") + confidence;
    }
  }

  function fatal(message) {
    state.fatal = true;
    if (els.mapLoading) els.mapLoading.hidden = true;
    els.emptyTitle.textContent = t("Could not read the scan");
    els.emptyText.textContent = message;
    els.btnEmptyClear.hidden = true;
    els.mapEmpty.hidden = false;
    els.listEmpty.hidden = true;
    els.dataBadge.dataset.mode = "error";
    els.dataBadgeText.textContent = t("No data");
    console.warn("[waypoint] " + message);
  }

  async function loadAll() {
    var population = null;
    var zonesPayload = null;
    var populationMode = "live";
    var zoneMode = "live";

    if (window.location.protocol !== "file:") {
      try {
        /* ?reserve=N selects a reserve; without it the page follows the game.
           /api/radar reports which reserve the live entities belong to (it works it
           out from the saved player positions), and that is the only reserve whose
           animals are actually simulated — anchoring the page on any other one puts
           every animal past the 500 m radius and the live layer looks dead. */
        var wantedReserve = null;
        try {
          wantedReserve = new URLSearchParams(window.location.search).get("reserve");
        } catch (paramErr) {
          wantedReserve = null;
        }
        if (wantedReserve == null || wantedReserve === "") {
          try {
            var probe = await fetchJson("/api/radar");
            var liveReserve = probe ? fin(probe.live_reserve) : null;
            if (liveReserve != null) wantedReserve = String(liveReserve);
          } catch (probeErr) {
            /* the radar is optional here: fall back to the server's default reserve */
          }
        }
        var reserveQuery =
          wantedReserve != null && wantedReserve !== ""
            ? "?reserve=" + encodeURIComponent(wantedReserve)
            : "";
        population = await fetchJson("/api/population" + reserveQuery);
      } catch (err) {
        console.warn("[waypoint] /api/population unavailable \u2014 falling back to bundled sample data.",
          err && err.message ? err.message : err);
        population = null;
      }
      if (population) {
        var idx = population && population.reserve ? fin(population.reserve.index) : null;
        if (idx != null) {
          try {
            zonesPayload = await fetchJson("/api/needzones?reserve=" + encodeURIComponent(idx));
          } catch (err) {
            console.warn("[waypoint] /api/needzones unavailable for reserve " + idx + ".",
              err && err.message ? err.message : err);
            zonesPayload = null;
          }
        }
      }
    } else {
      console.warn("[waypoint] opened from file:// \u2014 using bundled sample population and zones.");
    }

    if (!population) {
      population = window.FIXTURE_DATA || null;
      populationMode = "fixture";
    }
    if (!zonesPayload) {
      /* Only ever pair sample zones with sample population: mixing fake zones
         into a real save would be misleading. */
      if (populationMode === "fixture" && window.FIXTURE_ZONES) {
        zonesPayload = window.FIXTURE_ZONES;
        zoneMode = "fixture";
      } else {
        zoneMode = "missing";
      }
    }

    return { population: population, zones: zonesPayload, populationMode: populationMode, zoneMode: zoneMode };
  }

  async function boot() {
    cacheDom();
    readPalette();
    state.lastDpr = window.devicePixelRatio;

    var ctx = els.canvas.getContext("2d", { alpha: true });
    if (!ctx) { fatal(t("This browser cannot draw the map layer (no 2D canvas).")); return; }
    state.ctx = ctx;

    state.baseTitle = document.title;
    state.reducedMotion = mqMotion.matches;
    state.hour = loadHour();
    els.hourSlider.value = String(state.hour);
    setFollowClock(loadFollowClock());
    loadSort();

    /* A species icon that fails to load must not leave a broken image in the
       tooltip — hide it and keep the name. */
    els.ttIcon.addEventListener("error", function () { els.ttIcon.hidden = true; });

    state.filters = defaultFilters([]);
    bindImage();
    bindChrome();
    bindMap();
    bindSortBar();
    bindReservePicker();
    bindLive();
    bindLayers();
    bindAlerts();
    bindSetup();
    syncCompact();
    syncSortBar();
    resizeCanvas();

    /* Does the server know where the saves are? If not, the setup panel is the first
       thing the user must see — the rest of the page would show sample data and look
       broken. */
    try {
      state.app = await fetchJson("/api/ping");
    } catch (err) {
      state.app = null;   // file:// or a server too old to answer: no setup panel
    }
    state.needsSetup = !!(state.app && state.app.save_dir == null);
    paintSetup();

    var loaded = null;
    try {
      loaded = await loadAll();
    } catch (err) {
      fatal(t("The scan could not be read: {message}",
        { message: err && err.message ? err.message : t("unknown error") }));
      return;
    }

    if (!loaded.population) {
      fatal(t("No population data was returned and no bundled sample is available."));
      return;
    }

    var pop, zones;
    try {
      pop = normalisePopulation(loaded.population);
      zones = normaliseZones(loaded.zones, pop.world);
    } catch (err) {
      fatal(t("The scan JSON could not be understood."));
      return;
    }

    state.mode = loaded.populationMode;
    state.zoneMode = loaded.zoneMode;
    state.generatedAt = pop.generatedAt;
    state.animals = pop.animals;
    state.species = pop.species;
    state.reserve = {
      index: pop.reserve.index != null ? pop.reserve.index : zones.reserve.index,
      name: zones.reserve.name || pop.reserve.name,
      confidence: zones.reserve.confidence
    };
    state.world = zones.world;
    state.zones = zones.zones;

    state.byId = Object.create(null);
    state.speciesByLower = Object.create(null);
    state.iconByName = Object.create(null);
    for (var s = 0; s < state.species.length; s++) {
      var sp = state.species[s];
      state.speciesByLower[sp.name.toLowerCase().trim()] = sp.name;
      state.iconByName[sp.name] = iconSrc(sp.icon);
    }
    for (var i = 0; i < state.animals.length; i++) {
      var a = state.animals[i];
      state.byId[a.id] = a;
      for (var s2 = 0; s2 < state.species.length; s2++) {
        if (state.species[s2].name === a.species) { a.icon = state.species[s2].icon; break; }
      }
    }

    /* Resolve each zone's animal name against the scanned roster (case-insensitive)
       so the species filter can match zones and animals with one key. */
    for (var z = 0; z < state.zones.length; z++) {
      var zone = state.zones[z];
      zone.rosterName = zone.animal ? (state.speciesByLower[zone.animal.toLowerCase().trim()] || null) : null;
    }

    state.filters = loadFilters(defaultFilters(state.species));

    buildZoneTypeList();
    buildSpeciesList();
    buildMedalList();
    buildFurList();
    bindFilterInputs();
    syncFilterInputs();
    if (state.filters.search) {
      els.speciesSearch.value = state.filters.search;
      filterSpeciesRows();
    }
    applyMedalAvailability();

    setHeader();
    /* Animal positions are never persisted in save data, so this note is a
       permanent explanation of why the map carries zones rather than animals —
       not an error state. */
    els.posNotice.hidden = false;

    applyPopulationFilters();
    applyZoneFilters();
    renderBadges();

    /* The reserve is known now, so the radar can ask for that reserve's saved
       player position and start polling. */
    startLive();
    loadFurs();
    loadPressure();
    renderHarvests();
    renderHours();
    renderCompare();
    renderHistory();

    if (!state.userMoved) fitZones(); else applyCamera();
    els.mapImg.src = mapSrc(pop.reserve.map);
    els.mapLoading.hidden = true;
    scheduleDraw();

    if (state.zoneMode === "missing") {
      showPersistentNote(t("Need zones unavailable — only the population could be loaded"));
    }
    void zones.dropped;
  }

  /* ======================================================================== *
   * 14. Live radar layer
   *
   * Animals come from /api/radar, which reads the running game's memory
   * read-only. Entity positions update in place and a refresh costs about a
   * millisecond, so polling at ~1.4 Hz keeps the layer live. The player's own
   * position cannot be read from memory on this build, so the server takes it
   * from the last saved position in playerinformation_adf — the same file that
   * carries the in-game clock, which is what drives the time slider.
   * ======================================================================== */

  var LIVE_POLL_MS = 700;
  var LIVE_ROWS = 14;
  /* Proximity alerts: how close a live animal must be, and how long before the same
     animal can fire again. */
  var NEARBY_RADIUS = 120;
  var NEARBY_COOLDOWN_MS = 300000;
  var FONT_STACK = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
  var LIVE_PALETTE = [
    "#e8a33d", "#7fb7e8", "#e0745c", "#8fd18a",
    "#c9a0e8", "#e8d05d", "#6fd3cb", "#e896b4"
  ];

  /* The in-game clock. The game writes TimeOfDay into playerinformation_adf, which the
     radar already polls, so the slider can simply follow it. Dragging the slider takes
     over until the button is pressed again. */
  function setFollowClock(on) {
    state.followClock = !!on;
    try { localStorage.setItem(STORE_CLOCK, state.followClock ? "1" : "0"); } catch (e) { /* ignore */ }
    if (!els.btnClock) return;
    els.btnClock.setAttribute("aria-pressed", state.followClock ? "true" : "false");
    els.btnClock.textContent = state.followClock ? t("Auto") : t("Manual");
    els.btnClock.title = state.followClock
      ? t("The hour follows the in-game clock — click for manual")
      : t("Manual hour — click to follow the in-game clock");
  }

  function syncClock(clock) {
    if (!clock || typeof clock.hour !== "number" || !isFinite(clock.hour)) return;
    var hour = ((clock.hour % 24) + 24) % 24;
    var stale = typeof clock.age_seconds === "number" && clock.age_seconds > 30;
    if (state.followClock) {
      if (Math.abs(hour - state.hour) > 0.02) updateHour(hour, false);
      if (els.btnClock) {
        els.btnClock.classList.toggle("is-stale", stale);
        els.btnClock.title = t("Following the in-game clock ({hhmm})", { hhmm: clock.hhmm })
          + (stale ? t(" — last write {n} s ago", { n: Math.round(clock.age_seconds) }) : "");
      }
    }
  }

  function liveColor(name) {
    var key = String(name || "");
    if (state.live.colors[key]) return state.live.colors[key];
    var h = 0;
    for (var i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
    var color = LIVE_PALETTE[h % LIVE_PALETTE.length];
    state.live.colors[key] = color;
    return color;
  }

  function liveUrl() {
    var idx = state.reserve && state.reserve.index;
    return idx == null ? "/api/radar" : "/api/radar?reserve=" + encodeURIComponent(idx);
  }

  function pollLive() {
    if (!state.live.on || state.live.busy || document.hidden) return;
    state.live.busy = true;
    fetchJson(liveUrl()).then(function (payload) {
      state.live.busy = false;
      var list = payload && payload.animals ? payload.animals : [];
      state.live.animals = list;
      state.live.player = payload && payload.player ? payload.player : null;
      state.live.source = payload ? payload.player_source : null;
      state.live.age = payload ? payload.player_age_seconds : null;
      state.live.error = payload ? payload.error : null;
      state.live.count = list.length;
      state.live.radius = payload && payload.radius ? payload.radius : 0;
      state.live.known = payload && payload.known != null ? payload.known : list.length;
      state.live.reserve = payload && payload.live_reserve != null ? payload.live_reserve : null;
      state.live.reserveName = payload ? payload.live_reserve_name : null;
      state.live.discovering = !!(payload && payload.discovering);
      recordTrails(list);
      checkProximity(list);
      recordPlayerTrail(payload ? payload.player : null);
      syncClock(payload ? payload.game_time : null);
      paintLiveCard();
      scheduleDraw();
    }).catch(function (err) {
      state.live.busy = false;
      state.live.error = err && err.message ? err.message : "unavailable";
      state.live.count = 0;
      state.live.reserve = null;
      state.live.reserveName = null;
      paintLiveCard();
    });
  }

  function startLive() {
    state.live.on = true;
    if (els.btnLive) els.btnLive.setAttribute("aria-pressed", "true");
    if (state.live.timer) window.clearInterval(state.live.timer);
    state.live.timer = window.setInterval(pollLive, LIVE_POLL_MS);
    pollLive();
  }

  function stopLive() {
    state.live.on = false;
    if (els.btnLive) els.btnLive.setAttribute("aria-pressed", "false");
    if (state.live.timer) { window.clearInterval(state.live.timer); state.live.timer = 0; }
  }

  function paintLiveCard() {
    if (!els.liveCard) return;
    var live = state.live;
    if (!live.on) { els.liveCard.hidden = true; return; }
    els.liveCard.hidden = false;
    els.liveCount.textContent = String(live.count || 0);

    var meta;
    if (live.error) {
      meta = t("not available — {error}", { error: live.error });
    } else if (live.discovering && !live.count) {
      /* The first sweep over the entity pools takes ~10 s: say so instead of a bare 0. */
      meta = t("looking for the animals around you…");
    } else if (!live.player) {
      meta = t("waiting for the game…");
    } else {
      var bits = [t("you {x}, {z}", { x: Math.round(live.player.x), z: Math.round(live.player.z) })];
      if (live.radius) bits.push(t("within {r} m", { r: Math.round(live.radius) }));
      if (live.age != null) bits.push(t("saved {n} s ago", { n: Math.round(live.age) }));
      meta = bits.join(" \u00b7 ");
    }
    els.liveMeta.textContent = meta;

    /* The entities in memory belong to ONE reserve: the one the game is running. If
       this page shows another, every animal is outside the simulation radius and the
       panel would just read 0 with no explanation — say so, and offer the way there. */
    var mismatch = live.reserve != null && state.reserve.index != null
      && Number(live.reserve) !== Number(state.reserve.index);
    if (els.liveHint) {
      els.liveHint.hidden = !mismatch;
      if (mismatch) {
        var where = live.reserveName || t("Reserve {n}", { n: live.reserve });
        els.liveHintText.textContent = t("The game is running {reserve}.", { reserve: where });
        els.liveHintLink.textContent = t("Open that reserve");
        els.liveHintLink.href = "?reserve=" + encodeURIComponent(live.reserve);
      }
    }

    var animals = (live.animals || []).slice(0, LIVE_ROWS);
    var frag = document.createDocumentFragment();
    for (var i = 0; i < animals.length; i++) {
      var a = animals[i];
      var li = document.createElement("li");
      var sw = document.createElement("span");
      sw.className = "live-swatch";
      sw.style.background = liveColor(a.species);
      var dist = document.createElement("span");
      dist.className = "live-distance";
      dist.textContent = Math.round(a.distance) + " m";
      var name = document.createElement("span");
      name.className = "live-name";
      name.textContent = a.species;
      li.appendChild(sw);
      li.appendChild(dist);
      li.appendChild(name);
      if (a.fur) {
        var furChip = document.createElement("span");
        furChip.className = "live-fur";
        furChip.dataset.fur = a.fur_rarity || "common";
        furChip.textContent = a.fur;
        furChip.title = a.fur + (a.fur_rarity ? " \u00b7 " + (FUR_LABEL[a.fur_rarity] || a.fur_rarity) : "");
        li.appendChild(furChip);
      }
      var alt = document.createElement("span");
      alt.className = "live-altitude";
      alt.textContent = Math.round(a.y) + " m";
      li.appendChild(alt);
      /* Clicking a row flies the map to that animal. */
      li.addEventListener("click", function (animal) {
        return function () { focusOnWorld(animal.x, animal.z); };
      }(a));
      li.title = a.species + " \u00b7 " + Math.round(a.distance) + " m"
        + (a.fur ? " \u00b7 " + a.fur : "") + t(" — click to centre the map");
      frag.appendChild(li);
    }
    els.liveList.textContent = "";
    els.liveList.appendChild(frag);
  }

  /* Species icons on the map: one Image per species, shared and redrawn when it
     finishes loading. Falls back to a plain dot while loading or if it 404s. */
  var liveIconCache = Object.create(null);

  function liveImage(url) {
    if (!url) return null;
    var img = liveIconCache[url];
    if (!img) {
      img = new Image();
      img.addEventListener("load", function () { scheduleDraw(); });
      img.addEventListener("error", function () { img.dataset.failed = "1"; });
      img.src = url;
      liveIconCache[url] = img;
    }
    if (img.dataset && img.dataset.failed) return null;
    return img.complete && img.naturalWidth ? img : null;
  }

  function drawLive(ctx, w, h) {
    var live = state.live;
    if (!live || !live.on || !live.animals.length) return;
    var proj = state.proj;
    var r = clamp(3.4 * clamp(Math.sqrt(w / 1400), 0.85, 1.4), 2.8, 5);
    var iconSize = clamp(r * 2 + 9, 13, 22);

    for (var i = 0; i < live.animals.length; i++) {
      var a = live.animals[i];
      if (!isFinite(a.x) || !isFinite(a.z)) continue;
      var sx = a.x * proj.kx + proj.ox;
      var sy = proj.flip ? proj.oy - a.z * proj.ky : a.z * proj.ky + proj.oy;
      if (sx < -20 || sy < -20 || sx > w + 20 || sy > h + 20) continue;
      var color = liveColor(a.species);
      var img = liveImage(state.iconByName[a.species]);

      ctx.save();
      ctx.translate(sx, sy);

      /* A rare fur gets a halo, the same language the list uses for its chips. */
      if (a.fur_rarity && a.fur_rarity !== "common") {
        var halo = PAL[a.fur_rarity === "great_one" ? "great_one_fur" : a.fur_rarity] || PAL.accent;
        ctx.beginPath();
        ctx.arc(0, 0, iconSize / 2 + 5.5, 0, TAU);
        ctx.lineWidth = 2;
        ctx.strokeStyle = rgba(halo, 0.95);
        ctx.stroke();
      }

      /* halo + ring keep the marker readable on light terrain */
      ctx.beginPath();
      ctx.arc(0, 0, iconSize / 2 + 2, 0, TAU);
      ctx.fillStyle = rgba(color, 0.22);
      ctx.fill();
      ctx.lineWidth = 1;
      ctx.strokeStyle = rgba(color, 0.85);
      ctx.stroke();

      if (img) {
        ctx.drawImage(img, -iconSize / 2, -iconSize / 2, iconSize, iconSize);
      } else {
        ctx.beginPath();
        ctx.arc(0, 0, r, 0, TAU);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.lineWidth = 1;
        ctx.strokeStyle = PAL.ink;
        ctx.stroke();
      }
      ctx.restore();
    }

    /* Where "you" are, so the animal dots can be read as bearings. */
    if (live.player) {
      var px = live.player.x * proj.kx + proj.ox;
      var py = proj.flip ? proj.oy - live.player.z * proj.ky : live.player.z * proj.ky + proj.oy;
      if (px > -30 && py > -30 && px < w + 30 && py < h + 30) {
        ctx.save();
        ctx.translate(px, py);
        ctx.beginPath();
        ctx.arc(0, 0, 7, 0, TAU);
        ctx.strokeStyle = rgba(PAL.text, 0.9);
        ctx.lineWidth = 1.6;
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(0, 0, 2.4, 0, TAU);
        ctx.fillStyle = PAL.text;
        ctx.fill();
        ctx.restore();
      }
    }
  }

  /* Fur catalogue: the save never stores a fur for a living animal, so what we
     can offer is the species' known variants and their rarity, surfaced on the
     species rows instead of invented per-animal data. */
  function applyFurTitles() {
    if (!els.speciesList || !state.furs) return;
    var rows = els.speciesList.querySelectorAll('[data-kind="species"]');
    for (var i = 0; i < rows.length; i++) {
      var name = rows[i].getAttribute("data-value");
      var variants = state.furs[name];
      if (!variants || !variants.length) continue;
      var rare = [];
      for (var j = 0; j < variants.length && rare.length < 4; j++) {
        var rarity = variants[j].rarity;
        if (rarity && rarity !== "common") {
          rare.push(variants[j].name + " (" + (FUR_LABEL[rarity] || String(rarity).replace(/_/g, " ")) + ")");
        }
      }
      if (rare.length) rows[i].title = t("Rare furs: {list}", { list: rare.join(", ") });
    }
  }

  function loadFurs() {
    var idx = state.reserve && state.reserve.index;
    var url = idx == null ? "/api/furs" : "/api/furs?reserve=" + encodeURIComponent(idx);
    fetchJson(url).then(function (payload) {
      state.furs = (payload && payload.species) || {};
      applyFurTitles();
    }).catch(function () { /* the catalogue is optional, never fatal */ });
  }

  function bindLive() {
    if (els.btnLive) {
      els.btnLive.addEventListener("click", function () {
        if (state.live.on) { stopLive(); paintLiveCard(); scheduleDraw(); }
        else startLive();
      });
    }
    if (els.btnLiveHide) {
      els.btnLiveHide.addEventListener("click", function () {
        stopLive();
        paintLiveCard();
        scheduleDraw();
      });
    }
    document.addEventListener("visibilitychange", function () {
      if (!state.live.on) return;
      if (document.hidden) {
        if (state.live.timer) { window.clearInterval(state.live.timer); state.live.timer = 0; }
      } else if (!state.live.timer) {
        state.live.timer = window.setInterval(pollLive, LIVE_POLL_MS);
        pollLive();
      }
    });
  }

  /* ======================================================================== *
   * 15. Map layers and planning panels
   *
   * Three additions that reuse data the app already had but never showed:
   *  - hunting pressure (`HuntingPressureMap` in the save, 256x256, the same
   *    blue alert zones the game paints);
   *  - a trail layer, accumulating the live radar's positions so the map shows
   *    where animals actually are over a session, which no save file contains;
   *  - the in-game hour planner and a reserve comparison for one species.
   * ======================================================================== */

  var TRAILS_KEY = "cotw.trails";
  var TRAILS_GRID = 256;

  /* The pressure grid's world mapping was fitted from two real in-game alert zones. Both
     now land on cells that carry pressure, and the resulting blobs sit on the lakes — an
     independent check, since the lakes played no part in the fit. Reserves without a
     fitted transform still fall back to the old "stretch over the map box" guess, so the
     warning stays for them. */
  var pressureWarned = false;

  function showPressureWarning() {
    if (pressureWarned) return;
    pressureWarned = true;
    showPersistentNote(t("Hunting pressure has no measured placement for this reserve yet — its position is a rough guess. Silver Ridge Peaks is calibrated."));
  }

  function selectedSpecies() {
    var table = state.filters && state.filters.species;
    if (!table) return null;
    var found = null;
    for (var name in table) {
      if (!table[name]) continue;
      if (found) return null; // more than one species ticked
      found = name;
    }
    return found;
  }

  /* -- hunting pressure -------------------------------------------------- */
  function loadPressure() {
    var index = state.reserve && state.reserve.index;
    var url = "/api/pressure" + (index == null ? "" : "?reserve=" + encodeURIComponent(index));
    fetchJson(url).then(function (payload) {
      state.pressure = payload && payload.cells ? payload : { cells: [], max: 0 };
      scheduleDraw();
    }).catch(function () {
      state.pressure = { cells: [], max: 0 };
    });
  }

  function drawPressure(ctx, w, h) {
    if (!state.showPressure) return;
    var cells = state.pressure && state.pressure.cells;
    if (!cells || !cells.length) return;
    if (!state.pressure.calibrated) {
      showPressureWarning();
    }
    var proj = state.proj;
    var peak = Math.max(1, (state.pressure && state.pressure.max) || 1);
    var span = state.world ? (state.world.maxX - state.world.minX) : 0;
    var radius = span > 0 ? clamp(Math.abs(proj.kx) * (span / 256) * 1.6, 5, 90) : 12;

    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (var i = 0; i < cells.length; i++) {
      var cell = cells[i];
      var sx = cell[0] * proj.kx + proj.ox;
      var sy = proj.flip ? proj.oy - cell[1] * proj.ky : cell[1] * proj.ky + proj.oy;
      if (sx < -radius || sy < -radius || sx > w + radius || sy > h + radius) continue;
      var intensity = clamp(cell[2] / peak, 0, 1);
      var gradient = ctx.createRadialGradient(sx, sy, 0, sx, sy, radius);
      gradient.addColorStop(0, "rgba(96,156,255," + (0.06 + intensity * 0.26).toFixed(3) + ")");
      gradient.addColorStop(1, "rgba(96,156,255,0)");
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(sx, sy, radius, 0, TAU);
      ctx.fill();
    }
    ctx.restore();
  }

  /* -- observation trails ------------------------------------------------ */
  function loadTrails() {
    if (state.trails) return;
    try {
      var raw = localStorage.getItem(TRAILS_KEY);
      state.trails = raw ? JSON.parse(raw) : {};
    } catch (e) {
      state.trails = {};
    }
    if (!state.trails || typeof state.trails !== "object") state.trails = {};
  }

  function saveTrails() {
    if (!state.trails || !state.trailsDirty) return;
    try {
      localStorage.setItem(TRAILS_KEY, JSON.stringify(state.trails));
      state.trailsDirty = false;
    } catch (e) { /* quota exceeded: keep the session's trails in memory only */ }
  }

  function trailGrid() {
    loadTrails();
    var key = String((state.reserve && state.reserve.index) || "?");
    if (!state.trails[key]) state.trails[key] = {};
    return state.trails[key];
  }

  function recordTrails(animals) {
    if (!state.showTrails || !animals || !animals.length) return;
    var box = state.world;
    if (!box || !(box.maxX > box.minX) || !(box.maxY > box.minY)) return;
    var grid = trailGrid();
    var added = 0;
    for (var i = 0; i < animals.length; i++) {
      var animal = animals[i];
      var col = Math.floor((animal.x - box.minX) / (box.maxX - box.minX) * TRAILS_GRID);
      var row = Math.floor((animal.z - box.minY) / (box.maxY - box.minY) * TRAILS_GRID);
      if (!(col >= 0 && col < TRAILS_GRID && row >= 0 && row < TRAILS_GRID)) continue;
      var key = row * TRAILS_GRID + col;
      grid[key] = (grid[key] || 0) + 1;
      added++;
    }
    if (added) state.trailsDirty = true;
  }

  function drawTrails(ctx, w, h) {
    if (!state.showTrails) return;
    loadTrails();
    var key = String((state.reserve && state.reserve.index) || "?");
    var grid = state.trails && state.trails[key];
    if (!grid) return;
    var box = state.world;
    if (!box) return;

    var keys = Object.keys(grid);
    if (!keys.length) return;
    var peak = 1;
    for (var k = 0; k < keys.length; k++) peak = Math.max(peak, grid[keys[k]]);

    var proj = state.proj;
    var radius = clamp(Math.abs(proj.kx) * ((box.maxX - box.minX) / TRAILS_GRID) * 2.2, 4, 60);
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (var i = 0; i < keys.length; i++) {
      var cell = parseInt(keys[i], 10);
      if (!isFinite(cell)) continue;
      var row = Math.floor(cell / TRAILS_GRID);
      var col = cell % TRAILS_GRID;
      var x = box.minX + (col + 0.5) / TRAILS_GRID * (box.maxX - box.minX);
      var z = box.minY + (row + 0.5) / TRAILS_GRID * (box.maxY - box.minY);
      var sx = x * proj.kx + proj.ox;
      var sy = proj.flip ? proj.oy - z * proj.ky : z * proj.ky + proj.oy;
      if (sx < -radius || sy < -radius || sx > w + radius || sy > h + radius) continue;
      var heat = clamp(grid[keys[i]] / peak, 0, 1);
      var gradient = ctx.createRadialGradient(sx, sy, 0, sx, sy, radius);
      gradient.addColorStop(0, "rgba(232,163,61," + (0.05 + heat * 0.30).toFixed(3) + ")");
      gradient.addColorStop(1, "rgba(232,163,61,0)");
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(sx, sy, radius, 0, TAU);
      ctx.fill();
    }
    ctx.restore();
  }

  /* -- centre the map on a world point ----------------------------------- */
  function focusOnWorld(x, z) {
    if (!isFinite(x) || !isFinite(z)) return;
    var box = state.world;
    if (!box) return;
    setLimits();
    var scale = clamp(state.cam.fit * 3.4, state.cam.min, state.cam.max);
    var kx = state.img.w / (box.maxX - box.minX);
    var ky = state.img.h / (box.maxY - box.minY);
    var px = (x - box.minX) * kx;
    var py = (z - box.minY) * ky;
    state.userMoved = true;
    animateCamera(scale, state.view.w / 2 - px * scale, state.view.h / 2 - py * scale, 360);
  }

  /* -- active hours for one species -------------------------------------- */
  function windowLabel(zone) {
    var start = zone.startHour == null ? null : zone.startHour;
    var end = zone.endHour == null ? null : zone.endHour;
    if (start == null || end == null) return null;
    return formatHour(start) + "\u2013" + formatHour(end);
  }

  function renderHours() {
    if (!els.hoursList) return;
    els.hoursList.textContent = "";
    var name = selectedSpecies();
    els.hoursSpecies.textContent = name || "\u2014";
    els.hoursHint.hidden = !!name;
    if (!name) return;

    var windows = { feed: {}, drink: {}, rest: {} };
    for (var i = 0; i < state.zones.length; i++) {
      var zone = state.zones[i];
      if (zone.rosterName !== name) continue;
      var label = windowLabel(zone);
      if (!label) continue;
      var bag = windows[zone.type] || windows.rest;
      bag[label] = (bag[label] || 0) + 1;
    }

    var frag = document.createDocumentFragment();
    for (var ti = 0; ti < TYPES.length; ti++) {
      var type = TYPES[ti];
      var entries = Object.keys(windows[type] || {});
      if (!entries.length) continue;
      entries.sort(function (a, b) { return windows[type][b] - windows[type][a]; });
      var li = el("li", "hours-row");
      var glyph = el("i", "zglyph");
      glyph.dataset.zone = type;
      glyph.setAttribute("aria-hidden", "true");
      li.appendChild(glyph);
      li.appendChild(el("span", "hours-type", TYPE_LABEL[type] || type));
      li.appendChild(el("span", "hours-window", entries[0]));
      li.appendChild(el("span", "hours-count", entries.length > 1
        ? "+" + (entries.length - 1) : String(windows[type][entries[0]])));
      li.title = entries.map(function (label) {
        return label + " (" + windows[type][label] + ")";
      }).join(", ");
      frag.appendChild(li);
    }
    els.hoursList.appendChild(frag);
    if (!frag.childNodes.length) {
      els.hoursList.appendChild(el("li", "hours-row hours-empty", t("No zone for this species")));
    }
  }

  /* -- which reserve is best for one species ----------------------------- */
  function renderCompare() {
    if (!els.compareList) return;
    els.compareList.textContent = "";
    var name = selectedSpecies();
    els.compareHint.hidden = !!name;
    els.comparePanel.dataset.species = name || "";
    if (!name) { state.compare = null; return; }

    var url = "/api/compare?species=" + encodeURIComponent(name);
    fetchJson(url).then(function (payload) {
      if (selectedSpecies() !== name) return; // selection changed meanwhile
      var rows = (payload && payload.reserves) || [];
      els.compareList.textContent = "";
      var frag = document.createDocumentFragment();
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        var li = el("li", "compare-row");
        li.dataset.reserve = row.reserve;
        var medals = row.medals || {};
        li.appendChild(el("span", "compare-name", row.name));
        li.appendChild(el("span", "compare-total", String(row.total)));
        var diamond = medals.diamond || 0;
        var gold = medals.gold || 0;
        li.appendChild(el("span", "compare-medal", "\u25c6 " + diamond));
        li.appendChild(el("span", "compare-medal", "\u25cf " + gold));
        li.title = t("{name}: {total} animals, {diamond} diamond, {gold} gold",
          { name: row.name, total: row.total, diamond: diamond, gold: gold });
        frag.appendChild(li);
      }
      els.compareList.appendChild(frag);
      if (!frag.childNodes.length) {
        els.compareList.appendChild(el("li", "compare-row", t("No reserve has this species")));
      }
    }).catch(function () { /* the panel is optional */ });
  }

  /* -- harvested animals ------------------------------------------------- */
  function renderHarvests() {
    if (!els.harvestList) return;
    var rows = state.harvests;
    if (!rows) {
      fetchJson("/api/harvests").then(function (payload) {
        state.harvests = (payload && payload.harvests) || [];
        renderHarvests();
      }).catch(function () { state.harvests = []; renderHarvests(); });
      return;
    }
    els.harvestList.textContent = "";
    els.harvestCount.textContent = String(rows.length);
    els.harvestHint.hidden = rows.length > 0;
    var frag = document.createDocumentFragment();
    for (var i = 0; i < rows.length && i < 20; i++) {
      var row = rows[i];
      var li = el("li", "harvest-row");
      li.appendChild(el("span", "harvest-species", row.species || "?"));
      if (row.fur) {
        var chip = el("span", "live-fur", row.fur);
        chip.dataset.fur = row.fur_rarity || "common";
        li.appendChild(chip);
      }
      li.appendChild(el("span", "harvest-score", num(row.score == null ? null : Number(row.score), 2)));
      var when = row.timestamp ? String(row.timestamp).slice(0, 16).replace("T", " ") : "";
      li.appendChild(el("span", "harvest-time", when));
      li.title = (row.species || "") + (row.fur ? " \u00b7 " + row.fur : "")
        + (row.score != null ? " \u00b7 " + num(Number(row.score), 2) : "");
      frag.appendChild(li);
    }
    els.harvestList.appendChild(frag);
  }

  function bindLayers() {
    function toggle(button, key, reload) {
      if (!button) return;
      button.setAttribute("aria-pressed", state[key] ? "true" : "false");
      button.addEventListener("click", function () {
        state[key] = !state[key];
        button.setAttribute("aria-pressed", state[key] ? "true" : "false");
        if (reload && state[key]) reload();
        scheduleDraw();
      });
    }
    toggle(els.btnPressure, "showPressure", function () {
      if (!state.pressure || !state.pressure.cells || !state.pressure.cells.length) loadPressure();
    });
    toggle(els.btnTrails, "showTrails", null);

    if (els.btnRoute) {
      els.btnRoute.setAttribute("aria-pressed", "false");
      els.btnRoute.addEventListener("click", function () {
        state.routeMode = !state.routeMode;
        els.btnRoute.setAttribute("aria-pressed", state.routeMode ? "true" : "false");
        if (state.routeMode) planRoute();
        else state.route = null;
        scheduleDraw();
      });
    }

    if (els.btnMeasure) {
      els.btnMeasure.setAttribute("aria-pressed", "false");
      els.btnMeasure.addEventListener("click", function () {
        state.measureMode = !state.measureMode;
        els.btnMeasure.setAttribute("aria-pressed", state.measureMode ? "true" : "false");
        if (!state.measureMode) state.measure = null;
        else state.measure = { a: null, b: null, distance: 0, bearing: 0 };
        scheduleDraw();
      });
    }

    if (els.btnNearby) {
      els.btnNearby.setAttribute("aria-pressed", "false");
      els.btnNearby.addEventListener("click", function () {
        state.nearby = !state.nearby;
        if (!state.nearbySeen) state.nearbySeen = Object.create(null);
        els.btnNearby.setAttribute("aria-pressed", state.nearby ? "true" : "false");
      });
    }

    if (els.btnCsv) els.btnCsv.addEventListener("click", exportCsv);

    /* Measure tool: a click that did not pan the map drops a point. */
    if (els.mapWrap) {
      var downAt = null;
      els.mapWrap.addEventListener("pointerdown", function (e) {
        downAt = { x: e.clientX, y: e.clientY };
      });
      els.mapWrap.addEventListener("pointerup", function (e) {
        if (!state.measureMode || !downAt) { downAt = null; return; }
        var moved = Math.abs(e.clientX - downAt.x) + Math.abs(e.clientY - downAt.y);
        downAt = null;
        if (moved > 5) return;
        var local = localPoint(e);
        measurePoint(worldAt(local.x, local.y));
      });
    }

    window.setInterval(saveTrails, 15000);
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) saveTrails();
    });
    window.addEventListener("beforeunload", saveTrails);
  }

  /* -- alerts on new diamonds and great ones ----------------------------- */
  var ALERT_POLL_MS = 5000;

  function alertLabel(alert) {
    if (alert.reason === "great_one") return MEDAL_LABEL.great_one;
    if (alert.reason === "nearby") return t("Animal nearby");
    return MEDAL_LABEL.diamond;
  }

  function showAlertToast(alert) {
    if (!els.alertToast) return;
    els.alertTitle.textContent = t("{kind} detected", { kind: alertLabel(alert) })
      + " \u2014 " + alert.species;
    var bits = [alert.reserve_name];
    if (alert.fur) bits.push(alert.fur);
    if (alert.score != null) bits.push(t("TR {score}", { score: num(Number(alert.score), 2) }));
    els.alertDetail.textContent = bits.join(" \u00b7 ");
    els.alertToast.dataset.reason = alert.reason;
    els.alertToast.hidden = false;
    window.clearTimeout(showAlertToast.timer);
    showAlertToast.timer = window.setTimeout(function () {
      els.alertToast.hidden = true;
    }, 12000);
    /* A background tab still deserves to be noticed. */
    if (document.hidden) {
      state.titleAlert = t("{kind} detected", { kind: alertLabel(alert) })
        + " \u2014 " + alert.species;
      document.title = "\u26a0 " + state.titleAlert;
    }
  }

  function renderAlerts(rows) {
    if (!els.alertsList) return;
    els.alertsList.textContent = "";
    els.alertsCount.textContent = String(rows.length);
    var frag = document.createDocumentFragment();
    for (var i = 0; i < rows.length && i < 20; i++) {
      var alert = rows[i];
      var li = el("li", "alert-row");
      li.dataset.reason = alert.reason;
      li.appendChild(el("span", "alert-kind", alertLabel(alert)));
      li.appendChild(el("span", "alert-species", alert.species));
      li.appendChild(el("span", "alert-score", num(alert.score == null ? null : Number(alert.score), 2)));
      var when = new Date((alert.seen_at || 0) * 1000);
      li.appendChild(el("span", "alert-when",
        isNaN(when.getTime()) ? "" : when.toTimeString().slice(0, 5)));
      li.title = alert.reserve_name + (alert.fur ? " \u00b7 " + alert.fur : "");
      frag.appendChild(li);
    }
    els.alertsList.appendChild(frag);
  }

  function pollAlerts() {
    fetchJson("/api/alerts").then(function (payload) {
      var rows = (payload && payload.alerts) || [];
      if (els.alertsMeta) {
        var watched = payload && payload.reserves_watched;
        els.alertsMeta.textContent = watched
          ? t("Watching {n} reserve(s) · checks every {s} s",
            { n: watched, s: Math.round(payload.poll_seconds || 20) })
          : t("Waiting for a populated save…");
      }
      var newest = rows.length ? rows[0].id : 0;
      if (state.lastAlertId == null) {
        state.lastAlertId = newest; // first load: no toast for history
      } else if (newest > state.lastAlertId) {
        showAlertToast(rows[0]);
        state.lastAlertId = newest;
      }
      renderAlerts(rows);
      if (payload && payload.changes) renderChanges(payload.changes);
      /* Which animals are new since the previous scan of the save file. */
      applySpawns(payload ? payload.spawns : null);
      /* The save changed: reload the population so the list is never stale. */
      var version = payload && payload.data_version;
      if (version != null) {
        if (state.dataVersion != null && version !== state.dataVersion) refreshData();
        state.dataVersion = version;
      }
    }).catch(function () { /* alerts are optional */ });
  }

  function bindAlerts() {
    pollAlerts();
    window.setInterval(pollAlerts, ALERT_POLL_MS);
    if (els.alertClose) {
      els.alertClose.addEventListener("click", function () {
        els.alertToast.hidden = true;
      });
    }
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden && state.titleAlert) {
        document.title = state.baseTitle || document.title.replace(/^\u26a0\s*/, "");
        state.titleAlert = null;
      }
    });
  }

  /* ======================================================================== *
   * 16. Delta, route, measure, proximity, CSV, history, auto-refresh
   * ======================================================================== */

  /* -- reload the population when the save changes ------------------------ */
  async function refreshData() {
    if (state.refreshing) return;
    state.refreshing = true;
    try {
      var loaded = await loadAll();
      if (!loaded.population) return;
      var pop = normalisePopulation(loaded.population);
      var zones = normaliseZones(loaded.zones, pop.world);

      /* carry the user's selections across the swap */
      var keep = state.filters;
      var keepSpecies = keep ? keep.species : null;
      var keepMedals = keep ? keep.medals : null;
      var keepFurs = keep ? keep.furs : null;
      var keepTypes = keep ? keep.zoneTypes : null;
      var keepGender = keep ? keep.gender : "all";
      var keepSearch = keep ? keep.search : "";

      state.animals = pop.animals;
      state.species = pop.species;
      state.reserve = {
        index: pop.reserve.index != null ? pop.reserve.index : zones.reserve.index,
        name: zones.reserve.name || pop.reserve.name,
        confidence: zones.reserve.confidence
      };
      state.world = zones.world;
      state.zones = zones.zones;
      state.generatedAt = pop.generatedAt;

      state.byId = Object.create(null);
      state.speciesByLower = Object.create(null);
      state.iconByName = Object.create(null);
      for (var s = 0; s < state.species.length; s++) {
        var sp = state.species[s];
        state.speciesByLower[sp.name.toLowerCase().trim()] = sp.name;
        state.iconByName[sp.name] = iconSrc(sp.icon);
      }
      for (var i = 0; i < state.animals.length; i++) {
        var animal = state.animals[i];
        state.byId[animal.id] = animal;
        for (var s2 = 0; s2 < state.species.length; s2++) {
          if (state.species[s2].name === animal.species) { animal.icon = state.species[s2].icon; break; }
        }
      }
      for (var z = 0; z < state.zones.length; z++) {
        var zone = state.zones[z];
        zone.rosterName = zone.animal
          ? (state.speciesByLower[zone.animal.toLowerCase().trim()] || null) : null;
      }

      state.filters = defaultFilters(state.species);
      var key;
      if (keepSpecies) for (key in state.filters.species) {
        if (keepSpecies[key] === false) state.filters.species[key] = false;
      }
      if (keepMedals) for (key in state.filters.medals) {
        if (keepMedals[key] === false) state.filters.medals[key] = false;
      }
      if (keepFurs) for (key in state.filters.furs) {
        if (keepFurs[key] === false) state.filters.furs[key] = false;
      }
      if (keepTypes) for (key in state.filters.zoneTypes) {
        if (keepTypes[key] === false) state.filters.zoneTypes[key] = false;
      }
      state.filters.gender = keepGender;
      state.filters.search = keepSearch;

      buildZoneTypeList();
      buildSpeciesList();
      buildMedalList();
      buildFurList();
      syncFilterInputs();
      applyMedalAvailability();
      setHeader();
      applyPopulationFilters();
      applyZoneFilters();
      renderBadges();
      scheduleDraw();
    } catch (err) {
      /* a failed refresh must never break the page already on screen */
    } finally {
      state.refreshing = false;
    }
  }

  /* -- what changed since the previous scan ------------------------------- */
  function renderChanges(changes) {
    if (!els.changesList) return;
    els.changesList.textContent = "";
    var appeared = (changes && changes.appeared) || [];
    var gone = (changes && changes.disappeared) || [];
    var all = [];
    for (var i = 0; i < appeared.length; i++) all.push({ row: appeared[i], dir: "in" });
    for (var j = 0; j < gone.length; j++) all.push({ row: gone[j], dir: "out" });
    els.changesHint.hidden = all.length > 0;
    var frag = document.createDocumentFragment();
    for (var k = 0; k < all.length && k < 20; k++) {
      var entry = all[k];
      var row = entry.row;
      var li = el("li", "alert-row");
      li.dataset.direction = entry.dir;
      li.appendChild(el("span", "alert-kind", entry.dir === "in" ? t("new") : t("gone")));
      li.appendChild(el("span", "alert-species", row.species || "?"));
      li.appendChild(el("span", "alert-score", num(row.score == null ? null : Number(row.score), 2)));
      li.appendChild(el("span", "alert-when", row.medal || ""));
      li.title = (row.reserve_name || "") + (row.fur ? " \u00b7 " + row.fur : "");
      frag.appendChild(li);
    }
    els.changesList.appendChild(frag);
  }

  /* -- route planner ------------------------------------------------------ */
  function tourDistance(points, start) {
    var total = 0;
    var cur = start;
    for (var i = 0; i < points.length; i++) {
      total += Math.hypot(points[i].x - cur.x, points[i].z - cur.z);
      cur = points[i];
    }
    return total;
  }

  function planRoute() {
    var zones = (state.visibleZones || []).filter(function (z) { return z.active; });
    if (zones.length < 2) zones = (state.visibleZones || []).slice();
    var start = state.live && state.live.player ? state.live.player : null;
    if (!start) { showPersistentNote(t("No player position yet — is the game running?")); return; }
    if (!zones.length) { showPersistentNote(t("No zone to visit with the current filters.")); return; }

    var limit = Math.min(zones.length, 10);
    var remaining = zones.slice();
    var order = [];
    var cur = { x: start.x, z: start.z };
    while (remaining.length && order.length < limit) {
      var best = 0;
      var bestDistance = Infinity;
      for (var i = 0; i < remaining.length; i++) {
        var d = Math.hypot(remaining[i].x - cur.x, remaining[i].z - cur.z);
        if (d < bestDistance) { bestDistance = d; best = i; }
      }
      var pick = remaining.splice(best, 1)[0];
      order.push(pick);
      cur = pick;
    }

    /* 2-opt: cheap and enough for ten stops */
    var improved = true;
    var guard = 0;
    while (improved && guard++ < 40) {
      improved = false;
      for (var a = 1; a < order.length - 1; a++) {
        for (var b = a + 1; b < order.length; b++) {
          var trial = order.slice(0, a).concat(order.slice(a, b + 1).reverse(), order.slice(b + 1));
          if (tourDistance(trial, start) + 1e-9 < tourDistance(order, start)) {
            order = trial;
            improved = true;
          }
        }
      }
    }

    state.route = {
      points: order,
      distance: tourDistance(order, start),
      start: { x: start.x, z: start.z }
    };
    scheduleDraw();
  }

  function drawRoute(ctx, w, h) {
    if (!state.route || !state.route.points.length) return;
    var points = state.route.points;

    ctx.save();
    ctx.beginPath();
    var first = screenOf(state.route.start.x, state.route.start.z);
    ctx.moveTo(first.x, first.y);
    for (var i = 0; i < points.length; i++) {
      var s = screenOf(points[i].x, points[i].z);
      ctx.lineTo(s.x, s.y);
    }
    ctx.strokeStyle = rgba(PAL.text, 0.55);
    ctx.lineWidth = 1.6;
    ctx.setLineDash([5, 4]);
    ctx.stroke();
    ctx.setLineDash([]);

    for (var j = 0; j < points.length; j++) {
      var sp = screenOf(points[j].x, points[j].z);
      if (sp.x < -20 || sp.y < -20 || sp.x > w + 20 || sp.y > h + 20) continue;
      ctx.beginPath();
      ctx.arc(sp.x, sp.y, 9, 0, TAU);
      ctx.fillStyle = rgba(PAL.accent, 0.92);
      ctx.fill();
      ctx.lineWidth = 1.2;
      ctx.strokeStyle = PAL.ink;
      ctx.stroke();
      ctx.fillStyle = PAL.ink;
      ctx.font = "600 10px " + FONT_STACK;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(j + 1), sp.x, sp.y + 0.5);
    }
    ctx.restore();
  }

  /* -- measure tool ------------------------------------------------------- */
  function drawMeasure(ctx, w, h) {
    var measure = state.measure;
    if (!measure || !measure.a) return;
    var a = screenOf(measure.a.x, measure.a.z);
    var b = measure.b ? screenOf(measure.b.x, measure.b.z) : null;
    ctx.save();
    ctx.beginPath();
    ctx.arc(a.x, a.y, 5, 0, TAU);
    ctx.fillStyle = PAL.accent;
    ctx.fill();
    if (b) {
      ctx.beginPath();
      ctx.arc(b.x, b.y, 5, 0, TAU);
      ctx.fillStyle = PAL.accent;
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = rgba(PAL.accent, 0.9);
      ctx.lineWidth = 1.8;
      ctx.stroke();
      var mx = (a.x + b.x) / 2;
      var my = (a.y + b.y) / 2;
      var label = Math.round(measure.distance) + " m \u00b7 " + Math.round(measure.bearing) + "\u00b0";
      ctx.font = "600 11px " + FONT_STACK;
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      var width = ctx.measureText(label).width;
      ctx.fillStyle = rgba(PAL.ink, 0.85);
      roundRectPath(ctx, mx - width / 2 - 6, my - 20, width + 12, 17, 5);
      ctx.fill();
      ctx.fillStyle = PAL.accent;
      ctx.fillText(label, mx, my - 5);
    }
    ctx.restore();
  }

  function measurePoint(world) {
    if (!world) return;
    var previous = state.measure && state.measure.a && !state.measure.b ? state.measure : { a: null, b: null };
    if (!previous.a) {
      state.measure = { a: world, b: null, distance: 0, bearing: 0 };
    } else {
      var dx = world.x - previous.a.x;
      var dz = world.z - previous.a.z;
      var bearing = (Math.atan2(dx, -dz) * 180 / Math.PI + 360) % 360;
      state.measure = {
        a: previous.a, b: world,
        distance: Math.hypot(dx, dz), bearing: bearing
      };
    }
    scheduleDraw();
  }

  /* -- proximity alerts --------------------------------------------------- */
  function checkProximity(animals) {
    if (!state.nearby) return;
    var now = Date.now();
    for (var i = 0; i < animals.length; i++) {
      var animal = animals[i];
      if (!(animal.distance <= NEARBY_RADIUS)) continue;
      var key = animal.hash_address || (animal.species + ":" + Math.round(animal.x) + ":" + Math.round(animal.z));
      var last = state.nearbySeen[key] || 0;
      if (now - last < NEARBY_COOLDOWN_MS) continue;
      state.nearbySeen[key] = now;
      showAlertToast({
        reason: "nearby",
        species: animal.species,
        reserve_name: t("{n} m away", { n: Math.round(animal.distance) }),
        fur: animal.fur,
        score: null
      });
      break; // one banner at a time
    }
  }

  /* -- player trail ------------------------------------------------------- */
  function loadPlayerTrail() {
    if (state.playerTrail) return;
    try {
      var raw = localStorage.getItem(TRAILS_KEY + ".player");
      state.playerTrail = raw ? JSON.parse(raw) : {};
    } catch (e) {
      state.playerTrail = {};
    }
    if (!state.playerTrail || typeof state.playerTrail !== "object") state.playerTrail = {};
  }

  function recordPlayerTrail(player) {
    if (!state.showTrails || !player || !state.world) return;
    loadPlayerTrail();
    var key = String((state.reserve && state.reserve.index) || "?");
    if (!state.playerTrail[key]) state.playerTrail[key] = {};
    var box = state.world;
    var col = Math.floor((player.x - box.minX) / (box.maxX - box.minX) * TRAILS_GRID);
    var row = Math.floor((player.z - box.minY) / (box.maxY - box.minY) * TRAILS_GRID);
    if (!(col >= 0 && col < TRAILS_GRID && row >= 0 && row < TRAILS_GRID)) return;
    var cell = row * TRAILS_GRID + col;
    if (state.playerTrail[key][cell]) return;
    state.playerTrail[key][cell] = 1;
    try {
      localStorage.setItem(TRAILS_KEY + ".player", JSON.stringify(state.playerTrail));
    } catch (e) { /* ignore */ }
  }

  function drawPlayerTrail(ctx, w, h) {
    if (!state.showTrails) return;
    loadPlayerTrail();
    var key = String((state.reserve && state.reserve.index) || "?");
    var grid = state.playerTrail[key];
    if (!grid || !state.world) return;
    var cells = Object.keys(grid);
    if (!cells.length) return;
    var box = state.world;
    var proj = state.proj;
    var radius = clamp(Math.abs(proj.kx) * ((box.maxX - box.minX) / TRAILS_GRID) * 1.4, 3, 26);
    ctx.save();
    for (var i = 0; i < cells.length; i++) {
      var cell = parseInt(cells[i], 10);
      if (!isFinite(cell)) continue;
      var row = Math.floor(cell / TRAILS_GRID);
      var col = cell % TRAILS_GRID;
      var x = box.minX + (col + 0.5) / TRAILS_GRID * (box.maxX - box.minX);
      var z = box.minY + (row + 0.5) / TRAILS_GRID * (box.maxY - box.minY);
      var sx = x * proj.kx + proj.ox;
      var sy = proj.flip ? proj.oy - z * proj.ky : z * proj.ky + proj.oy;
      if (sx < -radius || sy < -radius || sx > w + radius || sy > h + radius) continue;
      ctx.beginPath();
      ctx.arc(sx, sy, radius, 0, TAU);
      ctx.fillStyle = rgba(PAL.text, 0.10);
      ctx.fill();
    }
    ctx.restore();
  }

  /* -- CSV export --------------------------------------------------------- */
  function exportCsv() {
    var rows = state.filtered || [];
    var header = ["species", "gender", "weight_kg", "score", "trophy_rating",
                  "medal", "fur", "fur_rarity", "seed", "group", "spawn_area"];
    var lines = [header.join(",")];
    function cell(value) {
      if (value == null) return "";
      var text = String(value);
      return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
    }
    for (var i = 0; i < rows.length; i++) {
      var a = rows[i];
      lines.push([
        cell(a.species), cell(a.gender),
        a.weight == null ? "" : a.weight.toFixed(3),
        a.score == null ? "" : a.score.toFixed(4),
        a.trophy == null ? "" : String(a.trophy),
        cell(a.medal), cell(a.fur), cell(a.furRarity),
        cell(a.seed), cell(a.group), cell(a.spawnArea)
      ].join(","));
    }
    try {
      var blob = new Blob([lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
      var url = URL.createObjectURL(blob);
      var link = document.createElement("a");
      link.href = url;
      link.download = "cotw-" + ((state.reserve && state.reserve.name) || "animals")
        .replace(/[^a-z0-9]+/gi, "-").toLowerCase() + ".csv";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
    } catch (e) {
      showPersistentNote(t("CSV export is not available in this browser."));
    }
  }

  /* -- daily history ------------------------------------------------------ */
  function renderHistory() {
    if (!els.historyList) return;
    var index = state.reserve && state.reserve.index;
    var url = "/api/history" + (index == null ? "" : "?reserve=" + encodeURIComponent(index));
    fetchJson(url).then(function (payload) {
      var points = (payload && payload.points) || [];
      els.historyList.textContent = "";
      els.historyCount.textContent = String(points.length);
      els.historyHint.hidden = points.length > 0;
      var frag = document.createDocumentFragment();
      for (var i = points.length - 1; i >= 0 && i >= points.length - 20; i--) {
        var point = points[i];
        var li = el("li", "history-row");
        li.appendChild(el("span", "history-date", point.date || ""));
        li.appendChild(el("span", "history-total", String(point.total)));
        li.appendChild(el("span", "history-medal", "\u25c6 " + (point.diamonds || 0)));
        li.appendChild(el("span", "history-medal", "\u25cf " + (point.golds || 0)));
        frag.appendChild(li);
      }
      els.historyList.appendChild(frag);
    }).catch(function () {
      els.historyHint.hidden = false;
    });
  }

  function bootSafely() {
    boot().catch(function (err) {
      console.warn("[waypoint] startup failed:", err && err.stack ? err.stack : err);
      try { fatal(t("Startup failed: {message}", { message: err && err.message ? err.message : t("unknown error") })); }
      catch (e) { /* nothing left to report with */ }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootSafely);
  } else {
    bootSafely();
  }
})();
