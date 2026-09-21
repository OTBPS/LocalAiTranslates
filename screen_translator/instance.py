"""Single-instance coordination and local activation commands."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QThread, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .native import allow_set_foreground_window

VALID_COMMANDS = frozenset({"ping", "show-settings"})


def server_name_for(data_directory: Path) -> str:
    """Return a stable, per-user server name without exposing the profile path."""
    normalized = str(data_directory.resolve()).casefold().encode("utf-8")
    suffix = hashlib.sha256(normalized).hexdigest()[:16]
    return f"ScreenTranslator.Desktop.{suffix}"


class InstanceCoordinator(QObject):
    """Own the process lock and relay commands from later launches."""

    command_received = Signal(str)

    def __init__(self, data_directory: Path):
        super().__init__()
        self.data_directory = data_directory
        self.lock = QLockFile(str(data_directory / "instance.lock"))
        self.server_name = server_name_for(data_directory)
        self.server: QLocalServer | None = None
        self._clients: set[QLocalSocket] = set()

    def acquire_or_notify(self, command: str) -> bool:
        """Become the primary instance, or notify it and return ``False``."""
        if command not in VALID_COMMANDS:
            raise ValueError(f"Unsupported instance command: {command}")
        self.data_directory.mkdir(parents=True, exist_ok=True)
        if self.lock.tryLock(0):
            self._listen()
            return True

        if self._notify_primary(command):
            return False

        # QLockFile validates the recorded PID before removing a stale file.
        if self.lock.removeStaleLockFile() and self.lock.tryLock(0):
            self._listen()
            return True

        # A primary process may hold the lock briefly before its local server is ready.
        self._notify_primary(command, attempts=4)
        return False

    def _listen(self) -> None:
        QLocalServer.removeServer(self.server_name)
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self.server_name):
            self.lock.unlock()
            raise RuntimeError(f"无法创建本地单实例服务：{server.errorString()}")
        server.newConnection.connect(self._accept_connections)
        self.server = server

    def _accept_connections(self) -> None:
        if self.server is None:
            return
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._clients.add(socket)
            socket.disconnected.connect(lambda client=socket: self._discard_client(client))
            socket.readyRead.connect(lambda client=socket: self._read_client(client))
            socket.write(
                (json.dumps({"status": "ready", "pid": os.getpid()}) + "\n").encode("utf-8")
            )
            socket.flush()

    def _discard_client(self, socket: QLocalSocket) -> None:
        self._clients.discard(socket)
        socket.deleteLater()

    def _read_client(self, socket: QLocalSocket) -> None:
        if socket.bytesAvailable() > 4096:
            socket.abort()
            return
        while socket.canReadLine():
            try:
                payload = json.loads(bytes(socket.readLine()).decode("utf-8"))
                command = payload.get("command")
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                command = None
            if command not in VALID_COMMANDS:
                socket.write(b'{"status":"error"}\n')
            else:
                if command != "ping":
                    self.command_received.emit(command)
                socket.write(b'{"status":"ok"}\n')
            socket.flush()

    def _notify_primary(self, command: str, attempts: int = 3) -> bool:
        for attempt in range(attempts):
            socket = QLocalSocket()
            socket.connectToServer(self.server_name)
            if not socket.waitForConnected(300):
                if attempt + 1 < attempts:
                    QThread.msleep(80)
                continue
            if not socket.waitForReadyRead(500):
                socket.abort()
                continue
            try:
                hello = json.loads(bytes(socket.readLine()).decode("utf-8"))
                primary_pid = int(hello["pid"])
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                socket.abort()
                continue
            allow_set_foreground_window(primary_pid)
            socket.write((json.dumps({"command": command}) + "\n").encode("utf-8"))
            if not socket.waitForBytesWritten(300) or not socket.waitForReadyRead(800):
                socket.abort()
                continue
            try:
                response = json.loads(bytes(socket.readLine()).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                response = {}
            socket.disconnectFromServer()
            return response.get("status") == "ok"
        return False

    def close(self) -> None:
        for socket in tuple(self._clients):
            socket.abort()
        self._clients.clear()
        if self.server is not None:
            self.server.close()
            QLocalServer.removeServer(self.server_name)
            self.server = None
        self.lock.unlock()
