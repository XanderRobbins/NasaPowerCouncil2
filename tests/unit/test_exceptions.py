"""Unit tests for xfinance exception hierarchy."""

from __future__ import annotations

import pytest

from xfinance.exceptions import (
    AllSourcesFailedError,
    DataValidationError,
    MissingDependencyError,
    SourceAuthError,
    SourceRateLimitError,
    SourceUnavailableError,
    SymbolNotFoundError,
    XFinanceError,
)


def test_source_unavailable():
    exc = SourceUnavailableError("yahoo", "Network error")
    assert exc.source == "yahoo"
    assert "yahoo" in str(exc)
    assert isinstance(exc, XFinanceError)


def test_rate_limit_with_retry_after():
    exc = SourceRateLimitError("finnhub", retry_after=30.0)
    assert exc.retry_after == 30.0
    assert "30" in str(exc)
    assert exc.status_code == 429


def test_rate_limit_without_retry_after():
    exc = SourceRateLimitError("yahoo")
    assert exc.retry_after is None


def test_symbol_not_found():
    exc = SymbolNotFoundError("yahoo", "FOOBAR")
    assert exc.symbol == "FOOBAR"
    assert "FOOBAR" in str(exc)


def test_auth_error():
    exc = SourceAuthError("alphavantage", "Invalid key", status_code=401)
    assert exc.status_code == 401


def test_all_sources_failed():
    errors = {
        "yahoo": SourceUnavailableError("yahoo", "timeout"),
        "sec": SymbolNotFoundError("sec", "BTC"),
    }
    exc = AllSourcesFailedError("BTC", errors)
    assert exc.symbol == "BTC"
    assert "yahoo" in str(exc)


def test_missing_dependency():
    exc = MissingDependencyError("duckdb", "duckdb")
    assert "pip install xfinance[duckdb]" in str(exc)


def test_data_validation_error():
    exc = DataValidationError("high < low", source="yahoo", field="high")
    assert exc.source == "yahoo"
    assert "yahoo" in str(exc)
