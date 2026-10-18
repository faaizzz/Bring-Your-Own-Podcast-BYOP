import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pydantic import SecretStr

ALGORITHM = "HS256"
COOKIE_NAME = "byop_session"


def _signing_key(secret: SecretStr) -> bytes:
    # Domain-separated from other uses of BYOP_SECRET_KEY (e.g. credential encryption).
    return hashlib.sha256(b"byop-session-v1:" + secret.get_secret_value().encode()).digest()


def password_fingerprint(password_hash: str) -> str:
    """Short digest of the password hash; changing the password invalidates old sessions."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def create_session_token(
    user_id: uuid.UUID, password_hash: str, secret: SecretStr, ttl_hours: int
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "pv": password_fingerprint(password_hash),
        "iat": now,
        "exp": now + timedelta(hours=ttl_hours),
    }
    return jwt.encode(claims, _signing_key(secret), algorithm=ALGORITHM)


def decode_session_token(token: str, secret: SecretStr) -> tuple[uuid.UUID, str] | None:
    """Return (user_id, password fingerprint) for a valid, unexpired token, else None."""
    try:
        claims = jwt.decode(
            token,
            _signing_key(secret),
            algorithms=[ALGORITHM],
            options={"require": ["sub", "pv", "exp"]},
        )
        return uuid.UUID(str(claims["sub"])), str(claims["pv"])
    except (jwt.PyJWTError, ValueError):
        return None
