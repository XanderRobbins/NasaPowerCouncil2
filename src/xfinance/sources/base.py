"""DataSource protocol and shared parameter types."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd
from pydantic import BaseModel

from xfinance.models.source import DataSourceMeta, SupportedDataType


class PricesParams(BaseModel):
    symbol: str
    start: date | None = None
    end: date | None = None
    period: str | None = None
    interval: str = "1d"


@runtime_checkable
class DataSource(Protocol):
    meta: DataSourceMeta

    def supports(self, data_type: SupportedDataType, symbol: str) -> bool: ...
    async def fetch_prices(self, params: PricesParams, *, client: "httpx.AsyncClient") -> pd.DataFrame: ...  # type: ignore[name-defined]
    async def fetch_info(self, symbol: str, *, client: "httpx.AsyncClient") -> object: ...  # type: ignore[name-defined]
    async def health_check(self, *, client: "httpx.AsyncClient") -> bool: ...  # type: ignore[name-defined]
