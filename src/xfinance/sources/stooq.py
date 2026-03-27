"""Stooq data source adapter — free global EOD price data.

Stooq (stooq.com) provides free historical end-of-day OHLCV data in CSV
format for global equities, indices, ETFs, forex, and some commodities.
No authentication required.  Risk tier 3 (unofficial, scraping-adjacent).

Symbol mapping
--------------
US stocks:    AAPL    → aapl.us
US ETFs:      SPY     → spy.us
Indices:      ^GSPC   → ^spx  |  ^DJI → ^dji  |  ^IXIC → ^ndq
Forex (Y=X):  EURUSD=X → eurusd  |  GBPUSD=X → gbpusd
International: ASML.AS → asml.nl | 7203.T → 7203.jp

Stooq is used as an equity price fallback when Yahoo Finance is unavailable.
Data is typically 15-minute delayed for US markets.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pandas as pd

from xfinance.exceptions import SourceUnavailableError, SymbolNotFoundError
from xfinance.models.source import DataSourceMeta, SupportedDataType
from xfinance.sources._utils import period_to_dates
from xfinance.sources.base import PricesParams

logger = logging.getLogger(__name__)

_BASE = "https://stooq.com/q/d/l/"

# Known index symbol translations: Yahoo → Stooq
_INDEX_MAP: dict[str, str] = {
    "^GSPC": "^spx",
    "^DJI": "^dji",
    "^IXIC": "^ndq",
    "^RUT": "^rut",
    "^VIX": "^vix",
    "^FTSE": "^fts",
    "^GDAXI": "^dax",
    "^FCHI": "^cac",
    "^N225": "^nkx",
    "^HSI": "^hsi",
    "^STOXX50E": "^sx5e",
    "^TNX": "^tnx",   # 10-year Treasury
    "^TYX": "^tyx",   # 30-year Treasury
    "^FVX": "^fvx",   # 5-year Treasury
    "^IRX": "^irx",   # 13-week T-bill
}

# Yahoo exchange suffix → Stooq country suffix
_EXCHANGE_SUFFIX: dict[str, str] = {
    ".L":  ".uk",    # London
    ".PA": ".fr",    # Paris
    ".AS": ".nl",    # Amsterdam
    ".DE": ".de",    # Frankfurt
    ".MI": ".it",    # Milan
    ".MC": ".es",    # Madrid
    ".TO": ".ca",    # Toronto
    ".AX": ".au",    # Australia
    ".HK": ".hk",    # Hong Kong
    ".T":  ".jp",    # Tokyo
    ".SS": ".cn",    # Shanghai
    ".SZ": ".cn",    # Shenzhen
    ".KS": ".kr",    # Korea
    ".BO": ".in",    # Bombay
    ".NS": ".in",    # National India
    ".SW": ".ch",    # Switzerland
    ".ST": ".se",    # Stockholm
    ".CO": ".dk",    # Copenhagen
    ".OL": ".no",    # Oslo
    ".HE": ".fi",    # Helsinki
    ".BR": ".be",    # Brussels
    ".LS": ".pt",    # Lisbon
    ".VI": ".at",    # Vienna
    ".WA": ".pl",    # Warsaw
    ".PR": ".cz",    # Prague
    ".BU": ".hu",    # Budapest
}

_INTERVAL_MAP = {
    "1d": "d",
    "1wk": "w",
    "1mo": "m",
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://stooq.com/",
}


class StooqSource:
    """Data source adapter for Stooq (free global EOD data, no auth required).

    Used as a fallback for equity price data when Yahoo Finance is unavailable.
    Coverage: US stocks/ETFs, major global indices, forex, some international equities.
    """

    meta = DataSourceMeta(
        name="stooq",
        description="Stooq — free global EOD data, no auth, equity fallback",
        supported_types=[SupportedDataType.PRICES, SupportedDataType.FOREX],
        requires_api_key=False,
        rate_limit_per_minute=60,
        risk_tier=3,
        tos_url="https://stooq.com/",
    )

    def supports(self, data_type: SupportedDataType, symbol: str) -> bool:
        if data_type not in (SupportedDataType.PRICES, SupportedDataType.FOREX):
            return False
        # Skip crypto (Stooq coverage is poor)
        sym = symbol.upper()
        if sym.endswith(("-USD", "USDT", "BTC", "ETH")) or "BTC" in sym:
            return False
        return True

    async def fetch_prices(self, params: PricesParams, *, client: httpx.AsyncClient) -> pd.DataFrame:
        stooq_sym = self._to_stooq_symbol(params.symbol)

        if params.period:
            start, end = period_to_dates(params.period)
        else:
            start = params.start or date(1970, 1, 1)
            end = params.end or datetime.now(timezone.utc).date()

        interval = _INTERVAL_MAP.get(params.interval, "d")
        query = {
            "s": stooq_sym,
            "d1": start.strftime("%Y%m%d"),
            "d2": end.strftime("%Y%m%d"),
            "i": interval,
        }

        try:
            resp = await client.get(_BASE, params=query, headers=_HEADERS, timeout=15)
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError("stooq", f"Timeout fetching {stooq_sym}") from exc
        except httpx.RequestError as exc:
            raise SourceUnavailableError("stooq", str(exc)) from exc

        if resp.status_code == 404:
            raise SymbolNotFoundError("stooq", params.symbol)
        if resp.status_code != 200:
            raise SourceUnavailableError("stooq", f"HTTP {resp.status_code}", status_code=resp.status_code)

        return self._parse_csv(resp.text, params.symbol)

    async def fetch_info(self, symbol: str, *, client: httpx.AsyncClient) -> dict[str, Any]:
        # Stooq doesn't provide rich info — return minimal metadata
        return {"symbol": symbol, "stooq_symbol": self._to_stooq_symbol(symbol), "source": "stooq"}

    async def health_check(self, *, client: httpx.AsyncClient) -> bool:
        try:
            resp = await client.get(
                _BASE,
                params={"s": "aapl.us", "d1": "20240101", "d2": "20240105", "i": "d"},
                headers=_HEADERS,
                timeout=5,
            )
            return resp.status_code == 200 and "Date" in resp.text
        except httpx.RequestError:
            return False

    # ── Symbol translation ────────────────────────────────────────────────────

    @classmethod
    def _to_stooq_symbol(cls, symbol: str) -> str:
        """Translate a Yahoo-style symbol to Stooq format."""
        sym = symbol.strip()

        # 1. Known index map
        if sym in _INDEX_MAP:
            return _INDEX_MAP[sym]

        # 2. Stooq-style index (already has ^)
        if sym.startswith("^"):
            return sym.lower()

        # 3. Forex: EURUSD=X → eurusd
        if sym.endswith("=X"):
            return sym[:-2].lower()

        # 4. International: strip Yahoo exchange suffix, add Stooq suffix
        for yah_sfx, stooq_sfx in _EXCHANGE_SUFFIX.items():
            if sym.upper().endswith(yah_sfx.upper()):
                base = sym[: -len(yah_sfx)]
                return f"{base.lower()}{stooq_sfx}"

        # 5. Default: US stock — lowercase + .us suffix
        # Remove any Yahoo-specific suffixes like -USD, .US already
        clean = re.sub(r"\.(US|us)$", "", sym)
        return f"{clean.lower()}.us"

    @staticmethod
    def _parse_csv(text: str, original_symbol: str) -> pd.DataFrame:
        """Parse Stooq CSV response into a normalized price DataFrame."""
        text = text.strip()
        if not text or "No data" in text or len(text.splitlines()) < 2:
            raise SymbolNotFoundError("stooq", original_symbol)

        try:
            df = pd.read_csv(io.StringIO(text), parse_dates=["Date"])
        except Exception as exc:
            raise SourceUnavailableError("stooq", f"CSV parse error: {exc}") from exc

        if df.empty or "Close" not in df.columns:
            raise SymbolNotFoundError("stooq", original_symbol)

        # Standardise column names (Stooq uses Title Case already)
        col_map = {
            "Date": "Date",
            "Open": "Open",
            "High": "High",
            "Low": "Low",
            "Close": "Close",
            "Volume": "Volume",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        # Ensure all standard columns exist
        for col in ("Open", "High", "Low", "Volume"):
            if col not in df.columns:
                df[col] = float("nan") if col != "Volume" else 0

        df["Dividends"] = 0.0
        df["Stock Splits"] = 0.0
        df["Capital Gains"] = 0.0
        df["Adj Close"] = df["Close"]

        df["Date"] = pd.to_datetime(df["Date"], utc=True)
        df = df.set_index("Date").sort_index()

        # Drop rows where Close is NaN
        df = df.dropna(subset=["Close"])

        return df
