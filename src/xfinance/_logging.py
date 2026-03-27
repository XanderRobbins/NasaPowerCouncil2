"""Logging setup for xfinance."""

from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"xfinance.{name}")


def configure_logging(level: int | str = logging.WARNING) -> None:
    """Configure the xfinance root logger."""
    root = logging.getLogger("xfinance")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        )
        root.addHandler(handler)
    root.setLevel(level)
