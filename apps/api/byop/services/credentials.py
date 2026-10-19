"""Provider credentials: encrypted per-user overrides with a fallback to the environment.

`CredentialResolver` is the only code that reads provider keys (from the database or from
`Settings`); providers receive the resolved `ProviderConfig` and never touch either.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

import structlog
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import ProviderConnection, ProviderCredential
from byop.models.columns import JsonObject
from byop.models.enums import CredentialProvider
from byop.security.crypto import CryptoError, decrypt_json, encrypt_json
from byop.services.provider_ref import ProviderRef

log = structlog.get_logger(__name__)

Source = Literal["user", "env"]

# Providers that cannot work without an API key / without a base URL.
REQUIRES_API_KEY = {
    CredentialProvider.OPENROUTER,
    CredentialProvider.OPENAI,
    CredentialProvider.ELEVENLABS,
    CredentialProvider.LANGFUSE,
}
REQUIRES_BASE_URL = {CredentialProvider.KOKORO}


class ProviderNotConfigured(Exception):
    def __init__(
        self, provider: CredentialProvider | ProviderRef, reason: str | None = None
    ) -> None:
        super().__init__(reason or f"Provider '{provider}' is not configured")
        self.provider = provider


class CredentialDecryptionError(Exception):
    def __init__(self, provider: CredentialProvider | str) -> None:
        super().__init__(
            f"The stored '{provider}' credential cannot be decrypted. Was BYOP_SECRET_KEY "
            "changed? Re-enter the key, or run `python -m byop.cli rotate-key`."
        )
        self.provider = provider


@dataclass(frozen=True)
class ProviderConfig:
    """A resolved, ready-to-use provider configuration. Secrets stay wrapped in SecretStr.

    For a connection `provider` is `OPENAI_COMPATIBLE` and `connection_id`/`label` say which one.
    """

    provider: CredentialProvider
    source: Source
    api_key: SecretStr | None = None
    base_url: str | None = None
    extra: Mapping[str, str] = field(default_factory=dict)
    # Extra HTTP headers sent on every request (connections only); values are secrets.
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    connection_id: uuid.UUID | None = None
    label: str | None = None

    @property
    def usage_name(self) -> str:
        """The provider name recorded on usage events."""
        return f"conn:{self.label}" if self.connection_id else self.provider.value


def mask_secret(value: str) -> str:
    """`sk-or-v1-abcdef1234` -> `sk-…1234`; short values are fully hidden."""
    if len(value) <= 8:
        return "••••"
    return f"{value[:3]}…{value[-4:]}"


def _env_config(settings: Settings, provider: CredentialProvider) -> ProviderConfig | None:
    match provider:
        case CredentialProvider.OPENROUTER:
            key = settings.openrouter_api_key
        case CredentialProvider.OPENAI:
            key = settings.openai_api_key
        case CredentialProvider.ELEVENLABS:
            key = settings.elevenlabs_api_key
        case CredentialProvider.LANGFUSE:
            public, secret = settings.langfuse_public_key, settings.langfuse_secret_key
            if not (public and secret):
                return None
            return ProviderConfig(
                provider,
                "env",
                api_key=secret,
                base_url=settings.langfuse_host,
                extra={"public_key": public.get_secret_value()},
            )
        case CredentialProvider.KOKORO:
            if not settings.kokoro_base_url:
                return None
            return ProviderConfig(provider, "env", base_url=settings.kokoro_base_url)
        case CredentialProvider.OPENAI_COMPATIBLE:
            return None
    if key is None or not key.get_secret_value():
        return None
    return ProviderConfig(provider, "env", api_key=key)


def _config_from_payload(provider: CredentialProvider, payload: JsonObject) -> ProviderConfig:
    api_key = payload.get("api_key")
    base_url = payload.get("base_url")
    extra = payload.get("extra")
    return ProviderConfig(
        provider,
        "user",
        api_key=SecretStr(api_key) if isinstance(api_key, str) and api_key else None,
        base_url=base_url if isinstance(base_url, str) and base_url else None,
        extra={str(k): str(v) for k, v in extra.items()} if isinstance(extra, dict) else {},
    )


@dataclass(frozen=True)
class CredentialView:
    """What the API may show about a provider: never the secret itself."""

    provider: CredentialProvider
    source: Literal["user", "env", "none"]
    enabled: bool
    api_key_masked: str | None = None
    base_url: str | None = None
    extra_masked: Mapping[str, str] = field(default_factory=dict)
    problem: str | None = None


class CredentialResolver:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def _record(
        self, user_id: uuid.UUID, provider: CredentialProvider
    ) -> ProviderCredential | None:
        return await self._session.scalar(
            select(ProviderCredential).where(
                ProviderCredential.user_id == user_id, ProviderCredential.provider == provider
            )
        )

    def _decrypt(self, record: ProviderCredential) -> ProviderConfig:
        try:
            payload = decrypt_json(record.secret_encrypted, self._settings.byop_secret_key)
        except CryptoError as exc:
            raise CredentialDecryptionError(record.provider) from exc
        return _config_from_payload(record.provider, payload)

    async def stored_override(
        self, user_id: uuid.UUID, provider: CredentialProvider
    ) -> ProviderConfig | None:
        """The user's saved override whether or not it is enabled; None if absent/unreadable."""
        record = await self._record(user_id, provider)
        if record is None:
            return None
        try:
            return self._decrypt(record)
        except CredentialDecryptionError:
            return None

    async def get(self, user_id: uuid.UUID, provider: CredentialProvider) -> ProviderConfig:
        """The user's enabled override first, then the environment, else `ProviderNotConfigured`."""
        record = await self._record(user_id, provider)
        if record is not None and record.enabled:
            return self._decrypt(record)
        env = _env_config(self._settings, provider)
        if env is None:
            raise ProviderNotConfigured(provider)
        return env

    # -- connections ------------------------------------------------------------------------

    def connection_config(self, record: ProviderConnection) -> ProviderConfig:
        """The ready-to-use configuration of a stored connection (enabled or not)."""
        api_key, headers = self.open_connection(record)
        return ProviderConfig(
            CredentialProvider.OPENAI_COMPATIBLE,
            "user",
            api_key=SecretStr(api_key) if api_key else None,
            base_url=record.base_url.rstrip("/"),
            headers=headers,
            connection_id=record.id,
            label=record.name,
        )

    def open_connection(self, record: ProviderConnection) -> tuple[str | None, dict[str, str]]:
        """A connection's API key and headers; `CredentialDecryptionError` if unreadable."""
        try:
            payload = decrypt_json(record.secret_encrypted, self._settings.byop_secret_key)
        except CryptoError as exc:
            raise CredentialDecryptionError(f"conn:{record.name}") from exc
        key = payload.get("api_key")
        raw = payload.get("headers")
        headers: dict[str, str] = {}
        for entry in raw if isinstance(raw, list) else []:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                headers[entry["name"]] = str(entry.get("value", ""))
        return (key if isinstance(key, str) and key else None), headers

    def seal_connection(self, api_key: str | None, headers: Mapping[str, str]) -> str:
        """The encrypted document stored in `provider_connections.secret_encrypted`."""
        document: JsonObject = {
            "api_key": api_key or None,
            "headers": [{"name": n, "value": v} for n, v in headers.items()],
        }
        return encrypt_json(document, self._settings.byop_secret_key)

    async def get_ref(
        self,
        user_id: uuid.UUID,
        ref: ProviderRef,
        capability: Literal["llm", "tts"] | None = None,
    ) -> ProviderConfig:
        """Like `get`, for a built-in provider or one of the user's connections.

        A connection must exist, be enabled and (when `capability` is given) allow that use.
        """
        if ref.builtin is not None:
            return await self.get(user_id, ref.builtin)
        record = await self._session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.user_id == user_id, ProviderConnection.id == ref.connection_id
            )
        )
        if record is None:
            raise ProviderNotConfigured(ref, "The connection does not exist (was it deleted?)")
        if not record.enabled:
            raise ProviderNotConfigured(ref, f"The connection '{record.name}' is disabled")
        if capability == "llm" and not record.llm:
            raise ProviderNotConfigured(
                ref, f"The connection '{record.name}' is not enabled for language models"
            )
        if capability == "tts" and not record.tts:
            raise ProviderNotConfigured(
                ref, f"The connection '{record.name}' is not enabled for voices"
            )
        return self.connection_config(record)

    async def view(self, user_id: uuid.UUID, provider: CredentialProvider) -> CredentialView:
        """The effective configuration, masked for display."""
        record = await self._record(user_id, provider)
        if record is not None and record.enabled:
            try:
                config = self._decrypt(record)
            except CredentialDecryptionError as exc:
                return CredentialView(provider, "user", True, problem=str(exc))
            return _view(config, enabled=True)
        env = _env_config(self._settings, provider)
        if env is not None:
            return _view(env, enabled=record.enabled if record else True)
        return CredentialView(provider, "none", enabled=record.enabled if record else True)

    async def save(
        self,
        user_id: uuid.UUID,
        provider: CredentialProvider,
        *,
        api_key: str | None,
        base_url: str | None,
        extra: Mapping[str, str] | None,
        enabled: bool,
    ) -> None:
        """Create or update the user's override. Omitted fields keep their stored value."""
        record = await self._record(user_id, provider)
        current: JsonObject = {}
        if record is not None:
            try:
                current = decrypt_json(record.secret_encrypted, self._settings.byop_secret_key)
            except CryptoError:
                current = {}  # unreadable (rotated key): the new values replace it

        merged: JsonObject = {
            "api_key": api_key if api_key else current.get("api_key"),
            "base_url": base_url if base_url is not None else current.get("base_url"),
            "extra": dict(extra) if extra is not None else current.get("extra", {}),
        }
        token = encrypt_json(merged, self._settings.byop_secret_key)
        if record is None:
            self._session.add(
                ProviderCredential(
                    user_id=user_id, provider=provider, secret_encrypted=token, enabled=enabled
                )
            )
        else:
            record.secret_encrypted = token
            record.enabled = enabled
        await self._session.commit()

    async def delete(self, user_id: uuid.UUID, provider: CredentialProvider) -> None:
        record = await self._record(user_id, provider)
        if record is not None:
            await self._session.delete(record)
            await self._session.commit()


def _view(config: ProviderConfig, *, enabled: bool) -> CredentialView:
    return CredentialView(
        provider=config.provider,
        source=config.source,
        enabled=enabled,
        api_key_masked=mask_secret(config.api_key.get_secret_value()) if config.api_key else None,
        base_url=config.base_url,
        extra_masked={k: mask_secret(v) for k, v in config.extra.items()},
    )


async def rotate_credentials(
    session: AsyncSession, old_secret: SecretStr, new_secret: SecretStr
) -> int:
    """Re-encrypt every stored credential from `old_secret` to `new_secret`.

    All-or-nothing: if any row cannot be decrypted with the old key nothing is changed.
    """
    records: list[ProviderCredential | ProviderConnection] = [
        *(await session.scalars(select(ProviderCredential))).all(),
        *(await session.scalars(select(ProviderConnection))).all(),
    ]
    reencrypted: dict[uuid.UUID, str] = {}
    for record in records:
        try:
            payload = decrypt_json(record.secret_encrypted, old_secret)
        except CryptoError as exc:
            name = record.provider.value if isinstance(record, ProviderCredential) else record.name
            raise CredentialDecryptionError(name) from exc
        reencrypted[record.id] = encrypt_json(payload, new_secret)
    for record in records:
        record.secret_encrypted = reencrypted[record.id]
    await session.commit()
    log.info("credentials_rotated", count=len(records))
    return len(records)
