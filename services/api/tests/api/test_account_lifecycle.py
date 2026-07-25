"""Password change, password reset, account deletion, and the cookie refresh transport.

The recurring theme is that a credential change must actually end the sessions it is meant
to end. A password change that leaves the attacker's session alive has not taken the account
back, and that is invisible from the response body — so it is asserted here directly.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.core.security import hash_reset_token
from app.domain.accounts.service import AccountService
from app.models.user import PasswordResetToken, User


async def _login(client: AsyncClient, user: User) -> dict[str, str]:
    response = await client.post(
        "/auth/login", json={"email": user.email, "password": "test-passphrase-9x"}
    )
    assert response.status_code == 200
    return response.json()["tokens"]


class TestChangePassword:
    async def test_changes_the_password_and_issues_new_tokens(
        self, client: AsyncClient, user: User, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/auth/change-password",
            headers=auth_headers,
            json={"current_password": "test-passphrase-9x", "new_password": "a-much-better-secret"},
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

        assert (
            await client.post(
                "/auth/login", json={"email": user.email, "password": "a-much-better-secret"}
            )
        ).status_code == 200
        assert (
            await client.post(
                "/auth/login", json={"email": user.email, "password": "test-passphrase-9x"}
            )
        ).status_code == 401

    async def test_revokes_every_other_session(
        self, client: AsyncClient, user: User, auth_headers: dict[str, str]
    ) -> None:
        # A second device, signed in before the password changes.
        other_device = await _login(client, user)

        await client.post(
            "/auth/change-password",
            headers=auth_headers,
            json={"current_password": "test-passphrase-9x", "new_password": "a-much-better-secret"},
        )

        # The whole point: the other device is signed out, not merely inconvenienced.
        replayed = await client.post(
            "/auth/refresh", json={"refresh_token": other_device["refresh_token"]}
        )
        assert replayed.status_code == 401

    async def test_rejects_a_wrong_current_password(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/auth/change-password",
            headers=auth_headers,
            json={"current_password": "not-it", "new_password": "a-much-better-secret"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"

    async def test_rejects_a_password_matching_the_username(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/auth/change-password",
            headers=auth_headers,
            json={"current_password": "test-passphrase-9x", "new_password": "student"},
        )
        # Fails the length rule first; either way it must not be accepted.
        assert response.status_code in (400, 422)

    async def test_rejects_a_common_password(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/auth/change-password",
            headers=auth_headers,
            json={"current_password": "test-passphrase-9x", "new_password": "password123"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "password_too_weak"

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/change-password",
            json={"current_password": "test-passphrase-9x", "new_password": "another-good-secret"},
        )
        assert response.status_code == 401


class TestPasswordReset:
    async def test_unknown_address_is_indistinguishable_from_a_known_one(
        self, client: AsyncClient, user: User
    ) -> None:
        known = await client.post("/auth/forgot-password", json={"email": user.email})
        unknown = await client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
        # Same status and same body: this endpoint must not be a membership oracle.
        assert known.status_code == unknown.status_code == 202
        assert known.json() == unknown.json()

    async def test_resets_the_password_and_ends_every_session(
        self, client: AsyncClient, db: AsyncSession, user: User, settings: object
    ) -> None:
        signed_in = await _login(client, user)
        await client.post("/auth/forgot-password", json={"email": user.email})

        raw = _issued_token(await _stored_tokens(db, user))
        response = await client.post(
            "/auth/reset-password", json={"token": raw, "new_password": "brand-new-secret"}
        )
        assert response.status_code == 204

        assert (
            await client.post(
                "/auth/login", json={"email": user.email, "password": "brand-new-secret"}
            )
        ).status_code == 200
        # A reset is a recovery action, so whatever was already signed in is suspect.
        assert (
            await client.post("/auth/refresh", json={"refresh_token": signed_in["refresh_token"]})
        ).status_code == 401

    async def test_a_token_cannot_be_used_twice(
        self, client: AsyncClient, db: AsyncSession, user: User
    ) -> None:
        await client.post("/auth/forgot-password", json={"email": user.email})
        raw = _issued_token(await _stored_tokens(db, user))

        first = await client.post(
            "/auth/reset-password", json={"token": raw, "new_password": "brand-new-secret"}
        )
        second = await client.post(
            "/auth/reset-password", json={"token": raw, "new_password": "another-secret-x"}
        )
        assert first.status_code == 204
        assert second.status_code == 400
        assert second.json()["error"]["code"] == "invalid_reset_token"

    async def test_an_expired_token_is_refused(
        self, client: AsyncClient, db: AsyncSession, user: User
    ) -> None:
        await client.post("/auth/forgot-password", json={"email": user.email})
        stored = await _stored_tokens(db, user)
        record = stored[0]
        record.expires_at = utc_now() - timedelta(minutes=1)
        await db.commit()

        response = await client.post(
            "/auth/reset-password",
            json={"token": _issued_token(stored), "new_password": "brand-new-secret"},
        )
        assert response.status_code == 400

    async def test_a_new_request_supersedes_the_previous_link(
        self, client: AsyncClient, db: AsyncSession, user: User
    ) -> None:
        await client.post("/auth/forgot-password", json={"email": user.email})
        first_batch = await _stored_tokens(db, user)
        first_raw = _issued_token(first_batch)

        await client.post("/auth/forgot-password", json={"email": user.email})

        # Two live links double the exposure window for no benefit; the older one is dead.
        response = await client.post(
            "/auth/reset-password", json={"token": first_raw, "new_password": "brand-new-secret"}
        )
        assert response.status_code == 400

    async def test_only_the_hash_is_stored(
        self, client: AsyncClient, db: AsyncSession, user: User
    ) -> None:
        await client.post("/auth/forgot-password", json={"email": user.email})
        stored = await _stored_tokens(db, user)
        raw = _issued_token(stored)
        assert stored[0].token_hash != raw
        assert stored[0].token_hash == hash_reset_token(raw)

    async def test_a_garbage_token_is_refused(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/reset-password", json={"token": "nonsense", "new_password": "brand-new-x"}
        )
        assert response.status_code == 400


class TestAccountDeletion:
    async def test_soft_deletes_and_signs_every_device_out(
        self, client: AsyncClient, db: AsyncSession, user: User, auth_headers: dict[str, str]
    ) -> None:
        signed_in = await _login(client, user)

        response = await client.delete("/me", headers=auth_headers)
        assert response.status_code == 204

        # Refresh the columns as well as the relationship: this session holds its own copy
        # of the row, and reloading only `profile` would leave `deleted_at` stale.
        await db.refresh(user)
        assert user.deleted_at is not None
        assert user.is_active is False
        assert (
            await client.post("/auth/refresh", json={"refresh_token": signed_in["refresh_token"]})
        ).status_code == 401
        assert (await client.get("/me", headers=auth_headers)).status_code == 401

    async def test_frees_the_email_for_immediate_reuse(
        self, client: AsyncClient, user: User, auth_headers: dict[str, str]
    ) -> None:
        original_email = user.email
        await client.delete("/me", headers=auth_headers)

        # Waiting out a 30-day retention window before you can sign up again with your own
        # address would be a bug, not a safeguard.
        response = await client.post(
            "/auth/register",
            json={
                "email": original_email,
                "password": "a-fresh-start-secret",
                "username": "student2",
            },
        )
        assert response.status_code == 201

    async def test_scrubs_the_public_profile(
        self, client: AsyncClient, db: AsyncSession, user: User, auth_headers: dict[str, str]
    ) -> None:
        await client.delete("/me", headers=auth_headers)
        await db.refresh(user, attribute_names=["profile"])
        assert user.profile.display_name == "Deleted account"
        assert user.profile.bio is None
        assert user.profile.username != "student"


class TestRefreshCookieTransport:
    async def test_cookie_clients_get_no_token_in_the_body(
        self, client: AsyncClient, user: User
    ) -> None:
        response = await client.post(
            "/auth/login",
            headers={"X-Refresh-Transport": "cookie"},
            json={"email": user.email, "password": "test-passphrase-9x"},
        )
        assert response.status_code == 200
        # Returning it here as well would hand the token straight back to JavaScript and
        # make the httpOnly cookie pointless.
        assert response.json()["tokens"]["refresh_token"] is None
        assert "sl_refresh" in response.cookies

    async def test_the_cookie_is_httponly_and_samesite_strict(
        self, client: AsyncClient, user: User
    ) -> None:
        response = await client.post(
            "/auth/login",
            headers={"X-Refresh-Transport": "cookie"},
            json={"email": user.email, "password": "test-passphrase-9x"},
        )
        header = response.headers["set-cookie"].lower()
        assert "httponly" in header
        assert "samesite=strict" in header
        # Not Secure locally, or the cookie would never be delivered over http://localhost.
        assert "secure" not in header

    async def test_refresh_works_from_the_cookie_alone(
        self, client: AsyncClient, user: User
    ) -> None:
        await client.post(
            "/auth/login",
            headers={"X-Refresh-Transport": "cookie"},
            json={"email": user.email, "password": "test-passphrase-9x"},
        )
        # No body token at all: the browser sends the cookie and nothing else.
        response = await client.post("/auth/refresh", json={})
        assert response.status_code == 200
        assert response.json()["access_token"]
        assert response.json()["refresh_token"] is None

    async def test_body_clients_are_unaffected(self, client: AsyncClient, user: User) -> None:
        tokens = await _login(client, user)
        assert tokens["refresh_token"]
        rotated = await client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert rotated.status_code == 200
        assert rotated.json()["refresh_token"]

    async def test_refresh_without_any_token_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post("/auth/refresh", json={})
        assert response.status_code == 401

    async def test_logout_clears_the_cookie(self, client: AsyncClient, user: User) -> None:
        await client.post(
            "/auth/login",
            headers={"X-Refresh-Transport": "cookie"},
            json={"email": user.email, "password": "test-passphrase-9x"},
        )
        response = await client.post("/auth/logout", json={})
        assert response.status_code == 204
        assert not client.cookies.get("sl_refresh")


class TestWeakPasswordsAtRegistration:
    async def test_rejects_a_common_password(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={"email": "new@example.com", "password": "password123", "username": "newbie"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "password_too_weak"

    async def test_rejects_a_password_equal_to_the_email_local_part(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/auth/register",
            json={
                "email": "longenoughname@example.com",
                "password": "longenoughname",
                "username": "newbie",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "password_too_weak"

    async def test_accepts_an_ordinary_password(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={"email": "new@example.com", "password": "quiet-otter-73", "username": "newbie"},
        )
        assert response.status_code == 201


# The clear token only exists in the service's return value, so tests reproduce the lookup
# by hashing candidates rather than reading something the database never stores.
_ISSUED: list[str] = []


async def _stored_tokens(db: AsyncSession, user: User) -> list[PasswordResetToken]:
    result = await db.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id)
        .order_by(PasswordResetToken.created_at)
    )
    return list(result.scalars().all())


def _issued_token(stored: list[PasswordResetToken]) -> str:
    """Recover the clear token that produced a stored hash, from the ones we minted."""
    hashes = {record.token_hash for record in stored}
    for candidate in reversed(_ISSUED):
        if hash_reset_token(candidate) in hashes:
            return candidate
    raise AssertionError("No issued reset token matches the stored hashes.")


@pytest.fixture(autouse=True)
def _capture_issued_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Record every reset token the service mints, the way an inbox would receive it."""
    _ISSUED.clear()
    original = AccountService.request_password_reset

    async def spy(self: AccountService, **kwargs: object) -> tuple[str, str] | None:
        issued = await original(self, **kwargs)  # type: ignore[arg-type]
        if issued is not None:
            _ISSUED.append(issued[1])
        return issued

    monkeypatch.setattr(AccountService, "request_password_reset", spy)
