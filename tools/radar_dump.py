"""Dump the Python modules of the AnimalRadar bundle as disassembly.

We extract the PYZ by direct search (the CArchive TOC offsets do not point where the
naive parse expects), then unmarshal each module and write its bytecode disassembly.
Same CPython 3.12 here and there, so no third-party decompiler is needed.

Run:  python tools/radar_dump.py <bundle.exe> [outdir]
"""

from __future__ import annotations

import marshal
import struct
import sys
import zlib
from pathlib import Path

STDLIB_PREFIXES = (
    "encodings", "importlib", "collections", "email", "json", "xml", "urllib", "http",
    "unittest", "logging", "asyncio", "concurrent", "ctypes", "sqlite3", "multiprocessing",
    "PySide6", "shiboken6", "pyimod", "_", "abc", "codecs", "io", "os", "re", "sre_",
    "traceback", "weakref", "typing", "struct", "hashlib", "datetime", "functools",
)


def load_pyz(data: bytes) -> tuple[int, dict]:
    position = data.find(b"PYZ\0")
    if position < 0:
        raise SystemExit("FAIL: no PYZ in bundle")
    toc_offset = struct.unpack_from("!I", data, position + 8)[0]
    raw = marshal.loads(data[position + toc_offset:])
    # the TOC is normally a dict; accept a list of (name, entry) pairs too
    if isinstance(raw, dict):
        return position, raw
    return position, {name: entry for name, entry in raw}


def module_code(pyz: bytes, entry: tuple[int, int, int]):
    _, offset, length = entry
    blob = pyz[offset: offset + length]
    try:
        blob = zlib.decompress(blob)
    except zlib.error:
        pass
    return marshal.loads(blob)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: radar_dump.py <bundle.exe> [outdir]")
        return 1
    bundle = Path(sys.argv[1])
    outdir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("work/radar")
    outdir.mkdir(parents=True, exist_ok=True)

    data = bundle.read_bytes()
    position, toc = load_pyz(data)
    pyz = data[position:]
    print(f"PYZ @0x{position:X}, {len(toc)} modules")

    app = [name for name in sorted(toc) if not name.startswith(STDLIB_PREFIXES)]
    print(f"application modules ({len(app)}):")
    for name in app:
        print(f"   {name}")

    (outdir / "modules.txt").write_text("\n".join(sorted(toc)), encoding="utf-8")

    import dis
    import io

    for name in app:
        try:
            code = module_code(pyz, toc[name])
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {name}: {exc}")
            continue
        buffer = io.StringIO()

        def walk(co, depth=0):
            buffer.write("\n" + "=" * 70 + "\n")
            buffer.write(f"{'  ' * depth}CODE {co.co_name}  args={co.co_varnames[:co.co_argcount]}\n")
            buffer.write("=" * 70 + "\n")
            for const in co.co_consts:
                if isinstance(const, str) and len(const) > 2:
                    buffer.write(f"  const: {const!r}\n")
            buffer.write("\n")
            dis.dis(co, file=buffer, depth=0)
            for const in co.co_consts:
                if hasattr(const, "co_code"):
                    walk(const, depth + 1)

        walk(code)
        target = outdir / (name.replace(".", "_") + ".asm.txt")
        target.write_text(buffer.getvalue(), encoding="utf-8")
        print(f"  wrote {target.name}  ({len(buffer.getvalue()) // 1024} KiB)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
