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

import re
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd


# ── Price history ─────────────────────────────────────────────────────────────

_PRICE_COLS = ["Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits", "Capital Gains", "Adj Close"]
_FLOAT_PRICE_COLS = ["Open", "High", "Low", "Close", "Dividends", "Stock Splits", "Capital Gains", "Adj Close"]


def clean_prices(df: pd.DataFrame, *, auto_adjust: bool = True, actions: bool = True) -> pd.DataFrame:
    """Normalize a raw prices DataFrame.

    Parameters
    ----------
    df:           Raw DataFrame from a source adapter (index = Date).
    auto_adjust:  If True, scale OHLC by Adj Close / Close ratio so all prices
                  are split- and dividend-adjusted.
    actions:      If True, keep Dividends and Stock Splits columns.
                  If False, drop them.
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

    # Drop rows where OHLC are all NaN
    df = df.dropna(subset=["Open", "High", "Low", "Close"], how="all")

    # Adj Close fallback: use Close when not provided
    df["Adj Close"] = df["Adj Close"].fillna(df["Close"])

    # Auto-adjust: scale OHLC so Close == Adj Close
    if auto_adjust:
        ratio = df["Adj Close"] / df["Close"].replace(0, np.nan)
        for col in ["Open", "High", "Low", "Close"]:
            df[col] = (df[col] * ratio).round(6)
        # After adjusting, Adj Close == Close
        df["Adj Close"] = df["Close"]

    # Sort ascending
    df = df.sort_index()

    if not actions:
        df = df.drop(columns=["Dividends", "Stock Splits", "Capital Gains"], errors="ignore")

    return df[_PRICE_COLS if actions else ["Open", "High", "Low", "Close", "Volume", "Adj Close"]]


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
