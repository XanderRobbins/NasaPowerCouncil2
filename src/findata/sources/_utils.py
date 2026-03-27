"""Shared helpers used by multiple source adapters."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone


_PERIOD_RE = re.compile(r"^(\d+)(d|mo|y|ytd|max)$")

_INTERVAL_MAP = {
    "1d": "1d",
    "1wk": "1wk",
    "1mo": "1mo",
}


def period_to_dates(period: str) -> tuple[date, date]:
    """Convert a period string like '1mo' to (start, end) dates."""
    today = datetime.now(timezone.utc).date()

    if period in ("ytd",):
        return date(today.year, 1, 1), today
    if period in ("max",):
        return date(1970, 1, 1), today

    m = _PERIOD_RE.match(period)
    if not m:
        raise ValueError(f"Invalid period: {period!r}. Use e.g. '1d','5d','1mo','1y'.")

    n, unit = int(m.group(1)), m.group(2)
    if unit == "d":
        start = today - timedelta(days=n)
    elif unit == "mo":
        # Approximate: 30 days per month
        start = today - timedelta(days=30 * n)
    elif unit == "y":
        start = today - timedelta(days=365 * n)
    else:
        raise ValueError(f"Unknown period unit: {unit!r}")

    return start, today


def date_to_timestamp(d: date) -> int:
    """Convert a date to a POSIX timestamp (seconds) at midnight UTC."""
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def safe_float(value: object) -> float | None:
    """Coerce *value* to float, returning None on failure."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
