import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.models import User
from app.models.enums import UserRole
from app.services.auth import (
    AuthService,
    InactiveUser,
    InvalidCredentials,
    UserAlreadyExists,
    _conflict_field,
)
from tests.fakes import FastPasswordHasher, InMemoryUserRepository, NullSession


def _service(store: InMemoryUserRepository | None = None) -> tuple[AuthService, InMemoryUserRepository]:
    repository = store or InMemoryUserRepository()
    service = AuthService(
        users=repository,
        session=NullSession(),
        settings=Settings(
            jwt_secret_key="service-test-secret-key-32-characters",
            access_token_expire_minutes=30,
        ),
        hasher=FastPasswordHasher(),
    )
    return service, repository


@pytest.mark.asyncio
async def test_register_stores_user_role_and_hashed_password() -> None:
    service, repository = _service()

    user, token = await service.register("User@Example.com", "Nick_Name", "password123")

    assert token
    assert user.email == "user@example.com"
    assert user.username == "Nick_Name"
    assert user.role == UserRole.USER
    assert user.hashed_password == "fast:password123"
    assert repository.users[user.id] is user


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email_and_username() -> None:
    service, _repository = _service()
    await service.register("user@example.com", "nick", "password123")

    with pytest.raises(UserAlreadyExists) as email_error:
        await service.register("USER@example.com", "other", "password123")
    assert email_error.value.field == "email"

    with pytest.raises(UserAlreadyExists) as username_error:
        await service.register("second@example.com", "NICK", "password123")
    assert username_error.value.field == "username"


@pytest.mark.asyncio
async def test_register_maps_database_unique_violation() -> None:
    class RaceRepository(InMemoryUserRepository):
        async def get_by_email(self, email: str) -> User | None:
            return None

        async def get_by_username(self, username: str) -> User | None:
            return None

        async def add(self, user: User) -> User:
            raise IntegrityError(
                "INSERT",
                {},
                Exception("duplicate key value violates unique constraint uq_users_username_lower"),
            )

    service, _repository = _service(RaceRepository())

    with pytest.raises(UserAlreadyExists) as error:
        await service.register("user@example.com", "nick", "password123")
    assert error.value.field == "username"


@pytest.mark.asyncio
async def test_authenticate_accepts_email_case_insensitive() -> None:
    service, _repository = _service()
    created, _token = await service.register("user@example.com", "nick", "password123")

    user, token = await service.authenticate("User@Example.com", "password123")

    assert user.id == created.id
    assert token


@pytest.mark.asyncio
async def test_authenticate_rejects_unknown_user_and_wrong_password() -> None:
    service, _repository = _service()
    await service.register("user@example.com", "nick", "password123")

    with pytest.raises(InvalidCredentials):
        await service.authenticate("missing@example.com", "password123")
    with pytest.raises(InvalidCredentials):
        await service.authenticate("user@example.com", "wrong-password")


@pytest.mark.asyncio
async def test_authenticate_rejects_inactive_user() -> None:
    service, repository = _service()
    user, _token = await service.register("user@example.com", "nick", "password123")
    repository.users[user.id].is_active = False

    with pytest.raises(InactiveUser):
        await service.authenticate("user@example.com", "password123")


def test_conflict_field_falls_back_when_constraint_name_is_unknown() -> None:
    exc = IntegrityError("INSERT", {}, Exception("unique violation"))
    assert _conflict_field(exc) == "account"
