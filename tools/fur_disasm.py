"""Annotated disassembly of a VA range in the scanner.

Every RIP-relative memory operand is resolved and described (string / int / float / pointer),
so table walks inside `.text` can be read directly.

Run:  python tools/fur_disasm.py 0x140056900 0x140056B80
"""

from __future__ import annotations

import struct
import sys

import capstone

import fur_pe


def describe(data: bytes, secs, va: int) -> str:
    offset = fur_pe.va_to_off(va, secs)
    if offset is None or offset + 8 > len(data):
        return ""
    section = fur_pe.section_of(va, secs)
    parts = [section]
    text = fur_pe.cstring(data, secs, va, 48)
    if text is not None:
        safe = "".join(c if 32 <= ord(c) < 127 else "\\x%02x" % ord(c) for c in text)
        parts.append(f'"{safe}"')
    else:
        qword = struct.unpack_from("<Q", data, offset)[0]
        dword = struct.unpack_from("<I", data, offset)[0]
        single = struct.unpack_from("<f", data, offset)[0]
        if fur_pe.IMAGE_BASE <= qword < fur_pe.IMAGE_BASE + 0x200000:
            parts.append(f"ptr 0x{qword:X}")
        if 0 < dword < 100000:
            parts.append(f"u32={dword}")
        if 1e-6 < abs(single) < 1e6:
            parts.append(f"f32={single:.6g}")
    return "  ".join(parts)


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    start = int(sys.argv[1], 0)
    end = int(sys.argv[2], 0)
    data = fur_pe.load()
    secs = fur_pe.sections(data)
    start_offset = fur_pe.va_to_off(start, secs)
    block = data[start_offset: start_offset + (end - start)]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    md.skipdata = True
    for insn in md.disasm(block, start):
        if insn.id == 0:
            print(f"  0x{insn.address:X}  .byte 0x{block[insn.address - start]:02X}")
            continue
        note = ""
        for operand in insn.operands:
            if operand.type == capstone.x86.X86_OP_MEM and \
                    operand.mem.base == capstone.x86.X86_REG_RIP:
                target = insn.address + insn.size + operand.mem.disp
                note = f"   ; [0x{target:X}] {describe(data, secs, target)}"
        print(f"  0x{insn.address:X}  {insn.mnemonic:<8} {insn.op_str:<42}{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
