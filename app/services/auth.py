import uuid
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.security import PasswordHasher, create_access_token, get_password_hasher
from app.models import User
from app.models.enums import UserRole
from app.repositories.user import UserStore


class Transaction(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class AuthError(Exception):
    pass


class InvalidCredentials(AuthError):
    pass


class InactiveUser(AuthError):
    pass


class UserAlreadyExists(AuthError):
    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(field)


class AuthService:
    def __init__(
        self,
        users: UserStore,
        session: Transaction,
        settings: Settings,
        hasher: PasswordHasher | None = None,
    ) -> None:
        self._users = users
        self._session = session
        self._settings = settings
        self._hasher = hasher or get_password_hasher()

    async def register(self, email: str, username: str, password: str) -> tuple[User, str]:
        normalized_email = email.strip().lower()
        normalized_username = username.strip()

        if await self._users.get_by_email(normalized_email) is not None:
            raise UserAlreadyExists("email")
        if await self._users.get_by_username(normalized_username) is not None:
            raise UserAlreadyExists("username")

        user = User(
            id=uuid.uuid4(),
            email=normalized_email,
            username=normalized_username,
            hashed_password=self._hasher.hash(password),
            role=UserRole.USER,
            is_active=True,
        )
        try:
            await self._users.add(user)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise UserAlreadyExists(_conflict_field(exc)) from exc

        token = create_access_token(user.id, self._settings)
        return user, token

    async def authenticate(self, email: str, password: str) -> tuple[User, str]:
        user = await self._users.get_by_email(email.strip().lower())
        stored_hash = user.hashed_password if user is not None else self._hasher.dummy_hash
        password_matches = self._hasher.verify(password, stored_hash)
        if user is None or not password_matches:
            raise InvalidCredentials
        if not user.is_active:
            raise InactiveUser

        token = create_access_token(user.id, self._settings)
        return user, token


def _conflict_field(exc: IntegrityError) -> str:
    original = getattr(exc, "orig", None)
    message = str(original if original is not None else exc).lower()
    if "username" in message:
        return "username"
    if "email" in message:
        return "email"
    return "account"
