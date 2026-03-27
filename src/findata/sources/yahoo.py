"""Yahoo Finance data source adapter.

Uses the unofficial v8/v10 JSON endpoints.  Implements cookie + crumb
authentication as yfinance does.  Risk tier 3 (unofficial API).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pandas as pd

from findata.exceptions import (
    SourceAuthError,
    SourceRateLimitError,
    SourceUnavailableError,
    SymbolNotFoundError,
)
from findata.models.assets import AssetClass, AssetInfo
from findata.models.source import DataSourceMeta, SupportedDataType
from findata.sources._utils import date_to_timestamp, period_to_dates, safe_float
from findata.sources.base import DataSource, PricesParams

logger = logging.getLogger(__name__)

_BASE = "https://query1.finance.yahoo.com"
_BASE2 = "https://query2.finance.yahoo.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

_ASSET_TYPE_MAP: dict[str, AssetClass] = {
    "EQUITY": AssetClass.EQUITY,
    "ETF": AssetClass.ETF,
    "MUTUALFUND": AssetClass.ETF,
    "CRYPTOCURRENCY": AssetClass.CRYPTO,
    "CURRENCY": AssetClass.FOREX,
    "FUTURE": AssetClass.FUTURES,
    "INDEX": AssetClass.INDEX,
    "OPTION": AssetClass.OPTION,
}


class _YahooCrumb:
    """Manages the session cookie + crumb needed by Yahoo's API."""

    def __init__(self) -> None:
        self._crumb: str | None = None

    async def get(self, client: httpx.AsyncClient) -> str:
        if self._crumb is None:
            await self._refresh(client)
        return self._crumb  # type: ignore[return-value]

    async def _refresh(self, client: httpx.AsyncClient) -> None:
        # Step 1: obtain session cookie
        try:
            resp = await client.get(
                "https://fc.yahoo.com",
                headers=_HEADERS,
                follow_redirects=True,
                timeout=10,
            )
        except httpx.RequestError as exc:
            raise SourceUnavailableError("yahoo", f"Cookie fetch failed: {exc}") from exc

        # Step 2: fetch crumb
        try:
            crumb_resp = await client.get(
                f"{_BASE}/v1/test/getcrumb",
                headers={**_HEADERS, "referer": "https://finance.yahoo.com/"},
                timeout=10,
            )
        except httpx.RequestError as exc:
            raise SourceUnavailableError("yahoo", f"Crumb fetch failed: {exc}") from exc

        if crumb_resp.status_code != 200 or not crumb_resp.text.strip():
            logger.warning("Yahoo crumb unavailable (%d); proceeding without", crumb_resp.status_code)
            self._crumb = ""
            return

        self._crumb = crumb_resp.text.strip()
        logger.debug("Yahoo crumb refreshed: %s", self._crumb)

    def invalidate(self) -> None:
        self._crumb = None


class YahooSource:
    """Data source adapter for Yahoo Finance (unofficial API, risk tier 3)."""

    meta = DataSourceMeta(
        name="yahoo",
        description="Yahoo Finance unofficial JSON API",
        supported_types=[
            SupportedDataType.PRICES,
            SupportedDataType.INFO,
            SupportedDataType.OPTIONS,
            SupportedDataType.CRYPTO,
            SupportedDataType.FOREX,
        ],
        requires_api_key=False,
        rate_limit_per_minute=60,
        risk_tier=3,
        tos_url="https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
    )

    def __init__(self) -> None:
        self._crumb = _YahooCrumb()

    def supports(self, data_type: SupportedDataType, symbol: str) -> bool:
        return data_type in self.meta.supported_types

    async def fetch_prices(self, params: PricesParams, *, client: httpx.AsyncClient) -> pd.DataFrame:
        if params.period:
            start, end = period_to_dates(params.period)
        else:
            start = params.start or date(1970, 1, 1)
            end = params.end or datetime.now(timezone.utc).date()

        crumb = await self._crumb.get(client)
        query: dict[str, Any] = {
            "period1": date_to_timestamp(start),
            "period2": date_to_timestamp(end),
            "interval": params.interval,
            "includeAdjustedClose": "true",
        }
        if crumb:
            query["crumb"] = crumb

        url = f"{_BASE}/v8/finance/chart/{params.symbol}"
        resp = await self._get(client, url, params=query)
        return self._parse_chart(resp, params.symbol)

    async def fetch_info(self, symbol: str, *, client: httpx.AsyncClient) -> AssetInfo:
        crumb = await self._crumb.get(client)
        query: dict[str, Any] = {
            "modules": "summaryProfile,summaryDetail,defaultKeyStatistics,quoteType",
        }
        if crumb:
            query["crumb"] = crumb

        url = f"{_BASE}/v10/finance/quoteSummary/{symbol}"
        data = await self._get(client, url, params=query)
        return self._parse_info(data, symbol)

    async def health_check(self, *, client: httpx.AsyncClient) -> bool:
        try:
            resp = await client.get(
                f"{_BASE}/v8/finance/chart/AAPL",
                headers=_HEADERS,
                timeout=5,
                follow_redirects=True,
            )
            return resp.status_code in {200, 401, 403}
        except httpx.RequestError:
            return False

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _get(
        self, client: httpx.AsyncClient, url: str, *, params: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            resp = await client.get(url, params=params, headers=_HEADERS, timeout=15, follow_redirects=True)
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError("yahoo", f"Request timed out: {url}") from exc
        except httpx.RequestError as exc:
            raise SourceUnavailableError("yahoo", str(exc)) from exc

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 60))
            self._crumb.invalidate()
            raise SourceRateLimitError("yahoo", retry_after=retry_after)
        if resp.status_code in {401, 403}:
            self._crumb.invalidate()
            raise SourceAuthError("yahoo", "Authentication failed; crumb may have expired", status_code=resp.status_code)
        if resp.status_code == 404:
            raise SymbolNotFoundError("yahoo", url.rsplit("/", 1)[-1])
        if resp.status_code != 200:
            raise SourceUnavailableError("yahoo", f"HTTP {resp.status_code}: {url}", status_code=resp.status_code)

        try:
            return resp.json()  # type: ignore[no-any-return]
        except Exception as exc:
            raise SourceUnavailableError("yahoo", f"Invalid JSON response: {exc}") from exc

    def _parse_chart(self, data: dict[str, Any], symbol: str) -> pd.DataFrame:
        try:
            result = data["chart"]["result"]
            if not result:
                error = data["chart"].get("error") or {}
                raise SymbolNotFoundError("yahoo", symbol)

            r = result[0]
            timestamps = r["timestamp"]
            ohlcv = r["indicators"]["quote"][0]
            adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose", [])

            rows = []
            for i, ts in enumerate(timestamps):
                o = safe_float(ohlcv["open"][i])
                h = safe_float(ohlcv["high"][i])
                lo = safe_float(ohlcv["low"][i])
                c = safe_float(ohlcv["close"][i])
                v = safe_float(ohlcv["volume"][i])
                if None in (o, h, lo, c):
                    continue
                rows.append(
                    {
                        "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc),
                        "open": o,
                        "high": h,
                        "low": lo,
                        "close": c,
                        "volume": v or 0.0,
                        "adjusted_close": safe_float(adj[i]) if i < len(adj) else None,
                    }
                )

            df = pd.DataFrame(rows)
            if df.empty:
                raise SymbolNotFoundError("yahoo", symbol)
            df = df.set_index("timestamp").sort_index()
            return df

        except (KeyError, IndexError, TypeError) as exc:
            raise SourceUnavailableError("yahoo", f"Unexpected chart format: {exc}") from exc

    def _parse_info(self, data: dict[str, Any], symbol: str) -> AssetInfo:
        try:
            result = data.get("quoteSummary", {}).get("result") or []
            if not result:
                raise SymbolNotFoundError("yahoo", symbol)
            r = result[0]
            profile = r.get("summaryProfile", {})
            key_stats = r.get("defaultKeyStatistics", {})
            quote_type = r.get("quoteType", {})
            detail = r.get("summaryDetail", {})

            raw_type = quote_type.get("quoteType", "UNKNOWN")
            asset_class = _ASSET_TYPE_MAP.get(raw_type, AssetClass.UNKNOWN)
            market_cap = detail.get("marketCap", {}).get("raw")

            return AssetInfo(
                symbol=symbol,
                name=quote_type.get("longName") or quote_type.get("shortName", ""),
                asset_class=asset_class,
                exchange=quote_type.get("exchange", ""),
                currency=quote_type.get("currency", ""),
                country=profile.get("country", ""),
                sector=profile.get("sector", ""),
                industry=profile.get("industry", ""),
                description=profile.get("longBusinessSummary", ""),
                market_cap=safe_float(market_cap) if market_cap is not None else None,
                employees=profile.get("fullTimeEmployees"),
                website=profile.get("website", ""),
                extra={"key_stats": key_stats},
                source="yahoo",
            )
        except (KeyError, TypeError) as exc:
            raise SourceUnavailableError("yahoo", f"Unexpected info format: {exc}") from exc
