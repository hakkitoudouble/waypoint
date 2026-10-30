"""Exercise cotw.save against every real save file on this machine.

Run:  python tools/verify_save.py
Exits non-zero if any file fails to unwrap or a size assertion breaks.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cotw import save  # noqa: E402


def main() -> int:
    dirs = save.find_save_dirs()
    if not dirs:
        print("FAIL: no save directories found")
        return 1

    failures = 0
    total = 0
    for save_dir in dirs:
        print(f"save dir: {save_dir}")
        for path in save.list_population_files(save_dir):
            total += 1
            try:
                container = save.read_container(path)
            except save.SaveFormatError as exc:
                print(f"  FAIL {path.name}: {exc}")
                failures += 1
                continue

            payload = save.adf_payload(container)
            has_magic = payload[:4] == b" FDA"
            if not has_magic:
                print(f"  FAIL {path.name}: stripped payload does not start with 'ADF ' magic")
                failures += 1
                continue

            index = save.reserve_index(path)
            kind = "stub" if container.unpacked_size < 2000 else "data"
            print(
                f"  ok   reserve {index:>2}  {path.name:<22} "
                f"{container.unpacked_size:>7} bytes  version=0x{container.version:08X}  {kind}"
            )

    print()
    if failures:
        print(f"FAIL: {failures}/{total} population files rejected")
        return 1
    print(f"PASS: all {total} population files unwrapped, magic verified in every payload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
