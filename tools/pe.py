"""Minimal PE parser + VA<->file-offset mapping. No external deps."""
import struct, sys, os

def u16(b, o): return struct.unpack_from('<H', b, o)[0]
def u32(b, o): return struct.unpack_from('<I', b, o)[0]
def u64(b, o): return struct.unpack_from('<Q', b, o)[0]

class Section:
    def __init__(self, name, vsize, vaddr, rawsize, rawptr, chars):
        self.name = name; self.vsize = vsize; self.vaddr = vaddr
        self.rawsize = rawsize; self.rawptr = rawptr; self.chars = chars
    def __repr__(self):
        return ("<%-9s VA=%08X VS=%08X RAW=%08X RS=%08X %s>" %
                (self.name, self.vaddr, self.vsize, self.rawptr, self.rawsize,
                 'R' if self.chars & 0x40000000 else '-') +
                 ('W' if self.chars & 0x80000000 else '-') +
                 ('X' if self.chars & 0x20000000 else '-') +
                 ('C' if self.chars & 0x20 else '-'))

class PE:
    def __init__(self, path):
        self.path = path
        self.b = open(path, 'rb').read()
        b = self.b
        assert b[:2] == b'MZ', "not MZ"
        e_lfanew = u32(b, 0x3C)
        assert b[e_lfanew:e_lfanew+4] == b'PE\0\0', "no PE sig"
        coff = e_lfanew + 4
        self.machine = u16(b, coff)
        self.nsect = u16(b, coff + 2)
        self.timestamp = u32(b, coff + 4)
        self.symptr = u32(b, coff + 8)
        self.nsyms = u32(b, coff + 12)
        self.opt_size = u16(b, coff + 16)
        self.chars = u16(b, coff + 18)
        opt = coff + 20
        self.opt = opt
        magic = u16(b, opt)
        self.magic = magic
        assert magic == 0x20B, "not PE32+ (magic %04X)" % magic
        self.entry = u32(b, opt + 16)
        self.base_of_code = u32(b, opt + 20)
        self.image_base = u64(b, opt + 24)
        self.sect_align = u32(b, opt + 32)
        self.file_align = u32(b, opt + 36)
        self.size_of_image = u32(b, opt + 56)
        self.size_of_headers = u32(b, opt + 60)
        self.checksum = u32(b, opt + 64)
        self.subsystem = u16(b, opt + 68)
        self.dllchars = u16(b, opt + 70)
        self.stackres = u64(b, opt + 72)
        self.stackcommit = u64(b, opt + 80)
        self.heapres = u64(b, opt + 88)
        self.heapcommit = u64(b, opt + 96)
        self.loaderflags = u32(b, opt + 104)
        self.nrva = u32(b, opt + 108)
        # data directories start at opt+112
        self.ddirs = []
        for i in range(min(self.nrva, 16)):
            rva = u32(b, opt + 112 + i*8)
            sz = u32(b, opt + 116 + i*8)
            self.ddirs.append((rva, sz))
        self.sections = []
        st = opt + self.opt_size
        for i in range(self.nsect):
            o = st + i*40
            raw = b[o:o+40]
            name = raw[:8].rstrip(b'\0').decode('latin-1')
            vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', raw, 8)
            chars = u32(raw, 36)
            self.sections.append(Section(name, vsize, vaddr, rawsize, rawptr, chars))

    # ---- VA / RVA conversion ----
    def rva_to_off(self, rva):
        for s in self.sections:
            span = max(s.vsize, s.rawsize)
            if s.vaddr <= rva < s.vaddr + span:
                delta = rva - s.vaddr
                if delta < s.rawsize:
                    return s.rawptr + delta
                return None  # in virtual-only (zero-filled) tail
        return None

    def va_to_off(self, va):
        return self.rva_to_off(va - self.image_base)

    def off_to_rva(self, off):
        for s in self.sections:
            if s.rawptr <= off < s.rawptr + s.rawsize:
                return s.vaddr + (off - s.rawptr)
        return None

    def off_to_va(self, off):
        r = self.off_to_rva(off)
        return None if r is None else r + self.image_base

    def section_of_rva(self, rva):
        for s in self.sections:
            span = max(s.vsize, s.rawsize)
            if s.vaddr <= rva < s.vaddr + span:
                return s
        return None

    def section_of_off(self, off):
        for s in self.sections:
            if s.rawptr <= off < s.rawptr + s.rawsize:
                return s
        return None

    def dump_layout(self):
        out = []
        out.append("FILE   : %s (%d bytes)" % (self.path, len(self.b)))
        out.append("MACHINE: %04X   SUBSYSTEM: %d   DLLCHAR: %04X" % (self.machine, self.subsystem, self.dllchars))
        out.append("IMAGE_BASE: %016X   ENTRY(RVA): %08X  VA=%016X" % (self.image_base, self.entry, self.entry + self.image_base))
        out.append("SECT_ALIGN=%X  FILE_ALIGN=%X  SIZE_OF_IMAGE=%X  SIZE_OF_HEADERS=%X" %
                   (self.sect_align, self.file_align, self.size_of_image, self.size_of_headers))
        out.append("TIMESTAMP: %08X  -> %s" % (self.timestamp, ts_str(self.timestamp)))
        out.append("")
        out.append("%-9s %10s %10s %10s %10s %5s" % ("name", "VAddr", "VSize", "RawPtr", "RawSize", "flags"))
        for s in self.sections:
            out.append("%-9s %10X %10X %10X %10X %5s" % (s.name, s.vaddr, s.vsize, s.rawptr, s.rawsize,
                ('R' if s.chars & 0x40000000 else '-') + ('W' if s.chars & 0x80000000 else '-') +
                ('X' if s.chars & 0x20000000 else '-') + ('C' if s.chars & 0x20 else '-')))
        ddnames = ["Export","Import","Resource","Exception","Certificate","BaseReloc","Debug","Arch",
                   "GlobalPtr","TLS","LoadConfig","BoundImport","IAT","DelayImport","CLR","Reserved"]
        out.append("")
        out.append("DATA DIRECTORIES:")
        for i, (rva, sz) in enumerate(self.ddirs):
            if rva or sz:
                s = self.section_of_rva(rva) if rva else None
                out.append("  %-12s RVA=%08X VA=%016X size=%X  sec=%s" %
                           (ddnames[i], rva, rva + self.image_base, sz, s.name if s else '-'))
        if self.nsyms and self.symptr:
            out.append("")
            out.append("COFF SYMBOL TABLE: off=%X count=%d (=%d bytes) -> %s" %
                       (self.symptr, self.nsyms, self.nsyms*18, "PRESENT" if self.symptr < len(self.b) else "OUT OF FILE"))
            if self.symptr + self.nsyms*18 <= len(self.b):
                nstr = u32(self.b, self.symptr + self.nsyms*18)
                out.append("  string table size = %d" % nstr)
        return "\n".join(out)

def ts_str(t):
    import datetime
    try:
        return datetime.datetime.utcfromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S UTC')
    except Exception:
        return "?"

if __name__ == '__main__':
    for p in sys.argv[1:]:
        pe = PE(p)
        print(pe.dump_layout())
