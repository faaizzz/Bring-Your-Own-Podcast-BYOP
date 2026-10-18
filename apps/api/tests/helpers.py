from pydantic import SecretStr

from byop.config import Settings

TEST_SECRET = "test-secret-key-0123456789abcdef"


def make_settings(**overrides: object) -> Settings:
    """Settings that ignore the machine's .env; pass field overrides as keyword arguments."""
    values: dict[str, object] = {"byop_secret_key": SecretStr(TEST_SECRET), **overrides}
    return Settings(**values, _env_file=None)  # type: ignore[arg-type,call-arg]  # test helper
