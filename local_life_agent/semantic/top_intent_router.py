"""Explicit top-intent router module.

This is a thin compatibility wrapper around ``intent_parser.py`` so the
module name matches the stage-09 design doc.
"""

from __future__ import annotations

from .intent_parser import TopIntentRouter, parse_top_intent

__all__ = ["TopIntentRouter", "parse_top_intent"]
