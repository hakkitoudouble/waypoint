const fs = require("fs"), path = require("path"), http = require("http");
const { JSDOM } = require("jsdom");
const WEB = path.resolve(__dirname, "..", "..", "web");
const html = fs.readFileSync(path.join(WEB, "index.html"), "utf8");
const dom = new JSDOM(html, { url: "http://127.0.0.1:8791/", runScripts: "outside-only", pretendToBeVisual: true });
const { window } = dom, doc = window.document;
const payload = { player: {x:-7412,z:-12984}, count: 1, player_source:"save:16", player_age_seconds: 5,
  game_time: {hour: 6.25, hhmm: "06:15", age_seconds: 5},
  animals: [{ species: "Red Deer", x: -7500, y: 1200, z: -12900, distance: 120.4, hash_id: "0", fur: "Albino", fur_rarity: "very_rare" }] };
const pop = JSON.parse(fs.readFileSync(path.join(WEB, "fixture.js"), "utf8").replace(/^[^{]*/, "").replace(/;\s*$/, "")) ;
console.log("fixture parse ok?", !!pop);
