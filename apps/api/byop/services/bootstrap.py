import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import User
from byop.security.passwords import hash_password
from byop.services.personas import seed_starter_personas

log = structlog.get_logger(__name__)


async def ensure_admin_user(session: AsyncSession, settings: Settings) -> User | None:
    """Create the single admin from the environment if it does not exist yet.

    An existing user is never modified: after the first start the password lives in
    the database and is changed through the app, not through `.env`.
    """
    if settings.byop_admin_password is None:
        log.warning("admin_seed_skipped", reason="BYOP_ADMIN_PASSWORD is not set")
        return None

    email = settings.byop_admin_email.strip().lower()
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        return existing

    user = User(
        email=email,
        password_hash=hash_password(settings.byop_admin_password.get_secret_value()),
        is_admin=True,
    )
    session.add(user)
    await session.flush()
    await seed_starter_personas(session, user.id)
    await session.commit()
    log.info("admin_seeded", email=email)
    return user
