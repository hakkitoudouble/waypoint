"""Copy every species icon and resolve species name -> real icon filename.

Why this exists: the frontend builds an icon path from a slug
(`assets/icons/<Capitalised>_frame.png`), which works for "Red Deer" but not for
"EG Kangaroo" (the real file is `Kangaroo_frame.png`) or "Coll. Peccary"
(`Peccary_frame.png`). Rather than teach the UI about every abbreviation, the API
now ships the *actual* filename and the UI passes it through unchanged.

Writes cotw/data/species_icons.json and copies the PNGs into web/assets/icons.
Run:  python tools/build_icons.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "cotw" / "data"
OUT_ICONS = ROOT / "web" / "assets" / "icons"

SOURCE = Path(
    r"C:\Users\Maelo\Downloads\Animal Population Scanner 41 1.2.15.1 2026-06-28T14-37Z aIEulX545"
    r"\AnimalPopulationScanner\data\Icons"
)

#: abbreviations the game uses in asset names that the icon files drop
PREFIXES = ("coll", "eg", "sw", "eur", "eu", "ew", "ec", "w", "e", "m", "s", "g")

#: Hand-checked pairs the fuzzy matcher cannot get: abbreviations and spelling
#: variants ("mufflon" vs "Mouflon", "SES" vs "Southeastern"). Keyed by the
#: normalised species name. A ``None`` means "no icon asset exists".
OVERRIDES: dict[str, str | None] = {
    "cinteal": "Cinnamonteal_frame.png",
    "hduck": "Harlequinduck_frame.png",
    "sesibex": "Southeasternibex_frame.png",
    "tbeangoose": "TundraBeanGoose_frame.png",
    "iberianmouflon": "Iberianmufflon_frame.png",
    "vicua": "Vicuna_frame.png",
    "rmelk": None,
    "greenwingedteal": None,
    "rockptarmigan": None,
}


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def score(species_norm: str, icon_norm: str) -> int:
    """Higher is better; 0 means no match."""
    if not species_norm or not icon_norm:
        return 0
    if species_norm == icon_norm:
        return 1000
    # try dropping a leading abbreviation ("egkangaroo" -> "kangaroo")
    for prefix in PREFIXES:
        if species_norm.startswith(prefix) and len(species_norm) > len(prefix) + 3:
            trimmed = species_norm[len(prefix):]
            if trimmed == icon_norm:
                return 900
            if trimmed.endswith(icon_norm) or icon_norm.endswith(trimmed):
                return 600 + min(len(trimmed), 40)
    if icon_norm.endswith(species_norm) or species_norm.endswith(icon_norm):
        shorter = min(len(species_norm), len(icon_norm))
        if shorter >= 4:
            return 400 + shorter
    if species_norm in icon_norm or icon_norm in species_norm:
        shorter = min(len(species_norm), len(icon_norm))
        if shorter >= 5:
            return 200 + shorter
    return 0


def main() -> int:
    if not SOURCE.is_dir():
        print(f"FAIL: icon source not found: {SOURCE}")
        return 1
    icons = sorted(p.name for p in SOURCE.glob("*.png"))
    print(f"source icons: {len(icons)}")

    OUT_ICONS.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in icons:
        target = OUT_ICONS / name
        if not target.exists():
            shutil.copy2(SOURCE / name, target)
            copied += 1
    print(f"copied {copied} new icon(s); {len(list(OUT_ICONS.glob('*.png')))} now present")

    species = json.loads((DATA / "species_hashes.json").read_text(encoding="utf-8"))
    # only real hash entries: the file also carries "_"-prefixed metadata keys
    # whose values are long prose notes, not species names
    names = sorted({
        v for k, v in species.items()
        if isinstance(v, str) and re.fullmatch(r"[0-9A-Fa-f]{8}", str(k))
    })
    print(f"species to map: {len(names)}")

    by_norm = {norm(Path(i).stem.replace("_frame", "")): i for i in icons}
    mapping: dict[str, str] = {}
    unmatched: list[str] = []
    for name in names:
        key = norm(name)
        if key in OVERRIDES:
            chosen = OVERRIDES[key]
            if chosen:
                mapping[name] = chosen
            else:
                unmatched.append(name)
            continue
        best, best_name = 0, None
        for icon_norm, icon_file in by_norm.items():
            s = score(key, icon_norm)
            if s > best:
                best, best_name = s, icon_file
        if best_name:
            mapping[name] = best_name
        else:
            unmatched.append(name)

    print(f"mapped {len(mapping)}/{len(names)}")
    if unmatched:
        print(f"unmatched ({len(unmatched)}): {', '.join(unmatched[:14])}")
        placeholder = "Placeholder.png"
        if (OUT_ICONS / placeholder).exists():
            for name in unmatched:
                mapping[name] = placeholder
            print(f"  -> fell back to {placeholder}")

    out = {
        "_meta": {
            "note": "species name -> real icon filename in web/assets/icons/",
            "source": "AnimalPopulationScanner/data/Icons",
            "mapped": len(mapping),
            "fallback": "Placeholder.png",
        },
        "icons": mapping,
    }
    target = DATA / "species_icons.json"
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
