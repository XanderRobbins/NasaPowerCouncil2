"""Unit tests for the exception hierarchy."""

from __future__ import annotations

import pytest

from findata.exceptions import (
    AllSourcesFailedError,
    DataValidationError,
    FindataError,
    MissingDependencyError,
    SourceAuthError,
    SourceRateLimitError,
    SourceUnavailableError,
    SymbolNotFoundError,
)


def test_source_unavailable_has_source():
    exc = SourceUnavailableError("yahoo", "Network error")
    assert exc.source == "yahoo"
    assert "yahoo" in str(exc)
    assert isinstance(exc, FindataError)


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


def test_auth_error_with_status():
    exc = SourceAuthError("alphavantage", "Invalid API key", status_code=401)
    assert exc.status_code == 401
    assert "alphavantage" in str(exc)


def test_all_sources_failed():
    errors = {
        "yahoo": SourceUnavailableError("yahoo", "timeout"),
        "sec": SymbolNotFoundError("sec", "BTC"),
    }
    exc = AllSourcesFailedError("BTC", errors)
    assert exc.symbol == "BTC"
    assert "yahoo" in str(exc)
    assert "sec" in str(exc)
    assert isinstance(exc, FindataError)


def test_data_validation_error():
    exc = DataValidationError("high < low", source="yahoo", field="high")
    assert exc.source == "yahoo"
    assert exc.field == "high"
    assert "yahoo" in str(exc)
    assert "high" in str(exc)


def test_missing_dependency():
    exc = MissingDependencyError("duckdb", "duckdb")
    assert "pip install findata[duckdb]" in str(exc)
    assert isinstance(exc, FindataError)
