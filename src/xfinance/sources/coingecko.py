"""CoinGecko public API — 14,000+ coins, risk tier 2."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pandas as pd

from xfinance.exceptions import SourceRateLimitError, SourceUnavailableError, SymbolNotFoundError
from xfinance.models.source import DataSourceMeta, SupportedDataType
from xfinance.sources._utils import period_to_dates, safe_float
from xfinance.sources.base import PricesParams

logger = logging.getLogger(__name__)
_BASE = "https://api.coingecko.com/api/v3"


class CoinGeckoSource:
    meta = DataSourceMeta(
        name="coingecko",
        description="CoinGecko public API — 14,000+ coins",
        supported_types=[SupportedDataType.CRYPTO, SupportedDataType.INFO],
        requires_api_key=False,
        rate_limit_per_minute=30,
        risk_tier=2,
        tos_url="https://www.coingecko.com/en/terms",
    )

    def __init__(self) -> None:
        self._symbol_to_id: dict[str, str] = {}

    def supports(self, data_type: SupportedDataType, symbol: str) -> bool:
        return data_type in (SupportedDataType.CRYPTO, SupportedDataType.INFO)

    async def fetch_prices(self, params: PricesParams, *, client: httpx.AsyncClient) -> pd.DataFrame:
        coin_id = await self._resolve_id(params.symbol, client)
        if params.period:
            start, end = period_to_dates(params.period)
        else:
            start = params.start or date(2013, 4, 28)
            end = params.end or datetime.now(timezone.utc).date()
        days = max((end - start).days, 1)
        data = await self._get(client, f"{_BASE}/coins/{coin_id}/market_chart",
                               params={"vs_currency": "usd", "days": str(days), "interval": "daily"})
        return self._parse_chart(data, coin_id)

    async def fetch_info(self, symbol: str, *, client: httpx.AsyncClient) -> dict[str, Any]:
        coin_id = await self._resolve_id(symbol, client)
        data = await self._get(client, f"{_BASE}/coins/{coin_id}",
                               params={"localization": "false", "tickers": "false",
                                       "community_data": "false", "developer_data": "false"})
        md = data.get("market_data", {})
        return {
            "symbol": symbol.upper(), "coingecko_id": coin_id,
            "name": data.get("name", ""), "source": "coingecko",
            "market_cap": safe_float((md.get("market_cap") or {}).get("usd")),
            "current_price": safe_float((md.get("current_price") or {}).get("usd")),
            "rank": data.get("market_cap_rank"),
            "categories": data.get("categories", []),
            "description": data.get("description", {}).get("en", ""),
            "website": (data.get("links") or {}).get("homepage", [""])[0],
        }

    async def health_check(self, *, client: httpx.AsyncClient) -> bool:
        try:
            resp = await client.get(f"{_BASE}/ping", timeout=5)
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    async def _resolve_id(self, symbol: str, client: httpx.AsyncClient) -> str:
        lower = symbol.lower()
        if lower in self._symbol_to_id:
            return self._symbol_to_id[lower]
        try:
            resp = await client.get(f"{_BASE}/coins/{lower}",
                                    params={"localization": "false", "tickers": "false",
                                            "market_data": "false", "community_data": "false",
                                            "developer_data": "false"}, timeout=10)
            if resp.status_code == 200:
                self._symbol_to_id[lower] = lower
                return lower
        except httpx.RequestError:
            pass
        if not self._symbol_to_id:
            await self._populate_map(client)
        coin_id = self._symbol_to_id.get(lower)
        if not coin_id:
            raise SymbolNotFoundError("coingecko", symbol)
        return coin_id

    async def _populate_map(self, client: httpx.AsyncClient) -> None:
        data = await self._get(client, f"{_BASE}/coins/list", params={})
        for entry in data:
            sym = entry.get("symbol", "").lower()
            cid = entry.get("id", "")
            if sym and cid and sym not in self._symbol_to_id:
                self._symbol_to_id[sym] = cid
            name = entry.get("name", "").lower()
            if name and name not in self._symbol_to_id:
                self._symbol_to_id[name] = cid

    async def _get(self, client: httpx.AsyncClient, url: str, *, params: dict[str, Any]) -> Any:
        try:
            resp = await client.get(url, params=params, timeout=15)
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError("coingecko", f"Timeout: {url}") from exc
        except httpx.RequestError as exc:
            raise SourceUnavailableError("coingecko", str(exc)) from exc
        if resp.status_code == 429:
            raise SourceRateLimitError("coingecko", retry_after=float(resp.headers.get("Retry-After", 60)))
        if resp.status_code == 404:
            raise SymbolNotFoundError("coingecko", url.rsplit("/", 1)[-1])
        if resp.status_code != 200:
            raise SourceUnavailableError("coingecko", f"HTTP {resp.status_code}", status_code=resp.status_code)
        try:
            return resp.json()
        except Exception as exc:
            raise SourceUnavailableError("coingecko", f"Invalid JSON: {exc}") from exc

    @staticmethod
    def _parse_chart(data: dict[str, Any], coin_id: str) -> pd.DataFrame:
        prices = data.get("prices", [])
        vol_map = {ts: v for ts, v in data.get("total_volumes", [])}
        rows = [{
            "Date": datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
            "Open": float(p), "High": float(p), "Low": float(p), "Close": float(p),
            "Volume": float(vol_map.get(ts, 0)),
            "Dividends": 0.0, "Stock Splits": 0.0,
            "Capital Gains": 0.0, "Adj Close": float(p),
        } for ts, p in prices]
        if not rows:
            raise SourceUnavailableError("coingecko", f"No data for {coin_id}")
        return pd.DataFrame(rows).set_index("Date").sort_index()
