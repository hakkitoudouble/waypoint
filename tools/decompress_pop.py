"""Decompress COTW ADF 'SAVE'/'COMP' container (zlib) and dump strings."""
import os
import re
import sys
import zlib

SAVE_DIR = r"C:\Users\Maelo\Documents\Avalanche Studios\COTW\Saves\76561199084637132"
OUT_DIR = r"C:\Users\Maelo\Documents\mods\cotw-pop\work\decompressed"


def decompress(path):
    data = open(path, "rb").read()
    assert data[:4] == b"SAVE", data[:4]
    # COMP chunk payload starts at 0x20
    out = bytearray()
    for start in range(0x20, len(data)):
        if data[start] == 0x78 and data[start + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            try:
                d = zlib.decompressobj()
                plain = d.decompress(data[start:])
                plain += d.flush()
                if len(plain) > 16:
                    out = plain
                    break
            except zlib.error:
                continue
    return bytes(out)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    names = sys.argv[1:] or sorted(
        [f for f in os.listdir(SAVE_DIR) if f.startswith("animal_population_")],
        key=lambda s: int(s.rsplit("_", 1)[1]),
    )
    for name in names:
        p = os.path.join(SAVE_DIR, name)
        plain = decompress(p)
        out = os.path.join(OUT_DIR, name + ".bin")
        open(out, "wb").write(plain)
        print(f"{name:24} compressed={os.path.getsize(p):>7}  decompressed={len(plain):>7}")


if __name__ == "__main__":
    main()
