import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import Settings
from app.core.security import (
    Argon2PasswordHasher,
    TokenError,
    create_access_token,
    decode_access_token,
)


def _settings() -> Settings:
    return Settings(
        jwt_secret_key="unit-test-secret-key-32-characters",
        access_token_expire_minutes=15,
    )


def test_argon2_hash_fits_column_and_verifies() -> None:
    hasher = Argon2PasswordHasher()
    stored = hasher.hash("correct-horse")

    assert stored != "correct-horse"
    assert len(stored) <= 255
    assert hasher.verify("correct-horse", stored) is True
    assert hasher.verify("wrong-horse", stored) is False
    assert hasher.verify("correct-horse", "not-a-hash") is False


def test_access_token_round_trip() -> None:
    settings = _settings()
    user_id = uuid.uuid4()

    token = create_access_token(user_id, settings)

    assert decode_access_token(token, settings) == user_id


def test_expired_token_is_rejected() -> None:
    settings = _settings()
    token = create_access_token(
        uuid.uuid4(),
        settings,
        now=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_token_with_wrong_secret_is_rejected() -> None:
    issued = _settings()
    other = Settings(
        jwt_secret_key="different-secret-key-32-characters",
        access_token_expire_minutes=15,
    )
    token = create_access_token(uuid.uuid4(), issued)

    with pytest.raises(TokenError):
        decode_access_token(token, other)


def test_token_with_unexpected_type_is_rejected() -> None:
    settings = _settings()
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "typ": "refresh",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_token_with_invalid_subject_is_rejected() -> None:
    settings = _settings()
    token = jwt.encode(
        {
            "sub": "not-a-uuid",
            "typ": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(TokenError):
        decode_access_token(token, settings)
