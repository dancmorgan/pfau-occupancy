#!/usr/bin/env python3
"""Manual check of pfau_occupancy against the live portal.

Run it yourself; it asks for your member portal email and password, so they
never need to be pasted anywhere. Only counts are printed.

    python3 example.py

Set PF_EMAIL and PF_PASSWORD instead to skip the prompts. Pass --debug to see
the client's own log lines (request paths and statuses, never credentials).

Pass --probe to also print, for every club, today's utilisation profile beside
the live count. It shows whether a club reading 0 has any utilisation data at
all, which separates a quiet club from one the portal has no data for.
"""
import asyncio
import getpass
import logging
import os
import sys
import time
from typing import Any

from pfau_occupancy import (
    Club,
    PlanetFitnessAuthError,
    PlanetFitnessClient,
    PlanetFitnessConnectionError,
)

PROBE_CONCURRENCY = 6


def summarise_profile(buckets: Any) -> tuple[int | None, int, int, int] | None:
    """(now %, peak %, hours above 0, hours listed) for a `today` response.

    None if the response is not the expected list of hourly buckets. `now` is
    None when no bucket is flagged as the current hour.
    """
    if not isinstance(buckets, list) or not buckets:
        return None
    percentages = [
        b.get("percentage") or 0 for b in buckets if isinstance(b, dict)
    ]
    if not percentages:
        return None
    now = next(
        (b.get("percentage") or 0 for b in buckets if isinstance(b, dict) and b.get("current")),
        None,
    )
    return now, max(percentages), sum(1 for p in percentages if p > 0), len(percentages)


async def probe(client: PlanetFitnessClient, clubs: list[Club]) -> None:
    """Print each club's live count beside today's utilisation profile.

    Uses the client's private request helper: this is a diagnostic, not part
    of the library's API.
    """
    semaphore = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def today(club: Club) -> Any:
        async with semaphore:
            try:
                return await client._get_json(
                    f"/nox/v1/studios/{club.studio_id}/utilization/v2/today"
                )
            except (PlanetFitnessAuthError, PlanetFitnessConnectionError) as err:
                return err

    results = await asyncio.gather(*(today(club) for club in clubs))

    print(f"\n  {'Club':<22} {'count':>5} {'now %':>6} {'peak %':>7}  hours > 0")
    reads_zero_with_profile: list[str] = []
    reads_zero_without_profile: list[str] = []
    for club, result in sorted(zip(clubs, results), key=lambda pair: pair[0].name):
        count = "?" if club.occupancy is None else club.occupancy
        if isinstance(result, Exception):
            print(f"  {club.name:<22} {count:>5}   request failed: {type(result).__name__}")
            continue
        summary = summarise_profile(result)
        if summary is None:
            print(f"  {club.name:<22} {count:>5}   unexpected response shape")
            continue
        now, peak, active, listed = summary
        now_text = "?" if now is None else now
        print(f"  {club.name:<22} {count:>5} {now_text:>6} {peak:>7}  {active}/{listed}")
        if club.occupancy == 0:
            (reads_zero_with_profile if peak > 0 else reads_zero_without_profile).append(
                club.name
            )

    print(f"\nReads 0 but has a utilisation profile ({len(reads_zero_with_profile)}):")
    print("  " + (", ".join(reads_zero_with_profile) or "none"))
    print(f"Reads 0 and its profile is all zero ({len(reads_zero_without_profile)}):")
    print("  " + (", ".join(reads_zero_without_profile) or "none"))


async def main() -> None:
    if "--debug" in sys.argv:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    email = os.environ.get("PF_EMAIL") or input("Member portal email: ")
    password = os.environ.get("PF_PASSWORD") or getpass.getpass("Password: ")

    async with PlanetFitnessClient(email, password) as client:
        started = time.monotonic()
        try:
            clubs = await client.async_get_clubs()
        except PlanetFitnessAuthError as err:
            print("Auth failed:", err)
            return
        except PlanetFitnessConnectionError as err:
            print("Could not reach the portal:", err)
            return
        elapsed = time.monotonic() - started

        print(f"\n{len(clubs)} clubs in {elapsed:.1f}s\n")
        for club in sorted(clubs, key=lambda c: c.name):
            count = "?" if club.occupancy is None else club.occupancy
            print(f"  {club.name:<22} {count:>4}   key={club.key}")

        unknown = [c.name for c in clubs if c.occupancy is None]
        if unknown:
            print(f"\nNo count for: {', '.join(unknown)}")

        if "--probe" in sys.argv:
            await probe(client, clubs)


if __name__ == "__main__":
    asyncio.run(main())
