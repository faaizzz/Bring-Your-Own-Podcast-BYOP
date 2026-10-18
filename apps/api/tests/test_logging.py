import json

import pytest
from httpx import AsyncClient

from byop.logging import REQUEST_ID_HEADER, configure_logging


async def test_request_id_is_generated_and_returned(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert len(response.headers[REQUEST_ID_HEADER]) == 32


async def test_incoming_request_id_is_kept_and_logged_as_json(
    client: AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO")  # rebind the handler to this test's captured stdout
    response = await client.get("/api/health", headers={REQUEST_ID_HEADER: "abc123"})
    assert response.headers[REQUEST_ID_HEADER] == "abc123"
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    request_lines = [line for line in lines if line.get("event") == "request"]
    assert request_lines
    assert request_lines[-1]["request_id"] == "abc123"
    assert request_lines[-1]["status"] == 200
