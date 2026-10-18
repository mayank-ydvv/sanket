"""Sign up, log in, log out, current user; and the dependency that protects dispatcher routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth import SESSION_COOKIE, LoginThrottle, hash_password, read_session, sign_session, verify_password
from app.config import Settings, session_secret
from app.db import Database
from app.deps import get_db

router = APIRouter(prefix="/auth", tags=["auth"])
# Deliberately simple: something@something.tld, no spaces. Delivery is never attempted.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class SignUp(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)
    password: str = Field(min_length=8, max_length=200)


class LogIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class User(BaseModel):
    id: str
    name: str
    email: str


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _start_session(response: Response, settings: Settings, user_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        sign_session(user_id, session_secret(settings), settings.session_ttl_s),
        max_age=int(settings.session_ttl_s),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


async def current_user(request: Request, db: Annotated[Database, Depends(get_db)]) -> User | None:
    """Signed-in user, or 401. Returns None when AUTH_REQUIRED is off (tests, local scripts)."""
    settings = _settings(request)
    if not settings.auth_required:
        return None
    user_id = read_session(request.cookies.get(SESSION_COOKIE), session_secret(settings))
    row = await db.user_by_id(user_id) if user_id else None
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "please log in")
    return User(id=row["id"], name=row["name"], email=row["email"])


require_user = Depends(current_user)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: SignUp, request: Request, response: Response, db: Annotated[Database, Depends(get_db)]) -> User:
    email = body.email.lower()
    if await db.user_by_email(email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "an account with this email already exists")
    user = User(id=f"u_{uuid.uuid4().hex}", name=body.name, email=email)
    async with db.transaction():
        await db.create_user(user.id, user.name, user.email, hash_password(body.password))
    _start_session(response, _settings(request), user.id)
    return user


@router.post("/login")
async def login(body: LogIn, request: Request, response: Response, db: Annotated[Database, Depends(get_db)]) -> User:
    throttle: LoginThrottle = request.app.state.login_throttle
    email = body.email.lower()
    if throttle.blocked(email):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many attempts, try again in a few minutes")
    row = await db.user_by_email(email)
    if row is None or not verify_password(body.password, row["password_hash"]):
        throttle.failed(email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong email or password")
    throttle.succeeded(email)
    _start_session(response, _settings(request), row["id"])
    return User(id=row["id"], name=row["name"], email=row["email"])


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
async def me(request: Request, db: Annotated[Database, Depends(get_db)]) -> User | None:
    """The signed-in user, or null for a visitor (not a 401: public pages ask this on load)."""
    settings = _settings(request)
    user_id = read_session(request.cookies.get(SESSION_COOKIE), session_secret(settings))
    row = await db.user_by_id(user_id) if user_id else None
    return User(id=row["id"], name=row["name"], email=row["email"]) if row else None
