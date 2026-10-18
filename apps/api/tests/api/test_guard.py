"""Every API route must reject anonymous callers unless it is deliberately public."""

import re

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

# Add a route here only if it must work without a session (feed, audio, health, login...).
PUBLIC_ROUTES = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
}


def api_routes(app: FastAPI) -> list[tuple[str, str]]:
    """(METHOD, path) for every documented route, read from the public OpenAPI schema."""
    paths: dict[str, dict[str, object]] = app.openapi()["paths"]
    return sorted(
        (method.upper(), path)
        for path, operations in paths.items()
        for method in operations
        if path.startswith("/api") and method in {"get", "post", "put", "patch", "delete"}
    )


def test_public_allowlist_has_no_stale_entries(app: FastAPI) -> None:
    assert PUBLIC_ROUTES <= set(api_routes(app))


async def test_every_non_public_route_returns_401_without_a_session(
    app: FastAPI, client: AsyncClient
) -> None:
    protected = [r for r in api_routes(app) if r not in PUBLIC_ROUTES]
    assert protected, "expected at least the authenticated routes"

    for method, path in protected:
        url = re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", path)
        response = await client.request(method, url)
        assert response.status_code == 401, f"{method} {path} is not guarded"


@pytest.mark.parametrize("path", ["/api/health", "/api/docs", "/api/openapi.json"])
async def test_health_and_docs_stay_public(client: AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 200
