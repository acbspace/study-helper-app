"""Community: posts, comments, reactions, bookmarks, soft-deletion, and reporting."""

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


async def _post(client: AsyncClient, headers: dict[str, str], **overrides: object) -> dict:
    payload = {"title": "How do you stay consistent?", "body": "Genuinely asking.", **overrides}
    response = await client.post("/community/posts", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestPosts:
    async def test_create_and_list(self, client: AsyncClient) -> None:
        _, author = await _register(client, email="a@example.com", username="alice")
        _, reader = await _register(client, email="b@example.com", username="bob")
        created = await _post(client, author, topic="motivation", title="My best week yet")

        assert created["author"]["username"] == "alice"
        assert created["topic"] == "motivation"
        assert created["comment_count"] == 0

        listed = await client.get("/community/posts", headers=reader)
        assert [p["id"] for p in listed.json()] == [created["id"]]

    async def test_topic_filter(self, client: AsyncClient) -> None:
        _, author = await _register(client, email="a@example.com", username="alice")
        await _post(client, author, topic="wins", title="Passed my exam")
        await _post(client, author, topic="questions", title="Anki vs paper?")

        wins = await client.get("/community/posts", params={"topic": "wins"}, headers=author)
        assert [p["title"] for p in wins.json()] == ["Passed my exam"]

    async def test_invalid_topic_is_rejected(self, client: AsyncClient) -> None:
        _, author = await _register(client, email="a@example.com", username="alice")
        response = await client.post(
            "/community/posts",
            json={"topic": "spam", "title": "Buy my course", "body": "..."},
            headers=author,
        )
        assert response.status_code == 422

    async def test_soft_delete_hides_the_post(self, client: AsyncClient) -> None:
        _, author = await _register(client, email="a@example.com", username="alice")
        post = await _post(client, author)

        deleted = await client.delete(f"/community/posts/{post['id']}", headers=author)
        assert deleted.status_code == 204
        assert (await client.get("/community/posts", headers=author)).json() == []
        assert (
            await client.get(f"/community/posts/{post['id']}", headers=author)
        ).status_code == 404

    async def test_only_author_can_delete(self, client: AsyncClient) -> None:
        _, author = await _register(client, email="a@example.com", username="alice")
        _, other = await _register(client, email="b@example.com", username="bob")
        post = await _post(client, author)
        assert (
            await client.delete(f"/community/posts/{post['id']}", headers=other)
        ).status_code == 403


class TestComments:
    async def test_comment_and_count(self, client: AsyncClient) -> None:
        _, author = await _register(client, email="a@example.com", username="alice")
        _, commenter = await _register(client, email="b@example.com", username="bob")
        post = await _post(client, author)

        comment = await client.post(
            f"/community/posts/{post['id']}/comments",
            json={"body": "Schedule it like a class."},
            headers=commenter,
        )
        assert comment.status_code == 201
        assert comment.json()["author"]["username"] == "bob"

        detail = await client.get(f"/community/posts/{post['id']}", headers=author)
        assert detail.json()["post"]["comment_count"] == 1
        assert [c["body"] for c in detail.json()["comments"]] == ["Schedule it like a class."]

    async def test_deleting_a_comment_drops_the_count(self, client: AsyncClient) -> None:
        _, author = await _register(client, email="a@example.com", username="alice")
        post = await _post(client, author)
        comment = await client.post(
            f"/community/posts/{post['id']}/comments", json={"body": "Nice"}, headers=author
        )
        comment_id = comment.json()["id"]

        assert (
            await client.delete(f"/community/comments/{comment_id}", headers=author)
        ).status_code == 204
        detail = await client.get(f"/community/posts/{post['id']}", headers=author)
        assert detail.json()["post"]["comment_count"] == 0
        assert detail.json()["comments"] == []

    async def test_commenting_on_a_missing_post_is_not_found(self, client: AsyncClient) -> None:
        _, author = await _register(client, email="a@example.com", username="alice")
        response = await client.post(
            f"/community/posts/{uuid.uuid4()}/comments", json={"body": "hi"}, headers=author
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "post_not_found"


class TestReactionsAndBookmarks:
    async def test_react_is_one_per_user(self, client: AsyncClient) -> None:
        _, author = await _register(client, email="a@example.com", username="alice")
        _, reader = await _register(client, email="b@example.com", username="bob")
        post = await _post(client, author)

        await client.put(
            f"/community/posts/{post['id']}/reaction", json={"emoji": "like"}, headers=reader
        )
        # Reacting again changes the emoji rather than stacking.
        await client.put(
            f"/community/posts/{post['id']}/reaction", json={"emoji": "celebrate"}, headers=reader
        )

        detail = await client.get(f"/community/posts/{post['id']}", headers=reader)
        assert detail.json()["post"]["reaction_count"] == 1
        assert detail.json()["post"]["my_reaction"] == "celebrate"

    async def test_unreact(self, client: AsyncClient) -> None:
        _, author = await _register(client, email="a@example.com", username="alice")
        post = await _post(client, author)
        await client.put(
            f"/community/posts/{post['id']}/reaction", json={"emoji": "support"}, headers=author
        )
        await client.delete(f"/community/posts/{post['id']}/reaction", headers=author)

        detail = await client.get(f"/community/posts/{post['id']}", headers=author)
        assert detail.json()["post"]["reaction_count"] == 0
        assert detail.json()["post"]["my_reaction"] is None

    async def test_bookmark_flow(self, client: AsyncClient) -> None:
        _, author = await _register(client, email="a@example.com", username="alice")
        _, reader = await _register(client, email="b@example.com", username="bob")
        post = await _post(client, author)

        await client.put(f"/community/posts/{post['id']}/bookmark", headers=reader)
        # Bookmarking twice is idempotent.
        await client.put(f"/community/posts/{post['id']}/bookmark", headers=reader)

        marks = await client.get("/community/bookmarks", headers=reader)
        assert [p["id"] for p in marks.json()] == [post["id"]]
        assert marks.json()[0]["bookmarked"] is True

        await client.delete(f"/community/posts/{post['id']}/bookmark", headers=reader)
        assert (await client.get("/community/bookmarks", headers=reader)).json() == []


class TestReporting:
    async def test_report_a_post(self, client: AsyncClient) -> None:
        _, author = await _register(client, email="a@example.com", username="alice")
        _, reporter = await _register(client, email="b@example.com", username="bob")
        post = await _post(client, author)

        response = await client.post(
            "/reports",
            json={"subject_type": "post", "subject_id": post["id"], "reason": "Spam"},
            headers=reporter,
        )
        assert response.status_code == 201
        assert response.json()["subject_type"] == "post"

    async def test_report_a_comment(self, client: AsyncClient) -> None:
        _, author = await _register(client, email="a@example.com", username="alice")
        _, reporter = await _register(client, email="b@example.com", username="bob")
        post = await _post(client, author)
        comment = await client.post(
            f"/community/posts/{post['id']}/comments", json={"body": "rude"}, headers=author
        )

        response = await client.post(
            "/reports",
            json={
                "subject_type": "comment",
                "subject_id": comment.json()["id"],
                "reason": "Harassment",
            },
            headers=reporter,
        )
        assert response.status_code == 201


class TestAuthentication:
    async def test_endpoints_require_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/community/posts")).status_code == 401
        assert (
            await client.post("/community/posts", json={"title": "hi", "body": "there"})
        ).status_code == 401
