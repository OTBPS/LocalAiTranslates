"""Who may ask this host to translate.

Pure policy: no sockets, no subprocesses, no logging of secrets.  The service
binds to a Tailscale address so peers already arrive through an encrypted
WireGuard tunnel, but a tunnel proves the traffic came from the tailnet, not
that this particular device was invited.  Two independent checks close that
gap: the peer address must be a tailnet address (optionally narrowed to an
explicit allow-list), and the request must carry the shared secret.
"""

from __future__ import annotations

import ipaddress
import secrets
from dataclasses import dataclass, field

# Tailscale hands out addresses from the CGNAT range and a fixed ULA prefix.
TAILNET_IPV4 = ipaddress.ip_network("100.64.0.0/10")
TAILNET_IPV6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")

MINIMUM_SECRET_CHARACTERS = 16
SECRET_CHARACTERS = 43  # secrets.token_urlsafe(32)

#: What `authorize` returns for the host-wide secret, as opposed to one
#: issued to a particular device by pairing.
SHARED_DEVICE_ID = "shared"


class AccessDenied(PermissionError):
    """Raised when a request may not be served.

    The message is a stable reason code with no secret material in it, so it
    is safe both to log and to return to the peer.
    """


def generate_secret() -> str:
    return secrets.token_urlsafe(32)


def is_tailnet_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    if isinstance(parsed, ipaddress.IPv4Address):
        return parsed in TAILNET_IPV4
    return parsed in TAILNET_IPV6


def is_loopback_address(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def parse_bearer(header: str | None) -> str:
    """Extract the token from an Authorization header, or return an empty string."""
    if not isinstance(header, str):
        return ""
    prefix = "bearer "
    if not header.lower().startswith(prefix):
        return ""
    return header[len(prefix) :].strip()


@dataclass(frozen=True)
class AccessPolicy:
    """The rules a request must satisfy before any model work is scheduled."""

    secret: str
    allowed_peers: frozenset[str] = field(default_factory=frozenset)
    # The host may always reach its own service, so that a self-test is not
    # blocked by its own device allow-list.  Anything running on the host can
    # already do whatever it likes; this is never a substitute for the shared
    # secret, which is still required.
    allow_loopback: bool = True
    # The address the service is bound to, filled in once it is known.
    # Connecting to it from the host is the same machine talking to itself,
    # even though the packets carry a tailnet address rather than 127.0.0.1.
    local_address: str = ""
    # device_id -> secret, one per paired device. Revoking one device is
    # then removing one entry, rather than rotating the shared secret and
    # re-pairing everything else.
    device_secrets: tuple[tuple[str, str], ...] = ()

    def validate(self) -> None:
        """Fail fast at start-up rather than serving an unauthenticated port."""
        if len(self.secret) < MINIMUM_SECRET_CHARACTERS:
            raise ValueError(f"共享密钥至少需要 {MINIMUM_SECRET_CHARACTERS} 个字符")
        for peer in self.allowed_peers:
            if not is_tailnet_address(peer) and not is_loopback_address(peer):
                raise ValueError(f"设备白名单包含非 Tailscale 地址：{peer}")
        for device_id, secret in self.device_secrets:
            if len(secret) < MINIMUM_SECRET_CHARACTERS:
                raise ValueError(f"设备 {device_id} 的密钥过短")

    def identify_token(self, token: str) -> str | None:
        """Which credential this token is, or ``None``.

        Every candidate is compared, without short-circuiting on the first
        match, so the number of comparisons does not depend on which
        secret was supplied.
        """
        matched: str | None = None
        if token and secrets.compare_digest(token, self.secret):
            matched = SHARED_DEVICE_ID
        for device_id, secret in self.device_secrets:
            if token and secrets.compare_digest(token, secret):
                matched = device_id
        return matched

    def is_same_machine(self, peer_address: str) -> bool:
        if is_loopback_address(peer_address):
            return True
        return bool(self.local_address) and peer_address == self.local_address

    def admit(self, peer_address: str) -> None:
        """The address half of the check, which pairing also has to pass."""
        local = self.allow_loopback and self.is_same_machine(peer_address)
        if not is_tailnet_address(peer_address) and not local:
            raise AccessDenied("peer-not-on-tailnet")
        if self.allowed_peers and peer_address not in self.allowed_peers and not local:
            raise AccessDenied("peer-not-allowed")

    def authorize(self, peer_address: str, authorization: str | None) -> str:
        """Raise :class:`AccessDenied` unless the peer and token both check out.

        Returns which credential was used, so the host log can name the
        device without ever printing its secret.
        """
        self.admit(peer_address)
        # compare_digest keeps a wrong token from leaking its length by timing.
        device_id = self.identify_token(parse_bearer(authorization))
        if device_id is None:
            raise AccessDenied("invalid-token")
        return device_id
