"""Shared pytest fixtures and response stubs for xfinance tests."""

from __future__ import annotations

import pathlib
from datetime import datetime, timezone

import pytest

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"


@pytest.fixture(scope="session")
def vcr_config():
    return {
        "cassette_library_dir": str(CASSETTE_DIR),
        "record_mode": "none",
        "filter_headers": ["Cookie", "Set-Cookie", "Authorization", "X-Api-Key"],
        "filter_query_parameters": ["crumb", "apikey", "api_key"],
        "decode_compressed_response": True,
    }


@pytest.fixture
def yahoo_chart_response():
    """Minimal Yahoo Finance v8 chart API response with events."""
    return {
        "chart": {
            "result": [{
                "timestamp": [1704067200, 1704153600, 1704240000],
                "indicators": {
                    "quote": [{
                        "open": [184.0, 185.0, 186.0],
                        "high": [185.5, 186.5, 187.5],
                        "low": [183.0, 184.0, 185.0],
                        "close": [185.0, 186.0, 187.0],
                        "volume": [50000000, 45000000, 48000000],
                    }],
                    "adjclose": [{"adjclose": [185.0, 186.0, 187.0]}],
                },
                "events": {
                    "dividends": {
                        "1704153600": {"date": 1704153600, "amount": 0.24},
                    },
                    "splits": {},
                    "capitalGains": {},
                },
                "meta": {"symbol": "AAPL", "currency": "USD"},
            }],
            "error": None,
        }
    }


@pytest.fixture
def yahoo_chart_no_events():
    """Chart response without events (many tickers)."""
    return {
        "chart": {
            "result": [{
                "timestamp": [1704067200, 1704153600, 1704240000],
                "indicators": {
                    "quote": [{
                        "open": [184.0, 185.0, 186.0],
                        "high": [185.5, 186.5, 187.5],
                        "low": [183.0, 184.0, 185.0],
                        "close": [185.0, 186.0, 187.0],
                        "volume": [50000000, 45000000, 48000000],
                    }],
                    "adjclose": [{"adjclose": [185.0, 186.0, 187.0]}],
                },
                "meta": {"symbol": "AAPL", "currency": "USD"},
            }],
            "error": None,
        }
    }


@pytest.fixture
def yahoo_income_stmt_module():
    """Minimal Yahoo incomeStatementHistory quoteSummary module."""
    return {
        "incomeStatementHistory": [
            {
                "maxAge": 1,
                "endDate": {"raw": 1696032000, "fmt": "2023-09-30"},
                "totalRevenue": {"raw": 383285000000, "fmt": "383.29B"},
                "costOfRevenue": {"raw": 214137000000, "fmt": "214.14B"},
                "grossProfit": {"raw": 169148000000, "fmt": "169.15B"},
                "netIncome": {"raw": 96995000000, "fmt": "96.99B"},
            },
            {
                "maxAge": 1,
                "endDate": {"raw": 1664496000, "fmt": "2022-09-24"},
                "totalRevenue": {"raw": 394328000000, "fmt": "394.33B"},
                "costOfRevenue": {"raw": 223546000000, "fmt": "223.55B"},
                "grossProfit": {"raw": 170782000000, "fmt": "170.78B"},
                "netIncome": {"raw": 99803000000, "fmt": "99.80B"},
            },
        ]
    }


@pytest.fixture
def yahoo_options_chain():
    """Minimal Yahoo options chain response."""
    return {
        "optionChain": {
            "result": [{
                "underlyingSymbol": "AAPL",
                "expirationDates": [1705449600, 1706054400],
                "strikes": [180.0, 185.0, 190.0],
                "hasMiniOptions": False,
                "quote": {"regularMarketPrice": 185.5},
                "options": [{
                    "expirationDate": 1705449600,
                    "hasMiniOptions": False,
                    "calls": [
                        {
                            "contractSymbol": "AAPL240117C00185000",
                            "strike": {"raw": 185.0},
                            "lastTradeDate": {"raw": 1704153600},
                            "lastPrice": {"raw": 4.50},
                            "bid": {"raw": 4.40},
                            "ask": {"raw": 4.60},
                            "change": 0.25,
                            "percentChange": 5.88,
                            "volume": {"raw": 1200},
                            "openInterest": {"raw": 8500},
                            "impliedVolatility": {"raw": 0.285},
                            "inTheMoney": True,
                            "contractSize": "REGULAR",
                            "currency": "USD",
                        }
                    ],
                    "puts": [
                        {
                            "contractSymbol": "AAPL240117P00185000",
                            "strike": {"raw": 185.0},
                            "lastTradeDate": {"raw": 1704153600},
                            "lastPrice": {"raw": 3.80},
                            "bid": {"raw": 3.70},
                            "ask": {"raw": 3.90},
                            "change": -0.10,
                            "percentChange": -2.56,
                            "volume": {"raw": 980},
                            "openInterest": {"raw": 6200},
                            "impliedVolatility": {"raw": 0.292},
                            "inTheMoney": False,
                            "contractSize": "REGULAR",
                            "currency": "USD",
                        }
                    ],
                }],
            }],
            "error": None,
        }
    }


@pytest.fixture
def yahoo_earnings_trend_module():
    """Minimal earningsTrend quoteSummary stub with 4 periods."""
    return {
        "earningsTrend": {
            "trend": [
                {
                    "period": "0q",
                    "endDate": "2024-03-31",
                    "growth": {"raw": 0.12, "fmt": "12%"},
                    "earningsEstimate": {
                        "avg": {"raw": 1.50},
                        "low": {"raw": 1.20},
                        "high": {"raw": 1.80},
                        "yearAgoEps": {"raw": 1.34},
                        "numberOfAnalysts": {"raw": 15},
                        "growth": {"raw": 0.12},
                    },
                    "revenueEstimate": {
                        "avg": {"raw": 90_000_000_000},
                        "low": {"raw": 85_000_000_000},
                        "high": {"raw": 95_000_000_000},
                        "yearAgoRevenue": {"raw": 80_000_000_000},
                        "numberOfAnalysts": {"raw": 14},
                        "growth": {"raw": 0.10},
                    },
                    "epsTrend": {
                        "current": {"raw": 1.50},
                        "7daysAgo": {"raw": 1.48},
                        "30daysAgo": {"raw": 1.45},
                        "60daysAgo": {"raw": 1.42},
                        "90daysAgo": {"raw": 1.40},
                    },
                    "epsRevisions": {
                        "upLast7days": {"raw": 3},
                        "upLast30days": {"raw": 5},
                        "downLast30days": {"raw": 2},
                        "downLast90days": {"raw": 1},
                    },
                },
                {
                    "period": "+1q",
                    "endDate": "2024-06-30",
                    "growth": {"raw": 0.08, "fmt": "8%"},
                    "earningsEstimate": {
                        "avg": {"raw": 1.60},
                        "low": {"raw": 1.30},
                        "high": {"raw": 1.90},
                        "yearAgoEps": {"raw": 1.48},
                        "numberOfAnalysts": {"raw": 12},
                        "growth": {"raw": 0.08},
                    },
                    "revenueEstimate": {
                        "avg": {"raw": 92_000_000_000},
                        "low": {"raw": 88_000_000_000},
                        "high": {"raw": 96_000_000_000},
                        "yearAgoRevenue": {"raw": 81_000_000_000},
                        "numberOfAnalysts": {"raw": 11},
                        "growth": {"raw": 0.09},
                    },
                    "epsTrend": {
                        "current": {"raw": 1.60},
                        "7daysAgo": {"raw": 1.58},
                        "30daysAgo": {"raw": 1.55},
                        "60daysAgo": {"raw": 1.52},
                        "90daysAgo": {"raw": 1.50},
                    },
                    "epsRevisions": {
                        "upLast7days": {"raw": 2},
                        "upLast30days": {"raw": 4},
                        "downLast30days": {"raw": 1},
                        "downLast90days": {"raw": 0},
                    },
                },
            ]
        }
    }


@pytest.fixture
def ecb_rates_response():
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
    return [
        [1704067200000, "42000.0", "43000.0", "41500.0", "42500.0", "1234.5",
         1704153599999, "52345678.9", 10000, "600.0", "25000000.0", "0"],
        [1704153600000, "42500.0", "44000.0", "42000.0", "43800.0", "2345.6",
         1704239999999, "102345678.9", 12000, "1200.0", "52000000.0", "0"],
    ]
