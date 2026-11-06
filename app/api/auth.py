from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_auth_service, get_current_user
from app.models import User
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserResponse
from app.services.auth import (
    AuthService,
    InactiveUser,
    InvalidCredentials,
    UserAlreadyExists,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_CONFLICT_DETAILS = {
    "email": "Email already registered",
    "username": "Username already registered",
    "account": "User already exists",
}


def _auth_response(user: User, token: str) -> AuthResponse:
    return AuthResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    try:
        user, token = await auth.register(payload.email, payload.username, payload.password)
    except UserAlreadyExists as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_CONFLICT_DETAILS.get(exc.field, _CONFLICT_DETAILS["account"]),
        ) from exc
    return _auth_response(user, token)


@router.post("/login")
async def login(
    payload: LoginRequest,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    try:
        user, token = await auth.authenticate(payload.email, payload.password)
    except (InvalidCredentials, InactiveUser):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    return _auth_response(user, token)


@router.get("/me")
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return UserResponse.model_validate(user)
