"""Authentication endpoint tests."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.user import User
from tests.conftest import API, DEFAULT_PASSWORD, auth_headers, register_and_login

REGISTER_URL = f"{API}/auth/register"
LOGIN_URL = f"{API}/auth/login"
ME_URL = f"{API}/auth/me"


# --- Registration ------------------------------------------------------------


async def test_register_creates_an_account(client: AsyncClient) -> None:
    response = await client.post(
        REGISTER_URL,
        json={"email": "new@example.com", "password": DEFAULT_PASSWORD, "display_name": "New"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert body["display_name"] == "New"
    assert body["is_active"] is True
    assert uuid.UUID(body["id"])


async def test_register_never_returns_the_password_hash(client: AsyncClient) -> None:
    response = await client.post(
        REGISTER_URL, json={"email": "secret@example.com", "password": DEFAULT_PASSWORD}
    )

    assert "password_hash" not in response.text
    assert DEFAULT_PASSWORD not in response.text


async def test_register_stores_a_hash_not_the_plaintext(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post(
        REGISTER_URL, json={"email": "hashed@example.com", "password": DEFAULT_PASSWORD}
    )

    user = (
        await db_session.execute(select(User).where(User.email == "hashed@example.com"))
    ).scalar_one()
    assert user.password_hash != DEFAULT_PASSWORD
    assert user.password_hash.startswith("$argon2id$")


async def test_register_rejects_a_duplicate_email(client: AsyncClient) -> None:
    payload = {"email": "dup@example.com", "password": DEFAULT_PASSWORD}
    assert (await client.post(REGISTER_URL, json=payload)).status_code == 201

    response = await client.post(REGISTER_URL, json=payload)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_register_treats_email_case_insensitively(client: AsyncClient) -> None:
    await client.post(
        REGISTER_URL, json={"email": "Mixed@Example.com", "password": DEFAULT_PASSWORD}
    )

    response = await client.post(
        REGISTER_URL, json={"email": "mixed@example.com", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"email": "not-an-email", "password": DEFAULT_PASSWORD}, id="bad-email"),
        pytest.param({"email": "short@example.com", "password": "short"}, id="short-password"),
        pytest.param({"email": "missing@example.com"}, id="missing-password"),
        pytest.param({"password": DEFAULT_PASSWORD}, id="missing-email"),
        pytest.param(
            {"email": "long@example.com", "password": "x" * 200}, id="over-long-password"
        ),
    ],
)
async def test_register_rejects_invalid_data(client: AsyncClient, payload: dict) -> None:
    response = await client.post(REGISTER_URL, json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- Login -------------------------------------------------------------------


async def test_login_returns_a_bearer_token(client: AsyncClient) -> None:
    await client.post(
        REGISTER_URL, json={"email": "login@example.com", "password": DEFAULT_PASSWORD}
    )

    response = await client.post(
        LOGIN_URL, json={"email": "login@example.com", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] > 0


async def test_login_accepts_a_differently_cased_email(client: AsyncClient) -> None:
    await client.post(
        REGISTER_URL, json={"email": "case@example.com", "password": DEFAULT_PASSWORD}
    )

    response = await client.post(
        LOGIN_URL, json={"email": "CASE@Example.COM", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200


async def test_login_rejects_a_wrong_password(client: AsyncClient) -> None:
    await client.post(
        REGISTER_URL, json={"email": "wrong@example.com", "password": DEFAULT_PASSWORD}
    )

    response = await client.post(
        LOGIN_URL, json={"email": "wrong@example.com", "password": "definitely-not-it"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_login_does_not_reveal_whether_an_email_exists(client: AsyncClient) -> None:
    """Unknown account and wrong password must be indistinguishable."""
    await client.post(
        REGISTER_URL, json={"email": "known@example.com", "password": DEFAULT_PASSWORD}
    )

    wrong_password = await client.post(
        LOGIN_URL, json={"email": "known@example.com", "password": "not-the-password"}
    )
    unknown_email = await client.post(
        LOGIN_URL, json={"email": "nobody@example.com", "password": "not-the-password"}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"] == unknown_email.json()["error"]


async def test_login_rejects_a_deactivated_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post(
        REGISTER_URL, json={"email": "gone@example.com", "password": DEFAULT_PASSWORD}
    )
    user = (
        await db_session.execute(select(User).where(User.email == "gone@example.com"))
    ).scalar_one()
    user.is_active = False
    await db_session.commit()

    response = await client.post(
        LOGIN_URL, json={"email": "gone@example.com", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 401


async def test_login_rejects_invalid_payloads(client: AsyncClient) -> None:
    response = await client.post(LOGIN_URL, json={"email": "nope", "password": ""})

    assert response.status_code == 422


# --- /auth/me ----------------------------------------------------------------


async def test_me_returns_the_authenticated_user(client: AsyncClient, user_token: str) -> None:
    response = await client.get(ME_URL, headers=auth_headers(user_token))

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "owner@example.com"
    assert body["display_name"] == "Owner"
    assert "password_hash" not in body


async def test_me_requires_a_token(client: AsyncClient) -> None:
    response = await client.get(ME_URL)

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["request_id"]


@pytest.mark.parametrize(
    "header",
    [
        pytest.param("Bearer not-a-jwt", id="malformed"),
        pytest.param("Bearer ", id="empty-token"),
        pytest.param("Basic dXNlcjpwYXNz", id="wrong-scheme"),
    ],
)
async def test_me_rejects_bad_authorization_headers(client: AsyncClient, header: str) -> None:
    response = await client.get(ME_URL, headers={"Authorization": header})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_me_rejects_an_expired_token(client: AsyncClient, db_session: AsyncSession) -> None:
    await register_and_login(client, "expired@example.com")
    user = (
        await db_session.execute(select(User).where(User.email == "expired@example.com"))
    ).scalar_one()
    token, _ = create_access_token(user.id, expires_delta=timedelta(seconds=-30))

    response = await client.get(ME_URL, headers=auth_headers(token))

    assert response.status_code == 401
    assert "expired" in response.json()["error"]["message"].lower()


async def test_me_rejects_a_token_signed_with_another_key(client: AsyncClient) -> None:
    import jwt

    from app.core.config import settings

    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "exp": 9_999_999_999},
        # Long enough to avoid PyJWT's short-key warning; still the wrong key.
        "an-attacker-controlled-key-of-sufficient-length-to-sign",
        algorithm=settings.JWT_ALGORITHM,
    )

    response = await client.get(ME_URL, headers=auth_headers(forged))

    assert response.status_code == 401


async def test_me_rejects_a_token_for_a_deleted_user(client: AsyncClient) -> None:
    """Correctly signed, but the subject no longer exists."""
    token, _ = create_access_token(uuid.uuid4())

    response = await client.get(ME_URL, headers=auth_headers(token))

    assert response.status_code == 401


async def test_token_identifies_its_subject(client: AsyncClient, db_session: AsyncSession) -> None:
    token = await register_and_login(client, "subject@example.com")
    user = (
        await db_session.execute(select(User).where(User.email == "subject@example.com"))
    ).scalar_one()

    body = (await client.get(ME_URL, headers=auth_headers(token))).json()

    assert body["id"] == str(user.id)
