"""Fur variants: where they live, and what we can actually recover.

Finding, established on the real saves:

* The **population file does not carry fur for living animals.** `AnimalData_5` has
  a `FeatureModifiers` byte at +0x0C, but it is `0` (or absent, for saves written by
  an older game build) for all 28 243 animals across the 16 population files, and the
  32-byte record is fully accounted for by its eight fields — there is no spare byte
  for a variant.
* The **harvest log does carry it.** `hunting_log_adf -> HarvestHistory[]` stores
  ``{SpeciesName, Score, TrophyScore, VariationName, Timestamp, RegionName}`` where
  `VariationName` is the fur variant hash.
* `SpeciesName` in that log uses the *need-zone* animal-type hash space, not the
  `NameHashId` asset space — e.g. 1587180490 (0x5E9A73CA) resolves to Black Bear via
  the constraint-solved zone table, and not via `species_hashes.json`.

The variant hashes below were recovered by matching a harvest entry's `Score` to the
trophy rating the vendor scanner displays for the same animal, which it labels with a
fur name. Provenance is recorded per entry; nothing here is guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import adf, save

DATA = Path(__file__).resolve().parent / "data"
FUR_FILE = DATA / "fur_variants.json"

#: Fallback table if the data file is missing. Each pair was confirmed by matching a
#: harvest `Score` against the scanner's own display (see notes/fur.md).
FALLBACK_FUR: dict[int, str] = {
    0xE6A4B966: "Noire",   # Black Bear, seen at TR 16.70 / 16.83 / 18.06
    0x7573495B: "Sombre",  # Black Bear, TR 17.00
    0x5EF18CE1: "Foncé",   # Black Bear, TR 17.10
}


@dataclass
class Harvest:
    species_hash: int
    species: str | None
    score: float | None
    variation_hash: int
    fur: str | None
    timestamp: int | None

    def as_dict(self) -> dict[str, Any]:
        when = None
        if isinstance(self.timestamp, int) and self.timestamp > 0:
            try:
                when = datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                when = None
        return {
            "species": self.species,
            "species_hash": f"{self.species_hash:08X}",
            "score": self.score,
            "variation_hash": f"{self.variation_hash:08X}",
            "fur": self.fur,
            "timestamp": when,
        }


def _load_furs() -> dict[int, str]:
    if not FUR_FILE.is_file():
        return dict(FALLBACK_FUR)
    try:
        raw = json.loads(FUR_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(FALLBACK_FUR)
    out: dict[int, str] = {}
    for key, value in (raw.get("variants") or {}).items():
        if isinstance(value, dict) and isinstance(value.get("name"), str):
            try:
                out[int(key, 16)] = value["name"]
            except ValueError:
                continue
    return out or dict(FALLBACK_FUR)


def _species_resolver() -> dict[int, str]:
    """Animal-type hash -> species, from the constraint-solved need-zone table."""
    table: dict[int, str] = {}
    zone_file = DATA / "needzone_types.json"
    if zone_file.is_file():
        try:
            raw = json.loads(zone_file.read_text(encoding="utf-8"))
            for key, value in (raw.get("types") or {}).items():
                if isinstance(value, dict) and isinstance(value.get("species"), str):
                    table[int(key, 16)] = value["species"]
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return table


def read_harvests(save_dir: str | Path) -> list[Harvest]:
    """Harvested animals, newest first, with their fur where the hash is known."""
    path = Path(save_dir) / "hunting_log_adf"
    if not path.is_file():
        return []

    doc = adf.parse_document(save.read_container(path).payload)
    root = doc.parse_entry(0)
    furs = _load_furs()
    zone_species = _species_resolver()

    out: list[Harvest] = []
    for entry in root.get("HarvestHistory", []) or []:
        species_hash = int(entry.get("SpeciesName") or 0)
        variation = int(entry.get("VariationName") or 0)
        score = entry.get("Score")
        out.append(
            Harvest(
                species_hash=species_hash,
                species=zone_species.get(species_hash),
                score=float(score) if isinstance(score, (int, float)) else None,
                variation_hash=variation,
                fur=furs.get(variation),
                timestamp=entry.get("Timestamp") if isinstance(entry.get("Timestamp"), int) else None,
            )
        )
    out.sort(key=lambda h: h.timestamp or 0, reverse=True)
    return out
