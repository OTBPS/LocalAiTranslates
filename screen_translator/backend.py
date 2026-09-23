"""Where the models live.

``Backend`` is the seam between the application and a set of engines.  The
capture pipeline does not care whether OCR and translation run on this machine
or on another one across a tailnet, so everything that differs between those
two worlds — construction, readiness, teardown — is collected here instead of
being spread through the controller as ``models_ready`` calls and mode checks.
"""

from __future__ import annotations

from typing import Protocol

from .capabilities import describe_missing_runtime, local_runtime_available
from .contracts import OcrPort, TranslationPort
from .core import Config
from .models import models_ready
from .ocr_engine import OcrEngine
from .translation_engine import TranslationEngine

LOCAL = "local"
REMOTE = "remote"


class Backend(Protocol):
    """One OCR engine, one translation engine, and their shared readiness."""

    kind: str
    ocr: OcrPort
    translator: TranslationPort

    def ready(self) -> bool:
        """Cheap, non-blocking: polled from the UI thread on every hotkey press."""
        ...

    def refresh(self) -> None:
        """Update any cached readiness. Called from a background task only."""
        ...

    def describe(self) -> str:
        """One line for the settings window."""
        ...

    def stop(self) -> None: ...


class LocalBackend:
    """Models on this machine, the original single-device behaviour."""

    kind = LOCAL

    def __init__(
        self,
        config: Config,
        *,
        ocr_factory=OcrEngine,
        translator_factory=TranslationEngine,
    ):
        self._model_dir = config.model_dir
        self._model_id = config.translation_model
        self.ocr: OcrPort = ocr_factory(config.model_dir, config.allow_cpu)
        self.translator: TranslationPort = translator_factory(
            config.model_dir, config.allow_cpu, config.translation_model
        )

    def ready(self) -> bool:
        return local_runtime_available() and models_ready(self._model_dir, self._model_id)

    def refresh(self) -> None:
        """Nothing to cache: ``ready`` already reads live state for the price
        of a directory listing and a few ``stat`` calls."""

    def describe(self) -> str:
        missing = describe_missing_runtime()
        if missing:
            return missing
        return "本地模型就绪" if self.ready() else "本地模型未下载"

    def stop(self) -> None:
        self.translator.stop()


def create_backend(config: Config) -> Backend:
    """Composition root for engine selection.

    Remote mode fails loudly on a missing address or secret rather than
    quietly falling back to local models, which would silently change which
    machine the user's screen content is sent to.
    """
    if config.mode != REMOTE:
        return LocalBackend(config)
    from .remote.client import RemoteBackend

    if not config.remote_url.strip():
        raise ValueError("远程模式需要填写主机地址")
    if not config.remote_token.strip():
        raise ValueError("远程模式需要填写配对密钥")
    return RemoteBackend(config.remote_url.strip(), config.remote_token.strip())
