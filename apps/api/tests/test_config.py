import pytest
from pydantic import SecretStr

from byop.config import ConfigError, Settings


def test_missing_secret_key_fails_fast_with_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYOP_SECRET_KEY", raising=False)
    monkeypatch.setattr(Settings, "model_config", {**Settings.model_config, "env_file": None})
    with pytest.raises(ConfigError) as excinfo:
        Settings.load()
    message = str(excinfo.value)
    assert "BYOP_SECRET_KEY" in message
    assert "openssl rand -hex 32" in message


def test_short_secret_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYOP_SECRET_KEY", "short")
    with pytest.raises(ConfigError, match="BYOP_SECRET_KEY"):
        Settings.load()


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYOP_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings.load()
    assert settings.openai_api_key == SecretStr("sk-test")
    assert "sk-test" not in repr(settings)
