"""Data-structure dumping helpers: read at VA (handles zero-fill tails), follow pointers,
dump arrays of fixed-stride records, and resolve pointers to C strings."""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import PE

class Mem:
    def __init__(self, pe):
        self.pe = pe
        self.b = pe.b
    def read(self, va, n):
        """Return bytes at VA; pad with zeros for zero-filled virtual tail / unmapped."""
        rva = va - self.pe.image_base
        s = self.pe.section_of_rva(rva)
        if s is None:
            return b'\0' * n
        delta = rva - s.vaddr
        if delta < s.rawsize:
            avail = min(n, s.rawsize - delta)
            data = self.b[s.rawptr + delta: s.rawptr + delta + avail]
            return data + b'\0' * (n - len(data))
        return b'\0' * n   # virtual tail
    def u32(self, va): return struct.unpack('<I', self.read(va, 4))[0]
    def i32(self, va): return struct.unpack('<i', self.read(va, 4))[0]
    def u64(self, va): return struct.unpack('<Q', self.read(va, 8))[0]
    def f32(self, va): return struct.unpack('<f', self.read(va, 4))[0]
    def cstr(self, va, maxn=512):
        d = self.read(va, maxn)
        z = d.find(b'\0')
        if z >= 0: d = d[:z]
        try:
            return d.decode('utf-8')
        except UnicodeDecodeError:
            return d.decode('latin-1')
    def is_ascii_ptr(self, va):
        if va < self.pe.image_base or va > self.pe.image_base + self.pe.size_of_image:
            return False
        d = self.read(va, 8)
        return len(d) >= 4 and all(32 <= c < 127 for c in d[:4])
