"""Disassemble the scanner's map-rendering code, found through its string references.

The binary references strings RIP-relatively, which is why searching for absolute
pointers found nothing. So: take the virtual address of a map-related string, look in
`.text` for `lea reg, [rip+disp]` instructions that resolve to it, then disassemble a
window around each hit. Every RIP-relative memory operand is resolved and annotated with
its value, which is where the drawing constants live.

Run:  python tools/scanner_disasm.py "Map won't show any need zones"
      python tools/scanner_disasm.py "data/Maps/MapSRP_bw.png"
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import capstone

EXE = Path(
    r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 "
    r"2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\AnimalPopulationScanner.exe"
)
WINDOW = 320  # bytes disassembled on each side of a reference


def sections(data: bytes):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    table = pe + 24 + opt_size
    out = []
    for index in range(count):
        entry = table + index * 40
        name = data[entry: entry + 8].rstrip(b"\0").decode("latin-1")
        vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", data, entry + 8)
        out.append({"name": name, "va": va, "vsize": vsize,
                    "raw": raw_ptr, "raw_size": raw_size})
    return out


def off_to_va(offset: int, secs) -> int | None:
    for section in secs:
        if section["raw"] <= offset < section["raw"] + section["raw_size"]:
            return section["va"] + (offset - section["raw"])
    return None


def va_to_off(va: int, secs) -> int | None:
    for section in secs:
        if section["va"] <= va < section["va"] + section["raw_size"]:
            return section["raw"] + (va - section["va"])
    return None


def describe(data: bytes, secs, va: int) -> str:
    offset = va_to_off(va, secs)
    if offset is None or offset + 8 > len(data):
        return "?"
    raw = data[offset: offset + 64]
    text = "".join(chr(c) if 32 <= c < 127 else "." for c in raw[:32])
    parts = []
    for position in (0, 4):
        if offset + position + 4 <= len(data):
            f = struct.unpack_from("<f", data, offset + position)[0]
            ui = struct.unpack_from("<I", data, offset + position)[0]
            i = struct.unpack_from("<i", data, offset + position)[0]
            if f == f and 1e-6 < abs(f) < 1e7:
                parts.append(f"f{position}={f:.4f}")
            if abs(i) > 100:
                parts.append(f"i{position}={i}")
    printable = sum(1 for c in raw[:16] if 32 <= c < 127)
    if printable >= 10:
        parts.insert(0, f'"{text}"')
    return "  ".join(parts) if parts else "?"


def main() -> int:
    needle = (sys.argv[1] if len(sys.argv) > 1 else "Map won't show any need zones")
    data = EXE.read_bytes()
    secs = sections(data)
    text = next(s for s in secs if s["name"] == ".text")

    offset = data.find(needle.encode("utf-8"))
    if offset < 0:
        print(f"FAIL: string not found: {needle!r}")
        return 1
    string_va = off_to_va(offset, secs)
    print(f"string {needle!r}")
    print(f"  file 0x{offset:X}  va 0x{string_va:X}")

    # scan .text for RIP-relative LEA whose target resolves to the string
    code = data[text["raw"]: text["raw"] + text["raw_size"]]
    hits: list[int] = []
    for index in range(len(code) - 7):
        rex, opcode, modrm = code[index], code[index + 1], code[index + 2]
        if opcode != 0x8D:
            continue
        if (modrm & 0xC7) != 0x05:  # mod=00, rm=101 -> RIP-relative
            continue
        if not (0x48 <= rex <= 0x4F or 0x40 <= rex <= 0x4F or rex in (0x00,)):
            continue
        disp = struct.unpack_from("<i", code, index + 3)[0]
        insn_va = text["va"] + index
        target = insn_va + 7 + disp
        if target == string_va:
            hits.append(insn_va)

    print(f"  references found: {len(hits)} -> {[hex(h) for h in hits[:6]]}")
    if not hits:
        return 2

    disassembler = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    disassembler.detail = True

    for hit in hits[:4]:
        start_va = hit - WINDOW
        start_off = va_to_off(start_va, secs)
        if start_off is None:
            continue
        block = data[start_off: start_off + WINDOW * 2]
        print(f"\n{'=' * 78}\ncode around 0x{hit:X}\n{'=' * 78}")
        for insn in disassembler.disasm(block, start_va):
            marker = "  <== string ref" if insn.address == hit else ""
            note = ""
            for operand in insn.operands:
                if operand.type == capstone.x86.X86_OP_MEM and operand.mem.base == capstone.x86.X86_REG_RIP:
                    target = insn.address + insn.size + operand.mem.disp
                    info = describe(data, secs, target)
                    note += f"   ; [0x{target:X}] {info}"
            print(f"  0x{insn.address:06X}  {insn.mnemonic:<8} {insn.op_str:<40}{note}{marker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
