from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings, get_settings
from byop.models import User
from byop.security.passwords import hash_password, verify_password
from byop.security.tokens import COOKIE_NAME, create_session_token
from tests.models.factories import make_user

PASSWORD = "correct-horse-battery"
GENERIC_FAILURE = "Invalid email or password"


@pytest.fixture
async def admin(db_session: AsyncSession) -> User:
    user = await make_user(db_session, "admin@example.com")
    user.password_hash = hash_password(PASSWORD)
    await db_session.flush()
    return user


async def login(client: AsyncClient, email: str = "admin@example.com", password: str = PASSWORD):  # type: ignore[no-untyped-def]
    return await client.post("/api/auth/login", json={"email": email, "password": password})


async def test_login_sets_an_httponly_lax_session_cookie(client: AsyncClient, admin: User) -> None:
    response = await login(client)

    assert response.status_code == 200
    assert response.json() == {"id": str(admin.id), "email": "admin@example.com", "is_admin": True}
    cookie = response.headers["set-cookie"].lower()
    assert f"{COOKIE_NAME}=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" not in cookie  # PUBLIC_BASE_URL is plain http in tests
    assert "password" not in response.text.lower()


async def test_login_normalises_the_email(client: AsyncClient, admin: User) -> None:
    assert (await login(client, "  ADMIN@Example.com ")).status_code == 200


async def test_session_cookie_is_secure_behind_https(
    app: FastAPI, client: AsyncClient, admin: User
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        byop_secret_key=SecretStr("test-secret-key-0123456789abcdef"),
        public_base_url="https://podcast.example.org",
        _env_file=None,  # type: ignore[call-arg]  # pydantic-settings init kwarg
    )

    response = await login(client)

    assert "secure" in response.headers["set-cookie"].lower()


async def test_me_returns_the_signed_in_user(client: AsyncClient, admin: User) -> None:
    await login(client)

    response = await client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["email"] == "admin@example.com"


async def test_me_without_a_session_is_401(client: AsyncClient, admin: User) -> None:
    response = await client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


async def test_wrong_password_and_unknown_email_get_the_same_generic_401(
    client: AsyncClient, admin: User
) -> None:
    wrong_password = await login(client, password="nope")
    unknown_email = await login(client, email="nobody@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == {"detail": GENERIC_FAILURE}
    assert "set-cookie" not in wrong_password.headers


async def test_inactive_users_cannot_log_in(
    client: AsyncClient, admin: User, db_session: AsyncSession
) -> None:
    admin.is_active = False
    await db_session.flush()

    assert (await login(client)).status_code == 401


async def test_login_is_rate_limited_to_five_attempts_a_minute_per_ip(
    client: AsyncClient, admin: User
) -> None:
    headers = {"X-Forwarded-For": "203.0.113.7"}
    for _ in range(5):
        r = await client.post(
            "/api/auth/login", json={"email": "a@b.c", "password": "x"}, headers=headers
        )
        assert r.status_code == 401

    blocked = await client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": PASSWORD},
        headers=headers,
    )

    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["retry-after"]) <= 60
    # Another address is unaffected.
    other = await client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": PASSWORD},
        headers={"X-Forwarded-For": "198.51.100.9"},
    )
    assert other.status_code == 200


async def test_spoofed_forwarded_for_prefix_does_not_dodge_the_limit(
    client: AsyncClient, admin: User
) -> None:
    # Only the last entry (added by our proxy) identifies the caller.
    for i in range(5):
        await client.post(
            "/api/auth/login",
            json={"email": "a@b.c", "password": "x"},
            headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.50"},
        )

    r = await client.post(
        "/api/auth/login",
        json={"email": "a@b.c", "password": "x"},
        headers={"X-Forwarded-For": "10.9.9.9, 203.0.113.50"},
    )

    assert r.status_code == 429


async def test_logout_clears_the_cookie(client: AsyncClient, admin: User) -> None:
    await login(client)
    assert (await client.get("/api/auth/me")).status_code == 200

    response = await client.post("/api/auth/logout")

    assert response.status_code == 204
    assert (
        f'{COOKIE_NAME}="";' in response.headers["set-cookie"]
        or "Max-Age=0" in (response.headers["set-cookie"])
    )
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_logout_without_a_session_is_fine(client: AsyncClient) -> None:
    assert (await client.post("/api/auth/logout")).status_code == 204


async def test_tampered_token_is_rejected(client: AsyncClient, admin: User) -> None:
    client.cookies.set(COOKIE_NAME, "not.a.jwt")
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_token_signed_with_another_key_is_rejected(client: AsyncClient, admin: User) -> None:
    forged = create_session_token(admin.id, admin.password_hash, SecretStr("x" * 32), 1)
    client.cookies.set(COOKIE_NAME, forged)

    assert (await client.get("/api/auth/me")).status_code == 401


async def test_expired_token_is_rejected(client: AsyncClient, admin: User) -> None:
    secret = SecretStr("test-secret-key-0123456789abcdef")
    token = create_session_token(admin.id, admin.password_hash, secret, 1)
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["exp"] = datetime.now(UTC) - timedelta(minutes=1)
    # Re-sign with the real key but a past expiry.
    from byop.security.tokens import ALGORITHM, _signing_key

    expired = jwt.encode(claims, _signing_key(secret), algorithm=ALGORITHM)
    client.cookies.set(COOKIE_NAME, expired)

    assert (await client.get("/api/auth/me")).status_code == 401


async def test_token_for_a_deleted_user_is_rejected(
    client: AsyncClient, admin: User, db_session: AsyncSession
) -> None:
    await login(client)
    await db_session.delete(admin)
    await db_session.flush()

    assert (await client.get("/api/auth/me")).status_code == 401


async def test_password_change_updates_the_hash_and_ends_old_sessions(
    client: AsyncClient, admin: User
) -> None:
    await login(client)
    old_cookie = client.cookies.get(COOKIE_NAME)

    changed = await client.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": "a-new-password"}
    )

    assert changed.status_code == 204
    assert verify_password("a-new-password", admin.password_hash)
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, old_cookie or "")
    assert (await client.get("/api/auth/me")).status_code == 401
    client.cookies.clear()
    assert (await login(client, password=PASSWORD)).status_code == 401
    assert (await login(client, password="a-new-password")).status_code == 200


async def test_password_change_needs_the_current_password(client: AsyncClient, admin: User) -> None:
    await login(client)

    wrong = await client.post(
        "/api/auth/password", json={"current_password": "nope", "new_password": "a-new-password"}
    )
    short = await client.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": "short"}
    )

    assert wrong.status_code == 400
    assert short.status_code == 422
    assert verify_password(PASSWORD, admin.password_hash)


async def test_password_change_requires_a_session(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/password", json={"current_password": "a", "new_password": "b" * 8}
    )

    assert response.status_code == 401
