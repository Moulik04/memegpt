"""
Who a request is from, for limits only (rate_limit.py, daily_quota.py).

The address this process sees on a connection is not the visitor's. Chat,
Lore and Make arrive through the frontend's server, so every visitor shows
up as that server, and a header saying otherwise could be typed by anyone
who calls this backend directly. So a visitor's address is believed in
exactly two cases, both of which need a secret only the frontend's server
and this backend hold (settings.proxy_shared_secret):

  - the request carries that secret, and with it the address the frontend's
    server saw (its host sets that address itself and discards whatever the
    browser sent);
  - the request carries a short-lived token the frontend's server signed
    with that secret for the address it saw. This is for photo uploads,
    which the browser sends here directly because they are too large to
    pass through the frontend's server.

Anything else is keyed on the connection, and the connection is not to be
relied on either: behind a host's own proxy, request.client is whatever
that proxy and the server in front of this app make of the forwarding
headers, and where the first X-Forwarded-For entry is believed a direct
caller picks their own address with one header. That is acceptable for a
per-minute limit on a route that costs nothing. It is not for the routes
that spend the model budget, so those do not fall back to it: with a secret
configured they turn away any request that neither case above vouches for
(require_vouched).

Nothing here is stored or logged. The anonymous browser id (identity.py) is
a different thing: the browser chooses it, so on its own it limits nothing.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from config import get_settings
from identity import get_anon_user_id

PROXY_SECRET_HEADER = "X-MemeGPT-Proxy-Secret"
PROXY_ADDRESS_HEADER = "X-MemeGPT-Client-Address"
VISIT_TOKEN_HEADER = "X-MemeGPT-Visit"

# Shown when a meme-making request arrives with nothing to vouch for it. A
# visitor only sees it if the page failed to fetch its upload token.
UNVOUCHED_MESSAGE = "MemeGPT couldn't confirm this request came from the app. Reload the page and try again."

_TOKEN_VERSION = "v1"
_MAX_ADDRESS_LEN = 64  # an IPv6 address is at most 45 characters


@dataclass(frozen=True)
class Visitor:
    address: str
    # True when `address` came from the frontend's server under the shared
    # secret. False when it is only the connection this process saw.
    address_verified: bool
    browser: str | None


def _connection_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _clean_address(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value or len(value) > _MAX_ADDRESS_LEN:
        return None
    return value


def network_of(address: str) -> str:
    """The network an address counts against for the daily ceiling
    (daily_quota.py). An IPv4 address is its own network. An IPv6 address
    counts as its /64: that is what one home or office connection is
    normally given, and a device picks, and can keep changing, the half
    after it. Counting whole IPv6 addresses would make the ceiling a
    matter of asking for a new one.

    Anything that is not an address ("unknown", a test client's name) is
    returned as it came.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    if ip.version == 4:
        return str(ip)
    if ip.ipv4_mapped is not None:
        return str(ip.ipv4_mapped)
    return str(ipaddress.IPv6Network((int(ip) >> 64 << 64, 64)))


def sign_visit(address: str, expires_at: int, secret: str) -> str:
    """The token the frontend's server issues (frontend/src/app/api/visit).
    Kept here as the reference for that route and for the tests."""
    encoded = base64.urlsafe_b64encode(address.encode()).decode().rstrip("=")
    payload = f"{_TOKEN_VERSION}.{expires_at}.{encoded}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _address_from_visit_token(token: str, secret: str) -> str | None:
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != _TOKEN_VERSION:
        return None
    version, expires, encoded, signature = parts
    expected = hmac.new(secret.encode(), f"{version}.{expires}.{encoded}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.encode(), expected.encode()):
        return None
    try:
        if int(expires) < time.time():
            return None
        address = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    return _clean_address(address)


def _verified_address(request: Request) -> str | None:
    secret = get_settings().proxy_shared_secret
    if not secret:
        return None
    provided = request.headers.get(PROXY_SECRET_HEADER, "")
    if provided and hmac.compare_digest(provided.encode(), secret.encode()):
        return _clean_address(request.headers.get(PROXY_ADDRESS_HEADER))
    token = request.headers.get(VISIT_TOKEN_HEADER, "")
    if token:
        return _address_from_visit_token(token, secret)
    return None


def identify(request: Request) -> Visitor:
    verified = _verified_address(request)
    return Visitor(
        address=verified or _connection_address(request),
        address_verified=verified is not None,
        browser=get_anon_user_id(request),
    )


def require_vouched(request: Request) -> Visitor:
    """Dependency for the routes that make memes (Chat, Lore, Make, with or
    without photos). With a secret configured, a request the frontend's
    server has not vouched for is refused before anything is read from it,
    counted or sent to a model: the daily allowance is only worth having if
    the address it is counted against cannot be chosen by the caller.

    With no secret configured there is no frontend server to vouch for
    anyone (a local run), and every request is let in.
    """
    visitor = identify(request)
    if get_settings().proxy_shared_secret and not visitor.address_verified:
        raise HTTPException(status_code=403, detail=UNVOUCHED_MESSAGE)
    return visitor


def rate_limit_key(request: Request) -> str:
    """slowapi's key: the visitor's address when it can be believed, the
    connection otherwise."""
    return identify(request).address


def describe_address_trust(settings) -> tuple[str, str]:
    """(level, message) for the startup log, same idea as
    llm_client.describe_llm_provider: a missing secret changes behavior
    quietly, so say it once where it will be seen."""
    if settings.proxy_shared_secret:
        return "info", (
            "Visitor addresses: taken from the frontend's server (PROXY_SHARED_SECRET is set). "
            "Chat, Lore and Make refuse requests it has not vouched for."
        )
    return "warning", (
        "PROXY_SHARED_SECRET is not set. Requests that come through the frontend's "
        "server all look like one address, so per-minute limits there are shared by "
        "every visitor and the per-network daily ceiling is switched off. The "
        "per-browser daily limit still applies, but a browser id can be changed at will."
    )


def log_address_trust(settings) -> None:
    level, message = describe_address_trust(settings)
    if level == "warning":
        banner = "!" * 78
        print(f"{banner}\nWARNING: {message}\n{banner}", flush=True)
    else:
        print(message, flush=True)
