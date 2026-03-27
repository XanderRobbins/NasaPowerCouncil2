"""Client — synchronous wrapper around AsyncClient.

Uses asyncio.run() (or an existing event loop when inside Jupyter/IPython)
to bridge the async internals into a blocking API.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Sequence

from findata.client.async_client import AsyncClient
from findata.models.result import DataResult


def _run(coro: Any) -> Any:
    """Run a coroutine, handling the case where a loop is already running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # Inside Jupyter / asyncio REPL — schedule on the running loop
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


class Client:
    """Synchronous financial data client with multi-source failover.

    This is a thin blocking wrapper around ``AsyncClient``.  All parameters
    are forwarded verbatim; see ``AsyncClient`` for full documentation.

    Example
    -------
    >>> import findata
    >>> df = findata.prices("AAPL", period="1mo")

    >>> client = findata.Client(sources=["yahoo", "sec"])
    >>> df = client.prices("AAPL", start="2024-01-01", validate=True)
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
        self._async = AsyncClient(
            sources,
            use_cache=use_cache,
            use_disk_cache=use_disk_cache,
            cache_dir=cache_dir,
            validate=validate,
            discover_plugins=discover_plugins,
            http2=http2,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def prices(
        self,
        symbol: str | Sequence[str],
        *,
        period: str | None = "1mo",
        start: str | date | None = None,
        end: str | date | None = None,
        interval: str = "1d",
        validate: bool | None = None,
    ) -> DataResult | dict[str, DataResult]:
        """Fetch OHLCV price history (blocking).

        See ``AsyncClient.prices`` for full parameter documentation.
        """
        return _run(
            self._async.prices(
                symbol,
                period=period,
                start=start,
                end=end,
                interval=interval,
                validate=validate,
            )
        )

    def info(self, symbol: str) -> Any:
        """Fetch descriptive asset information (blocking)."""
        return _run(self._async.info(symbol))

    def forex(
        self,
        pair: str,
        *,
        period: str | None = "1y",
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> DataResult:
        """Fetch forex rate history (blocking)."""
        return _run(self._async.forex(pair, period=period, start=start, end=end))

    def health(self) -> dict[str, bool]:
        """Check health of all configured sources (blocking)."""
        return _run(self._async.health())

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        _run(self._async.close())

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
