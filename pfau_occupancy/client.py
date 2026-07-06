"""Async client for the Planet Fitness AU (PerfectGym ClientPortal2) portal."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .exceptions import (
    PlanetFitnessAuthError,
    PlanetFitnessConnectionError,
)
from .models import Club

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://planetfitness.perfectgym.com.au/clientportal2"

# Sent on every XHR by the browser. The backend checks x-requested-with;
# cp-lang / cp-mode are constants the portal expects.
_BASE_HEADERS = {
    "x-requested-with": "XMLHttpRequest",
    "cp-lang": "en",
    "cp-mode": "desktop",
    "accept": "application/json, text/plain, */*",
}


class PlanetFitnessClient:
    """Talks to the member portal: login, then fetch club occupancy.

    Holds one aiohttp session so the auth cookie persists across calls. Credentials
    are kept so the client can transparently re-login when the session expires,
    which for a long-running poller it eventually will.

    The caller owns the aiohttp session lifecycle by passing one in (this is what
    Home Assistant wants: it supplies its shared session). If none is given, one is
    created and closed by `async with` / `close()`.
    """

    def __init__(
        self,
        email: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._email = email
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._owns_session = session is None
        self._authenticated = False

    async def __aenter__(self) -> "PlanetFitnessClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            # cookie_jar persists the session cookie across requests.
            self._session = aiohttp.ClientSession()
        return self._session

    def _headers(self) -> dict[str, str]:
        return {
            **_BASE_HEADERS,
            "origin": "https://planetfitness.perfectgym.com.au",
            "referer": self._base_url + "/",
        }

    async def async_login(self) -> dict[str, Any]:
        """Authenticate and return the member record.

        Raises PlanetFitnessAuthError on bad credentials, PlanetFitnessConnectionError
        on transport problems.
        """
        session = self._get_session()
        payload = {"RememberMe": True, "Login": self._email, "Password": self._password}
        _LOGGER.debug("Logging in as %s", self._email)
        try:
            async with session.post(
                f"{self._base_url}/Auth/Login",
                json=payload,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:500]
                    _LOGGER.debug(
                        "Login failed: HTTP %s, body: %s", resp.status, body
                    )
                    if resp.status in (400, 401, 403) or _looks_like_bad_credentials(
                        body
                    ):
                        raise PlanetFitnessAuthError(
                            f"Login rejected (HTTP {resp.status}); check credentials."
                        )
                    raise PlanetFitnessConnectionError(
                        f"Unexpected login status HTTP {resp.status}."
                    )
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise PlanetFitnessConnectionError(f"Login request failed: {err}") from err

        member = _extract_member(data)
        if not member:
            # 200 but no member usually means the session cookie was not set.
            raise PlanetFitnessAuthError("Login succeeded but no member returned.")
        self._authenticated = True
        _LOGGER.debug("Authenticated as member %s", member.get("Id"))
        return member

    async def async_get_clubs(self) -> list[Club]:
        """Fetch occupancy for all clubs.

        Logs in automatically if not yet authenticated, and re-logs-in once if the
        session has expired (detected as an auth failure mid-fetch).
        """
        if not self._authenticated:
            await self.async_login()
        try:
            return await self._fetch_clubs()
        except PlanetFitnessAuthError:
            # Session likely expired. Re-login once, then retry.
            _LOGGER.debug("Session expired; re-authenticating.")
            self._authenticated = False
            await self.async_login()
            return await self._fetch_clubs()

    async def _fetch_clubs(self) -> list[Club]:
        session = self._get_session()
        try:
            async with session.post(
                f"{self._base_url}/Clubs/Clubs/GetMembersInClubs",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status in (401, 403):
                    raise PlanetFitnessAuthError("Not authenticated for club fetch.")
                if resp.status != 200:
                    _LOGGER.debug(
                        "Club fetch failed: HTTP %s, body: %s",
                        resp.status,
                        (await resp.text())[:500],
                    )
                    raise PlanetFitnessConnectionError(
                        f"Club fetch failed HTTP {resp.status}."
                    )
                # An expired session can also return the login page (HTML) with a
                # 200. Guard against that so we don't parse HTML as JSON.
                ctype = resp.headers.get("content-type", "")
                if "application/json" not in ctype:
                    _LOGGER.debug(
                        "Club fetch returned content-type %r instead of JSON", ctype
                    )
                    raise PlanetFitnessAuthError(
                        "Club fetch returned non-JSON; session likely expired."
                    )
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise PlanetFitnessConnectionError(f"Club fetch failed: {err}") from err

        raw_list = data.get("UsersInClubList") or []
        _LOGGER.debug("Fetched occupancy for %d clubs", len(raw_list))
        return [Club.from_api(item) for item in raw_list]


def _looks_like_bad_credentials(body: str) -> bool:
    """Detect a credentials rejection hiding behind a non-auth status code.

    The portal reports a wrong password as HTTP 500 with an error payload
    (e.g. "IncorrectLoginOrPassword") rather than a 401, which would otherwise
    be misclassified as a connection problem.
    """
    lowered = body.lower()
    return "incorrectloginorpassword" in lowered or "incorrect login" in lowered


def _extract_member(data: dict) -> dict:
    """Login returns {"User": {"Member": {...}}}; Identity returns {"Member": {...}}.

    Handle both so either response shape confirms authentication.
    """
    user = data.get("User")
    if isinstance(user, dict) and user.get("Member"):
        return user["Member"]
    return data.get("Member") or {}
