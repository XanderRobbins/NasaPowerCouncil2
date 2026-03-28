"""Screener — programmatic stock/fund screener.

Analogous to yfinance.Screener, yfinance.EquityQuery, yfinance.FundQuery.

Usage
-----
>>> import xfinance as xf

# Build a query and run the screener
>>> q = xf.EquityQuery("and", [
...     xf.EquityQuery("gte", ["marketcap", 1_000_000_000]),
...     xf.EquityQuery("eq",  ["region", "us"]),
...     xf.EquityQuery("lte", ["peratio.lasttwelvemonths", 25]),
... ])
>>> s = xf.Screener(query=q, sort_by="marketcap", count=25)
>>> s.results          # list[dict] of matching quotes
>>> s.to_dataframe()   # pandas DataFrame

# Predefined Yahoo screener IDs (no query required)
>>> s = xf.Screener(screen_id="most_actives", count=50)
>>> s.results

# Fund screener
>>> fq = xf.FundQuery("and", [
...     xf.FundQuery("gte", ["annualreturnnavy1categoryrank", 50]),
... ])
>>> fs = xf.Screener(query=fq, sort_by="fundnetassets", count=20)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

_BASE = "https://query2.finance.yahoo.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Content-Type": "application/json",
    "Referer": "https://finance.yahoo.com/",
}

# Well-known predefined Yahoo screener IDs
PREDEFINED_SCREENS: tuple[str, ...] = (
    "most_actives",
    "day_gainers",
    "day_losers",
    "undervalued_growth_stocks",
    "growth_technology_stocks",
    "aggressive_small_caps",
    "small_cap_gainers",
    "undervalued_large_caps",
    "conservative_foreign_funds",
    "high_yield_bond",
    "top_mutual_funds",
    "portfolio_anchors",
    "solid_large_growth_funds",
    "solid_midcap_growth_funds",
    "ms_basic_materials",
    "ms_communication_services",
    "ms_consumer_cyclical",
    "ms_consumer_defensive",
    "ms_energy",
    "ms_financial_services",
    "ms_healthcare",
    "ms_industrials",
    "ms_real_estate",
    "ms_technology",
    "ms_utilities",
)


def _run(coro: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


# ── Query classes ─────────────────────────────────────────────────────────────


class EquityQuery:
    """Build a Yahoo Finance equity screener query node.

    Parameters
    ----------
    operator:
        Comparison or logical operator.  Logical: ``'and'``, ``'or'``.
        Comparison: ``'eq'``, ``'neq'``, ``'gt'``, ``'gte'``, ``'lt'``, ``'lte'``,
        ``'btwn'`` (between, requires 3 operands: field, lo, hi).
    operands:
        For logical operators — list of child ``EquityQuery`` objects.
        For comparison operators — ``[field_name, value]`` or
        ``[field_name, lo, hi]`` for ``btwn``.

    Common field names
    ------------------
    ``marketcap``, ``peratio.lasttwelvemonths``, ``forwardpe``,
    ``epsgrowth.lasttwelvemonths``, ``revenue.lasttwelvemonths``,
    ``region`` (e.g. ``'us'``), ``exchange`` (e.g. ``'NMS'``),
    ``sector`` (e.g. ``'Technology'``), ``industry``,
    ``avgdailyvol3m``, ``percentchange``, ``dayvolume``,
    ``beta``, ``50dayma``, ``200dayma``.

    Examples
    --------
    >>> q = EquityQuery("and", [
    ...     EquityQuery("gte", ["marketcap", 10_000_000_000]),
    ...     EquityQuery("eq",  ["region", "us"]),
    ...     EquityQuery("lt",  ["peratio.lasttwelvemonths", 20]),
    ... ])
    """

    def __init__(self, operator: str, operands: list[Any]) -> None:
        self._operator = operator.lower()
        self._operands = operands

    def to_dict(self) -> dict[str, Any]:
        """Convert to Yahoo Finance screener query dict."""
        ops = []
        for o in self._operands:
            if isinstance(o, (EquityQuery, FundQuery)):
                ops.append(o.to_dict())
            else:
                ops.append(o)
        return {"operator": self._operator, "operands": ops}

    def __repr__(self) -> str:
        return f"EquityQuery({self._operator!r}, {self._operands!r})"


class FundQuery(EquityQuery):
    """Build a Yahoo Finance fund screener query node.

    Identical API to :class:`EquityQuery` but signals to :class:`Screener`
    that ``quoteType='MUTUALFUND'`` should be used.

    Common field names
    ------------------
    ``fundnetassets``, ``annualreturnnavy1categoryrank``,
    ``categoryname``, ``morningstarrating``, ``expenseratiocat``.
    """


# ── Screener class ────────────────────────────────────────────────────────────


class Screener:
    """Execute a Yahoo Finance screener and return matching quotes.

    Parameters
    ----------
    query:
        An :class:`EquityQuery` or :class:`FundQuery` tree, **or** ``None``
        when using a predefined ``screen_id``.
    screen_id:
        One of the predefined screener IDs (e.g. ``'most_actives'``,
        ``'day_gainers'``).  Used when *query* is ``None``.
    sort_by:
        Field name to sort results by (default ``'marketcap'``).
    sort_asc:
        Sort ascending when True, descending when False (default False).
    count:
        Maximum number of results (default 25, max ~250 per request).
    offset:
        Result page offset (default 0).

    Examples
    --------
    >>> s = xf.Screener(screen_id="most_actives", count=50)
    >>> df = s.to_dataframe()
    >>> df[["symbol", "shortName", "regularMarketPrice", "regularMarketVolume"]]
    """

    def __init__(
        self,
        query: EquityQuery | FundQuery | None = None,
        screen_id: str | None = None,
        *,
        sort_by: str = "marketcap",
        sort_asc: bool = False,
        count: int = 25,
        offset: int = 0,
    ) -> None:
        if query is None and screen_id is None:
            raise ValueError("Provide either 'query' or 'screen_id'.")
        self._query = query
        self._screen_id = screen_id
        self._sort_by = sort_by
        self._sort_asc = sort_asc
        self._count = count
        self._offset = offset
        self._data: list[dict[str, Any]] | None = None

    def _fetch(self) -> list[dict[str, Any]]:
        if self._data is None:
            self._data = _run(self._fetch_async())
        return self._data

    async def _fetch_async(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(http2=True, follow_redirects=True) as client:
            if self._screen_id:
                return await self._fetch_predefined(client)
            return await self._fetch_custom(client)

    async def _fetch_predefined(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """Fetch a Yahoo predefined screener by its ID."""
        params = {
            "scrIds": self._screen_id,
            "offset": self._offset,
            "count": self._count,
            "sortField": self._sort_by,
            "sortType": "asc" if self._sort_asc else "desc",
            "lang": "en-US",
            "region": "US",
        }
        try:
            resp = await client.get(
                "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved",
                params=params,
                headers=_HEADERS,
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                body = (data.get("finance") or {}).get("result") or []
                if body:
                    return body[0].get("quotes", [])  # type: ignore[return-value]
        except Exception as exc:
            logger.warning("Screener (predefined) error: %s", exc)
        return []

    async def _fetch_custom(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """POST a custom query to the Yahoo screener API."""
        quote_type = "MUTUALFUND" if isinstance(self._query, FundQuery) else "EQUITY"
        payload: dict[str, Any] = {
            "offset": self._offset,
            "size": self._count,
            "sortField": self._sort_by,
            "sortType": "asc" if self._sort_asc else "desc",
            "quoteType": quote_type,
            "topOperator": "AND",
            "query": self._query.to_dict() if self._query else {"operator": "AND", "operands": []},
            "userId": "",
            "userIdType": "guid",
        }
        try:
            resp = await client.post(
                f"{_BASE}/v1/finance/screener",
                params={"lang": "en-US", "region": "US"},
                json=payload,
                headers=_HEADERS,
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                body = (data.get("finance") or {}).get("result") or []
                if body:
                    return body[0].get("quotes", [])  # type: ignore[return-value]
        except Exception as exc:
            logger.warning("Screener (custom) error: %s", exc)
        return []

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def results(self) -> list[dict[str, Any]]:
        """List of quote dicts for matching symbols."""
        return self._fetch()

    def to_dataframe(self) -> pd.DataFrame:
        """Return screener results as a DataFrame.

        Columns include: ``symbol``, ``shortName``, ``quoteType``, ``exchange``,
        ``regularMarketPrice``, ``regularMarketChangePercent``,
        ``regularMarketVolume``, ``marketCap``, ``trailingPE``, etc.
        """
        rows = self._fetch()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    def __len__(self) -> int:
        return len(self.results)

    def __repr__(self) -> str:
        sid = self._screen_id or "custom"
        return f"xfinance.Screener(screen_id={sid!r}, count={self._count})"


def screen(screen_id: str, *, count: int = 25, **kwargs: Any) -> list[dict[str, Any]]:
    """Shorthand for ``Screener(screen_id=screen_id, count=count).results``.

    Parameters
    ----------
    screen_id:
        Predefined Yahoo screener ID, e.g. ``"most_actives"``,
        ``"day_gainers"``, ``"day_losers"``, ``"undervalued_growth_stocks"``.
    count:
        Maximum number of results to return (default 25).
    **kwargs:
        Additional keyword arguments forwarded to :class:`Screener`.

    Examples
    --------
    >>> xf.screen("most_actives")
    >>> xf.screen("day_gainers", count=50)
    """
    return Screener(screen_id=screen_id, count=count, **kwargs).results
