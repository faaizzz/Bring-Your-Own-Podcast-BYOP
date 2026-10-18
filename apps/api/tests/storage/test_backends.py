from pathlib import Path

import pytest
from pydantic import SecretStr

from byop.config import ConfigError, Settings
from byop.storage import LocalStorage, S3Storage, StorageError, build_storage
from tests.helpers import make_settings
from tests.storage.conftest import ACCESS_KEY, SECRET_KEY


def s3_settings(**overrides: object) -> Settings:
    return make_settings(
        storage_backend="s3",
        s3_bucket="byop",
        s3_access_key_id="key",
        s3_secret_access_key=SecretStr("secret"),
        **overrides,
    )


def test_local_is_the_default_backend(tmp_path: Path) -> None:
    storage = build_storage(make_settings(media_root=str(tmp_path)))

    assert isinstance(storage, LocalStorage)


def test_s3_backend_is_built_from_settings_and_reused() -> None:
    settings = s3_settings(s3_endpoint_url="http://s3:9000")

    first, second = build_storage(settings), build_storage(settings)

    assert isinstance(first, S3Storage)
    assert first is second


@pytest.mark.parametrize("missing", ["s3_bucket", "s3_access_key_id", "s3_secret_access_key"])
def test_s3_backend_needs_bucket_and_credentials(missing: str) -> None:
    values: dict[str, object] = {
        "s3_bucket": "byop",
        "s3_access_key_id": "key",
        "s3_secret_access_key": SecretStr("secret"),
    }
    values.pop(missing)

    with pytest.raises(ValueError, match=missing.upper()):
        make_settings(storage_backend="s3", **values)


def test_blank_s3_values_in_the_environment_count_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BYOP_SECRET_KEY", "x" * 20)
    monkeypatch.setenv("S3_ENDPOINT_URL", "")
    monkeypatch.setenv("S3_REGION", "")
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "")

    with pytest.raises(ConfigError, match="S3_BUCKET"):
        Settings.load()

    monkeypatch.setenv("STORAGE_BACKEND", "local")
    settings = Settings.load()
    assert settings.s3_endpoint_url is None
    assert settings.s3_region == "us-east-1"


async def test_an_unreachable_server_is_a_storage_error() -> None:
    storage = S3Storage(
        bucket="byop",
        access_key_id=ACCESS_KEY,
        secret_access_key=SECRET_KEY,
        endpoint_url="http://127.0.0.1:1",
    )

    with pytest.raises(StorageError):
        await storage.put("a/b.txt", b"x")


async def test_links_for_browsers_use_the_public_endpoint(moto_endpoint: str) -> None:
    storage = S3Storage(
        bucket="byop",
        access_key_id=ACCESS_KEY,
        secret_access_key=SECRET_KEY,
        endpoint_url=moto_endpoint,
        public_endpoint_url="http://localhost:9999",
    )

    url = await storage.url_for("shows/a/cover.jpg")

    assert url is not None and url.startswith("http://localhost:9999/byop/shows/a/cover.jpg?")
