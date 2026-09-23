"""User-visible feedback: confirmations now, notices as the refactor lands.

The layering here matches the rest of the application. Contracts and domain
types stay free of Qt so that flow-layer code can raise a question or report
an outcome without importing a widget toolkit; only the sink implementations
know what a dialog is.
"""

from .confirm import ConfirmationPort, ConfirmationRequest

__all__ = ["ConfirmationPort", "ConfirmationRequest"]
