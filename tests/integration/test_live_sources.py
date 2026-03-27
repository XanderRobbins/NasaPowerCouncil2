"""Integration tests against live APIs.

These tests make REAL network calls and are excluded from CI by default.
Run manually with:  pytest tests/integration/ -m integration

A weekly scheduled CI job runs these to detect upstream API changes.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Live API — run manually with pytest -m integration")
async def test_yahoo_live_aapl():
    """Yahoo Finance returns valid AAPL prices."""
    import httpx
    from findata.sources.yahoo import YahooSource
    from findata.sources.base import PricesParams

    src = YahooSource()
    async with httpx.AsyncClient(follow_redirects=True) as client:
        df = await src.fetch_prices(PricesParams(symbol="AAPL", period="5d"), client=client)
    assert not df.empty
    assert "close" in df.columns
    assert (df["close"] > 0).all()


@pytest.mark.skip(reason="Live API — run manually with pytest -m integration")
async def test_ecb_live_usd_eur():
    """ECB returns valid USD/EUR forex data."""
    import httpx
    from findata.sources.ecb import ECBSource
    from findata.sources.base import PricesParams

    src = ECBSource()
    async with httpx.AsyncClient() as client:
        df = await src.fetch_prices(PricesParams(symbol="USD/EUR", period="5d"), client=client)
    assert not df.empty
    assert "close" in df.columns
    assert (df["close"] > 0).all()
    assert (df["close"] < 2).all()  # USD/EUR is never > 2


@pytest.mark.skip(reason="Live API — run manually with pytest -m integration")
async def test_binance_live_btcusdt():
    """Binance returns valid BTCUSDT klines."""
    import httpx
    from findata.sources.binance import BinanceSource
    from findata.sources.base import PricesParams

    src = BinanceSource()
    async with httpx.AsyncClient() as client:
        df = await src.fetch_prices(PricesParams(symbol="BTCUSDT", period="5d"), client=client)
    assert not df.empty
    assert "close" in df.columns
    assert (df["close"] > 1000).all()  # BTC has been > $1000 since 2017


@pytest.mark.skip(reason="Live API — run manually with pytest -m integration")
async def test_sec_live_aapl_info():
    """SEC EDGAR returns valid Apple Inc. information."""
    import httpx
    from findata.sources.sec import SECSource

    src = SECSource()
    async with httpx.AsyncClient() as client:
        info = await src.fetch_info("AAPL", client=client)
    assert info.name  # has a name
    assert info.extra.get("cik")  # has a CIK
    assert info.country == "US"
