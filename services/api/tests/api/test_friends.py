"""Friendships: requests, acceptance, removal, blocking, and search.

The friendship graph is stored directionally but read undirected, and blocking is meant to
be invisible from the outside; these tests pin down both, plus the ownership boundaries.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def _register(
    client: AsyncClient,
    *,
    email: str,
    username: str,
    display_name: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Create a user through the public API; return their id and auth headers."""
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "password123",
            "username": username,
            "display_name": display_name or username.title(),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    headers = {"Authorization": f"Bearer {body['tokens']['access_token']}"}
    return body["user"]["id"], headers


class TestFriendRequests:
    async def test_request_appears_for_both_parties(self, client: AsyncClient) -> None:
        a_id, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")

        sent = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        assert sent.status_code == 201
        assert sent.json()["direction"] == "outgoing"
        assert sent.json()["status"] == "pending"
        assert sent.json()["user"]["username"] == "bob"

        outgoing = await client.get("/friends/requests", headers=a)
        assert [r["user"]["id"] for r in outgoing.json()["outgoing"]] == [b_id]
        assert outgoing.json()["incoming"] == []

        incoming = await client.get("/friends/requests", headers=b)
        assert [r["user"]["id"] for r in incoming.json()["incoming"]] == [a_id]
        assert incoming.json()["outgoing"] == []

    async def test_accept_makes_them_friends_both_ways(self, client: AsyncClient) -> None:
        a_id, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")

        sent = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        friendship_id = sent.json()["friendship_id"]

        accepted = await client.post(f"/friends/requests/{friendship_id}/accept", headers=b)
        assert accepted.status_code == 200
        assert accepted.json()["user"]["id"] == a_id

        assert [f["user"]["id"] for f in (await client.get("/friends", headers=a)).json()] == [b_id]
        assert [f["user"]["id"] for f in (await client.get("/friends", headers=b)).json()] == [a_id]
        # No longer pending for either side.
        assert (await client.get("/friends/requests", headers=a)).json()["outgoing"] == []
        assert (await client.get("/friends/requests", headers=b)).json()["incoming"] == []

    async def test_cannot_friend_yourself(
        self, client: AsyncClient, auth_headers: dict[str, str], user
    ) -> None:
        response = await client.post(
            "/friends/requests", json={"user_id": str(user.id)}, headers=auth_headers
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "cannot_friend_self"

    async def test_duplicate_request_is_rejected(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, _ = await _register(client, email="b@example.com", username="bob")

        await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        again = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "friend_request_exists"

    async def test_mutual_requests_auto_accept(self, client: AsyncClient) -> None:
        """If they already asked you, sending them a request just accepts theirs."""
        a_id, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")

        await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        # B sends back to A instead of accepting.
        response = await client.post("/friends/requests", json={"user_id": a_id}, headers=b)
        assert response.status_code == 201
        assert response.json()["status"] == "accepted"

        assert [f["user"]["id"] for f in (await client.get("/friends", headers=a)).json()] == [b_id]
        assert [f["user"]["id"] for f in (await client.get("/friends", headers=b)).json()] == [a_id]

    async def test_already_friends_request_is_rejected(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        sent = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        await client.post(f"/friends/requests/{sent.json()['friendship_id']}/accept", headers=b)

        response = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "already_friends"

    async def test_declined_request_can_be_resent(self, client: AsyncClient) -> None:
        a_id, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        sent = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        declined = await client.post(
            f"/friends/requests/{sent.json()['friendship_id']}/decline", headers=b
        )
        assert declined.status_code == 204
        # A decline is not visible as a pending request to either party.
        assert (await client.get("/friends/requests", headers=b)).json()["incoming"] == []

        resent = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        assert resent.status_code == 201
        incoming = (await client.get("/friends/requests", headers=b)).json()["incoming"]
        assert [r["user"]["id"] for r in incoming] == [a_id]

    async def test_request_by_username(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, _ = await _register(client, email="b@example.com", username="bob")

        sent = await client.post("/friends/requests", json={"username": "bob"}, headers=a)
        assert sent.status_code == 201
        assert sent.json()["user"]["id"] == b_id

    async def test_unknown_username_is_not_found(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/friends/requests", json={"username": "ghost"}, headers=auth_headers
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "user_not_found"

    async def test_request_requires_exactly_one_target(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        neither = await client.post("/friends/requests", json={}, headers=auth_headers)
        assert neither.status_code == 422
        both = await client.post(
            "/friends/requests",
            json={"user_id": str(uuid.uuid4()), "username": "bob"},
            headers=auth_headers,
        )
        assert both.status_code == 422


class TestRemoval:
    async def test_cancel_outgoing_request(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        sent = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)

        cancelled = await client.delete(f"/friends/{sent.json()['friendship_id']}", headers=a)
        assert cancelled.status_code == 204
        assert (await client.get("/friends/requests", headers=b)).json()["incoming"] == []

    async def test_unfriend_removes_from_both_lists(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        sent = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        fid = sent.json()["friendship_id"]
        await client.post(f"/friends/requests/{fid}/accept", headers=b)

        # Either party can remove the friendship.
        removed = await client.delete(f"/friends/{fid}", headers=b)
        assert removed.status_code == 204
        assert (await client.get("/friends", headers=a)).json() == []
        assert (await client.get("/friends", headers=b)).json() == []

    async def test_accepting_a_request_not_addressed_to_you_is_not_found(
        self, client: AsyncClient
    ) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, _ = await _register(client, email="b@example.com", username="bob")
        _, c = await _register(client, email="c@example.com", username="carol")
        sent = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)

        # Carol is neither the requester nor the addressee.
        response = await client.post(
            f"/friends/requests/{sent.json()['friendship_id']}/accept", headers=c
        )
        assert response.status_code == 404


class TestBlocking:
    async def test_block_hides_and_severs(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        sent = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        await client.post(f"/friends/requests/{sent.json()['friendship_id']}/accept", headers=b)

        blocked = await client.post("/friends/blocks", json={"user_id": b_id}, headers=a)
        assert blocked.status_code == 204

        # The friendship is gone for both.
        assert (await client.get("/friends", headers=a)).json() == []
        assert (await client.get("/friends", headers=b)).json() == []
        # Bob appears on Alice's block list.
        assert [u["id"] for u in (await client.get("/friends/blocked", headers=a)).json()] == [b_id]

    async def test_blocked_user_cannot_send_request(self, client: AsyncClient) -> None:
        a_id, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        await client.post("/friends/blocks", json={"user_id": b_id}, headers=a)

        # Bob cannot tell he was blocked: Alice simply "doesn't exist" to him.
        response = await client.post("/friends/requests", json={"user_id": a_id}, headers=b)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "user_not_found"

    async def test_blocker_must_unblock_before_requesting(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, _ = await _register(client, email="b@example.com", username="bob")
        await client.post("/friends/blocks", json={"user_id": b_id}, headers=a)

        response = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "user_blocked"

    async def test_unblock_restores_discoverability(self, client: AsyncClient) -> None:
        a_id, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        await client.post("/friends/blocks", json={"user_id": b_id}, headers=a)

        unblocked = await client.delete(f"/friends/blocks/{b_id}", headers=a)
        assert unblocked.status_code == 204
        assert (await client.get("/friends/blocked", headers=a)).json() == []

        # Bob can now find Alice again and send a request.
        found = await client.get("/users/search", params={"q": "alice"}, headers=b)
        assert [r["user"]["id"] for r in found.json()] == [a_id]
        assert (
            await client.post("/friends/requests", json={"user_id": a_id}, headers=b)
        ).status_code == 201


class TestSearch:
    async def test_search_reports_relationship_state(self, client: AsyncClient) -> None:
        a_id, a = await _register(client, email="a@example.com", username="alice")
        b_id, _ = await _register(client, email="b@example.com", username="bob")
        c_id, c = await _register(client, email="c@example.com", username="carol")

        # Alice sends to Bob; Carol sends to Alice.
        await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        await client.post("/friends/requests", json={"user_id": a_id}, headers=c)

        by_id = {
            r["user"]["id"]: r
            for r in (await client.get("/users/search", params={"q": "o"}, headers=a)).json()
        }
        # "o" matches bob and carol (display names Bob / Carol), not Alice (excluded as self).
        assert a_id not in by_id
        assert by_id[b_id]["relationship"] == "request_sent"
        assert by_id[c_id]["relationship"] == "request_received"

    async def test_search_marks_friends(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        sent = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        await client.post(f"/friends/requests/{sent.json()['friendship_id']}/accept", headers=b)

        results = await client.get("/users/search", params={"q": "bob"}, headers=a)
        assert results.json()[0]["relationship"] == "friends"
        assert results.json()[0]["friendship_id"] == sent.json()["friendship_id"]

    async def test_search_hides_users_who_blocked_you(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        await client.post("/friends/blocks", json={"user_id": b_id}, headers=a)

        # Bob searching for Alice finds nothing; Alice searching for Bob sees him as blocked.
        assert (await client.get("/users/search", params={"q": "alice"}, headers=b)).json() == []
        alice_view = await client.get("/users/search", params={"q": "bob"}, headers=a)
        assert alice_view.json()[0]["relationship"] == "blocked"

    async def test_search_excludes_self(
        self, client: AsyncClient, auth_headers: dict[str, str], user
    ) -> None:
        results = await client.get(
            "/users/search", params={"q": user.profile.username}, headers=auth_headers
        )
        assert all(r["user"]["id"] != str(user.id) for r in results.json())


class TestAuthentication:
    async def test_endpoints_require_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/friends")).status_code == 401
        assert (await client.get("/friends/requests")).status_code == 401
        assert (await client.get("/users/search", params={"q": "x"})).status_code == 401
        assert (await client.post("/friends/requests", json={"username": "x"})).status_code == 401
