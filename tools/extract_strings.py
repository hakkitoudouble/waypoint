"""Extract ASCII and UTF-16LE strings from a binary, with file offsets."""
import re
import sys
import json

def strings_ascii(data, minlen=4):
    out = []
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, data):
        out.append((m.start(), "ascii", m.group().decode("ascii")))
    return out

def strings_utf16(data, minlen=4):
    out = []
    pat = rb"(?:[\x20-\x7e]\x00){%d,}" % minlen
    for m in re.finditer(pat, data):
        out.append((m.start(), "utf16", m.group().decode("utf-16-le")))
    return out

def main():
    path = sys.argv[1]
    with open(path, "rb") as f:
        data = f.read()
    items = strings_ascii(data) + strings_utf16(data)
    items.sort(key=lambda t: (t[0], t[1]))
    print(json.dumps(items, ensure_ascii=False))

if __name__ == "__main__":
    main()
