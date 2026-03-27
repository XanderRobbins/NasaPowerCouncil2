"""Data source adapters for findata.

Each source implements the DataSource protocol.  Sources are discovered at
runtime both from this package and from any installed community plugins that
register themselves under the ``findata.sources`` entry-point group.
"""

from findata.sources.base import DataSource, PricesParams
from findata.sources.binance import BinanceSource
from findata.sources.coingecko import CoinGeckoSource
from findata.sources.ecb import ECBSource
from findata.sources.sec import SECSource
from findata.sources.yahoo import YahooSource

__all__ = [
    "BinanceSource",
    "CoinGeckoSource",
    "DataSource",
    "ECBSource",
    "PricesParams",
    "SECSource",
    "YahooSource",
]
