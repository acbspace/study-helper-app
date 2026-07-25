"""Moderation reports, the notification inbox, and push-token registration."""

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


class TestReports:
    async def test_report_a_user(self, client: AsyncClient) -> None:
        _, reporter = await _register(client, email="a@example.com", username="alice")
        target_id, _ = await _register(client, email="b@example.com", username="bob")

        response = await client.post(
            "/reports",
            json={"subject_type": "user", "subject_id": target_id, "reason": "Spamming me"},
            headers=reporter,
        )
        assert response.status_code == 201
        assert response.json()["status"] == "open"
        assert response.json()["subject_id"] == target_id

        listed = await client.get("/reports", headers=reporter)
        assert len(listed.json()) == 1

    async def test_duplicate_open_report_is_rejected(self, client: AsyncClient) -> None:
        _, reporter = await _register(client, email="a@example.com", username="alice")
        target_id, _ = await _register(client, email="b@example.com", username="bob")
        body = {"subject_type": "user", "subject_id": target_id, "reason": "Spamming me"}
        await client.post("/reports", json=body, headers=reporter)

        again = await client.post("/reports", json=body, headers=reporter)
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "report_exists"

    async def test_cannot_report_yourself(self, client: AsyncClient) -> None:
        me_id, me = await _register(client, email="a@example.com", username="alice")
        response = await client.post(
            "/reports",
            json={"subject_type": "user", "subject_id": me_id, "reason": "Testing"},
            headers=me,
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "cannot_report_self"

    async def test_reporting_an_unknown_subject_is_not_found(self, client: AsyncClient) -> None:
        _, reporter = await _register(client, email="a@example.com", username="alice")
        response = await client.post(
            "/reports",
            json={"subject_type": "group", "subject_id": str(uuid.uuid4()), "reason": "Bad"},
            headers=reporter,
        )
        assert response.status_code == 404

    async def test_report_a_group(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        _, reporter = await _register(client, email="a@example.com", username="alice")
        created = await client.post("/groups", json={"name": "Rowdy Room"}, headers=owner)
        gid = created.json()["group"]["id"]

        response = await client.post(
            "/reports",
            json={"subject_type": "group", "subject_id": gid, "reason": "Off topic"},
            headers=reporter,
        )
        assert response.status_code == 201

    async def test_reason_is_required(self, client: AsyncClient) -> None:
        _, reporter = await _register(client, email="a@example.com", username="alice")
        target_id, _ = await _register(client, email="b@example.com", username="bob")
        response = await client.post(
            "/reports",
            json={"subject_type": "user", "subject_id": target_id, "reason": "x"},
            headers=reporter,
        )
        assert response.status_code == 422


class TestNotifications:
    async def test_friend_request_notifies_the_addressee(self, client: AsyncClient) -> None:
        a_id, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        await client.post("/friends/requests", json={"user_id": b_id}, headers=a)

        inbox = await client.get("/notifications", headers=b)
        assert len(inbox.json()) == 1
        assert inbox.json()[0]["kind"] == "friend_request"
        assert inbox.json()[0]["data"]["user_id"] == a_id
        assert inbox.json()[0]["read_at"] is None
        # The sender has nothing waiting.
        assert (await client.get("/notifications", headers=a)).json() == []

    async def test_accepting_notifies_the_requester(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        sent = await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        await client.post(f"/friends/requests/{sent.json()['friendship_id']}/accept", headers=b)

        inbox = await client.get("/notifications", headers=a)
        assert [n["title"] for n in inbox.json()] == ["Friend request accepted"]

    async def test_group_invitation_notifies_the_invitee(self, client: AsyncClient) -> None:
        _, owner = await _register(client, email="o@example.com", username="owner")
        invitee_id, invitee = await _register(client, email="i@example.com", username="invitee")
        created = await client.post(
            "/groups", json={"name": "Deep Work", "visibility": "private"}, headers=owner
        )
        gid = created.json()["group"]["id"]
        await client.post(f"/groups/{gid}/invitations", json={"user_id": invitee_id}, headers=owner)

        inbox = await client.get("/notifications", headers=invitee)
        assert inbox.json()[0]["kind"] == "group_invite"
        assert inbox.json()[0]["data"]["group_id"] == gid

    async def test_unread_count_and_marking_read(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        await client.post("/friends/requests", json={"user_id": b_id}, headers=a)

        assert (await client.get("/notifications/unread-count", headers=b)).json()["unread"] == 1

        notification_id = (await client.get("/notifications", headers=b)).json()[0]["id"]
        read = await client.post(f"/notifications/{notification_id}/read", headers=b)
        assert read.status_code == 200
        assert read.json()["read_at"] is not None
        assert (await client.get("/notifications/unread-count", headers=b)).json()["unread"] == 0

    async def test_mark_all_read(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        _, c = await _register(client, email="c@example.com", username="carol")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        await client.post("/friends/requests", json={"user_id": b_id}, headers=c)
        assert (await client.get("/notifications/unread-count", headers=b)).json()["unread"] == 2

        assert (await client.post("/notifications/read-all", headers=b)).status_code == 204
        assert (await client.get("/notifications/unread-count", headers=b)).json()["unread"] == 0

    async def test_unread_only_filter(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        notification_id = (await client.get("/notifications", headers=b)).json()[0]["id"]
        await client.post(f"/notifications/{notification_id}/read", headers=b)

        unread = await client.get("/notifications", params={"unread_only": True}, headers=b)
        assert unread.json() == []

    async def test_cannot_read_someone_elses_notification(self, client: AsyncClient) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        await client.post("/friends/requests", json={"user_id": b_id}, headers=a)
        notification_id = (await client.get("/notifications", headers=b)).json()[0]["id"]

        response = await client.post(f"/notifications/{notification_id}/read", headers=a)
        assert response.status_code == 404


class TestPushToken:
    async def test_registering_requires_a_device_header(self, client: AsyncClient) -> None:
        _, headers = await _register(client, email="a@example.com", username="alice")
        response = await client.put(
            "/me/push-token", json={"token": "ExponentPushToken[abc]"}, headers=headers
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "device_required"

    async def test_token_is_stored_for_the_device(self, client: AsyncClient) -> None:
        _, headers = await _register(client, email="a@example.com", username="alice")
        response = await client.put(
            "/me/push-token",
            json={"token": "ExponentPushToken[abc]", "platform": "ios"},
            headers={**headers, "X-Device-Id": "device-1"},
        )
        assert response.status_code == 204


class TestAuthentication:
    async def test_endpoints_require_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/notifications")).status_code == 401
        assert (await client.get("/notifications/unread-count")).status_code == 401
        assert (await client.get("/reports")).status_code == 401
