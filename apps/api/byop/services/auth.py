import uuid

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import User
from byop.security.passwords import hash_password, verify_password
from byop.security.tokens import decode_session_token, password_fingerprint

# Verified against when the email is unknown, so both failure paths cost the same time.
_DUMMY_HASH = hash_password("byop-timing-equaliser")


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash) or not user.is_active:
        return None
    return user


async def user_from_token(session: AsyncSession, token: str, secret: SecretStr) -> User | None:
    decoded = decode_session_token(token, secret)
    if decoded is None:
        return None
    user_id, fingerprint = decoded
    return await _active_user(session, user_id, fingerprint)


async def _active_user(session: AsyncSession, user_id: uuid.UUID, fingerprint: str) -> User | None:
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        return None
    if password_fingerprint(user.password_hash) != fingerprint:
        return None  # password changed since this session was issued
    return user


async def change_password(
    session: AsyncSession, user: User, current_password: str, new_password: str
) -> bool:
    if not verify_password(current_password, user.password_hash):
        return False
    user.password_hash = hash_password(new_password)
    await session.commit()
    return True
