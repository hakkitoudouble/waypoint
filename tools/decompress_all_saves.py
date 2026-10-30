"""Decompress every SAVE/COMP file in the COTW save folder, then grep for keywords."""
import os
import re
import sys
import zlib

SAVE_DIR = r"C:\Users\Maelo\Documents\Avalanche Studios\COTW\Saves\76561199084637132"
OUT_DIR = r"C:\Users\Maelo\Documents\mods\cotw-pop\work\save_decompressed"


def decompress_file(path):
    data = open(path, "rb").read()
    if data[:4] != b"SAVE":
        return None
    for start in range(0x10, min(len(data), 256)):
        if data[start] == 0x78 and data[start + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            try:
                d = zlib.decompressobj()
                plain = d.decompress(data[start:])
                plain += d.flush()
                if len(plain) > 16:
                    return plain
            except zlib.error:
                continue
    return None


def walk(root):
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            yield os.path.join(dirpath, f)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for p in walk(SAVE_DIR):
        rel = os.path.relpath(p, SAVE_DIR).replace("\\", "__")
        plain = decompress_file(p)
        if plain is None:
            print(f"skip  {rel}")
            continue
        open(os.path.join(OUT_DIR, rel + ".bin"), "wb").write(plain)
        print(f"ok    {rel:50} {os.path.getsize(p):>8} -> {len(plain)}")


if __name__ == "__main__":
    main()
