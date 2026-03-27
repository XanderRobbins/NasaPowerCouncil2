"""DataCleaner — normalizes all raw API responses into consistent, typed DataFrames.

Standards applied to every output:
  - Prices:    DatetimeIndex (UTC, name="Date"), float64 OHLC, int64 volume,
               columns: Open, High, Low, Close, Volume, Dividends, Stock Splits,
               Capital Gains, Adj Close
  - Financials: columns = period dates (newest first), rows = line items (str),
               all numeric values float64, NaN where not reported
  - Options:   strike, lastPrice, bid, ask, change as float64; volume,
               openInterest as Int64 (nullable); inTheMoney as bool
  - Info:      all numeric strings coerced to float/int, "N/A"/"None" → None,
               standard key names preserved (yfinance-compatible)
  - Holders:   consistent column naming, numeric dtypes, date columns as Timestamp
  - Series:    Dividends/Splits as float64 Series with DatetimeIndex (UTC)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Price history ─────────────────────────────────────────────────────────────

_PRICE_COLS = ["Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits", "Capital Gains", "Adj Close"]
_FLOAT_PRICE_COLS = ["Open", "High", "Low", "Close", "Dividends", "Stock Splits", "Capital Gains", "Adj Close"]


def clean_prices(
    df: pd.DataFrame,
    *,
    auto_adjust: bool = True,
    actions: bool = True,
    keepna: bool = False,
    rounding: bool = False,
    repair: bool = False,
) -> pd.DataFrame:
    """Normalize a raw prices DataFrame.

    Parameters
    ----------
    df:           Raw DataFrame from a source adapter (index = Date).
    auto_adjust:  If True, scale OHLC by Adj Close / Close ratio so all prices
                  are split- and dividend-adjusted.
    actions:      If True, keep Dividends and Stock Splits columns.
                  If False, drop them.
    keepna:       If True, keep rows where all OHLCV values are NaN instead of
                  dropping them (matches yfinance ``keepna=True`` behaviour).
    rounding:     If True, round OHLC and Adj Close to 2 decimal places after
                  all other processing.
    repair:       If True, attempt to detect and fix common data quality issues:
                  - 100× unit errors (Yahoo occasionally returns prices in cents)
                  - Split-unadjusted history (large single-bar jump with no
                    recorded split, corrected by applying the inverse factor to
                    all prior bars).
    """
    if df.empty:
        return df

    # Ensure DatetimeIndex named "Date", UTC
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    elif df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df.index.name = "Date"

    # Ensure all expected columns exist
    for col in _PRICE_COLS:
        if col not in df.columns:
            df[col] = 0.0 if col != "Adj Close" else np.nan

    # Float dtypes for price columns
    for col in _FLOAT_PRICE_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

    # Volume as int64 (fills NaN with 0)
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype("int64")

    # Optionally drop rows where OHLC are all NaN
    if not keepna:
        df = df.dropna(subset=["Open", "High", "Low", "Close"], how="all")

    # Adj Close fallback: use Close when not provided
    df["Adj Close"] = df["Adj Close"].fillna(df["Close"])

    # Repair before adjustment so corrections act on raw prices
    if repair:
        df = repair_prices(df)

    # Auto-adjust: scale OHLC so Close == Adj Close
    if auto_adjust:
        ratio = df["Adj Close"] / df["Close"].replace(0, np.nan)
        for col in ["Open", "High", "Low", "Close"]:
            df[col] = (df[col] * ratio).round(6)
        # After adjusting, Adj Close == Close
        df["Adj Close"] = df["Close"]

    # Sort ascending
    df = df.sort_index()

    if rounding:
        for col in ["Open", "High", "Low", "Close", "Adj Close"]:
            if col in df.columns:
                df[col] = df[col].round(2)

    if not actions:
        df = df.drop(columns=["Dividends", "Stock Splits", "Capital Gains"], errors="ignore")

    return df[_PRICE_COLS if actions else ["Open", "High", "Low", "Close", "Volume", "Adj Close"]]


def repair_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Detect and fix common OHLCV data quality issues.

    Two classes of errors are corrected:

    1. **100× unit errors** — Yahoo Finance occasionally returns historical
       prices denominated in cents (pence for LSE stocks, fils for Gulf
       markets, etc.) instead of the standard currency unit.  Any bar whose
       Close is more than 20× the series median is divided by 100; any bar
       whose Close is less than 1/20 of the median is multiplied by 100.

    2. **Split-unadjusted history** — When Yahoo applies a stock split
       going forward but leaves historical bars unadjusted, there is a large
       discontinuous jump (or drop) at the split date with no corresponding
       ``Stock Splits`` entry.  This function identifies those jumps,
       recognises the implied split ratio, and retroactively scales all
       prior OHLC bars by the inverse ratio so the series is continuous.

    Parameters
    ----------
    df:   Price DataFrame **after** type coercion (float64 OHLC, UTC index)
          but **before** auto-adjustment.  Must contain at least ``Close``.

    Returns
    -------
    Corrected copy of the DataFrame.
    """
    if df.empty or "Close" not in df.columns or len(df) < 2:
        return df

    df = df.copy()
    price_cols = [c for c in ["Open", "High", "Low", "Close", "Adj Close"] if c in df.columns]

    # ── 1. 100× unit errors ────────────────────────────────────────────────────
    median_close = df["Close"].median()
    if median_close > 0:
        too_high = df["Close"] > median_close * 20
        too_low = (df["Close"] < median_close / 20) & (df["Close"] > 0)
        if too_high.any():
            logger.debug("repair: divided %d rows by 100 (unit error)", too_high.sum())
            for col in price_cols:
                df.loc[too_high, col] /= 100
        if too_low.any():
            logger.debug("repair: multiplied %d rows by 100 (unit error)", too_low.sum())
            for col in price_cols:
                df.loc[too_low, col] *= 100

    # ── 2. Split-unadjusted history ────────────────────────────────────────────
    # Common exact split ratios and their reciprocals
    _SPLIT_FACTORS = [
        2.0, 3.0, 4.0, 5.0, 10.0,
        1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10,
        1.5, 2.5, 3 / 2,
    ]
    _TOLERANCE = 0.06  # ±6% around each factor

    close = df["Close"]
    pct_change = close.pct_change().abs()
    recorded_splits = df.get("Stock Splits", pd.Series(0.0, index=df.index)).fillna(0)

    # Candidate bars: single-day move ≥ 40% AND no split recorded that day
    candidates = pct_change[
        (pct_change >= 0.40) & ((recorded_splits == 0) | recorded_splits.isna())
    ].index

    for idx in candidates:
        loc = df.index.get_loc(idx)
        if loc == 0:
            continue
        prev = df["Close"].iloc[loc - 1]
        curr = df["Close"].iloc[loc]
        if prev <= 0 or curr <= 0:
            continue
        ratio = curr / prev
        for factor in _SPLIT_FACTORS:
            if abs(ratio / factor - 1.0) <= _TOLERANCE:
                # ratio ≈ factor: scale prior bars by ratio so the series is
                # continuous.  e.g. 2:1 split → ratio=0.5, prior bars halved;
                # 1:2 reverse split → ratio=2.0, prior bars doubled.
                for col in price_cols:
                    df.iloc[:loc, df.columns.get_loc(col)] *= ratio
                logger.debug(
                    "repair: corrected split artifact at %s "
                    "(ratio=%.4f, factor=%.4f, adjusted %d prior bars)",
                    idx, ratio, factor, loc,
                )
                break

    return df


def extract_dividends(df: pd.DataFrame) -> pd.Series:
    """Extract non-zero dividend rows as a float64 Series."""
    if "Dividends" not in df.columns:
        return pd.Series(dtype=float, name="Dividends")
    s = df["Dividends"].astype(float)
    return s[s > 0].rename("Dividends")


def extract_splits(df: pd.DataFrame) -> pd.Series:
    """Extract non-unity split rows as a float64 Series."""
    if "Stock Splits" not in df.columns:
        return pd.Series(dtype=float, name="Stock Splits")
    s = df["Stock Splits"].astype(float)
    return s[s != 0].rename("Stock Splits")


def extract_capital_gains(df: pd.DataFrame) -> pd.Series:
    """Extract non-zero capital gains as a float64 Series (mutual funds / ETFs)."""
    if "Capital Gains" not in df.columns:
        return pd.Series(dtype=float, name="Capital Gains")
    s = df["Capital Gains"].astype(float)
    return s[s > 0].rename("Capital Gains")


# ── Financial statements ──────────────────────────────────────────────────────

def clean_financial_statement(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a financial statement DataFrame.

    Columns → period dates sorted newest-first.
    Values  → float64 (NaN where not reported).
    Index   → string line-item names.
    """
    if df.empty:
        return df

    # Coerce all values to float
    df = df.apply(pd.to_numeric, errors="coerce")

    # Sort columns newest-first (they are date strings like "2023-09-30")
    try:
        sorted_cols = sorted(df.columns, key=lambda c: pd.Timestamp(c), reverse=True)
        df = df[sorted_cols]
    except Exception:
        pass

    # Drop rows that are entirely NaN
    df = df.dropna(how="all")

    return df


# ── Options ───────────────────────────────────────────────────────────────────

_OPT_FLOAT = ["strike", "lastPrice", "bid", "ask", "change", "percentChange", "impliedVolatility"]
_OPT_NULLABLE_INT = ["volume", "openInterest"]


def clean_options(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize an options chain DataFrame (calls or puts)."""
    if df.empty:
        return df

    for col in _OPT_FLOAT:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

    for col in _OPT_NULLABLE_INT:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    if "inTheMoney" in df.columns:
        df["inTheMoney"] = df["inTheMoney"].astype(bool)

    if "lastTradeDate" in df.columns:
        df["lastTradeDate"] = pd.to_datetime(df["lastTradeDate"], utc=True, errors="coerce")

    return df.sort_values("strike").reset_index(drop=True)


# ── Asset info dict ───────────────────────────────────────────────────────────

_INFO_STR_FIELDS = frozenset({
    "symbol", "shortName", "longName", "exchange", "fullExchangeName",
    "quoteType", "currency", "financialCurrency", "sector", "industry",
    "longBusinessSummary", "website", "address1", "address2", "city",
    "state", "zip", "country", "phone", "fax", "ir_website",
    "recommendationKey", "uuid", "messageBoardId", "market",
    "underlyingSymbol", "contractSymbol", "headSymbol",
})

_NA_STRINGS = frozenset({"N/A", "None", "null", "", "-", "nan", "NaN", "n/a"})


def clean_info(raw_modules: dict[str, Any]) -> dict[str, Any]:
    """Merge multiple quoteSummary modules into a single normalized info dict.

    Numeric values are coerced to float/int.
    N/A strings become None.
    All {raw, fmt, longFmt} dicts are unwrapped to their raw value.
    """
    merged: dict[str, Any] = {}

    # Module priority order (later modules override earlier for shared keys)
    module_order = [
        "quoteType", "price", "summaryDetail", "defaultKeyStatistics",
        "assetProfile", "financialData",
    ]
    for mod_name in module_order:
        mod = raw_modules.get(mod_name)
        if not mod:
            continue
        for k, v in mod.items():
            if k == "maxAge":
                continue
            merged[k] = _normalize_info_value(k, v)

    # Ensure symbol is uppercase
    if "symbol" in merged and merged["symbol"]:
        merged["symbol"] = str(merged["symbol"]).upper()

    return merged


def _normalize_info_value(key: str, value: Any) -> Any:
    """Unwrap Yahoo {raw, fmt} dicts and coerce types."""
    if isinstance(value, dict):
        raw = value.get("raw")
        if raw is not None:
            return _coerce_scalar(key, raw)
        # Empty dict or no raw → None
        return None

    if isinstance(value, str):
        if value in _NA_STRINGS:
            return None
        if key not in _INFO_STR_FIELDS:
            # Try numeric coercion for unknown string fields
            try:
                if "." in value:
                    return float(value.replace(",", ""))
                return int(value.replace(",", ""))
            except ValueError:
                pass
        return value

    return value


def _coerce_scalar(key: str, value: Any) -> Any:
    if key in _INFO_STR_FIELDS:
        return str(value) if value is not None else None
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.replace(",", ""))
        except ValueError:
            try:
                return float(value.replace(",", ""))
            except ValueError:
                return value
    return value


# ── Holders ───────────────────────────────────────────────────────────────────

def clean_holders(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a holders DataFrame: coerce numeric columns, parse dates."""
    if df.empty:
        return df

    for col in df.columns:
        if col in ("Date Reported", "Date"):
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
        elif col not in ("Holder", "URL", "Relation", "Transaction", "Period", "Firm", "Action", "Breakdown"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.reset_index(drop=True)


# ── Recommendations ───────────────────────────────────────────────────────────

def clean_recommendations(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a recommendations/upgrade-downgrade DataFrame."""
    if df.empty:
        return df

    int_cols = {"Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"}
    for col in int_cols & set(df.columns):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    return df
