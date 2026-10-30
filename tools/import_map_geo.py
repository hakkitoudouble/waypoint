"""Recover the scanner's per-reserve map georeference and store it for our app.

Reverse-engineered from `AnimalPopulationScanner.exe` at 0x653A5:

    pixel_x = (world_x - origin_x) * width * scale / 800
    pixel_y = (world_z - origin_z) * width * scale / 800

with a table of three floats per reserve index at VA 0xB0040 (file offset 0xAE240):
`origin_x`, `origin_z`, `scale`. The same `width * scale / 800` factor is used for both
axes, so the mapping is isotropic — about 0.1246 px/m, i.e. 8 metres per pixel, on every
reserve. That uniformity is what makes the recovery trustworthy: the scale constant is
only there so that images of different widths keep that same ground resolution.

Verify against the player: on reserve 9 the box works out to x[-9780..1002],
z[-13380..-5191], which puts (-7570.5, -13071.9) at 20.5 % from the left and 3.8 % from
the top — the top-left corner, exactly where the player reports standing.

Run:  python tools/import_map_geo.py
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cotw import mapgeo, reserves  # noqa: E402

EXE = Path(
    r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 "
    r"2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\AnimalPopulationScanner.exe"
)
TABLE_OFFSET = 0xAE240          # file offset of VA 0xB0040
REFERENCE_WIDTH_M = 800.0       # the divisor baked into the scanner's formula


def read_table() -> list[tuple[float, float, float]]:
    data = EXE.read_bytes()
    return [struct.unpack_from("<3f", data, TABLE_OFFSET + index * 12) for index in range(24)]


def main() -> int:
    table = read_table()
    payload = mapgeo.load()
    written = 0
    print(f"{'idx':<4}{'reserve':<28}{'origin':>20}{'span':>18}{'px/m':>9}{'inside':>8}")
    print("-" * 88)

    for index, (origin_x, origin_z, scale) in enumerate(table):
        meta = reserves.lookup(index)
        if meta.pixel_size is None or scale in (0.0, 1.0):
            continue
        width, height = meta.pixel_size
        ppm = width * scale / REFERENCE_WIDTH_M
        if ppm <= 0:
            continue
        span_x = width / ppm
        span_z = height / ppm
        box = {
            "min_x": origin_x,
            "max_x": origin_x + span_x,
            "min_y": origin_z,
            "max_y": origin_z + span_z,
            "flip_z": False,
        }

        # every zone of the reserve must fall inside its own box
        from cotw import population, save

        directory = save.find_save_dirs()
        inside = 0
        total = 0
        if directory:
            zones = population.scan_need_zones(directory[0]).get(index, [])
            for zone in zones:
                total += 1
                if box["min_x"] <= zone.x <= box["max_x"] and box["min_y"] <= zone.z <= box["max_y"]:
                    inside += 1
        ratio = inside / total if total else 1.0

        mapgeo.save(index, box, meta.pixel_size, source="scanner-table:0xB0040")
        written += 1
        print(f"{index:<4}{(meta.display_name or '?'):<28}"
              f"({origin_x:>8.0f},{origin_z:>8.0f})"
              f"{span_x:>9.0f}x{span_z:<8.0f}{ppm:>9.4f}{ratio:>7.0%}")

    print("-" * 88)
    print(f"ecrit {written} reserve(s) dans {mapgeo.DATA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
