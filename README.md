# pfau-occupancy

Async Python client for Planet Fitness Australia club occupancy, backing a Home
Assistant integration. Data comes from the member portal (Magicline "MySports"),
which exposes a live "people currently checked in" count for each studio.

This library deliberately does only the API layer: login, session handling, and
fetching occupancy. All Home Assistant concerns (entities, config flow,
coordinator) live in the [pfau-occupancy-ha](https://github.com/dancmorgan/pfau-occupancy-ha)
integration that depends on this package.

> **0.2.0 is a breaking change.** Planet Fitness moved its member portal from
> PerfectGym to Magicline, so the old endpoints no longer work. The public API
> of this package (`PlanetFitnessClient.async_get_clubs()` and `Club`) is
> unchanged, but `Club.limit` is now always `None` (the new portal reports no
> capacity) and `async_login()` no longer returns the member record.

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

Each poll is one request for the studio list (cached for six hours, and reused
if a refresh fails) plus one live-count request per studio, a few at a time. A
studio whose count cannot be read comes back with `occupancy` of `None`; if none
can be read the client raises `PlanetFitnessConnectionError`.

### Clubs that have not moved to the new portal yet

Franchises are moving onto the new portal one at a time. A studio that has not
moved is still listed, under a placeholder name (often without the "Planet
Fitness " prefix), and reports a count of `0`. That `0` does not mean the club is
empty; there is simply no live data for it yet. When two listed studios share a
name, the client returns only the one with the higher count (a count beats `0`,
and `0` beats no reading), so a placeholder never hides a live studio. The
client cannot tell a placeholder `0` from a club that really is empty, so a
studio reading `0` is not necessarily reporting.

### Identity

The portal's numeric studio ID is available as `Club.studio_id`, but the
(slugified) club name remains the stable identity used for entity `unique_id`s,
so existing installs keep their entities. A couple of clubs whose portal name
has changed keep their old key. A club being renamed on the portal therefore
looks like one club disappearing and another appearing.

The session is a cookie held by the client itself, so several clients can share
one `aiohttp` session without sharing a login.

### Firewall refusals

The portal sits behind a CloudFront firewall that refuses some `User-Agent`s,
including the `HomeAssistant/...` one Home Assistant's shared `aiohttp` session
sends by default, with an HTML HTTP 403 before the credentials are even looked
at. The client therefore sends its own `User-Agent` on every request (it
overrides the session's), and reports such a refusal as
`PlanetFitnessConnectionError` rather than `PlanetFitnessAuthError`. A wrong
password is a JSON 401 and stays an auth error.

## Trying it against the live portal

```bash
python3 example.py        # prompts for your email and password; prints counts only
python3 example.py --debug
python3 example.py --probe   # also prints each club's utilisation profile for today
```

`--probe` puts the live count beside today's hourly utilisation profile for every
club, and lists the clubs that read `0`, split by whether they have any profile
at all. That separates a quiet club from one the portal has no data for. It
prints percentages and counts only.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests run the client against a fake portal served over localhost.

## Disclaimer

This uses the member portal's internal endpoints, which are undocumented and may
change or break without notice. It requires your own valid membership
credentials. Use it with your own account and keep polling gentle.
