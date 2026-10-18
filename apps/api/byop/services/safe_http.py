"""Fetching user-supplied URLs without becoming a way into the host's network.

Every request (and every redirect hop) must resolve to an allowed address. Resolution and
connection are separate steps, so a DNS server that answers differently the second time could
still slip through; this is a guard against mistakes and the obvious attacks, not a sandbox.
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT_S = 15.0
MAX_REDIRECTS = 5
USER_AGENT = "BYOP/0.1 (podcast generator; feed fetcher)"

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class FetchError(Exception):
    """The URL cannot be fetched; the message says why, in words a user can act on."""


@dataclass(frozen=True)
class Fetched:
    url: str  # after redirects
    content_type: str | None
    content: bytes


async def resolve_host(host: str, port: int) -> list[str]:
    """The addresses `host` resolves to. A seam for tests, which must not hit real DNS."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"Could not find the host '{host}'") from exc
    return sorted({str(info[4][0]) for info in infos})


def address_problem(address: IPAddress, *, allow_private: bool) -> str | None:
    """Why requests to `address` are refused, or None when they are allowed."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_link_local or address.is_unspecified or address.is_multicast:
        return "link-local, unspecified and multicast addresses are never allowed"
    if not allow_private and not address.is_global:
        return "private and internal network addresses are not allowed"
    return None


async def ensure_public_url(url: str, *, allow_private: bool) -> httpx.URL:
    """Parse `url` and refuse anything that is not http(s) to an allowed address."""
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise FetchError("That is not a valid URL") from exc
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise FetchError("The URL must start with http:// or https://")
    if parsed.userinfo:
        raise FetchError("The URL must not contain a user name or password")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    for text in await resolve_host(parsed.host, port):
        problem = address_problem(
            ipaddress.ip_address(text.split("%")[0]), allow_private=allow_private
        )
        if problem:
            raise FetchError(f"'{parsed.host}' is not reachable from here: {problem}")
    return parsed


async def fetch_bytes(
    url: str,
    *,
    allow_private: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    accept: str = "*/*",
) -> Fetched:
    """GET `url`, following up to `MAX_REDIRECTS` redirects that each pass the address check."""
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    # trust_env=False: never route through proxies named in the environment.
    async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            target = await ensure_public_url(current, allow_private=allow_private)
            try:
                async with client.stream("GET", target, headers=headers) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError("The server redirected without saying where")
                        current = urljoin(str(response.url), location)
                        continue
                    if response.status_code >= 400:
                        raise FetchError(f"The server answered HTTP {response.status_code}")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise FetchError(
                                f"The response is larger than {max_bytes // (1024 * 1024)} MB"
                            )
                    return Fetched(
                        str(response.url), response.headers.get("content-type"), bytes(body)
                    )
            except httpx.TimeoutException as exc:
                raise FetchError("The server took too long to answer") from exc
            except httpx.TransportError as exc:
                raise FetchError("Could not connect to the server") from exc
    raise FetchError(f"Too many redirects (more than {MAX_REDIRECTS})")
