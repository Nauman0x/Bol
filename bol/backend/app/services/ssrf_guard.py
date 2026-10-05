"""Shared SSRF guard for any URL BOL sends outbound requests to on the
API's or worker's own initiative — an agent's webhook tool (worker/tools.py)
and an org's outbound event webhook subscription (app/routers/webhooks.py)
have the identical threat model: a URL supplied by an org admin that must
not be able to reach internal infrastructure.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = {"localhost"}


async def check_webhook_url(url: str) -> None:
    """Re-resolves on every call (not just at save/tool-build time) so a URL
    can't pass validation once and then DNS-rebind to an internal address
    later. Requires https — plain http both leaks payloads on the wire and
    is how most SSRF payloads target unauthenticated internal HTTP services."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("webhook URL must use https")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("webhook URL missing host")
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise ValueError("webhook URL host not allowed")
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"could not resolve webhook host: {exc}") from exc
    for *_rest, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(f"webhook URL resolves to a blocked address: {ip}")
