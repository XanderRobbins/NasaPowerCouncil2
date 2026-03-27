"""Search — query Yahoo Finance for symbols, news, and more.

Analogous to yfinance.Search.

Usage
-----
>>> import xfinance as xf
>>> s = xf.Search("Apple")
>>> s.quotes           # list of matching ticker dicts
>>> s.news             # list of recent news articles
>>> s.all              # combined results dict
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://query1.finance.yahoo.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://finance.yahoo.com/",
}


def _run(coro: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


class Search:
    """Search Yahoo Finance for symbols, funds, news articles, and more.

    Parameters
    ----------
    query:
        Free-text search query (e.g. ``'Apple'``, ``'AAPL'``, ``'S&P 500'``).
    max_results:
        Maximum number of quote results to return (default 8).
    news_count:
        Maximum number of news articles to return (default 8).
    enable_fuzzy_query:
        Allow fuzzy matching for typos (default True).
    session:
        Optional pre-configured ``httpx.AsyncClient``.

    Examples
    --------
    >>> s = xf.Search("Apple Inc")
    >>> s.quotes[0]["symbol"]   # → 'AAPL'
    >>> s.news[0]["title"]
    """

    def __init__(
        self,
        query: str,
        max_results: int = 8,
        news_count: int = 8,
        enable_fuzzy_query: bool = True,
        session: httpx.AsyncClient | None = None,
    ) -> None:
        self._query = query
        self._max_results = max_results
        self._news_count = news_count
        self._enable_fuzzy_query = enable_fuzzy_query
        self._session = session
        self._data: dict[str, Any] | None = None

    def _fetch(self) -> dict[str, Any]:
        if self._data is not None:
            return self._data
        self._data = _run(self._fetch_async())
        return self._data

    async def _fetch_async(self) -> dict[str, Any]:
        params = {
            "q": self._query,
            "quotesCount": self._max_results,
            "newsCount": self._news_count,
            "enableFuzzyQuery": str(self._enable_fuzzy_query).lower(),
            "enableCb": "true",
            "enableNavLinks": "true",
            "enableEnhancedTrivialQuery": "true",
        }
        close_client = False
        client = self._session
        if client is None:
            client = httpx.AsyncClient(http2=True, follow_redirects=True)
            close_client = True

        try:
            resp = await client.get(
                f"{_BASE}/v1/finance/search",
                params=params,
                headers=_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[return-value]
        except Exception as exc:
            logger.warning("Search failed for %r: %s", self._query, exc)
            return {}
        finally:
            if close_client:
                await client.aclose()

    # ── Public properties ──────────────────────────────────────────────────────

    @property
    def quotes(self) -> list[dict[str, Any]]:
        """List of matching ticker dicts with symbol, shortname, exchange, quoteType."""
        return self._fetch().get("quotes", [])  # type: ignore[return-value]

    @property
    def news(self) -> list[dict[str, Any]]:
        """List of recent news articles related to the query."""
        return self._fetch().get("news", [])  # type: ignore[return-value]

    @property
    def lists(self) -> list[dict[str, Any]]:
        """Yahoo Finance curated lists matching the query (e.g. 'Most Active')."""
        return self._fetch().get("lists", [])  # type: ignore[return-value]

    @property
    def nav(self) -> list[dict[str, Any]]:
        """Navigation links returned by Yahoo (sector pages, screeners, etc.)."""
        return self._fetch().get("nav", [])  # type: ignore[return-value]

    @property
    def all(self) -> dict[str, Any]:
        """Raw combined search response dict."""
        return self._fetch()

    def __repr__(self) -> str:
        return f"xfinance.Search(query={self._query!r}, results={len(self.quotes)})"
