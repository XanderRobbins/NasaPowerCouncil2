"""Binance public API — crypto OHLCV, risk tier 2."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pandas as pd

from xfinance.exceptions import SourceRateLimitError, SourceUnavailableError, SymbolNotFoundError
from xfinance.models.source import DataSourceMeta, SupportedDataType
from xfinance.sources._utils import date_to_timestamp, period_to_dates, safe_float
from xfinance.sources.base import PricesParams

logger = logging.getLogger(__name__)
_BASE = "https://api.binance.com"
_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "6h": "6h", "12h": "12h",
    "1d": "1d", "3d": "3d", "1wk": "1w", "1mo": "1M",
}


class BinanceSource:
    meta = DataSourceMeta(
        name="binance",
        description="Binance public API — 2,000+ crypto pairs, no auth",
        supported_types=[SupportedDataType.CRYPTO, SupportedDataType.PRICES],
        requires_api_key=False,
        rate_limit_per_minute=1200,
        risk_tier=2,
        tos_url="https://www.binance.com/en/terms",
    )

    def supports(self, data_type: SupportedDataType, symbol: str) -> bool:
        return data_type in (SupportedDataType.CRYPTO, SupportedDataType.PRICES)

    async def fetch_prices(self, params: PricesParams, *, client: httpx.AsyncClient) -> pd.DataFrame:
        symbol = self._normalize(params.symbol)
        if params.period:
            start, end = period_to_dates(params.period)
        else:
            start = params.start or date(2017, 8, 17)
            end = params.end or datetime.now(timezone.utc).date()

        interval = _INTERVAL_MAP.get(params.interval, "1d")
        start_ms, end_ms = date_to_timestamp(start) * 1000, date_to_timestamp(end) * 1000

        all_rows: list[list[Any]] = []
        while start_ms < end_ms:
            data = await self._get(client, f"{_BASE}/api/v3/klines", params={
                "symbol": symbol, "interval": interval,
                "startTime": start_ms, "endTime": end_ms, "limit": 1000,
            })
            if not data:
                break
            all_rows.extend(data)
            last_ts = data[-1][0]
            if len(data) < 1000 or last_ts >= end_ms:
                break
            start_ms = last_ts + 1

        return self._parse_klines(all_rows, symbol)

    async def fetch_info(self, symbol: str, *, client: httpx.AsyncClient) -> dict[str, Any]:
        sym = self._normalize(symbol)
        data = await self._get(client, f"{_BASE}/api/v3/ticker/24hr", params={"symbol": sym})
        return {"symbol": symbol, "binanceSymbol": sym, "exchange": "Binance", "source": "binance", **data}

    async def health_check(self, *, client: httpx.AsyncClient) -> bool:
        try:
            resp = await client.get(f"{_BASE}/api/v3/ping", timeout=5)
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    @staticmethod
    def _normalize(symbol: str) -> str:
        return symbol.upper().replace("/", "").replace("-", "")

    async def _get(self, client: httpx.AsyncClient, url: str, *, params: dict[str, Any]) -> Any:
        try:
            resp = await client.get(url, params=params, timeout=15)
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError("binance", f"Timeout: {url}") from exc
        except httpx.RequestError as exc:
            raise SourceUnavailableError("binance", str(exc)) from exc
        if resp.status_code == 429:
            raise SourceRateLimitError("binance", retry_after=float(resp.headers.get("Retry-After", 60)))
        if resp.status_code == 400:
            body = resp.json() if resp.content else {}
            if isinstance(body, dict) and body.get("code") == -1121:
                raise SymbolNotFoundError("binance", params.get("symbol", ""))
        if resp.status_code != 200:
            raise SourceUnavailableError("binance", f"HTTP {resp.status_code}", status_code=resp.status_code)
        try:
            return resp.json()
        except Exception as exc:
            raise SourceUnavailableError("binance", f"Invalid JSON: {exc}") from exc

    @staticmethod
    def _parse_klines(rows: list[list[Any]], symbol: str) -> pd.DataFrame:
        if not rows:
            raise SymbolNotFoundError("binance", symbol)
        parsed = [{
            "Date": datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc),
            "Open": float(r[1]), "High": float(r[2]),
            "Low": float(r[3]), "Close": float(r[4]),
            "Volume": float(r[5]),
            "Dividends": 0.0, "Stock Splits": 0.0,
            "Capital Gains": 0.0, "Adj Close": float(r[4]),
        } for r in rows]
        return pd.DataFrame(parsed).set_index("Date").sort_index()
