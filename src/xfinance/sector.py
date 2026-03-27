"""Sector and Industry — browse Yahoo Finance sector/industry market data.

Analogous to yfinance.Sector and yfinance.Industry.

Usage
-----
>>> import xfinance as xf
>>> tech = xf.Sector("technology")
>>> tech.overview           # dict with sector stats
>>> tech.top_companies      # DataFrame of top companies by market cap
>>> tech.industries         # list of industry names in this sector

>>> ai = xf.Industry("semiconductors")
>>> ai.top_companies        # DataFrame
>>> ai.sector               # parent sector name
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any

import httpx
import pandas as pd

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

# Yahoo Finance sector key mapping (user-friendly → Yahoo key)
_SECTOR_KEYS: dict[str, str] = {
    "technology": "technology",
    "healthcare": "healthcare",
    "financial-services": "financial-services",
    "consumer-cyclical": "consumer-cyclical",
    "consumer-defensive": "consumer-defensive",
    "energy": "energy",
    "industrials": "industrials",
    "utilities": "utilities",
    "real-estate": "real-estate",
    "basic-materials": "basic-materials",
    "communication-services": "communication-services",
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


async def _get_screener(
    client: httpx.AsyncClient,
    query_type: str,
    offset: int = 0,
    count: int = 25,
) -> dict[str, Any]:
    """Call Yahoo Finance screener API."""
    url = f"{_BASE}/v1/finance/screener/predefined/saved"
    params = {
        "scrIds": query_type,
        "offset": offset,
        "count": count,
    }
    try:
        resp = await client.get(url, params=params, headers=_HEADERS, timeout=15)
        if resp.status_code == 200:
            return resp.json()  # type: ignore[return-value]
    except Exception as exc:
        logger.warning("Screener request failed: %s", exc)
    return {}


async def _get_sector_data(key: str) -> dict[str, Any]:
    """Fetch sector overview from Yahoo Finance sector API."""
    async with httpx.AsyncClient(http2=True, follow_redirects=True) as client:
        url = f"{_BASE}/v1/finance/sectors"
        try:
            resp = await client.get(url, headers=_HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                sectors = data.get("sectorPerformance", {}).get("sectors", [])
                for s in sectors:
                    if s.get("sectorKey", "").lower() == key.lower():
                        return s
        except Exception as exc:
            logger.warning("Sector data fetch failed: %s", exc)
    return {}


async def _search_quotes(query: str, count: int) -> list[dict[str, Any]]:
    """Use search API to find top companies for a sector/industry."""
    async with httpx.AsyncClient(http2=True, follow_redirects=True) as client:
        params = {
            "q": query,
            "quotesCount": count,
            "newsCount": 0,
            "enableFuzzyQuery": "false",
        }
        try:
            resp = await client.get(
                f"{_BASE}/v1/finance/search",
                params=params,
                headers=_HEADERS,
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json().get("quotes", [])  # type: ignore[return-value]
        except Exception as exc:
            logger.warning("Search failed for %r: %s", query, exc)
    return []


def _quotes_to_df(quotes: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for q in quotes:
        rows.append({
            "Symbol": q.get("symbol", ""),
            "Name": q.get("longname") or q.get("shortname", ""),
            "Exchange": q.get("exchange", ""),
            "Type": q.get("quoteType", ""),
            "Score": q.get("score"),
        })
    return pd.DataFrame(rows)


class Sector:
    """Access Yahoo Finance sector-level market data.

    Parameters
    ----------
    key:
        Sector name or Yahoo Finance sector key. Accepted values (case-insensitive):
        ``'technology'``, ``'healthcare'``, ``'financial-services'``,
        ``'consumer-cyclical'``, ``'consumer-defensive'``, ``'energy'``,
        ``'industrials'``, ``'utilities'``, ``'real-estate'``,
        ``'basic-materials'``, ``'communication-services'``.

    Examples
    --------
    >>> s = xf.Sector("technology")
    >>> s.overview
    >>> s.top_companies
    >>> s.industries
    """

    def __init__(self, key: str) -> None:
        # Normalize: strip spaces, lowercase, replace spaces with dashes
        self._key = key.strip().lower().replace(" ", "-")
        self._data: dict[str, Any] | None = None

    def _get_data(self) -> dict[str, Any]:
        if self._data is None:
            self._data = _run(_get_sector_data(self._key))
        return self._data

    @property
    def key(self) -> str:
        return self._key

    @property
    def overview(self) -> dict[str, Any]:
        """Sector performance overview dict with changesPercentage, dayHigh, etc."""
        return self._get_data()

    @property
    def name(self) -> str:
        """Human-readable sector name."""
        return self._get_data().get("sector", self._key.replace("-", " ").title())

    @property
    def top_companies(self) -> pd.DataFrame:
        """Top companies in this sector by search relevance / market cap."""
        quotes = _run(_search_quotes(self._key.replace("-", " "), count=25))
        return _quotes_to_df(quotes)

    @property
    def industries(self) -> list[str]:
        """List of industry sub-groups within this sector (from sector data)."""
        industries = self._get_data().get("industries", [])
        if isinstance(industries, list):
            return [i.get("industry", "") for i in industries if i.get("industry")]
        return []

    @property
    def ticker(self) -> str | None:
        """Sector ETF or index ticker if available (e.g. 'XLK' for technology)."""
        return self._get_data().get("ticker")

    def __repr__(self) -> str:
        return f"xfinance.Sector(key={self._key!r})"


class Industry:
    """Access Yahoo Finance industry-level market data.

    Parameters
    ----------
    key:
        Industry name (e.g. ``'semiconductors'``, ``'software-infrastructure'``,
        ``'consumer-electronics'``).

    Examples
    --------
    >>> ind = xf.Industry("semiconductors")
    >>> ind.top_companies
    >>> ind.sector
    """

    _INDUSTRY_TO_SECTOR: dict[str, str] = {
        "semiconductors": "technology",
        "software-infrastructure": "technology",
        "software-application": "technology",
        "consumer-electronics": "technology",
        "electronic-components": "technology",
        "information-technology-services": "technology",
        "internet-content-information": "communication-services",
        "entertainment": "communication-services",
        "telecom-services": "communication-services",
        "biotechnology": "healthcare",
        "drug-manufacturers-general": "healthcare",
        "medical-devices": "healthcare",
        "diagnostics-research": "healthcare",
        "banks-diversified": "financial-services",
        "asset-management": "financial-services",
        "insurance-diversified": "financial-services",
        "credit-services": "financial-services",
        "auto-manufacturers": "consumer-cyclical",
        "restaurants": "consumer-cyclical",
        "specialty-retail": "consumer-cyclical",
        "household-personal-products": "consumer-defensive",
        "beverages-non-alcoholic": "consumer-defensive",
        "tobacco": "consumer-defensive",
        "oil-gas-integrated": "energy",
        "oil-gas-e-p": "energy",
        "oil-gas-midstream": "energy",
        "aerospace-defense": "industrials",
        "industrial-conglomerates": "industrials",
        "trucking": "industrials",
        "utilities-regulated-electric": "utilities",
        "utilities-diversified": "utilities",
        "reit-residential": "real-estate",
        "reit-retail": "real-estate",
        "steel": "basic-materials",
        "chemicals": "basic-materials",
        "gold": "basic-materials",
    }

    def __init__(self, key: str) -> None:
        self._key = key.strip().lower().replace(" ", "-")

    @property
    def key(self) -> str:
        return self._key

    @property
    def name(self) -> str:
        return self._key.replace("-", " ").title()

    @property
    def sector(self) -> str:
        """Parent sector name for this industry."""
        return self._INDUSTRY_TO_SECTOR.get(self._key, "unknown")

    @property
    def top_companies(self) -> pd.DataFrame:
        """Top companies in this industry by search relevance."""
        quotes = _run(_search_quotes(self._key.replace("-", " "), count=25))
        return _quotes_to_df(quotes)

    def __repr__(self) -> str:
        return f"xfinance.Industry(key={self._key!r})"
