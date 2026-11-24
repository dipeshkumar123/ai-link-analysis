from __future__ import annotations

import asyncio
import socket

import pytest

from app.utils.validators import (
    URLValidationError,
    resolve_redirect_url,
    validate_public_url,
    validate_public_url_sync,
)

PUBLIC_DNS = [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
]
PRIVATE_DNS = [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 443)),
]


def test_rejects_loopback_ip() -> None:
    with pytest.raises(URLValidationError) as exc:
        validate_public_url_sync("http://127.0.0.1:8000/admin")
    assert exc.value.code == "blocked_ip"


def test_rejects_private_network_ip() -> None:
    with pytest.raises(URLValidationError) as exc:
        validate_public_url_sync("http://10.0.0.5")
    assert exc.value.code == "blocked_ip"


def test_rejects_localhost_hostname() -> None:
    with pytest.raises(URLValidationError) as exc:
        validate_public_url_sync("http://localhost:4000")
    assert exc.value.code == "blocked_host"


def test_rejects_unsupported_scheme() -> None:
    with pytest.raises(URLValidationError) as exc:
        validate_public_url_sync("ftp://example.com/file")
    assert exc.value.code == "unsupported_scheme"


def test_rejects_embedded_credentials() -> None:
    with pytest.raises(URLValidationError) as exc:
        validate_public_url_sync("https://user:password@example.com")
    assert exc.value.code == "credentials_not_allowed"


def test_rejects_empty_url() -> None:
    with pytest.raises(URLValidationError) as exc:
        validate_public_url_sync("   ")
    assert exc.value.code == "empty_url"


def test_accepts_public_url_with_mocked_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.utils.validators.socket.getaddrinfo", lambda *args, **kwargs: PUBLIC_DNS
    )
    validated = validate_public_url_sync("Example.com/path#fragment")
    assert validated.scheme == "https"
    assert validated.hostname == "example.com"
    assert validated.url == "https://example.com/path"


def test_rejects_hostname_resolving_to_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.utils.validators.socket.getaddrinfo", lambda *args, **kwargs: PRIVATE_DNS
    )
    with pytest.raises(URLValidationError) as exc:
        validate_public_url_sync("https://rebind.example")
    assert exc.value.code == "blocked_ip"


def test_dns_failure_returns_502() -> None:
    def fail(*args, **kwargs):
        raise socket.gaierror("no such host")

    import app.utils.validators as validators

    original = validators.socket.getaddrinfo
    validators.socket.getaddrinfo = fail
    try:
        with pytest.raises(URLValidationError) as exc:
            validate_public_url_sync("https://does-not-exist.invalid")
        assert exc.value.code == "dns_error"
        assert exc.value.status_code == 502
    finally:
        validators.socket.getaddrinfo = original


def test_async_validation_rejects_loopback() -> None:
    async def run() -> None:
        with pytest.raises(URLValidationError) as exc:
            await validate_public_url("http://127.0.0.1")
        assert exc.value.code == "blocked_ip"

    asyncio.run(run())


def test_redirect_url_resolution() -> None:
    assert (
        resolve_redirect_url("https://example.com/a/b", "/next")
        == "https://example.com/next"
    )
    assert (
        resolve_redirect_url("https://example.com/a/b", "https://other.test/x")
        == "https://other.test/x"
    )