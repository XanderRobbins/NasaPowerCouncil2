"""Market — market hours, status, and summary data.

Analogous to yfinance.Market.

Usage
-----
>>> import xfinance as xf
>>> m = xf.Market("us_market")
>>> m.status           # "pre" | "regular" | "post" | "closed"
>>> m.summary          # dict of index prices and market stats
>>> m.open_time        # datetime of next/current open
>>> m.close_time       # datetime of next/current close
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from datetime import datetime, timezone
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

# Map user-friendly market IDs to Yahoo region/exchange info and a
# representative index symbol used to probe market state.
_MARKET_META: dict[str, dict[str, str]] = {
    "us_market":   {"region": "US",  "lang": "en-US",  "probe": "^GSPC", "tz": "America/New_York"},
    "gb_market":   {"region": "GB",  "lang": "en-GB",  "probe": "^FTSE", "tz": "Europe/London"},
    "de_market":   {"region": "DE",  "lang": "de-DE",  "probe": "^GDAXI", "tz": "Europe/Berlin"},
    "fr_market":   {"region": "FR",  "lang": "fr-FR",  "probe": "^FCHI",  "tz": "Europe/Paris"},
    "jp_market":   {"region": "JP",  "lang": "ja-JP",  "probe": "^N225",  "tz": "Asia/Tokyo"},
    "cn_market":   {"region": "CN",  "lang": "zh-CN",  "probe": "000001.SS", "tz": "Asia/Shanghai"},
    "hk_market":   {"region": "HK",  "lang": "zh-HK",  "probe": "^HSI",  "tz": "Asia/Hong_Kong"},
    "au_market":   {"region": "AU",  "lang": "en-AU",  "probe": "^AXJO", "tz": "Australia/Sydney"},
    "ca_market":   {"region": "CA",  "lang": "en-CA",  "probe": "^GSPTSE", "tz": "America/Toronto"},
    "in_market":   {"region": "IN",  "lang": "en-IN",  "probe": "^BSESN", "tz": "Asia/Kolkata"},
    "br_market":   {"region": "BR",  "lang": "pt-BR",  "probe": "^BVSP",  "tz": "America/Sao_Paulo"},
    "crypto_market": {"region": "US", "lang": "en-US", "probe": "BTC-USD", "tz": "UTC"},
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


class Market:
    """Access market-level data: status, hours, index summary.

    Parameters
    ----------
    market_id:
        Market identifier.  Recognised values:
        ``'us_market'``, ``'gb_market'``, ``'de_market'``, ``'fr_market'``,
        ``'jp_market'``, ``'cn_market'``, ``'hk_market'``, ``'au_market'``,
        ``'ca_market'``, ``'in_market'``, ``'br_market'``, ``'crypto_market'``.

    Examples
    --------
    >>> m = xf.Market("us_market")
    >>> m.status           # "pre" | "regular" | "post" | "closed"
    >>> m.timezone         # "America/New_York"
    >>> m.summary          # dict with index level, change, market state
    """

    def __init__(self, market_id: str) -> None:
        self._id = market_id.lower()
        self._meta = _MARKET_META.get(self._id, _MARKET_META["us_market"])
        self._data: dict[str, Any] | None = None

    def _get_data(self) -> dict[str, Any]:
        if self._data is None:
            self._data = _run(self._fetch_async())
        return self._data

    def _invalidate(self) -> None:
        """Clear cached data so the next access re-fetches."""
        self._data = None

    async def _fetch_async(self) -> dict[str, Any]:
        probe = self._meta["probe"]
        region = self._meta["region"]
        lang = self._meta["lang"]

        async with httpx.AsyncClient(http2=True, follow_redirects=True) as client:
            # v7 quote for live market state
            try:
                resp = await client.get(
                    f"{_BASE}/v7/finance/quote",
                    params={"symbols": probe, "lang": lang, "region": region},
                    headers=_HEADERS,
                    timeout=10,
                )
                if resp.status_code == 200:
                    quotes = (
                        (resp.json().get("quoteResponse") or {})
                        .get("result") or []
                    )
                    if quotes:
                        return dict(quotes[0])
            except Exception as exc:
                logger.debug("Market fetch failed: %s", exc)
        return {}

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def market_id(self) -> str:
        return self._id

    @property
    def timezone(self) -> str:
        """IANA timezone name for this market (e.g. ``'America/New_York'``)."""
        return self._get_data().get("exchangeTimezoneName") or self._meta["tz"]

    @property
    def status(self) -> str:
        """Current market state: ``'pre'``, ``'regular'``, ``'post'``, or ``'closed'``."""
        raw = self._get_data().get("marketState", "CLOSED").upper()
        _map = {"PRE": "pre", "REGULAR": "regular", "POST": "post", "POSTPOST": "post"}
        return _map.get(raw, "closed")

    @property
    def is_open(self) -> bool:
        """True when the regular session is currently active."""
        return self.status == "regular"

    @property
    def currency(self) -> str | None:
        return self._get_data().get("currency")

    @property
    def exchange(self) -> str | None:
        return self._get_data().get("fullExchangeName") or self._get_data().get("exchange")

    @property
    def summary(self) -> dict[str, Any]:
        """Full quote dict for the probe instrument (index/benchmark asset)."""
        data = self._get_data()
        return {
            "market_id": self._id,
            "status": self.status,
            "timezone": self.timezone,
            "currency": data.get("currency"),
            "exchange": data.get("fullExchangeName"),
            "symbol": data.get("symbol"),
            "price": data.get("regularMarketPrice"),
            "change": data.get("regularMarketChange"),
            "change_pct": data.get("regularMarketChangePercent"),
            "previous_close": data.get("regularMarketPreviousClose"),
            "open": data.get("regularMarketOpen"),
            "day_high": data.get("regularMarketDayHigh"),
            "day_low": data.get("regularMarketDayLow"),
            "volume": data.get("regularMarketVolume"),
            "fifty_two_week_high": data.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": data.get("fiftyTwoWeekLow"),
            "pre_market_price": data.get("preMarketPrice"),
            "post_market_price": data.get("postMarketPrice"),
        }

    @property
    def open_time(self) -> datetime | None:
        """Timestamp of the last regular-session open (UTC)."""
        epoch = self._get_data().get("regularMarketTime")
        if epoch:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        return None

    def __repr__(self) -> str:
        return f"xfinance.Market('{self._id}', status='{self.status}')"
