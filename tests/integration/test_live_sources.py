"""Integration tests against live APIs — skipped in CI, run manually.

    pytest tests/integration/ -m integration
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Live API — run manually")
async def test_yahoo_prices():
    import httpx
    from xfinance.sources.yahoo import YahooSource
    from xfinance.sources.base import PricesParams
    from xfinance import cleaner

    src = YahooSource()
    async with httpx.AsyncClient(follow_redirects=True) as client:
        raw = await src.fetch_prices(PricesParams(symbol="AAPL", period="5d"), client=client)
    df = cleaner.clean_prices(raw)
    assert not df.empty
    assert (df["Close"] > 0).all()
    assert df.index.tz is not None


@pytest.mark.skip(reason="Live API — run manually")
async def test_yahoo_info():
    import httpx
    from xfinance.sources.yahoo import YahooSource
    from xfinance import cleaner

    src = YahooSource()
    async with httpx.AsyncClient(follow_redirects=True) as client:
        raw = await src.fetch_info("AAPL", client=client)
    info = cleaner.clean_info(raw)
    assert info.get("symbol") == "AAPL"
    assert isinstance(info.get("marketCap"), (int, float))


@pytest.mark.skip(reason="Live API — run manually")
async def test_yahoo_options():
    import httpx
    from xfinance.sources.yahoo import YahooSource
    from xfinance import cleaner

    src = YahooSource()
    async with httpx.AsyncClient(follow_redirects=True) as client:
        expiries = await src.fetch_option_expiries("AAPL", client=client)
        assert len(expiries) > 0
        chain = await src.fetch_option_chain("AAPL", expiries[0], client=client)
    calls = cleaner.clean_options(chain.calls)
    puts = cleaner.clean_options(chain.puts)
    assert not calls.empty
    assert not puts.empty
    assert (calls["strike"] > 0).all()


@pytest.mark.skip(reason="Live API — run manually")
async def test_yahoo_financials():
    import httpx
    from xfinance.sources.yahoo import YahooSource
    from xfinance import cleaner

    src = YahooSource()
    async with httpx.AsyncClient(follow_redirects=True) as client:
        raw = await src.fetch_financials("AAPL", client=client)
    mod = raw.get("incomeStatementHistory", {})
    df = YahooSource.parse_financial_statement(mod, "incomeStatementHistory")
    cleaned = cleaner.clean_financial_statement(df)
    assert not cleaned.empty
    assert "Total Revenue" in cleaned.index


@pytest.mark.skip(reason="Live API — run manually")
async def test_ecb_forex():
    import httpx
    from xfinance.sources.ecb import ECBSource
    from xfinance.sources.base import PricesParams

    src = ECBSource()
    async with httpx.AsyncClient() as client:
        df = await src.fetch_prices(PricesParams(symbol="USD/EUR", period="5d"), client=client)
    assert not df.empty
    assert 0 < df["Close"].mean() < 2


@pytest.mark.skip(reason="Live API — run manually")
async def test_binance_crypto():
    import httpx
    from xfinance.sources.binance import BinanceSource
    from xfinance.sources.base import PricesParams

    src = BinanceSource()
    async with httpx.AsyncClient() as client:
        df = await src.fetch_prices(PricesParams(symbol="BTCUSDT", period="5d"), client=client)
    assert not df.empty
    assert (df["Close"] > 1000).all()


@pytest.mark.skip(reason="Live API — run manually")
async def test_sec_company_facts():
    import httpx
    from xfinance.sources.sec import SECSource

    src = SECSource()
    async with httpx.AsyncClient() as client:
        info = await src.fetch_info("AAPL", client=client)
    assert info["name"]
    assert info["cik"]


@pytest.mark.skip(reason="Live API — run manually")
def test_ticker_history():
    import xfinance as xf
    t = xf.Ticker("AAPL")
    df = t.history(period="5d")
    assert not df.empty
    assert "Close" in df.columns
    assert (df["Close"] > 0).all()


@pytest.mark.skip(reason="Live API — run manually")
def test_ticker_financials():
    import xfinance as xf
    t = xf.Ticker("AAPL")
    fs = t.financials
    assert not fs.empty
    assert "Total Revenue" in fs.index


@pytest.mark.skip(reason="Live API — run manually")
def test_download_multi():
    import xfinance as xf
    df = xf.download(["AAPL", "MSFT"], period="5d")
    assert not df.empty
    assert ("Close", "AAPL") in df.columns or "Close" in df.columns
