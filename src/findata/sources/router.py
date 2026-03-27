"""DataSourceRouter — priority-ordered failover with circuit breakers.

The router maintains an ordered list of DataSource adapters.  Each source is
wrapped in a pybreaker CircuitBreaker.  On each request the router tries
sources in order, skipping any whose circuit is open, and returns the first
successful result.  If all sources fail, AllSourcesFailedError is raised.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
from typing import Any

import httpx
import pybreaker

from findata.exceptions import AllSourcesFailedError, SourceUnavailableError
from findata.models.source import SupportedDataType
from findata.sources.base import DataSource, PricesParams

logger = logging.getLogger(__name__)

_FAIL_MAX = 5          # trips open after 5 consecutive failures
_RESET_TIMEOUT = 60    # seconds before half-open probe


def _make_breaker(source_name: str) -> pybreaker.CircuitBreaker:
    return pybreaker.CircuitBreaker(
        fail_max=_FAIL_MAX,
        reset_timeout=_RESET_TIMEOUT,
        name=f"findata.{source_name}",
        listeners=[_BreakListener(source_name)],
    )


class _BreakListener(pybreaker.CircuitBreakerListener):
    def __init__(self, name: str) -> None:
        self._name = name

    def state_change(self, cb: pybreaker.CircuitBreaker, old_state: Any, new_state: Any) -> None:
        logger.warning(
            "Circuit breaker [%s]: %s → %s",
            self._name,
            old_state.name,
            new_state.name,
        )


class DataSourceRouter:
    """Routes requests across an ordered list of DataSource adapters with failover.

    Sources are tried in priority order (index 0 = highest priority).
    Circuit breakers automatically skip failing sources and re-probe them after
    ``reset_timeout`` seconds.

    Community plugins registered under the ``findata.sources`` entry-point
    group are discovered and appended after the built-in sources.
    """

    def __init__(self, sources: list[DataSource], *, http_client: httpx.AsyncClient) -> None:
        self._sources = sources
        self._client = http_client
        self._breakers: dict[str, pybreaker.CircuitBreaker] = {
            s.meta.name: _make_breaker(s.meta.name) for s in sources
        }

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_names(
        cls,
        names: list[str],
        *,
        http_client: httpx.AsyncClient,
        discover_plugins: bool = True,
    ) -> "DataSourceRouter":
        """Build a router from a list of source names (e.g. ['yahoo', 'sec']).

        Parameters
        ----------
        names:
            Ordered list of source names to enable.  If empty, all built-in
            sources are used.
        discover_plugins:
            Whether to discover and append community plugins.
        """
        registry = _build_registry(discover_plugins=discover_plugins)
        ordered: list[DataSource] = []
        missing = []
        for name in names:
            if name in registry:
                ordered.append(registry[name])
            else:
                missing.append(name)
        if missing:
            logger.warning("Unknown sources (will be ignored): %s", missing)
        if not ordered:
            ordered = list(registry.values())
        return cls(ordered, http_client=http_client)

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_prices(self, params: PricesParams) -> tuple[Any, str]:
        """Return ``(DataFrame, source_name)`` from the first healthy source."""
        return await self._try_sources(
            SupportedDataType.PRICES,
            params.symbol,
            "fetch_prices",
            params,
        )

    async def fetch_info(self, symbol: str) -> tuple[Any, str]:
        """Return ``(AssetInfo, source_name)`` from the first healthy source."""
        return await self._try_sources(
            SupportedDataType.INFO,
            symbol,
            "fetch_info",
            symbol,
        )

    async def health_status(self) -> dict[str, bool]:
        """Probe all sources concurrently and return their health state."""
        tasks = {
            s.meta.name: asyncio.create_task(
                self._safe_health(s)
            )
            for s in self._sources
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        return dict(zip(tasks.keys(), [r if isinstance(r, bool) else False for r in results]))

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _try_sources(
        self,
        data_type: SupportedDataType,
        symbol: str,
        method: str,
        *args: Any,
    ) -> tuple[Any, str]:
        errors: dict[str, Exception] = {}

        for source in self._sources:
            if not source.supports(data_type, symbol):
                continue
            breaker = self._breakers[source.meta.name]
            if breaker.current_state == "open":
                logger.debug("Skipping %s (circuit open)", source.meta.name)
                errors[source.meta.name] = SourceUnavailableError(
                    source.meta.name, "Circuit breaker open"
                )
                continue

            try:
                fn = getattr(source, method)
                result = await breaker.call_async(fn, *args, client=self._client)
                return result, source.meta.name
            except pybreaker.CircuitBreakerError as exc:
                errors[source.meta.name] = exc
                logger.debug("Circuit breaker rejected call to %s", source.meta.name)
            except Exception as exc:
                errors[source.meta.name] = exc
                logger.warning("Source %s failed for %s: %s", source.meta.name, symbol, exc)

        raise AllSourcesFailedError(symbol, errors)

    async def _safe_health(self, source: DataSource) -> bool:
        try:
            return await source.health_check(client=self._client)
        except Exception:
            return False


# ── Plugin discovery ──────────────────────────────────────────────────────────


def _build_registry(*, discover_plugins: bool) -> dict[str, DataSource]:
    """Build an ordered dict of all available sources.

    Built-in sources come first in their natural order; plugins are appended.
    """
    from findata.sources.binance import BinanceSource
    from findata.sources.coingecko import CoinGeckoSource
    from findata.sources.ecb import ECBSource
    from findata.sources.sec import SECSource
    from findata.sources.yahoo import YahooSource

    registry: dict[str, DataSource] = {}
    for cls in [YahooSource, SECSource, ECBSource, BinanceSource, CoinGeckoSource]:
        instance = cls()
        registry[instance.meta.name] = instance  # type: ignore[arg-type]

    if discover_plugins:
        try:
            eps = importlib.metadata.entry_points(group="findata.sources")
        except Exception:
            eps = []

        for ep in eps:
            if ep.name in registry:
                continue  # built-in wins
            try:
                plugin_cls = ep.load()
                instance = plugin_cls()
                registry[instance.meta.name] = instance  # type: ignore[arg-type]
                logger.info("Loaded plugin source: %s", ep.name)
            except Exception as exc:
                logger.warning("Failed to load plugin source %r: %s", ep.name, exc)

    return registry
