"""Species tables: NameHashId resolution, per-species stats, and medal prediction.

Three data files feed this module, all under ``cotw/data``:

* ``species_hashes.json``  ``{"08CBEB4A": "Wild Boar", ...}`` — recovered from the
  vendor binary (135 entries). The hash function itself was never cracked, so this
  table is the authoritative mapping; a species legitimately owns several hashes
  (one per asset variant), which is why lookups are by hash and not by name.
* ``species_stats.json``   extracted per-species records (icon path, difficulty
  ceiling, weight series). Optional; absent fields degrade gracefully.
* ``medal_thresholds.json`` trophy-rating cut-offs per species. Optional: when a
  species is missing, medals come back as ``Medal.NONE`` rather than guessed.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .model import Animal, FurRarity, Gender, Medal

DATA = Path(__file__).resolve().parent / "data"


def _load(name: str) -> dict:
    path = DATA / name
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


@lru_cache(maxsize=1)
def hash_table() -> dict[int, str]:
    """NameHashId -> species name, with the metadata key filtered out."""
    raw = _load("species_hashes.json")
    table: dict[int, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            continue
        try:
            table[int(key, 16)] = value
        except ValueError:
            continue
    return table


@lru_cache(maxsize=1)
def stats_table() -> dict[str, dict]:
    raw = _load("species_stats.json")
    out: dict[str, dict] = {}
    entries = raw.get("species", raw) if isinstance(raw, dict) else {}
    if isinstance(entries, dict):
        for key, value in entries.items():
            if isinstance(value, dict):
                out[key] = value
    elif isinstance(entries, list):
        for value in entries:
            if isinstance(value, dict):
                name = value.get("name")
                if isinstance(name, str):
                    out[name] = value
    return out


@lru_cache(maxsize=1)
def thresholds() -> dict[str, dict]:
    raw = _load("medal_thresholds.json")
    return {k: v for k, v in raw.items() if isinstance(v, dict) and not k.startswith("_")}


@lru_cache(maxsize=1)
def _fur_catalogue() -> dict[str, dict]:
    raw = _load("fur_catalogue.json")
    species_table = raw.get("species") if isinstance(raw, dict) else None
    return species_table if isinstance(species_table, dict) else {}


def fur_variants(species_name: str) -> list[dict]:
    """Every fur variant of a species, rarest first, with its drop probability."""
    entry = _fur_catalogue().get(species_name) or {}
    variants = entry.get("variants") or []
    return sorted(
        (v for v in variants if isinstance(v, dict)),
        key=lambda v: v.get("probability", 1.0),
    )


def fur_rarity(species_name: str, variant: str | None) -> str | None:
    """Rarity bucket for one variant name ('rare', 'very_rare', ...)."""
    if not variant:
        return None
    wanted = variant.strip().lower().replace(" ", "_")
    for entry in fur_variants(species_name):
        if str(entry.get("name", "")).lower().replace(" ", "_") == wanted:
            return entry.get("rarity")
    return None


def name_for_hash(hash_id: int | None) -> str | None:
    if hash_id is None:
        return None
    return hash_table().get(hash_id & 0xFFFFFFFF)


def difficulty(species: str) -> int | None:
    entry = stats_table().get(species)
    if not entry:
        return None
    value = entry.get("maxDifficulty") or entry.get("max_difficulty")
    return int(value) if isinstance(value, (int, float)) else None


@lru_cache(maxsize=1)
def _icon_map() -> dict[str, str]:
    raw = _load("species_icons.json")
    icons = raw.get("icons") if isinstance(raw, dict) else None
    if not isinstance(icons, dict):
        return {}
    return {k: v for k, v in icons.items() if isinstance(v, str)}


def icon_for(species: str) -> str:
    """Real icon filename for a species, e.g. 'Kangaroo_frame.png'.

    Returned with its extension on purpose: the frontend passes anything that looks
    like a filename straight through, so the API decides which asset to use instead
    of the UI guessing from the species name (which broke on 'EG Kangaroo').
    """
    mapped = _icon_map().get(species)
    if mapped:
        return mapped
    return "".join(ch for ch in species.lower() if ch.isalnum()) + "_frame.png"


def medal_for(species: str | None, score: float | None) -> Medal:
    """Highest medal the trophy rating reaches, or NONE when undeterminable.

    No source publishes a Bronze cut-off — the vendor binary's record only carries
    three floats at +0x1C (silver, gold, diamond) and the community charts stop at
    silver too. An animal with a trophy score but below silver therefore still
    earns *a* medal in game, so we treat "has a score at all" as the Bronze floor.
    Trophy-less animals (females without antlers, unspawned slots) have score 0 and
    correctly get NONE.
    """
    if not species or score is None:
        return Medal.NONE
    entry = thresholds().get(species)
    if not entry:
        return Medal.NONE

    for medal, key in (
        (Medal.GREAT_ONE, "great_one"),
        (Medal.DIAMOND, "diamond"),
        (Medal.GOLD, "gold"),
        (Medal.SILVER, "silver"),
    ):
        cut = entry.get(key)
        if isinstance(cut, (int, float)) and score >= cut:
            return medal

    bronze = entry.get("bronze")
    if isinstance(bronze, (int, float)):
        return Medal.BRONZE if score >= bronze else Medal.NONE
    return Medal.BRONZE if score > 0 else Medal.NONE


def trophy_rating(species: str | None, score: float | None) -> float | None:
    """Normalise ``score`` in 0..1 against the species' diamond threshold."""
    if not species or score is None:
        return None
    entry = thresholds().get(species)
    if not entry:
        return None
    diamond = entry.get("diamond")
    if not isinstance(diamond, (int, float)) or diamond <= 0:
        return None
    return max(0.0, min(1.5, score / diamond))


def gender_from_raw(value: Any) -> Gender:
    """Map the save's 1-based gender code.

    Codes 1/2 are what actually occur in the files. Which is which was settled
    statistically rather than guessed: across every dimorphic species the code-1
    animals are the heavier ones (Red Deer 199.8 vs 146.3 kg, Moose 511.8 vs
    380.2 kg, Whitetail 79.4 vs 49.6 kg, Sambar 274.4 vs 204.4 kg), and in those
    species the male is the heavier sex. So 1 = male, 2 = female.
    """
    if value == 1:
        return Gender.MALE
    if value == 2:
        return Gender.FEMALE
    return Gender.UNKNOWN


def build_animal(raw: dict[str, Any], group_index: int | None = None,
                 spawn_area: int | None = None) -> Animal:
    """Turn a raw parser record into a domain Animal."""
    species = raw.get("species") or name_for_hash(raw.get("species_hash"))
    score = raw.get("score")
    score = float(score) if isinstance(score, (int, float)) else None
    weight = raw.get("weight")
    weight = float(weight) if isinstance(weight, (int, float)) else None

    animal_id = raw.get("id")
    if isinstance(animal_id, int):
        animal_id = f"{animal_id & 0xFFFFFFFFFFFFFFFF:016X}"
    elif animal_id is None:
        animal_id = "?"

    has_thresholds = bool(species and species in thresholds())
    # The fur is a function of the visual variation seed; `cotw.furs` owns that model
    # and returns (None, None) until the draw logic is known, so nothing is invented.
    from . import furs as fur_module

    fur_name, fur_rarity = fur_module.describe(species, raw.get("seed"), raw.get("gender"))
    return Animal(
        id=str(animal_id),
        species=species or "Unknown",
        gender=gender_from_raw(raw.get("gender")),
        weight=weight,
        score=score,
        trophy_rating=trophy_rating(species, score),
        medal=medal_for(species, score),
        medal_source="game" if has_thresholds else "none",
        fur=fur_name if fur_name else raw.get("fur"),
        fur_rarity=(FurRarity(fur_rarity) if fur_rarity in FurRarity._value2member_map_
                    else (raw.get("fur_rarity") if isinstance(raw.get("fur_rarity"), FurRarity) else None)),
        is_scripted=bool(raw.get("is_scripted")),
        seed=raw.get("seed") if isinstance(raw.get("seed"), int) else None,
        x=raw.get("x") if isinstance(raw.get("x"), (int, float)) else None,
        y=raw.get("y") if isinstance(raw.get("y"), (int, float)) else None,
        group=group_index if group_index is not None else raw.get("group"),
        spawn_area=spawn_area if spawn_area is not None else raw.get("spawn_area"),
    )


def coverage() -> dict[str, int]:
    """Small diagnostic used by the verification script."""
    table = hash_table()
    names = set(table.values())
    return {
        "hashes": len(table),
        "distinct_species": len(names),
        "with_stats": sum(1 for n in names if n in stats_table()),
        "with_thresholds": sum(1 for n in names if n in thresholds()),
    }
