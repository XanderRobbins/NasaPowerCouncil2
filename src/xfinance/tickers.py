"""Tickers — multi-symbol wrapper analogous to yfinance.Tickers.

Usage
-----
>>> import xfinance as xf
>>> ts = xf.Tickers("AAPL MSFT GOOGL")
>>> ts.tickers["AAPL"].info
>>> ts["MSFT"].history(period="1y")
>>> ts.download(period="1y")          # concurrent bulk download
>>> ts.history(period="6mo")          # dict of DataFrames per symbol
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from xfinance.ticker import Ticker


class Tickers:
    """Multi-ticker wrapper.  Gives individual ``Ticker`` objects plus bulk helpers.

    Parameters
    ----------
    tickers:
        Space-separated string (``"AAPL MSFT GOOGL"``) or list of symbols.
    session:
        Optional shared ``httpx.AsyncClient`` passed to every ``Ticker``.
    proxy:
        Optional HTTP proxy URL passed to every ``Ticker``.

    Examples
    --------
    >>> ts = xf.Tickers("AAPL MSFT")
    >>> ts["AAPL"].info["longName"]
    'Apple Inc.'
    >>> ts.tickers            # dict[str, Ticker]
    >>> ts.symbols            # list[str]
    >>> ts.download(period="1y")
    """

    def __init__(
        self,
        tickers: str | list[str],
        session: Any | None = None,
        proxy: str | None = None,
    ) -> None:
        if isinstance(tickers, str):
            # Accept both space-separated ("AAPL MSFT") and comma-separated
            # ("AAPL, MSFT") or mixed ("AAPL,MSFT GOOGL").
            import re as _re
            syms = [s.strip().upper() for s in _re.split(r"[\s,]+", tickers) if s.strip()]
        else:
            syms = [str(t).strip().upper() for t in tickers if str(t).strip()]

        self.symbols: list[str] = syms
        self.tickers: dict[str, Ticker] = {
            sym: Ticker(sym, session=session, proxy=proxy) for sym in syms
        }

    # ── Item access ───────────────────────────────────────────────────────────

    def __getitem__(self, key: str) -> Ticker:
        return self.tickers[key.upper()]

    def __getattr__(self, key: str) -> Ticker:
        # Allow ts.AAPL as well as ts["AAPL"]
        upper = key.upper()
        tickers = object.__getattribute__(self, "tickers")
        if upper in tickers:
            return tickers[upper]
        raise AttributeError(f"'Tickers' object has no attribute {key!r}")

    def __iter__(self):
        return iter(self.tickers)

    def __len__(self) -> int:
        return len(self.tickers)

    def __repr__(self) -> str:
        return f"xfinance.Tickers({self.symbols!r})"

    # ── Bulk helpers ──────────────────────────────────────────────────────────

    def download(
        self,
        period: str | None = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        *,
        group_by: str = "column",
        auto_adjust: bool = True,
        actions: bool = False,
        repair: bool = False,
        keepna: bool = False,
        rounding: bool = False,
        ignore_tz: bool = True,
        multi_level_index: bool = True,
    ) -> pd.DataFrame:
        """Bulk-download price history for all symbols concurrently.

        Delegates to :func:`xfinance.download`.  Returns a MultiIndex DataFrame
        (Price × Ticker) identical to calling ``xf.download(ts.symbols, ...)``.
        """
        from xfinance.download import download as _dl
        return _dl(
            self.symbols,
            period=period,
            interval=interval,
            start=start,
            end=end,
            group_by=group_by,
            auto_adjust=auto_adjust,
            actions=actions,
            repair=repair,
            keepna=keepna,
            rounding=rounding,
            ignore_tz=ignore_tz,
            multi_level_index=multi_level_index,
        )

    def history(
        self,
        period: str | None = "1mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        *,
        auto_adjust: bool = True,
        actions: bool = True,
        repair: bool = False,
        keepna: bool = False,
        rounding: bool = False,
    ) -> dict[str, pd.DataFrame]:
        """Fetch price history for each symbol individually.

        Returns
        -------
        dict[symbol, DataFrame] — one entry per symbol.
        Failed symbols are omitted with a warning logged.
        """
        import logging
        log = logging.getLogger(__name__)
        result: dict[str, pd.DataFrame] = {}
        for sym, ticker in self.tickers.items():
            try:
                result[sym] = ticker.history(
                    period=period,
                    interval=interval,
                    start=start,
                    end=end,
                    auto_adjust=auto_adjust,
                    actions=actions,
                    repair=repair,
                    keepna=keepna,
                    rounding=rounding,
                )
            except Exception as exc:
                log.warning("Tickers.history: failed %s — %s", sym, exc)
        return result

    def news(self) -> dict[str, list[dict]]:
        """Fetch recent news for each symbol.  Returns dict[symbol, list[article]]."""
        import logging
        log = logging.getLogger(__name__)
        result: dict[str, list[dict]] = {}
        for sym, ticker in self.tickers.items():
            try:
                result[sym] = ticker.news
            except Exception as exc:
                log.warning("Tickers.news: failed %s — %s", sym, exc)
        return result
