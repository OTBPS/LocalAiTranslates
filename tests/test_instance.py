import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.instance import InstanceCoordinator, server_name_for


def qt_app():
    return QApplication.instance() or QApplication([])


def test_server_name_is_stable_and_does_not_expose_profile_path(tmp_path):
    first = server_name_for(tmp_path)
    assert first == server_name_for(tmp_path)
    assert str(tmp_path) not in first
    assert first.startswith("ScreenTranslator.Desktop.")


def test_primary_instance_owns_private_local_server(tmp_path):
    qt_app()
    coordinator = InstanceCoordinator(tmp_path)
    try:
        assert coordinator.acquire_or_notify("ping")
        assert coordinator.server is not None
        assert coordinator.server.isListening()
        assert coordinator.server.socketOptions() == coordinator.server.SocketOption.UserAccessOption
    finally:
        coordinator.close()


def test_instance_command_is_validated(tmp_path):
    qt_app()
    coordinator = InstanceCoordinator(tmp_path)
    try:
        try:
            coordinator.acquire_or_notify("delete-everything")
        except ValueError as error:
            assert "Unsupported instance command" in str(error)
        else:
            raise AssertionError("invalid command was accepted")
    finally:
        coordinator.close()
