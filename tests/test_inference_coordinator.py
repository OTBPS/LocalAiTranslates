import threading
from types import SimpleNamespace

import pytest

from screen_translator.core import CancellationToken
from screen_translator.inference import (
    CAPTURE,
    MANUAL,
    InferenceBusy,
    InferenceCoordinator,
)


def coordinator(port=None):
    port = port or SimpleNamespace(mode="CUDA")
    return InferenceCoordinator(lambda: port), port


def test_manual_reservation_yields_the_current_engine_and_releases_it():
    arbiter, port = coordinator()

    with arbiter.reserve(MANUAL) as reserved:
        assert reserved is port
        assert arbiter.owner == MANUAL

    assert arbiter.owner is None


def test_provider_is_consulted_on_every_reservation():
    engines = [SimpleNamespace(mode="a"), SimpleNamespace(mode="b")]
    arbiter = InferenceCoordinator(lambda: engines[-1])

    with arbiter.reserve(MANUAL) as first:
        assert first is engines[1]
    engines.append(SimpleNamespace(mode="c"))
    with arbiter.reserve(MANUAL) as second:
        assert second is engines[2]


def test_manual_is_refused_while_a_capture_is_active():
    arbiter, _port = coordinator()
    arbiter.begin_capture()

    with pytest.raises(InferenceBusy, match="截图翻译"):
        with arbiter.reserve(MANUAL):
            pass

    arbiter.end_capture()
    with arbiter.reserve(MANUAL):
        pass


def test_beginning_a_capture_cancels_an_in_flight_manual_translation():
    arbiter, _port = coordinator()
    token = CancellationToken()
    arbiter.register_manual(token)

    assert arbiter.begin_capture() is True
    assert token.event.is_set()
    assert arbiter.cancel_manual() is False


def test_capture_reservation_cancels_the_manual_token_before_waiting():
    arbiter, _port = coordinator()
    token = CancellationToken()
    arbiter.register_manual(token)

    with arbiter.reserve(CAPTURE):
        assert token.event.is_set()
        assert arbiter.owner == CAPTURE


def test_capture_gives_up_when_the_slot_stays_held():
    arbiter, _port = coordinator()
    held = threading.Event()
    done = threading.Event()

    def hold():
        with arbiter.reserve(MANUAL):
            held.set()
            done.wait(2)

    worker = threading.Thread(target=hold)
    worker.start()
    held.wait(2)
    try:
        with pytest.raises(InferenceBusy, match="正忙"):
            with arbiter.reserve(CAPTURE, timeout=0.05):
                pass
    finally:
        done.set()
        worker.join(2)

    with arbiter.reserve(CAPTURE, timeout=0.05):
        pass


def test_slot_is_released_when_the_body_raises():
    arbiter, _port = coordinator()

    with pytest.raises(ZeroDivisionError):
        with arbiter.reserve(MANUAL):
            raise ZeroDivisionError

    assert arbiter.owner is None
    with arbiter.reserve(MANUAL):
        pass


def test_release_manual_only_clears_the_matching_token():
    arbiter, _port = coordinator()
    first = CancellationToken()
    second = CancellationToken()
    arbiter.register_manual(second)

    arbiter.release_manual(first)
    assert arbiter.cancel_manual() is True

    arbiter.register_manual(second)
    arbiter.release_manual(second)
    assert arbiter.cancel_manual() is False


def test_unknown_owner_is_rejected():
    arbiter, _port = coordinator()

    with pytest.raises(ValueError, match="unknown inference owner"):
        with arbiter.reserve("background"):
            pass
