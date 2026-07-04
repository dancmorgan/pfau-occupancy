#!/usr/bin/env python3
"""Manual smoke test for pfau_occupancy against the live portal.

    export PF_EMAIL="you@example.com"
    export PF_PASSWORD="yourpassword"
    python3 example.py
"""
import asyncio
import os

from pfau_occupancy import PlanetFitnessClient, PlanetFitnessAuthError


async def main() -> None:
    email = os.environ["PF_EMAIL"]
    password = os.environ["PF_PASSWORD"]

    async with PlanetFitnessClient(email, password) as client:
        try:
            member = await client.async_login()
        except PlanetFitnessAuthError as err:
            print("Auth failed:", err)
            return
        print(f"Logged in, home club id = {member.get('HomeClubId')}\n")

        clubs = await client.async_get_clubs()
        for club in sorted(clubs, key=lambda c: c.name):
            pct = f" ({club.percent_full}%)" if club.percent_full is not None else ""
            print(f"  {club.name:<20} {club.occupancy}{pct}")


if __name__ == "__main__":
    asyncio.run(main())
