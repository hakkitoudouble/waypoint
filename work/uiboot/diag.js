const fs = require("fs"), path = require("path");
const { JSDOM } = require("jsdom");
const WEB = path.resolve("..", "..", "web");
const html = fs.readFileSync(path.join(WEB, "index.html"), "utf8");
const dom = new JSDOM(html, { url: "http://127.0.0.1:8791/", runScripts: "outside-only", pretendToBeVisual: true });
const { window } = dom, doc = window.document;
console.log("document.hidden =", doc.hidden, "| visibilityState =", doc.visibilityState);
console.log("btnLive =", !!doc.getElementById("btnLive"), "| liveCard =", !!doc.getElementById("liveCard"));
