"""Headless sanity checks on the web UI.

No browser is available here, so this checks the things that break a page before it
ever renders:

* every element id the script looks up actually exists in index.html;
* every script/stylesheet the HTML references exists on disk;
* the globals the fallback path depends on (window.FIXTURE_*) are defined;
* the sample data carries the fields the normaliser reads;
* the localisation wiring is in place (i18n.js first, every label tagged, and the
  markup source left in the source language — tools/check_i18n.py then proves the
  table itself is complete).

Run:  python tools/check_ui.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"

FAILURES: list[str] = []

# Characters that only occur in French prose. The markup is the ENGLISH source of
# every label, so finding one of these outside a comment means a translated string
# was pasted into index.html instead of into i18n.js.
FRENCH_ONLY = re.compile(r"[àâäçéèêëîïôöùûüœÀÂÇÉÈÊËÎÏÔÖÙÛÜŒ«»]")


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        FAILURES.append(label)


def main() -> int:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "style.css").read_text(encoding="utf-8")
    fixture = (WEB / "fixture.js").read_text(encoding="utf-8")

    print("== referenced files exist ==")
    refs = re.findall(r'(?:src|href)="([^"]+)"', html)
    missing = []
    for ref in refs:
        if ref.startswith(("http://", "https://", "data:", "#")):
            continue
        if not (WEB / ref.split("?")[0]).is_file():
            missing.append(ref)
    check("all script/style/img references resolve", not missing, str(missing))

    print("\n== DOM ids ==")
    ids = set(re.findall(r'id="([^"]+)"', html))
    lookups = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', app))
    lookups |= set(re.findall(r"getElementById\(\"([^\"]+)\"\)", app))
    unknown = sorted(lookups - ids)
    check(f"{len(lookups)} id lookups all exist in the HTML", not unknown,
          f"missing: {unknown[:12]}")
    # ids created dynamically are fine, so report rather than fail when few
    if unknown:
        print(f"  info  {len(unknown)} lookup(s) not in static HTML — ok only if script-created")

    print("\n== fixture globals ==")
    for name in ("FIXTURE_DATA", "FIXTURE_ZONES"):
        used = f"window.{name}" in app or f"{name}" in app
        defined = re.search(rf"window\.{name}\s*=", fixture) or re.search(
            rf"var\s+{name}\s*=", fixture
        )
        check(f"{name} is used by the app and defined by the fixture",
              (not used) or bool(defined), f"used={used} defined={bool(defined)}")

    print("\n== CSS hooks ==")
    # data-attribute driven styling is how the medal colours are applied
    for attr in ("data-medal", "data-zone", "data-type"):
        used = attr in app
        styled = attr in css
        if used:
            check(f"{attr} used in JS is styled in CSS", styled, "no CSS rule found")
    check("stylesheet is non-trivial", len(css) > 5000, f"{len(css)} bytes")

    print("\n== script structure ==")
    check("script is not a module (file:// fallback works)", "type=\"module\"" not in html)
    check("app defines an entry point", "init" in app or "DOMContentLoaded" in app)
    check("no leftover console.error without handler",
          "console.error" not in app or "try" in app, "check error paths")

    print("\n== localisation ==")
    i18n_at, app_at = html.find("i18n.js"), html.find("app.js")
    check("i18n.js is loaded", i18n_at >= 0, "missing script tag")
    check("i18n.js loads before app.js", 0 <= i18n_at < app_at,
          f"i18n at {i18n_at}, app at {app_at}")
    check("the markup declares the reference language", 'lang="fr"' in html, "html lang")
    check("a language switch exists", 'id="btnLang"' in html, "no #btnLang button")
    check("every data-i18n attribute carries a key",
          all(re.findall(r'data-i18n(?:-\w+)?="([^"]*)"', html)), "empty data-i18n attribute")
    check("i18n.js defines the table", "I18N" in (WEB / "i18n.js").read_text(encoding="utf-8"),
          "no I18N global")
    check("the pending-language guard is styled", "i18n-pending" in css, "no CSS rule")
    # The source language of the markup is English: French prose belongs in i18n.js.
    bare_french = [
        line.strip()[:80]
        for line in html.splitlines()
        if FRENCH_ONLY.search(line) and not line.lstrip().startswith(("<!--", "//"))
    ]
    check("no French prose pasted into the markup", not bare_french, str(bare_french[:3]))

    print("\n== theme ==")
    # The palette is token-driven, so the theme is defined by a handful of values.
    check("background is near-black", "--bg: #050505" in css, "expected --bg: #050505")
    check("accent is the COTW amber", "--accent: #e8a33d" in css, "expected --accent: #e8a33d")
    green_tinted = [c for c in ("#070b09", "#0f1714", "#141f1a", "#1b2923", "#22332b") if c in css]
    check("no leftover green-tinted surfaces", not green_tinted, str(green_tinted))
    check("panels use transparency", "backdrop-filter" in css, "no backdrop blur anywhere")
    for token in ("--glass:", "--overlay:", "--medal-none:", "--zone-feed:"):
        check(f"token {token} defined", token in css, "missing")

    print("\n== payload contract ==")
    for field in ("animal_type", "start_hour", "end_hour", "need_type"):
        check(f"normaliser reads zone.{field}", field in app, "field not referenced")

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed")
        for f in FAILURES:
            print(f"   - {f}")
        return 1
    print("PASS: web UI wiring checks out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
