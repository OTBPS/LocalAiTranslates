"""Cross-device translation: one device captures, another runs the models.

The packages below must stay importable without Qt, OpenCV, PaddleOCR or
llama.cpp so that a headless host service and a client build shipping no model
runtime can both use them.  Only :mod:`screen_translator.remote.client` and
:mod:`screen_translator.remote.service` touch the network.
"""

from .protocol import PROTOCOL_VERSION, ProtocolError

__all__ = ["PROTOCOL_VERSION", "ProtocolError"]
