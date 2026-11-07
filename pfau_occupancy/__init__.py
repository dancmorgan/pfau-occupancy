"""pfau_occupancy: async client for Planet Fitness AU club occupancy."""
from .client import PlanetFitnessClient, DEFAULT_BASE_URL
from .exceptions import (
    PlanetFitnessError,
    PlanetFitnessAuthError,
    PlanetFitnessConnectionError,
)
from .models import Club, Studio, slugify_club

__version__ = "0.2.0"

__all__ = [
    "PlanetFitnessClient",
    "DEFAULT_BASE_URL",
    "PlanetFitnessError",
    "PlanetFitnessAuthError",
    "PlanetFitnessConnectionError",
    "Club",
    "Studio",
    "slugify_club",
]
