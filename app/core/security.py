import uuid
from datetime import datetime, timedelta, timezone
from typing import Protocol

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import Settings


class TokenError(Exception):
    pass


class PasswordHasher(Protocol):
    dummy_hash: str

    def hash(self, password: str) -> str: ...

    def verify(self, password: str, password_hash: str) -> bool: ...


class Argon2PasswordHasher:
    def __init__(self) -> None:
        self._hasher = PasswordHash.recommended()
        self.dummy_hash = self._hasher.hash("dummy-password")

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return bool(self._hasher.verify(password, password_hash))
        except (UnknownHashError, ValueError, TypeError):
            return False


_password_hasher = Argon2PasswordHasher()


def get_password_hasher() -> Argon2PasswordHasher:
    return _password_hasher


def create_access_token(
    user_id: uuid.UUID,
    settings: Settings,
    now: datetime | None = None,
) -> str:
    issued_at = now or datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.access_token_expire_minutes),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid token") from exc

    if payload.get("typ") != "access":
        raise TokenError("Invalid token type")

    subject = payload.get("sub")
    try:
        return uuid.UUID(str(subject))
    except (TypeError, ValueError) as exc:
        raise TokenError("Invalid subject") from exc
