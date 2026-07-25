"""Transport and configuration hardening.

These cover the failures that are invisible from the outside: a response missing a header, a
limiter keyed on something the caller controls, a deployment that boots with protection
switched off. Each of those looks exactly like a working system until it matters.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.rate_limit import client_ip
from app.core.config import Environment, Settings
from app.main import create_app


def _request(settings: Settings, *, peer: str, forwarded: str | None) -> Request:
    headers = [(b"host", b"test")]
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "client": (peer, 1234),
        "app": type("App", (), {"state": type("State", (), {"settings": settings})()})(),
    }
    return Request(scope)  # type: ignore[arg-type]


class TestClientIp:
    """The rate-limit key must not be something the caller can choose."""

    def test_ignores_forwarded_header_without_a_proxy(self, settings: Settings) -> None:
        # With no proxy configured, a caller who invents an XFF header would otherwise get a
        # fresh bucket per request and bypass the limiter entirely.
        request = _request(settings, peer="203.0.113.9", forwarded="1.2.3.4")
        assert client_ip(request) == "203.0.113.9"

    def test_reads_one_hop_from_the_right(self, settings: Settings) -> None:
        proxied = settings.model_copy(update={"trusted_proxy_hops": 1})
        # Our proxy appended the real client; anything to its left is caller-supplied.
        request = _request(proxied, peer="10.0.0.1", forwarded="9.9.9.9, 198.51.100.7")
        assert client_ip(request) == "198.51.100.7"

    def test_spoofed_prefix_cannot_shift_the_result(self, settings: Settings) -> None:
        proxied = settings.model_copy(update={"trusted_proxy_hops": 1})
        request = _request(proxied, peer="10.0.0.1", forwarded="evil, spoof, more, 198.51.100.7")
        assert client_ip(request) == "198.51.100.7"

    def test_two_hops_reads_two_from_the_right(self, settings: Settings) -> None:
        proxied = settings.model_copy(update={"trusted_proxy_hops": 2})
        request = _request(proxied, peer="10.0.0.1", forwarded="198.51.100.7, 10.0.0.9")
        assert client_ip(request) == "198.51.100.7"

    def test_short_chain_falls_back_to_the_leftmost_entry(self, settings: Settings) -> None:
        proxied = settings.model_copy(update={"trusted_proxy_hops": 3})
        request = _request(proxied, peer="10.0.0.1", forwarded="198.51.100.7")
        assert client_ip(request) == "198.51.100.7"

    def test_falls_back_to_the_peer_when_the_header_is_absent(self, settings: Settings) -> None:
        proxied = settings.model_copy(update={"trusted_proxy_hops": 1})
        request = _request(proxied, peer="203.0.113.9", forwarded=None)
        assert client_ip(request) == "203.0.113.9"


class TestDeployedConfiguration:
    """A deployed environment must refuse to start in an unsafe shape."""

    def _deployed(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "STUDY_ENV": Environment.PRODUCTION,
            "JWT_SECRET": "a" * 40,
            "DEVICE_HASH_SALT": "a-real-salt",
            "RATE_LIMIT_ENABLED": True,
            "ALLOWED_HOSTS": "api.example.com",
        }
        base.update(overrides)
        return base

    def test_boots_when_fully_configured(self) -> None:
        assert Settings(**self._deployed()).is_deployed  # type: ignore[arg-type]

    def test_refuses_a_disabled_rate_limiter(self) -> None:
        with pytest.raises(ValueError, match="RATE_LIMIT_ENABLED"):
            Settings(**self._deployed(RATE_LIMIT_ENABLED=False))  # type: ignore[arg-type]

    def test_refuses_a_missing_host_allowlist(self) -> None:
        with pytest.raises(ValueError, match="ALLOWED_HOSTS"):
            Settings(**self._deployed(ALLOWED_HOSTS=""))  # type: ignore[arg-type]

    def test_refuses_the_default_signing_key(self) -> None:
        with pytest.raises(ValueError, match="JWT_SECRET"):
            Settings(**self._deployed(JWT_SECRET="local-dev-secret-change-me"))  # type: ignore[arg-type]

    def test_refuses_a_short_signing_key(self) -> None:
        with pytest.raises(ValueError, match="at least 32"):
            Settings(**self._deployed(JWT_SECRET="too-short"))  # type: ignore[arg-type]

    def test_local_stays_convenient(self, settings: Settings) -> None:
        # The whole point of the gate is that it does not fire in development.
        assert not settings.is_deployed


class TestSecurityHeaders:
    async def test_every_response_carries_the_hardening_headers(self, client: AsyncClient) -> None:
        response = await client.get("/health/live")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Content-Security-Policy"] == "default-src 'none'"
        assert "camera=()" in response.headers["Permissions-Policy"]

    async def test_errors_are_hardened_too(self, client: AsyncClient) -> None:
        # An error path that skips the headers is the one an attacker will look for.
        response = await client.get("/me")
        assert response.status_code == 401
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    async def test_hsts_is_absent_locally(self, client: AsyncClient) -> None:
        # Sending HSTS from a local HTTP origin would make the browser refuse plain
        # http://localhost afterwards — a self-inflicted outage for every developer.
        response = await client.get("/health/live")
        assert "Strict-Transport-Security" not in response.headers

    async def test_hsts_is_present_when_deployed(
        self, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        deployed = settings.model_copy(
            update={
                "environment": Environment.PRODUCTION,
                "jwt_secret": "b" * 40,
                "device_hash_salt": "salt",
                "rate_limit_enabled": True,
                "allowed_hosts": ["test"],
            }
        )
        app = create_app(deployed)
        app.state.session_factory = session_factory
        app.state.redis = None
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api/v1"
        ) as http:
            response = await http.get("/health/live")
        assert "max-age=" in response.headers["Strict-Transport-Security"]
        assert "includeSubDomains" in response.headers["Strict-Transport-Security"]


class TestRequestSizeLimit:
    async def test_rejects_a_body_over_the_ceiling(
        self, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        tiny = settings.model_copy(update={"max_request_bytes": 512})
        app = create_app(tiny)
        app.state.session_factory = session_factory
        app.state.redis = None
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api/v1"
        ) as http:
            response = await http.post("/auth/login", json={"email": "a@b.c", "p": "x" * 2000})

        assert response.status_code == 413
        assert response.json()["error"]["details"]["max_bytes"] == 512

    async def test_allows_an_ordinary_body(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": "password123"}
        )
        # Wrong credentials, but it got past the size gate, which is what this asserts.
        assert response.status_code == 401


class TestTrustedHost:
    async def test_rejects_an_unlisted_host(
        self, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        guarded = settings.model_copy(update={"allowed_hosts": ["api.example.com"]})
        app = create_app(guarded)
        app.state.session_factory = session_factory
        app.state.redis = None
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://evil.example.net/api/v1"
        ) as http:
            response = await http.get("/health/live")
        assert response.status_code == 400
