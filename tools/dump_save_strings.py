"""Dump printable ASCII + UTF-16 strings from save files (population/fog/etc)."""
import re
import sys
import os


def ascii_strings(data, minlen=5):
    return [m.group().decode("ascii") for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, data)]


def utf16_strings(data, minlen=5):
    return [m.group().decode("utf-16-le") for m in re.finditer(rb"(?:[\x20-\x7e]\x00){%d,}" % minlen, data)]


def main():
    path = sys.argv[1]
    minlen = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    with open(path, "rb") as f:
        data = f.read()
    a = ascii_strings(data, minlen)
    u = utf16_strings(data, minlen)
    print(f"### {os.path.basename(path)}  size={len(data)}")
    print(f"-- ascii strings: {len(a)} unique={len(set(a))}")
    seen = set()
    for s in a:
        if s not in seen:
            seen.add(s)
            print(f"   A {s!r}")
    print(f"-- utf16 strings: {len(u)} unique={len(set(u))}")
    seen = set()
    for s in u:
        if s not in seen:
            seen.add(s)
            print(f"   U {s!r}")


if __name__ == "__main__":
    main()
