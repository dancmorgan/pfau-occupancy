"""The client against a fake portal."""
from __future__ import annotations

import aiohttp
import pytest

from pfau_occupancy import (
    PlanetFitnessAuthError,
    PlanetFitnessClient,
    PlanetFitnessConnectionError,
)
from pfau_occupancy import client as client_module
from conftest import EMAIL, PASSWORD, studio


class TestLogin:
    async def test_sends_what_the_web_app_sends(self, client, fake) -> None:
        await client.async_login()

        request = fake.last_login_request
        assert request["json"] == {"username": EMAIL, "password": PASSWORD}
        headers = request["headers"]
        assert headers["X-Tenant"] == "planet-fitness-au"
        assert headers["X-Nox-Client-Type"] == "WEB"
        assert headers["X-Nox-Web-Context"] == "v=1"
        assert headers["X-Public-Facility-Group"].startswith("BRANDEDAPP-")
        assert headers["X-Ms-Web-Context"]
        assert headers["Authorization"].startswith("Basic ")

    @pytest.mark.parametrize("status", [400, 401, 403])
    async def test_rejected_credentials(self, client, fake, status: int) -> None:
        fake.login_status = status

        with pytest.raises(PlanetFitnessAuthError):
            await client.async_login()

    async def test_wrong_password(self, portal) -> None:
        _, base_url = portal
        async with PlanetFitnessClient(EMAIL, "wrong", base_url=base_url) as c:
            with pytest.raises(PlanetFitnessAuthError):
                await c.async_login()

    @pytest.mark.parametrize("status", [500, 502, 503])
    async def test_server_errors_are_connection_errors(
        self, client, fake, status: int
    ) -> None:
        fake.login_status = status

        with pytest.raises(PlanetFitnessConnectionError):
            await client.async_login()

    async def test_success_without_a_session_cookie_is_not_logged_in(
        self, client, fake
    ) -> None:
        fake.login_sets_cookie = False

        with pytest.raises(PlanetFitnessAuthError):
            await client.async_login()

    async def test_unreachable_portal(self) -> None:
        async with PlanetFitnessClient(
            EMAIL, PASSWORD, base_url="http://127.0.0.1:1"
        ) as c:
            with pytest.raises(PlanetFitnessConnectionError):
                await c.async_login()


class TestGetClubs:
    async def test_returns_every_studio_with_its_live_count(self, client) -> None:
        clubs = await client.async_get_clubs()

        by_name = {club.name: club for club in clubs}
        assert set(by_name) == {"Hornsby", "Morayfield", "Auburn"}
        assert by_name["Hornsby"].occupancy == 32
        assert by_name["Morayfield"].occupancy == 7
        assert by_name["Hornsby"].address == "1 Test Street, Hornsby NSW 2000"
        assert by_name["Morayfield"].timezone == "Australia/Brisbane"
        assert by_name["Hornsby"].studio_id == 101
        assert by_name["Hornsby"].limit is None

    async def test_logs_in_by_itself(self, client, fake) -> None:
        await client.async_get_clubs()

        assert fake.logins == 1

    async def test_keys_match_the_old_portals(self, client) -> None:
        keys = {club.key for club in await client.async_get_clubs()}

        assert keys == {"hornsby", "morayfield", "sydney_auburn"}

    async def test_data_requests_carry_the_headers_and_session(
        self, client, fake
    ) -> None:
        await client.async_get_clubs()

        headers = fake.last_data_headers
        assert headers["X-Tenant"] == "planet-fitness-au"
        assert headers["X-Public-Facility-Group"].startswith("BRANDEDAPP-")
        assert "SESSION=session-1" in headers["Cookie"]

    async def test_a_new_count_shows_up_on_the_next_poll(self, client, fake) -> None:
        await client.async_get_clubs()
        fake.counts[101] = 90

        clubs = await client.async_get_clubs()

        assert {c.name: c.occupancy for c in clubs}["Hornsby"] == 90
        assert fake.logins == 1

    async def test_requests_are_limited_to_a_few_at_a_time(self, portal) -> None:
        fake, base_url = portal
        fake.delay = 0.05
        async with PlanetFitnessClient(
            EMAIL, PASSWORD, base_url=base_url, max_concurrency=2
        ) as c:
            await c.async_get_clubs()

        assert fake.max_in_flight == 2
        assert sorted(fake.count_requests) == [101, 102, 103]


class TestDuplicateStudios:
    async def test_the_studio_with_a_real_count_is_used(self, client, fake) -> None:
        # A not-yet-migrated placeholder sharing a live studio's name, listed
        # on both sides of it, always reads 0.
        fake.studios.insert(0, studio(104, "Hornsby", "Hornsby"))
        fake.studios.append(studio(105, "Planet Fitness Hornsby", "Hornsby"))
        fake.counts.update({104: 0, 105: 0})

        clubs = await client.async_get_clubs()

        hornsby = [c for c in clubs if c.key == "hornsby"]
        assert len(hornsby) == 1
        assert hornsby[0].occupancy == 32
        assert hornsby[0].studio_id == 101
        assert len(clubs) == 3

    async def test_a_placeholder_that_fails_to_read_does_not_hide_the_live_one(
        self, client, fake
    ) -> None:
        fake.studios.insert(0, studio(104, "Hornsby", "Hornsby"))
        fake.counts[104] = 0
        fake.fail_status[104] = 502

        clubs = await client.async_get_clubs()

        assert {c.key: c.occupancy for c in clubs}["hornsby"] == 32


class TestSessionExpiry:
    async def test_expired_session_is_renewed_transparently(self, client, fake) -> None:
        await client.async_get_clubs()
        fake.expire_sessions()

        clubs = await client.async_get_clubs()

        assert len(clubs) == 3
        assert fake.logins == 2

    async def test_failing_renewal_is_an_auth_error(self, client, fake) -> None:
        await client.async_get_clubs()
        fake.expire_sessions()
        fake.login_status = 401

        with pytest.raises(PlanetFitnessAuthError):
            await client.async_get_clubs()


class TestPartialFailures:
    async def test_one_studio_failing_leaves_the_rest(self, client, fake) -> None:
        fake.fail_status[102] = 502

        clubs = await client.async_get_clubs()

        by_name = {club.name: club.occupancy for club in clubs}
        assert by_name == {"Hornsby": 32, "Morayfield": None, "Auburn": 55}

    async def test_a_malformed_count_leaves_that_studio_unknown(
        self, client, fake
    ) -> None:
        fake.count_body_override[103] = '{"value": "lots"}'

        clubs = await client.async_get_clubs()

        assert {c.name: c.occupancy for c in clubs}["Auburn"] is None

    async def test_every_studio_failing_is_a_connection_error(
        self, client, fake
    ) -> None:
        for studio_id in (101, 102, 103):
            fake.fail_status[studio_id] = 502

        with pytest.raises(PlanetFitnessConnectionError):
            await client.async_get_clubs()

    async def test_a_non_json_count_body_counts_as_a_failure(self, client, fake) -> None:
        for studio_id in (101, 102, 103):
            fake.count_body_override[studio_id] = "<html>maintenance</html>"

        with pytest.raises(PlanetFitnessConnectionError):
            await client.async_get_clubs()


class TestStudioList:
    async def test_is_cached_between_polls(self, client, fake) -> None:
        await client.async_get_clubs()
        await client.async_get_clubs()

        assert fake.studio_list_requests == 1

    async def test_is_refreshed_once_stale(self, client, fake, monkeypatch) -> None:
        await client.async_get_clubs()
        monkeypatch.setattr(client_module, "_STUDIO_CACHE_SECONDS", 0)
        fake.studios.append(studio(104, "Gosford", "Gosford"))
        fake.counts[104] = 3

        clubs = await client.async_get_clubs()

        assert "Gosford" in {c.name for c in clubs}
        assert fake.studio_list_requests == 2

    async def test_old_list_is_used_when_a_refresh_fails(
        self, client, fake, monkeypatch
    ) -> None:
        await client.async_get_clubs()
        monkeypatch.setattr(client_module, "_STUDIO_CACHE_SECONDS", 0)
        fake.studio_list_status = 502

        clubs = await client.async_get_clubs()

        assert len(clubs) == 3

    async def test_failure_with_no_cached_list_is_a_connection_error(
        self, client, fake
    ) -> None:
        fake.studio_list_status = 502

        with pytest.raises(PlanetFitnessConnectionError):
            await client.async_get_clubs()

    async def test_unexpected_shape_with_no_cached_list_is_a_connection_error(
        self, client, fake
    ) -> None:
        fake.studio_list_body = {"unexpected": []}

        with pytest.raises(PlanetFitnessConnectionError):
            await client.async_get_clubs()

    async def test_unexpected_shape_after_a_good_list_keeps_the_old_one(
        self, client, fake, monkeypatch
    ) -> None:
        await client.async_get_clubs()
        monkeypatch.setattr(client_module, "_STUDIO_CACHE_SECONDS", 0)
        fake.studio_list_body = {"unexpected": []}

        clubs = await client.async_get_clubs()

        assert len(clubs) == 3


class TestSharedSession:
    async def test_clients_sharing_a_session_keep_separate_logins(self, portal) -> None:
        fake, base_url = portal
        async with aiohttp.ClientSession() as shared:
            first = PlanetFitnessClient(EMAIL, PASSWORD, shared, base_url)
            second = PlanetFitnessClient(EMAIL, PASSWORD, shared, base_url)

            await first.async_login()
            await second.async_login()
            await first.async_get_clubs()
            first_cookie = fake.last_data_headers["Cookie"]
            await second.async_get_clubs()
            second_cookie = fake.last_data_headers["Cookie"]

        assert "session-1" in first_cookie
        assert "session-2" in second_cookie

    async def test_a_caller_supplied_session_is_not_closed(self, portal) -> None:
        _, base_url = portal
        async with aiohttp.ClientSession() as shared:
            async with PlanetFitnessClient(EMAIL, PASSWORD, shared, base_url) as c:
                await c.async_get_clubs()

            assert not shared.closed
