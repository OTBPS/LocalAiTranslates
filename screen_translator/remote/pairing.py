"""Exchanging a six-digit code for a per-device secret.

Pairing used to be: read a 43-character secret off the host's screen and
type it into the client. This replaces it with a code short enough to read
aloud, and hands back a secret the two machines never have to show anyone.

Pure standard library: no sockets, no Qt, no configuration. The transport
in :mod:`service` calls `claim`; everything about *whether* a claim is
accepted is decided here, where it can be tested exhaustively.

Why six digits is enough
------------------------
The code is not the only thing in the way. An attacker has to already be a
member of this tailnet (WireGuard, plus the CGNAT range check in
:mod:`access`), has to hit the 180-second window while it is open, and gets
five attempts before the offer is exhausted -- after which a further
lockout applies per peer. Blind guessing succeeds with probability at most
5/10^6, once, and only from inside the tailnet. Lengthening the code would
cost readability and buy nothing against the threat that remains.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum

CODE_DIGITS = 6
OFFER_TTL = 180.0
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60.0
SECRET_BYTES = 32
MAX_NONCE_LENGTH = 64
MAX_LABEL_LENGTH = 64

#: What every rejected claim is told, whatever the real reason. Saying
#: "wrong code" rather than "no offer" confirms that pairing is open;
#: saying "expired" confirms that the code was right.
REJECTION_MESSAGE = "配对失败，请向主机确认配对码后重试"


class OfferState(StrEnum):
    IDLE = "idle"
    OFFERED = "offered"
    CLAIMED = "claimed"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"
    CANCELLED = "cancelled"


class PairingError(Exception):
    """A claim that must not be accepted. The message is the uniform one."""

    def __init__(self, reason: str):
        super().__init__(REJECTION_MESSAGE)
        #: The real reason, for the host's own log only.
        self.reason = reason


def generate_code() -> str:
    """Six digits, uniformly random, leading zeros preserved."""
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


def generate_secret() -> str:
    return secrets.token_urlsafe(SECRET_BYTES)


def identify(secret: str) -> str:
    """A device's public name for its secret. Never the secret itself.

    Same rule as `core.PairedDevice.identify`, repeated here so this
    module stays importable without the configuration layer; a test holds
    the two to the same answer.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def normalize_code(value: object) -> str:
    """Accept what a person actually types: spaces, dashes, full-width digits."""
    if not isinstance(value, str):
        return ""
    cleaned = "".join(
        chr(ord(char) - 0xFEE0) if "０" <= char <= "９" else char
        for char in value.strip()
        if not char.isspace() and char not in "-_"
    )
    return cleaned if cleaned.isdigit() and len(cleaned) == CODE_DIGITS else ""


@dataclass(frozen=True)
class PairingGrant:
    """What a successful claim hands back."""

    device_id: str
    secret: str
    label: str = ""
    host_label: str = ""
    protocol: int = 0

    def to_payload(self) -> dict[str, object]:
        return {
            "device_id": self.device_id,
            "secret": self.secret,
            "label": self.label,
            "host_label": self.host_label,
            "protocol": self.protocol,
        }


@dataclass
class PairingOffer:
    """One open window during which a device may claim a secret."""

    code: str = field(default_factory=generate_code)
    created_at: float = field(default_factory=time.monotonic)
    ttl: float = OFFER_TTL
    state: OfferState = OfferState.OFFERED
    attempts: int = 0
    #: nonce -> grant, so a retried claim after a lost reply is idempotent.
    granted: dict[str, PairingGrant] = field(default_factory=dict)
    #: nonce -> peer address, so the same nonce from elsewhere is refused.
    claimants: dict[str, str] = field(default_factory=dict)

    def remaining(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        return max(0.0, self.created_at + self.ttl - now)

    @property
    def attempts_left(self) -> int:
        return max(0, MAX_ATTEMPTS - self.attempts)

    def settle(self, now: float | None = None) -> OfferState:
        """Move to a terminal state if time or attempts have run out."""
        if self.state is OfferState.OFFERED and self.remaining(now) <= 0:
            self.state = OfferState.EXPIRED
        return self.state

    @property
    def open(self) -> bool:
        return self.settle() is OfferState.OFFERED

    def describe(self) -> str:
        if self.state is OfferState.OFFERED:
            return f"配对码 {self.code}，{int(self.remaining())} 秒内有效"
        return {
            OfferState.CLAIMED: "已完成配对",
            OfferState.EXPIRED: "配对码已过期",
            OfferState.EXHAUSTED: "尝试次数过多，请重新生成配对码",
            OfferState.CANCELLED: "已取消配对",
        }.get(self.state, "未开始配对")


@dataclass
class PairingBroker:
    """The host's side: at most one offer open at a time.

    Rate limiting is per peer address rather than global, so one device
    burning its attempts cannot lock out another that is typing correctly.
    """

    offer: PairingOffer | None = None
    lockouts: dict[str, float] = field(default_factory=dict)
    host_label: str = ""

    @property
    def state(self) -> OfferState:
        if self.offer is None:
            return OfferState.IDLE
        return self.offer.settle()

    def describe(self) -> str:
        return self.offer.describe() if self.offer is not None else "未开始配对"

    def open_offer(self, ttl: float = OFFER_TTL) -> PairingOffer:
        """Start a new window, replacing any previous one."""
        self.offer = PairingOffer(ttl=ttl)
        return self.offer

    def cancel(self) -> None:
        if self.offer is not None and self.offer.state is OfferState.OFFERED:
            self.offer.state = OfferState.CANCELLED

    def _check_lockout(self, peer: str, now: float) -> None:
        until = self.lockouts.get(peer, 0.0)
        if until > now:
            raise PairingError(f"peer {peer} locked out for {until - now:.0f}s")
        if until:
            del self.lockouts[peer]

    def already_granted(self, nonce: object, peer: str) -> bool:
        """Whether this exact claim has already been answered.

        `claim` is idempotent so a peer that lost the reply gets the same
        grant back instead of a second secret. The host's own reaction is
        not idempotent, though: persisting the device and announcing it
        again for one pairing is wrong, and the caller cannot tell the two
        cases apart afterwards because the grant is identical. So it has
        to ask first.
        """
        offer = self.offer
        return (
            offer is not None
            and isinstance(nonce, str)
            and offer.claimants.get(nonce) == peer
        )

    def claim(
        self,
        *,
        code: object,
        nonce: object,
        peer: str,
        label: object = "",
        protocol: int = 0,
        now: float | None = None,
    ) -> PairingGrant:
        """Exchange a code for a per-device secret, or raise `PairingError`."""
        now = time.monotonic() if now is None else now
        self._check_lockout(peer, now)

        nonce_text = nonce if isinstance(nonce, str) else ""
        if not nonce_text or len(nonce_text) > MAX_NONCE_LENGTH:
            raise PairingError("missing or oversized nonce")

        offer = self.offer
        if offer is not None and offer.claimants.get(nonce_text) == peer:
            # Same device, same nonce: the reply was probably lost. Hand
            # back the identical grant rather than issuing a second secret,
            # and do it before the state check -- the offer is CLAIMED by
            # now precisely because this claim already succeeded.
            return offer.granted[nonce_text]

        if offer is None or offer.settle(now) is not OfferState.OFFERED:
            # Includes "nobody is pairing right now", which the peer is
            # never told apart from a wrong code.
            raise PairingError(f"no open offer (state={self.state})")

        if nonce_text in offer.claimants:
            # Someone replaying another device's claim from a different
            # address. Costs an attempt, like any other bad claim.
            offer.attempts += 1
            self._punish(offer, peer, now)
            raise PairingError("nonce replayed from a different peer")

        supplied = normalize_code(code)
        if not supplied or not secrets.compare_digest(supplied, offer.code):
            offer.attempts += 1
            self._punish(offer, peer, now)
            raise PairingError("wrong code")

        secret = generate_secret()
        grant = PairingGrant(
            # Derived from the secret, not invented: both ends reach the
            # same identifier without the identifier being a credential.
            device_id=identify(secret),
            secret=secret,
            label=_clean_label(label) or peer,
            host_label=self.host_label,
            protocol=protocol,
        )
        offer.claimants[nonce_text] = peer
        offer.granted[nonce_text] = grant
        offer.state = OfferState.CLAIMED
        self.lockouts.pop(peer, None)
        return grant

    def _punish(self, offer: PairingOffer, peer: str, now: float) -> None:
        if offer.attempts_left <= 0:
            offer.state = OfferState.EXHAUSTED
            self.lockouts[peer] = now + LOCKOUT_SECONDS


def _clean_label(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:MAX_LABEL_LENGTH]


def decode_claim(payload: object) -> dict[str, object]:
    """Validate an untrusted claim body. Raises `PairingError`."""
    if not isinstance(payload, dict):
        raise PairingError("claim body is not an object")
    code = payload.get("code")
    nonce = payload.get("nonce")
    if not isinstance(code, str) or not isinstance(nonce, str):
        raise PairingError("code and nonce must be strings")
    return {
        "code": code,
        "nonce": nonce,
        "label": payload.get("label", ""),
        "protocol": payload.get("protocol", 0),
    }


def new_nonce() -> str:
    """The client's replay token: proves a retry is the same attempt."""
    return secrets.token_urlsafe(16)


def remember(devices, grant: PairingGrant, address: str):
    """Add or replace this host in a client's list of paired devices.

    Keyed by device_id so re-pairing the same host replaces its entry
    instead of accumulating dead secrets.
    """
    from ..core import PairedDevice

    entry = PairedDevice(
        device_id=grant.device_id,
        label=grant.host_label or address,
        address=address,
        secret=grant.secret,
        paired_at=time.time(),
    )
    kept = tuple(item for item in devices if item.device_id != grant.device_id)
    return (*kept, entry)


def forget(devices, device_id: str):
    return tuple(item for item in devices if item.device_id != device_id)


def rotate(offer: PairingOffer) -> PairingOffer:
    """A fresh code on the same terms, for "the user misread it"."""
    return replace(offer, code=generate_code(), created_at=time.monotonic(), attempts=0)
