/* =============================================================================
 * Waypoint — interface translations
 * -----------------------------------------------------------------------------
 * The interface ships in two languages. FRENCH is the reference language of
 * this build; English is the original wording and doubles as the KEY.
 *
 *   t("Fit map")                       → "Ajuster la carte"      (fr)
 *   t("Hide great ones")               → "Masquer les Great Ones" (fr)
 *   t("Sort by {key}", { key: "poids" })
 *
 * Design rules
 *   • The English source string IS the key. A missing translation therefore
 *     degrades to readable English instead of a raw identifier, and a typo in a
 *     key is caught by tools/check_i18n.py, which cross-checks every t() call in
 *     app.js and every data-i18n attribute in index.html against this table.
 *   • `en` is intentionally empty: English needs no translation, and the English
 *     text lives in the markup and in the key itself (single source of truth).
 *   • Static markup carries `data-i18n` (text), `data-i18n-title`,
 *     `data-i18n-aria-label`, `data-i18n-placeholder` and `data-i18n-content`.
 *     apply() rewrites those nodes; the app re-renders its dynamic parts itself.
 *   • Changing the language RELOADS the page. Every label in app.js is resolved
 *     once into constants at load time (TYPE_LABEL, MEDAL_LABEL, …) and the whole
 *     list/map pipeline is built on them, so a reload is the only honest way to
 *     avoid a half-translated screen.
 *   • Species and reserve names are NOT translated: they come from the game
 *     files (the scanned population and /api/reserves) and are shown exactly as
 *     the save stores them.
 * ========================================================================== */
(function (global) {
  "use strict";

  var STORE = "cotw.locale";
  var DEFAULT = "fr";
  var NNBSP = "\u00a0";   // espace insécable
  var NBSP = "\u202f";    // espace fine insécable (avant : ; ! ? et dans « »)

  var NAMES = { fr: "Français", en: "English" };

  var DICT = {
    /* ── Français (langue de référence) ──────────────────────────────────── */
    fr: {
      /* document */
      "Waypoint · theHunter: Call of the Wild companion":
        "Waypoint · compagnon theHunter: Call of the Wild",
      "Waypoint — an offline companion for theHunter: Call of the Wild: the scanned population on one side, discovered need zones and their active hours on the map.":
        "Waypoint — un compagnon hors ligne pour theHunter: Call of the Wild : la population scannée d'un côté, les zones de besoin découvertes et leurs heures d'activité sur la carte.",
      "Waypoint needs JavaScript to read the scan and draw the map.":
        "Waypoint a besoin de JavaScript pour lire le scan et dessiner la carte.",

      /* top bar */
      "population scanner": "scanner de population",
      "Reserve": "Réserve",
      "Change reserve": "Changer de réserve",
      "Choose a reserve": "Choisir une réserve",
      "Loading…": "Chargement…",
      "Live save": "Sauvegarde en direct",
      "Sample data": "Données d'exemple",
      "No data": "Aucune donnée",
      "Filters": "Filtres",
      "Switch to light theme": "Passer au thème clair",
      "Switch to dark theme": "Passer au thème sombre",
      "Switch language": "Changer de langue",
      "Close filters": "Fermer les filtres",

      /* filters — need zones */
      "Need zones": "Zones de besoin",
      "Need zone types": "Types de zones de besoin",
      "Zones outside the selected hour stay on the map, dimmed. The species filter below applies to zones as well.":
        "Les zones hors de l'heure sélectionnée restent sur la carte, en retrait. Le filtre d'espèces ci-dessous s'applique aussi aux zones.",
      "Feed zone": "Zone d'alimentation",
      "Drink zone": "Zone d'abreuvement",
      "Rest zone": "Zone de repos",
      "Feed": "Alimentation",
      "Drink": "Abreuvement",
      "Rest": "Repos",

      /* filters — species */
      "Species": "Espèces",
      "species": "espèce",
      "All": "Tout",
      "None": "Aucun",
      "Search species…": "Rechercher une espèce…",
      "Search species": "Rechercher une espèce",
      "Clear species search": "Effacer la recherche d'espèce",
      "No species match “{term}”.": "Aucune espèce ne correspond à «" + NNBSP + "{term}" + NBSP + "».",
      "All day": "Toute la journée",

      /* filters — population */
      "Live animals": "Animaux en direct",
      "waiting for the game…": "en attente du jeu…",
      "The game is running {reserve}.": "Le jeu tourne sur {reserve}.",
      "Open that reserve": "Ouvrir cette réserve",
      "Population": "Population",
      "Individual positions are not saved — the Live layer reads them from the running game":
        "Positions individuelles non enregistrées — la couche « Direct » les lit dans le jeu en cours",
      "Sex": "Sexe",
      "Any": "Indifférent",
      "Male": "Mâle",
      "Female": "Femelle",
      "Unknown": "Inconnu",
      "Medal": "Médaille",
      "Medal tier": "Niveau de médaille",
      "Fur rarity": "Rareté de la fourrure",
      "Visibility": "Visibilité",
      "Hide scripted animals": "Masquer les animaux scriptés",
      "Hide great ones": "Masquer les Great Ones",
      "Reset all filters": "Réinitialiser les filtres",

      /* medals */
      "Great One": "Great One",
      "Diamond": "Diamant",
      "Gold": "Or",
      "Silver": "Argent",
      "Bronze": "Bronze",

      /* furs */
      "Common": "Commune",
      "Uncommon": "Peu commune",
      "Rare": "Rare",
      "Very rare": "Très rare",
      "Super rare": "Super rare",
      "(relative)": "(relatif)",

      /* side panels */
      "Active hours": "Heures d'activité",
      "Tick a single species to see when its zones are active.":
        "Cochez une seule espèce pour voir quand ses zones sont actives.",
      "No zone for this species": "Aucune zone pour cette espèce",
      "Where to hunt": "Où chasser",
      "Tick a single species to compare reserves.":
        "Cochez une seule espèce pour comparer les réserves.",
      "No reserve has this species": "Aucune réserve n'abrite cette espèce",
      "{name}: {total} animals, {diamond} diamond, {gold} gold":
        "{name} : {total} animaux, {diamond} diamants, {gold} or",
      "Alerts": "Alertes",
      "Warn when a live animal comes within 120 m":
        "Alerter quand un animal vivant passe à moins de 120 m",
      "Nearby": "Proximité",
      "Watching for new diamonds and great ones.":
        "À l'affût des nouveaux diamants et Great Ones.",
      "No change since the last scan.": "Aucun changement depuis le dernier scan.",
      "History": "Historique",
      "No daily snapshot recorded yet.": "Aucun instantané quotidien enregistré.",
      "Harvests": "Tableau de chasse",
      "No harvest recorded yet.": "Aucun prélèvement enregistré.",

      /* map chrome */
      "Reserve map": "Carte de la réserve",
      "In-game time": "Heure du jeu",
      "In-game hour": "Heure du jeu",
      "Follow the in-game clock": "Suivre l'horloge du jeu",
      "Auto": "Auto",
      "Manual": "Manuel",
      "The hour follows the in-game clock — click for manual":
        "L'heure suit l'horloge du jeu — cliquez pour passer en manuel",
      "Manual hour — click to follow the in-game clock":
        "Heure manuelle — cliquez pour suivre l'horloge du jeu",
      "Following the in-game clock ({hhmm})": "Suit l'horloge du jeu ({hhmm})",
      " — last write {n} s ago": " — dernière écriture il y a {n}" + NNBSP + "s",
      "Need zones active at this hour": "Zones de besoin actives à cette heure",
      "active": "actives",
      "Need zone map. Drag to pan, scroll to zoom, double-click to reset.":
        "Carte des zones de besoin. Glissez pour déplacer, molette pour zoomer, double-clic pour réinitialiser.",
      "Drag to pan · scroll to zoom · double-click to reset":
        "Glisser pour déplacer · molette pour zoomer · double-clic pour réinitialiser",
      "Diamond detected": "Diamant détecté",
      "Dismiss": "Fermer",
      "Map controls": "Commandes de la carte",
      "Zoom in": "Zoomer",
      "Zoom in (+)": "Zoomer (+)",
      "Zoom out": "Dézoomer",
      "Zoom out (−)": "Dézoomer (−)",
      "Fit map": "Ajuster la carte",
      "Fit the whole reserve map in the view":
        "Afficher toute la carte de la réserve dans la vue",
      "Fit zones": "Ajuster les zones",
      "Zoom to the zones currently shown": "Zoomer sur les zones affichées",
      "Reset view": "Réinitialiser la vue",
      "Reset view (0)": "Réinitialiser la vue (0)",
      "Live": "Direct",
      "Toggle live animals read from the running game":
        "Afficher ou masquer les animaux lus dans le jeu en cours",
      "Pressure": "Pression",
      "Hunting pressure. Placement is measured on Silver Ridge Peaks from two in-game alert zones; other reserves are still a rough guess.":
        "Pression de chasse. Position mesurée sur Silver Ridge Peaks à partir de deux zones d'alerte relevées en jeu ; les autres réserves restent approximatives.",
      "Trails": "Traces",
      "Show where animals have been observed during this session":
        "Montrer où les animaux ont été observés pendant cette session",
      "Route": "Tournée",
      "Order the active zones into a short tour from your position":
        "Ordonner les zones actives en une courte tournée depuis votre position",
      "Measure": "Mesure",
      "Click two points on the map to measure distance and bearing":
        "Cliquez deux points sur la carte pour mesurer distance et azimut",

      /* legend */
      "Legend": "Légende",
      "feed": "alimentation",
      "drink": "abreuvement",
      "rest": "repos",
      "inactive now": "inactives",
      "Animals": "Animaux",
      "in the list": "dans la liste",
      "ring = female": "anneau = femelle",
      "stem = male": "hampe = mâle",
      "halo = rare fur": "halo = fourrure rare",

      /* tooltip */
      "Zone": "Zone",
      "active now": "active maintenant",
      "Altitude": "Altitude",
      "Unknown animal type": "Espèce inconnue",
      "Type hash {hash}": "Hash de type {hash}",
      "No animal type in this scan": "Aucun type d'espèce dans ce scan",

      /* empty / loading states */
      "No need zones found": "Aucune zone de besoin trouvée",
      "Discover food, water and rest spots in game, then scan again.":
        "Découvrez des zones de nourriture, d'eau et de repos en jeu, puis relancez un scan.",
      "Discover food, water and rest spots in game, then scan again — they will appear here.":
        "Découvrez des zones de nourriture, d'eau et de repos en jeu, puis relancez un scan — elles apparaîtront ici.",
      "Need zones unavailable": "Zones de besoin indisponibles",
      "The zone endpoint did not answer. The reserve map and the population list are still shown.":
        "L'endpoint des zones n'a pas répondu. La carte de la réserve et la liste de population restent affichées.",
      "No zones for the selected species": "Aucune zone pour les espèces sélectionnées",
      "These species have no discovered need zones on this reserve yet. Widen the species filter to see the rest.":
        "Ces espèces n'ont pas encore de zone de besoin découverte sur cette réserve. Élargissez le filtre d'espèces pour voir le reste.",
      "All zone types are hidden": "Tous les types de zones sont masqués",
      "Enable feed, drink or rest zones in the filters to see them again.":
        "Réactivez les zones d'alimentation, d'abreuvement ou de repos dans les filtres pour les revoir.",
      "Show all zone types": "Afficher tous les types de zones",
      "Reading population and zones…": "Lecture de la population et des zones…",
      "Could not read the scan": "Impossible de lire le scan",
      "No animals in this reserve.": "Aucun animal dans cette réserve.",
      "No animals match the current filters.": "Aucun animal ne correspond aux filtres.",

      /* list */
      "Animal list": "Liste des animaux",
      "Close animal list": "Fermer la liste des animaux",
      "scanned population": "population scannée",
      "Sort animals": "Trier les animaux",
      "Weight": "Poids",
      "Score": "Score",
      "Rating": "Note",
      "Sort by {key}": "Trier par {key}",
      "Sort by species": "Trier par espèce",
      "Sort by weight": "Trier par poids",
      "Sort by score": "Trier par score",
      "Sort by trophy rating": "Trier par note de trophée",
      "Sort by medal tier": "Trier par niveau de médaille",
      ", ascending": " (croissant)",
      ", descending": " (décroissant)",
      /* lowercase forms: the sort bar's aria-label reads like a sentence
         ("species" itself is defined with the species filter, above) */
      "weight": "poids",
      "score": "score",
      "trophy rating": "note de trophée",
      "medal tier": "niveau de médaille",
      "Download the filtered list as CSV": "Télécharger la liste filtrée au format CSV",
      "Scripted animal": "Animal scripté",
      "New": "Nouveau",
      "Spawned {when}": "Apparu {when}",
      "{n} new animal": "{n} nouvel animal",
      "{n} new animals": "{n} nouveaux animaux",
      "Percentile within this reserve — no per-species trophy thresholds for this species":
        "Percentile dans cette réserve — aucun seuil de trophée par espèce pour cette espèce",
      "Panels": "Panneaux",

      /* summary line */
      "animal": "animal",
      "animals": "animaux",
      "diamond": "diamant",
      "diamonds": "diamants",
      "great one": "Great One",
      "great ones": "Great Ones",
      "rare fur": "fourrure rare",
      "rare furs": "fourrures rares",
      "{n} of {total}": "{n} sur {total}",
      "{n} of {total} species selected — applies to the list and the map":
        "{n} sur {total} espèces sélectionnées — s'applique à la liste et à la carte",

      /* counts, titles */
      "No “{medal}” animals in this scan": "Aucun animal «" + NNBSP + "{medal}" + NBSP + "» dans ce scan",
      "{active} of {total} active at {hour}": "{active} sur {total} actives à {hour}",

      /* reserve picker + header */
      "No reserves found": "Aucune réserve trouvée",
      "Reserve {n}": "Réserve {n}",
      "not played": "non jouée",
      "Could not load reserves": "Impossible de charger les réserves",
      "Unknown reserve": "Réserve inconnue",
      "scanned {when}": "scanné {when}",
      "(index {n})": "(indice {n})",
      " · zones {confidence}": " · zones {confidence}",
      "The local API was not reachable, so the bundled sample reserve is shown.":
        "L'API locale est injoignable : la réserve d'exemple embarquée est affichée.",
      "Population loaded from the scanner.": "Population lue par le scanner.",
      "Sample need zones · {confidence}": "Zones de besoin d'exemple · {confidence}",
      "Need zone endpoint unavailable": "Endpoint des zones de besoin indisponible",
      "Need zones from the save scan": "Zones de besoin issues du scan de sauvegarde",

      /* fatal / notes */
      "This browser cannot draw the map layer (no 2D canvas).":
        "Ce navigateur ne peut pas dessiner la carte (canvas 2D indisponible).",
      "The scan could not be read: {message}": "Le scan n'a pas pu être lu : {message}",
      "unknown error": "erreur inconnue",
      "No population data was returned and no bundled sample is available.":
        "Aucune donnée de population reçue et aucun exemple embarqué disponible.",
      "The scan JSON could not be understood.": "Le JSON du scan n'a pas pu être interprété.",
      "Startup failed: {message}": "Le démarrage a échoué : {message}",
      "Reserve map image missing — plotting on a schematic grid":
        "Image de la carte manquante — tracé sur une grille schématique",
      "Need zones unavailable — only the population could be loaded":
        "Zones de besoin indisponibles — seule la population a pu être chargée",
      "Hunting pressure has no measured placement for this reserve yet — its position is a rough guess. Silver Ridge Peaks is calibrated.":
        "La pression de chasse n'a pas encore de position mesurée sur cette réserve — son placement est approximatif. Silver Ridge Peaks est calibrée.",

      /* live card */
      "not available — {error}": "indisponible — {error}",
      "you {x}, {z}": "vous {x}, {z}",
      "within {r} m": "dans un rayon de {r}" + NNBSP + "m",
      "saved {n} s ago": "enregistré il y a {n}" + NNBSP + "s",
      " — click to centre the map": " — cliquez pour centrer la carte",
      "Rare furs: {list}": "Fourrures rares :" + NNBSP + "{list}",

      /* alerts */
      "{kind} detected": "{kind} détecté",
      "Animal nearby": "Animal proche",
      "TR {score}": "TR" + NNBSP + "{score}",
      "Watching {n} reserve(s) · checks every {s} s":
        "Surveillance de {n} réserve(s) · vérification toutes les {s}" + NNBSP + "s",
      "Waiting for a populated save…": "En attente d'une sauvegarde peuplée…",
      "new": "nouveau",
      "gone": "disparu",
      "{n} m away": "à {n}" + NNBSP + "m",

      /* route, csv */
      "No player position yet — is the game running?":
        "Pas encore de position du joueur — le jeu est-il lancé ?",
      "No zone to visit with the current filters.":
        "Aucune zone à visiter avec les filtres actuels.",
      "CSV export is not available in this browser.":
        "L'export CSV n'est pas disponible dans ce navigateur."
    },

    /* ── English: the source language, so nothing to override ────────────── */
    en: {}
  };

  function warn(message) {
    if (global.console && console.warn) console.warn("[i18n] " + message);
  }

  function readStored() {
    try {
      var saved = global.localStorage.getItem(STORE);
      if (saved && Object.prototype.hasOwnProperty.call(DICT, saved)) return saved;
    } catch (err) { /* storage can be blocked (file://, private mode) */ }
    return null;
  }

  var current = readStored() || DEFAULT;

  /** Look up `key` in the active locale, then interpolate {placeholders}. */
  function t(key, vars) {
    var table = DICT[current] || {};
    var text = Object.prototype.hasOwnProperty.call(table, key) ? table[key] : null;
    if (text == null) {
      /* English is the source: the key itself is the English string. */
      text = key;
      if (current !== "en" && DICT.fr && !Object.prototype.hasOwnProperty.call(DICT.fr, key)) {
        warn("missing translation: " + JSON.stringify(key));
      }
    }
    if (vars) {
      text = text.replace(/\{(\w+)\}/g, function (match, name) {
        return Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : match;
      });
    }
    return text;
  }

  /**
   * Split a translated string around one placeholder, so the caller can put real
   * markup (a <b>) at that spot: split("No species match “{term}”.", "term")
   * → ["Aucune espèce ne correspond à « ", " »."].
   */
  function split(key, placeholder) {
    var text = t(key);
    var token = "{" + placeholder + "}";
    var at = text.indexOf(token);
    if (at < 0) return [text, ""];
    return [text.slice(0, at), text.slice(at + token.length)];
  }

  /** Rewrite every tagged node under `root` (default: the whole document). */
  function apply(root) {
    root = root || global.document;
    if (!root || !root.querySelectorAll) return;
    var ATTRS = ["title", "aria-label", "placeholder", "alt", "content"];
    var nodes = root.querySelectorAll("[data-i18n]");
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].textContent = t(nodes[i].getAttribute("data-i18n"));
    }
    for (var a = 0; a < ATTRS.length; a++) {
      var attr = ATTRS[a];
      var tagged = root.querySelectorAll("[data-i18n-" + attr + "]");
      for (var j = 0; j < tagged.length; j++) {
        tagged[j].setAttribute(attr, t(tagged[j].getAttribute("data-i18n-" + attr)));
      }
    }
    if (global.document && global.document.documentElement) {
      global.document.documentElement.lang = current;
    }
  }

  function setLocale(next) {
    if (!Object.prototype.hasOwnProperty.call(DICT, next) || next === current) return false;
    try { global.localStorage.setItem(STORE, next); } catch (err) { /* ignore */ }
    /* Every label is resolved into constants at load time; reloading is the only
       way to switch without leaving a half-translated screen behind. */
    if (global.location && global.location.reload) {
      global.location.reload();
      return true;
    }
    current = next;
    apply();
    return true;
  }

  function toggle() {
    return setLocale(current === "fr" ? "en" : "fr");
  }

  function wire() {
    var doc = global.document;
    if (!doc) return;
    var btn = doc.getElementById("btnLang");
    if (btn && !btn.dataset.i18nWired) {
      btn.dataset.i18nWired = "1";
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        toggle();
      });
    }
    var code = doc.getElementById("langCode");
    if (code) code.textContent = current.toUpperCase();
    apply(doc);
    if (doc.documentElement.classList) doc.documentElement.classList.remove("i18n-pending");
  }

  global.I18N = {
    t: t,
    split: split,
    apply: apply,
    setLocale: setLocale,
    toggle: toggle,
    locale: function () { return current; },
    locales: ["fr", "en"],
    names: NAMES,
    /** Decimal separator for displayed numbers (fr uses the comma). */
    decimal: function () { return current === "fr" ? "," : "."; },
    /** BCP-47 tag for Intl / toLocaleString. */
    dateLocale: function () { return current === "fr" ? "fr-FR" : "en-GB"; },
    dictionary: DICT
  };

  /* This script is loaded at the end of <body>, so the markup is already parsed
     and the first (and only) paint can carry the translated text. */
  if (global.document) {
    if (global.document.readyState === "loading") {
      global.document.addEventListener("DOMContentLoaded", wire);
    } else {
      wire();
    }
  }
})(typeof window !== "undefined" ? window : this);
