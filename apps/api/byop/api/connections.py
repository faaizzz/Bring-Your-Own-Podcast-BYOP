import uuid

from fastapi import APIRouter, HTTPException, status

from byop.api.deps import CurrentUser, SessionDep
from byop.api.integrations import ResolverDep
from byop.schemas.connections import (
    ConnectionCreate,
    ConnectionResponse,
    ConnectionTestResponse,
    ConnectionUpdate,
)
from byop.services import connections as service
from byop.services.credentials import CredentialDecryptionError

router = APIRouter(prefix="/connections", tags=["connections"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")


@router.get("", response_model=list[ConnectionResponse])
async def list_connections(
    user: CurrentUser, session: SessionDep, resolver: ResolverDep
) -> list[ConnectionResponse]:
    return await service.list_connections(session, resolver, user.id)


@router.post("", response_model=ConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: ConnectionCreate, user: CurrentUser, session: SessionDep, resolver: ResolverDep
) -> ConnectionResponse:
    try:
        return await service.create_connection(session, resolver, user.id, body)
    except service.ConnectionConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: uuid.UUID, user: CurrentUser, session: SessionDep, resolver: ResolverDep
) -> ConnectionResponse:
    try:
        return await service.get_connection(session, resolver, user.id, connection_id)
    except service.ConnectionNotFound as exc:
        raise NOT_FOUND from exc


@router.patch("/{connection_id}", response_model=ConnectionResponse)
async def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionUpdate,
    user: CurrentUser,
    session: SessionDep,
    resolver: ResolverDep,
) -> ConnectionResponse:
    try:
        return await service.update_connection(session, resolver, user.id, connection_id, body)
    except service.ConnectionNotFound as exc:
        raise NOT_FOUND from exc
    except service.ConnectionConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except service.ConnectionInvalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> None:
    """Refused (409) while a show or speaker still uses the connection."""
    try:
        await service.delete_connection(session, user.id, connection_id)
    except service.ConnectionNotFound as exc:
        raise NOT_FOUND from exc
    except service.ConnectionConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/{connection_id}/test", response_model=ConnectionTestResponse)
async def test_connection(
    connection_id: uuid.UUID, user: CurrentUser, session: SessionDep, resolver: ResolverDep
) -> ConnectionTestResponse:
    """List the models and/or voices the connection is set up for."""
    try:
        record = await service.get_record(session, user.id, connection_id)
    except service.ConnectionNotFound as exc:
        raise NOT_FOUND from exc
    try:
        config = resolver.connection_config(record)
    except CredentialDecryptionError as exc:
        return ConnectionTestResponse(ok=False, detail=str(exc), checks=[])
    return await service.check_connection(config, record)
