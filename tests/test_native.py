from unittest.mock import patch

import pytest

from screen_translator.native import Hotkey, hotkey_parts


def test_hotkey_parser():
    assert hotkey_parts("Ctrl+Alt+T") == (0x4003, ord("T"))
    assert hotkey_parts("Ctrl+F12")[1] == 0x7B
    with pytest.raises(ValueError):
        hotkey_parts("T")


def test_hotkey_conflict_keeps_previous():
    with patch("screen_translator.native.user32") as native:
        native.RegisterHotKey.return_value = True
        hotkey = Hotkey(lambda: None)
        hotkey.register("Ctrl+Alt+T")
        old_id = hotkey.key_id
        native.RegisterHotKey.return_value = False
        with pytest.raises(ValueError):
            hotkey.register("Ctrl+Alt+Q")
        assert hotkey.current == "Ctrl+Alt+T" and hotkey.key_id == old_id
