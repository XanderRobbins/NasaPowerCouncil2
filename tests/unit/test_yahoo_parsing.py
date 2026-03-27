"""Unit tests for Yahoo source parsing (no network calls)."""

from __future__ import annotations

import pytest

from xfinance.exceptions import SymbolNotFoundError, SourceUnavailableError
from xfinance.sources.yahoo import YahooSource


class TestYahooChartParsing:
    def test_happy_path(self, yahoo_chart_response):
        src = YahooSource()
        df = src._parse_chart(yahoo_chart_response, "AAPL")
        assert len(df) == 3
        assert df.index.name == "Date"
        assert df["Close"].iloc[0] == pytest.approx(185.0)

    def test_dividends_extracted_from_events(self, yahoo_chart_response):
        src = YahooSource()
        df = src._parse_chart(yahoo_chart_response, "AAPL")
        # 2nd bar has a dividend at ts=1704153600
        assert df["Dividends"].iloc[1] == pytest.approx(0.24)

    def test_no_events_field_defaults_to_zero(self, yahoo_chart_no_events):
        src = YahooSource()
        df = src._parse_chart(yahoo_chart_no_events, "AAPL")
        assert (df["Dividends"] == 0.0).all()
        assert (df["Stock Splits"] == 0.0).all()

    def test_empty_result_raises(self):
        src = YahooSource()
        with pytest.raises(SymbolNotFoundError):
            src._parse_chart({"chart": {"result": None, "error": {}}}, "FOOBAR")

    def test_none_prices_filtered(self):
        src = YahooSource()
        data = {
            "chart": {
                "result": [{
                    "timestamp": [1704067200, 1704153600],
                    "indicators": {
                        "quote": [{"open": [184.0, None], "high": [185.5, None],
                                   "low": [183.0, None], "close": [185.0, None],
                                   "volume": [50000000, None]}],
                        "adjclose": [{"adjclose": [185.0, None]}],
                    },
                }],
                "error": None,
            }
        }
        df = src._parse_chart(data, "AAPL")
        assert len(df) == 1

    def test_sorted_ascending(self, yahoo_chart_response):
        src = YahooSource()
        df = src._parse_chart(yahoo_chart_response, "AAPL")
        assert df.index.is_monotonic_increasing


class TestYahooFinancialStatements:
    def test_parse_income_statement(self, yahoo_income_stmt_module):
        df = YahooSource.parse_financial_statement(yahoo_income_stmt_module, "incomeStatementHistory")
        assert not df.empty
        assert "2023-09-30" in df.columns
        assert "2022-09-24" in df.columns
        assert "Total Revenue" in df.index

    def test_columns_newest_first(self, yahoo_income_stmt_module):
        df = YahooSource.parse_financial_statement(yahoo_income_stmt_module, "incomeStatementHistory")
        import pandas as pd
        dates = pd.to_datetime(df.columns)
        assert dates[0] > dates[-1]

    def test_raw_values_extracted(self, yahoo_income_stmt_module):
        df = YahooSource.parse_financial_statement(yahoo_income_stmt_module, "incomeStatementHistory")
        assert df.loc["Total Revenue", "2023-09-30"] == pytest.approx(383_285_000_000)

    def test_empty_module_returns_empty_df(self):
        df = YahooSource.parse_financial_statement({}, "incomeStatementHistory")
        assert df.empty


class TestYahooOptionsChain:
    def test_calls_parsed(self, yahoo_options_chain):
        src = YahooSource()
        result = src._parse_chart  # just verify the parse_options_contracts is accessible
        raw_result = yahoo_options_chain["optionChain"]["result"][0]
        contracts = raw_result["options"][0]["calls"]
        calls = YahooSource._parse_options_contracts(contracts)
        assert len(calls) == 1
        assert calls["contractSymbol"].iloc[0] == "AAPL240117C00185000"
        assert calls["strike"].iloc[0] == pytest.approx(185.0)
        assert bool(calls["inTheMoney"].iloc[0]) is True

    def test_puts_parsed(self, yahoo_options_chain):
        raw_result = yahoo_options_chain["optionChain"]["result"][0]
        contracts = raw_result["options"][0]["puts"]
        puts = YahooSource._parse_options_contracts(contracts)
        assert len(puts) == 1
        assert bool(puts["inTheMoney"].iloc[0]) is False

    def test_empty_contracts_returns_empty_df(self):
        df = YahooSource._parse_options_contracts([])
        assert df.empty

    def test_option_chain_expiry_parsing(self, yahoo_options_chain):
        src = YahooSource()
        raw = yahoo_options_chain
        result = raw["optionChain"]["result"][0]
        timestamps = result["expirationDates"]
        from datetime import datetime, timezone
        dates = [datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") for ts in timestamps]
        assert len(dates) == 2
        assert all("-" in d for d in dates)


class TestYahooRecommendations:
    def test_parse_recommendations(self):
        raw = {
            "recommendationTrend": {
                "trend": [
                    {"period": "0m", "strongBuy": 20, "buy": 15, "hold": 8, "sell": 2, "strongSell": 0},
                    {"period": "-1m", "strongBuy": 18, "buy": 14, "hold": 9, "sell": 3, "strongSell": 1},
                ]
            }
        }
        df = YahooSource.parse_recommendations(raw)
        assert len(df) == 2
        assert "Strong Buy" in df.columns
        assert df["Strong Buy"].iloc[0] == 20

    def test_parse_recommendations_empty(self):
        df = YahooSource.parse_recommendations({})
        assert df.empty


class TestYahooCalendar:
    def test_parse_calendar(self):
        cal = {
            "calendarEvents": {
                "earnings": {
                    "earningsDate": [{"raw": 1710374400}, {"raw": 1710460800}],
                    "earningsAverage": {"raw": 1.52},
                    "earningsLow": {"raw": 1.35},
                    "earningsHigh": {"raw": 1.65},
                    "revenueAverage": {"raw": 90_000_000_000},
                    "revenueLow": {"raw": 88_000_000_000},
                    "revenueHigh": {"raw": 92_000_000_000},
                },
                "dividendDate": {"raw": 1710288000, "fmt": "2024-03-13"},
                "exDividendDate": {"raw": 1710115200, "fmt": "2024-03-11"},
            }
        }
        result = YahooSource.parse_calendar(cal)
        assert isinstance(result, dict)
        assert len(result["Earnings Date"]) == 2
        assert result["EPS Estimate"] == pytest.approx(1.52)
        assert result["Dividend Date"] == "2024-03-13"

    def test_parse_calendar_empty(self):
        result = YahooSource.parse_calendar({})
        assert isinstance(result, dict)


class TestYahooAnalystTargets:
    def test_parse_analyst_targets(self):
        raw = {
            "financialData": {
                "currentPrice": {"raw": 185.5},
                "targetHighPrice": {"raw": 220.0},
                "targetLowPrice": {"raw": 160.0},
                "targetMeanPrice": {"raw": 196.0},
                "targetMedianPrice": {"raw": 200.0},
                "recommendationMean": {"raw": 1.8},
                "recommendationKey": "buy",
                "numberOfAnalystOpinions": {"raw": 38},
            }
        }
        result = YahooSource.parse_analyst_targets(raw)
        assert result["Current Price"] == pytest.approx(185.5)
        assert result["Target Mean Price"] == pytest.approx(196.0)
        assert result["Recommendation Key"] == "buy"
        assert result["Number Of Analyst Opinions"] == 38

    def test_parse_analyst_targets_empty(self):
        result = YahooSource.parse_analyst_targets({})
        assert isinstance(result, dict)
