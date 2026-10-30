"""Domain model for a scanned reserve population, plus the JSON contract the UI consumes.

The contract is deliberately explicit and versioned (`schema: 1`) so the web
frontend can be developed and tested against fixtures before the ADF parser
exists, and so a future schema change is a visible, deliberate act.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

SCHEMA_VERSION = 1


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"

    @classmethod
    def from_raw(cls, value: Any) -> "Gender":
        """Best-effort mapping of the game's raw gender value."""
        if value == 0:
            return cls.MALE
        if value == 1:
            return cls.FEMALE
        if isinstance(value, str):
            lowered = value.strip().lower()
            for member in cls:
                if lowered == member.value:
                    return member
        return cls.UNKNOWN


class Medal(str, Enum):
    """Trophy tier, most prestigious first."""

    GREAT_ONE = "great_one"
    DIAMOND = "diamond"
    GOLD = "gold"
    SILVER = "silver"
    BRONZE = "bronze"
    NONE = "none"

    @property
    def rank(self) -> int:
        """Sort key: 6 for great_one down to 1 for none (higher == rarer)."""
        return len(_MEDAL_ORDER) - _MEDAL_ORDER.index(self)


#: Ordered most prestigious first; `rank` inverts the index so that a plain
#: descending sort puts great ones first.
_MEDAL_ORDER: tuple[Medal, ...] = (
    Medal.GREAT_ONE,
    Medal.DIAMOND,
    Medal.GOLD,
    Medal.SILVER,
    Medal.BRONZE,
    Medal.NONE,
)


class FurRarity(str, Enum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    VERY_RARE = "very_rare"
    SUPER_RARE = "super_rare"
    GREAT_ONE = "great_one"


@dataclass(frozen=True)
class WorldBounds:
    """World-space rectangle that the reserve map image depicts."""

    min_x: float
    max_x: float
    min_y: float
    max_y: float

    def as_dict(self) -> dict[str, float]:
        return {
            "min_x": self.min_x,
            "max_x": self.max_x,
            "min_y": self.min_y,
            "max_y": self.max_y,
        }


@dataclass
class Animal:
    """One animal present in a reserve population file."""

    id: str
    species: str
    gender: Gender = Gender.UNKNOWN
    weight: float | None = None
    score: float | None = None
    trophy_rating: float | None = None
    medal: Medal = Medal.NONE
    fur: str | None = None
    fur_rarity: FurRarity | None = None
    is_scripted: bool = False
    #: The save's `VisualVariationSeed`. Not shown in the UI, but it is the only
    #: per-animal value the game writes that is unique in practice (the `id` field is 0
    #: for every animal), so it is what lets a watcher tell a new spawn from an old one.
    seed: int | None = None
    x: float | None = None
    y: float | None = None
    group: int | None = None
    spawn_area: int | None = None
    #: Where the medal came from. "game" = the real per-species trophy-rating
    #: thresholds; "relative" = a percentile computed inside this reserve, used
    #: only as a fallback when the game thresholds are unknown; "none" = no basis.
    medal_source: str = "none"

    @property
    def has_position(self) -> bool:
        return self.x is not None and self.y is not None

    def as_dict(self) -> dict[str, Any]:
        """Serialise exactly as the frontend contract expects."""
        return {
            "id": self.id,
            "species": self.species,
            "gender": self.gender.value,
            "weight": self.weight,
            "score": self.score,
            "trophy_rating": self.trophy_rating,
            "medal": self.medal.value,
            "medal_source": self.medal_source,
            "fur": self.fur,
            "fur_rarity": self.fur_rarity.value if self.fur_rarity else None,
            "is_scripted": self.is_scripted,
            "seed": self.seed,
            "x": self.x,
            "y": self.y,
            "group": self.group,
            "spawn_area": self.spawn_area,
        }


@dataclass
class Population:
    """A whole reserve population, ready to serialise for the UI."""

    reserve_index: int
    reserve_name: str
    map_image: str
    world: WorldBounds
    animals: list[Animal] = field(default_factory=list)
    source_file: str | None = None
    generated_at: datetime | None = None

    def species_summary(self) -> list[dict[str, Any]]:
        """Per-species counts, alphabetical, with great-one capability flagged later."""
        counts: dict[str, int] = {}
        for animal in self.animals:
            counts[animal.species] = counts.get(animal.species, 0) + 1
        return [
            {"name": name, "icon": _icon_for(name), "count": counts[name]}
            for name in sorted(counts)
        ]

    def medal_counts(self) -> dict[str, int]:
        counts = {medal.value: 0 for medal in Medal}
        for animal in self.animals:
            counts[animal.medal.value] += 1
        return counts

    def as_contract(self) -> dict[str, Any]:
        """The full JSON document served at /api/population."""
        stamp = self.generated_at or datetime.now(timezone.utc)
        return {
            "schema": SCHEMA_VERSION,
            "generated_at": stamp.isoformat(),
            "reserve": {
                "index": self.reserve_index,
                "name": self.reserve_name,
                "map_image": self.map_image,
                # alias: the frontend's normaliser reads `map`
                "map": self.map_image,
            },
            "world": self.world.as_dict(),
            "species": self.species_summary(),
            "animals": [a.as_dict() for a in self.animals],
            "source": self.source_file,
            "summary": {
                "total": len(self.animals),
                "medals": self.medal_counts(),
            },
        }


def _icon_for(species_name: str) -> str:
    """Resolve the icon asset through the recovered species table.

    Imported lazily: ``cotw.species`` imports this module, so a module-level import
    would be circular.
    """
    try:
        from . import species as species_tables

        return species_tables.icon_for(species_name)
    except Exception:  # noqa: BLE001 - never break serialisation over a thumbnail
        return "".join(ch for ch in species_name.lower() if ch.isalnum()) + "_frame.png"


def _icon_slug(species_name: str) -> str:
    """Legacy slug helper, kept for callers that want a bare slug."""
    return "".join(ch for ch in species_name.lower() if ch.isalnum())


def sort_animals(animals: Iterable[Animal]) -> list[Animal]:
    """Default display order: rarest first, then heaviest."""
    return sorted(
        animals,
        key=lambda a: (a.medal.rank, a.trophy_rating or 0.0, a.weight or 0.0),
        reverse=True,
    )
