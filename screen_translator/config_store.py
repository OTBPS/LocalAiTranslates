"""The single write path for user configuration.

Before this existed, configuration was a plain attribute on ``Controller``
that several places assigned to directly, and keeping views in sync meant
reloading the whole settings form — which silently discarded whatever the
user had typed and not yet saved. A store with one mutator and one signal
replaces "reload everything" with "tell me what changed".
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import fields, replace

from PySide6.QtCore import QObject, Signal

from .core import Config

LOGGER = logging.getLogger(__name__)

_FIELD_NAMES = frozenset(item.name for item in fields(Config))


class ConfigStore(QObject):
    """Hold the current configuration and announce validated changes."""

    changed = Signal(object)  # Config

    def __init__(
        self,
        config: Config | None = None,
        *,
        writer: Callable[[Config], None] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._config = (config or Config.load()).normalized()
        self._writer = writer if writer is not None else _save

    @property
    def current(self) -> Config:
        return self._config

    def update(self, **changes: object) -> Config:
        """Apply field changes, persist them, and announce the result.

        Values are normalised before they are stored, so an invalid value is
        rejected here rather than surviving until the next load. Returns the
        stored configuration, which may differ from what was requested.
        """
        unknown = set(changes) - _FIELD_NAMES
        if unknown:
            raise ValueError(f"未知的配置字段：{', '.join(sorted(unknown))}")
        candidate = replace(self._config, **changes).normalized()
        return self.adopt(candidate)

    def adopt(self, config: Config) -> Config:
        """Store an already-built configuration. No-op when nothing changed."""
        candidate = config.normalized()
        if candidate == self._config:
            return self._config
        self._writer(candidate)
        self._config = candidate
        self.changed.emit(candidate)
        return candidate

    def reload(self) -> Config:
        """Re-read from disk, for example after an external repair."""
        return self.adopt(Config.load())


def _save(config: Config) -> None:
    config.save()
