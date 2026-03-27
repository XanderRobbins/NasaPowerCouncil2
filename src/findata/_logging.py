"""Structured logging setup for findata."""

from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'findata' namespace."""
    return logging.getLogger(f"findata.{name}")


def configure_logging(level: int | str = logging.WARNING) -> None:
    """Configure the findata root logger.

    Call this in your application startup if you want findata log output.
    By default the library is silent (no handlers attached).
    """
    root = logging.getLogger("findata")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        )
        root.addHandler(handler)
    root.setLevel(level)
