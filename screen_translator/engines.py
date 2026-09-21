"""Compatibility exports for the separated inference backends.

New application code should import from ``ocr_engine`` or
``translation_engine`` directly.
"""

from .ocr_engine import (
    KOREAN_REC,
    STANDARD_REC,
    OcrEngine,
    dominant_language,
    prefer_korean,
    representative_indices,
    script_counts,
    text_language,
)
from .translation_engine import TranslationEngine

__all__ = [
    "KOREAN_REC",
    "STANDARD_REC",
    "OcrEngine",
    "TranslationEngine",
    "dominant_language",
    "prefer_korean",
    "representative_indices",
    "script_counts",
    "text_language",
]
