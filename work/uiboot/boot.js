/* Boot the real web UI inside jsdom against the live API.
 *
 * There is no browser on this machine, so this is the closest thing to actually
 * opening the page: it loads index.html, stubs the canvas 2D context, replays the
 * fetch calls from the running Python server, executes the real scripts in order,
 * then asserts that the app booted without errors and populated the DOM.
 *
 * The interface ships in French (reference) and English (source). Run this twice
 * to cover both:
 *
 *   node work/uiboot/boot.js                      # French (default)
 *   COTW_LOCALE=en node work/uiboot/boot.js       # English
 *
 * Run:  node work/uiboot/boot.js
 */
const fs = require("fs");
const path = require("path");
const http = require("http");
const { JSDOM } = require("jsdom");

const WEB = path.resolve(__dirname, "..", "..", "web");
const BASE = "http://127.0.0.1:8791";
const LOCALE = process.env.COTW_LOCALE === "en" ? "en" : "fr";

/* What the chrome must say in this language, plus what it must NOT say (a
   leftover in the other language is exactly the "half translated" bug). */
const EXPECT = {
  fr: {
    fitMap: "Ajuster la carte",
    needZones: "Zones de besoin",
    resetFilters: "Réinitialiser les filtres",
    hideScripted: "Masquer les animaux scriptés",
    scanned: "population scannée",
    activeWord: "actives",
    decimal: ",",
    forbidden: [
      "Fit map", "Fit zones", "Need zones", "Active hours", "Hide scripted animals",
      "Hide great ones", "Reset all filters", "scanned population", "Where to hunt",
      "Live animals", "Reading population and zones", "Search species",
    ],
  },
  en: {
    fitMap: "Fit map",
    needZones: "Need zones",
    resetFilters: "Reset all filters",
    hideScripted: "Hide scripted animals",
    scanned: "scanned population",
    activeWord: "active",
    decimal: ".",
    forbidden: [
      "Ajuster la carte", "Zones de besoin", "Heures d'activité", "Masquer les animaux",
      "Réinitialiser les filtres", "population scannée", "Où chasser", "Animaux en direct",
      "Lecture de la population", "Rechercher une espèce",
    ],
  },
};
const WANT = EXPECT[LOCALE];

function getJson(urlPath) {
  return new Promise((resolve, reject) => {
    http
      .get(BASE + urlPath, (res) => {
        let body = "";
        res.on("data", (c) => (body += c));
        res.on("end", () => {
          try {
            resolve({ ok: res.statusCode === 200, status: res.statusCode, json: JSON.parse(body) });
          } catch (e) {
            resolve({ ok: false, status: res.statusCode, json: null, error: String(e) });
          }
        });
      })
      .on("error", reject);
  });
}

function canvasContextStub() {
  const noop = () => {};
  const target = { canvas: null };
  return new Proxy(target, {
    get(t, k) {
      if (k in t) return t[k];
      if (k === "measureText") return () => ({ width: 12, actualBoundingBoxAscent: 8 });
      if (k === "createLinearGradient" || k === "createRadialGradient")
        return () => ({ addColorStop: noop });
      if (k === "getImageData") return () => ({ data: new Uint8ClampedArray(4), width: 1, height: 1 });
      if (k === "createPattern") return () => null;
      if (k === "isPointInPath") return () => false;
      return noop;
    },
    set(t, k, v) {
      t[k] = v;
      return true;
    },
  });
}

async function main() {
  const html = fs.readFileSync(path.join(WEB, "index.html"), "utf8");

  const population = await getJson("/api/population?reserve=16");
  const zones = await getJson("/api/needzones?reserve=16");
  const reserveList = await getJson("/api/reserves");
  if (!population.ok) {
    console.error("cannot reach the API on " + BASE + " — is the server running?");
    process.exit(2);
  }

  const dom = new JSDOM(html, {
    url: BASE + "/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;

  /* The language is read once, at load time, from localStorage (i18n.js) — set it
     before any script runs so the boot below is the real thing, not a re-render. */
  window.localStorage.setItem("cotw.locale", LOCALE);

  /* Optional: pretend the previous session left a filter behind, so this boot also
     covers the restore path. COTW_SEED_FILTERS=1 node work/uiboot/boot.js */
  const SEED_FILTERS = process.env.COTW_SEED_FILTERS === "1";
  const SPECIES = (population.json.species || []).map((s) => s.name);
  const seedSpecies = SEED_FILTERS && SPECIES.length > 1 ? SPECIES[0] : null;
  /* The two species this run unticks (one seeded, one during the run): the spawn
     stub must avoid them, or its rows would be filtered out of the list. */
  const otherSpecies = SPECIES.find((name) => name !== seedSpecies);
  if (seedSpecies) {
    window.localStorage.setItem("cotw.filters",
      JSON.stringify({ species: { [seedSpecies]: false } }));
  }

  /* The five heaviest animals of the reserve (the shortlist cap), excluding the species
     unticked above. The sort test leaves the list ordered by weight, descending, so
     these are the rows the list will actually have rendered — which is what lets the
     check below look at real DOM rows instead of trusting the badge count. */
  const spawnPick = (population.json.animals || [])
    .filter((a) => a.species !== seedSpecies && a.species !== otherSpecies)
    .sort((a, b) => (b.weight || 0) - (a.weight || 0))
    .slice(0, 5);

  const errors = [];
  const warnings = [];
  window.addEventListener("error", (e) => errors.push("window.error: " + (e.message || e)));
  window.addEventListener("unhandledrejection", (e) =>
    errors.push("unhandledrejection: " + (e.reason && e.reason.message ? e.reason.message : e.reason))
  );
  const realError = console.error;
  console.error = (...a) => errors.push("console.error: " + a.join(" "));
  console.warn = (...a) => warnings.push("console.warn: " + a.join(" "));

  window.HTMLCanvasElement.prototype.getContext = () => canvasContextStub();
  window.devicePixelRatio = 1;
  window.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 16);
  window.cancelAnimationFrame = (id) => clearTimeout(id);
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  window.matchMedia =
    window.matchMedia ||
    (() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }));

  /* Synthetic radar payload: the live layer must render whatever the API says,
     independent of whether the game happens to be running during the test. */
  const radarPayload = {
    player: { x: -7412, z: -12984 },
    count: 2,
    player_source: "save:reserve16",
    player_age_seconds: 7,
    discovering: false,
    error: null,
    /* Which reserve the entities in memory belong to: the page follows it at boot. */
    live_reserve: 16,
    live_reserve_name: "Emerald Coast Australia",
    /* The hour slider must follow this, not the value stored locally. */
    game_time: { hour: 6.25, hhmm: "06:15", age_seconds: 5 },
    animals: [
      { species: "Red Deer", x: -7500, y: 1200, z: -12900, distance: 120.4, hash_id: "00000000", fur: "Albino", fur_rarity: "very_rare" },
      { species: "Black Bear", x: -7300, y: 1100, z: -13100, distance: 160.8, hash_id: "00000000", fur: null, fur_rarity: null },
    ],
  };

  const harvestPayload = {
    harvests: [
      { species: "Black Bear", fur: "Noire", fur_rarity: "very_rare", score: 18.06, timestamp: "2026-10-30T14:12:00Z" },
      { species: "Red Fox", fur: null, fur_rarity: null, score: 12.5, timestamp: "2026-10-30T13:40:00Z" },
    ],
  };
  const pressurePayload = {
    reserve: 16, grid: 256, max: 100, count: 2, calibrated: true,
    cell: [30.67, 39.18], origin: [-8620.7, -13636.8],
    cells: [[-7400, -12900, 80], [-7350, -12950, 20]],
  };
  const comparePayload = {
    species: "Red Deer",
    reserves: [
      { reserve: 16, name: "Emerald Coast Australia", total: 120, medals: { diamond: 2, gold: 14 } },
      { reserve: 9, name: "Silver Ridge Peaks", total: 80, medals: { diamond: 1, gold: 9 } },
    ],
  };
  const alertsPayload = {
    alerts: [{ id: 7, reserve: 16, reserve_name: "Emerald Coast", species: "Sambar",
               gender: "male", weight: 300, score: 210.5, medal: "diamond",
               fur: "Albino", fur_rarity: "very_rare", seen_at: 0, reason: "diamond" }],
    count: 1,
    reserves_watched: 8,
    last_poll: 0,
    poll_seconds: 20,
    error: null,
    data_version: "v1",
    /* The watcher's rolling shortlist of the 5 most recent spawns — the list paints
       them green. */
    spawns: {
      at: Math.floor(Date.now() / 1000),
      count: spawnPick.length,
      per_reserve: 5,
      animals: spawnPick.map((a) => ({
        reserve: 16, reserve_name: "Emerald Coast", species: a.species,
        gender: a.gender, weight: a.weight, score: a.score, medal: a.medal,
        fur: a.fur, fur_rarity: a.fur_rarity, seed: a.seed,
        seen_at: Math.floor(Date.now() / 1000), direction: "appeared",
      })),
    },
    changes: {
      appeared: [{ reserve: 16, reserve_name: "Emerald Coast", species: "Sambar",
                   gender: "male", weight: 300, score: 210.5, medal: "diamond",
                   fur: "Albino", fur_rarity: "very_rare", seen_at: 0 }],
      disappeared: [{ reserve: 16, reserve_name: "Emerald Coast", species: "Banteng",
                      gender: "female", weight: 400, score: 90.0, medal: "silver",
                      fur: null, fur_rarity: null, seen_at: 0 }],
      since: 0,
    },
  };
  const historyPayload = {
    reserve: 16,
    points: [{ date: "2026-10-30", total: 4004, diamonds: 6, golds: 430 }],
  };

  /* Every URL the page asked for, so the boot can prove which reserve it followed. */
  window.__fetched = [];
  window.fetch = (url) => {
    const target = String(url);
    window.__fetched.push(target);
    let payload = null;
    if (target.includes("/api/population")) payload = population.json;
    else if (target.includes("/api/needzones")) payload = zones.json;
    else if (target.includes("/api/radar")) payload = radarPayload;
    else if (target.includes("/api/harvests")) payload = harvestPayload;
    else if (target.includes("/api/pressure")) payload = pressurePayload;
    else if (target.includes("/api/compare")) payload = comparePayload;
    else if (target.includes("/api/alerts")) payload = alertsPayload;
    else if (target.includes("/api/history")) payload = historyPayload;
    else if (target.includes("/api/furs")) payload = { reserve: 16, species: {} };
    else if (target.includes("/api/reserves")) payload = reserveList.json || { reserves: [] };
    if (payload === null) return Promise.reject(new Error("stubbed fetch: " + target));
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(payload),
      text: () => Promise.resolve(JSON.stringify(payload)),
    });
  };

  /* which scripts the page loads, in order */
  const scripts = [...html.matchAll(/<script[^>]+src="([^"]+)"/g)].map((m) => m[1]);
  for (const src of scripts) {
    const file = path.join(WEB, src.split("?")[0]);
    if (!fs.existsSync(file)) {
      errors.push("missing script " + src);
      continue;
    }
    try {
      window.eval(fs.readFileSync(file, "utf8"));
    } catch (e) {
      errors.push("throw while evaluating " + src + ": " + e.message);
    }
  }

  await new Promise((r) => setTimeout(r, 1200));

  const text = window.document.body.textContent || "";
  const doc = window.document;
  const isHidden = (id) => {
    const el = doc.getElementById(id);
    if (!el) return true;
    if (el.hasAttribute("hidden")) return true;
    if (el.classList.contains("is-hidden")) return true;
    const style = window.getComputedStyle(el);
    return style.display === "none" || style.visibility === "hidden";
  };

  const speciesNames = (population.json.species || []).map((s) => s.name);
  const rendered = speciesNames.filter((n) => text.includes(n));

  /* --- functional: the sort bar must actually reorder the list ---------------- */
  const listEl = doc.getElementById("animalList");
  const sortRows = () => Array.from(listEl.querySelectorAll(".arow, li, [data-id]"))
    .slice(0, 3)
    .map((r) => r.textContent.trim().slice(0, 40));
  const beforeSort = sortRows();
  const weightBtn = doc.querySelector('[data-sort="weight"]');
  let sortChanged = false;
  let sortActive = false;
  if (weightBtn) {
    weightBtn.click();
    await new Promise((r) => setTimeout(r, 250));
    const afterSort = sortRows();
    sortChanged = beforeSort.join("|") !== afterSort.join("|");
    sortActive = weightBtn.classList.contains("is-active");
  }

  await new Promise((r) => setTimeout(r, 200));

  /* --- functional: the reserve picker must open and list reserves ------------ */
  const reserveBtn = doc.getElementById("reserveName");
  const reserveMenu = doc.getElementById("reserveMenu");
  let pickerOpened = false;
  let pickerItems = 0;
  if (reserveBtn && reserveMenu) {
    reserveBtn.click();
    await new Promise((r) => setTimeout(r, 300));
    pickerOpened = !reserveMenu.hasAttribute("hidden");
    pickerItems = reserveMenu.querySelectorAll(".reserve-item").length;
  }

  /* --- theme: jsdom cannot resolve custom properties, so this is informational;
         the authoritative check lives in tools/check_ui.py ------------------- */
  const rootStyle = window.getComputedStyle(doc.documentElement);
  const tokenBg = (rootStyle.getPropertyValue("--bg") || "").trim().toLowerCase();

  /* --- functional: the live radar layer must poll and list what the API says -- */
  const liveCard = doc.getElementById("liveCard");
  const liveList = doc.getElementById("liveList");
  const liveCount = doc.getElementById("liveCount");
  const liveRows = liveList ? liveList.querySelectorAll("li").length : 0;
  const liveVisible = liveCard ? !liveCard.hasAttribute("hidden") : false;
  const liveOk =
    liveVisible &&
    liveRows === radarPayload.animals.length &&
    (liveCount ? liveCount.textContent.trim() === String(radarPayload.count) : false);

  const liveText = liveList ? liveList.textContent || "" : "";

  /* --- functional: the map layers must toggle, harvests must list ---------- */
  const pressureBtn = doc.getElementById("btnPressure");
  const trailsBtn = doc.getElementById("btnTrails");
  let pressureToggled = false;
  let trailsToggled = false;
  if (pressureBtn) {
    pressureBtn.click();
    await new Promise((r) => setTimeout(r, 250));
    pressureToggled = pressureBtn.getAttribute("aria-pressed") === "true";
  }
  if (trailsBtn) {
    trailsBtn.click();
    await new Promise((r) => setTimeout(r, 120));
    trailsToggled = trailsBtn.getAttribute("aria-pressed") === "true";
  }
  await new Promise((r) => setTimeout(r, 250));
  const harvestList = doc.getElementById("harvestList");
  const harvestRows = harvestList ? harvestList.querySelectorAll("li").length : 0;

  /* --- route / measure / nearby / history / changes ------------------------ */
  const routeBtn = doc.getElementById("btnRoute");
  let routeOk = false;
  if (routeBtn) {
    routeBtn.click();
    await new Promise((r) => setTimeout(r, 200));
    routeOk = routeBtn.getAttribute("aria-pressed") === "true";
  }
  const measureBtn = doc.getElementById("btnMeasure");
  let measureOk = false;
  if (measureBtn) {
    measureBtn.click();
    await new Promise((r) => setTimeout(r, 80));
    measureOk = measureBtn.getAttribute("aria-pressed") === "true";
  }
  const nearbyBtn = doc.getElementById("btnNearby");
  let nearbyOk = false;
  if (nearbyBtn) {
    nearbyBtn.click();
    await new Promise((r) => setTimeout(r, 80));
    nearbyOk = nearbyBtn.getAttribute("aria-pressed") === "true";
  }
  await new Promise((r) => setTimeout(r, 400));
  const changesList = doc.getElementById("changesList");
  const changeRows = changesList ? changesList.querySelectorAll("li").length : 0;
  const historyList = doc.getElementById("historyList");
  const historyRows = historyList ? historyList.querySelectorAll("li").length : 0;
  const alertsList = doc.getElementById("alertsList");
  const alertRows = alertsList ? alertsList.querySelectorAll("li").length : 0;

  /* --- language: the chrome must be in the expected language and carry no
         leftover in the other one — that is the "half translated" bug ---------- */
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
  const txt = (id) => norm((doc.getElementById(id) || {}).textContent);
  const label = (sel) => norm((doc.querySelector(sel) || {}).textContent);
  const chrome = {
    lang: doc.documentElement.getAttribute("lang"),
    code: txt("langCode"),
    fitMap: txt("btnFitMap"),
    needZones: txt("fs-zones"),
    resetFilters: txt("btnResetFilters"),
    hideScripted: label('label[for="hideScripted"] .toggle-label'),
    scanned: label(".list-hint"),
    activeWord: txt("timebarCount"),
    speciesTotal: txt("speciesTotal"),
  };
  const leftover = WANT.forbidden.filter((phrase) => text.includes(phrase));
  const listText = listEl ? listEl.textContent || "" : "";
  const decimalOk = new RegExp(`\\d\\${WANT.decimal}\\d`).test(listText);

  /* --- the filter selection must be written back: switching language reloads,
         and nobody wants to lose their species/medal selection doing it -------- */
  let filterSaved = false;
  if (otherSpecies) {
    const box = doc.querySelector(`#speciesList .check[data-value="${otherSpecies}"] input`);
    if (box) {
      box.checked = false;
      box.dispatchEvent(new window.Event("change", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 200));
      try {
        const saved = JSON.parse(window.localStorage.getItem("cotw.filters") || "null");
        filterSaved = !!(saved && saved.species && saved.species[otherSpecies] === false);
      } catch (e) {
        filterSaved = false;
      }
    }
  }
  const seededBox = seedSpecies
    ? doc.querySelector(`#speciesList .check[data-value="${seedSpecies}"] input`)
    : null;

  /* --- the "just spawned" marking ---------------------------------------- */
  const listNew = doc.getElementById("listNew");
  const newBadge = txt("listNewText");
  const markedRows = Array.from(doc.querySelectorAll(".animal-row.is-new"))
    .map((row) => (row.querySelector(".row-species") || {}).textContent || "");
  const newDot = doc.querySelectorAll(".animal-row.is-new .row-new").length;
  const spawnBadgeNumber = (newBadge.match(/\d+/) || [null])[0];

  /* --- which reserve the page followed, and what it says on a mismatch ---- */
  const populationUrl = (window.__fetched || []).find((u) => u.includes("/api/population")) || "";
  const liveHint = doc.getElementById("liveHint");
  const liveHintText = doc.getElementById("liveHintText");
  const liveHintLink = doc.getElementById("liveHintLink");
  const hintHiddenOnMatch = liveHint.hasAttribute("hidden");

  /* Pretend the game is in another reserve: the panel must say so and offer the link. */
  radarPayload.live_reserve = 9;
  radarPayload.live_reserve_name = "Silver Ridge Peaks";
  await new Promise((r) => setTimeout(r, 1600));
  const hintShownOnMismatch = !liveHint.hasAttribute("hidden");
  const hintText = norm(liveHintText.textContent);
  const hintHref = liveHintLink.getAttribute("href");
  radarPayload.live_reserve = 16;
  radarPayload.live_reserve_name = "Emerald Coast Australia";

  const checks = [
    ["app booted without errors", errors.length === 0, errors.slice(0, 6).join(" | ")],
    [
      "hour slider follows the in-game clock",
      (doc.getElementById("hourReadout") || {}).textContent === radarPayload.game_time.hhmm,
      "readout is " + (doc.getElementById("hourReadout") || {}).textContent,
    ],
    [
      "fur chip rendered on an animal with a fur",
      liveText.indexOf("Albino") >= 0,
      "live list text: " + liveText.slice(0, 120),
    ],
    [
      "clock toggle is in follow mode",
      (doc.getElementById("btnClock") || {}).getAttribute
        ? doc.getElementById("btnClock").getAttribute("aria-pressed") === "true"
        : false,
      "btnClock missing or not pressed",
    ],
    ["reserve name rendered", /Emerald Coast/i.test(text), ""],
    ["a species from the roster is rendered", /Red Deer|Sambar|Banteng/i.test(text), ""],
    [
      /* The save is live: its zone count moves as the game discovers zones, so the
         expectation comes from the API payload, not from a number pinned here. */
      `zone count rendered (${(zones.json.zones || []).length} from the API)`,
      new RegExp(`\\b${(zones.json.zones || []).length}\\b`).test(text),
      "the zone total from /api/needzones is not in the page",
    ],
    ["empty-state overlay is hidden", isHidden("mapEmpty"), "mapEmpty still visible"],
    [
      `species list populated (${rendered.length}/${speciesNames.length} names in the DOM)`,
      rendered.length >= speciesNames.length - 1,
      "missing: " + speciesNames.filter((n) => !text.includes(n)).join(", "),
    ],
    ["sort button is marked active after a click", sortActive, "no is-active class"],
    ["sort button reorders the animal list", sortChanged, "list order unchanged"],
    ["reserve picker opens", pickerOpened, "menu stayed hidden"],
    [`reserve picker lists reserves (${pickerItems})`, pickerItems > 5, String(pickerItems)],
    [
      `live radar lists the API animals (${liveRows} row(s), count ${liveCount ? liveCount.textContent : "?"})`,
      liveOk,
      liveVisible ? "card visible but rows/count mismatch" : "live card stayed hidden",
    ],
    ["hunting pressure layer toggles", pressureToggled, "btnPressure did not switch on"],
    ["observation trail layer toggles", trailsToggled, "btnTrails did not switch on"],
    [
      `harvest panel lists the API harvests (${harvestRows})`,
      harvestRows >= harvestPayload.harvests.length,
      "no harvest row rendered",
    ],
    ["route planner toggles", routeOk, "btnRoute did not switch on"],
    ["measure tool toggles", measureOk, "btnMeasure did not switch on"],
    ["nearby alerts toggle", nearbyOk, "btnNearby did not switch on"],
    [
      `delta panel lists the changes (${changeRows})`,
      changeRows === alertsPayload.changes.appeared.length + alertsPayload.changes.disappeared.length,
      "expected appeared + disappeared rows",
    ],
    [
      `history panel lists the snapshots (${historyRows})`,
      historyRows >= historyPayload.points.length,
      "no history row rendered",
    ],
    [
      `alert panel lists the API alerts (${alertRows})`,
      alertRows >= alertsPayload.alerts.length,
      "no alert row rendered",
    ],
    [
      "CSV export button is present",
      !!(doc.getElementById("btnCsv")),
      "btnCsv missing",
    ],
    /* --- interface language ------------------------------------------------ */
    [`html lang is "${LOCALE}"`, chrome.lang === LOCALE, "lang=" + chrome.lang],
    [
      `language button shows ${LOCALE.toUpperCase()}`,
      chrome.code === LOCALE.toUpperCase(),
      "langCode says " + JSON.stringify(chrome.code),
    ],
    [
      `map toolbar is in ${LOCALE.toUpperCase()} ("${WANT.fitMap}")`,
      chrome.fitMap === WANT.fitMap,
      "btnFitMap says " + JSON.stringify(chrome.fitMap),
    ],
    [
      `section headings are in ${LOCALE.toUpperCase()} ("${WANT.needZones}")`,
      chrome.needZones === WANT.needZones,
      "fs-zones says " + JSON.stringify(chrome.needZones),
    ],
    [
      `filter controls are in ${LOCALE.toUpperCase()}`,
      chrome.resetFilters === WANT.resetFilters && chrome.hideScripted === WANT.hideScripted,
      JSON.stringify([chrome.resetFilters, chrome.hideScripted]),
    ],
    [
      `list chrome is in ${LOCALE.toUpperCase()} ("${WANT.scanned}")`,
      chrome.scanned === WANT.scanned,
      "list hint says " + JSON.stringify(chrome.scanned),
    ],
    [
      `hour bar reads "${WANT.activeWord}"`,
      chrome.activeWord.indexOf(WANT.activeWord) >= 0,
      JSON.stringify(chrome.activeWord),
    ],
    [
      `no ${LOCALE === "fr" ? "English" : "French"} label left in the page`,
      leftover.length === 0,
      "leftovers: " + leftover.join(" | "),
    ],
    [
      `numbers use the ${LOCALE === "fr" ? "decimal comma" : "decimal point"}`,
      decimalOk,
      "no such number in the animal list: " + norm(listText).slice(0, 90),
    ],
    /* --- filter persistence (a reload must not lose the selection) ---------- */
    [
      seedSpecies
        ? `a saved filter is restored on load (${seedSpecies} arrives unticked)`
        : "every species starts ticked when nothing was saved",
      seedSpecies
        ? seededBox !== null && seededBox.checked === false
          && chrome.speciesTotal === `${SPECIES.length - 1}/${SPECIES.length}`
        : chrome.speciesTotal === `${SPECIES.length}/${SPECIES.length}`,
      `checked=${seededBox ? seededBox.checked : "n/a"} speciesTotal=${chrome.speciesTotal}`,
    ],
    [
      "a filter change is written back for the next load",
      filterSaved,
      "cotw.filters did not record the unticked species",
    ],
    /* --- the "just spawned" marking the server's delta feeds --------------- */
    [
      `the spawn batch is painted green (${markedRows.length}/${spawnPick.length} rows)`,
      spawnPick.length > 0 && markedRows.length === spawnPick.length
        && markedRows.every((species) => spawnPick.some((a) => a.species === species)),
      "marked: " + JSON.stringify(markedRows) + " expected: "
        + JSON.stringify(spawnPick.map((a) => a.species)),
    ],
    [
      `every marked row carries the dot (${newDot})`,
      newDot === markedRows.length,
      "dots without rows or rows without dots",
    ],
    [
      `the list header counts the newcomers ("${newBadge}")`,
      !listNew.hasAttribute("hidden") && spawnBadgeNumber === String(spawnPick.length),
      `hidden=${listNew.hasAttribute("hidden")} text=${JSON.stringify(newBadge)}`,
    ],
    [
      "a row that did not spawn stays unmarked",
      doc.querySelectorAll(".animal-row:not(.is-new)").length > markedRows.length,
      "every rendered row is marked",
    ],
    /* --- the live layer must be anchored on the reserve the game is in ------ */
    [
      `the page followed the game's reserve at boot ("${populationUrl}")`,
      populationUrl.includes("reserve=16"),
      "population request was " + JSON.stringify(populationUrl),
    ],
    [
      "no mismatch note when the page is on the live reserve",
      hintHiddenOnMatch,
      "liveHint was already visible",
    ],
    [
      `a reserve mismatch is explained ("${hintText}")`,
      hintShownOnMismatch
        && hintText.includes("Silver Ridge Peaks")
        && hintHref === "?reserve=9",
      `shown=${hintShownOnMismatch} text=${JSON.stringify(hintText)} href=${JSON.stringify(hintHref)}`,
    ],
  ];

  let failed = 0;
  console.log(`== ${LOCALE === "fr" ? "French" : "English"} interface ==`);
  for (const [label, ok, detail] of checks) {
    if (ok) console.log("  PASS  " + label);
    else {
      console.log("  FAIL  " + label + (detail ? "  " + detail : ""));
      failed++;
    }
  }
  if (warnings.length) {
    console.log("  info  warnings: " + [...new Set(warnings)].slice(0, 4).join(" | "));
  }
  console.log(
    failed ? `FAIL: ${failed} check(s) failed` : "PASS: the UI boots and renders real data"
  );
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error("harness crashed:", e && e.stack ? e.stack : e);
  process.exit(3);
});
