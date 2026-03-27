"""DataSource protocol and shared parameter types."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd
from pydantic import BaseModel

from findata.models.assets import AssetInfo
from findata.models.source import DataSourceMeta, SupportedDataType


class PricesParams(BaseModel):
    """Normalised parameters for a price history request."""

    symbol: str
    start: date | None = None
    end: date | None = None
    #: Convenience period string: "1d","5d","1mo","3mo","6mo","1y","2y","5y","10y","ytd","max"
    period: str | None = None
    interval: str = "1d"


@runtime_checkable
class DataSource(Protocol):
    """Protocol that every data source adapter must satisfy.

    Implementations may be async coroutines or regular functions — the router
    handles both via ``asyncio.iscoroutinefunction`` detection.
    """

    meta: DataSourceMeta

    def supports(self, data_type: SupportedDataType, symbol: str) -> bool:
        """Return True if this source can serve *data_type* for *symbol*."""
        ...

    async def fetch_prices(self, params: PricesParams, *, client: "httpx.AsyncClient") -> pd.DataFrame:  # type: ignore[name-defined]
        """Return a DataFrame with columns: timestamp, open, high, low, close, volume."""
        ...

    async def fetch_info(self, symbol: str, *, client: "httpx.AsyncClient") -> AssetInfo:  # type: ignore[name-defined]
        """Return descriptive asset information."""
        ...

    async def health_check(self, *, client: "httpx.AsyncClient") -> bool:  # type: ignore[name-defined]
        """Return True if the source is currently reachable."""
        ...
