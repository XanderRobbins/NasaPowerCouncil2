"""ECB / Frankfurter forex data source — risk tier 1."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pandas as pd

from xfinance.exceptions import SourceUnavailableError, SymbolNotFoundError
from xfinance.models.source import DataSourceMeta, SupportedDataType
from xfinance.sources._utils import period_to_dates
from xfinance.sources.base import PricesParams

logger = logging.getLogger(__name__)
_BASE = "https://api.frankfurter.app"


class ECBSource:
    meta = DataSourceMeta(
        name="ecb",
        description="ECB exchange rates via Frankfurter API (150+ currencies)",
        supported_types=[SupportedDataType.FOREX],
        requires_api_key=False,
        rate_limit_per_minute=None,
        risk_tier=1,
        tos_url="https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html",
    )

    def supports(self, data_type: SupportedDataType, symbol: str) -> bool:
        return data_type == SupportedDataType.FOREX

    async def fetch_prices(self, params: PricesParams, *, client: httpx.AsyncClient) -> pd.DataFrame:
        base, quote = self._parse_pair(params.symbol)
        if params.period:
            start, end = period_to_dates(params.period)
        else:
            start = params.start or date(1999, 1, 4)
            end = params.end or datetime.now(timezone.utc).date()

        data = await self._get(client, f"{_BASE}/{start}..{end}", params={"from": base, "to": quote})
        return self._parse_rates(data, base, quote)

    async def fetch_info(self, symbol: str, *, client: httpx.AsyncClient) -> dict[str, Any]:
        base, quote = self._parse_pair(symbol)
        return {"symbol": symbol, "base": base, "quote": quote, "source": "ecb"}

    async def health_check(self, *, client: httpx.AsyncClient) -> bool:
        try:
            resp = await client.get(f"{_BASE}/latest", timeout=5)
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    @staticmethod
    def _parse_pair(symbol: str) -> tuple[str, str]:
        if "/" in symbol:
            parts = symbol.upper().split("/", 1)
            return parts[0], parts[1]
        return "EUR", symbol.upper()

    async def _get(self, client: httpx.AsyncClient, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            resp = await client.get(url, params=params or {}, timeout=10)
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError("ecb", f"Timeout: {url}") from exc
        except httpx.RequestError as exc:
            raise SourceUnavailableError("ecb", str(exc)) from exc
        if resp.status_code == 404:
            raise SymbolNotFoundError("ecb", url)
        if resp.status_code != 200:
            raise SourceUnavailableError("ecb", f"HTTP {resp.status_code}", status_code=resp.status_code)
        try:
            return resp.json()  # type: ignore[return-value]
        except Exception as exc:
            raise SourceUnavailableError("ecb", f"Invalid JSON: {exc}") from exc

    @staticmethod
    def _parse_rates(data: dict[str, Any], base: str, quote: str) -> pd.DataFrame:
        rates_by_date = data.get("rates", {})
        if not rates_by_date:
            raise SourceUnavailableError("ecb", "Empty rates response")
        rows = []
        for date_str, rates in rates_by_date.items():
            rate = rates.get(quote)
            if rate is None:
                continue
            rows.append({
                "Date": pd.Timestamp(date_str, tz="UTC"),
                "Open": float(rate), "High": float(rate),
                "Low": float(rate), "Close": float(rate),
                "Volume": 0, "Dividends": 0.0, "Stock Splits": 0.0,
                "Capital Gains": 0.0, "Adj Close": float(rate),
            })
        df = pd.DataFrame(rows)
        if df.empty:
            raise SourceUnavailableError("ecb", f"No data for {base}/{quote}")
        return df.set_index("Date").sort_index()
