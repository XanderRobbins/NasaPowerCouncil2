"""Ticker — the primary interface for xfinance, analogous to yfinance.Ticker.

Every property is lazily fetched and cached on first access.
All data is normalized through the DataCleaner layer before being returned.

Usage
-----
>>> import xfinance as xf
>>> t = xf.Ticker("AAPL")
>>> df = t.history(period="1y")
>>> t.info["longName"]
'Apple Inc.'
>>> t.financials
>>> t.balance_sheet
>>> t.cashflow
>>> t.dividends
>>> t.splits
>>> t.options
>>> chain = t.option_chain("2025-01-17")
>>> chain.calls
>>> t.recommendations
>>> t.institutional_holders
>>> t.major_holders
>>> t.insider_transactions
>>> t.calendar
>>> t.earnings_dates
>>> t.news
>>> t.analyst_price_targets
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from datetime import date
from typing import Any

import httpx
import pandas as pd

from xfinance import cleaner
from xfinance.exceptions import AllSourcesFailedError, SymbolNotFoundError
from xfinance.sources._utils import period_to_dates
from xfinance.sources.base import PricesParams
from xfinance.sources.yahoo import OptionChain, YahooSource
from xfinance.stores.memory import MemoryCache

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 300.0  # 5 minutes for cached properties


def _run(coro: Any) -> Any:
    """Run an async coroutine from sync context, including inside Jupyter."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


class Ticker:
    """Fetch financial data for a single symbol from multiple sources.

    Parameters
    ----------
    symbol:
        Ticker symbol (e.g. ``'AAPL'``, ``'BTC-USD'``, ``'EUR=X'``).
    session:
        Optional pre-configured httpx.AsyncClient.  A new one is created
        if not provided.
    proxy:
        Optional HTTP proxy URL.

    Examples
    --------
    >>> t = xf.Ticker("AAPL")
    >>> df = t.history(period="1mo")
    >>> t.info["longName"]
    'Apple Inc.'
    """

    def __init__(
        self,
        symbol: str,
        session: httpx.AsyncClient | None = None,
        proxy: str | None = None,
    ) -> None:
        self._symbol = symbol.upper()
        self._proxy = proxy
        self._session = session
        self._yahoo = YahooSource()
        self._cache = MemoryCache(default_ttl=_DEFAULT_TTL)
        self._http: httpx.AsyncClient | None = session

    @property
    def ticker(self) -> str:
        return self._symbol

    # ── HTTP client lifecycle ─────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None:
            kwargs: dict[str, Any] = {"http2": True, "follow_redirects": True}
            if self._proxy:
                kwargs["proxies"] = self._proxy
            self._http = httpx.AsyncClient(**kwargs)
        return self._http

    def _cached(self, key: str, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Return cached value or call fn(*args, **kwargs) and cache result."""
        val = self._cache.get(key)
        if val is not None:
            return val
        result = _run(fn(*args, **kwargs))
        self._cache.set(key, result)
        return result

    # ── Price history (the most important method) ─────────────────────────────

    def history(
        self,
        period: str | None = "1mo",
        interval: str = "1d",
        start: str | date | None = None,
        end: str | date | None = None,
        *,
        auto_adjust: bool = True,
        actions: bool = True,
        prepost: bool = False,
        repair: bool = False,
        keepna: bool = False,
        rounding: bool = False,
    ) -> pd.DataFrame:
        """Fetch OHLCV price history.

        Parameters
        ----------
        period:       ``'1d'``, ``'5d'``, ``'1mo'``, ``'3mo'``, ``'6mo'``,
                      ``'1y'``, ``'2y'``, ``'5y'``, ``'10y'``, ``'ytd'``, ``'max'``.
                      Ignored when *start* is provided.
        interval:     Bar size: ``'1m'``, ``'2m'``, ``'5m'``, ``'15m'``, ``'30m'``,
                      ``'60m'``, ``'90m'``, ``'1h'``, ``'1d'``, ``'5d'``, ``'1wk'``,
                      ``'1mo'``, ``'3mo'``.
        start / end:  ISO date strings or date objects.
        auto_adjust:  Adjust all OHLC for splits and dividends (default True).
        actions:      Include Dividends and Stock Splits columns (default True).
        repair:       Detect and fix data quality issues:
                      - 100× unit errors (prices in wrong currency denomination)
                      - Split-unadjusted historical bars (large jump with no
                        recorded split; prior bars are scaled by inverse ratio)
        keepna:       Keep rows where all OHLCV values are NaN rather than
                      dropping them (default False).
        rounding:     Round OHLC and Adj Close to 2 decimal places (default False).

        Returns
        -------
        pd.DataFrame with DatetimeIndex (UTC) and columns:
        Open, High, Low, Close, Volume, Dividends, Stock Splits, Capital Gains, Adj Close
        """
        async def _fetch() -> pd.DataFrame:
            client = await self._get_client()
            start_date = _parse_date(start) if start else None
            end_date = _parse_date(end) if end else None
            params = PricesParams(
                symbol=self._symbol,
                period=period if not start_date else None,
                start=start_date,
                end=end_date,
                interval=interval,
                prepost=prepost,
            )
            return await self._yahoo.fetch_prices(params, client=client)

        raw = _run(_fetch())
        # Capture chart metadata emitted by fetch_prices
        self._last_history_meta: dict[str, Any] = raw.attrs.get("_meta", {})
        return cleaner.clean_prices(
            raw,
            auto_adjust=auto_adjust,
            actions=actions,
            repair=repair,
            keepna=keepna,
            rounding=rounding,
        )

    # ── Dividends / splits / capital gains ───────────────────────────────────

    @property
    def dividends(self) -> pd.Series:
        """Historical dividend payments as a float64 Series."""
        df = self.history(period="max", auto_adjust=False, actions=True)
        return cleaner.extract_dividends(df)

    @property
    def splits(self) -> pd.Series:
        """Historical stock splits as a float64 Series (ratio: new/old)."""
        df = self.history(period="max", auto_adjust=False, actions=True)
        return cleaner.extract_splits(df)

    @property
    def capital_gains(self) -> pd.Series:
        """Historical capital gains distributions (ETFs / mutual funds)."""
        df = self.history(period="max", auto_adjust=False, actions=True)
        return cleaner.extract_capital_gains(df)

    @property
    def actions(self) -> pd.DataFrame:
        """Combined dividends and splits DataFrame."""
        df = self.history(period="max", auto_adjust=False, actions=True)
        divs = cleaner.extract_dividends(df)
        splt = cleaner.extract_splits(df)
        combined = pd.concat([divs.rename("Dividends"), splt.rename("Stock Splits")], axis=1).fillna(0)
        return combined[combined.any(axis=1)]

    # ── Info ──────────────────────────────────────────────────────────────────

    @property
    def info(self) -> dict[str, Any]:
        """Comprehensive asset information dict (200+ fields for equities).

        Keys match yfinance naming conventions for compatibility.
        All numeric values are properly typed (float / int, not strings).
        """
        def _fetch() -> dict[str, Any]:
            async def inner() -> dict[str, Any]:
                client = await self._get_client()
                raw = await self._yahoo.fetch_info(self._symbol, client=client)
                return cleaner.clean_info(raw)
            return _run(inner())
        return self._cached("info", lambda: (lambda: _fetch())())  # type: ignore[return-value]

    @property
    def fast_info(self) -> dict[str, Any]:
        """Quick-access subset of info — only makes one lightweight API call."""
        full = self.info
        keys = [
            "symbol", "shortName", "longName", "quoteType", "exchange",
            "currency", "regularMarketPrice", "regularMarketPreviousClose",
            "regularMarketOpen", "regularMarketDayHigh", "regularMarketDayLow",
            "regularMarketVolume", "marketCap", "fiftyTwoWeekHigh",
            "fiftyTwoWeekLow", "fiftyDayAverage", "twoHundredDayAverage",
            "trailingPE", "forwardPE", "dividendYield", "beta",
        ]
        return {k: full.get(k) for k in keys if k in full}

    # ── Financial statements ──────────────────────────────────────────────────

    def _get_financials(self) -> dict[str, Any]:
        return self._cached(
            "financials_raw",
            self._fetch_financials_async,
        )

    async def _fetch_financials_async(self) -> dict[str, Any]:
        client = await self._get_client()
        return await self._yahoo.fetch_financials(self._symbol, client=client)

    @property
    def income_stmt(self) -> pd.DataFrame:
        """Annual income statement. Columns = fiscal year end dates (newest first)."""
        raw = self._get_financials()
        mod = raw.get("incomeStatementHistory", {})
        df = YahooSource.parse_financial_statement(mod, "incomeStatementHistory")
        return cleaner.clean_financial_statement(df)

    # Alias matching yfinance
    @property
    def financials(self) -> pd.DataFrame:
        return self.income_stmt

    @property
    def quarterly_income_stmt(self) -> pd.DataFrame:
        """Quarterly income statement."""
        raw = self._get_financials()
        mod = raw.get("incomeStatementHistoryQuarterly", {})
        df = YahooSource.parse_financial_statement(mod, "incomeStatementHistory")
        return cleaner.clean_financial_statement(df)

    @property
    def quarterly_financials(self) -> pd.DataFrame:
        return self.quarterly_income_stmt

    @property
    def balance_sheet(self) -> pd.DataFrame:
        """Annual balance sheet."""
        raw = self._get_financials()
        mod = raw.get("balanceSheetHistory", {})
        df = YahooSource.parse_financial_statement(mod, "balanceSheetStatements")
        return cleaner.clean_financial_statement(df)

    @property
    def quarterly_balance_sheet(self) -> pd.DataFrame:
        """Quarterly balance sheet."""
        raw = self._get_financials()
        mod = raw.get("balanceSheetHistoryQuarterly", {})
        df = YahooSource.parse_financial_statement(mod, "balanceSheetStatements")
        return cleaner.clean_financial_statement(df)

    @property
    def cashflow(self) -> pd.DataFrame:
        """Annual cash flow statement."""
        raw = self._get_financials()
        mod = raw.get("cashflowStatementHistory", {})
        df = YahooSource.parse_financial_statement(mod, "cashflowStatements")
        return cleaner.clean_financial_statement(df)

    # Alias
    @property
    def cash_flow(self) -> pd.DataFrame:
        return self.cashflow

    @property
    def quarterly_cashflow(self) -> pd.DataFrame:
        """Quarterly cash flow statement."""
        raw = self._get_financials()
        mod = raw.get("cashflowStatementHistoryQuarterly", {})
        df = YahooSource.parse_financial_statement(mod, "cashflowStatements")
        return cleaner.clean_financial_statement(df)

    @property
    def quarterly_cash_flow(self) -> pd.DataFrame:
        return self.quarterly_cashflow

    # ── Options ───────────────────────────────────────────────────────────────

    @property
    def options(self) -> tuple[str, ...]:
        """Tuple of available options expiry dates as ISO strings (YYYY-MM-DD)."""
        async def _fetch() -> list[str]:
            client = await self._get_client()
            return await self._yahoo.fetch_option_expiries(self._symbol, client=client)
        dates = self._cached("options_expiries", _fetch)
        return tuple(dates)

    def option_chain(self, date_str: str) -> OptionChain:
        """Fetch the full options chain for a specific expiry date.

        Parameters
        ----------
        date_str:  Expiry date as 'YYYY-MM-DD'. Use ``ticker.options`` to
                   get available dates.

        Returns
        -------
        OptionChain(calls=DataFrame, puts=DataFrame)
        """
        async def _fetch() -> OptionChain:
            client = await self._get_client()
            raw = await self._yahoo.fetch_option_chain(self._symbol, date_str, client=client)
            return OptionChain(
                calls=cleaner.clean_options(raw.calls),
                puts=cleaner.clean_options(raw.puts),
            )
        return _run(_fetch())

    # ── Holders ───────────────────────────────────────────────────────────────

    def _get_holders(self) -> dict[str, Any]:
        return self._cached("holders_raw", self._fetch_holders_async)

    async def _fetch_holders_async(self) -> dict[str, Any]:
        client = await self._get_client()
        return await self._yahoo.fetch_holders(self._symbol, client=client)

    @property
    def institutional_holders(self) -> pd.DataFrame:
        """Top institutional holders with shares and % held."""
        raw = self._get_holders()
        df = YahooSource.parse_institutional_holders(raw)
        return cleaner.clean_holders(df)

    @property
    def major_holders(self) -> pd.DataFrame:
        """Breakdown of insider / institutional ownership percentages."""
        raw = self._get_holders()
        df = YahooSource.parse_major_holders(raw)
        return cleaner.clean_holders(df)

    @property
    def insider_transactions(self) -> pd.DataFrame:
        """Recent insider buy/sell transactions."""
        raw = self._get_holders()
        df = YahooSource.parse_insider_transactions(raw)
        return cleaner.clean_holders(df)

    @property
    def insider_purchases(self) -> pd.DataFrame:
        """Insider transactions filtered to purchases only."""
        df = self.insider_transactions
        if df.empty or "Transaction" not in df.columns:
            return df
        return df[df["Transaction"].str.contains("Purchase|Buy", case=False, na=False)].reset_index(drop=True)

    @property
    def mutualfund_holders(self) -> pd.DataFrame:
        """Top mutual fund holders with shares and % held."""
        raw = self._get_holders()
        df = YahooSource.parse_mutualfund_holders(raw)
        return cleaner.clean_holders(df)

    @property
    def insider_roster_holders(self) -> pd.DataFrame:
        """Full insider roster — names, positions, and shares held directly/indirectly."""
        raw = self._get_holders()
        df = YahooSource.parse_insider_roster_holders(raw)
        return cleaner.clean_holders(df)

    # ── Events / earnings ─────────────────────────────────────────────────────

    def _get_events(self) -> dict[str, Any]:
        return self._cached("events_raw", self._fetch_events_async)

    async def _fetch_events_async(self) -> dict[str, Any]:
        client = await self._get_client()
        return await self._yahoo.fetch_events(self._symbol, client=client)

    @property
    def calendar(self) -> dict[str, Any]:
        """Upcoming earnings and dividend dates plus consensus estimates."""
        return YahooSource.parse_calendar(self._get_events())

    @property
    def earnings_dates(self) -> pd.DataFrame:
        """Historical earnings dates with EPS estimates and surprises."""
        raw = self._get_events()
        df = YahooSource.parse_earnings_dates(raw)
        return cleaner.clean_holders(df)

    # Alias
    @property
    def earnings_history(self) -> pd.DataFrame:
        return self.earnings_dates

    def get_earnings_dates(self, limit: int = 12) -> pd.DataFrame:
        """Return earnings dates — past (with actuals) and upcoming (estimates only).

        Parameters
        ----------
        limit:  Maximum number of dates to return (default 12, newest first).

        Returns
        -------
        DataFrame indexed by earnings date with columns:
        EPS Estimate, Reported EPS, Surprise(%), Period.
        Upcoming rows have NaN in Reported EPS and Surprise.
        """
        from datetime import datetime, timezone

        events = self._get_events()
        cal = YahooSource.parse_calendar(events)

        # Build rows for upcoming dates from calendar
        upcoming_rows = []
        for ds in cal.get("Earnings Date", []):
            try:
                dt = datetime.strptime(ds, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            upcoming_rows.append({
                "Date": dt,
                "EPS Estimate": cal.get("EPS Estimate"),
                "Reported EPS": float("nan"),
                "Surprise(%)": float("nan"),
                "Period": "future",
            })

        # Build rows for historical dates from earningsHistory
        raw = YahooSource.parse_earnings_dates(events)
        hist_rows = []
        if not raw.empty:
            for _, row in raw.iterrows():
                try:
                    dt = datetime.strptime(str(row.get("Date", "")), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue
                hist_rows.append({
                    "Date": dt,
                    "EPS Estimate": row.get("EPS Estimate"),
                    "Reported EPS": row.get("Reported EPS"),
                    "Surprise(%)": row.get("Surprise(%)"),
                    "Period": row.get("Period", ""),
                })

        all_rows = upcoming_rows + hist_rows
        if not all_rows:
            return pd.DataFrame(columns=["EPS Estimate", "Reported EPS", "Surprise(%)", "Period"])

        df = pd.DataFrame(all_rows)
        df = df.set_index("Date").sort_index(ascending=False)
        df.index.name = "Earnings Date"
        return df.head(limit)

    # ── Recommendations ───────────────────────────────────────────────────────

    @property
    def recommendations(self) -> pd.DataFrame:
        """Analyst recommendation trend (buy/hold/sell counts by period)."""
        raw_info = self._cached("info_raw", self._fetch_info_raw_async)
        df = YahooSource.parse_recommendations(raw_info)
        return cleaner.clean_recommendations(df)

    async def _fetch_info_raw_async(self) -> dict[str, Any]:
        client = await self._get_client()
        return await self._yahoo.fetch_info(self._symbol, client=client)

    @property
    def recommendations_summary(self) -> pd.DataFrame:
        return self.recommendations

    @property
    def upgrades_downgrades(self) -> pd.DataFrame:
        """Analyst upgrade/downgrade history."""
        raw = self._get_events()
        df = YahooSource.parse_upgrade_downgrade(raw)
        return cleaner.clean_holders(df)

    @property
    def analyst_price_targets(self) -> dict[str, Any]:
        """Analyst consensus price targets and recommendation."""
        raw_info = self._cached("info_raw", self._fetch_info_raw_async)
        return YahooSource.parse_analyst_targets(raw_info)

    # ── Sustainability (ESG) ──────────────────────────────────────────────────

    @property
    def sustainability(self) -> pd.DataFrame:
        """ESG scores — environment, social, governance, peer percentile.

        Returns a DataFrame with index = metric name, column = 'Value'.
        Returns an empty DataFrame for assets without ESG coverage.
        """
        async def _fetch() -> dict[str, Any]:
            client = await self._get_client()
            return await self._yahoo.fetch_esg(self._symbol, client=client)
        raw = self._cached("esg_raw", _fetch)
        return YahooSource.parse_sustainability(raw)

    # ── Earnings summary ──────────────────────────────────────────────────────

    @property
    def earnings(self) -> pd.DataFrame:
        """Annual EPS and Revenue summary.

        Returns a DataFrame indexed by fiscal year with columns
        ``['Earnings', 'Revenue']``.  Values are raw (unadjusted) totals.
        """
        raw = self._get_events()
        return YahooSource.parse_earnings_summary(raw, quarterly=False)

    @property
    def quarterly_earnings(self) -> pd.DataFrame:
        """Quarterly EPS and Revenue summary.

        Returns a DataFrame indexed by quarter label (e.g. '1Q2024') with
        columns ``['Earnings', 'Revenue']``.
        """
        raw = self._get_events()
        return YahooSource.parse_earnings_summary(raw, quarterly=True)

    # ── News ──────────────────────────────────────────────────────────────────

    @property
    def news(self) -> list[dict[str, Any]]:
        """Recent news articles. Each dict has: title, publisher, link, providerPublishTime, type."""
        async def _fetch() -> list[dict[str, Any]]:
            client = await self._get_client()
            return await self._yahoo.fetch_news(self._symbol, client=client)
        return self._cached("news", _fetch)  # type: ignore[return-value]

    # ── SEC EDGAR supplemental data ───────────────────────────────────────────

    async def _sec_company_facts_async(self) -> dict[str, Any]:
        from xfinance.sources.sec import SECSource
        sec = SECSource()
        client = await self._get_client()
        return await sec.fetch_company_facts(self._symbol, client=client)

    def sec_financials(self, concept: str, taxonomy: str = "us-gaap") -> pd.DataFrame:
        """Fetch a specific XBRL financial concept directly from SEC EDGAR.

        More reliable and historically deeper than Yahoo fundamentals.

        Parameters
        ----------
        concept:   XBRL concept name, e.g. ``'Revenues'``, ``'NetIncomeLoss'``,
                   ``'Assets'``, ``'EarningsPerShareBasic'``.
        taxonomy:  XBRL taxonomy, usually ``'us-gaap'`` or ``'dei'``.

        Examples
        --------
        >>> t = xf.Ticker("AAPL")
        >>> t.sec_financials("Revenues")
        """
        from xfinance.sources.sec import SECSource

        async def _fetch() -> pd.DataFrame:
            sec = SECSource()
            client = await self._get_client()
            return await sec.fetch_concept(self._symbol, taxonomy, concept, client=client)

        return _run(_fetch())

    # ── Funds data (ETF / mutual fund) ────────────────────────────────────────

    @property
    def funds_data(self) -> dict[str, Any]:
        """Rich ETF / mutual fund data object.

        Keys
        ----
        ``top_holdings``     DataFrame — symbol, name, % of assets
        ``sector_weightings`` DataFrame — sector, weight
        ``asset_classes``    dict — stock/bond/cash/other position %
        ``profile``          dict — fund family, category, manager
        ``annual_returns``   DataFrame — year, annual return
        ``monthly_returns``  DataFrame — trailing period returns
        ``risk_stats``       dict keyed by period (``'3y'``, ``'5y'``, ``'10y'``)
                             with alpha, beta, sharpe, std dev

        Returns an empty dict for non-fund assets.
        """
        async def _fetch() -> dict[str, Any]:
            client = await self._get_client()
            return await self._yahoo.fetch_funds_data(self._symbol, client=client)
        raw = self._cached("funds_raw", _fetch)
        return YahooSource.parse_funds_data(raw)

    # ── History metadata ──────────────────────────────────────────────────────

    @property
    def history_metadata(self) -> dict[str, Any]:
        """Metadata from the last ``history()`` call (or a lightweight probe).

        Includes: ``currency``, ``symbol``, ``exchangeName``,
        ``instrumentType``, ``timezone``, ``exchangeTimezoneName``,
        ``regularMarketPrice``, ``dataGranularity``, ``range``,
        ``validRanges``, ``firstTradeDate``.

        Populated automatically by ``history()``.  A lightweight API call
        is made if ``history()`` has not yet been called.
        """
        if hasattr(self, "_last_history_meta") and self._last_history_meta:
            return self._last_history_meta

        async def _probe() -> dict[str, Any]:
            client = await self._get_client()
            return await self._yahoo.fetch_price_metadata(self._symbol, client=client)

        return self._cached("history_meta", _probe)  # type: ignore[return-value]

    # ── Financial statement method variants ────────────────────────────────────

    def get_income_stmt(self, pretty: bool = False, freq: str = "yearly") -> pd.DataFrame:
        """Return the income statement as a DataFrame.

        Parameters
        ----------
        pretty:
            If True, format column headers as plain strings (no Timestamp objects).
        freq:
            ``'yearly'`` (default) or ``'quarterly'``.
        """
        df = self.quarterly_income_stmt if freq in ("quarterly", "q") else self.income_stmt
        if pretty:
            df = df.copy()
            df.columns = [str(c) for c in df.columns]
        return df

    def get_balance_sheet(self, pretty: bool = False, freq: str = "yearly") -> pd.DataFrame:
        """Return the balance sheet as a DataFrame.

        Parameters
        ----------
        pretty:
            If True, format column headers as plain strings.
        freq:
            ``'yearly'`` (default) or ``'quarterly'``.
        """
        df = self.quarterly_balance_sheet if freq in ("quarterly", "q") else self.balance_sheet
        if pretty:
            df = df.copy()
            df.columns = [str(c) for c in df.columns]
        return df

    def get_cashflow(self, pretty: bool = False, freq: str = "yearly") -> pd.DataFrame:
        """Return the cash flow statement as a DataFrame.

        Parameters
        ----------
        pretty:
            If True, format column headers as plain strings.
        freq:
            ``'yearly'`` (default) or ``'quarterly'``.
        """
        df = self.quarterly_cashflow if freq in ("quarterly", "q") else self.cashflow
        if pretty:
            df = df.copy()
            df.columns = [str(c) for c in df.columns]
        return df

    # ── TTM data ──────────────────────────────────────────────────────────────

    @property
    def ttm_data(self) -> pd.DataFrame:
        """Trailing-twelve-months income statement and cash flow.

        Computed by summing the four most recent quarterly income statement
        and cash flow columns.  Returns a single-column DataFrame with index
        = line-item name and column = ``'TTM'``.

        For items where summing is not meaningful (percentages, per-share
        figures, already-cumulative totals from balance sheet), use the
        annual statements or ``quarterly_income_stmt`` directly.
        """
        inc_q = self.quarterly_income_stmt
        cf_q = self.quarterly_cashflow

        parts: list[pd.Series] = []
        for df in (inc_q, cf_q):
            if df.empty:
                continue
            # Take up to 4 most recent columns (already sorted newest-first)
            cols = df.columns[:4]
            ttm = df[cols].sum(axis=1)
            parts.append(ttm)

        if not parts:
            return pd.DataFrame(columns=["TTM"])

        combined = pd.concat(parts)
        # De-duplicate (some line items appear in both statements)
        combined = combined[~combined.index.duplicated(keep="first")]
        return combined.rename("TTM").to_frame().sort_index()

    # ── Utility ───────────────────────────────────────────────────────────────

    @property
    def isin(self) -> str | None:
        """ISIN identifier for the security (if available)."""
        return self.info.get("isin")

    def get_isin(self) -> str | None:
        """Return ISIN if available in info, else None."""
        return self.isin

    def get_shares_full(self, start: str | None = None, end: str | None = None) -> pd.Series | None:
        """Return shares outstanding history (when available via SEC or Yahoo)."""
        try:
            df = self.sec_financials("CommonStockSharesOutstanding", "us-gaap")
            if df.empty:
                return None
            s = df[df["form"].isin(["10-K", "10-Q"])].set_index("end")["value"].sort_index()
            s.index = pd.to_datetime(s.index, utc=True)
            if start:
                s = s[s.index >= pd.Timestamp(start, tz="UTC")]
            if end:
                s = s[s.index <= pd.Timestamp(end, tz="UTC")]
            return s.rename("Shares Outstanding")
        except Exception:
            return None

    def __repr__(self) -> str:
        return f"xfinance.Ticker('{self._symbol}')"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(d: str | date) -> date:
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d))
