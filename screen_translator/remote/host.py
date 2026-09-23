"""Binding the host service to the running application.

Kept out of ``controller`` deliberately: the controller is already the widest
module in the project, and the rules for when a listener should exist are
self-contained.  This object translates configuration changes into service
lifecycle transitions and nothing else.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from ..contracts import OcrPort
from ..core import Config
from ..inference import InferenceCoordinator
from ..tasks import TaskRunner
from .access import AccessPolicy
from .pairing import PairingBroker, PairingGrant, PairingOffer
from .service import (
    RemoteService,
    ServiceState,
    ServiceStatus,
    TranslationService,
)

LOGGER = logging.getLogger(__name__)


class HostService:
    """Start, stop and restart the listener as configuration changes."""

    def __init__(
        self,
        *,
        ocr_provider: Callable[[], OcrPort],
        ready_provider: Callable[[], bool],
        model_provider: Callable[[], str],
        inference: InferenceCoordinator,
        tasks: TaskRunner,
        service_factory=RemoteService,
        # Called with a fresh grant so the owner can persist it. The
        # listener never touches configuration itself.
        on_paired: Callable[[PairingGrant, str], None] | None = None,
    ):
        self._service = TranslationService(
            ocr_provider=ocr_provider,
            inference=inference,
            ready_provider=ready_provider,
            model_provider=model_provider,
        )
        self._tasks = tasks
        self._service_factory = service_factory
        self._on_paired = on_paired or (lambda _grant, _peer: None)
        self._running: RemoteService | None = None
        self._signature: tuple[object, ...] | None = None
        self._status = ServiceStatus()

    @property
    def status(self) -> ServiceStatus:
        return self._running.status if self._running else self._status

    @property
    def broker(self) -> PairingBroker | None:
        """The open pairing window, or None when the listener is not up."""
        return self._running.broker if self._running else None

    def offer_pairing(self, host_label: str = "") -> PairingOffer | None:
        """Open a window and return the code to read out loud."""
        broker = self.broker
        if broker is None:
            return None
        broker.host_label = host_label
        return broker.open_offer()

    def cancel_pairing(self) -> None:
        broker = self.broker
        if broker is not None:
            broker.cancel()

    @staticmethod
    def _signature_of(config: Config) -> tuple[object, ...]:
        return (
            config.service_address,
            config.service_port,
            config.service_token,
            tuple(config.service_allowed_peers),
        )

    @staticmethod
    def _rejection(config: Config) -> str | None:
        """Why this configuration must not serve other devices."""
        if not config.service_enabled:
            return "远程服务未启用"
        if config.mode != "local":
            # Chaining hosts would send the same screenshot through two hops
            # and make the inference slot impossible to reason about.
            return "远程模式下无法同时作为主机，请先切换回本地模型"
        if not config.service_token:
            return "远程服务需要配对密钥"
        return None

    def apply(self, config: Config) -> ServiceStatus:
        """Make the listener match ``config``. Safe to call on every save."""
        rejection = self._rejection(config)
        if rejection is not None:
            self.stop()
            self._status = ServiceStatus(detail=rejection)
            return self._status
        signature = self._signature_of(config)
        if self._running is not None and signature == self._signature:
            # Per-device secrets are swapped into the live policy rather
            # than counted in the signature: restarting the listener the
            # instant a device pairs would drop the connection that just
            # paired with it.
            self._running.set_device_secrets(config.paired_devices)
            return self._running.status
        self.stop()
        policy = AccessPolicy(
            secret=config.service_token,
            allowed_peers=frozenset(config.service_allowed_peers),
            device_secrets=tuple(
                (device.device_id, device.secret) for device in config.paired_devices
            ),
        )
        service = self._service_factory(
            self._service,
            policy,
            self._tasks,
            address=config.service_address,
            port=config.service_port,
            on_paired=self._on_paired,
        )
        status = service.start()
        if status.state == ServiceState.RUNNING:
            self._running = service
            self._signature = signature
        else:
            self._status = status
        return status

    def stop(self) -> None:
        running, self._running = self._running, None
        self._signature = None
        if running is not None:
            running.stop()
            LOGGER.info("Remote service stopped")
