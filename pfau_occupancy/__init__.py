"""pfau_occupancy: async client for Planet Fitness AU club occupancy."""
from .client import PlanetFitnessClient, DEFAULT_BASE_URL
from .exceptions import (
    PlanetFitnessError,
    PlanetFitnessAuthError,
    PlanetFitnessConnectionError,
)
from .models import Club, slugify_club

__version__ = "0.1.1"

__all__ = [
    "PlanetFitnessClient",
    "DEFAULT_BASE_URL",
    "PlanetFitnessError",
    "PlanetFitnessAuthError",
    "PlanetFitnessConnectionError",
    "Club",
    "slugify_club",
]
