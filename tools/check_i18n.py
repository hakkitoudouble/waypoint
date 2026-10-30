"""Static checks on the interface translations.

The UI ships in French (reference) and English (source). i18n.js holds the table,
the markup carries `data-i18n*` attributes and app.js calls t("English source").
This script refuses the build if any of that drifts apart:

* every key used by app.js / index.html exists in the table (no silent English);
* every key in the table is actually used (no dead weight);
* each translation keeps exactly the placeholders of its source string;
* no visible text node in index.html escapes translation;
* no `data-i18n` element has element children (apply() sets textContent, which
  would wipe them).

It evaluates web/i18n.js in Node, so it also proves the dictionary parses.

Run:  python tools/check_i18n.py            (checks French, the reference)
      python tools/check_i18n.py --verbose
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
I18N = WEB / "i18n.js"
APP = WEB / "app.js"
HTML = WEB / "index.html"

FAILURES: list[str] = []
VERBOSE = "--verbose" in sys.argv

NODE_CANDIDATES = [
    "node",
    r"C:\Users\Maelo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe",
]

# Strings that are legitimately identical in both languages: proper nouns, units
# and game terms the French community keeps in English.
IDENTICAL_OK = {
    "Great One", "Great Ones", "great one", "great ones",
    "Rare", "Super rare", "Bronze", "Zone", "Population", "Altitude", "Auto",
    "Score", "score", "CSV", "TR {score}", "animal",
    " · zones {confidence}",
    "Waypoint · theHunter: Call of the Wild companion",
}

# Proper nouns and format names that must not be translated.
NON_TRANSLATABLE_TEXT = {"Waypoint", "FR", "EN", "CSV"}

# Attributes i18n.apply() knows how to rewrite.
ATTRS = ("title", "aria-label", "placeholder", "alt", "content")

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        FAILURES.append(label)


# ── dictionary ───────────────────────────────────────────────────────────────


def find_node() -> str | None:
    for candidate in NODE_CANDIDATES:
        found = shutil.which(candidate) if not candidate.endswith(".exe") else candidate
        if found and Path(found).is_file():
            return found
    return None


def load_dictionary() -> dict[str, dict[str, str]]:
    """Evaluate i18n.js in Node and hand back its dictionary as JSON."""
    node = find_node()
    if node is None:
        sys.exit("cannot find node; run this from the project (see README)")

    script = """
const fs = require("fs"), vm = require("vm");
const code = fs.readFileSync(process.argv[1], "utf8");
const sandbox = { console, localStorage: { getItem: () => null, setItem: () => {} } };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox, { filename: "i18n.js" });
if (!sandbox.I18N) { console.error("i18n.js did not define window.I18N"); process.exit(3); }
process.stdout.write(JSON.stringify({
  dictionary: sandbox.I18N.dictionary,
  locales: sandbox.I18N.locales,
  locale: sandbox.I18N.locale(),
  decimal: sandbox.I18N.decimal(),
  dateLocale: sandbox.I18N.dateLocale()
}));
"""
    proc = subprocess.run(
        [node, "-e", script, str(I18N)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        sys.exit(f"node could not evaluate i18n.js:\n{proc.stderr.strip()}")
    return json.loads(proc.stdout)


# ── sources ──────────────────────────────────────────────────────────────────


def keys_from_app() -> set[str]:
    """Every t("…") / I18N.split("…") literal in app.js."""
    source = APP.read_text(encoding="utf-8")
    keys: set[str] = set()
    for match in re.finditer(r'(?<![\w.])t\(\s*"((?:[^"\\]|\\.)*)"', source):
        keys.add(match.group(1).replace('\\"', '"'))
    for match in re.finditer(r'I18N\.split\(\s*"((?:[^"\\]|\\.)*)"', source):
        keys.add(match.group(1).replace('\\"', '"'))
    return keys


class MarkupScan(HTMLParser):
    """Collects data-i18n keys, visible text nodes and nesting mistakes."""

    SKIP_TEXT = {"script", "style", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.keys: set[str] = set()
        self.bad_attrs: list[str] = []
        self.untranslated: list[str] = []
        self.nested: list[str] = []
        self.duplicate_content: list[str] = []
        self._stack: list[dict] = []
        self._skip_depth = 0

    # -- helpers
    def _in_skipped(self) -> bool:
        return self._skip_depth > 0

    def _textual_ancestor(self) -> bool:
        """True when an ancestor sets data-i18n (textContent would wipe children)."""
        return any(frame["text"] for frame in self._stack)

    def _tagged_ancestor(self) -> bool:
        return any(frame["any"] for frame in self._stack)

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        key = attr.get("data-i18n")
        if tag in self.SKIP_TEXT:
            self._skip_depth += 1
        if key is not None:
            self.keys.add(key)
            if self._textual_ancestor():
                self.nested.append(f"<{tag} data-i18n={key!r}>")
        for name, value in attr.items():
            if not name.startswith("data-i18n-"):
                continue
            attr_name = name[len("data-i18n-"):]
            if attr_name not in ATTRS:
                self.bad_attrs.append(name)
            self.keys.add(value or "")
            if attr_name == "content" and attr.get("content") != value:
                self.duplicate_content.append(tag)
        if tag not in ("br", "img", "input", "meta", "link", "hr", "use", "path",
                       "circle", "source", "col", "rect"):
            self._stack.append({
                "tag": tag,
                "text": key is not None,
                "any": key is not None or any(n.startswith("data-i18n") for n in attr),
            })

    def handle_endtag(self, tag):
        if tag in self.SKIP_TEXT:
            self._skip_depth = max(0, self._skip_depth - 1)
        for depth in range(len(self._stack) - 1, -1, -1):
            if self._stack[depth]["tag"] == tag:
                del self._stack[depth:]
                break

    def handle_data(self, data):
        text = data.strip()
        if not text or self._in_skipped():
            return
        if not re.search(r"[^\W\d_]", text):
            return  # numbers, units, punctuation, em dashes: not language
        if text in NON_TRANSLATABLE_TEXT:
            return
        if self._textual_ancestor():
            return
        self.untranslated.append(text[:70])


def main() -> int:
    print("== i18n.js parses ==")
    bundle = load_dictionary()
    table = bundle["dictionary"]
    fr = table.get("fr") or {}
    en = table.get("en") or {}
    check(f"node evaluated i18n.js ({len(fr)} French entries)", bool(fr), "empty table")
    check("French is the reference locale", bundle["locale"] == "fr", str(bundle["locale"]))
    check("locales are fr + en", bundle["locales"] == ["fr", "en"], str(bundle["locales"]))
    check("French numbers use the decimal comma", bundle["decimal"] == ",", bundle["decimal"])
    check("English overrides stay empty (English is the source)", en == {}, str(list(en)[:5]))
    check("French uses a French date locale", bundle["dateLocale"].startswith("fr"),
          bundle["dateLocale"])

    print("\n== keys used by the code exist ==")
    app_keys = keys_from_app()
    index_keys_scan = MarkupScan()
    index_keys_scan.feed(HTML.read_text(encoding="utf-8"))
    index_keys = {k for k in index_keys_scan.keys if k}
    missing_app = sorted(app_keys - set(fr))
    missing_html = sorted(index_keys - set(fr))
    check(f"{len(app_keys)} t() keys in app.js all translated", not missing_app,
          f"missing: {missing_app[:8]}")
    check(f"{len(index_keys)} data-i18n keys in index.html all translated", not missing_html,
          f"missing: {missing_html[:8]}")

    print("\n== no dead entries ==")
    unused = sorted(set(fr) - app_keys - index_keys)
    check("every French entry is used somewhere", not unused, f"unused: {unused[:8]}")

    print("\n== placeholders survive translation ==")
    broken = []
    for key, value in fr.items():
        if set(PLACEHOLDER.findall(key)) != set(PLACEHOLDER.findall(value)):
            broken.append(f"{key!r} → {value!r}")
    check("each translation keeps its {placeholders}", not broken, "; ".join(broken[:4]))

    print("\n== no untranslated copy ==")
    copies = sorted(k for k, v in fr.items() if k == v and k not in IDENTICAL_OK)
    check("no French value is a plain copy of its English key", not copies,
          f"{copies[:6]}")

    print("\n== markup is fully tagged ==")
    scan = MarkupScan()
    scan.feed(HTML.read_text(encoding="utf-8"))
    check("no unknown data-i18n-* attribute", not scan.bad_attrs, str(scan.bad_attrs[:5]))
    check("every visible text node is translatable", not scan.untranslated,
          f"bare text: {scan.untranslated[:8]}")
    check("no data-i18n element has element children", not scan.nested, str(scan.nested[:5]))
    check("meta description key matches its content", not scan.duplicate_content,
          str(scan.duplicate_content))

    print("\n== app wiring ==")
    app_source = APP.read_text(encoding="utf-8")
    check("app.js falls back to the key when i18n.js is missing",
          "window.I18N ? window.I18N.t(key, vars) : key" in app_source, "no fallback")
    check("app.js leaves no bare label literal behind",
          not re.search(r'(?:textContent|\.title|placeholder|aria-label)\s*=\s*"[A-Z][a-z]',
                        app_source), "found a hard-coded label")
    check("index.html loads i18n.js before app.js",
          HTML.read_text(encoding="utf-8").find("i18n.js")
          < HTML.read_text(encoding="utf-8").find("app.js"), "wrong order")

    if VERBOSE:
        print("\n== entries ==")
        for key in sorted(fr):
            print(f"  {key!r}\n    → {fr[key]!r}")

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed")
        for failure in FAILURES:
            print(f"   - {failure}")
        return 1
    print("PASS: the French interface is complete and every key resolves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
