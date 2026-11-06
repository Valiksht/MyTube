from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    get_auth_service,
    get_settings,
    get_user_repository,
    require_admin,
    require_moderator,
)
from app.core.config import Settings
from app.main import create_app
from app.models import User
from app.services.auth import AuthService
from tests.fakes import FastPasswordHasher, InMemoryUserRepository, NullSession


@pytest.fixture
def settings() -> Settings:
    return Settings(
        jwt_secret_key="test-jwt-secret-key-not-for-production",
        access_token_expire_minutes=30,
    )


@pytest.fixture
def user_store() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def hasher() -> FastPasswordHasher:
    return FastPasswordHasher()


@pytest.fixture
def auth_service(
    user_store: InMemoryUserRepository,
    settings: Settings,
    hasher: FastPasswordHasher,
) -> AuthService:
    return AuthService(
        users=user_store,
        session=NullSession(),
        settings=settings,
        hasher=hasher,
    )


@pytest.fixture
async def client(
    settings: Settings,
    user_store: InMemoryUserRepository,
    hasher: FastPasswordHasher,
) -> AsyncIterator[AsyncClient]:
    application = _application_with_role_zones(settings, user_store, hasher)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


def _application_with_role_zones(
    settings: Settings,
    user_store: InMemoryUserRepository,
    hasher: FastPasswordHasher,
) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_user_repository] = lambda: user_store
    application.dependency_overrides[get_auth_service] = lambda: AuthService(
        users=user_store,
        session=NullSession(),
        settings=settings,
        hasher=hasher,
    )

    zones = APIRouter()

    @zones.get("/zones/moderator")
    async def moderator_zone(
        user: Annotated[User, Depends(require_moderator)],
    ) -> dict[str, str]:
        return {"role": user.role.value}

    @zones.get("/zones/admin")
    async def admin_zone(
        user: Annotated[User, Depends(require_admin)],
    ) -> dict[str, str]:
        return {"role": user.role.value}

    application.include_router(zones)
    return application
