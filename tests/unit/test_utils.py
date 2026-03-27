"""Unit tests for internal utility functions."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from findata.sources._utils import date_to_timestamp, period_to_dates, safe_float


class TestPeriodToDates:
    def test_1d(self):
        start, end = period_to_dates("1d")
        assert (end - start).days == 1

    def test_1mo(self):
        start, end = period_to_dates("1mo")
        diff = (end - start).days
        assert 28 <= diff <= 32

    def test_1y(self):
        start, end = period_to_dates("1y")
        diff = (end - start).days
        assert 364 <= diff <= 366

    def test_ytd(self):
        start, end = period_to_dates("ytd")
        today = datetime.now(timezone.utc).date()
        assert start == date(today.year, 1, 1)
        assert end == today

    def test_max(self):
        start, end = period_to_dates("max")
        assert start == date(1970, 1, 1)

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError, match="Invalid period"):
            period_to_dates("3x")

    def test_5d(self):
        start, end = period_to_dates("5d")
        assert (end - start).days == 5


class TestDateToTimestamp:
    def test_known_epoch(self):
        ts = date_to_timestamp(date(1970, 1, 1))
        assert ts == 0

    def test_2024_jan_1(self):
        ts = date_to_timestamp(date(2024, 1, 1))
        assert ts == 1704067200  # 2024-01-01T00:00:00Z

    def test_returns_int(self):
        ts = date_to_timestamp(date(2024, 6, 15))
        assert isinstance(ts, int)


class TestSafeFloat:
    def test_valid_number(self):
        assert safe_float(3.14) == pytest.approx(3.14)

    def test_string_number(self):
        assert safe_float("42.0") == 42.0

    def test_none_returns_none(self):
        assert safe_float(None) is None

    def test_invalid_string_returns_none(self):
        assert safe_float("abc") is None

    def test_nan_converts(self):
        import math
        result = safe_float(float("nan"))
        assert result is not None
        assert math.isnan(result)
