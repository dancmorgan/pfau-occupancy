"""Data models for pfau_occupancy."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

_BRAND_PREFIX = re.compile(r"^planet\s+fitness\s+", re.IGNORECASE)

# Keys this library used under the previous member portal for clubs whose
# name has since changed. Entity unique_ids are built from the key, so a club
# keeps its old key here rather than appearing as a new club.
_LEGACY_KEYS = {
    "auburn": "sydney_auburn",
    "casula": "sydney_casula",
}


def slugify_club(name: str) -> str:
    """Produce a stable, filesystem/entity-safe key from a club name.

    Used to build entity unique_ids. The portal exposes a numeric studio ID,
    but the (slugified) name is what existing installs' unique_ids were built
    from, so it stays the identity. Two different clubs must not collide
    here, so we keep it close to the original: lowercased, accents stripped,
    non-alphanumerics collapsed to underscores.
    """
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")
    return slug or "club"


def club_display_name(name: str) -> str:
    """The studio's name without the brand prefix.

    The portal lists some studios as "Planet Fitness Hornsby" and others as
    just "Morayfield". Dropping the prefix makes both read the same, and
    matches the names the previous portal used.
    """
    stripped = _BRAND_PREFIX.sub("", " ".join(name.split()))
    return stripped or name.strip()


def format_address(address: dict[str, Any] | None) -> str | None:
    """Join a studio's address fields into one line, skipping missing parts."""
    if not address:
        return None
    street = " ".join(
        str(part) for part in (address.get("houseNumber"), address.get("street")) if part
    )
    locality = " ".join(
        str(part)
        for part in (
            address.get("city"),
            address.get("provinceCode"),
            address.get("zipCode") or address.get("zip"),
        )
        if part
    )
    return ", ".join(part for part in (street, locality) if part) or None


@dataclass(frozen=True)
class Club:
    """A single club's occupancy snapshot."""

    name: str
    address: str | None
    occupancy: int | None
    limit: int | None
    # The portal's numeric studio ID, and the club's IANA timezone.
    studio_id: int | None = None
    timezone: str | None = None

    @property
    def key(self) -> str:
        """Stable identity for this club (used for the entity unique_id)."""
        slug = slugify_club(self.name)
        return _LEGACY_KEYS.get(slug, slug)

    @property
    def percent_full(self) -> float | None:
        """Occupancy as a percentage of the club's stated limit, if known."""
        if not self.limit or self.occupancy is None:
            return None
        return round(self.occupancy / self.limit * 100, 1)


def _reading(club: Club) -> int:
    return -1 if club.occupancy is None else club.occupancy


def one_club_per_key(clubs: Iterable[Club]) -> list[Club]:
    """Collapse clubs that share a key into the one that is reporting.

    Franchises are moving onto the new portal one at a time, and a studio not
    yet moved can be listed beside the live one under the same name, always
    reading 0. Entities are keyed by name, so both cannot stay. The higher
    count wins: a count beats 0, and 0 beats no reading. On a tie the club
    listed first is kept, so the choice is stable from poll to poll.
    """
    best: dict[str, Club] = {}
    for club in clubs:
        current = best.get(club.key)
        if current is None or _reading(club) > _reading(current):
            best[club.key] = club
    return list(best.values())


@dataclass(frozen=True)
class Studio:
    """A studio as listed by the portal's public studio endpoint."""

    studio_id: int
    name: str
    address: str | None
    timezone: str | None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Studio":
        return cls(
            studio_id=int(raw["magiclineId"]),
            name=club_display_name(raw["name"]),
            address=format_address(raw.get("address")),
            timezone=raw.get("zoneId"),
        )

    def to_club(self, occupancy: int | None) -> Club:
        return Club(
            name=self.name,
            address=self.address,
            occupancy=occupancy,
            limit=None,
            studio_id=self.studio_id,
            timezone=self.timezone,
        )
