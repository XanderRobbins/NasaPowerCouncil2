"""DataSourceRouter with circuit-breaker failover."""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
from typing import Any

import httpx
import pybreaker

from xfinance.exceptions import AllSourcesFailedError, SourceUnavailableError
from xfinance.models.source import SupportedDataType
from xfinance.sources.base import DataSource, PricesParams

logger = logging.getLogger(__name__)
_FAIL_MAX = 5
_RESET_TIMEOUT = 60


def _make_breaker(name: str) -> pybreaker.CircuitBreaker:
    return pybreaker.CircuitBreaker(
        fail_max=_FAIL_MAX,
        reset_timeout=_RESET_TIMEOUT,
        name=f"xfinance.{name}",
        listeners=[_BreakListener(name)],
    )


class _BreakListener(pybreaker.CircuitBreakerListener):
    def __init__(self, name: str) -> None:
        self._name = name

    def state_change(self, cb: Any, old: Any, new: Any) -> None:
        logger.warning("Circuit breaker [%s]: %s → %s", self._name, old.name, new.name)


class DataSourceRouter:
    def __init__(self, sources: list[DataSource], *, http_client: httpx.AsyncClient) -> None:
        self._sources = sources
        self._client = http_client
        self._breakers = {s.meta.name: _make_breaker(s.meta.name) for s in sources}

    @classmethod
    def from_names(
        cls, names: list[str], *, http_client: httpx.AsyncClient, discover_plugins: bool = True
    ) -> "DataSourceRouter":
        registry = _build_registry(discover_plugins=discover_plugins)
        ordered = [registry[n] for n in names if n in registry]
        if not ordered:
            ordered = list(registry.values())
        return cls(ordered, http_client=http_client)

    async def fetch_prices(self, params: PricesParams) -> tuple[Any, str]:
        return await self._try(SupportedDataType.PRICES, params.symbol, "fetch_prices", params)

    async def fetch_info(self, symbol: str) -> tuple[Any, str]:
        return await self._try(SupportedDataType.INFO, symbol, "fetch_info", symbol)

    async def health_status(self) -> dict[str, bool]:
        results = await asyncio.gather(
            *[self._safe_health(s) for s in self._sources], return_exceptions=True
        )
        return {s.meta.name: r if isinstance(r, bool) else False
                for s, r in zip(self._sources, results)}

    async def _try(self, data_type: SupportedDataType, symbol: str, method: str, *args: Any) -> tuple[Any, str]:
        errors: dict[str, Exception] = {}
        for source in self._sources:
            if not source.supports(data_type, symbol):
                continue
            breaker = self._breakers[source.meta.name]
            if breaker.current_state == "open":
                errors[source.meta.name] = SourceUnavailableError(source.meta.name, "Circuit open")
                continue
            try:
                fn = getattr(source, method)
                result = await breaker.call_async(fn, *args, client=self._client)
                return result, source.meta.name
            except pybreaker.CircuitBreakerError as exc:
                errors[source.meta.name] = exc
            except Exception as exc:
                errors[source.meta.name] = exc
                logger.warning("Source %s failed for %s: %s", source.meta.name, symbol, exc)
        raise AllSourcesFailedError(symbol, errors)

    async def _safe_health(self, source: DataSource) -> bool:
        try:
            return await source.health_check(client=self._client)
        except Exception:
            return False


def _build_registry(*, discover_plugins: bool) -> dict[str, DataSource]:
    from xfinance.sources.binance import BinanceSource
    from xfinance.sources.coingecko import CoinGeckoSource
    from xfinance.sources.ecb import ECBSource
    from xfinance.sources.sec import SECSource
    from xfinance.sources.stooq import StooqSource
    from xfinance.sources.yahoo import YahooSource

    # Priority order: Yahoo first, Stooq as equity fallback, then SEC/ECB/crypto
    registry: dict[str, DataSource] = {}
    for cls in [YahooSource, StooqSource, SECSource, ECBSource, BinanceSource, CoinGeckoSource]:
        inst = cls()
        registry[inst.meta.name] = inst  # type: ignore[arg-type]

    if discover_plugins:
        try:
            eps = importlib.metadata.entry_points(group="xfinance.sources")
        except Exception:
            eps = []
        for ep in eps:
            if ep.name in registry:
                continue
            try:
                inst = ep.load()()
                registry[inst.meta.name] = inst  # type: ignore[arg-type]
            except Exception as exc:
                logger.warning("Failed to load plugin %r: %s", ep.name, exc)

    return registry
