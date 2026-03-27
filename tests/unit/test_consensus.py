"""Unit tests for MedianConsensus reconciliation."""

from __future__ import annotations

import pandas as pd
import pytest

from findata.reconciliation.consensus import MedianConsensus


def _make_prices(closes: list[float], dates: list[str] | None = None) -> pd.DataFrame:
    if dates is None:
        dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    idx = pd.to_datetime(dates, utc=True)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1e6] * len(closes),
        },
        index=idx,
    )


class TestMedianConsensus:
    def test_single_source_returned_unchanged(self):
        df = _make_prices([185.0, 186.0, 187.0])
        consensus = MedianConsensus()
        result, warnings = consensus.reconcile({"yahoo": df}, symbol="AAPL")
        pd.testing.assert_frame_equal(result, df)
        assert warnings == []

    def test_two_agreeing_sources(self):
        df1 = _make_prices([185.0, 186.0, 187.0])
        df2 = _make_prices([185.1, 186.1, 187.1])
        consensus = MedianConsensus()
        result, warnings = consensus.reconcile({"yahoo": df1, "finnhub": df2}, symbol="AAPL")
        assert result is not None
        assert warnings == []

    def test_anomalous_source_flagged(self):
        df_good1 = _make_prices([185.0, 186.0, 187.0])
        df_good2 = _make_prices([185.1, 186.1, 187.1])
        df_bad = _make_prices([280.0, 281.0, 282.0])  # far from median

        consensus = MedianConsensus(deviation_threshold=0.01)
        result, warnings = consensus.reconcile(
            {"yahoo": df_good1, "finnhub": df_good2, "bad_source": df_bad},
            symbol="AAPL",
        )
        assert any("bad_source" in w for w in warnings)
        # Best result should be one of the good sources
        assert result["close"].mean() < 200

    def test_no_overlap_warns(self):
        df1 = _make_prices([185.0, 186.0], dates=["2024-01-01", "2024-01-02"])
        df2 = _make_prices([185.0, 186.0], dates=["2024-01-03", "2024-01-04"])
        consensus = MedianConsensus()
        result, warnings = consensus.reconcile({"a": df1, "b": df2}, symbol="AAPL")
        assert any("overlapping" in w for w in warnings)

    def test_empty_frames_dict_raises(self):
        consensus = MedianConsensus()
        with pytest.raises(ValueError):
            consensus.reconcile({}, symbol="AAPL")

    def test_all_empty_dfs_raises(self):
        consensus = MedianConsensus()
        with pytest.raises(ValueError):
            consensus.reconcile({"yahoo": pd.DataFrame(), "sec": pd.DataFrame()}, symbol="AAPL")
