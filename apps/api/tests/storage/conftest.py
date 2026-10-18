import os
import socket
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from moto.server import ThreadedMotoServer

from byop.storage import LocalStorage, S3Storage, Storage

# The same image the `minio` compose profile runs (MinIO no longer publishes images).
S3_SERVER_IMAGE = "rustfs/rustfs:1.0.3"
ACCESS_KEY = "byoptestkey"
SECRET_KEY = "byoptestsecret123"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@pytest.fixture(scope="session")
def moto_endpoint() -> Iterator[str]:
    port = _free_port()
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    server.start()
    yield f"http://127.0.0.1:{port}"
    server.stop()


@pytest.fixture(scope="session")
def container_endpoint() -> Iterator[str]:
    """A real S3-compatible server in Docker; the tests that need it skip without Docker."""
    # The fixture stops the container itself; Ryuk (the reaper) needs the Docker socket mounted,
    # which Docker Desktop on macOS refuses.
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
    try:
        from testcontainers.core.container import DockerContainer

        container = (
            DockerContainer(S3_SERVER_IMAGE)
            .with_exposed_ports(9000)
            .with_env("RUSTFS_ACCESS_KEY", ACCESS_KEY)
            .with_env("RUSTFS_SECRET_KEY", SECRET_KEY)
        )
        container.start()
    except Exception as exc:  # no Docker daemon, image not pullable, ...
        pytest.skip(f"S3-compatible container unavailable: {exc}")
    try:
        # Docker publishes the port a moment after the container starts, so wait for the mapping
        # and for the server; give up (skip) rather than fail if either never shows up.
        deadline = time.monotonic() + 90
        endpoint = ""
        while True:
            try:
                if not endpoint:
                    endpoint = f"http://127.0.0.1:{container.get_exposed_port(9000)}"
                if httpx.get(f"{endpoint}/health", timeout=2).status_code < 500:
                    break
            except (httpx.HTTPError, ConnectionError):
                endpoint = ""
            if time.monotonic() > deadline:
                pytest.skip("S3-compatible container did not become ready")
            time.sleep(1)
        yield endpoint
    finally:
        container.stop()


@pytest.fixture(params=["local", "s3-moto", "s3-container"])
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> Storage:
    """Every backend, so each behaviour is specified once and holds for all of them."""
    if request.param == "local":
        return LocalStorage(tmp_path)
    endpoint = request.getfixturevalue(
        "moto_endpoint" if request.param == "s3-moto" else "container_endpoint"
    )
    return S3Storage(
        bucket=f"byop-{uuid.uuid4().hex[:12]}",  # created on first write
        access_key_id=ACCESS_KEY,
        secret_access_key=SECRET_KEY,
        endpoint_url=endpoint,
    )
