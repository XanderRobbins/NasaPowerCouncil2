"""Unit tests for shared source utilities."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from xfinance.sources._utils import (
    camel_to_title,
    date_to_timestamp,
    extract_raw,
    period_to_dates,
    safe_float,
    safe_int,
)


class TestPeriodToDates:
    def test_1d(self):
        start, end = period_to_dates("1d")
        assert (end - start).days == 1

    def test_1mo(self):
        start, end = period_to_dates("1mo")
        assert 28 <= (end - start).days <= 32

    def test_1y(self):
        start, end = period_to_dates("1y")
        assert 364 <= (end - start).days <= 366

    def test_ytd(self):
        start, end = period_to_dates("ytd")
        today = datetime.now(timezone.utc).date()
        assert start == date(today.year, 1, 1)

    def test_max(self):
        start, _ = period_to_dates("max")
        assert start == date(1970, 1, 1)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            period_to_dates("3x")


class TestDateToTimestamp:
    def test_epoch(self):
        assert date_to_timestamp(date(1970, 1, 1)) == 0

    def test_2024_jan_1(self):
        assert date_to_timestamp(date(2024, 1, 1)) == 1704067200

    def test_returns_int(self):
        assert isinstance(date_to_timestamp(date(2024, 6, 15)), int)


class TestSafeFloat:
    def test_valid(self):
        assert safe_float(3.14) == pytest.approx(3.14)

    def test_string(self):
        assert safe_float("42.0") == 42.0

    def test_none(self):
        assert safe_float(None) is None

    def test_invalid_string(self):
        assert safe_float("abc") is None


class TestSafeInt:
    def test_valid(self):
        assert safe_int(42) == 42

    def test_float_truncated(self):
        assert safe_int(3.9) == 3

    def test_none(self):
        assert safe_int(None) is None


class TestExtractRaw:
    def test_extracts_raw_from_dict(self):
        assert extract_raw({"raw": 42, "fmt": "42"}) == 42

    def test_passthrough_non_dict(self):
        assert extract_raw(99) == 99

    def test_none_raw_returns_none(self):
        assert extract_raw({"fmt": "42"}) is None


class TestCamelToTitle:
    def test_simple(self):
        assert camel_to_title("totalRevenue") == "Total Revenue"

    def test_ebit(self):
        assert camel_to_title("ebit") == "Ebit"

    def test_already_lower(self):
        result = camel_to_title("netIncome")
        assert "Net" in result and "Income" in result
