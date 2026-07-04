"""Exceptions for pfau_occupancy."""


class PlanetFitnessError(Exception):
    """Base error for all pfau_occupancy failures."""


class PlanetFitnessAuthError(PlanetFitnessError):
    """Raised when login fails or the session is no longer authenticated.

    The Home Assistant coordinator treats this specially: it triggers a
    re-login (and, if that fails, a reauth flow) rather than marking sensors
    unavailable, so a dropped session is never confused with an empty club.
    """


class PlanetFitnessConnectionError(PlanetFitnessError):
    """Raised on network/transport problems talking to the portal."""
