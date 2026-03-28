"""Bulk download of OHLCV data for multiple symbols.

Analogous to yfinance.download() but faster (concurrent async fetching)
and more reliable (multi-source failover per symbol).

Usage
-----
>>> import xfinance as xf
>>> df = xf.download(["AAPL", "MSFT", "GOOGL"], period="1y")
>>> df["Close"]          # all close prices, one column per ticker
>>> df["AAPL"]["Close"]  # or access by ticker
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

import httpx
import pandas as pd

from xfinance import cleaner
from xfinance.sources._utils import period_to_dates
from xfinance.sources.base import PricesParams
from xfinance.sources.yahoo import YahooSource
from xfinance.stores.memory import MemoryCache

logger = logging.getLogger(__name__)


async def _fetch_one(
    symbol: str,
    params: PricesParams,
    yahoo: YahooSource,
    client: httpx.AsyncClient,
) -> tuple[str, pd.DataFrame | Exception]:
    try:
        raw = await yahoo.fetch_prices(params, client=client)
        return symbol, raw
    except Exception as exc:
        logger.warning("download: failed to fetch %s: %s", symbol, exc)
        return symbol, exc


async def _download_async(
    symbols: list[str],
    *,
    period: str | None,
    start: date | None,
    end: date | None,
    interval: str,
    group_by: str,
    auto_adjust: bool,
    back_adjust: bool,
    actions: bool,
    threads: bool,
    multi_level_index: bool,
    repair: bool,
    keepna: bool,
    rounding: bool,
    prepost: bool,
    proxy: str | None = None,
) -> pd.DataFrame:
    yahoo = YahooSource()

    client_kwargs: dict = {"http2": True, "follow_redirects": True}
    if proxy:
        client_kwargs["proxies"] = proxy
    async with httpx.AsyncClient(**client_kwargs) as client:
        tasks = []
        for sym in symbols:
            params = PricesParams(
                symbol=sym,
                period=period if not start else None,
                start=start,
                end=end,
                interval=interval,
                prepost=prepost,
            )
            tasks.append(_fetch_one(sym, params, yahoo, client))

        results = await asyncio.gather(*tasks)

    # Build per-symbol DataFrames
    frames: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    for sym, result in results:
        if isinstance(result, Exception):
            failed.append(sym)
        else:
            df = cleaner.clean_prices(
                result,
                auto_adjust=auto_adjust,
                back_adjust=back_adjust,
                actions=actions,
                repair=repair,
                # For multi-symbol, always keep NaN rows here so the shared
                # index is preserved after concat; apply keepna post-concat.
                keepna=True if len(symbols) > 1 else keepna,
                rounding=rounding,
            )
            frames[sym] = df

    if failed:
        logger.warning("download: no data returned for: %s", ", ".join(failed))

    if not frames:
        return pd.DataFrame()

    if len(frames) == 1 and not multi_level_index:
        sym = list(frames.keys())[0]
        return frames[sym]

    # Multi-symbol: create a MultiIndex DataFrame
    # Outer level = metric (Open, High, Low, Close, Volume, …)
    # Inner level = symbol
    all_cols = list(next(iter(frames.values())).columns)
    pieces: dict[str, pd.DataFrame] = {}
    for col in all_cols:
        col_df = pd.concat(
            {sym: df[col] for sym, df in frames.items() if col in df.columns},
            axis=1,
        )
        col_df.columns.name = "Ticker"
        pieces[col] = col_df

    combined = pd.concat(pieces, axis=1)
    combined.columns.names = ["Price", "Ticker"]

    if group_by == "ticker":
        combined = combined.swaplevel(axis=1).sort_index(axis=1)
        combined.columns.names = ["Ticker", "Price"]

    combined = combined.sort_index()

    # keepna post-concat: drop rows where ALL symbols have NaN Close
    if not keepna and len(symbols) > 1:
        close_cols = combined.get("Close") if "Close" in combined.columns.get_level_values(0) else None
        if close_cols is not None:
            combined = combined[close_cols.notna().any(axis=1)]

    return combined


def download(
    tickers: str | list[str],
    period: str | None = "1mo",
    interval: str = "1d",
    start: str | date | None = None,
    end: str | date | None = None,
    *,
    group_by: str = "column",
    auto_adjust: bool = True,
    back_adjust: bool = False,
    actions: bool = False,
    threads: bool = True,
    ignore_tz: bool = True,
    multi_level_index: bool = True,
    repair: bool = False,
    keepna: bool = False,
    rounding: bool = False,
    prepost: bool = False,
    progress: bool = True,
    proxy: str | None = None,
) -> pd.DataFrame:
    """Download OHLCV data for one or multiple symbols concurrently.

    Parameters
    ----------
    tickers:
        Single symbol string or list of symbols.
    period:
        Lookback period (``'1d'``, ``'5d'``, ``'1mo'``, ``'3mo'``, ``'6mo'``,
        ``'1y'``, ``'2y'``, ``'5y'``, ``'10y'``, ``'ytd'``, ``'max'``).
        Ignored when *start* is provided.
    interval:
        Bar size (``'1d'``, ``'1wk'``, ``'1mo'``, ``'1h'``, etc.).
    start / end:
        Date range as ISO strings or date objects.
    group_by:
        ``'column'`` (default) — outer level is metric (Open, Close, …);
        ``'ticker'`` — outer level is symbol.
    auto_adjust:
        Adjust OHLC prices for splits/dividends (default True).
    actions:
        Include Dividends and Stock Splits columns (default False).
    threads:
        Fetch all symbols concurrently (always True in this implementation).
    ignore_tz:
        Strip timezone info from the DatetimeIndex (default True, matching
        yfinance behaviour for consistency with downstream tools).
    back_adjust:
        Use back-adjusted prices (scales prices backward to align with the
        oldest historical level).  Mutually exclusive with *auto_adjust*;
        when both are True, *back_adjust* takes precedence.
    multi_level_index:
        When True (default), always return a MultiIndex DataFrame for multiple
        tickers. When False, return a plain DataFrame for single-ticker downloads.
        Mirrors yfinance's ``multi_level_index`` parameter.
    repair:
        Detect and fix 100× unit errors and split-unadjusted history.
    keepna:
        Preserve rows where all OHLCV values are NaN.
    rounding:
        Round OHLC and Adj Close to 2 decimal places.
    prepost:
        Include pre- and post-market bars (only available for intraday intervals).
    progress:
        Print a progress indicator to stderr (default True; no-op when only
        one symbol is requested).

    Returns
    -------
    For a single ticker: plain DataFrame.
    For multiple tickers: MultiIndex DataFrame where the first level is the
    metric name and the second is the ticker symbol (or vice-versa when
    ``group_by='ticker'``).

    Examples
    --------
    >>> df = xf.download("AAPL", period="1mo")
    >>> df = xf.download(["AAPL", "MSFT"], period="1y")
    >>> df["Close"]["AAPL"]   # close prices for AAPL
    >>> df["AAPL"]["Close"]   # same thing with group_by="ticker"
    """
    import sys
    import concurrent.futures

    if isinstance(tickers, str):
        syms = [tickers.upper()]
    else:
        syms = [t.upper() for t in tickers]

    if progress and len(syms) > 1:
        print(f"[xfinance] Downloading {len(syms)} tickers: {', '.join(syms)}", file=sys.stderr)

    start_date = _parse_date(start) if start else None
    end_date = _parse_date(end) if end else None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(
                asyncio.run,
                _download_async(
                    syms,
                    period=period,
                    start=start_date,
                    end=end_date,
                    interval=interval,
                    group_by=group_by,
                    auto_adjust=auto_adjust,
                    back_adjust=back_adjust,
                    actions=actions,
                    threads=threads,
                    multi_level_index=multi_level_index,
                    repair=repair,
                    keepna=keepna,
                    rounding=rounding,
                    prepost=prepost,
                    proxy=proxy,
                ),
            ).result()
    else:
        result = asyncio.run(
            _download_async(
                syms,
                period=period,
                start=start_date,
                end=end_date,
                interval=interval,
                group_by=group_by,
                auto_adjust=auto_adjust,
                back_adjust=back_adjust,
                actions=actions,
                threads=threads,
                multi_level_index=multi_level_index,
                repair=repair,
                keepna=keepna,
                rounding=rounding,
                prepost=prepost,
                proxy=proxy,
            )
        )

    if ignore_tz and not result.empty and isinstance(result.index, pd.DatetimeIndex):
        result.index = result.index.tz_localize(None)

    return result


def _parse_date(d: str | date) -> date:
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d))
