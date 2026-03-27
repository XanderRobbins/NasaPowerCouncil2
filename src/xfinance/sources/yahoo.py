"""Yahoo Finance data source adapter — comprehensive coverage of all endpoints.

Covers:
  - Price history with dividends, splits, capital gains (v8 chart API)
  - Company info (25+ quoteSummary modules)
  - Income statement, balance sheet, cash flow (annual + quarterly)
  - Options chains (calls + puts)
  - Analyst recommendations and price targets
  - Institutional / insider holders
  - Earnings calendar and history
  - News
  - Real-time quote

Risk tier 3 — unofficial API, no warranty.
"""

from __future__ import annotations

import logging
from collections import namedtuple
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pandas as pd

from xfinance.exceptions import (
    SourceAuthError,
    SourceRateLimitError,
    SourceUnavailableError,
    SymbolNotFoundError,
)
from xfinance.models.source import DataSourceMeta, SupportedDataType
from xfinance.sources._utils import (
    camel_to_title,
    date_to_timestamp,
    extract_raw,
    period_to_dates,
    safe_float,
    safe_int,
)
from xfinance.sources.base import PricesParams

logger = logging.getLogger(__name__)

_BASE = "https://query1.finance.yahoo.com"
_BASE2 = "https://query2.finance.yahoo.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://finance.yahoo.com/",
    "Origin": "https://finance.yahoo.com",
}

OptionChain = namedtuple("OptionChain", ["calls", "puts"])

# ── quoteSummary module groupings ─────────────────────────────────────────────

_INFO_MODULES = (
    "assetProfile,summaryDetail,financialData,defaultKeyStatistics,"
    "price,quoteType,recommendationTrend"
)
_FINANCIALS_MODULES = (
    "incomeStatementHistory,incomeStatementHistoryQuarterly,"
    "balanceSheetHistory,balanceSheetHistoryQuarterly,"
    "cashflowStatementHistory,cashflowStatementHistoryQuarterly"
)
_HOLDERS_MODULES = (
    "institutionOwnership,majorHoldersBreakdown,"
    "insiderTransactions,insiderHolders,netSharePurchaseActivity,fundOwnership"
)
_EVENTS_MODULES = (
    "calendarEvents,earnings,earningsHistory,earningsTrend,upgradeDowngradeHistory"
)

# Human-readable names for financial statement line items
_METRIC_LABELS: dict[str, str] = {
    "totalRevenue": "Total Revenue",
    "costOfRevenue": "Cost Of Revenue",
    "grossProfit": "Gross Profit",
    "researchDevelopment": "Research Development",
    "sellingGeneralAdministrative": "Selling General Administrative",
    "nonRecurring": "Non Recurring",
    "otherOperatingExpenses": "Other Operating Expenses",
    "totalOperatingExpenses": "Total Operating Expenses",
    "operatingIncome": "Operating Income",
    "totalOtherIncomeExpenseNet": "Total Other Income Expense Net",
    "ebit": "EBIT",
    "interestExpense": "Interest Expense",
    "incomeBeforeTax": "Income Before Tax",
    "incomeTaxExpense": "Income Tax Expense",
    "minorityInterest": "Minority Interest",
    "netIncomeFromContinuingOps": "Net Income From Continuing Ops",
    "discontinuedOperations": "Discontinued Operations",
    "extraordinaryItems": "Extraordinary Items",
    "effectOfAccountingCharges": "Effect Of Accounting Charges",
    "otherItems": "Other Items",
    "netIncome": "Net Income",
    "netIncomeApplicableToCommonShares": "Net Income Applicable To Common Shares",
    # Balance sheet
    "cash": "Cash",
    "shortTermInvestments": "Short Term Investments",
    "netReceivables": "Net Receivables",
    "inventory": "Inventory",
    "otherCurrentAssets": "Other Current Assets",
    "totalCurrentAssets": "Total Current Assets",
    "longTermInvestments": "Long Term Investments",
    "propertyPlantEquipment": "Property Plant Equipment",
    "goodWill": "Goodwill",
    "intangibleAssets": "Intangible Assets",
    "otherAssets": "Other Assets",
    "deferredLongTermAssetCharges": "Deferred Long Term Asset Charges",
    "totalAssets": "Total Assets",
    "accountsPayable": "Accounts Payable",
    "shortLongTermDebt": "Short Long Term Debt",
    "otherCurrentLiab": "Other Current Liabilities",
    "longTermDebt": "Long Term Debt",
    "otherLiab": "Other Liabilities",
    "deferredLongTermLiab": "Deferred Long Term Liabilities",
    "minorityInterestBalance": "Minority Interest",
    "negativeGoodwill": "Negative Goodwill",
    "totalLiab": "Total Liabilities",
    "commonStock": "Common Stock",
    "retainedEarnings": "Retained Earnings",
    "treasuryStock": "Treasury Stock",
    "capitalSurplus": "Capital Surplus",
    "otherStockholderEquity": "Other Stockholder Equity",
    "totalStockholderEquity": "Total Stockholder Equity",
    "netTangibleAssets": "Net Tangible Assets",
    # Cash flow
    "netIncome": "Net Income",
    "depreciation": "Depreciation",
    "changeToNetincome": "Change To Netincome",
    "changeToAccountReceivables": "Change To Account Receivables",
    "changeToLiabilities": "Change To Liabilities",
    "changeToInventory": "Change To Inventory",
    "changeToOperatingActivities": "Change To Operating Activities",
    "totalCashFromOperatingActivities": "Total Cash From Operating Activities",
    "capitalExpenditures": "Capital Expenditures",
    "investments": "Investments",
    "otherCashflowsFromInvestingActivities": "Other Cash Flows From Investing Activities",
    "totalCashflowsFromInvestingActivities": "Total Cash From Investing Activities",
    "dividendsPaid": "Dividends Paid",
    "salePurchaseOfStock": "Sale Purchase Of Stock",
    "netBorrowings": "Net Borrowings",
    "otherCashflowsFromFinancingActivities": "Other Cash Flows From Financing Activities",
    "totalCashFromFinancingActivities": "Total Cash From Financing Activities",
    "effectOfExchangeRate": "Effect Of Exchange Rate",
    "changeInCash": "Change In Cash",
    "repurchaseOfStock": "Repurchase Of Stock",
    "issuanceOfStock": "Issuance Of Stock",
}

_SKIP_KEYS = frozenset({"maxAge", "endDate", "startDate"})


# ── Crumb / session management ────────────────────────────────────────────────

class _YahooCrumb:
    def __init__(self) -> None:
        self._crumb: str | None = None

    async def get(self, client: httpx.AsyncClient) -> str:
        if self._crumb is None:
            await self._refresh(client)
        return self._crumb or ""

    async def _refresh(self, client: httpx.AsyncClient) -> None:
        try:
            await client.get("https://fc.yahoo.com", headers=_HEADERS, follow_redirects=True, timeout=10)
        except httpx.RequestError:
            pass

        try:
            r = await client.get(
                f"{_BASE}/v1/test/getcrumb",
                headers={**_HEADERS, "referer": "https://finance.yahoo.com/"},
                timeout=10,
            )
            if r.status_code == 200 and r.text.strip():
                self._crumb = r.text.strip()
                return
        except httpx.RequestError:
            pass

        self._crumb = ""

    def invalidate(self) -> None:
        self._crumb = None


# ── Main source class ─────────────────────────────────────────────────────────

class YahooSource:
    """Comprehensive Yahoo Finance adapter.

    Provides prices, info, financials, options, holders, news, and more.
    All data is returned as raw parsed structures; the DataCleaner layer
    normalizes them into consistent DataFrames.
    """

    meta = DataSourceMeta(
        name="yahoo",
        description="Yahoo Finance unofficial JSON API — global equities, ETFs, crypto, forex, options",
        supported_types=[
            SupportedDataType.PRICES,
            SupportedDataType.INFO,
            SupportedDataType.OPTIONS,
            SupportedDataType.CRYPTO,
            SupportedDataType.FOREX,
            SupportedDataType.FUNDAMENTALS,
        ],
        requires_api_key=False,
        rate_limit_per_minute=60,
        risk_tier=3,
        tos_url="https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
    )

    def __init__(self) -> None:
        self._crumb = _YahooCrumb()

    def supports(self, data_type: SupportedDataType, symbol: str) -> bool:
        return data_type in self.meta.supported_types

    # ── Price history ─────────────────────────────────────────────────────────

    async def fetch_prices(self, params: PricesParams, *, client: httpx.AsyncClient) -> pd.DataFrame:
        if params.period:
            start, end = period_to_dates(params.period)
        else:
            start = params.start or date(1970, 1, 1)
            end = params.end or datetime.now(timezone.utc).date()

        crumb = await self._crumb.get(client)
        query: dict[str, Any] = {
            "period1": date_to_timestamp(start),
            "period2": date_to_timestamp(end),
            "interval": params.interval,
            "includeAdjustedClose": "true",
            "events": "div,splits,capitalGains",
        }
        if crumb:
            query["crumb"] = crumb

        data = await self._get(client, f"{_BASE}/v8/finance/chart/{params.symbol}", params=query)
        return self._parse_chart(data, params.symbol)

    # ── quoteSummary (info / fundamentals) ────────────────────────────────────

    async def fetch_quote_summary(
        self, symbol: str, modules: str, *, client: httpx.AsyncClient
    ) -> dict[str, Any]:
        """Fetch one or more quoteSummary modules. Returns raw dict keyed by module name."""
        crumb = await self._crumb.get(client)
        params: dict[str, Any] = {"modules": modules}
        if crumb:
            params["crumb"] = crumb

        data = await self._get(client, f"{_BASE}/v10/finance/quoteSummary/{symbol}", params=params)
        result = (data.get("quoteSummary") or {}).get("result") or []
        if not result:
            raise SymbolNotFoundError("yahoo", symbol)
        return result[0]  # type: ignore[return-value]

    async def fetch_info(self, symbol: str, *, client: httpx.AsyncClient) -> dict[str, Any]:
        return await self.fetch_quote_summary(symbol, _INFO_MODULES, client=client)

    async def fetch_financials(self, symbol: str, *, client: httpx.AsyncClient) -> dict[str, Any]:
        return await self.fetch_quote_summary(symbol, _FINANCIALS_MODULES, client=client)

    async def fetch_holders(self, symbol: str, *, client: httpx.AsyncClient) -> dict[str, Any]:
        return await self.fetch_quote_summary(symbol, _HOLDERS_MODULES, client=client)

    async def fetch_events(self, symbol: str, *, client: httpx.AsyncClient) -> dict[str, Any]:
        return await self.fetch_quote_summary(symbol, _EVENTS_MODULES, client=client)

    # ── Options ───────────────────────────────────────────────────────────────

    async def fetch_option_expiries(self, symbol: str, *, client: httpx.AsyncClient) -> list[str]:
        """Return list of available options expiry dates as ISO strings."""
        crumb = await self._crumb.get(client)
        params: dict[str, Any] = {}
        if crumb:
            params["crumb"] = crumb

        data = await self._get(client, f"{_BASE}/v7/finance/options/{symbol}", params=params)
        result = (data.get("optionChain") or {}).get("result") or []
        if not result:
            raise SymbolNotFoundError("yahoo", symbol)

        timestamps: list[int] = result[0].get("expirationDates", [])
        return [
            datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            for ts in timestamps
        ]

    async def fetch_option_chain(
        self, symbol: str, date_str: str, *, client: httpx.AsyncClient
    ) -> OptionChain:
        """Fetch calls and puts for a specific expiry date."""
        crumb = await self._crumb.get(client)
        # Convert ISO date → Unix timestamp
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        params: dict[str, Any] = {"date": int(dt.timestamp())}
        if crumb:
            params["crumb"] = crumb

        data = await self._get(client, f"{_BASE}/v7/finance/options/{symbol}", params=params)
        result = (data.get("optionChain") or {}).get("result") or []
        if not result:
            raise SymbolNotFoundError("yahoo", symbol)

        options = result[0].get("options", [{}])[0] if result[0].get("options") else {}
        calls = self._parse_options_contracts(options.get("calls", []))
        puts = self._parse_options_contracts(options.get("puts", []))
        return OptionChain(calls=calls, puts=puts)

    # ── News ──────────────────────────────────────────────────────────────────

    async def fetch_news(self, symbol: str, *, client: httpx.AsyncClient, count: int = 10) -> list[dict[str, Any]]:
        """Fetch recent news articles for a symbol."""
        params: dict[str, Any] = {
            "q": symbol,
            "newsCount": count,
            "enableFuzzyQuery": "false",
            "quotesCount": 0,
        }
        crumb = await self._crumb.get(client)
        if crumb:
            params["crumb"] = crumb

        data = await self._get(client, f"{_BASE}/v1/finance/search", params=params)
        return data.get("news", [])  # type: ignore[return-value]

    # ── Health ────────────────────────────────────────────────────────────────

    async def health_check(self, *, client: httpx.AsyncClient) -> bool:
        try:
            resp = await client.get(
                f"{_BASE}/v8/finance/chart/AAPL",
                headers=_HEADERS,
                timeout=5,
                follow_redirects=True,
            )
            return resp.status_code in {200, 401, 403}
        except httpx.RequestError:
            return False

    # ── HTTP helper ───────────────────────────────────────────────────────────

    async def _get(
        self, client: httpx.AsyncClient, url: str, *, params: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            resp = await client.get(url, params=params, headers=_HEADERS, timeout=20, follow_redirects=True)
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError("yahoo", f"Timeout: {url}") from exc
        except httpx.RequestError as exc:
            raise SourceUnavailableError("yahoo", str(exc)) from exc

        if resp.status_code == 429:
            self._crumb.invalidate()
            raise SourceRateLimitError("yahoo", retry_after=float(resp.headers.get("Retry-After", 60)))
        if resp.status_code in {401, 403}:
            self._crumb.invalidate()
            raise SourceAuthError("yahoo", "Auth failed; crumb expired", status_code=resp.status_code)
        if resp.status_code == 404:
            raise SymbolNotFoundError("yahoo", url.rsplit("/", 1)[-1].split("?")[0])
        if resp.status_code != 200:
            raise SourceUnavailableError("yahoo", f"HTTP {resp.status_code}", status_code=resp.status_code)

        try:
            return resp.json()  # type: ignore[return-value]
        except Exception as exc:
            raise SourceUnavailableError("yahoo", f"Invalid JSON: {exc}") from exc

    # ── Parsers ───────────────────────────────────────────────────────────────

    def _parse_chart(self, data: dict[str, Any], symbol: str) -> pd.DataFrame:
        result = (data.get("chart") or {}).get("result")
        if not result:
            raise SymbolNotFoundError("yahoo", symbol)

        r = result[0]
        timestamps: list[int] = r.get("timestamp", [])
        if not timestamps:
            raise SymbolNotFoundError("yahoo", symbol)

        quote = r.get("indicators", {}).get("quote", [{}])[0]
        adj_list = r.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])

        # Build events lookup: {timestamp → {div: float, split: float}}
        events = r.get("events", {})
        div_map: dict[int, float] = {
            int(v["date"]): float(v.get("amount", 0))
            for v in (events.get("dividends") or {}).values()
        }
        split_map: dict[int, float] = {
            int(v["date"]): float(v.get("numerator", 1)) / float(v.get("denominator", 1))
            for v in (events.get("splits") or {}).values()
        }
        cg_map: dict[int, float] = {
            int(v["date"]): float(v.get("amount", 0))
            for v in (events.get("capitalGains") or {}).values()
        }

        rows = []
        for i, ts in enumerate(timestamps):
            o = safe_float(quote.get("open", [None])[i] if i < len(quote.get("open", [])) else None)
            h = safe_float(quote.get("high", [None])[i] if i < len(quote.get("high", [])) else None)
            lo = safe_float(quote.get("low", [None])[i] if i < len(quote.get("low", [])) else None)
            c = safe_float(quote.get("close", [None])[i] if i < len(quote.get("close", [])) else None)
            v = safe_float(quote.get("volume", [0])[i] if i < len(quote.get("volume", [])) else 0)
            ac = safe_float(adj_list[i]) if i < len(adj_list) else None

            if None in (o, h, lo, c):
                continue

            rows.append({
                "Date": datetime.fromtimestamp(ts, tz=timezone.utc),
                "Open": o,
                "High": h,
                "Low": lo,
                "Close": c,
                "Volume": int(v or 0),
                "Dividends": div_map.get(ts, 0.0),
                "Stock Splits": split_map.get(ts, 0.0),
                "Capital Gains": cg_map.get(ts, 0.0),
                "Adj Close": ac,
            })

        if not rows:
            raise SymbolNotFoundError("yahoo", symbol)

        df = pd.DataFrame(rows).set_index("Date").sort_index()
        return df

    @staticmethod
    def _parse_options_contracts(contracts: list[dict[str, Any]]) -> pd.DataFrame:
        """Parse a list of Yahoo option contract dicts into a clean DataFrame."""
        rows = []
        for c in contracts:
            ltt = c.get("lastTradeDate", {})
            last_trade = (
                datetime.fromtimestamp(extract_raw(ltt) or 0, tz=timezone.utc)
                if extract_raw(ltt)
                else None
            )
            rows.append({
                "contractSymbol": c.get("contractSymbol", ""),
                "lastTradeDate": last_trade,
                "strike": safe_float(extract_raw(c.get("strike"))) or safe_float(c.get("strike")),
                "lastPrice": safe_float(extract_raw(c.get("lastPrice"))) or safe_float(c.get("lastPrice")),
                "bid": safe_float(extract_raw(c.get("bid"))) or safe_float(c.get("bid")),
                "ask": safe_float(extract_raw(c.get("ask"))) or safe_float(c.get("ask")),
                "change": safe_float(c.get("change", 0.0)),
                "percentChange": safe_float(c.get("percentChange", 0.0)),
                "volume": safe_float(extract_raw(c.get("volume"))) or safe_float(c.get("volume")),
                "openInterest": safe_float(extract_raw(c.get("openInterest"))) or safe_float(c.get("openInterest")),
                "impliedVolatility": safe_float(extract_raw(c.get("impliedVolatility"))) or safe_float(c.get("impliedVolatility")),
                "inTheMoney": bool(c.get("inTheMoney", False)),
                "contractSize": c.get("contractSize", "REGULAR"),
                "currency": c.get("currency", "USD"),
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("strike").reset_index(drop=True)
        return df

    # ── Static financial statement parsers ────────────────────────────────────

    @staticmethod
    def parse_financial_statement(
        raw_module: dict[str, Any],
        list_key: str,
    ) -> pd.DataFrame:
        """Parse a Yahoo quoteSummary financial statement module.

        Parameters
        ----------
        raw_module:  The module dict (e.g. data["incomeStatementHistory"])
        list_key:    The key whose value is the list of periods
                     (e.g. "incomeStatementHistory")
        """
        entries: list[dict[str, Any]] = raw_module.get(list_key, [])
        if not entries:
            return pd.DataFrame()

        periods: dict[str, dict[str, Any]] = {}
        for entry in entries:
            end_raw = entry.get("endDate", {})
            period_label = (
                end_raw.get("fmt")
                if isinstance(end_raw, dict)
                else str(end_raw)
            )
            if not period_label:
                continue
            row_data: dict[str, Any] = {}
            for key, val in entry.items():
                if key in _SKIP_KEYS:
                    continue
                raw_val = extract_raw(val)
                label = _METRIC_LABELS.get(key, camel_to_title(key))
                row_data[label] = raw_val
            periods[period_label] = row_data

        if not periods:
            return pd.DataFrame()

        df = pd.DataFrame(periods)
        # Sort columns newest-first
        try:
            df = df[sorted(df.columns, reverse=True)]
        except TypeError:
            pass
        return df

    @staticmethod
    def parse_recommendations(raw: dict[str, Any]) -> pd.DataFrame:
        trend = raw.get("recommendationTrend", {}).get("trend", [])
        rows = []
        for t in trend:
            rows.append({
                "Period": t.get("period"),
                "Strong Buy": t.get("strongBuy", 0),
                "Buy": t.get("buy", 0),
                "Hold": t.get("hold", 0),
                "Sell": t.get("sell", 0),
                "Strong Sell": t.get("strongSell", 0),
            })
        return pd.DataFrame(rows)

    @staticmethod
    def parse_upgrade_downgrade(raw: dict[str, Any]) -> pd.DataFrame:
        history = raw.get("upgradeDowngradeHistory", {}).get("history", [])
        rows = []
        for h in history:
            epoch = h.get("epochGradeDate")
            rows.append({
                "Date": datetime.fromtimestamp(epoch, tz=timezone.utc) if epoch else None,
                "Firm": h.get("firm", ""),
                "To Grade": h.get("toGrade", ""),
                "From Grade": h.get("fromGrade", ""),
                "Action": h.get("action", ""),
            })
        df = pd.DataFrame(rows)
        if not df.empty and "Date" in df.columns:
            df = df.set_index("Date").sort_index(ascending=False)
        return df

    @staticmethod
    def parse_institutional_holders(raw: dict[str, Any]) -> pd.DataFrame:
        owners = raw.get("institutionOwnership", {}).get("ownershipList", [])
        rows = []
        for o in owners:
            report_date = o.get("reportDate", {})
            rows.append({
                "Date Reported": report_date.get("fmt") if isinstance(report_date, dict) else report_date,
                "Holder": o.get("organization", ""),
                "pctHeld": safe_float(extract_raw(o.get("pctHeld"))),
                "Shares": safe_int(extract_raw(o.get("position"))),
                "Value": safe_int(extract_raw(o.get("value"))),
            })
        return pd.DataFrame(rows)

    @staticmethod
    def parse_major_holders(raw: dict[str, Any]) -> pd.DataFrame:
        data = raw.get("majorHoldersBreakdown", {})
        rows = [
            ("% of Shares Held by All Insider", safe_float(extract_raw(data.get("insidersPercentHeld")))),
            ("% of Shares Held by Institutions", safe_float(extract_raw(data.get("institutionsPercentHeld")))),
            ("% of Float Held by Institutions", safe_float(extract_raw(data.get("institutionsFloatPercentHeld")))),
            ("Number of Institutions Holding Shares", safe_int(extract_raw(data.get("institutionsCount")))),
        ]
        return pd.DataFrame(rows, columns=["Breakdown", "Value"])

    @staticmethod
    def parse_insider_transactions(raw: dict[str, Any]) -> pd.DataFrame:
        txns = raw.get("insiderTransactions", {}).get("transactions", [])
        rows = []
        for t in txns:
            start_date = t.get("startDate", {})
            rows.append({
                "Date": start_date.get("fmt") if isinstance(start_date, dict) else start_date,
                "Insider": t.get("filerName", ""),
                "Relation": t.get("filerRelation", ""),
                "Transaction": t.get("transactionText", ""),
                "Shares": safe_int(extract_raw(t.get("shares"))),
                "Value": safe_float(extract_raw(t.get("value"))),
                "URL": t.get("filerUrl", ""),
            })
        df = pd.DataFrame(rows)
        if not df.empty and "Date" in df.columns:
            df = df.sort_values("Date", ascending=False).reset_index(drop=True)
        return df

    @staticmethod
    def parse_mutualfund_holders(raw: dict[str, Any]) -> pd.DataFrame:
        """Parse mutual fund ownership from fundOwnership module."""
        owners = raw.get("fundOwnership", {}).get("ownershipList", [])
        rows = []
        for o in owners:
            report_date = o.get("reportDate", {})
            rows.append({
                "Date Reported": report_date.get("fmt") if isinstance(report_date, dict) else report_date,
                "Holder": o.get("organization", ""),
                "pctHeld": safe_float(extract_raw(o.get("pctHeld"))),
                "Shares": safe_int(extract_raw(o.get("position"))),
                "Value": safe_int(extract_raw(o.get("value"))),
            })
        return pd.DataFrame(rows)

    @staticmethod
    def parse_insider_roster_holders(raw: dict[str, Any]) -> pd.DataFrame:
        """Parse insider roster from insiderHolders module."""
        holders = raw.get("insiderHolders", {}).get("holders", [])
        rows = []
        for h in holders:
            latest_date = h.get("latestTransDate", {})
            pos_direct_date = h.get("positionDirectDate", {})
            rows.append({
                "Name": h.get("name", ""),
                "Position": h.get("relation", ""),
                "URL": h.get("url", ""),
                "Most Recent Transaction": h.get("transactionDescription", ""),
                "Latest Transaction Date": latest_date.get("fmt") if isinstance(latest_date, dict) else latest_date,
                "Shares Owned Directly": safe_int(extract_raw(h.get("positionDirect"))),
                "Position Direct Date": pos_direct_date.get("fmt") if isinstance(pos_direct_date, dict) else pos_direct_date,
                "Shares Owned Indirectly": safe_int(extract_raw(h.get("positionIndirect"))),
            })
        df = pd.DataFrame(rows)
        if not df.empty and "Latest Transaction Date" in df.columns:
            df = df.sort_values("Latest Transaction Date", ascending=False).reset_index(drop=True)
        return df

    @staticmethod
    def parse_earnings_dates(raw: dict[str, Any]) -> pd.DataFrame:
        history = raw.get("earningsHistory", {}).get("history", [])
        rows = []
        for h in history:
            period = h.get("period", "")
            quarter = h.get("quarter", {})
            rows.append({
                "Date": quarter.get("fmt") if isinstance(quarter, dict) else quarter,
                "EPS Estimate": safe_float(extract_raw(h.get("epsEstimate"))),
                "Reported EPS": safe_float(extract_raw(h.get("epsActual"))),
                "Surprise(%)": safe_float(extract_raw(h.get("epsDifference"))),
                "Period": period,
            })
        df = pd.DataFrame(rows)
        if not df.empty and "Date" in df.columns:
            df = df.sort_values("Date", ascending=False).reset_index(drop=True)
        return df

    @staticmethod
    def parse_calendar(raw: dict[str, Any]) -> dict[str, Any]:
        cal = raw.get("calendarEvents", {})
        earnings = cal.get("earnings", {})
        dates = earnings.get("earningsDate", [])
        dividend_date = cal.get("dividendDate", {})
        ex_dividend = cal.get("exDividendDate", {})

        return {
            "Earnings Date": [
                datetime.fromtimestamp(extract_raw(d) or 0, tz=timezone.utc).strftime("%Y-%m-%d")
                for d in dates
                if extract_raw(d)
            ],
            "EPS Estimate": safe_float(extract_raw(earnings.get("earningsAverage"))),
            "EPS Estimate Low": safe_float(extract_raw(earnings.get("earningsLow"))),
            "EPS Estimate High": safe_float(extract_raw(earnings.get("earningsHigh"))),
            "Revenue Estimate Avg": safe_float(extract_raw(earnings.get("revenueAverage"))),
            "Revenue Estimate Low": safe_float(extract_raw(earnings.get("revenueLow"))),
            "Revenue Estimate High": safe_float(extract_raw(earnings.get("revenueHigh"))),
            "Dividend Date": dividend_date.get("fmt") if isinstance(dividend_date, dict) else None,
            "Ex-Dividend Date": ex_dividend.get("fmt") if isinstance(ex_dividend, dict) else None,
        }

    @staticmethod
    def parse_analyst_targets(raw: dict[str, Any]) -> dict[str, Any]:
        fd = raw.get("financialData", {})
        return {
            "Current Price": safe_float(extract_raw(fd.get("currentPrice"))),
            "Target High Price": safe_float(extract_raw(fd.get("targetHighPrice"))),
            "Target Low Price": safe_float(extract_raw(fd.get("targetLowPrice"))),
            "Target Mean Price": safe_float(extract_raw(fd.get("targetMeanPrice"))),
            "Target Median Price": safe_float(extract_raw(fd.get("targetMedianPrice"))),
            "Recommendation Mean": safe_float(extract_raw(fd.get("recommendationMean"))),
            "Recommendation Key": fd.get("recommendationKey", ""),
            "Number Of Analyst Opinions": safe_int(extract_raw(fd.get("numberOfAnalystOpinions"))),
        }
