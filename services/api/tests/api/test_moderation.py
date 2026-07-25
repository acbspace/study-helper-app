"""The moderator review queue: admin-only access, resolution, content removal, and audit."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import AuditLog
from app.models.user import User


async def _register(
    client: AsyncClient, *, email: str, username: str
) -> tuple[str, dict[str, str]]:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "test-passphrase-9x",
            "username": username,
            "display_name": username.title(),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['tokens']['access_token']}"}


async def _make_admin(
    client: AsyncClient, db: AsyncSession, *, email: str, username: str
) -> dict[str, str]:
    user_id, headers = await _register(client, email=email, username=username)
    user = await db.get(User, uuid.UUID(user_id))
    assert user is not None
    user.is_admin = True
    await db.commit()
    return headers


async def _reported_post(client: AsyncClient) -> tuple[str, dict[str, str]]:
    """A post reported by a second user. Returns the post id and the reporter's headers."""
    _, author = await _register(client, email="author@example.com", username="author")
    _, reporter = await _register(client, email="reporter@example.com", username="reporter")
    post = await client.post(
        "/community/posts",
        json={"title": "Spammy title", "body": "Buy my thing"},
        headers=author,
    )
    post_id = post.json()["id"]
    reported = await client.post(
        "/reports",
        json={"subject_type": "post", "subject_id": post_id, "reason": "This is spam"},
        headers=reporter,
    )
    assert reported.status_code == 201
    return post_id, reporter


class TestAccess:
    async def test_non_admin_cannot_see_the_queue(self, client: AsyncClient) -> None:
        _, headers = await _register(client, email="a@example.com", username="alice")
        # A non-moderator is told "not found", not "forbidden".
        assert (await client.get("/admin/reports", headers=headers)).status_code == 404

    async def test_queue_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/admin/reports")).status_code == 401


class TestQueue:
    async def test_admin_sees_reports_with_context(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        admin = await _make_admin(client, db, email="mod@example.com", username="moderator")
        await _reported_post(client)

        response = await client.get("/admin/reports", headers=admin)
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["subject_type"] == "post"
        assert rows[0]["subject_preview"] == "Spammy title"
        assert rows[0]["reporter"]["username"] == "reporter"
        assert rows[0]["status"] == "open"

    async def test_status_filter(self, client: AsyncClient, db: AsyncSession) -> None:
        admin = await _make_admin(client, db, email="mod@example.com", username="moderator")
        await _reported_post(client)
        report_id = (await client.get("/admin/reports", headers=admin)).json()[0]["id"]
        await client.post(
            f"/admin/reports/{report_id}/resolve",
            json={"decision": "dismiss"},
            headers=admin,
        )

        assert (
            await client.get("/admin/reports", params={"status": "open"}, headers=admin)
        ).json() == []
        dismissed = await client.get(
            "/admin/reports", params={"status": "dismissed"}, headers=admin
        )
        assert len(dismissed.json()) == 1


class TestResolution:
    async def test_dismiss_keeps_the_content(self, client: AsyncClient, db: AsyncSession) -> None:
        admin = await _make_admin(client, db, email="mod@example.com", username="moderator")
        post_id, reporter = await _reported_post(client)
        report_id = (await client.get("/admin/reports", headers=admin)).json()[0]["id"]

        resolved = await client.post(
            f"/admin/reports/{report_id}/resolve",
            json={"decision": "dismiss", "note": "Looks fine."},
            headers=admin,
        )
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "dismissed"
        assert resolved.json()["resolution_note"] == "Looks fine."
        # The post is still visible.
        assert (
            await client.get(f"/community/posts/{post_id}", headers=reporter)
        ).status_code == 200

    async def test_action_with_removal_soft_deletes_and_audits(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        admin = await _make_admin(client, db, email="mod@example.com", username="moderator")
        post_id, reporter = await _reported_post(client)
        report_id = (await client.get("/admin/reports", headers=admin)).json()[0]["id"]

        resolved = await client.post(
            f"/admin/reports/{report_id}/resolve",
            json={"decision": "action", "remove_content": True, "note": "Spam removed."},
            headers=admin,
        )
        assert resolved.json()["status"] == "actioned"
        # The post is gone for everyone.
        assert (
            await client.get(f"/community/posts/{post_id}", headers=reporter)
        ).status_code == 404

        # Two audit rows: the resolution and the content removal.
        actions = set((await db.execute(select(AuditLog.action))).scalars().all())
        assert {"report.resolved", "content.removed"} <= actions

    async def test_removal_closes_sibling_reports(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        admin = await _make_admin(client, db, email="mod@example.com", username="moderator")
        post_id, _ = await _reported_post(client)
        # A second user reports the same post.
        _, other = await _register(client, email="second@example.com", username="second")
        await client.post(
            "/reports",
            json={"subject_type": "post", "subject_id": post_id, "reason": "Also spam"},
            headers=other,
        )
        assert (
            len(
                (
                    await client.get("/admin/reports", params={"status": "open"}, headers=admin)
                ).json()
            )
            == 2
        )

        report_id = (
            await client.get("/admin/reports", params={"status": "open"}, headers=admin)
        ).json()[0]["id"]
        await client.post(
            f"/admin/reports/{report_id}/resolve",
            json={"decision": "action", "remove_content": True},
            headers=admin,
        )

        # Both reports are now closed — one decision, not two.
        remaining = await db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "content.removed")
        )
        assert remaining == 1  # content removed exactly once
        assert (
            await client.get("/admin/reports", params={"status": "open"}, headers=admin)
        ).json() == []

    async def test_resolving_an_already_resolved_report_is_not_found(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        admin = await _make_admin(client, db, email="mod@example.com", username="moderator")
        await _reported_post(client)
        report_id = (await client.get("/admin/reports", headers=admin)).json()[0]["id"]
        await client.post(
            f"/admin/reports/{report_id}/resolve", json={"decision": "dismiss"}, headers=admin
        )

        again = await client.post(
            f"/admin/reports/{report_id}/resolve", json={"decision": "dismiss"}, headers=admin
        )
        assert again.status_code == 404
        assert again.json()["error"]["code"] == "report_not_found"
