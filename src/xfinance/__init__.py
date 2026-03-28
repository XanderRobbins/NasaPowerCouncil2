"""xfinance — the definitive open-source yfinance alternative.

Everything yfinance offers, plus multi-source failover, SEC EDGAR fundamentals,
ECB forex, Binance/CoinGecko crypto, intelligent caching, and fully normalized output.

Quick start
-----------
>>> import xfinance as xf

# --- Exactly like yfinance ---
>>> t = xf.Ticker("AAPL")
>>> df = t.history(period="1y")
>>> t.info
>>> t.financials          # income statement
>>> t.balance_sheet
>>> t.cashflow
>>> t.dividends
>>> t.splits
>>> t.options             # available expiry dates
>>> chain = t.option_chain("2025-01-17")
>>> chain.calls
>>> t.recommendations
>>> t.institutional_holders
>>> t.insider_transactions
>>> t.calendar
>>> t.news
>>> t.analyst_price_targets

# --- Unique to xfinance ---
>>> t.sec_financials("Revenues")          # direct from SEC EDGAR
>>> t.get_shares_full()                   # shares outstanding history

# --- Bulk download ---
>>> df = xf.download(["AAPL", "MSFT", "GOOGL"], period="1y")

# --- Forex (ECB, free, unlimited) ---
>>> fx = xf.download("EURUSD=X", period="2y")   # via Yahoo
>>> t = xf.Ticker("USD/EUR")                     # via ECB directly

# --- Crypto ---
>>> btc = xf.Ticker("BTC-USD").history(period="1y")   # via Yahoo
>>> btc = xf.download("BTCUSDT", period="1y")          # via Binance
"""

from __future__ import annotations

from xfinance._logging import configure_logging, enable_debug_mode
from xfinance.download import download
from xfinance.exceptions import (
    AllSourcesFailedError,
    ConfigurationError,
    DataValidationError,
    MissingDependencyError,
    SourceAuthError,
    SourceError,
    SourceRateLimitError,
    SourceUnavailableError,
    SymbolNotFoundError,
    XFinanceError,
)
from xfinance.market import Market
from xfinance.screener import EquityQuery, FundQuery, Screener, screen
from xfinance.search import Search
from xfinance.sector import Industry, Sector
from xfinance.stream import stream, stream_sync
from xfinance.ticker import Ticker
from xfinance.tickers import Tickers

__version__ = "0.3.0"
__all__ = [
    "Ticker",
    "Tickers",
    "download",
    "configure_logging",
    "enable_debug_mode",
    "screen",
    "Search",
    "Sector",
    "Industry",
    "Market",
    "Screener",
    "EquityQuery",
    "FundQuery",
    "stream",
    "stream_sync",
    # Exceptions
    "XFinanceError",
    "SourceError",
    "SourceUnavailableError",
    "SourceRateLimitError",
    "SourceAuthError",
    "SymbolNotFoundError",
    "AllSourcesFailedError",
    "DataValidationError",
    "ConfigurationError",
    "MissingDependencyError",
]
