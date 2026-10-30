"""Find code/data references into a chosen VA range.

Two passes:
  * disassemble .text and report every RIP-relative memory operand whose target lands in
    [lo, hi)  (this is how MSVC reaches globals in a PIE image);
  * scan the whole file for 8-byte absolute pointers into [lo, hi).

Run:  python tools/fur_xref.py 0x1400CD000 0x1400EF500
"""

from __future__ import annotations

import struct
import sys

import capstone

import fur_pe


def main() -> int:
    lo = int(sys.argv[1], 0)
    hi = int(sys.argv[2], 0)
    data = fur_pe.load()
    secs = fur_pe.sections(data)
    text = next(s for s in secs if s["name"] == ".text")

    code = data[text["raw"]: text["raw"] + text["raw_size"]]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True

    print(f"== RIP-relative refs into 0x{lo:X}..0x{hi:X} ==")
    refs = []
    for insn in md.disasm(code, text["va"]):
        for operand in insn.operands:
            if operand.type == capstone.x86.X86_OP_MEM and \
                    operand.mem.base == capstone.x86.X86_REG_RIP:
                target = insn.address + insn.size + operand.mem.disp
                if lo <= target < hi:
                    refs.append((insn.address, target, f"{insn.mnemonic} {insn.op_str}"))
                    break
    for address, target, text_repr in refs:
        print(f"  0x{address:X}  -> 0x{target:X}   {text_repr}")
    print(f"   total {len(refs)}")

    print(f"\n== absolute qword pointers into 0x{lo:X}..0x{hi:X} ==")
    hits = []
    for offset in range(0, len(data) - 8):
        value = struct.unpack_from("<Q", data, offset)[0]
        if lo <= value < hi:
            hits.append((offset, value))
    for offset, value in hits[:80]:
        va = fur_pe.off_to_va(offset, secs)
        print(f"  file 0x{offset:06X} va 0x{va:X} -> 0x{value:X} ({fur_pe.section_of(value, secs)})")
    print(f"   total {len(hits)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
