"""Property-based tests using Hypothesis for data validation models."""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from findata.models.bars import PriceBar


positive_floats = st.floats(min_value=0.01, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)


@given(
    low=positive_floats,
    spread=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    volume=st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_valid_ohlcv_always_accepted(low: float, spread: float, volume: float):
    """Any OHLCV bar where high >= max(open, close) >= min(open, close) >= low is valid."""
    high = low + spread
    open_ = low + spread * 0.4
    close = low + spread * 0.6
    assume(high >= open_)
    assume(high >= close)
    assume(open_ >= low)
    assume(close >= low)

    bar = PriceBar(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )
    assert bar.high >= bar.low
    assert bar.high >= bar.open
    assert bar.high >= bar.close
    assert bar.low <= bar.open
    assert bar.low <= bar.close


@given(
    price=positive_floats,
    delta=st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_high_less_than_low_always_rejected(price: float, delta: float):
    """A bar where high < low must always be rejected."""
    with pytest.raises(ValidationError):
        PriceBar(
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=price,
            high=price,         # high == price
            low=price + delta,  # low > high: invalid
            close=price,
            volume=0,
        )


import pytest  # noqa: E402  (import after function definitions for clarity)
