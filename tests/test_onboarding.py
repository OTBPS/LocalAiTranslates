"""First run, as a pure function.

What a new installation was told used to depend on a boolean threaded
through two layers, and the only way to check it was to reinstall. All of
it is decided here from four observable facts.
"""

import pytest

from screen_translator.core import LOCAL_MODE, REMOTE_MODE, Config
from screen_translator.models import TRANSLATION_MODELS
from screen_translator.navigation import Destination
from screen_translator.onboarding import (
    Stage,
    StartupIntent,
    evaluate,
    intent_from_arguments,
)


def plan(**kwargs):
    defaults = {
        "backend_ready": False,
        "local_runtime": True,
        "intent": StartupIntent.LAUNCH,
    }
    config = kwargs.pop("config", Config(mode=LOCAL_MODE))
    return evaluate(config, **{**defaults, **kwargs})


def test_a_working_installation_is_told_nothing():
    result = plan(backend_ready=True)

    assert result.stage is Stage.READY
    assert result.blocking is False
    assert result.open_settings is False


def test_missing_weights_point_at_the_download_button():
    result = plan()

    # Not the tray balloon Windows may swallow, and not "whichever tab the
    # window was last showing" -- the control that fixes it.
    assert result.stage is Stage.NEEDS_MODEL
    assert result.destination is Destination.MODEL_DOWNLOAD
    assert result.open_settings is True


def test_the_download_size_is_named_before_the_user_commits():
    model = TRANSLATION_MODELS["qwen3-14b-q5-k-m"]

    result = plan(config=Config(translation_model=model.model_id))

    # 10.5 GB was the silent default; the number has to be on screen
    # before the button is pressed, not after.
    assert "10.5 GB" in result.detail
    assert model.display_name in result.detail


@pytest.mark.parametrize("model_id", list(TRANSLATION_MODELS))
def test_every_model_can_describe_its_own_download(model_id):
    result = plan(config=Config(translation_model=model_id))

    assert TRANSLATION_MODELS[model_id].display_name in result.detail


def test_a_thin_client_is_sent_to_the_host_settings_not_the_downloader():
    result = plan(local_runtime=False)

    # This build has no llama.cpp to feed; downloading weights would be
    # several gigabytes spent on nothing.
    assert result.stage is Stage.NEEDS_REMOTE
    assert result.destination is Destination.REMOTE_MODE


def test_a_configured_host_that_is_down_says_so_rather_than_offering_a_download():
    result = plan(
        config=Config(mode=REMOTE_MODE, remote_url="http://host:8765", remote_token="x" * 43)
    )

    assert result.stage is Stage.HOST_UNREACHABLE
    assert result.destination is Destination.REMOTE_PAIRING


def test_a_login_launch_never_opens_a_window():
    result = plan(intent=StartupIntent.AUTOSTART)

    # The installation is still broken and the tray still says so; what
    # must not happen is a window appearing on a machine the user has not
    # touched yet.
    assert result.blocking is True
    assert result.open_settings is False
    assert result.title


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["app.exe", "--autostart"], StartupIntent.AUTOSTART),
        (["app.exe", "--show-settings"], StartupIntent.ACTIVATE),
        (["app.exe"], StartupIntent.LAUNCH),
    ],
)
def test_the_launch_reason_is_read_rather_than_guessed(arguments, expected):
    assert intent_from_arguments(arguments) is expected


def test_every_blocking_stage_offers_a_way_out():
    for result in (
        plan(),
        plan(local_runtime=False),
        plan(config=Config(mode=REMOTE_MODE, remote_url="http://h:1", remote_token="x" * 43)),
    ):
        assert result.blocking
        # The whole point: a message that states the problem and not the
        # remedy leaves the reader to hunt through three tabs.
        assert result.destination is not None
        assert result.action_label
        assert result.title and result.detail
