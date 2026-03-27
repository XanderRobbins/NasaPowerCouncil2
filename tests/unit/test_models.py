"""Unit tests for Pydantic data models."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from findata.models.bars import PriceBar
from findata.models.assets import AssetClass, AssetInfo
from findata.models.result import DataResult, SourceContribution
import pandas as pd


class TestPriceBar:
    def test_valid_bar(self):
        bar = PriceBar(
            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
            open=184.0,
            high=185.5,
            low=183.0,
            close=185.0,
            volume=50_000_000,
        )
        assert bar.close == 185.0
        assert bar.adjusted_close is None

    def test_high_less_than_low_rejected(self):
        with pytest.raises(ValidationError, match="high.*low"):
            PriceBar(
                timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
                open=183.0,
                high=182.0,  # invalid
                low=183.0,
                close=183.0,
                volume=0,
            )

    def test_high_less_than_close_rejected(self):
        with pytest.raises(ValidationError):
            PriceBar(
                timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
                open=183.0,
                high=183.0,
                low=182.0,
                close=184.0,  # above high
                volume=0,
            )

    def test_non_positive_price_rejected(self):
        with pytest.raises(ValidationError):
            PriceBar(
                timestamp=date(2024, 1, 2),
                open=0,  # invalid
                high=1,
                low=0,
                close=1,
                volume=0,
            )

    def test_zero_volume_allowed(self):
        bar = PriceBar(
            timestamp=date(2024, 1, 2),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=0,
        )
        assert bar.volume == 0.0

    def test_with_adjusted_close(self):
        bar = PriceBar(
            timestamp=date(2024, 1, 2),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000,
            adjusted_close=99.8,
        )
        assert bar.adjusted_close == 99.8


class TestAssetInfo:
    def test_defaults(self):
        info = AssetInfo(symbol="AAPL")
        assert info.symbol == "AAPL"
        assert info.asset_class == AssetClass.UNKNOWN
        assert info.extra == {}

    def test_full_construction(self):
        info = AssetInfo(
            symbol="AAPL",
            name="Apple Inc.",
            asset_class=AssetClass.EQUITY,
            exchange="NASDAQ",
            currency="USD",
            country="US",
            sector="Technology",
            industry="Consumer Electronics",
            market_cap=3e12,
            source="yahoo",
        )
        assert info.market_cap == 3e12
        assert info.source == "yahoo"


class TestDataResult:
    def _make_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"close": [185.0, 186.0, 187.0]},
            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"], utc=True),
        )

    def test_basic_construction(self):
        df = self._make_df()
        result = DataResult(df, symbol="AAPL")
        assert result.symbol == "AAPL"
        assert len(result) == 3
        assert result.primary_source == "unknown"

    def test_with_sources(self):
        df = self._make_df()
        contrib = SourceContribution(source="yahoo", rows=3)
        result = DataResult(df, symbol="AAPL", sources=[contrib])
        assert result.primary_source == "yahoo"

    def test_to_pandas(self):
        df = self._make_df()
        result = DataResult(df, symbol="AAPL")
        pd.testing.assert_frame_equal(result.to_pandas(), df)

    def test_repr(self):
        df = self._make_df()
        result = DataResult(df, symbol="AAPL")
        assert "AAPL" in repr(result)

    def test_to_polars_without_dep_raises(self):
        import sys
        # Only test the error path if polars is not installed
        if "polars" not in sys.modules:
            df = self._make_df()
            result = DataResult(df, symbol="AAPL")
            try:
                import polars  # noqa: F401
                # polars is installed, skip this test
            except ImportError:
                from findata.exceptions import MissingDependencyError
                with pytest.raises(MissingDependencyError):
                    result.to_polars()
