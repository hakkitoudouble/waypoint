"""Report map PNG dimensions, and render fog-of-war masks + map thumbnails for visual matching."""
import os
import glob
from PIL import Image

MAPS = r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 2026-06-28T14-37Z aIEulX545\AnimalPopulationScanner\data\Maps"
OUT = r"C:\Users\Maelo\Documents\mods\cotw-pop\work\preview"
FOG = r"C:\Users\Maelo\Documents\mods\cotw-pop\work\save_decompressed"


def main():
    os.makedirs(OUT, exist_ok=True)
    print("== map png dimensions ==")
    for p in sorted(glob.glob(os.path.join(MAPS, "*.png"))):
        im = Image.open(p)
        print(f"{os.path.basename(p):28} {im.size[0]}x{im.size[1]}  mode={im.mode}")
        im.convert("L").resize((256, 256), Image.LANCZOS).save(
            os.path.join(OUT, "thumb_" + os.path.basename(p).replace(" ", "_"))
        )

    print("\n== fog masks (256x256 from decompressed) ==")
    for n in [0, 3, 4, 5, 6, 8, 9, 14, 16]:
        p = os.path.join(FOG, f"adf_fog_of_war_data_faster_{n}.bin")
        d = open(p, "rb").read()
        mask = d[0:65536]
        im = Image.frombytes("L", (256, 256), mask)
        im.save(os.path.join(OUT, f"fog_{n}.png"))
        white = sum(1 for b in mask if b > 128)
        print(f"fog_{n:2d}: nonzero_high={white} ({white/65536:.1%})")


if __name__ == "__main__":
    main()
