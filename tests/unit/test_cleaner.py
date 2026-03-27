"""Unit tests for the DataCleaner module."""

from __future__ import annotations

from datetime import timezone

import numpy as np
import pandas as pd
import pytest

from xfinance import cleaner


def _make_raw_prices(n: int = 3, *, include_events: bool = True) -> pd.DataFrame:
    idx = pd.date_range("2024-01-02", periods=n, freq="D", tz="UTC", name="Date")
    data = {
        "Open": [184.0 + i for i in range(n)],
        "High": [185.5 + i for i in range(n)],
        "Low": [183.0 + i for i in range(n)],
        "Close": [185.0 + i for i in range(n)],
        "Volume": [50_000_000 - i * 1_000_000 for i in range(n)],
        "Adj Close": [185.0 + i for i in range(n)],
    }
    if include_events:
        data["Dividends"] = [0.0, 0.24, 0.0][:n]
        data["Stock Splits"] = [0.0] * n
        data["Capital Gains"] = [0.0] * n
    return pd.DataFrame(data, index=idx)


class TestCleanPrices:
    def test_returns_correct_columns_with_actions(self):
        df = cleaner.clean_prices(_make_raw_prices(), auto_adjust=False, actions=True)
        assert set(df.columns) == set(cleaner._PRICE_COLS)

    def test_returns_correct_columns_without_actions(self):
        df = cleaner.clean_prices(_make_raw_prices(), auto_adjust=False, actions=False)
        assert "Dividends" not in df.columns
        assert "Close" in df.columns

    def test_index_is_utc_datetimeindex(self):
        df = cleaner.clean_prices(_make_raw_prices(), auto_adjust=False)
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.tz == timezone.utc
        assert df.index.name == "Date"

    def test_volume_is_int64(self):
        df = cleaner.clean_prices(_make_raw_prices(), auto_adjust=False)
        assert df["Volume"].dtype == "int64"

    def test_prices_are_float64(self):
        df = cleaner.clean_prices(_make_raw_prices(), auto_adjust=False)
        for col in ["Open", "High", "Low", "Close"]:
            assert df[col].dtype == float

    def test_sorted_ascending(self):
        raw = _make_raw_prices()
        raw = raw.iloc[::-1]  # reverse order
        df = cleaner.clean_prices(raw, auto_adjust=False)
        assert df.index.is_monotonic_increasing

    def test_auto_adjust_makes_close_equal_adj_close(self):
        raw = _make_raw_prices()
        # Make Adj Close different from Close (simulated split)
        raw["Adj Close"] = raw["Close"] * 0.5
        df = cleaner.clean_prices(raw, auto_adjust=True)
        pd.testing.assert_series_equal(df["Close"], df["Adj Close"], check_names=False)

    def test_nan_rows_dropped(self):
        raw = _make_raw_prices()
        raw.loc[raw.index[1], ["Open", "High", "Low", "Close"]] = np.nan
        df = cleaner.clean_prices(raw, auto_adjust=False)
        assert len(df) == 2  # NaN row dropped

    def test_missing_events_columns_filled_zero(self):
        raw = _make_raw_prices(include_events=False)
        df = cleaner.clean_prices(raw, auto_adjust=False, actions=True)
        assert (df["Dividends"] == 0.0).all()
        assert (df["Stock Splits"] == 0.0).all()

    def test_empty_df_passthrough(self):
        df = cleaner.clean_prices(pd.DataFrame())
        assert df.empty

    def test_naive_index_localized_to_utc(self):
        raw = _make_raw_prices()
        raw.index = raw.index.tz_localize(None)
        df = cleaner.clean_prices(raw, auto_adjust=False)
        assert df.index.tz == timezone.utc


class TestExtractDividendsSplits:
    def test_extract_dividends_filters_zeros(self):
        df = _make_raw_prices()
        s = cleaner.extract_dividends(df)
        assert len(s) == 1
        assert s.iloc[0] == pytest.approx(0.24)

    def test_extract_splits_empty_when_all_zero(self):
        df = _make_raw_prices()
        s = cleaner.extract_splits(df)
        assert s.empty

    def test_extract_splits_nonzero(self):
        df = _make_raw_prices()
        df["Stock Splits"] = [0.0, 2.0, 0.0]
        s = cleaner.extract_splits(df)
        assert len(s) == 1
        assert s.iloc[0] == 2.0


class TestCleanFinancialStatement:
    def test_all_numeric(self, yahoo_income_stmt_module):
        from xfinance.sources.yahoo import YahooSource
        df = YahooSource.parse_financial_statement(yahoo_income_stmt_module, "incomeStatementHistory")
        cleaned = cleaner.clean_financial_statement(df)
        for col in cleaned.columns:
            assert pd.api.types.is_numeric_dtype(cleaned[col])

    def test_columns_sorted_newest_first(self, yahoo_income_stmt_module):
        from xfinance.sources.yahoo import YahooSource
        df = YahooSource.parse_financial_statement(yahoo_income_stmt_module, "incomeStatementHistory")
        cleaned = cleaner.clean_financial_statement(df)
        dates = pd.to_datetime(cleaned.columns)
        assert dates[0] >= dates[-1]

    def test_drops_all_nan_rows(self, yahoo_income_stmt_module):
        from xfinance.sources.yahoo import YahooSource
        df = YahooSource.parse_financial_statement(yahoo_income_stmt_module, "incomeStatementHistory")
        cleaned = cleaner.clean_financial_statement(df)
        assert not cleaned.isnull().all(axis=1).any()

    def test_empty_df_passthrough(self):
        cleaned = cleaner.clean_financial_statement(pd.DataFrame())
        assert cleaned.empty


class TestCleanOptions:
    def test_float_columns(self, yahoo_options_chain):
        from xfinance.sources.yahoo import YahooSource
        raw_result = yahoo_options_chain["optionChain"]["result"][0]
        contracts = raw_result["options"][0]["calls"]
        calls = YahooSource._parse_options_contracts(contracts)
        cleaned = cleaner.clean_options(calls)
        for col in cleaner._OPT_FLOAT:
            if col in cleaned.columns:
                assert cleaned[col].dtype == float

    def test_volume_is_nullable_int(self, yahoo_options_chain):
        from xfinance.sources.yahoo import YahooSource
        raw_result = yahoo_options_chain["optionChain"]["result"][0]
        contracts = raw_result["options"][0]["calls"]
        calls = YahooSource._parse_options_contracts(contracts)
        cleaned = cleaner.clean_options(calls)
        assert str(cleaned["volume"].dtype) == "Int64"

    def test_in_the_money_is_bool(self, yahoo_options_chain):
        from xfinance.sources.yahoo import YahooSource
        raw_result = yahoo_options_chain["optionChain"]["result"][0]
        contracts = raw_result["options"][0]["calls"]
        calls = YahooSource._parse_options_contracts(contracts)
        cleaned = cleaner.clean_options(calls)
        assert cleaned["inTheMoney"].dtype == bool

    def test_sorted_by_strike(self, yahoo_options_chain):
        from xfinance.sources.yahoo import YahooSource
        raw_result = yahoo_options_chain["optionChain"]["result"][0]
        contracts = raw_result["options"][0]["calls"]
        calls = YahooSource._parse_options_contracts(contracts)
        cleaned = cleaner.clean_options(calls)
        assert cleaned["strike"].is_monotonic_increasing


class TestCleanInfo:
    def test_raw_values_unwrapped(self):
        raw = {
            "price": {"marketCap": {"raw": 3_000_000_000_000, "fmt": "3T"}},
        }
        result = cleaner.clean_info(raw)
        assert result.get("marketCap") == 3_000_000_000_000

    def test_na_strings_become_none(self):
        raw = {
            "summaryDetail": {"trailingPE": "N/A"},
        }
        result = cleaner.clean_info(raw)
        assert result.get("trailingPE") is None

    def test_numeric_strings_coerced(self):
        raw = {
            "defaultKeyStatistics": {"sharesOutstanding": "15000000000"},
        }
        result = cleaner.clean_info(raw)
        val = result.get("sharesOutstanding")
        assert isinstance(val, (int, float))

    def test_symbol_uppercased(self):
        raw = {"quoteType": {"symbol": "aapl"}}
        result = cleaner.clean_info(raw)
        assert result.get("symbol") == "AAPL"

    def test_empty_modules_no_crash(self):
        result = cleaner.clean_info({})
        assert isinstance(result, dict)
        assert len(result) == 0
