"""Study groups: lifecycle, membership, roles, visibility, and invitations.

The subtle parts pinned here: role rank governs who can manage whom, visibility governs who
can even see a group, capacity is enforced at join/accept time, and the owner cannot simply
walk away from a group that still has members.
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


async def _create_group(client: AsyncClient, headers: dict[str, str], **overrides: object) -> dict:
    payload = {"name": "Focus Club", "visibility": "public", **overrides}
    response = await client.post("/groups", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestGroupLifecycle:
    async def test_create_makes_owner_a_member(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        detail = await _create_group(client, owner, name="Algorithms Guild")

        assert detail["group"]["name"] == "Algorithms Guild"
        assert detail["group"]["member_count"] == 1
        assert detail["group"]["my_role"] == "owner"
        assert detail["invite_code"]  # the owner can see the code
        assert [m["role"] for m in detail["members"]] == ["owner"]

    async def test_list_mine_returns_joined_groups(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        await _create_group(client, owner, name="Group A")
        await _create_group(client, owner, name="Group B")

        mine = await client.get("/groups/mine", headers=owner)
        assert {g["name"] for g in mine.json()} == {"Group A", "Group B"}

    async def test_update_by_owner(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        detail = await _create_group(client, owner)
        gid = detail["group"]["id"]

        updated = await client.patch(
            f"/groups/{gid}", json={"description": "Deep work, together."}, headers=owner
        )
        assert updated.status_code == 200
        assert updated.json()["group"]["description"] == "Deep work, together."

    async def test_shrinking_capacity_below_members_is_rejected(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, m1 = await _register(client, email="a@example.com", username="alice")
        _, m2 = await _register(client, email="b@example.com", username="bob")
        detail = await _create_group(client, owner, max_members=10)
        gid = detail["group"]["id"]
        await client.post(f"/groups/{gid}/join", headers=m1)
        await client.post(f"/groups/{gid}/join", headers=m2)  # now 3 members

        response = await client.patch(f"/groups/{gid}", json={"max_members": 2}, headers=owner)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "group_full"

    async def test_delete_is_owner_only(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, member = await _register(client, email="m@example.com", username="member")
        detail = await _create_group(client, owner)
        gid = detail["group"]["id"]
        await client.post(f"/groups/{gid}/join", headers=member)

        assert (await client.delete(f"/groups/{gid}", headers=member)).status_code == 403
        assert (await client.delete(f"/groups/{gid}", headers=owner)).status_code == 204
        # The group is gone for everyone.
        assert (await client.get(f"/groups/{gid}", headers=owner)).status_code == 404
        assert (await client.get("/groups/mine", headers=member)).json() == []

    async def test_invalid_visibility_is_rejected(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        response = await client.post(
            "/groups", json={"name": "X", "visibility": "secret"}, headers=owner
        )
        assert response.status_code == 422


class TestVisibility:
    async def test_public_group_is_visible_to_anyone(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, other = await _register(client, email="x@example.com", username="stranger")
        gid = (await _create_group(client, owner))["group"]["id"]

        detail = await client.get(f"/groups/{gid}", headers=other)
        assert detail.status_code == 200
        assert detail.json()["group"]["my_role"] is None
        # A non-manager never sees the invite code.
        assert detail.json()["invite_code"] is None

    async def test_private_group_is_hidden_from_non_members(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, other = await _register(client, email="x@example.com", username="stranger")
        gid = (await _create_group(client, owner, visibility="private"))["group"]["id"]

        assert (await client.get(f"/groups/{gid}", headers=other)).status_code == 404

    async def test_member_does_not_see_invite_code(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, member = await _register(client, email="m@example.com", username="member")
        gid = (await _create_group(client, owner))["group"]["id"]
        await client.post(f"/groups/{gid}/join", headers=member)

        detail = await client.get(f"/groups/{gid}", headers=member)
        assert detail.json()["group"]["my_role"] == "member"
        assert detail.json()["invite_code"] is None


class TestJoining:
    async def test_join_public_group(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, member = await _register(client, email="m@example.com", username="member")
        gid = (await _create_group(client, owner))["group"]["id"]

        joined = await client.post(f"/groups/{gid}/join", headers=member)
        assert joined.status_code == 200
        assert joined.json()["group"]["member_count"] == 2
        assert joined.json()["group"]["my_role"] == "member"

    async def test_double_join_is_rejected(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, member = await _register(client, email="m@example.com", username="member")
        gid = (await _create_group(client, owner))["group"]["id"]
        await client.post(f"/groups/{gid}/join", headers=member)

        again = await client.post(f"/groups/{gid}/join", headers=member)
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "already_group_member"

    async def test_full_group_rejects_new_members(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, m1 = await _register(client, email="a@example.com", username="alice")
        _, m2 = await _register(client, email="b@example.com", username="bob")
        gid = (await _create_group(client, owner, max_members=2))["group"]["id"]
        assert (await client.post(f"/groups/{gid}/join", headers=m1)).status_code == 200

        full = await client.post(f"/groups/{gid}/join", headers=m2)
        assert full.status_code == 409
        assert full.json()["error"]["code"] == "group_full"

    async def test_join_by_invite_code(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, member = await _register(client, email="m@example.com", username="member")
        detail = await _create_group(client, owner, visibility="invite")
        code = detail["invite_code"]

        joined = await client.post("/groups/join", json={"invite_code": code}, headers=member)
        assert joined.status_code == 200
        assert joined.json()["group"]["my_role"] == "member"

    async def test_wrong_code_is_rejected(self, client: AsyncClient) -> None:
        _, member = await _register(client, email="m@example.com", username="member")
        response = await client.post(
            "/groups/join", json={"invite_code": "NOPENOPE"}, headers=member
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "invalid_invite_code"

    async def test_private_group_code_is_not_a_back_door(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, member = await _register(client, email="m@example.com", username="member")
        detail = await _create_group(client, owner, visibility="private")
        code = detail["invite_code"]

        response = await client.post("/groups/join", json={"invite_code": code}, headers=member)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "invalid_invite_code"

    async def test_join_non_public_by_id_is_hidden(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, member = await _register(client, email="m@example.com", username="member")
        gid = (await _create_group(client, owner, visibility="invite"))["group"]["id"]

        response = await client.post(f"/groups/{gid}/join", headers=member)
        assert response.status_code == 404


class TestLeaving:
    async def test_member_can_leave(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, member = await _register(client, email="m@example.com", username="member")
        gid = (await _create_group(client, owner))["group"]["id"]
        await client.post(f"/groups/{gid}/join", headers=member)

        left = await client.post(f"/groups/{gid}/leave", headers=member)
        assert left.status_code == 204
        assert (await client.get("/groups/mine", headers=member)).json() == []
        assert (await client.get(f"/groups/{gid}", headers=owner)).json()["group"][
            "member_count"
        ] == 1

    async def test_owner_cannot_leave_with_members(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, member = await _register(client, email="m@example.com", username="member")
        gid = (await _create_group(client, owner))["group"]["id"]
        await client.post(f"/groups/{gid}/join", headers=member)

        response = await client.post(f"/groups/{gid}/leave", headers=owner)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "owner_cannot_leave"

    async def test_sole_owner_leaving_retires_the_group(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        gid = (await _create_group(client, owner))["group"]["id"]

        left = await client.post(f"/groups/{gid}/leave", headers=owner)
        assert left.status_code == 204
        assert (await client.get(f"/groups/{gid}", headers=owner)).status_code == 404


class TestRolesAndModeration:
    async def test_owner_promotes_and_moderator_can_kick(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        mod_id, mod = await _register(client, email="mod@example.com", username="moddy")
        member_id, member = await _register(client, email="m@example.com", username="member")
        gid = (await _create_group(client, owner))["group"]["id"]
        await client.post(f"/groups/{gid}/join", headers=mod)
        await client.post(f"/groups/{gid}/join", headers=member)

        promoted = await client.patch(
            f"/groups/{gid}/members/{mod_id}", json={"role": "moderator"}, headers=owner
        )
        assert promoted.status_code == 200
        assert promoted.json()["role"] == "moderator"

        # The moderator can now remove a plain member.
        kicked = await client.delete(f"/groups/{gid}/members/{member_id}", headers=mod)
        assert kicked.status_code == 204

    async def test_moderator_cannot_remove_owner(self, client: AsyncClient) -> None:
        owner_id, owner = await _register(client, email="o@example.com", username="owner")
        mod_id, mod = await _register(client, email="mod@example.com", username="moddy")
        gid = (await _create_group(client, owner))["group"]["id"]
        await client.post(f"/groups/{gid}/join", headers=mod)
        await client.patch(
            f"/groups/{gid}/members/{mod_id}", json={"role": "moderator"}, headers=owner
        )

        response = await client.delete(f"/groups/{gid}/members/{owner_id}", headers=mod)
        assert response.status_code == 403

    async def test_only_owner_changes_roles(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        m1_id, _ = await _register(client, email="a@example.com", username="alice")
        _, m2 = await _register(client, email="b@example.com", username="bob")
        gid = (await _create_group(client, owner))["group"]["id"]
        await client.post(f"/groups/{gid}/join", headers=m2)

        # A plain member cannot promote anyone.
        response = await client.patch(
            f"/groups/{gid}/members/{m1_id}", json={"role": "moderator"}, headers=m2
        )
        assert response.status_code in (403, 404)

    async def test_cannot_remove_yourself(self, client: AsyncClient) -> None:
        owner_id, owner = await _register(client, email="o@example.com", username="owner")
        gid = (await _create_group(client, owner))["group"]["id"]

        response = await client.delete(f"/groups/{gid}/members/{owner_id}", headers=owner)
        assert response.status_code == 403


class TestInvitations:
    async def test_invite_accept_flow(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        invitee_id, invitee = await _register(client, email="i@example.com", username="invitee")
        gid = (await _create_group(client, owner, visibility="private"))["group"]["id"]

        invited = await client.post(
            f"/groups/{gid}/invitations", json={"user_id": invitee_id}, headers=owner
        )
        assert invited.status_code == 201
        assert invited.json()["group"]["id"] == gid

        pending = await client.get("/groups/invitations", headers=invitee)
        assert [inv["id"] for inv in pending.json()] == [invited.json()["id"]]

        accepted = await client.post(
            f"/groups/invitations/{invited.json()['id']}/accept", headers=invitee
        )
        assert accepted.status_code == 200
        assert accepted.json()["group"]["my_role"] == "member"
        # The invitation is consumed.
        assert (await client.get("/groups/invitations", headers=invitee)).json() == []

    async def test_decline_invitation(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        invitee_id, invitee = await _register(client, email="i@example.com", username="invitee")
        gid = (await _create_group(client, owner, visibility="private"))["group"]["id"]
        invited = await client.post(
            f"/groups/{gid}/invitations", json={"user_id": invitee_id}, headers=owner
        )

        declined = await client.post(
            f"/groups/invitations/{invited.json()['id']}/decline", headers=invitee
        )
        assert declined.status_code == 204
        assert (await client.get(f"/groups/{gid}", headers=owner)).json()["group"][
            "member_count"
        ] == 1

    async def test_duplicate_invitation_is_rejected(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        invitee_id, _ = await _register(client, email="i@example.com", username="invitee")
        gid = (await _create_group(client, owner))["group"]["id"]
        await client.post(f"/groups/{gid}/invitations", json={"user_id": invitee_id}, headers=owner)

        again = await client.post(
            f"/groups/{gid}/invitations", json={"user_id": invitee_id}, headers=owner
        )
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "invitation_exists"

    async def test_inviting_an_existing_member_is_rejected(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        member_id, member = await _register(client, email="m@example.com", username="member")
        gid = (await _create_group(client, owner))["group"]["id"]
        await client.post(f"/groups/{gid}/join", headers=member)

        response = await client.post(
            f"/groups/{gid}/invitations", json={"user_id": member_id}, headers=owner
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "already_group_member"

    async def test_non_manager_cannot_invite(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, member = await _register(client, email="m@example.com", username="member")
        target_id, _ = await _register(client, email="t@example.com", username="target")
        gid = (await _create_group(client, owner))["group"]["id"]
        await client.post(f"/groups/{gid}/join", headers=member)

        response = await client.post(
            f"/groups/{gid}/invitations", json={"user_id": target_id}, headers=member
        )
        assert response.status_code == 403

    async def test_accept_full_group_is_rejected(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        u1_id, u1 = await _register(client, email="a@example.com", username="alice")
        u2_id, u2 = await _register(client, email="b@example.com", username="bob")
        gid = (await _create_group(client, owner, visibility="private", max_members=2))["group"][
            "id"
        ]
        inv1 = await client.post(
            f"/groups/{gid}/invitations", json={"user_id": u1_id}, headers=owner
        )
        inv2 = await client.post(
            f"/groups/{gid}/invitations", json={"user_id": u2_id}, headers=owner
        )

        assert (
            await client.post(f"/groups/invitations/{inv1.json()['id']}/accept", headers=u1)
        ).status_code == 200
        full = await client.post(f"/groups/invitations/{inv2.json()['id']}/accept", headers=u2)
        assert full.status_code == 409
        assert full.json()["error"]["code"] == "group_full"

    async def test_cannot_accept_someone_elses_invitation(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        invitee_id, _ = await _register(client, email="i@example.com", username="invitee")
        _, stranger = await _register(client, email="s@example.com", username="stranger")
        gid = (await _create_group(client, owner, visibility="private"))["group"]["id"]
        invited = await client.post(
            f"/groups/{gid}/invitations", json={"user_id": invitee_id}, headers=owner
        )

        response = await client.post(
            f"/groups/invitations/{invited.json()['id']}/accept", headers=stranger
        )
        assert response.status_code == 404


class TestDiscovery:
    async def test_discover_finds_public_and_marks_membership(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, seeker = await _register(client, email="s@example.com", username="seeker")
        await _create_group(client, owner, name="Chemistry Crew", visibility="public")
        await _create_group(client, owner, name="Secret Society", visibility="private")

        found = await client.get("/groups/discover", params={"q": "chemistry"}, headers=seeker)
        names = {g["name"] for g in found.json()}
        assert "Chemistry Crew" in names
        assert "Secret Society" not in names

    async def test_discover_shows_my_role_for_joined_groups(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        gid = (await _create_group(client, owner, name="My Own Group"))["group"]["id"]

        found = await client.get("/groups/discover", params={"q": "My Own"}, headers=owner)
        mine = next(g for g in found.json() if g["id"] == gid)
        assert mine["my_role"] == "owner"


class TestAuthentication:
    async def test_endpoints_require_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/groups/mine")).status_code == 401
        assert (await client.get("/groups/discover")).status_code == 401
        assert (await client.post("/groups", json={"name": "X"})).status_code == 401
        assert (await client.get(f"/groups/{uuid.uuid4()}")).status_code == 401
