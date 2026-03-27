"""Unit tests for DataValidator."""

from __future__ import annotations

import pandas as pd
import pytest

from findata.exceptions import DataValidationError
from findata.reconciliation.validator import DataValidator


def _make_df(**overrides: list) -> pd.DataFrame:
    base = {
        "open": [184.0, 185.0, 186.0],
        "high": [185.5, 186.5, 187.5],
        "low": [183.0, 184.0, 185.0],
        "close": [185.0, 186.0, 187.0],
        "volume": [1e7, 2e7, 1.5e7],
    }
    base.update(overrides)
    return pd.DataFrame(base)


class TestDataValidator:
    def test_valid_data_no_warnings(self):
        df = _make_df()
        v = DataValidator()
        warnings = v.validate_prices(df, symbol="AAPL")
        assert warnings == []

    def test_empty_df_warns(self):
        v = DataValidator()
        warnings = v.validate_prices(pd.DataFrame(), symbol="AAPL")
        assert any("empty" in w.lower() for w in warnings)

    def test_high_less_than_low_warns(self):
        df = _make_df(high=[183.0, 186.5, 187.5], low=[184.0, 184.0, 185.0])
        v = DataValidator()
        warnings = v.validate_prices(df, symbol="TEST")
        assert any("high < low" in w for w in warnings)

    def test_high_less_than_close_warns(self):
        df = _make_df(high=[184.0, 186.5, 187.5], close=[185.0, 186.0, 187.0])
        v = DataValidator()
        warnings = v.validate_prices(df, symbol="TEST")
        assert any("high < close" in w for w in warnings)

    def test_non_positive_prices_warn(self):
        df = _make_df(close=[185.0, 0.0, 187.0])
        v = DataValidator()
        warnings = v.validate_prices(df, symbol="TEST")
        assert any("non-positive" in w for w in warnings)

    def test_extreme_move_warns(self):
        # 50% move between bars 1→2
        df = _make_df(
            open=[100.0, 150.0, 150.0],
            high=[101.0, 151.0, 151.0],
            low=[99.0, 149.0, 149.0],
            close=[100.0, 150.0, 150.0],
        )
        v = DataValidator()
        warnings = v.validate_prices(df, symbol="TEST")
        assert any("20%" in w or "daily move" in w for w in warnings)

    def test_raise_on_error_mode(self):
        df = _make_df(close=[185.0, 0.0, 187.0])
        v = DataValidator(raise_on_error=True)
        with pytest.raises(DataValidationError):
            v.validate_prices(df, symbol="TEST")

    def test_source_prefixed_in_warnings(self):
        df = _make_df(high=[183.0, 186.5, 187.5], low=[184.0, 184.0, 185.0])
        v = DataValidator(source="yahoo")
        warnings = v.validate_prices(df, symbol="AAPL")
        assert all(w.startswith("[yahoo]") for w in warnings)
