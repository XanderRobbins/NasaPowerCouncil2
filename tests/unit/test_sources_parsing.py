"""Unit tests for ECB and Binance source parsing."""

from __future__ import annotations

import pytest

from xfinance.exceptions import SourceUnavailableError, SymbolNotFoundError
from xfinance.sources.ecb import ECBSource
from xfinance.sources.binance import BinanceSource
from xfinance.sources.coingecko import CoinGeckoSource


class TestECBParsing:
    def test_parse_pair_slash(self):
        assert ECBSource._parse_pair("USD/EUR") == ("USD", "EUR")

    def test_parse_pair_single(self):
        assert ECBSource._parse_pair("USD") == ("EUR", "USD")

    def test_parse_rates(self, ecb_rates_response):
        df = ECBSource._parse_rates(ecb_rates_response, "USD", "EUR")
        assert len(df) == 3
        assert df.index.name == "Date"
        assert df["Close"].iloc[0] == pytest.approx(0.9123)

    def test_parse_rates_empty_raises(self):
        with pytest.raises(SourceUnavailableError):
            ECBSource._parse_rates({"rates": {}}, "USD", "EUR")

    def test_output_has_all_ohlcv_columns(self, ecb_rates_response):
        df = ECBSource._parse_rates(ecb_rates_response, "USD", "EUR")
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            assert col in df.columns


class TestBinanceParsing:
    def test_normalize_slash(self):
        assert BinanceSource._normalize("BTC/USDT") == "BTCUSDT"

    def test_normalize_dash(self):
        assert BinanceSource._normalize("ETH-USDT") == "ETHUSDT"

    def test_parse_klines(self, binance_klines_response):
        df = BinanceSource._parse_klines(binance_klines_response, "BTCUSDT")
        assert len(df) == 2
        assert df["Open"].iloc[0] == pytest.approx(42000.0)
        assert df["Close"].iloc[0] == pytest.approx(42500.0)

    def test_parse_klines_sorted(self, binance_klines_response):
        df = BinanceSource._parse_klines(list(reversed(binance_klines_response)), "BTCUSDT")
        assert df.index.is_monotonic_increasing

    def test_parse_klines_empty_raises(self):
        with pytest.raises(SymbolNotFoundError):
            BinanceSource._parse_klines([], "BTCUSDT")

    def test_output_has_all_columns(self, binance_klines_response):
        df = BinanceSource._parse_klines(binance_klines_response, "BTCUSDT")
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            assert col in df.columns


class TestCoinGeckoParsing:
    def test_parse_chart(self):
        src = CoinGeckoSource()
        data = {
            "prices": [[1704067200000, 42000.0], [1704153600000, 43000.0]],
            "total_volumes": [[1704067200000, 1e9], [1704153600000, 1.1e9]],
        }
        df = src._parse_chart(data, "bitcoin")
        assert len(df) == 2
        assert df["Close"].iloc[0] == pytest.approx(42000.0)
        assert df["Volume"].iloc[0] == pytest.approx(1e9)

    def test_parse_chart_empty_raises(self):
        src = CoinGeckoSource()
        with pytest.raises(SourceUnavailableError):
            src._parse_chart({"prices": [], "total_volumes": []}, "bitcoin")
