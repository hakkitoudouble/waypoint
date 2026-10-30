"""Rebuild the exe's runtime string table (stringId -> English literal).

The scanner has no static `char*` table: during static initialisation it fills a 359-entry
pointer array at VA 0x1400EF3A0 with inline `lea reg,[rip+literal]` / `mov [rip+slot],reg`
pairs, once per UI language. Store order interleaves different registers, so the literal is
tracked per register. Grouping stores by slot and keeping the earliest one recovers the
English table.

Run:  python tools/fur_ids.py [out.json]
"""

from __future__ import annotations

import json
import sys

import capstone

import fur_pe

TABLE_VA = 0x1400EF3A0
TABLE_LEN = 359


def recover(data: bytes, secs) -> dict[int, str]:
    text = next(s for s in secs if s["name"] == ".text")
    code = data[text["raw"]: text["raw"] + text["raw_size"]]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    md.skipdata = True  # linear disassembly desynchronises; skip instead of stopping

    registers: dict[int, tuple[int, int]] = {}  # reg id -> (literal VA, lea address)
    stores: dict[int, tuple[int, int]] = {}     # slot VA -> (store address, literal VA)

    for insn in md.disasm(code, text["va"]):
        if insn.id == 0:  # skipped data byte
            registers.clear()
            continue
        rip_operand = None
        for operand in insn.operands:
            if operand.type == capstone.x86.X86_OP_MEM and \
                    operand.mem.base == capstone.x86.X86_REG_RIP:
                rip_operand = (insn.address + insn.size + operand.mem.disp)
                break
        if insn.mnemonic == "lea" and rip_operand is not None and len(insn.operands) >= 2:
            destination = insn.operands[0]
            if destination.type == capstone.x86.X86_OP_REG:
                registers[destination.reg] = (rip_operand, insn.address)
            continue
        if insn.mnemonic == "mov" and rip_operand is not None and len(insn.operands) == 2:
            destination, source = insn.operands
            if destination.type == capstone.x86.X86_OP_MEM and \
                    source.type == capstone.x86.X86_OP_REG and \
                    TABLE_VA <= rip_operand < TABLE_VA + TABLE_LEN * 8:
                pending = registers.get(source.reg)
                if pending is not None:
                    slot = rip_operand
                    previous = stores.get(slot)
                    if previous is None or pending[1] < previous[0]:
                        stores[slot] = (pending[1], pending[0])
            continue
        # any write to a register invalidates its remembered literal
        if insn.operands and insn.operands[0].type == capstone.x86.X86_OP_REG and \
                insn.operands[0].access and insn.operands[0].access & capstone.CS_AC_WRITE:
            registers.pop(insn.operands[0].reg, None)

    out: dict[int, str] = {}
    for slot, (_, literal) in stores.items():
        value = fur_pe.cstring(data, secs, literal)
        if value is None:
            continue
        out[(slot - TABLE_VA) // 8] = value.rstrip()
    return out


def main() -> int:
    data = fur_pe.load()
    secs = fur_pe.sections(data)
    table = recover(data, secs)
    print(f"recovered {len(table)} / {TABLE_LEN} slots")
    for index in (0, 15, 26, 97, 137, 138, 139, 143, 147, 306, 310, 358):
        print(f"  id {index:>3} = {table.get(index)!r}")
    out = sys.argv[1] if len(sys.argv) > 1 else r"work\localization-en-from-init.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump({str(k): v for k, v in sorted(table.items())}, handle,
                  indent=1, ensure_ascii=False)
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
