import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.core.security import create_access_token
from app.models import User
from app.models.enums import UserRole
from tests.fakes import FastPasswordHasher, InMemoryUserRepository


async def _register(client: AsyncClient, email: str, username: str) -> dict[str, object]:
    response = await client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "password123"},
    )
    assert response.status_code == 201
    body: dict[str, object] = response.json()
    return body


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed(
    store: InMemoryUserRepository,
    hasher: FastPasswordHasher,
    *,
    email: str,
    username: str,
    role: UserRole,
    is_active: bool = True,
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        username=username,
        hashed_password=hasher.hash("password123"),
        role=role,
        is_active=is_active,
    )
    await store.add(user)
    return user


@pytest.mark.asyncio
async def test_register_login_and_me(client: AsyncClient) -> None:
    created = await _register(client, "User@Example.com", "Nick")
    user = created["user"]
    assert isinstance(user, dict)
    assert user["email"] == "user@example.com"
    assert user["username"] == "Nick"
    assert user["role"] == "user"
    assert "hashed_password" not in created
    assert "hashed_password" not in user

    login = await client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "password123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = await client.get("/auth/me", headers=_bearer(token))
    assert me.status_code == 200
    assert me.json()["username"] == "Nick"


@pytest.mark.asyncio
async def test_register_rejects_duplicates_and_role_escalation(client: AsyncClient) -> None:
    await _register(client, "user@example.com", "nick")

    duplicate_email = await client.post(
        "/auth/register",
        json={"email": "USER@example.com", "username": "other", "password": "password123"},
    )
    assert duplicate_email.status_code == 409
    assert duplicate_email.json()["detail"] == "Email already registered"

    duplicate_username = await client.post(
        "/auth/register",
        json={"email": "second@example.com", "username": "NICK", "password": "password123"},
    )
    assert duplicate_username.status_code == 409
    assert duplicate_username.json()["detail"] == "Username already registered"

    escalated = await client.post(
        "/auth/register",
        json={
            "email": "admin@example.com",
            "username": "admin",
            "password": "password123",
            "role": "admin",
        },
    )
    assert escalated.status_code == 422


@pytest.mark.asyncio
async def test_login_rejects_wrong_password_and_inactive_user(
    client: AsyncClient,
    user_store: InMemoryUserRepository,
    hasher: FastPasswordHasher,
) -> None:
    await _seed(
        user_store,
        hasher,
        email="idle@example.com",
        username="idle",
        role=UserRole.USER,
        is_active=False,
    )

    wrong_password = await client.post(
        "/auth/login",
        json={"email": "missing@example.com", "password": "password123"},
    )
    inactive = await client.post(
        "/auth/login",
        json={"email": "idle@example.com", "password": "password123"},
    )

    assert wrong_password.status_code == 401
    assert inactive.status_code == 401
    assert wrong_password.json()["detail"] == "Invalid email or password"
    assert inactive.json()["detail"] == "Invalid email or password"


@pytest.mark.asyncio
async def test_protected_routes_reject_missing_and_invalid_tokens(
    client: AsyncClient,
    settings: Settings,
    user_store: InMemoryUserRepository,
    hasher: FastPasswordHasher,
) -> None:
    user = await _seed(
        user_store,
        hasher,
        email="user@example.com",
        username="nick",
        role=UserRole.USER,
    )
    expired = create_access_token(
        user.id,
        settings,
        now=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    unknown = create_access_token(uuid.uuid4(), settings)

    missing = await client.get("/auth/me")
    malformed = await client.get("/auth/me", headers=_bearer("not-a-token"))
    expired_response = await client.get("/auth/me", headers=_bearer(expired))
    unknown_response = await client.get("/auth/me", headers=_bearer(unknown))

    assert missing.status_code == 401
    assert malformed.status_code == 401
    assert expired_response.status_code == 401
    assert unknown_response.status_code == 401

    user.is_active = False
    disabled = await client.get(
        "/auth/me",
        headers=_bearer(create_access_token(user.id, settings)),
    )
    assert disabled.status_code == 401


@pytest.mark.asyncio
async def test_role_dependencies(
    client: AsyncClient,
    user_store: InMemoryUserRepository,
    hasher: FastPasswordHasher,
) -> None:
    await _seed(
        user_store,
        hasher,
        email="user@example.com",
        username="nick",
        role=UserRole.USER,
    )
    await _seed(
        user_store,
        hasher,
        email="mod@example.com",
        username="mod",
        role=UserRole.MODERATOR,
    )
    await _seed(
        user_store,
        hasher,
        email="admin@example.com",
        username="admin",
        role=UserRole.ADMIN,
    )

    async def token_for(email: str) -> str:
        response = await client.post(
            "/auth/login",
            json={"email": email, "password": "password123"},
        )
        assert response.status_code == 200
        access_token: str = response.json()["access_token"]
        return access_token

    user_token = await token_for("user@example.com")
    moderator_token = await token_for("mod@example.com")
    admin_token = await token_for("admin@example.com")

    user_on_moderator = await client.get("/zones/moderator", headers=_bearer(user_token))
    moderator_on_moderator = await client.get(
        "/zones/moderator",
        headers=_bearer(moderator_token),
    )
    admin_on_moderator = await client.get("/zones/moderator", headers=_bearer(admin_token))
    moderator_on_admin = await client.get("/zones/admin", headers=_bearer(moderator_token))
    admin_on_admin = await client.get("/zones/admin", headers=_bearer(admin_token))
    anonymous_on_admin = await client.get("/zones/admin")

    assert user_on_moderator.status_code == 403
    assert user_on_moderator.json()["detail"] == "Moderator role required"
    assert moderator_on_moderator.status_code == 200
    assert moderator_on_moderator.json()["role"] == "moderator"
    assert admin_on_moderator.status_code == 200
    assert admin_on_moderator.json()["role"] == "admin"
    assert moderator_on_admin.status_code == 403
    assert moderator_on_admin.json()["detail"] == "Admin role required"
    assert admin_on_admin.status_code == 200
    assert anonymous_on_admin.status_code == 401
