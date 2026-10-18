import base64
import hashlib
import json
from collections.abc import Mapping
from typing import cast

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from byop.models.columns import JsonObject


class CryptoError(Exception):
    """A stored secret could not be decrypted (wrong or rotated BYOP_SECRET_KEY, or corrupt)."""


def _fernet(secret: SecretStr) -> Fernet:
    # Domain-separated from the session-signing key derived from the same secret.
    digest = hashlib.sha256(b"byop-credentials-v1:" + secret.get_secret_value().encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_json(data: Mapping[str, object], secret: SecretStr) -> str:
    return _fernet(secret).encrypt(json.dumps(data, separators=(",", ":")).encode()).decode()


def decrypt_json(token: str, secret: SecretStr) -> JsonObject:
    try:
        plaintext = _fernet(secret).decrypt(token.encode())
    except InvalidToken as exc:
        raise CryptoError("Cannot decrypt the stored secret") from exc
    return cast(JsonObject, json.loads(plaintext))
