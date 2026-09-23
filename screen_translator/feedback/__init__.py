"""User-visible feedback: confirmations now, notices as the refactor lands.

The layering here matches the rest of the application. Contracts and domain
types stay free of Qt so that flow-layer code can raise a question or report
an outcome without importing a widget toolkit; only the sink implementations
know what a dialog is.
"""

from .center import NoticeCenter, NoticeSink
from .confirm import AlwaysDecline, ConfirmationPort, ConfirmationRequest
from .notices import (
    Lifetime,
    Notice,
    NoticeAction,
    Occupancy,
    Severity,
    Surface,
    error_notice,
    progress_notice,
    route,
    success_notice,
    supersedes,
)

__all__ = [
    "AlwaysDecline",
    "ConfirmationPort",
    "ConfirmationRequest",
    "Lifetime",
    "Notice",
    "NoticeAction",
    "NoticeCenter",
    "NoticeSink",
    "Occupancy",
    "Severity",
    "Surface",
    "error_notice",
    "progress_notice",
    "route",
    "success_notice",
    "supersedes",
]
