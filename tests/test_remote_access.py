import json
from pathlib import Path

import pytest

from screen_translator.remote.access import (
    AccessDenied,
    AccessPolicy,
    generate_secret,
    is_tailnet_address,
    parse_bearer,
)
from screen_translator.remote.tailnet import parse_addresses, parse_peer_route

SECRET = "s" * 32

# Recorded from a real machine, not written by hand. See tests/data/README.md.
DATA = Path(__file__).resolve().parent / "data"
TAILSCALE_STATUS = json.loads((DATA / "tailscale_status.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "address",
    ["100.64.0.1", "100.101.102.103", "100.127.255.254", "fd7a:115c:a1e0::1", "::ffff:100.64.0.5"],
)
def test_tailnet_addresses_are_recognised(address):
    assert is_tailnet_address(address)


@pytest.mark.parametrize(
    "address",
    ["192.168.1.10", "10.0.0.1", "100.63.255.255", "100.128.0.1", "8.8.8.8", "::1", "nonsense", ""],
)
def test_other_addresses_are_not_tailnet_addresses(address):
    assert not is_tailnet_address(address)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer abc", "abc"),
        ("bearer abc", "abc"),
        ("BEARER  abc  ", "abc"),
        ("Basic abc", ""),
        ("abc", ""),
        (None, ""),
        (5, ""),
    ],
)
def test_bearer_parsing(header, expected):
    assert parse_bearer(header) == expected


def test_a_tailnet_peer_with_the_right_token_is_allowed():
    AccessPolicy(SECRET).authorize("100.101.102.103", f"Bearer {SECRET}")


def test_a_peer_outside_the_tailnet_is_refused_even_with_the_right_token():
    with pytest.raises(AccessDenied, match="peer-not-on-tailnet"):
        AccessPolicy(SECRET).authorize("192.168.1.10", f"Bearer {SECRET}")


def test_a_tailnet_peer_with_the_wrong_token_is_refused():
    with pytest.raises(AccessDenied, match="invalid-token"):
        AccessPolicy(SECRET).authorize("100.101.102.103", "Bearer wrong")


def test_a_missing_authorization_header_is_refused():
    with pytest.raises(AccessDenied, match="invalid-token"):
        AccessPolicy(SECRET).authorize("100.101.102.103", None)


def test_an_allow_list_narrows_the_tailnet_to_named_devices():
    policy = AccessPolicy(SECRET, allowed_peers=frozenset({"100.101.102.103"}))

    policy.authorize("100.101.102.103", f"Bearer {SECRET}")
    with pytest.raises(AccessDenied, match="peer-not-allowed"):
        policy.authorize("100.64.0.9", f"Bearer {SECRET}")


def test_loopback_is_allowed_for_self_test_but_still_needs_the_token():
    policy = AccessPolicy(SECRET, allowed_peers=frozenset({"100.101.102.103"}))

    policy.authorize("127.0.0.1", f"Bearer {SECRET}")
    with pytest.raises(AccessDenied, match="invalid-token"):
        policy.authorize("127.0.0.1", "Bearer wrong")


def test_the_host_may_reach_its_own_service_despite_its_own_allow_list():
    # Connecting to the bound tailnet address from the host carries that
    # address as the source, so a self-test would otherwise be refused by the
    # allow-list the host itself configured.
    policy = AccessPolicy(
        SECRET,
        allowed_peers=frozenset({"100.92.144.26"}),
        local_address="100.100.119.102",
    )

    policy.authorize("100.100.119.102", f"Bearer {SECRET}")
    policy.authorize("100.92.144.26", f"Bearer {SECRET}")
    with pytest.raises(AccessDenied, match="peer-not-allowed"):
        policy.authorize("100.64.0.9", f"Bearer {SECRET}")


def test_reaching_the_host_address_still_requires_the_secret():
    policy = AccessPolicy(SECRET, local_address="100.100.119.102")

    with pytest.raises(AccessDenied, match="invalid-token"):
        policy.authorize("100.100.119.102", "Bearer wrong")


def test_an_unset_local_address_grants_nothing():
    policy = AccessPolicy(SECRET, allowed_peers=frozenset({"100.92.144.26"}))

    with pytest.raises(AccessDenied, match="peer-not-allowed"):
        policy.authorize("100.100.119.102", f"Bearer {SECRET}")


def test_loopback_can_be_refused_explicitly():
    with pytest.raises(AccessDenied, match="peer-not-on-tailnet"):
        AccessPolicy(SECRET, allow_loopback=False).authorize("127.0.0.1", f"Bearer {SECRET}")


def test_a_weak_or_missing_secret_is_rejected_at_startup():
    with pytest.raises(ValueError, match="共享密钥"):
        AccessPolicy("").validate()
    with pytest.raises(ValueError, match="共享密钥"):
        AccessPolicy("short").validate()
    AccessPolicy(SECRET).validate()


def test_an_allow_list_entry_off_the_tailnet_is_rejected_at_startup():
    with pytest.raises(ValueError, match="非 Tailscale 地址"):
        AccessPolicy(SECRET, allowed_peers=frozenset({"192.168.1.10"})).validate()


def test_generated_secrets_are_long_and_unique():
    first, second = generate_secret(), generate_secret()
    assert first != second
    assert len(first) >= 32
    AccessPolicy(first).validate()


def test_tailscale_ip_output_is_filtered_to_tailnet_addresses():
    assert parse_addresses("100.101.102.103\n") == ["100.101.102.103"]
    assert parse_addresses("192.168.1.5\n100.64.0.1\n") == ["100.64.0.1"]
    assert parse_addresses("command not found") == []


def test_a_direct_peer_is_not_reported_as_relayed():
    """The regression this fixture exists for.

    `Relay` names the peer's home DERP region and is populated even when the
    connection is direct, so a classifier that reads it first calls every
    direct peer relayed. The previous hand-written fixture assumed a direct
    peer reports `Relay: ""`, which Tailscale never does, so it confirmed the
    bug instead of catching it.
    """
    peer = next(
        item
        for item in TAILSCALE_STATUS["Peer"].values()
        if item["HostName"] == "laptop"
    )
    assert peer["CurAddr"] and peer["Relay"], "fixture must keep both fields set"

    assert parse_peer_route(TAILSCALE_STATUS, "100.64.0.20") == "direct"


def test_peer_route_classification():
    assert parse_peer_route(TAILSCALE_STATUS, "100.64.0.20") == "direct"
    assert parse_peer_route(TAILSCALE_STATUS, "100.64.0.30") == "relay"
    assert parse_peer_route(TAILSCALE_STATUS, "100.64.0.40") == "relay"
    assert parse_peer_route(TAILSCALE_STATUS, "100.1.1.1") == "unknown"
    assert parse_peer_route("not-a-document", "100.64.0.20") == "unknown"


def test_the_recorded_fixture_carries_no_identifying_values():
    text = (DATA / "tailscale_status.json").read_text(encoding="utf-8")

    for leaked in ("tail39ac8f", "cnpengbo", "outlook.com", "100.100.", "100.92.", "172.20."):
        assert leaked not in text, f"fixture leaks {leaked}; see tests/data/README.md"
