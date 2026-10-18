import socket

import pytest


def test_external_connections_are_blocked_in_tests() -> None:
    sock = socket.socket()
    try:
        with pytest.raises(RuntimeError, match="blocked in tests"):
            sock.connect(("93.184.216.34", 80))
    finally:
        sock.close()
