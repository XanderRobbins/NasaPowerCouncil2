"""Shared helpers used by multiple source adapters."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any


_PERIOD_RE = re.compile(r"^(\d+)(d|mo|y)$")


def period_to_dates(period: str) -> tuple[date, date]:
    """Convert a period string like '1mo' to (start, end) dates."""
    today = datetime.now(timezone.utc).date()

    if period == "ytd":
        return date(today.year, 1, 1), today
    if period == "max":
        return date(1970, 1, 1), today

    m = _PERIOD_RE.match(period)
    if not m:
        raise ValueError(f"Invalid period: {period!r}. Use e.g. '1d','5d','1mo','1y'.")

    n, unit = int(m.group(1)), m.group(2)
    if unit == "d":
        start = today - timedelta(days=n)
    elif unit == "mo":
        start = today - timedelta(days=30 * n)
    else:  # y
        start = today - timedelta(days=365 * n)

    return start, today


def date_to_timestamp(d: date) -> int:
    """Convert a date to a POSIX timestamp (seconds) at midnight UTC."""
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def safe_float(value: Any) -> float | None:
    """Coerce value to float, returning None on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    """Coerce value to int, returning None on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_raw(obj: Any) -> Any:
    """Extract the 'raw' value from a Yahoo Finance {raw, fmt} dict."""
    if isinstance(obj, dict):
        return obj.get("raw")
    return obj


def camel_to_title(name: str) -> str:
    """Convert camelCase to Title Case (e.g. 'totalRevenue' -> 'Total Revenue')."""
    s = re.sub(r"([A-Z])", r" \1", name).strip()
    return s.title()
