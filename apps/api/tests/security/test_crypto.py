import pytest
from pydantic import SecretStr

from byop.security.crypto import CryptoError, decrypt_json, encrypt_json

KEY = SecretStr("k" * 32)


def test_round_trip() -> None:
    payload = {"api_key": "sk-secret-value", "extra": {"a": "b"}}

    assert decrypt_json(encrypt_json(payload, KEY), KEY) == payload


def test_ciphertext_hides_the_plaintext_and_is_randomised() -> None:
    token = encrypt_json({"api_key": "sk-secret-value"}, KEY)

    assert "sk-secret-value" not in token
    assert token != encrypt_json({"api_key": "sk-secret-value"}, KEY)


def test_wrong_key_and_tampering_are_detected() -> None:
    token = encrypt_json({"api_key": "x"}, KEY)

    with pytest.raises(CryptoError):
        decrypt_json(token, SecretStr("o" * 32))
    with pytest.raises(CryptoError):
        decrypt_json(token[:-4] + "AAAA", KEY)
    with pytest.raises(CryptoError):
        decrypt_json("not a token", KEY)
