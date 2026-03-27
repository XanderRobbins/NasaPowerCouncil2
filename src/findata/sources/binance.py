"""Binance public API data source adapter.

Uses the public REST API endpoints — no authentication required.
Provides OHLCV klines for 2,000+ crypto pairs.
Rate limit: 1200 requests/minute (weight-based).
Risk tier 2.
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
from findata.sources._utils import date_to_timestamp, period_to_dates, safe_float
from findata.sources.base import DataSource, PricesParams

logger = logging.getLogger(__name__)

_BASE = "https://api.binance.com"
_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "6h": "6h", "12h": "12h",
    "1d": "1d", "3d": "3d", "1wk": "1w", "1mo": "1M",
}


class BinanceSource:
    """Data source for Binance public REST API (crypto OHLCV).

    Symbols should be formatted as Binance pairs: 'BTCUSDT', 'ETHUSDT'.
    The slash-notation 'BTC/USDT' is also accepted and auto-converted.
    """

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
        if data_type not in (SupportedDataType.CRYPTO, SupportedDataType.PRICES):
            return False
        # Accept slash notation or direct Binance symbol
        sym = self._normalize_symbol(symbol)
        return len(sym) >= 5  # heuristic: at least 5 chars like BTCUSDT

    async def fetch_prices(self, params: PricesParams, *, client: httpx.AsyncClient) -> pd.DataFrame:
        symbol = self._normalize_symbol(params.symbol)

        if params.period:
            start, end = period_to_dates(params.period)
        else:
            start = params.start or date(2017, 8, 17)  # Binance founding date
            end = params.end or datetime.now(timezone.utc).date()

        interval = _INTERVAL_MAP.get(params.interval, "1d")
        start_ms = date_to_timestamp(start) * 1000
        end_ms = date_to_timestamp(end) * 1000

        all_rows: list[list[Any]] = []
        while start_ms < end_ms:
            resp_data = await self._get(
                client,
                f"{_BASE}/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": 1000,
                },
            )
            if not resp_data:
                break
            all_rows.extend(resp_data)
            last_ts = resp_data[-1][0]
            if len(resp_data) < 1000 or last_ts >= end_ms:
                break
            start_ms = last_ts + 1

        return self._parse_klines(all_rows, symbol)

    async def fetch_info(self, symbol: str, *, client: httpx.AsyncClient) -> AssetInfo:
        sym = self._normalize_symbol(symbol)
        data = await self._get(
            client,
            f"{_BASE}/api/v3/ticker/24hr",
            params={"symbol": sym},
        )
        return AssetInfo(
            symbol=symbol,
            name=sym,
            asset_class=AssetClass.CRYPTO,
            exchange="Binance",
            currency=sym[-4:] if sym.endswith(("USDT", "BUSD")) else "",
            extra={"volume": data.get("volume"), "quoteVolume": data.get("quoteVolume")},
            source="binance",
        )

    async def health_check(self, *, client: httpx.AsyncClient) -> bool:
        try:
            resp = await client.get(f"{_BASE}/api/v3/ping", timeout=5)
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        return symbol.upper().replace("/", "").replace("-", "")

    async def _get(
        self, client: httpx.AsyncClient, url: str, *, params: dict[str, Any]
    ) -> Any:
        try:
            resp = await client.get(url, params=params, timeout=15)
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError("binance", f"Request timed out: {url}") from exc
        except httpx.RequestError as exc:
            raise SourceUnavailableError("binance", str(exc)) from exc

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 60))
            raise SourceRateLimitError("binance", retry_after=retry_after)
        if resp.status_code == 400:
            body = resp.json() if resp.content else {}
            if isinstance(body, dict) and body.get("code") == -1121:
                raise SymbolNotFoundError("binance", params.get("symbol", ""))
        if resp.status_code != 200:
            raise SourceUnavailableError("binance", f"HTTP {resp.status_code}: {url}", status_code=resp.status_code)

        try:
            return resp.json()
        except Exception as exc:
            raise SourceUnavailableError("binance", f"Invalid JSON: {exc}") from exc

    @staticmethod
    def _parse_klines(rows: list[list[Any]], symbol: str) -> pd.DataFrame:
        """Parse Binance kline array into DataFrame.

        Each row: [open_time, open, high, low, close, volume, close_time, ...]
        """
        if not rows:
            raise SymbolNotFoundError("binance", symbol)

        parsed = []
        for row in rows:
            ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
            parsed.append(
                {
                    "timestamp": ts,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
            )

        df = pd.DataFrame(parsed)
        return df.set_index("timestamp").sort_index()
