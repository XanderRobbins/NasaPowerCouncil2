"""AsyncClient — async-first financial data client with multi-source failover."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any, Sequence

import httpx
import pandas as pd

from findata.exceptions import AllSourcesFailedError
from findata.models.result import DataResult, SourceContribution
from findata.reconciliation.consensus import MedianConsensus
from findata.reconciliation.validator import DataValidator
from findata.sources._utils import period_to_dates
from findata.sources.base import PricesParams
from findata.sources.router import DataSourceRouter
from findata.stores.manager import CacheManager

logger = logging.getLogger(__name__)

_DEFAULT_SOURCES = ["yahoo", "sec", "ecb", "binance", "coingecko"]


class AsyncClient:
    """Async client for fetching financial data from multiple sources.

    Parameters
    ----------
    sources:
        Ordered list of source names to use.  Earlier sources are tried first.
        Defaults to all built-in sources.
    use_cache:
        Whether to enable L1 (memory) caching.  Always enabled by default.
    use_disk_cache:
        Whether to enable L2 (diskcache) persistence.  Requires ``findata[cache]``.
    cache_dir:
        Directory for the disk cache.
    validate:
        Whether to validate returned data by default.
    discover_plugins:
        Whether to discover community plugins.
    http2:
        Whether to enable HTTP/2.
    """

    def __init__(
        self,
        sources: list[str] | None = None,
        *,
        use_cache: bool = True,
        use_disk_cache: bool = False,
        cache_dir: str | None = None,
        validate: bool = False,
        discover_plugins: bool = True,
        http2: bool = True,
    ) -> None:
        self._source_names = sources or _DEFAULT_SOURCES
        self._validate_default = validate
        self._http2 = http2
        self._discover_plugins = discover_plugins
        self._cache = CacheManager(use_disk=use_disk_cache, cache_dir=cache_dir) if use_cache else None
        self._validator = DataValidator()
        self._consensus = MedianConsensus()
        self._http_client: httpx.AsyncClient | None = None
        self._router: DataSourceRouter | None = None

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> "AsyncClient":
        await self._ensure_open()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
            self._router = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def prices(
        self,
        symbol: str | Sequence[str],
        *,
        period: str | None = "1mo",
        start: str | date | None = None,
        end: str | date | None = None,
        interval: str = "1d",
        validate: bool | None = None,
    ) -> DataResult | dict[str, DataResult]:
        """Fetch OHLCV price history.

        Parameters
        ----------
        symbol:
            Single ticker or list of tickers.
        period:
            Convenience string: '1d','5d','1mo','3mo','6mo','1y','2y','5y','10y','ytd','max'.
            Ignored when *start* is provided.
        start / end:
            Date range (ISO strings or date objects).
        interval:
            Bar interval: '1d', '1wk', '1mo', '1h', etc.
        validate:
            Override the client-level validate default.

        Returns
        -------
        DataResult for a single symbol; dict[symbol, DataResult] for multiple.
        """
        do_validate = validate if validate is not None else self._validate_default
        symbols = [symbol] if isinstance(symbol, str) else list(symbol)

        tasks = [
            self._fetch_prices_single(s, period=period, start=start, end=end,
                                      interval=interval, validate=do_validate)
            for s in symbols
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        if isinstance(symbol, str):
            result = results[0]
            if isinstance(result, BaseException):
                raise result
            return result  # type: ignore[return-value]

        out: dict[str, DataResult] = {}
        for sym, res in zip(symbols, results):
            if isinstance(res, BaseException):
                logger.error("Failed to fetch %s: %s", sym, res)
            else:
                out[sym] = res  # type: ignore[assignment]
        return out

    async def info(self, symbol: str) -> Any:
        """Fetch descriptive asset information."""
        await self._ensure_open()
        assert self._router is not None

        # Check cache
        if self._cache:
            cached = self._cache.get_info(symbol)
            if cached is not None:
                return cached

        info_obj, source_name = await self._router.fetch_info(symbol)

        if self._cache:
            self._cache.set_info(symbol, info_obj)

        return info_obj

    async def forex(
        self,
        pair: str,
        *,
        period: str | None = "1y",
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> DataResult:
        """Fetch forex rate history for a currency pair like 'USD/EUR'."""
        # Route through prices; ECB source handles forex symbols
        return await self.prices(pair, period=period, start=start, end=end, interval="1d")

    async def health(self) -> dict[str, bool]:
        """Probe all configured sources and return their health status."""
        await self._ensure_open()
        assert self._router is not None
        return await self._router.health_status()

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _ensure_open(self) -> None:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(http2=self._http2, follow_redirects=True)
            self._router = DataSourceRouter.from_names(
                self._source_names,
                http_client=self._http_client,
                discover_plugins=self._discover_plugins,
            )

    async def _fetch_prices_single(
        self,
        symbol: str,
        *,
        period: str | None,
        start: str | date | None,
        end: str | date | None,
        interval: str,
        validate: bool,
    ) -> DataResult:
        await self._ensure_open()
        assert self._router is not None

        # Normalise dates
        start_date = _parse_date(start) if start else None
        end_date = _parse_date(end) if end else None

        # Cache lookup
        cache_start = start_date
        cache_end = end_date
        if period and not start_date:
            cache_start, cache_end = period_to_dates(period)

        if self._cache:
            cached = self._cache.get_prices(symbol, interval, cache_start, cache_end)
            if cached is not None:
                return DataResult(
                    cached,
                    symbol=symbol,
                    sources=[SourceContribution(source="cache", rows=len(cached), from_cache=True)],
                    validated=validate,
                )

        params = PricesParams(
            symbol=symbol,
            period=period if not start_date else None,
            start=start_date,
            end=end_date,
            interval=interval,
        )

        df, source_name = await self._router.fetch_prices(params)

        warnings: list[str] = []
        if validate:
            validator = DataValidator(source=source_name)
            warnings = validator.validate_prices(df, symbol=symbol)

        if self._cache:
            self._cache.set_prices(symbol, interval, cache_start, cache_end, df)

        contribution = SourceContribution(source=source_name, rows=len(df))
        return DataResult(
            df,
            symbol=symbol,
            sources=[contribution],
            validated=validate,
            warnings=warnings,
        )


def _parse_date(d: str | date) -> date:
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d))
