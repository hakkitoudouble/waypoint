/* Unit tests for web/i18n.js — the module the whole interface depends on.
 *
 * The two UI boots (boot.js, run once per language) prove the real page renders
 * in French and in English. This file checks the pieces in isolation, where a
 * failure is easy to read: lookup, interpolation, the placeholder split used for
 * "No species match “…”", attribute rewriting, persistence and the reload-on-
 * switch contract, and the fallbacks when storage or a key is missing.
 *
 * Run:  node work/uiboot/i18n.js
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { JSDOM } = require("jsdom");

const SOURCE = fs.readFileSync(path.resolve(__dirname, "..", "..", "web", "i18n.js"), "utf8");

const checks = [];
function check(label, ok, detail) {
  checks.push([label, !!ok, detail || ""]);
}
function eq(label, actual, expected) {
  check(label, actual === expected, `got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)}`);
}

/** Load i18n.js into a sandbox with a real (jsdom) document and a fake storage. */
async function load({ stored = null, throwStorage = false } = {}) {
  const dom = new JSDOM(
    `<!doctype html><html lang="en" class="i18n-pending"><body>
       <p id="text" data-i18n="Fit map">Fit map</p>
       <p id="title" data-i18n-title="Switch to light theme"></p>
       <p id="aria" data-i18n-aria-label="Close filters"></p>
       <input id="ph" data-i18n-placeholder="Search species…" />
       <span id="langCode">?</span>
       <button id="btnLang"></button>
     </body></html>`,
    { url: "http://localhost/" }
  );
  const mem = new Map();
  if (stored != null) mem.set("cotw.locale", stored);
  const warnings = [];
  let reloads = 0;
  const sandbox = {
    document: dom.window.document,
    localStorage: {
      getItem: (k) => {
        if (throwStorage) throw new Error("storage is blocked");
        return mem.has(k) ? mem.get(k) : null;
      },
      setItem: (k, v) => {
        if (throwStorage) throw new Error("storage is blocked");
        mem.set(k, String(v));
      },
    },
    location: { reload: () => { reloads++; } },
    console: { warn: (m) => warnings.push(String(m)), log: () => {} },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SOURCE, sandbox, { filename: "i18n.js" });
  /* A freshly built JSDOM is still "loading", so i18n.js defers its wiring to
     DOMContentLoaded (in a real page the script sits at the end of <body> and
     runs straight away). Wait for that turn before asserting. */
  if (dom.window.document.readyState === "loading") {
    await new Promise((resolve) =>
      dom.window.document.addEventListener("DOMContentLoaded", resolve));
  }
  return { I18N: sandbox.I18N, doc: dom.window.document, mem, warnings, reloads: () => reloads };
}

async function main() {
  /* ---- French, the reference language ---------------------------------- */
  const fr = await load();
  eq("default locale is French", fr.I18N.locale(), "fr");
  eq('t("Fit map")', fr.I18N.t("Fit map"), "Ajuster la carte");
  eq('t("Hide great ones")', fr.I18N.t("Hide great ones"), "Masquer les Great Ones");
  eq("interpolates {placeholders}", fr.I18N.t("{n} of {total}", { n: 3, total: 5 }), "3 sur 5");
  eq("leaves unknown placeholders alone", fr.I18N.t("{n} of {total}", { n: 3 }), "3 sur {total}");
  eq("unknown key falls back to the English source",
     fr.I18N.t("No such string in the table"), "No such string in the table");
  check("a missing key is reported", fr.warnings.some((w) => w.includes("No such string in the table")),
        JSON.stringify(fr.warnings));

  /* ---- the placeholder split (used for the species-search empty state) -- */
  const [before, after] = fr.I18N.split("No species match “{term}”.", "term");
  /* French typography: a full no-break space after « and a narrow one before »,
     both supplied by the translation, not by the caller. */
  check('split() keeps the French quotes around the term',
        before.endsWith("«\u00a0") && after.startsWith("\u202f»."),
        JSON.stringify([before, after]));
  check("split() round-trips with the term", before + "Cerf" + after
        === "Aucune espèce ne correspond à «\u00a0Cerf\u202f».",
        JSON.stringify(before + "Cerf" + after));

  /* ---- applying to the DOM --------------------------------------------- */
  eq("html lang follows the locale", fr.doc.documentElement.lang, "fr");
  eq("data-i18n rewrites text", fr.doc.getElementById("text").textContent, "Ajuster la carte");
  eq("data-i18n-title rewrites title", fr.doc.getElementById("title").getAttribute("title"),
     "Passer au thème clair");
  eq("data-i18n-aria-label rewrites aria-label",
     fr.doc.getElementById("aria").getAttribute("aria-label"), "Fermer les filtres");
  eq("data-i18n-placeholder rewrites placeholder",
     fr.doc.getElementById("ph").getAttribute("placeholder"), "Rechercher une espèce…");
  eq("the language code is shown", fr.doc.getElementById("langCode").textContent, "FR");
  check("the pending-language class is cleared",
        !fr.doc.documentElement.classList.contains("i18n-pending"),
        fr.doc.documentElement.className);
  eq("decimal separator", fr.I18N.decimal(), ",");
  eq("date locale", fr.I18N.dateLocale(), "fr-FR");

  /* ---- switching language: persist, then reload ------------------------- */
  fr.doc.getElementById("btnLang").click();
  eq("clicking the language button stores the other locale", fr.mem.get("cotw.locale"), "en");
  eq("switching reloads the page (labels are resolved at load time)", fr.reloads(), 1);
  eq("the locale itself only changes after the reload", fr.I18N.locale(), "fr");

  /* ---- English: the source strings, no overrides ----------------------- */
  const en = await load({ stored: "en" });
  eq("stored locale wins", en.I18N.locale(), "en");
  eq('t("Fit map") in English', en.I18N.t("Fit map"), "Fit map");
  eq("English labels are the markup text", en.doc.getElementById("text").textContent, "Fit map");
  eq("English decimal separator", en.I18N.decimal(), ".");
  eq("English date locale", en.I18N.dateLocale(), "en-GB");

  /* ---- hostile / missing storage --------------------------------------- */
  const junk = await load({ stored: "de" });
  eq("an unknown stored locale falls back to French", junk.I18N.locale(), "fr");

  /* file:// and private mode can throw on every storage call: the interface must
     still work (French by default) and switching must not explode. */
  const blocked = await load({ throwStorage: true });
  eq("blocked storage still boots in French", blocked.I18N.locale(), "fr");
  let threw = null;
  try {
    blocked.I18N.setLocale("en");
  } catch (err) {
    threw = err;
  }
  check("setLocale survives a blocked localStorage", threw === null, String(threw));
  eq("and still asks for the reload", blocked.reloads(), 1);

  /* ---- the table itself ------------------------------------------------ */
  const table = fr.I18N.dictionary;
  check("the table has a French section", Object.keys(table.fr || {}).length > 150,
        String(Object.keys(table.fr || {}).length) + " entries");
  check("English carries no overrides", Object.keys(table.en || {}).length === 0,
        JSON.stringify(Object.keys(table.en || {})));
  const empty = Object.entries(table.fr).filter(([, v]) => !v || !String(v).trim());
  check("no empty translation", empty.length === 0, JSON.stringify(empty.slice(0, 3)));

  let failed = 0;
  for (const [label, ok, detail] of checks) {
    if (ok) console.log("  PASS  " + label);
    else {
      console.log("  FAIL  " + label + (detail ? "  " + detail : ""));
      failed++;
    }
  }
  console.log(failed ? `FAIL: ${failed} check(s) failed`
                     : "PASS: i18n.js looks up, applies, persists and reloads correctly");
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error("harness crashed:", e && e.stack ? e.stack : e);
  process.exit(3);
});
