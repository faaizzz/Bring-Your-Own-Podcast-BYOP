"""The user's OpenAI-compatible connections: create, change, test, delete.

A connection's key and header values live encrypted in `provider_connections.secret_encrypted`
and are read only through `CredentialResolver`; this module deals in masked views.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import ProviderConnection, Show, Speaker
from byop.schemas.connections import (
    ConnectionCheck,
    ConnectionCreate,
    ConnectionResponse,
    ConnectionTestResponse,
    ConnectionUpdate,
    HeaderOut,
)
from byop.schemas.speaker import SpeakerIn
from byop.services.credentials import (
    CredentialDecryptionError,
    CredentialResolver,
    ProviderConfig,
    mask_secret,
)
from byop.services.provider_ref import CONNECTION_PREFIX, InvalidProviderRef, ProviderRef
from byop.services.user_settings import discovery_choice_uses
from byop.services.validation import FieldError

TIMEOUT_SECONDS = 10.0


class ConnectionNotFound(Exception):
    pass


class ConnectionConflict(Exception):
    """The name is taken, or the connection is still in use."""


class ConnectionInvalid(Exception):
    pass


def _ref(connection_id: uuid.UUID) -> str:
    return f"{CONNECTION_PREFIX}{connection_id}"


@dataclass(frozen=True)
class Usage:
    shows: int
    speakers: int
    # The discovery model saved in Settings (0 or 1) is a language-model use too.
    settings: int = 0


async def usage_of(session: AsyncSession, user_id: uuid.UUID, connection_id: uuid.UUID) -> Usage:
    ref = _ref(connection_id)
    shows = await session.scalar(
        select(func.count())
        .select_from(Show)
        .where(Show.user_id == user_id, Show.llm_provider == ref)
    )
    speakers = await session.scalar(
        select(func.count())
        .select_from(Speaker)
        .where(
            Speaker.user_id == user_id,
            or_(Speaker.tts_provider == ref, Speaker.fallback_tts_provider == ref),
        )
    )
    chosen = await discovery_choice_uses(session, user_id, connection_id)
    return Usage(shows or 0, speakers or 0, int(chosen))


def _uses(shows: int, speakers: int, settings: int) -> str:
    parts = [
        f"{count} {noun}"
        for count, noun in (
            (shows, "show(s)"),
            (speakers, "speaker(s)"),
            (settings, "the discovery model setting"),
        )
        if count
    ]
    return " and ".join(parts)


def _view(
    record: ProviderConnection, resolver: CredentialResolver, usage: Usage
) -> ConnectionResponse:
    api_key: str | None = None
    headers: list[HeaderOut] = []
    problem: str | None = None
    try:
        key, values = resolver.open_connection(record)
        api_key = mask_secret(key) if key else None
        headers = [HeaderOut(name=n, value_masked=mask_secret(v)) for n, v in values.items()]
    except CredentialDecryptionError as exc:
        problem = str(exc)
    return ConnectionResponse(
        id=record.id,
        name=record.name,
        base_url=record.base_url,
        api_key_masked=api_key,
        headers=headers,
        llm=record.llm,
        tts=record.tts,
        web_search=record.web_search,
        enabled=record.enabled,
        shows_using=usage.shows,
        speakers_using=usage.speakers,
        problem=problem,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


async def get_record(
    session: AsyncSession, user_id: uuid.UUID, connection_id: uuid.UUID
) -> ProviderConnection:
    record = await session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.user_id == user_id, ProviderConnection.id == connection_id
        )
    )
    if record is None:
        raise ConnectionNotFound
    return record


async def _name_taken(
    session: AsyncSession, user_id: uuid.UUID, name: str, *, except_id: uuid.UUID | None = None
) -> bool:
    query = select(ProviderConnection.id).where(
        ProviderConnection.user_id == user_id, func.lower(ProviderConnection.name) == name.lower()
    )
    if except_id is not None:
        query = query.where(ProviderConnection.id != except_id)
    return await session.scalar(query) is not None


async def list_connections(
    session: AsyncSession, resolver: CredentialResolver, user_id: uuid.UUID
) -> list[ConnectionResponse]:
    rows = await session.scalars(
        select(ProviderConnection)
        .where(ProviderConnection.user_id == user_id)
        .order_by(func.lower(ProviderConnection.name))
    )
    return [_view(r, resolver, await usage_of(session, user_id, r.id)) for r in rows]


async def get_connection(
    session: AsyncSession,
    resolver: CredentialResolver,
    user_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> ConnectionResponse:
    record = await get_record(session, user_id, connection_id)
    return _view(record, resolver, await usage_of(session, user_id, record.id))


async def create_connection(
    session: AsyncSession,
    resolver: CredentialResolver,
    user_id: uuid.UUID,
    data: ConnectionCreate,
) -> ConnectionResponse:
    if await _name_taken(session, user_id, data.name):
        raise ConnectionConflict(f"There is already a connection called '{data.name}'")
    headers = {h.name: h.value.get_secret_value() for h in data.headers if h.value}
    record = ProviderConnection(
        user_id=user_id,
        name=data.name,
        base_url=str(data.base_url).rstrip("/"),
        secret_encrypted=resolver.seal_connection(
            data.api_key.get_secret_value() if data.api_key else None, headers
        ),
        llm=data.llm,
        tts=data.tts,
        web_search=data.web_search,
        enabled=data.enabled,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return _view(record, resolver, Usage(0, 0))


async def update_connection(
    session: AsyncSession,
    resolver: CredentialResolver,
    user_id: uuid.UUID,
    connection_id: uuid.UUID,
    data: ConnectionUpdate,
) -> ConnectionResponse:
    record = await get_record(session, user_id, connection_id)
    changed = data.model_fields_set
    if data.name is not None and await _name_taken(
        session, user_id, data.name, except_id=record.id
    ):
        raise ConnectionConflict(f"There is already a connection called '{data.name}'")

    usage = await usage_of(session, user_id, record.id)
    if data.llm is False and (usage.shows or usage.settings):
        raise ConnectionConflict(
            "Cannot switch off language models: "
            f"{_uses(usage.shows, 0, usage.settings)} this connection that way"
        )
    if data.tts is False and usage.speakers:
        raise ConnectionConflict(
            f"Cannot switch off voices: {usage.speakers} speaker(s) use this connection that way"
        )
    if data.enabled is False and (usage.shows or usage.speakers or usage.settings):
        raise ConnectionConflict(
            "Cannot disable a connection that shows, speakers or the discovery model setting "
            "use; move them first"
        )

    # Secrets are rewritten only when one of them is part of the request.
    if "api_key" in changed or data.headers is not None:
        try:
            old_key, old_headers = resolver.open_connection(record)
        except CredentialDecryptionError:
            old_key, old_headers = None, {}  # unreadable (rotated key): the request replaces it
        key = old_key
        if "api_key" in changed:
            key = data.api_key.get_secret_value() if data.api_key else None
        headers = old_headers
        if data.headers is not None:
            existing = {n.lower(): v for n, v in old_headers.items()}
            headers = {}
            for header in data.headers:
                if header.value is not None:
                    headers[header.name] = header.value.get_secret_value()
                elif header.name.lower() in existing:
                    headers[header.name] = existing[header.name.lower()]
                else:
                    raise ConnectionInvalid(f"The header '{header.name}' needs a value")
        record.secret_encrypted = resolver.seal_connection(key or None, headers)

    if data.name is not None:
        record.name = data.name
    if data.base_url is not None:
        record.base_url = str(data.base_url).rstrip("/")
    for flag in ("llm", "tts", "web_search", "enabled"):
        value = getattr(data, flag)
        if value is not None:
            setattr(record, flag, value)
    if not (record.llm or record.tts or record.web_search):
        raise ConnectionInvalid("Enable at least one use: language models, voices or web search")
    await session.commit()
    await session.refresh(record)
    return _view(record, resolver, usage)


async def delete_connection(
    session: AsyncSession, user_id: uuid.UUID, connection_id: uuid.UUID
) -> None:
    record = await get_record(session, user_id, connection_id)
    usage = await usage_of(session, user_id, record.id)
    if usage.shows or usage.speakers or usage.settings:
        raise ConnectionConflict(
            f"'{record.name}' is used by {_uses(usage.shows, usage.speakers, usage.settings)}. "
            "Choose another provider for them first."
        )
    await session.delete(record)
    await session.commit()


async def has_connection(
    session: AsyncSession, user_id: uuid.UUID, capability: Literal["llm", "tts"]
) -> bool:
    """Whether the user has an enabled connection for this use."""
    use = ProviderConnection.llm if capability == "llm" else ProviderConnection.tts
    found = await session.scalar(
        select(ProviderConnection.id)
        .where(ProviderConnection.user_id == user_id, ProviderConnection.enabled, use)
        .limit(1)
    )
    return found is not None


async def connection_problems(
    session: AsyncSession, user_id: uuid.UUID, speakers: Sequence[SpeakerIn]
) -> list[FieldError]:
    """Speakers that point at a connection which is missing, disabled or not for voices."""
    wanted: dict[uuid.UUID, list[tuple[int, str]]] = {}
    for index, speaker in enumerate(speakers):
        for field, value in (
            ("tts_provider", speaker.tts_provider),
            ("fallback_tts_provider", speaker.fallback_tts_provider),
        ):
            if value is None:
                continue
            try:
                ref = ProviderRef.parse(value)
            except InvalidProviderRef:
                continue  # the schema already rejected it
            if ref.connection_id is not None:
                wanted.setdefault(ref.connection_id, []).append((index, field))
    if not wanted:
        return []
    rows = await session.scalars(
        select(ProviderConnection).where(
            ProviderConnection.user_id == user_id, ProviderConnection.id.in_(wanted)
        )
    )
    found = {r.id: r for r in rows}
    errors: list[FieldError] = []
    for connection_id, places in wanted.items():
        record = found.get(connection_id)
        if record is None:
            problem = "The connection does not exist"
        elif not record.enabled:
            problem = f"The connection '{record.name}' is disabled"
        elif not record.tts:
            problem = f"The connection '{record.name}' is not enabled for voices"
        else:
            continue
        errors += [FieldError(("body", index, field), problem) for index, field in places]
    return errors


# --- testing --------------------------------------------------------------------------------------

Capability = Literal["llm", "tts", "web_search"]
# Servers without a list route answer one of these; the endpoint itself is reachable.
NO_LIST_ROUTE = {404, 405, 501}


def _bearer(config: ProviderConfig) -> dict[str, str]:
    headers = dict(config.headers)
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key.get_secret_value()}"
    return headers


async def _probe(
    client: httpx.AsyncClient, url: str, headers: dict[str, str]
) -> ConnectionCheck | tuple[bool, list[object]]:
    try:
        response = await client.get(url, headers=headers)
    except httpx.TimeoutException:
        return ConnectionCheck(
            capability="llm", ok=False, detail="The server did not answer in time"
        )
    except httpx.HTTPError as exc:
        return ConnectionCheck(
            capability="llm", ok=False, detail=f"Could not connect ({type(exc).__name__})"
        )
    if response.status_code in NO_LIST_ROUTE:
        return False, []
    if response.status_code in (401, 403):
        return ConnectionCheck(
            capability="llm",
            ok=False,
            detail=f"Authentication failed (HTTP {response.status_code})",
        )
    if not response.is_success:
        return ConnectionCheck(
            capability="llm", ok=False, detail=f"Unexpected response (HTTP {response.status_code})"
        )
    try:
        payload = response.json()
    except ValueError:
        return True, []
    items = payload.get("data", payload.get("voices")) if isinstance(payload, dict) else payload
    return True, items if isinstance(items, list) else []


async def check_connection(
    config: ProviderConfig, record: ProviderConnection
) -> ConnectionTestResponse:
    """List models and/or voices, as each enabled use needs. Details are safe to show: no URL,
    body, header or key ever appears in them."""
    base = (config.base_url or "").rstrip("/")
    headers = _bearer(config)
    plans: list[tuple[Capability, str, str]] = []
    if record.llm or record.web_search:
        plans.append(("llm" if record.llm else "web_search", f"{base}/models", "models"))
    if record.tts:
        plans.append(("tts", f"{base}/audio/voices", "voices"))
    checks: list[ConnectionCheck] = []
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        for capability, url, what in plans:
            outcome = await _probe(client, url, headers)
            if isinstance(outcome, ConnectionCheck):
                checks.append(outcome.model_copy(update={"capability": capability}))
                continue
            listed, items = outcome
            if not listed:
                detail = f"Reachable, but it has no list of {what}: type the name by hand"
            else:
                noun = what[:-1] if len(items) == 1 else what
                detail = f"Works: {len(items)} {noun} listed"
            checks.append(ConnectionCheck(capability=capability, ok=True, detail=detail))
    ok = all(c.ok for c in checks)
    return ConnectionTestResponse(
        ok=ok,
        detail="Connection works" if ok else next(c.detail for c in checks if not c.ok),
        checks=checks,
    )
