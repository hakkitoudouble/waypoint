"""Hexdump a byte range of a binary file, with printable/UTF-8 rendering."""
import sys

def main():
    path, start, end = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    with open(path, "rb") as f:
        data = f.read()
    chunk = data[start:end]
    # render as decoded latin-1-ish with dots for non printable, 16 bytes/row
    for i in range(0, len(chunk), 16):
        row = chunk[i:i+16]
        hexpart = " ".join(f"{b:02x}" for b in row)
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        print(f"{start+i:08x}  {hexpart:<47}  {txt}")
    print("\n--- utf-8 decode of whole range (errors=replace) ---")
    print(chunk.decode("utf-8", errors="replace"))

if __name__ == "__main__":
    main()
