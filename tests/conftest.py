"""A fake member portal, served over real HTTP on localhost.

It checks what the real portal's web app sends (headers, a session cookie) so
a regression in the client shows up as a failing request, not a silent pass.
"""
from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from pfau_occupancy import PlanetFitnessClient
from pfau_occupancy.client import DEFAULT_FACILITY_GROUP, DEFAULT_TENANT

EMAIL = "member@example.com"
PASSWORD = "hunter2"


def studio(
    magicline_id: int, name: str, city: str = "Sydney", zone: str = "Australia/Sydney"
) -> dict[str, Any]:
    return {
        "magiclineId": magicline_id,
        "name": name,
        "zoneId": zone,
        "address": {
            "houseNumber": "1",
            "street": "Test Street",
            "city": city,
            "provinceCode": "NSW",
            "zipCode": "2000",
        },
    }


class FakePortal:
    """Scriptable stand-in for the portal."""

    def __init__(self) -> None:
        self.studios = [
            studio(101, "Planet Fitness Hornsby", "Hornsby"),
            studio(102, "Morayfield", "Morayfield", "Australia/Brisbane"),
            studio(103, "Planet Fitness Auburn", "Auburn"),
        ]
        self.counts = {101: 32, 102: 7, 103: 55}
        self.fail_status: dict[int, int] = {}
        self.login_status = 200
        self.login_sets_cookie = True
        # Suspected of the real portal: a login that arrives already carrying a
        # live session is answered without starting a new one (no Set-Cookie).
        self.answers_a_live_session_without_a_cookie = False
        self.studio_list_status = 200
        self.studio_list_body: Any = None
        self.count_body_override: dict[int, Any] = {}
        self.delay = 0.0
        # The CloudFront firewall in front of the real portal refuses the User-Agent
        # Home Assistant's shared session sends; this switch refuses everything.
        self.firewall_refuses_all = False
        # Observations.
        self.firewall_refusals = 0
        self.logins = 0
        self.studio_list_requests = 0
        self.count_requests: list[int] = []
        self.last_login_request: dict[str, Any] = {}
        self.last_data_headers: dict[str, str] = {}
        self.active_sessions: set[str] = set()
        self._in_flight = 0
        self.max_in_flight = 0

    def expire_sessions(self) -> None:
        self.active_sessions.clear()

    # ---- handlers -------------------------------------------------------

    @web.middleware
    async def firewall(self, request: web.Request, handler: Any) -> web.StreamResponse:
        agent = request.headers.get("User-Agent", "")
        if self.firewall_refuses_all or agent.startswith("HomeAssistant/"):
            self.firewall_refusals += 1
            return web.Response(
                status=403, text="<html>Request blocked.</html>", content_type="text/html"
            )
        return await handler(request)

    async def login(self, request: web.Request) -> web.Response:
        self.logins += 1
        self.last_login_request = {
            "headers": dict(request.headers),
            "json": await request.json(),
        }
        if self.login_status != 200:
            return web.json_response(
                [{"errorCode": "login.bad.credentials"}], status=self.login_status
            )
        expected = base64.b64encode(f"{EMAIL}:{PASSWORD}".encode()).decode()
        body = self.last_login_request["json"]
        if (
            request.headers.get("Authorization") != f"Basic {expected}"
            or body != {"username": EMAIL, "password": PASSWORD}
        ):
            return web.json_response(
                [{"errorCode": "login.bad.credentials"}], status=401
            )
        # The real portal's answer carries the tokens in the body as well.
        response = web.json_response(
            {"access_token": "token-value", "sessionId": "session-value"}
        )
        carries_live_session = request.cookies.get("SESSION") in self.active_sessions
        if self.login_sets_cookie and not (
            self.answers_a_live_session_without_a_cookie and carries_live_session
        ):
            token = f"session-{self.logins}"
            self.active_sessions.add(token)
            response.set_cookie("SESSION", token, httponly=True, secure=False)
        return response

    async def studio_list(self, request: web.Request) -> web.Response:
        self.studio_list_requests += 1
        if request.headers.get("X-Public-Facility-Group") != DEFAULT_FACILITY_GROUP:
            return web.json_response({"content": []})
        if self.studio_list_status != 200:
            return web.Response(status=self.studio_list_status)
        if self.studio_list_body is not None:
            return web.json_response(self.studio_list_body)
        return web.json_response({"content": self.studios})

    async def active_checkin(self, request: web.Request) -> web.Response:
        studio_id = int(request.match_info["studio_id"])
        self.count_requests.append(studio_id)
        self.last_data_headers = dict(request.headers)
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        finally:
            self._in_flight -= 1
        if request.cookies.get("SESSION") not in self.active_sessions:
            return web.Response(status=401)
        if studio_id in self.fail_status:
            return web.Response(status=self.fail_status[studio_id])
        if studio_id in self.count_body_override:
            return web.Response(
                text=self.count_body_override[studio_id], content_type="application/json"
            )
        return web.json_response({"value": self.counts[studio_id]})


@pytest.fixture
async def portal() -> AsyncIterator[tuple[FakePortal, str]]:
    fake = FakePortal()
    app = web.Application(middlewares=[fake.firewall])
    app.router.add_post("/login", fake.login)
    app.router.add_get(
        "/studio-api/v1/public/studios/forwhitelabelportal", fake.studio_list
    )
    app.router.add_get(
        "/nox/v1/studios/{studio_id}/utilization/v2/active-checkin", fake.active_checkin
    )
    server = TestServer(app)
    await server.start_server()
    try:
        yield fake, str(server.make_url("")).rstrip("/")
    finally:
        await server.close()


@pytest.fixture
async def client(portal) -> AsyncIterator[PlanetFitnessClient]:
    _, base_url = portal
    async with PlanetFitnessClient(EMAIL, PASSWORD, base_url=base_url) as c:
        yield c


@pytest.fixture
def fake(portal) -> FakePortal:
    return portal[0]


__all__ = ["DEFAULT_TENANT", "EMAIL", "PASSWORD", "FakePortal", "studio"]
