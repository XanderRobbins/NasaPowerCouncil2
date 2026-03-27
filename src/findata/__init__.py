"""findata — multi-source, failover-capable Python financial data library.

Quick start
-----------
>>> import findata
>>> df = findata.prices("AAPL", period="1mo")
>>> info = findata.info("AAPL")
>>> fx = findata.forex("USD/EUR", period="1y")
>>> btc = findata.prices("BTCUSDT", period="30d")

For async usage or advanced configuration::

    client = findata.Client(sources=["yahoo", "sec"])
    df = client.prices("AAPL", start="2024-01-01", validate=True)

    async with findata.AsyncClient() as client:
        data = await client.prices(["AAPL", "GOOGL"], period="1y")
"""

from __future__ import annotations

from findata._logging import configure_logging, get_logger
from findata.client.async_client import AsyncClient
from findata.client.sync_client import Client
from findata.exceptions import (
    AllSourcesFailedError,
    ConfigurationError,
    DataValidationError,
    FindataError,
    MissingDependencyError,
    SourceAuthError,
    SourceError,
    SourceRateLimitError,
    SourceUnavailableError,
    SymbolNotFoundError,
)
from findata.models import AssetClass, AssetInfo, DataResult, DataSourceMeta, PriceBar

__version__ = "0.1.0"
__all__ = [
    # One-liner convenience functions
    "prices",
    "info",
    "forex",
    # Clients
    "Client",
    "AsyncClient",
    # Models
    "AssetClass",
    "AssetInfo",
    "DataResult",
    "DataSourceMeta",
    "PriceBar",
    # Exceptions
    "FindataError",
    "SourceError",
    "SourceUnavailableError",
    "SourceRateLimitError",
    "SourceAuthError",
    "SymbolNotFoundError",
    "AllSourcesFailedError",
    "DataValidationError",
    "ConfigurationError",
    "MissingDependencyError",
    # Logging
    "configure_logging",
]

# ── Module-level convenience API ──────────────────────────────────────────────
# These use a process-level default Client instance for the simplest usage.

_default_client: Client | None = None


def _get_default_client() -> Client:
    global _default_client
    if _default_client is None:
        _default_client = Client()
    return _default_client


def prices(
    symbol: "str | list[str]",
    *,
    period: "str | None" = "1mo",
    start: "str | None" = None,
    end: "str | None" = None,
    interval: str = "1d",
) -> "DataResult | dict[str, DataResult]":
    """Fetch OHLCV price history.  One-liner convenience wrapper.

    Parameters
    ----------
    symbol:
        Ticker symbol or list of symbols (e.g. ``'AAPL'``, ``['AAPL', 'MSFT']``).
    period:
        Lookback period: ``'1d'``, ``'5d'``, ``'1mo'``, ``'3mo'``, ``'6mo'``,
        ``'1y'``, ``'2y'``, ``'5y'``, ``'10y'``, ``'ytd'``, ``'max'``.
        Ignored when *start* is provided.
    start / end:
        Date range as ISO strings (``'2024-01-01'``).
    interval:
        Bar interval (``'1d'``, ``'1wk'``, ``'1mo'``, ``'1h'``, …).

    Returns
    -------
    ``DataResult`` for a single symbol; ``dict[symbol, DataResult]`` for a list.

    Examples
    --------
    >>> df = findata.prices("AAPL", period="1mo")
    >>> df = findata.prices(["AAPL", "MSFT"], start="2024-01-01")
    """
    return _get_default_client().prices(
        symbol, period=period, start=start, end=end, interval=interval
    )


def info(symbol: str) -> "AssetInfo":
    """Fetch descriptive asset information.

    Returns asset name, exchange, currency, sector, market cap, etc.

    Examples
    --------
    >>> inf = findata.info("AAPL")
    >>> print(inf.name, inf.sector)
    """
    return _get_default_client().info(symbol)


def forex(
    pair: str,
    *,
    period: "str | None" = "1y",
    start: "str | None" = None,
    end: "str | None" = None,
) -> "DataResult":
    """Fetch forex rate history for a currency pair.

    ECB/Frankfurter is the primary source (zero auth, zero rate limits).

    Parameters
    ----------
    pair:
        Currency pair in BASE/QUOTE format (e.g. ``'USD/EUR'``, ``'GBP/USD'``).

    Examples
    --------
    >>> fx = findata.forex("USD/EUR", period="1y")
    """
    return _get_default_client().forex(pair, period=period, start=start, end=end)
