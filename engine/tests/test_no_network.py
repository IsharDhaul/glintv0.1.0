import socket

import pytest


def test_sockets_are_blocked_outside_live_tests() -> None:
    with pytest.raises(RuntimeError, match="network access"):
        socket.create_connection(("www.sec.gov", 443), timeout=1)


def test_dns_is_blocked_outside_live_tests() -> None:
    with pytest.raises(RuntimeError, match="network access"):
        socket.getaddrinfo("www.sec.gov", 443)
