from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from redis.asyncio import Redis

from byop.api.deps import CurrentUser, SessionDep, SettingsDep
from byop.config import Settings
from byop.redis_client import get_redis
from byop.schemas.auth import LoginRequest, PasswordChangeRequest, UserResponse
from byop.security.tokens import COOKIE_NAME, create_session_token
from byop.services import auth as auth_service
from byop.services.rate_limit import hit

LOGIN_ATTEMPTS_PER_MINUTE = 5

# Routes that must work without a session; everything else is guarded in byop/api/__init__.py.
public_router = APIRouter(prefix="/auth", tags=["auth"])
protected_router = APIRouter(prefix="/auth", tags=["auth"])


def client_ip(request: Request) -> str:
    """Caller IP for rate limiting.

    The API is only reachable through the nginx proxy, which appends the address it saw as
    the last `X-Forwarded-For` entry; earlier entries are client-controlled and ignored.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _cookie_kwargs(settings: Settings) -> dict[str, object]:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.public_base_url.startswith("https://"),
        "path": "/",
    }


@public_router.post("/login", response_model=UserResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    redis: Annotated[Redis, Depends(get_redis)],
) -> UserResponse:
    limit = await hit(redis, f"ratelimit:login:{client_ip(request)}", LOGIN_ATTEMPTS_PER_MINUTE, 60)
    if not limit.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many login attempts. Try again in a minute.",
            headers={"Retry-After": str(limit.retry_after)},
        )

    user = await auth_service.authenticate(session, body.email, body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    token = create_session_token(
        user.id, user.password_hash, settings.byop_secret_key, settings.byop_session_hours
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.byop_session_hours * 3600,
        **_cookie_kwargs(settings),  # type: ignore[arg-type]
    )
    return UserResponse.model_validate(user)


@public_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, settings: SettingsDep) -> None:
    kwargs = _cookie_kwargs(settings)
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=bool(kwargs["secure"]),
    )


@protected_router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)


@protected_router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChangeRequest, user: CurrentUser, session: SessionDep
) -> None:
    if not await auth_service.change_password(
        session, user, body.current_password, body.new_password
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
