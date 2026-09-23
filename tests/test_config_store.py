"""The store is the only place configuration changes, so it validates."""

from dataclasses import replace

import pytest

from screen_translator.config_store import ConfigStore
from screen_translator.core import Config, PairedDevice

SECRET = "s" * 32


def store(config=None):
    written = []
    return ConfigStore(config or Config(), writer=written.append), written


def test_an_update_is_persisted_once_and_announced():
    subject, written = store()
    seen = []
    subject.changed.connect(seen.append)

    result = subject.update(target_language="en")

    assert result.target_language == "en"
    assert subject.current is result
    assert [config.target_language for config in written] == ["en"]
    assert [config.target_language for config in seen] == ["en"]


def test_an_update_that_changes_nothing_is_not_written():
    subject, written = store()
    seen = []
    subject.changed.connect(seen.append)

    subject.update(target_language=Config().target_language)

    assert written == []
    assert seen == []


def test_an_unknown_field_is_rejected_before_anything_is_written():
    subject, written = store()

    with pytest.raises(ValueError, match="未知的配置字段"):
        subject.update(colour_scheme="dark")

    assert written == []


def test_invalid_values_are_normalised_rather_than_stored():
    subject, _written = store()

    result = subject.update(target_language="fr", service_port=80)

    # Normalisation is what keeps an invalid value from surviving to disk and
    # only being discovered on the next load.
    assert result.target_language == Config().target_language
    assert result.service_port == Config().service_port


def test_adopting_a_configuration_normalises_it_too():
    subject, written = store()

    result = subject.adopt(replace(Config(), source_language="klingon"))

    assert result.source_language == Config().source_language
    assert written == []  # normalised back to the current value, so no write


def test_a_remote_configuration_without_a_host_falls_back_to_local():
    subject, _written = store()

    result = subject.update(mode="remote")

    assert result.mode == "local"


def test_paired_devices_survive_a_round_trip(tmp_path):
    path = tmp_path / "config.json"
    device = PairedDevice(
        device_id="abc123", label="laptop", address="100.64.0.20",
        secret=SECRET, paired_at=1.0, last_seen=2.0,
    )

    Config(paired_devices=(device,)).save(path)
    loaded = Config.load(path)

    assert loaded.paired_devices == (device,)
    assert isinstance(loaded.paired_devices[0], PairedDevice), "must not stay a dict"
