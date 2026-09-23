import json

import pytest

from screen_translator.core import (
    Config,
    PairedDevice,
    normalize_allowed_peers,
    normalize_remote_url,
    normalize_service_address,
)

SECRET = "s" * 32


def load(tmp_path, document):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return Config.load(path)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://100.101.102.103:8765", "http://100.101.102.103:8765"),
        ("  http://100.101.102.103:8765/  ", "http://100.101.102.103:8765"),
        ("100.101.102.103:8765", "http://100.101.102.103:8765"),
        ("https://host.tail1234.ts.net", "https://host.tail1234.ts.net"),
        ("http://100.101.102.103:8765/v1/translate", ""),
        ("http://user:pass@100.101.102.103:8765", ""),
        ("file:///etc/passwd", ""),
        ("", ""),
        (None, ""),
        (5, ""),
    ],
)
def test_remote_url_normalisation(raw, expected):
    assert normalize_remote_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("100.101.102.103", "100.101.102.103"),
        ("  127.0.0.1 ", "127.0.0.1"),
        ("auto", "auto"),
        ("", "auto"),
        ("not-an-address", "auto"),
        (None, "auto"),
    ],
)
def test_service_address_normalisation(raw, expected):
    assert normalize_service_address(raw) == expected


def test_allowed_peers_drop_invalid_entries_and_duplicates():
    assert normalize_allowed_peers(
        ["100.101.102.103", " 100.101.102.103 ", "nonsense", 7, "100.64.0.1"]
    ) == ("100.101.102.103", "100.64.0.1")
    assert normalize_allowed_peers("100.101.102.103") == ()
    assert normalize_allowed_peers(None) == ()


def test_a_remote_configuration_round_trips_through_disk(tmp_path):
    path = tmp_path / "config.json"
    saved = Config(
        mode="remote",
        remote_url="http://100.101.102.103:8765",
        remote_token=SECRET,
        service_enabled=True,
        service_address="100.104.105.106",
        service_port=9100,
        service_token=SECRET,
        service_allowed_peers=("100.101.102.103",),
    )
    saved.save(path)

    assert Config.load(path) == saved


def test_a_remote_mode_without_a_host_falls_back_to_local(tmp_path):
    config = load(tmp_path, {"version": 4, "mode": "remote", "remote_url": "", "remote_token": ""})

    assert config.mode == "local"


def test_an_unknown_mode_falls_back_to_local(tmp_path):
    config = load(tmp_path, {"version": 4, "mode": "cloud"})

    assert config.mode == "local"


@pytest.mark.parametrize("port", [80, 1023, 65536, "8765", True, None])
def test_an_invalid_service_port_falls_back_to_the_default(tmp_path, port):
    config = load(tmp_path, {"version": 4, "service_port": port})

    assert config.service_port == 8765


def test_an_oversized_secret_is_discarded(tmp_path):
    config = load(tmp_path, {"version": 4, "service_token": "x" * 1000})

    assert config.service_token == ""


def test_a_non_boolean_service_flag_falls_back_to_disabled(tmp_path):
    config = load(tmp_path, {"version": 4, "service_enabled": "yes"})

    assert config.service_enabled is False


def test_version_four_migrates_without_disturbing_an_existing_setup(tmp_path):
    config = load(
        tmp_path,
        {
            "version": 4,
            "hotkey": "Ctrl+Alt+Q",
            "model_dir": "D:\\AI\\Models",
            "translation_model": "qwen3-8b-q5-k-m",
            "source_language": "zh-Hans",
            "target_language": "en",
            "service_enabled": True,
            "service_token": SECRET,
            "service_allowed_peers": ["100.92.144.26"],
        },
    )

    assert config.version == 5
    # Everything the user already configured survives untouched.
    assert config.hotkey == "Ctrl+Alt+Q"
    assert config.translation_model == "qwen3-8b-q5-k-m"
    assert (config.source_language, config.target_language) == ("zh-Hans", "en")
    assert config.service_allowed_peers == ("100.92.144.26",)
    # An installation that already has a configuration file has been set up,
    # so it must not be shown onboarding.
    assert config.onboarding_completed is True


def test_an_existing_host_secret_becomes_the_first_paired_device(tmp_path):
    config = load(tmp_path, {"version": 4, "service_token": SECRET})

    (device,) = config.paired_devices
    assert device.secret == SECRET
    assert device.device_id == PairedDevice.identify(SECRET)
    # Kept in place as well, so downgrading to 0.7.0 still finds it.
    assert config.service_token == SECRET


def test_a_fresh_configuration_starts_unonboarded():
    assert Config().onboarding_completed is False
    assert Config().paired_devices == ()


@pytest.mark.parametrize(
    "devices",
    [
        "not-a-list",
        [{"label": "no secret"}],
        [{"secret": 5}],
        [{"secret": "x" * 500}],
        [{"secret": "a" * 32, "address": "nonsense"}],
    ],
)
def test_malformed_paired_devices_are_dropped_or_repaired(tmp_path, devices):
    config = load(tmp_path, {"version": 5, "paired_devices": devices})

    for device in config.paired_devices:
        assert device.secret and len(device.secret) <= 256
        assert device.address == "" or device.address.count(".") == 3


def test_duplicate_paired_devices_are_collapsed(tmp_path):
    entry = {"secret": SECRET, "label": "laptop"}

    config = load(tmp_path, {"version": 5, "paired_devices": [entry, dict(entry)]})

    assert len(config.paired_devices) == 1


def test_a_configuration_from_a_newer_version_is_still_refused(tmp_path):
    # The downgrade guard is the documented migration path in both
    # directions: a version 5 file is rejected rather than silently stripped
    # of the cross-device fields this build does not understand.
    with pytest.raises(ValueError, match="更新版本"):
        load(tmp_path, {"version": 99, "mode": "remote"})
