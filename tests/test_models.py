"""Names, keys and addresses."""
from __future__ import annotations

import pytest

from pfau_occupancy import Club, Studio, slugify_club
from pfau_occupancy.models import club_display_name, format_address, one_club_per_key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Planet Fitness Hornsby", "Hornsby"),
        ("planet  fitness   Hornsby", "Hornsby"),
        ("Morayfield", "Morayfield"),
        ("Planet Fitness", "Planet Fitness"),
        ("  Lake Haven ", "Lake Haven"),
    ],
)
def test_display_name_drops_the_brand_prefix(raw: str, expected: str) -> None:
    assert club_display_name(raw) == expected


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Hornsby", "hornsby"),
        ("Lake Haven", "lake_haven"),
        ("Hervey Bay", "hervey_bay"),
        ("Café Röd", "cafe_rod"),
        ("!!!", "club"),
    ],
)
def test_slug(name: str, key: str) -> None:
    assert slugify_club(name) == key


@pytest.mark.parametrize(
    ("name", "key"),
    [("Auburn", "sydney_auburn"), ("Casula", "sydney_casula"), ("Hornsby", "hornsby")],
)
def test_renamed_clubs_keep_their_old_key(name: str, key: str) -> None:
    assert Club(name, None, 1, None).key == key


def test_percent_full() -> None:
    assert Club("A", None, 25, 200).percent_full == 12.5
    assert Club("A", None, None, 200).percent_full is None
    assert Club("A", None, 25, None).percent_full is None
    assert Club("A", None, 25, 0).percent_full is None


def test_address_is_one_line() -> None:
    address = {
        "houseNumber": "236",
        "street": "Pacific Highway",
        "city": "Hornsby",
        "provinceCode": "NSW",
        "zipCode": "2077",
    }
    assert format_address(address) == "236 Pacific Highway, Hornsby NSW 2077"


def test_address_skips_missing_parts() -> None:
    assert format_address({"city": "Hornsby", "zip": "2077"}) == "Hornsby 2077"
    assert format_address({}) is None
    assert format_address(None) is None


class TestOneClubPerKey:
    def test_a_count_beats_a_placeholder_zero(self) -> None:
        placeholder = Club("Hornsby", None, 0, None, studio_id=1)
        live = Club("Hornsby", None, 32, None, studio_id=2)

        assert one_club_per_key([placeholder, live]) == [live]
        assert one_club_per_key([live, placeholder]) == [live]

    def test_zero_beats_no_reading(self) -> None:
        unknown = Club("Hornsby", None, None, None, studio_id=1)
        zero = Club("Hornsby", None, 0, None, studio_id=2)

        assert one_club_per_key([unknown, zero]) == [zero]
        assert one_club_per_key([zero, unknown]) == [zero]

    def test_a_tie_keeps_the_one_listed_first(self) -> None:
        first = Club("Hornsby", None, 0, None, studio_id=1)
        second = Club("Hornsby", None, 0, None, studio_id=2)

        assert one_club_per_key([first, second]) == [first]
        assert one_club_per_key([second, first]) == [second]

    def test_clubs_with_different_names_are_all_kept_in_order(self) -> None:
        clubs = [Club("B", None, 0, None), Club("A", None, 5, None)]

        assert one_club_per_key(clubs) == clubs

    def test_a_legacy_name_and_its_new_name_are_the_same_club(self) -> None:
        old = Club("Sydney Auburn", None, 0, None, studio_id=1)
        new = Club("Auburn", None, 12, None, studio_id=2)

        assert one_club_per_key([old, new]) == [new]

    def test_the_winner_keeps_its_place_in_the_list(self) -> None:
        before = Club("A", None, 1, None)
        placeholder = Club("B", None, 0, None, studio_id=1)
        after = Club("C", None, 1, None)
        live = Club("B", None, 9, None, studio_id=2)

        assert one_club_per_key([before, placeholder, after, live]) == [
            before,
            live,
            after,
        ]


def test_studio_becomes_a_club() -> None:
    studio = Studio.from_api(
        {
            "magiclineId": "1225884540",
            "name": "Planet Fitness Hornsby",
            "zoneId": "Australia/Sydney",
            "address": {"city": "Hornsby"},
        }
    )

    club = studio.to_club(32)

    assert studio.studio_id == 1225884540
    assert club.name == "Hornsby"
    assert club.occupancy == 32
    assert club.limit is None
    assert club.studio_id == 1225884540
    assert club.timezone == "Australia/Sydney"
    assert club.key == "hornsby"
