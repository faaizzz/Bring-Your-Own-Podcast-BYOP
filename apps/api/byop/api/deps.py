from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings, get_settings
from byop.db import get_session
from byop.models import User
from byop.security.tokens import COOKIE_NAME
from byop.services.auth import user_from_token
from byop.storage import Storage, build_storage

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_storage(settings: SettingsDep) -> Storage:
    return build_storage(settings)


StorageDep = Annotated[Storage, Depends(get_storage)]


async def current_user(request: Request, session: SessionDep, settings: SettingsDep) -> User:
    """The signed-in user, or 401. Every non-public router is guarded by this."""
    token = request.cookies.get(COOKIE_NAME)
    user = await user_from_token(session, token, settings.byop_secret_key) if token else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
