"""SEC EDGAR data source adapter.

Uses the official XBRL/submissions API at data.sec.gov.
Government data — no copyright, no API key required.
Rate limit: 10 requests/second.  Risk tier 1.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd

from findata.exceptions import SourceUnavailableError, SymbolNotFoundError
from findata.models.assets import AssetClass, AssetInfo
from findata.models.source import DataSourceMeta, SupportedDataType
from findata.sources.base import DataSource, PricesParams

logger = logging.getLogger(__name__)

_BASE = "https://data.sec.gov"
_HEADERS = {
    "User-Agent": "findata/0.1 (https://github.com/xanderrobbins/nasapowercouncil2; contact@example.com)",
    "Accept": "application/json",
}

# CIK lookup: ticker → CIK (zero-padded 10 digits)
_TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"


class SECSource:
    """Data source for SEC EDGAR — fundamentals, financial statements, filings.

    Provides fundamental data (income statement, balance sheet, cash flow)
    via the XBRL company facts API.  Does NOT provide price history.
    """

    meta = DataSourceMeta(
        name="sec",
        description="SEC EDGAR XBRL API — financial statements and filings",
        supported_types=[SupportedDataType.FUNDAMENTALS, SupportedDataType.INFO],
        requires_api_key=False,
        rate_limit_per_minute=600,  # 10/s × 60
        risk_tier=1,
        tos_url="https://www.sec.gov/privacy.htm",
    )

    def __init__(self) -> None:
        self._ticker_to_cik: dict[str, str] = {}

    def supports(self, data_type: SupportedDataType, symbol: str) -> bool:
        # Only for US-listed equities (no crypto, forex, futures)
        return data_type in self.meta.supported_types

    async def fetch_prices(self, params: PricesParams, *, client: httpx.AsyncClient) -> pd.DataFrame:
        raise NotImplementedError("SEC EDGAR does not provide price data. Use yahoo or another source.")

    async def fetch_info(self, symbol: str, *, client: httpx.AsyncClient) -> AssetInfo:
        cik = await self._resolve_cik(symbol, client)
        data = await self._get(client, f"{_BASE}/submissions/CIK{cik}.json")

        name = data.get("name", "")
        sic_desc = data.get("sicDescription", "")
        exchanges = data.get("exchanges", [])
        exchange = exchanges[0] if exchanges else ""
        tickers = data.get("tickers", [symbol])
        primary_ticker = tickers[0] if tickers else symbol

        return AssetInfo(
            symbol=primary_ticker,
            name=name,
            asset_class=AssetClass.EQUITY,
            exchange=exchange,
            country="US",
            industry=sic_desc,
            extra={
                "cik": cik,
                "sic": data.get("sic"),
                "category": data.get("category"),
                "fiscal_year_end": data.get("fiscalYearEnd"),
            },
            source="sec",
        )

    async def fetch_company_facts(self, symbol: str, *, client: httpx.AsyncClient) -> dict[str, Any]:
        """Fetch all XBRL company facts (income statement, balance sheet, etc.).

        Returns raw dict with structure:
        ``{'cik': ..., 'entityName': ..., 'facts': {'us-gaap': {...}, 'dei': {...}}}``
        """
        cik = await self._resolve_cik(symbol, client)
        return await self._get(client, f"{_BASE}/api/xbrl/companyfacts/CIK{cik}.json")

    async def fetch_concept(
        self, symbol: str, taxonomy: str, concept: str, *, client: httpx.AsyncClient
    ) -> pd.DataFrame:
        """Fetch a specific XBRL concept (e.g. 'us-gaap', 'Revenues') as a DataFrame.

        Parameters
        ----------
        symbol:   Stock ticker (e.g. 'AAPL')
        taxonomy: e.g. 'us-gaap', 'dei', 'ifrs-full'
        concept:  e.g. 'Revenues', 'NetIncomeLoss', 'Assets'
        """
        cik = await self._resolve_cik(symbol, client)
        url = f"{_BASE}/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{concept}.json"
        data = await self._get(client, url)
        return self._concept_to_df(data)

    async def health_check(self, *, client: httpx.AsyncClient) -> bool:
        try:
            resp = await client.get(
                f"{_BASE}/submissions/CIK0000320193.json",  # Apple
                headers=_HEADERS,
                timeout=5,
            )
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _resolve_cik(self, symbol: str, client: httpx.AsyncClient) -> str:
        sym = symbol.upper().split(".")[0]  # Strip exchange suffix
        if sym in self._ticker_to_cik:
            return self._ticker_to_cik[sym]

        # Download and cache the full ticker→CIK mapping
        data = await self._get(client, _TICKER_CIK_URL)
        for entry in data.values():
            ticker = entry.get("ticker", "").upper()
            cik_raw = entry.get("cik_str", 0)
            cik_padded = str(cik_raw).zfill(10)
            self._ticker_to_cik[ticker] = cik_padded

        if sym not in self._ticker_to_cik:
            raise SymbolNotFoundError("sec", symbol)

        return self._ticker_to_cik[sym]

    async def _get(self, client: httpx.AsyncClient, url: str) -> dict[str, Any]:
        try:
            resp = await client.get(url, headers=_HEADERS, timeout=20)
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError("sec", f"Request timed out: {url}") from exc
        except httpx.RequestError as exc:
            raise SourceUnavailableError("sec", str(exc)) from exc

        if resp.status_code == 404:
            raise SymbolNotFoundError("sec", url.rsplit("/", 1)[-1])
        if resp.status_code != 200:
            raise SourceUnavailableError("sec", f"HTTP {resp.status_code}: {url}", status_code=resp.status_code)

        try:
            return resp.json()  # type: ignore[no-any-return]
        except Exception as exc:
            raise SourceUnavailableError("sec", f"Invalid JSON: {exc}") from exc

    @staticmethod
    def _concept_to_df(data: dict[str, Any]) -> pd.DataFrame:
        """Convert a companyconcept response to a tidy DataFrame."""
        rows: list[dict[str, Any]] = []
        for unit_type, entries in data.get("units", {}).items():
            for e in entries:
                rows.append(
                    {
                        "end": e.get("end"),
                        "start": e.get("start"),
                        "value": e.get("val"),
                        "unit": unit_type,
                        "form": e.get("form"),
                        "filed": e.get("filed"),
                        "accn": e.get("accn"),
                        "fy": e.get("fy"),
                        "fp": e.get("fp"),
                    }
                )
        df = pd.DataFrame(rows)
        if not df.empty and "end" in df.columns:
            df["end"] = pd.to_datetime(df["end"], errors="coerce")
            df = df.sort_values("end")
        return df
