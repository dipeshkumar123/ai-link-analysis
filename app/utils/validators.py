"""URL validation and SSRF protection."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
    "kubernetes.default",
    "kubernetes.default.svc",
}

BLOCKED_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".home.arpa",
    ".lan",
    ".corp",
    ".intranet",
    ".private",
)


class URLValidationError(ValueError):
    """Raised when a submitted URL is invalid or unsafe to fetch."""

    def __init__(self, message: str, *, code: str = "invalid_url", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    scheme: str
    hostname: str
    port: int | None

    @property
    def origin(self) -> str:
        default_port = 443 if self.scheme == "https" else 80
        port = self.port or default_port
        return f"{self.scheme}://{self.hostname}:{port}"


def _normalise_input(url: str) -> str:
    cleaned = url.strip()
    if not cleaned:
        raise URLValidationError("URL is empty.", code="empty_url")
    if len(cleaned) > 2048:
        raise URLValidationError("URL is longer than 2048 characters.", code="url_too_long")
    if any(char in cleaned for char in ("\n", "\r", "\t", "\x00")):
        raise URLValidationError("URL contains control characters.", code="invalid_url")
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    return cleaned


def _parse_and_check_structure(url: str) -> ValidatedURL:
    cleaned = _normalise_input(url)
    try:
        parsed = urlsplit(cleaned)
    except ValueError as exc:
        raise URLValidationError("URL could not be parsed.", code="invalid_url") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise URLValidationError(
            "Only http and https URLs are supported.", code="unsupported_scheme"
        )

    if parsed.username or parsed.password:
        raise URLValidationError(
            "URLs containing embedded credentials are not allowed.", code="credentials_not_allowed"
        )

    hostname = parsed.hostname
    if not hostname:
        raise URLValidationError("URL must contain a hostname.", code="missing_hostname")

    try:
        hostname = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise URLValidationError("Hostname is not valid.", code="invalid_hostname") from exc

    if len(hostname) > 253 or any(not label for label in hostname.split(".")):
        raise URLValidationError("Hostname is not valid.", code="invalid_hostname")

    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(BLOCKED_HOST_SUFFIXES):
        raise URLValidationError(
            "Private, local and cloud-metadata hostnames are not allowed.",
            code="blocked_host",
        )

    try:
        port = parsed.port
    except ValueError as exc:
        raise URLValidationError("Port is not valid.", code="invalid_port") from exc
    if port == 0:
        raise URLValidationError("Port 0 is not allowed.", code="invalid_port")

    # Rebuild a canonical URL without fragments or credentials.
    path = parsed.path or "/"
    canonical = urlunsplit((scheme, parsed.netloc.lower(), path, parsed.query, ""))
    return ValidatedURL(url=canonical, scheme=scheme, hostname=hostname, port=port)


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not ip.is_global


def _check_ip_literal(hostname: str) -> None:
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if _blocked_ip(ip):
        raise URLValidationError(
            "Private, loopback, link-local and reserved IP addresses are not allowed.",
            code="blocked_ip",
        )


def _check_resolved_ips(hostname: str, addresses: Iterable[tuple]) -> None:
    resolved: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for family, _type, _proto, _canonname, sockaddr in addresses:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        resolved.append(ip)
    if not resolved:
        raise URLValidationError("Hostname did not resolve to an IP address.", code="dns_error")
    if any(_blocked_ip(ip) for ip in resolved):
        raise URLValidationError(
            "Hostname resolves to a private, loopback or reserved address.",
            code="blocked_ip",
        )


def validate_public_url_sync(
    url: str, *, allow_private_hosts: bool = False
) -> ValidatedURL:
    validated = _parse_and_check_structure(url)
    if allow_private_hosts:
        return validated
    _check_ip_literal(validated.hostname)
    try:
        addresses = socket.getaddrinfo(
            validated.hostname,
            validated.port or (443 if validated.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise URLValidationError(
            "Website hostname could not be resolved.", code="dns_error", status_code=502
        ) from exc
    _check_resolved_ips(validated.hostname, addresses)
    return validated


async def validate_public_url(url: str, *, allow_private_hosts: bool = False) -> ValidatedURL:
    validated = _parse_and_check_structure(url)
    if allow_private_hosts:
        return validated
    _check_ip_literal(validated.hostname)
    loop = asyncio.get_running_loop()
    try:
        addresses = await loop.getaddrinfo(
            validated.hostname,
            validated.port or (443 if validated.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise URLValidationError(
            "Website hostname could not be resolved.", code="dns_error", status_code=502
        ) from exc
    _check_resolved_ips(validated.hostname, addresses)
    return validated


def resolve_redirect_url(current_url: str, location: str) -> str:
    from urllib.parse import urljoin

    joined = urljoin(current_url, location.strip())
    return joined
