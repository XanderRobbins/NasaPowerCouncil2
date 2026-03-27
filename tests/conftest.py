"""Shared pytest fixtures and VCR cassette configuration."""

from __future__ import annotations

import pathlib

import pytest

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"


@pytest.fixture(scope="session")
def vcr_config():
    """Global VCR configuration: cassettes dir and filter sensitive headers."""
    return {
        "cassette_library_dir": str(CASSETTE_DIR),
        "record_mode": "none",  # Never make real HTTP calls in CI
        "filter_headers": [
            "Cookie",
            "Set-Cookie",
            "Authorization",
            "X-Api-Key",
        ],
        "filter_query_parameters": ["crumb", "apikey", "api_key"],
        "decode_compressed_response": True,
    }


@pytest.fixture
def yahoo_chart_response():
    """Minimal Yahoo Finance v8 chart API response fixture."""
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [1704067200, 1704153600, 1704240000],
                    "indicators": {
                        "quote": [
                            {
                                "open": [184.0, 185.0, 186.0],
                                "high": [185.5, 186.5, 187.5],
                                "low": [183.0, 184.0, 185.0],
                                "close": [185.0, 186.0, 187.0],
                                "volume": [50000000, 45000000, 48000000],
                            }
                        ],
                        "adjclose": [{"adjclose": [185.0, 186.0, 187.0]}],
                    },
                    "meta": {"symbol": "AAPL", "currency": "USD"},
                }
            ],
            "error": None,
        }
    }


@pytest.fixture
def ecb_rates_response():
    """Minimal Frankfurter API response fixture."""
    return {
        "amount": 1.0,
        "base": "USD",
        "start_date": "2024-01-01",
        "end_date": "2024-01-03",
        "rates": {
            "2024-01-01": {"EUR": 0.9123},
            "2024-01-02": {"EUR": 0.9145},
            "2024-01-03": {"EUR": 0.9101},
        },
    }


@pytest.fixture
def binance_klines_response():
    """Minimal Binance klines response fixture."""
    # [open_time, open, high, low, close, volume, close_time, ...]
    return [
        [1704067200000, "42000.0", "43000.0", "41500.0", "42500.0", "1234.5", 1704153599999, "52345678.9", 10000, "600.0", "25000000.0", "0"],
        [1704153600000, "42500.0", "44000.0", "42000.0", "43800.0", "2345.6", 1704239999999, "102345678.9", 12000, "1200.0", "52000000.0", "0"],
    ]
