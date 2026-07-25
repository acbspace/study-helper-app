"""Live presence: heartbeats in, privacy-filtered snapshots out.

Presence runs on the in-memory store here (the tests have no Redis), which is exactly the
single-instance fallback path — so these tests exercise the real service against a real
store, only without the network hop.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def _register(
    client: AsyncClient, *, email: str, username: str
) -> tuple[str, dict[str, str]]:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "password123",
            "username": username,
            "display_name": username.title(),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['tokens']['access_token']}"}


async def _befriend(
    client: AsyncClient,
    a_headers: dict[str, str],
    b_id: str,
    b_headers: dict[str, str],
) -> None:
    sent = await client.post("/friends/requests", json={"user_id": b_id}, headers=a_headers)
    await client.post(f"/friends/requests/{sent.json()['friendship_id']}/accept", headers=b_headers)


async def _heartbeat(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    state: str = "studying",
    subject_id: str | None = None,
) -> None:
    body: dict[str, object] = {"state": state}
    if subject_id is not None:
        body["subject_id"] = subject_id
    response = await client.put("/presence/heartbeat", json=body, headers=headers)
    assert response.status_code == 204, response.text


class TestFriendPresence:
    async def test_friend_sees_my_presence(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        await _befriend(client, a, b_id, b)

        subject = str(uuid.uuid4())
        await _heartbeat(client, b, state="studying", subject_id=subject)

        seen = await client.get("/presence/friends", headers=a)
        assert seen.status_code == 200
        rows = seen.json()
        assert [r["user"]["id"] for r in rows] == [b_id]
        assert rows[0]["state"] == "studying"
        assert rows[0]["subject_id"] == subject

    async def test_non_friends_are_invisible(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        _, b = await _register(client, email="b@example.com", username="bob")
        await _heartbeat(client, b)  # not friends

        seen = await client.get("/presence/friends", headers=a)
        assert seen.json() == []

    async def test_going_offline_clears_presence(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        await _befriend(client, a, b_id, b)
        await _heartbeat(client, b)
        assert len((await client.get("/presence/friends", headers=a)).json()) == 1

        offline = await client.delete("/presence", headers=b)
        assert offline.status_code == 204
        assert (await client.get("/presence/friends", headers=a)).json() == []

    async def test_hidden_presence_is_never_stored(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        await _befriend(client, a, b_id, b)
        await client.patch("/me/settings", json={"privacy_show_presence": False}, headers=b)

        await _heartbeat(client, b, state="studying", subject_id=str(uuid.uuid4()))
        assert (await client.get("/presence/friends", headers=a)).json() == []

    async def test_hidden_subject_is_omitted(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        await _befriend(client, a, b_id, b)
        await client.patch("/me/settings", json={"privacy_show_subject": False}, headers=b)

        await _heartbeat(client, b, state="studying", subject_id=str(uuid.uuid4()))
        rows = (await client.get("/presence/friends", headers=a)).json()
        assert rows[0]["user"]["id"] == b_id
        assert rows[0]["subject_id"] is None


class TestGroupPresence:
    async def _make_group(
        self, client: AsyncClient, owner: dict[str, str], **overrides: object
    ) -> str:
        payload = {"name": "Study Room", "visibility": "public", **overrides}
        response = await client.post("/groups", json=payload, headers=owner)
        assert response.status_code == 201, response.text
        return response.json()["group"]["id"]

    async def test_members_see_each_other(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        member_id, member = await _register(client, email="m@example.com", username="member")
        gid = await self._make_group(client, owner)
        await client.post(f"/groups/{gid}/join", headers=member)
        await _heartbeat(client, member, state="studying")

        seen = await client.get(f"/presence/groups/{gid}", headers=owner)
        assert [r["user"]["id"] for r in seen.json()] == [member_id]

    async def test_group_presence_excludes_self(self, client: AsyncClient) -> None:
        owner_id, owner = await _register(client, email="o@example.com", username="owner")
        gid = await self._make_group(client, owner)
        await _heartbeat(client, owner)

        seen = await client.get(f"/presence/groups/{gid}", headers=owner)
        assert all(r["user"]["id"] != owner_id for r in seen.json())

    async def test_private_group_hidden_from_non_members(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, stranger = await _register(client, email="s@example.com", username="stranger")
        gid = await self._make_group(client, owner, visibility="private")

        assert (await client.get(f"/presence/groups/{gid}", headers=stranger)).status_code == 404

    async def test_public_group_visible_to_non_members(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        member_id, member = await _register(client, email="m@example.com", username="member")
        _, stranger = await _register(client, email="s@example.com", username="stranger")
        gid = await self._make_group(client, owner)
        await client.post(f"/groups/{gid}/join", headers=member)
        await _heartbeat(client, member)

        seen = await client.get(f"/presence/groups/{gid}", headers=stranger)
        assert seen.status_code == 200
        assert [r["user"]["id"] for r in seen.json()] == [member_id]

    async def test_blocked_members_are_hidden(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        member_id, member = await _register(client, email="m@example.com", username="member")
        gid = await self._make_group(client, owner)
        await client.post(f"/groups/{gid}/join", headers=member)
        await _heartbeat(client, member)
        await _heartbeat(client, owner)

        # The owner blocks the member; neither should see the other's presence.
        await client.post("/friends/blocks", json={"user_id": member_id}, headers=owner)
        assert (await client.get(f"/presence/groups/{gid}", headers=owner)).json() == []
        assert (await client.get(f"/presence/groups/{gid}", headers=member)).json() == []


class TestAuthentication:
    async def test_endpoints_require_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/presence/friends")).status_code == 401
        assert (
            await client.put("/presence/heartbeat", json={"state": "studying"})
        ).status_code == 401
        assert (await client.get(f"/presence/groups/{uuid.uuid4()}")).status_code == 401
