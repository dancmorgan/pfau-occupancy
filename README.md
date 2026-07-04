# pfau-occupancy

Async Python client for Planet Fitness Australia club occupancy, backing a Home
Assistant integration. Data comes from the member portal (PerfectGym
ClientPortal2), which exposes a live "members currently in club" count for every
club in a single authenticated call.

This library deliberately does only the API layer: login, session handling, and
fetching occupancy. All Home Assistant concerns (entities, config flow,
coordinator) live in the [pfau-occupancy-ha](https://github.com/dancmorgan/pfau-occupancy-ha)
integration that depends on this package.

## Install

```bash
pip install pfau-occupancy
```

## Usage

```python
import asyncio
from pfau_occupancy import PlanetFitnessClient

async def main():
    async with PlanetFitnessClient("you@example.com", "password") as client:
        clubs = await client.async_get_clubs()
        for club in clubs:
            print(club.name, club.occupancy)

asyncio.run(main())
```

The client logs in automatically on first fetch and re-authenticates once if the
session expires, so a long-running poller keeps working without intervention.

## Data notes

The occupancy endpoint returns every club in one response. Each club carries a
name, address, a currently-in-club count, and a capacity limit (often null). The
response has no club ID, so the (slugified) club name is the stable identity used
for entity `unique_id`s. A club being renamed therefore looks like one club
disappearing and another appearing.

## Disclaimer

This uses the member portal's internal endpoints, which are undocumented and may
change or break without notice. It requires your own valid membership
credentials. Use it with your own account and keep polling gentle.
