import pytest
from unittest.mock import patch

from scripts.enrich_from_favicon import _is_public_host, _same_origin


@pytest.mark.parametrize(
    "ip,ok",
    [
        ("8.8.8.8", True),
        ("1.1.1.1", True),
        ("162.255.119.99", False),  # Namecheap NCNET-5 parking
        ("127.0.0.1", False),
        ("169.254.169.254", False),  # AWS/GCP metadata
        ("10.0.0.1", False),
        ("192.168.1.1", False),
        ("::ffff:162.255.119.99", False),  # IPv4-mapped IPv6 parking IP
        ("2606:4700:4700::1111", True),  # ordinary public IPv6
    ],
)
def test_public_host_blocks_parking(ip, ok):
    with patch(
        "scripts.enrich_from_favicon.socket.getaddrinfo",
        return_value=[(0, 0, 0, "", (ip, 0))],
    ):
        assert _is_public_host("example.com") is ok


def test_same_origin():
    assert _same_origin("https://foo.com/", "https://foo.com/x.ico")
    assert _same_origin("https://foo.com/", "https://www.foo.com/x.ico")
    assert not _same_origin("https://foo.com/", "https://attacker.tld/x.ico")
    assert not _same_origin("https://foo.com/", "https://162.255.119.99/x.ico")
