from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, status


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    email: str
    role: str


def _jwt_secret() -> str:
    return os.getenv("JWT_SECRET", "change-me-in-env").strip() or "change-me-in-env"


def _jwt_ttl_minutes() -> int:
    raw = os.getenv("AUTH_TOKEN_TTL_MINUTES", "720").strip()
    try:
        return max(int(raw), 5)
    except ValueError:
        return 720


def build_local_users() -> dict[str, dict[str, str]]:
    return {
        (os.getenv("ADMIN_EMAIL", "admin@local").strip() or "admin@local").lower(): {
            "password": os.getenv("ADMIN_PASSWORD", "ChangeMe123!").strip() or "ChangeMe123!",
            "role": "admin",
            "user_id": os.getenv("ADMIN_USER_ID", "11111111-1111-1111-1111-111111111111").strip()
            or "11111111-1111-1111-1111-111111111111",
        },
        (os.getenv("MEMBER_EMAIL", "member@local").strip() or "member@local").lower(): {
            "password": os.getenv("MEMBER_PASSWORD", "ChangeMe123!").strip() or "ChangeMe123!",
            "role": "member",
            "user_id": os.getenv("MEMBER_USER_ID", "22222222-2222-2222-2222-222222222222").strip()
            or "22222222-2222-2222-2222-222222222222",
        },
    }


def authenticate_local_user(email: str, password: str) -> AuthUser | None:
    users = build_local_users()
    candidate = users.get(email.strip().lower())
    if candidate is None or candidate["password"] != password:
        return None
    return AuthUser(
        user_id=candidate["user_id"],
        email=email.strip().lower(),
        role=candidate["role"],
    )


def create_access_token(user: AuthUser) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user.user_id,
        "email": user.email,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=_jwt_ttl_minutes())).timestamp()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def decode_access_token(token: str) -> AuthUser:
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid access token",
        ) from exc

    user_id = str(payload.get("sub", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    role = str(payload.get("role", "")).strip().lower() or "member"
    if not user_id or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid access token payload",
        )
    return AuthUser(user_id=user_id, email=email, role=role)


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing authorization header",
        )
    prefix = "bearer "
    if not authorization.lower().startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authorization scheme",
        )
    token = authorization[len(prefix) :].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    return token


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> AuthUser:
    return decode_access_token(_extract_bearer_token(authorization))


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]

