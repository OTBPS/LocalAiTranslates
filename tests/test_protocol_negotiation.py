"""Two builds one version apart have to keep working.

Both ends used to compare the version for exact equality, so raising the
number would have been a flag day: a v2 host and a v0.7.0 client would
refuse each other, and the user who updated one machine first would have
no way to tell which half was wrong. Negotiation therefore ships before
the first feature that needs a new version.
"""

import pytest

from screen_translator.remote.protocol import (
    LEGACY_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    describe_version_mismatch,
    negotiate,
    parse_version,
)


def test_version_one_is_still_spoken():
    # v0.7.0 is in the field on real machines; dropping it silently
    # bricks every pair that updates one side.
    assert LEGACY_PROTOCOL_VERSION in SUPPORTED_PROTOCOL_VERSIONS
    assert PROTOCOL_VERSION == max(SUPPORTED_PROTOCOL_VERSIONS)


@pytest.mark.parametrize("version", SUPPORTED_PROTOCOL_VERSIONS)
def test_a_version_both_ends_know_is_used_as_is(version):
    assert negotiate(str(version)) == version
    assert negotiate(version) == version


def test_a_missing_header_means_the_oldest_version():
    # Only a v1 build omits it, because v1 is when the header appeared.
    assert negotiate(None) == LEGACY_PROTOCOL_VERSION


def test_a_newer_peer_is_answered_at_our_best_rather_than_refused():
    # The newer side is required to be able to fall back; refusing it
    # would strand the older half of a rolling upgrade.
    assert negotiate(PROTOCOL_VERSION + 5) == PROTOCOL_VERSION


def test_a_version_below_everything_we_speak_has_no_common_ground():
    assert negotiate(0) is None
    assert negotiate(0, supported=(2,)) is None


def test_an_old_build_meeting_a_new_one_settles_on_the_old_version():
    # The client's half of the same handshake: it knows only 1.
    assert negotiate(2, supported=(1,)) == 1


@pytest.mark.parametrize(
    "value", ["", "  ", "abc", "1.0", "-1", "99999999", [], {}, 1.5, True]
)
def test_an_unreadable_version_is_refused_rather_than_coerced(value):
    # The header arrives from another machine; "2abc" must not become 2.
    assert parse_version(value) is None
    assert negotiate(value) is None


def test_the_mismatch_message_names_both_sides():
    message = describe_version_mismatch(0)

    assert "0" in message
    assert str(PROTOCOL_VERSION) in message
