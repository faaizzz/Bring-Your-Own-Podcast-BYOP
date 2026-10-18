import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pydantic import SecretStr

from byop.security.tokens import (
    ALGORITHM,
    _signing_key,
    create_session_token,
    decode_session_token,
    password_fingerprint,
)

SECRET = SecretStr("s" * 32)


def test_round_trip_returns_user_and_fingerprint() -> None:
    user_id = uuid.uuid4()

    token = create_session_token(user_id, "hash", SECRET, 1)

    assert decode_session_token(token, SECRET) == (user_id, password_fingerprint("hash"))


def test_wrong_key_garbage_and_expired_tokens_are_rejected() -> None:
    token = create_session_token(uuid.uuid4(), "hash", SECRET, 1)
    assert decode_session_token(token, SecretStr("o" * 32)) is None
    assert decode_session_token("garbage", SECRET) is None

    claims = jwt.decode(token, options={"verify_signature": False})
    claims["exp"] = datetime.now(UTC) - timedelta(seconds=5)
    expired = jwt.encode(claims, _signing_key(SECRET), algorithm=ALGORITHM)
    assert decode_session_token(expired, SECRET) is None


def test_tokens_without_required_claims_are_rejected() -> None:
    bare = jwt.encode({"sub": str(uuid.uuid4())}, _signing_key(SECRET), algorithm=ALGORITHM)

    assert decode_session_token(bare, SECRET) is None


def test_alg_none_tokens_are_rejected() -> None:
    forged = jwt.encode({"sub": str(uuid.uuid4()), "pv": "x"}, key=None, algorithm="none")  # type: ignore[arg-type]  # deliberately unsigned

    assert decode_session_token(forged, SECRET) is None
