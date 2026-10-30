"""Command-line live radar.

Usage:
    python tools/radar.py discover                 # one full scan, caches entities
    python tools/radar.py watch --x -7583.5 --z -13065.6 [--hz 5]
    python tools/radar.py once  --x -7583.5 --z -13065.6

The player position is required for distances: the game's own coordinate readout is the
only trustworthy source, and reading it back from memory is still unsolved on this
build (its X is found, its Z is not stored as a float32 that matches the display).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw.radar import Radar  # noqa: E402


def print_snapshot(animals, elapsed_ms: float, player) -> None:
    print(f"\033[2J\033[H", end="")  # clear
    print(f"player ({player[0]:.1f}, {player[1]:.1f})   "
          f"{len(animals)} animals   refresh {elapsed_ms:.1f} ms")
    print(f"{'dist m':>7}  {'species':<24} {'x':>10} {'y':>8} {'z':>10}")
    for animal in animals[:30]:
        print(f"{animal.distance:>7.0f}  {animal.species:<24} "
              f"{animal.x:>10.1f} {animal.y:>8.1f} {animal.z:>10.1f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="live animal radar")
    parser.add_argument("mode", choices=("discover", "watch", "once", "cache"))
    parser.add_argument("--x", type=float, default=None)
    parser.add_argument("--z", type=float, default=None)
    parser.add_argument("--hz", type=float, default=5.0)
    parser.add_argument("--seconds", type=float, default=30.0)
    args = parser.parse_args()

    radar = Radar()

    if args.mode == "discover":
        print("scanning process memory — this takes about 2.5 minutes...")
        count = radar.discover()
        print(f"discovered {count} live entities")
        return 0 if count else 2

    cached = radar.load_cache()
    print(f"loaded {cached} entities from cache")

    if args.mode == "cache":
        for animal in radar.refresh(None)[:20]:
            print(f"  {animal.species:<24} {animal.x:>10.1f} {animal.y:>8.1f} {animal.z:>10.1f}")
        return 0

    if args.x is None or args.z is None:
        print("FAIL: --x and --z are required for distances")
        return 1
    player = (args.x, args.z)

    if args.mode == "once":
        started = time.perf_counter()
        animals = radar.refresh(player)
        elapsed = (time.perf_counter() - started) * 1000
        print_snapshot(animals, elapsed, player)
        return 0

    deadline = time.time() + args.seconds
    period = 1.0 / max(0.5, args.hz)
    while time.time() < deadline:
        started = time.perf_counter()
        animals = radar.refresh(player)
        elapsed = (time.perf_counter() - started) * 1000
        print_snapshot(animals, elapsed, player)
        time.sleep(max(0.0, period - (time.perf_counter() - started)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
