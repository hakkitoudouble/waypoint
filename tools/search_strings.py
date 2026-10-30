"""Search extracted strings for keywords, print offset/encoding/string."""
import json
import sys

STRINGS = r"C:\Users\Maelo\Documents\mods\cotw-pop\work\strings.json"

def load():
    return json.load(open(STRINGS, encoding="utf-8-sig"))

def main():
    keys = sys.argv[1:]
    items = load()
    seen = set()
    for off, kind, s in items:
        low = s.lower()
        if any(k.lower() in low for k in keys):
            if s in seen:
                continue
            seen.add(s)
            print(f"{off:>9} {kind:5} {s!r}")

if __name__ == "__main__":
    main()
