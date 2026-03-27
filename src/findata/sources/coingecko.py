"""CoinGecko public API data source adapter.

Uses the free public tier (no API key).
Rate limit: 30 calls/minute.  14,000+ coins.  Risk tier 2.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pandas as pd

from findata.exceptions import SourceRateLimitError, SourceUnavailableError, SymbolNotFoundError
from findata.models.assets import AssetClass, AssetInfo
from findata.models.source import DataSourceMeta, SupportedDataType
from findata.sources._utils import period_to_dates, safe_float
from findata.sources.base import DataSource, PricesParams

logger = logging.getLogger(__name__)

_BASE = "https://api.coingecko.com/api/v3"


class CoinGeckoSource:
    """Data source for CoinGecko public API.

    Accepts CoinGecko coin IDs (e.g. 'bitcoin', 'ethereum') or common ticker
    symbols like 'BTC' / 'ETH' (auto-resolved via the coins/list endpoint).
    """

    meta = DataSourceMeta(
        name="coingecko",
        description="CoinGecko public API — 14,000+ coins, market data",
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

        days = (end - start).days
        if days <= 0:
            days = 1

        data = await self._get(
            client,
            f"{_BASE}/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": str(days), "interval": "daily"},
        )
        return self._parse_market_chart(data, coin_id)

    async def fetch_info(self, symbol: str, *, client: httpx.AsyncClient) -> AssetInfo:
        coin_id = await self._resolve_id(symbol, client)
        data = await self._get(client, f"{_BASE}/coins/{coin_id}", params={
            "localization": "false", "tickers": "false",
            "community_data": "false", "developer_data": "false",
        })

        market_data = data.get("market_data", {})
        market_cap_raw = market_data.get("market_cap", {}).get("usd")

        return AssetInfo(
            symbol=symbol.upper(),
            name=data.get("name", ""),
            asset_class=AssetClass.CRYPTO,
            exchange="",
            currency="USD",
            description=data.get("description", {}).get("en", ""),
            market_cap=safe_float(market_cap_raw),
            website=data.get("links", {}).get("homepage", [""])[0],
            extra={
                "coingecko_id": coin_id,
                "symbol": data.get("symbol", "").upper(),
                "rank": data.get("market_cap_rank"),
                "categories": data.get("categories", []),
            },
            source="coingecko",
        )

    async def health_check(self, *, client: httpx.AsyncClient) -> bool:
        try:
            resp = await client.get(f"{_BASE}/ping", timeout=5)
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _resolve_id(self, symbol: str, client: httpx.AsyncClient) -> str:
        """Map a symbol like 'BTC' or 'bitcoin' to CoinGecko coin ID."""
        lower = symbol.lower()
        if lower in self._symbol_to_id:
            return self._symbol_to_id[lower]

        # Try direct ID first (e.g. 'bitcoin')
        try:
            resp = await client.get(
                f"{_BASE}/coins/{lower}",
                params={"localization": "false", "tickers": "false",
                        "market_data": "false", "community_data": "false",
                        "developer_data": "false"},
                timeout=10,
            )
            if resp.status_code == 200:
                self._symbol_to_id[lower] = lower
                return lower
        except httpx.RequestError:
            pass

        # Fall back to searching the full coins list
        if not self._symbol_to_id:
            await self._populate_symbol_map(client)

        coin_id = self._symbol_to_id.get(lower)
        if not coin_id:
            raise SymbolNotFoundError("coingecko", symbol)
        return coin_id

    async def _populate_symbol_map(self, client: httpx.AsyncClient) -> None:
        data = await self._get(client, f"{_BASE}/coins/list", params={})
        for entry in data:
            sym = entry.get("symbol", "").lower()
            cid = entry.get("id", "")
            # Keep first occurrence (most established coin for that symbol)
            if sym and cid and sym not in self._symbol_to_id:
                self._symbol_to_id[sym] = cid
            # Also map by full name
            name = entry.get("name", "").lower()
            if name and name not in self._symbol_to_id:
                self._symbol_to_id[name] = cid

    async def _get(
        self, client: httpx.AsyncClient, url: str, *, params: dict[str, Any]
    ) -> Any:
        try:
            resp = await client.get(url, params=params, timeout=15)
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError("coingecko", f"Request timed out: {url}") from exc
        except httpx.RequestError as exc:
            raise SourceUnavailableError("coingecko", str(exc)) from exc

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 60))
            raise SourceRateLimitError("coingecko", retry_after=retry_after)
        if resp.status_code == 404:
            raise SymbolNotFoundError("coingecko", url.rsplit("/", 1)[-1])
        if resp.status_code != 200:
            raise SourceUnavailableError(
                "coingecko", f"HTTP {resp.status_code}: {url}", status_code=resp.status_code
            )

        try:
            return resp.json()
        except Exception as exc:
            raise SourceUnavailableError("coingecko", f"Invalid JSON: {exc}") from exc

    @staticmethod
    def _parse_market_chart(data: dict[str, Any], coin_id: str) -> pd.DataFrame:
        prices = data.get("prices", [])
        volumes = data.get("total_volumes", [])
        vol_map = {ts: v for ts, v in volumes}

        rows = []
        for ts_ms, price in prices:
            ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            rows.append(
                {
                    "timestamp": ts,
                    "open": float(price),
                    "high": float(price),
                    "low": float(price),
                    "close": float(price),
                    "volume": float(vol_map.get(ts_ms, 0)),
                }
            )

        if not rows:
            raise SourceUnavailableError("coingecko", f"No price data for {coin_id}")

        df = pd.DataFrame(rows)
        return df.set_index("timestamp").sort_index()
