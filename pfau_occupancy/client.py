"""Async client for the Planet Fitness AU member portal (Magicline "MySports")."""
from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from typing import Any

import aiohttp

from .exceptions import (
    PlanetFitnessAuthError,
    PlanetFitnessConnectionError,
)
from .models import Club, Studio, one_club_per_key

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://members.planetfitnessaustralia.com.au"

# Identify the brand to the portal. These are configuration the portal's own
# web app sends on every request, not secrets.
DEFAULT_TENANT = "planet-fitness-au"
DEFAULT_FACILITY_GROUP = "BRANDEDAPP-26ED290039B342C98BA951F51312D332"

# The studio list changes only when a club opens or closes, so it is fetched
# rarely and reused if a refresh fails.
_STUDIO_CACHE_SECONDS = 6 * 60 * 60

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)


class PlanetFitnessClient:
    """Talks to the member portal: login, then fetch occupancy per studio.

    The portal's live count is per studio, so one poll is one request for the
    studio list (cached) plus one per studio, run a few at a time.

    The session is a cookie. It is held here rather than in the aiohttp
    session's cookie jar, so two clients that share one aiohttp session (as
    Home Assistant's integrations do) never share a login.

    The caller owns the aiohttp session lifecycle by passing one in (this is
    what Home Assistant wants: it supplies its shared session). If none is
    given, one is created and closed by `async with` / `close()`.
    """

    def __init__(
        self,
        email: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
        base_url: str = DEFAULT_BASE_URL,
        *,
        tenant: str = DEFAULT_TENANT,
        facility_group: str = DEFAULT_FACILITY_GROUP,
        max_concurrency: int = 6,
    ) -> None:
        self._email = email
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._tenant = tenant
        self._facility_group = facility_group
        self._session = session
        self._owns_session = session is None
        self._max_concurrency = max(1, max_concurrency)
        self._cookies: dict[str, str] = {}
        # Per client, like the web app's per-page-load context id.
        self._web_context = base64.b64encode(uuid.uuid4().bytes * 2).decode()
        self._studios: list[Studio] | None = None
        self._studios_fetched_at = 0.0

    async def __aenter__(self) -> "PlanetFitnessClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "X-Nox-Client-Type": "WEB",
            "X-Nox-Web-Context": "v=1",
            "X-Ms-Web-Context": self._web_context,
            "X-Public-Facility-Group": self._facility_group,
            "X-Tenant": self._tenant,
        }

    async def async_login(self) -> None:
        """Authenticate; the session cookie is kept for later requests.

        Raises PlanetFitnessAuthError on bad credentials, PlanetFitnessConnectionError
        on transport problems.
        """
        credentials = base64.b64encode(
            f"{self._email}:{self._password}".encode()
        ).decode()
        headers = {**self._headers(), "Authorization": f"Basic {credentials}"}
        _LOGGER.debug("Logging in as %s", self._email)
        try:
            async with self._get_session().post(
                f"{self._base_url}/login",
                json={"username": self._email, "password": self._password},
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Login failed: HTTP %s", resp.status)
                    if resp.status in (400, 401, 403):
                        raise PlanetFitnessAuthError(
                            f"Login rejected (HTTP {resp.status}); check credentials."
                        )
                    raise PlanetFitnessConnectionError(
                        f"Unexpected login status HTTP {resp.status}."
                    )
                self._cookies = {
                    name: morsel.value for name, morsel in resp.cookies.items()
                }
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PlanetFitnessConnectionError(f"Login request failed: {err}") from err

        if not self._cookies:
            # 200 but no session cookie means we are not actually logged in.
            raise PlanetFitnessAuthError("Login succeeded but no session was started.")
        _LOGGER.debug("Logged in; session established")

    async def async_get_clubs(self) -> list[Club]:
        """Fetch live occupancy for every studio.

        Logs in automatically if not yet authenticated, and re-logs-in once if the
        session has expired (detected as an auth failure mid-fetch). A studio
        whose count could not be read comes back with `occupancy` None; only if
        none could be read does this raise PlanetFitnessConnectionError.
        """
        if not self._cookies:
            await self.async_login()
        try:
            return await self._fetch_clubs()
        except PlanetFitnessAuthError:
            _LOGGER.debug("Session expired; re-authenticating.")
            self._cookies = {}
            await self.async_login()
            return await self._fetch_clubs()

    async def async_get_studios(self) -> list[Studio]:
        """The studios on the portal, from cache unless it is stale.

        If a refresh fails but there is an older list, that is used rather
        than failing a poll over reference data that rarely changes.
        """
        age = time.monotonic() - self._studios_fetched_at
        if self._studios is not None and age < _STUDIO_CACHE_SECONDS:
            return self._studios
        try:
            data = await self._get_json(
                "/studio-api/v1/public/studios/forwhitelabelportal", authenticated=False
            )
            studios = [Studio.from_api(item) for item in data["content"]]
        except (PlanetFitnessConnectionError, KeyError, TypeError, ValueError) as err:
            if self._studios is not None:
                _LOGGER.debug("Studio list refresh failed (%s); using cached list", err)
                return self._studios
            if isinstance(err, PlanetFitnessConnectionError):
                raise
            raise PlanetFitnessConnectionError(
                f"Unexpected studio list response: {err}"
            ) from err
        self._studios = studios
        self._studios_fetched_at = time.monotonic()
        _LOGGER.debug("Fetched %d studios", len(studios))
        return studios

    async def _fetch_clubs(self) -> list[Club]:
        studios = await self.async_get_studios()
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def fetch_one(studio: Studio) -> int:
            async with semaphore:
                data = await self._get_json(
                    f"/nox/v1/studios/{studio.studio_id}/utilization/v2/active-checkin"
                )
            try:
                return int(data["value"])
            except (KeyError, TypeError, ValueError) as err:
                raise PlanetFitnessConnectionError(
                    f"Unexpected count for studio {studio.studio_id}: {data!r}"
                ) from err

        results = await asyncio.gather(
            *(fetch_one(studio) for studio in studios), return_exceptions=True
        )

        for result in results:
            if isinstance(result, PlanetFitnessAuthError):
                raise result
        failures = [r for r in results if isinstance(r, BaseException)]
        if failures and len(failures) == len(results):
            first = failures[0]
            if isinstance(first, PlanetFitnessConnectionError):
                raise first
            raise PlanetFitnessConnectionError(f"Occupancy fetch failed: {first}") from first
        if failures:
            _LOGGER.debug(
                "Could not read %d of %d studios; first error: %s",
                len(failures),
                len(results),
                failures[0],
            )

        clubs = [
            studio.to_club(None if isinstance(result, BaseException) else result)
            for studio, result in zip(studios, results)
        ]
        unique = one_club_per_key(clubs)
        if len(unique) != len(clubs):
            _LOGGER.debug(
                "Dropped %d studio(s) sharing a name with a better-reporting one",
                len(clubs) - len(unique),
            )
        return unique

    async def _get_json(self, path: str, *, authenticated: bool = True) -> Any:
        """GET a portal path and decode its JSON body.

        401/403 means the session is gone (PlanetFitnessAuthError); other bad
        statuses, transport errors and non-JSON bodies are connection errors.
        """
        kwargs: dict[str, Any] = {}
        if authenticated:
            kwargs["cookies"] = self._cookies
        try:
            async with self._get_session().get(
                f"{self._base_url}{path}",
                headers=self._headers(),
                timeout=_REQUEST_TIMEOUT,
                **kwargs,
            ) as resp:
                if authenticated and resp.status in (401, 403):
                    raise PlanetFitnessAuthError("Not authenticated for portal request.")
                if resp.status != 200:
                    _LOGGER.debug("GET %s failed: HTTP %s", path, resp.status)
                    raise PlanetFitnessConnectionError(
                        f"Portal request failed HTTP {resp.status}."
                    )
                try:
                    return await resp.json(content_type=None)
                except ValueError as err:
                    raise PlanetFitnessConnectionError(
                        "Portal returned a response that is not JSON."
                    ) from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PlanetFitnessConnectionError(f"Portal request failed: {err}") from err
