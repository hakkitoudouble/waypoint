"""Store a measured georeference for a reserve's map image.

The plotting box is, by default, derived from the zones themselves
(`population.fitted_world`): their bounding box, padded 6 % and aspect-corrected.
That is circular — it makes the zones fill the image edge to edge wherever the reserve
really sits, so absolute placement is wrong even though the image looks plausible.

Two (world position, image pixel) pairs fix everything: scale and offset on both axes,
and the orientation. The easiest pairs to obtain are the corners of the reserve as the
in-game map cursor reads them, with the cursor parked on the image's top-left and
bottom-right corners.

Usage:
    python tools/calibrate_map.py --reserve 9 --tl -13250,-15200 --br 2100,-4800
    python tools/calibrate_map.py --reserve 9 --tl 2100,-4800 --br -13250,-15200 --flip
    python tools/calibrate_map.py --list
    python tools/calibrate_map.py --reserve 9 --clear
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw import mapgeo, reserves  # noqa: E402


def pair(text: str) -> tuple[float, float]:
    parts = text.replace(";", ",").split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("expected 'x,z'")
    return float(parts[0]), float(parts[1])


def main() -> int:
    parser = argparse.ArgumentParser(description="per-reserve map georeference")
    parser.add_argument("--reserve", type=int)
    parser.add_argument("--tl", type=pair, help="world x,z of the image's TOP-LEFT pixel")
    parser.add_argument("--br", type=pair, help="world x,z of the image's BOTTOM-RIGHT pixel")
    parser.add_argument("--flip", action="store_true", help="z grows upward on the image")
    parser.add_argument("--clear", action="store_true", help="drop the stored calibration")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        stored = mapgeo.load()
        if not stored:
            print("no calibration stored")
        for key, entry in sorted(stored.items(), key=lambda kv: int(kv[0])):
            meta = reserves.lookup(int(key))
            print(f"reserve {key:>3} {meta.display_name:<26} "
                  f"x[{entry['min_x']:.0f}..{entry['max_x']:.0f}] "
                  f"z[{entry['min_z']:.0f}..{entry['max_z']:.0f}] "
                  f"flip={entry.get('flip_z')}  {entry.get('source')}")
        return 0

    if args.reserve is None:
        parser.error("--reserve is required")

    if args.clear:
        payload = mapgeo.load()
        payload.pop(str(args.reserve), None)
        mapgeo.DATA.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"cleared calibration for reserve {args.reserve}")
        return 0

    if not args.tl or not args.br:
        parser.error("--tl and --br are required")

    meta = reserves.lookup(args.reserve)
    box = mapgeo.calibrate_from_corners(
        args.reserve, args.tl, args.br, meta.pixel_size, flip_z=not args.flip
    )
    print(f"reserve {args.reserve} ({meta.display_name})")
    print(f"  x[{box['min_x']:.0f} .. {box['max_x']:.0f}]  "
          f"z[{box['min_y']:.0f} .. {box['max_y']:.0f}]")
    span_x = box["max_x"] - box["min_x"]
    span_z = box["max_y"] - box["min_y"]
    print(f"  span {span_x:.0f} x {span_z:.0f} m   "
          f"{meta.pixel_size[0] / max(span_x, 1):.4f} px/m (x), "
          f"{meta.pixel_size[1] / max(span_z, 1):.4f} px/m (z)")
    if abs(span_x / max(span_z, 1) - meta.pixel_size[0] / meta.pixel_size[1]) > 0.08:
        print("  WARNING: the span's aspect ratio does not match the image's — "
              "the two readings probably are not opposite corners.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

