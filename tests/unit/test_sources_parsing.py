"""Unit tests for source-specific data parsing logic (no network calls)."""

from __future__ import annotations

from datetime import timezone

import pytest

from findata.exceptions import SymbolNotFoundError, SourceUnavailableError
from findata.sources.yahoo import YahooSource
from findata.sources.ecb import ECBSource
from findata.sources.binance import BinanceSource
from findata.sources.coingecko import CoinGeckoSource


class TestYahooSourceParsing:
    def _source(self):
        return YahooSource()

    def test_parse_chart_happy_path(self, yahoo_chart_response):
        src = self._source()
        df = src._parse_chart(yahoo_chart_response, "AAPL")
        assert len(df) == 3
        assert list(df.columns) == ["open", "high", "low", "close", "volume", "adjusted_close"]
        assert df.index.name == "timestamp"
        assert df["close"].iloc[0] == 185.0

    def test_parse_chart_empty_result_raises(self):
        src = self._source()
        data = {"chart": {"result": None, "error": {"code": "Not Found"}}}
        with pytest.raises(SymbolNotFoundError):
            src._parse_chart(data, "FOOBAR")

    def test_parse_chart_filters_none_prices(self):
        src = self._source()
        data = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1704067200, 1704153600],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [184.0, None],
                                    "high": [185.5, None],
                                    "low": [183.0, None],
                                    "close": [185.0, None],
                                    "volume": [50000000, None],
                                }
                            ],
                            "adjclose": [{"adjclose": [185.0, None]}],
                        },
                    }
                ],
                "error": None,
            }
        }
        df = src._parse_chart(data, "AAPL")
        assert len(df) == 1  # None row filtered out

    def test_parse_chart_sorted_by_timestamp(self, yahoo_chart_response):
        src = self._source()
        df = src._parse_chart(yahoo_chart_response, "AAPL")
        assert df.index.is_monotonic_increasing


class TestECBSourceParsing:
    def test_parse_pair_slash(self):
        src = ECBSource()
        assert src._parse_pair("USD/EUR") == ("USD", "EUR")

    def test_parse_pair_single(self):
        src = ECBSource()
        assert src._parse_pair("USD") == ("EUR", "USD")

    def test_parse_rates_happy_path(self, ecb_rates_response):
        src = ECBSource()
        df = src._parse_rates(ecb_rates_response, "USD", "EUR")
        assert len(df) == 3
        assert df.index.name == "timestamp"
        assert "close" in df.columns
        assert df["close"].iloc[0] == pytest.approx(0.9123)

    def test_parse_rates_empty_raises(self):
        src = ECBSource()
        with pytest.raises(SourceUnavailableError):
            src._parse_rates({"rates": {}}, "USD", "EUR")


class TestBinanceSourceParsing:
    def test_normalize_symbol_slash(self):
        src = BinanceSource()
        assert src._normalize_symbol("BTC/USDT") == "BTCUSDT"

    def test_normalize_symbol_dash(self):
        src = BinanceSource()
        assert src._normalize_symbol("ETH-USDT") == "ETHUSDT"

    def test_parse_klines_happy_path(self, binance_klines_response):
        src = BinanceSource()
        df = src._parse_klines(binance_klines_response, "BTCUSDT")
        assert len(df) == 2
        assert df.index.name == "timestamp"
        assert df["open"].iloc[0] == 42000.0
        assert df["close"].iloc[0] == 42500.0

    def test_parse_klines_empty_raises(self):
        src = BinanceSource()
        with pytest.raises(SymbolNotFoundError):
            src._parse_klines([], "BTCUSDT")

    def test_parse_klines_sorted(self, binance_klines_response):
        src = BinanceSource()
        # Reverse order to test sorting
        df = src._parse_klines(list(reversed(binance_klines_response)), "BTCUSDT")
        assert df.index.is_monotonic_increasing


class TestCoinGeckoSourceParsing:
    def test_parse_market_chart(self):
        src = CoinGeckoSource()
        data = {
            "prices": [
                [1704067200000, 42000.0],
                [1704153600000, 43000.0],
            ],
            "total_volumes": [
                [1704067200000, 1e9],
                [1704153600000, 1.1e9],
            ],
        }
        df = src._parse_market_chart(data, "bitcoin")
        assert len(df) == 2
        assert df["close"].iloc[0] == 42000.0
        assert df["volume"].iloc[0] == 1e9

    def test_parse_market_chart_empty_raises(self):
        src = CoinGeckoSource()
        with pytest.raises(SourceUnavailableError):
            src._parse_market_chart({"prices": [], "total_volumes": []}, "bitcoin")
