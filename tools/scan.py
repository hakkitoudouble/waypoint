"""Scan the image for 8-byte / 4-byte pointers into a target VA range (pointer-table hunt)."""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import PE

def find_ptr_refs(pe, lo, hi, align=1):
    """Return list of (file_off, value) where an 8-byte LE at off is in [lo,hi)."""
    b = pe.b
    out = []
    # iterate over sections' raw data
    for s in pe.sections:
        o = s.rawptr
        end = s.rawptr + s.rawsize - 8
        while o <= end:
            v = struct.unpack_from('<Q', b, o)[0]
            if lo <= v < hi:
                out.append((o, v))
            o += 1
    return out

def find_ref32(pe, lo, hi):
    b = pe.b
    out = []
    for s in pe.sections:
        o = s.rawptr
        end = s.rawptr + s.rawsize - 4
        while o <= end:
            v = struct.unpack_from('<I', b, o)[0]
            if lo <= v < hi:
                out.append((o, v))
            o += 1
    return out

if __name__ == '__main__':
    pe = PE(sys.argv[1])
    lo = int(sys.argv[2], 0); hi = int(sys.argv[3], 0)
    mode = sys.argv[4] if len(sys.argv) > 4 else 'q'
    refs = find_ptr_refs(pe, lo, hi) if mode == 'q' else find_ref32(pe, lo, hi)
    print("%d refs into [%X,%X)" % (len(refs), lo, hi))
    for off, v in refs[:4000]:
        sec = pe.section_of_off(off)
        print("  file=%08X va=%016X sec=%-8s val=%016X -> file %08X" %
              (off, pe.off_to_va(off), sec.name, v, pe.va_to_off(v) if mode=='q' else 0))
