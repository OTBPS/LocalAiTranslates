"""Exchanging a six-digit code for a per-device secret.

Pairing used to be reading a 43-character secret off one screen and typing
it into another. A short code is only acceptable because of what surrounds
it, so most of this file is about the surroundings: the window closes, the
attempts run out, a peer that burns them is locked out, and a replay from
somewhere else is refused.
"""

import pytest

from screen_translator.core import PairedDevice
from screen_translator.remote.access import (
    SHARED_DEVICE_ID,
    AccessDenied,
    AccessPolicy,
)
from screen_translator.remote.pairing import (
    CODE_DIGITS,
    LOCKOUT_SECONDS,
    MAX_ATTEMPTS,
    OFFER_TTL,
    REJECTION_MESSAGE,
    OfferState,
    PairingBroker,
    PairingError,
    decode_claim,
    forget,
    generate_code,
    identify,
    new_nonce,
    normalize_code,
    remember,
)

PEER = "100.64.0.20"
OTHER = "100.64.0.30"


def broker(**kwargs):
    subject = PairingBroker(**kwargs)
    subject.open_offer()
    return subject


def claim(subject, code=None, *, peer=PEER, nonce=None, now=None, **kwargs):
    return subject.claim(
        code=code if code is not None else subject.offer.code,
        nonce=nonce or new_nonce(),
        peer=peer,
        now=now,
        **kwargs,
    )


# -- the code itself ---------------------------------------------------


def test_a_code_is_six_digits_and_keeps_its_leading_zeros():
    for _ in range(200):
        code = generate_code()
        assert len(code) == CODE_DIGITS
        assert code.isdigit()


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("123456", "123456"),
        (" 123 456 ", "123456"),
        ("123-456", "123456"),
        ("１２３４５６", "123456"),  # full-width, as a Chinese IME produces
        ("12345", ""),
        ("1234567", ""),
        ("12345a", ""),
        ("", ""),
        (None, ""),
        (123456, ""),
    ],
)
def test_a_code_is_read_the_way_a_person_types_it(typed, expected):
    assert normalize_code(typed) == expected


# -- the window --------------------------------------------------------


def test_the_right_code_hands_back_a_secret_the_device_keeps():
    subject = broker(host_label="workstation")

    grant = claim(subject, label="laptop")

    assert len(grant.secret) >= 32
    assert grant.device_id == identify(grant.secret)
    assert grant.host_label == "workstation"
    assert subject.state is OfferState.CLAIMED


def test_the_window_closes_on_its_own():
    subject = broker()
    subject.offer.ttl = 10.0
    start = subject.offer.created_at

    with pytest.raises(PairingError):
        claim(subject, now=start + OFFER_TTL + 1)

    assert subject.state is OfferState.EXPIRED


def test_no_offer_at_all_is_refused_the_same_way_as_a_wrong_code():
    quiet = PairingBroker()
    open_offer = broker()

    with pytest.raises(PairingError) as absent:
        claim(quiet, "000000")
    with pytest.raises(PairingError) as wrong:
        claim(open_offer, "000000" if open_offer.offer.code != "000000" else "111111")

    # Telling them apart would confirm to anyone on the tailnet whether
    # this host happens to be pairing right now.
    assert str(absent.value) == str(wrong.value) == REJECTION_MESSAGE


def test_attempts_run_out_and_the_peer_is_locked_out():
    subject = broker()
    wrong = "000000" if subject.offer.code != "000000" else "111111"

    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(PairingError):
            claim(subject, wrong)

    assert subject.state is OfferState.EXHAUSTED
    # Even the right code is now refused: the offer is spent.
    with pytest.raises(PairingError):
        claim(subject)


def test_a_lockout_applies_to_the_peer_that_earned_it_and_not_to_others():
    subject = broker()
    wrong = "000000" if subject.offer.code != "000000" else "111111"
    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(PairingError):
            claim(subject, wrong, peer=PEER, now=100.0)

    subject.open_offer()

    with pytest.raises(PairingError, match=REJECTION_MESSAGE):
        claim(subject, peer=PEER, now=100.0)
    # A second device typing correctly must not pay for the first one.
    assert claim(subject, peer=OTHER, now=100.0).secret


def test_a_lockout_expires():
    subject = broker()
    wrong = "000000" if subject.offer.code != "000000" else "111111"
    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(PairingError):
            claim(subject, wrong, now=100.0)
    subject.open_offer()

    assert claim(subject, now=100.0 + LOCKOUT_SECONDS + 1).secret


def test_cancelling_closes_the_window_immediately():
    subject = broker()

    subject.cancel()

    assert subject.state is OfferState.CANCELLED
    with pytest.raises(PairingError):
        claim(subject)


# -- replay ------------------------------------------------------------


def test_a_retry_after_a_lost_reply_returns_the_same_grant():
    subject = broker()
    nonce = new_nonce()

    first = claim(subject, nonce=nonce)
    second = claim(subject, nonce=nonce)

    # The client cannot tell a lost reply from a rejection, so it retries;
    # issuing a second secret would leave the first one orphaned on the
    # host and the device holding the wrong one.
    assert first == second
    assert first.secret == second.secret


def test_the_same_nonce_from_a_different_peer_is_refused():
    subject = broker()
    nonce = new_nonce()
    claim(subject, nonce=nonce, peer=PEER)

    with pytest.raises(PairingError):
        claim(subject, nonce=nonce, peer=OTHER)


@pytest.mark.parametrize("nonce", ["", None, 1234, "x" * 65])
def test_a_missing_or_oversized_nonce_is_refused(nonce):
    subject = broker()

    with pytest.raises(PairingError):
        subject.claim(code=subject.offer.code, nonce=nonce, peer=PEER)


@pytest.mark.parametrize(
    "payload", [None, [], "code", {"code": 1}, {"nonce": "n"}, {"code": "1", "nonce": 2}]
)
def test_a_malformed_claim_body_is_refused_before_anything_is_compared(payload):
    with pytest.raises(PairingError):
        decode_claim(payload)


# -- the secrets it produces -------------------------------------------


def test_each_device_gets_its_own_secret():
    subject = broker()
    first = claim(subject)
    subject.open_offer()
    second = claim(subject, peer=OTHER)

    assert first.secret != second.secret
    assert first.device_id != second.device_id


def test_a_per_device_secret_authorises_and_names_the_device():
    subject = broker()
    grant = claim(subject)
    policy = AccessPolicy(
        secret="s" * 32, device_secrets=((grant.device_id, grant.secret),)
    )

    assert policy.authorize(PEER, f"Bearer {grant.secret}") == grant.device_id
    # The host-wide secret still works, and is distinguishable in the log.
    assert policy.authorize(PEER, "Bearer " + "s" * 32) == SHARED_DEVICE_ID


def test_revoking_one_device_leaves_the_others_working():
    subject = broker()
    first = claim(subject)
    subject.open_offer()
    second = claim(subject, peer=OTHER)
    devices = (
        PairedDevice(first.device_id, "a", PEER, first.secret, 0.0),
        PairedDevice(second.device_id, "b", OTHER, second.secret, 0.0),
    )

    remaining = forget(devices, first.device_id)
    policy = AccessPolicy(
        secret="s" * 32,
        device_secrets=tuple((item.device_id, item.secret) for item in remaining),
    )

    with pytest.raises(AccessDenied):
        policy.authorize(PEER, f"Bearer {first.secret}")
    assert policy.authorize(OTHER, f"Bearer {second.secret}") == second.device_id


def test_the_device_identifier_matches_the_configuration_layer():
    subject = broker()
    grant = claim(subject)

    # `pairing.identify` is duplicated so the module stays importable
    # without the configuration layer; the two must not drift.
    assert grant.device_id == PairedDevice.identify(grant.secret)


def test_pairing_the_same_host_twice_replaces_rather_than_accumulates():
    subject = broker(host_label="workstation")
    grant = claim(subject)
    devices = remember((), grant, "100.64.0.10")

    again = remember(devices, grant, "100.64.0.11")

    assert len(again) == 1
    assert again[0].address == "100.64.0.11"


def test_an_invalid_device_secret_is_caught_at_startup():
    policy = AccessPolicy(secret="s" * 32, device_secrets=(("abc", "short"),))

    with pytest.raises(ValueError, match="密钥过短"):
        policy.validate()
