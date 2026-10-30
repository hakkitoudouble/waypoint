"""Fur variant per animal, recomputed from the save.

The save does not store a fur: `FeatureModifiers` is 0 for all 28 243 animals across the
reference saves, and a live entity exposes neither the population seed nor a variant hash.
What the save does store is a per-animal `VisualVariationSeed`.

The vendor scanner derives the fur from that seed, and its draw logic was recovered by
disassembly (`AnimalPopulationScanner.exe`, function 0x1400568A0):

    state = (seed * 0x343FD + 0x269EC3) mod 2^32      ; the MSVC rand() LCG
    u     = ((state >> 16) & 0x7FFF) / 32768.0
    roll  = trunc(u * totalWeight)
    walk the species'/gender's entries accumulating weights; the first entry whose
    cumulative weight exceeds `roll` wins

The per-species, per-gender weight tables come from the same binary (array at
VA 0x1400CF170, 254 blocks) and are imported by `tools/import_fur_tables.py`.

The draw is made against the animal's **gender code** (1 = male, 2 = female), which is
why a species can have two different tables and why a variant's probability is
per-gender rather than per-species.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
TABLE_FILE = DATA / "fur_tables.json"

#: constants of the draw, straight out of the disassembly
LCG_MUL = 0x000343FD
LCG_ADD = 0x00269EC3
LCG_MASK = 0xFFFFFFFF

#: rarity bands as fractions of the block's total weight. The two lower boundaries are
#: the scanner's own (`p < 0.001` -> class 2 "very rare", `p < 0.01` -> class 1 "rare");
#: the finer buckets around them only split what the scanner lumps together.
RARITY_BANDS = (
    (0.0002, "super_rare"),
    (0.0010, "very_rare"),
    (0.0100, "rare"),
    (0.0500, "uncommon"),
    (1.0001, "common"),
)

GREAT_ONE_HINTS = ("great one", "great_one", "fabled")


@lru_cache(maxsize=1)
def tables() -> dict[str, dict]:
    if not TABLE_FILE.is_file():
        return {}
    try:
        payload = json.loads(TABLE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    species_table = payload.get("species")
    return species_table if isinstance(species_table, dict) else {}


def available() -> bool:
    return bool(tables())


def coverage() -> dict[str, int]:
    table = tables()
    return {
        "species": len(table),
        "entries": sum(len(block.get("entries", []))
                       for blocks in table.values() for block in blocks.values()),
    }


def uniform(seed: int) -> float:
    """The scanner's u01 for one seed (kept for reference and for tests)."""
    return _mantissa(seed) / 32768.0


def _mantissa(seed: int) -> int:
    """The 15 bits the draw actually uses."""
    state = (int(seed) * LCG_MUL + LCG_ADD) & LCG_MASK
    return (state >> 16) & 0x7FFF


def roll_for(seed: int, total: int) -> int:
    """`trunc(u * total)` in exact integer form: (m * total) >> 15.

    The binary computes it in floating point (`mulss` + `cvttss2si`), which is
    bit-identical to this integer form because m is an exact 15-bit integer and 2^15
    divides evenly. The integer form is used so the result cannot drift with the
    platform's float rounding.
    """
    return (_mantissa(seed) * int(total)) >> 15


def draw(species_name: str | None, gender_code: int | None, seed: int | None
         ) -> tuple[str, int, int] | None:
    """(variant, weight, total) for one animal, or None when it cannot be drawn."""
    if not species_name or not isinstance(seed, int) or gender_code not in (1, 2):
        return None
    blocks = tables().get(species_name)
    if not blocks:
        return None
    block = blocks.get(str(gender_code))
    if not block:
        return None
    total = int(block.get("total") or 0)
    if total <= 0:
        return None
    roll = roll_for(seed, total)
    cumulative = 0
    for name, weight in block.get("entries", []):
        weight = int(weight)
        if weight == 0:
            break
        cumulative += weight
        if roll < cumulative:
            return str(name), weight, total
    return None


def rarity_bucket(variant: str, weight: int, total: int) -> str:
    lowered = variant.lower()
    if any(hint in lowered for hint in GREAT_ONE_HINTS):
        return "great_one"
    probability = weight / total if total else 1.0
    for cut, label in RARITY_BANDS:
        if probability <= cut:
            return label
    return "common"


def describe(species_name: str | None, seed: int | None,
             gender_code: int | None = None) -> tuple[str | None, str | None]:
    """(variant, rarity) for one animal."""
    result = draw(species_name, gender_code, seed)
    if result is None:
        return None, None
    variant, weight, total = result
    return variant, rarity_bucket(variant, weight, total)
