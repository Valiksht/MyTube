import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.core.security import TokenError, decode_access_token, get_password_hasher
from app.models import User
from app.models.enums import UserRole
from app.repositories.user import UserRepository, UserStore
from app.services.auth import AuthService

bearer_scheme = HTTPBearer(auto_error=False)


def get_user_repository(session: Annotated[AsyncSession, Depends(get_session)]) -> UserRepository:
    return UserRepository(session)


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    users: Annotated[UserStore, Depends(get_user_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    return AuthService(
        users=users,
        session=session,
        settings=settings,
        hasher=get_password_hasher(),
    )


def _unauthorized(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _resolve_user(
    credentials: HTTPAuthorizationCredentials | None,
    users: UserStore,
    settings: Settings,
) -> User | None:
    if credentials is None:
        return None
    if credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    try:
        user_id = decode_access_token(credentials.credentials, settings)
    except TokenError:
        raise _unauthorized() from None

    user = await users.get_by_id(user_id)
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    users: Annotated[UserStore, Depends(get_user_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User | None:
    return await _resolve_user(credentials, users, settings)


async def get_media_viewer(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    users: Annotated[UserStore, Depends(get_user_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User | None:
    if credentials is not None:
        return await _resolve_user(credentials, users, settings)
    access_token = request.query_params.get("access_token")
    if access_token is None or access_token.strip() == "":
        return None
    return await _resolve_user(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=access_token),
        users,
        settings,
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    users: Annotated[UserStore, Depends(get_user_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    user = await _resolve_user(credentials, users, settings)
    if user is None:
        raise _unauthorized()
    return user


async def require_moderator(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role not in {UserRole.MODERATOR, UserRole.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Moderator role required",
        )
    return user


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user
