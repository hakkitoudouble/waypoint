"""RIP-relative xref finder + disassembler for the target PE."""
import sys, os, json, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor'))
from pe import PE
import capstone
from capstone import x86 as X

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
md.detail = True
md.skipdata = True

def iter_insns(pe, ss=None):
    """Yield (va, size, disasm_text, insn) for .text (or given section)."""
    for s in pe.sections:
        if ss and s.name != ss: continue
        if ss is None and s.name != '.text': continue
        base = s.rawptr; va = s.vaddr + pe.image_base
        code = pe.b[base:base + s.rawsize]
        for insn in md.disasm(code, va):
            yield insn

def xrefs(pe):
    """map target_va -> [(insn_va, insn_size, mnemonic, op_str)]"""
    xr = {}
    for insn in iter_insns(pe):
        try:
            ops = insn.operands
        except Exception:
            continue
        for op in ops:
            if op.type == X.X86_OP_MEM and op.mem.base == X.X86_REG_RIP:
                tgt = insn.address + insn.size + op.mem.disp
                xr.setdefault(tgt, []).append((insn.address, insn.size, insn.mnemonic, insn.op_str, insn.bytes.hex()))
            elif op.type == X.X86_OP_IMM:
                v = op.imm
                if pe.image_base <= v < pe.image_base + pe.size_of_image:
                    xr.setdefault(v, []).append((insn.address, insn.size, insn.mnemonic, insn.op_str, insn.bytes.hex()))
    return xr

def xrefs_linear(pe):
    """Fast structural scan for `lea r64,[rip+d]` and `mov r64,[rip+d]` without full disasm."""
    out = {}
    b = pe.b
    for s in pe.sections:
        if s.name != '.text': continue
        o = s.rawptr; end = s.rawptr + s.rawsize - 7
        va = s.vaddr + pe.image_base
        while o <= end:
            p = o
            rex = b[p]
            if rex in (0x48, 0x4C):          # REX.W (with/without R)
                op2 = b[p+1]
                if op2 in (0x8D, 0x8B, 0x89):
                    modrm = b[p+2]
                    if (modrm & 0xC7) == 0x05:   # mod=00 rm=101 -> rip-rel
                        disp = struct.unpack_from('<i', b, p+3)[0]
                        nxt = (p - s.rawptr) + s.vaddr + pe.image_base + 7
                        tgt = nxt + disp
                        insva = (p - s.rawptr) + va
                        out.setdefault(tgt, []).append((insva, 7, '%02x%02x%02x' % (rex,op2,modrm)))
                        o += 7; continue
            o += 1
    return out

def disasm_range(pe, va, n, label=None):
    off = pe.va_to_off(va)
    if off is None:
        print("VA %X not mapped" % va); return
    code = pe.b[off:off+n]
    print("=== disasm VA %X (file %X) ===" % (va, off))
    for insn in md.disasm(code, va):
        print("  %016X  %-24s %-8s %s" % (insn.address, insn.bytes.hex(), insn.mnemonic, insn.op_str))

if __name__ == '__main__':
    pe = PE(sys.argv[1])
    cmd = sys.argv[2]
    if cmd == 'xr':
        tgt = int(sys.argv[3], 0)
        xr = xrefs(pe)
        got = xr.get(tgt, [])
        print("VA %X : %d xrefs" % (tgt, len(got)))
        for a, sz, m, o, by in got:
            print("   at %016X (file %08X) %s %s   [%s]" % (a, pe.va_to_off(a), m, o, by))
    elif cmd == 'dump':
        va = int(sys.argv[3], 0); n = int(sys.argv[4], 0)
        disasm_range(pe, va, n)
    elif cmd == 'xrefs':
        # dump all xrefs into .rdata strings, as json
        xr = xrefs_linear(pe)
        out = {}
        for tgt, lst in xr.items():
            off = pe.va_to_off(tgt)
            if off is None: continue
            sec = pe.section_of_off(off)
            if sec and sec.name in ('.rdata', '.data'):
                out["%X" % tgt] = [[a] for a,_,_ in lst]
        json.dump(out, open(sys.argv[3], 'w'), indent=0)
        print("wrote %d targets" % len(out))
