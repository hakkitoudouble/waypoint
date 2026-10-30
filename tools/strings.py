"""Extract ASCII (>=4) and UTF-16LE (>=4) runs; annotate with file offset + VA."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import PE

def runs(data, minlen, wide=False):
    out = []
    if wide:
        i = 0; n = len(data)
        while i + 1 < n:
            j = i
            chars = []
            while j + 1 < n:
                lo, hi = data[j], data[j+1]
                if hi == 0 and 32 <= lo < 127:
                    chars.append(lo); j += 2
                else:
                    break
            if len(chars) >= minlen:
                out.append((i, bytes(chars).decode('ascii')))
            i = j + 2 if chars else i + 1
    else:
        i = 0; n = len(data)
        while i < n:
            j = i; chars = []
            while j < n and 32 <= data[j] < 127:
                chars.append(data[j]); j += 1
            if len(chars) >= minlen:
                out.append((i, bytes(chars).decode('ascii')))
            i = j + 1 if chars else i + 1
    return out

def main(path, out_txt, out_json):
    pe = PE(path)
    b = pe.b
    a = runs(b, 4, False)
    w = runs(b, 4, True)
    alls = sorted(a + w)
    lines = []
    lines.append("### ASCII runs >=4 : %d" % len(a))
    lines.append("### UTF-16LE runs >=4 : %d" % len(w))
    lines.append("### format: off<dec>  va<hex or ->  sec  enc  text")
    for off, s in alls:
        sec = pe.section_of_off(off)
        va = pe.off_to_va(off)
        enc = 'W' if any(off == wo for wo, _ in w if wo == off) else 'A'
        lines.append("%08X  %s  %-8s %s  %s" % (off, ("%016X" % va) if va else "-", sec.name if sec else "?", enc, s))
    open(out_txt, 'w', encoding='utf-8', errors='replace').write("\n".join(lines) + "\n")
    # plain sorted-unique dump for grepping
    uniq = sorted(set(s for _, s in alls))
    json.dump(uniq, open(out_json, 'w', encoding='utf-8'), indent=0)
    print("ascii=%d utf16=%d total=%d unique=%d" % (len(a), len(w), len(alls), len(uniq)))

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])
