"""Data models for pfau_occupancy."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def slugify_club(name: str) -> str:
    """Produce a stable, filesystem/entity-safe key from a club name.

    Used to build entity unique_ids. Since the occupancy endpoint exposes no
    club ID, the (slugified) name is the only stable identity we have. Two
    different clubs must not collide here, so we keep it close to the original:
    lowercased, accents stripped, non-alphanumerics collapsed to underscores.
    """
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")
    return slug or "club"


@dataclass(frozen=True)
class Club:
    """A single club's occupancy snapshot."""

    name: str
    address: str | None
    occupancy: int | None
    limit: int | None

    @property
    def key(self) -> str:
        """Stable identity for this club (used for the entity unique_id)."""
        return slugify_club(self.name)

    @property
    def percent_full(self) -> float | None:
        """Occupancy as a percentage of the club's stated limit, if known."""
        if not self.limit or self.occupancy is None:
            return None
        return round(self.occupancy / self.limit * 100, 1)

    @classmethod
    def from_api(cls, raw: dict) -> "Club":
        return cls(
            name=raw["ClubName"],
            address=raw.get("ClubAddress"),
            occupancy=raw.get("UsersCountCurrentlyInClub"),
            limit=raw.get("UsersLimit"),
        )
