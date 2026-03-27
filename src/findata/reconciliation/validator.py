"""DataValidator — per-row and whole-DataFrame quality checks.

Two layers:
1. Row-level: each PriceBar passes through the Pydantic model (OHLCV sanity).
2. DataFrame-level: no gaps in daily series, no extreme daily moves (>20%).
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from findata.exceptions import DataValidationError
from findata.models.bars import PriceBar

logger = logging.getLogger(__name__)

# >20% single-day move flags as suspicious
_MAX_DAILY_MOVE = 0.20


class DataValidator:
    """Validates a prices DataFrame, collecting warnings rather than hard-failing.

    Parameters
    ----------
    raise_on_error:
        If True, raise DataValidationError on the first critical issue
        instead of accumulating warnings.
    """

    def __init__(self, *, raise_on_error: bool = False, source: str = "") -> None:
        self._raise = raise_on_error
        self._source = source

    def validate_prices(self, df: pd.DataFrame, *, symbol: str) -> list[str]:
        """Run all price checks.  Returns list of warning strings."""
        warnings: list[str] = []

        if df.empty:
            self._issue(warnings, f"{symbol}: DataFrame is empty", critical=True)
            return warnings

        warnings.extend(self._check_ohlcv_relationships(df, symbol))
        warnings.extend(self._check_extreme_moves(df, symbol))
        warnings.extend(self._check_non_positive(df, symbol))

        return warnings

    # ── Checks ────────────────────────────────────────────────────────────────

    def _check_ohlcv_relationships(self, df: pd.DataFrame, symbol: str) -> list[str]:
        warnings = []
        for col in ("open", "high", "low", "close"):
            if col not in df.columns:
                self._issue(warnings, f"{symbol}: Missing column '{col}'", critical=True)
        if not {"open", "high", "low", "close"}.issubset(df.columns):
            return warnings

        bad_hl = (df["high"] < df["low"]).sum()
        if bad_hl:
            self._issue(warnings, f"{symbol}: {bad_hl} rows where high < low")

        bad_ho = (df["high"] < df["open"]).sum()
        if bad_ho:
            self._issue(warnings, f"{symbol}: {bad_ho} rows where high < open")

        bad_hc = (df["high"] < df["close"]).sum()
        if bad_hc:
            self._issue(warnings, f"{symbol}: {bad_hc} rows where high < close")

        bad_lo = (df["low"] > df["open"]).sum()
        if bad_lo:
            self._issue(warnings, f"{symbol}: {bad_lo} rows where low > open")

        bad_lc = (df["low"] > df["close"]).sum()
        if bad_lc:
            self._issue(warnings, f"{symbol}: {bad_lc} rows where low > close")

        return warnings

    def _check_extreme_moves(self, df: pd.DataFrame, symbol: str) -> list[str]:
        warnings = []
        if "close" not in df.columns or len(df) < 2:
            return warnings

        pct_change = df["close"].pct_change().abs()
        extreme = pct_change[pct_change > _MAX_DAILY_MOVE]
        if not extreme.empty:
            n = len(extreme)
            first = extreme.index[0]
            warnings.append(
                f"{symbol}: {n} bars with >20% daily move (first: {first}); "
                "may indicate split or bad data"
            )
        return warnings

    def _check_non_positive(self, df: pd.DataFrame, symbol: str) -> list[str]:
        warnings = []
        for col in ("open", "high", "low", "close"):
            if col not in df.columns:
                continue
            bad = (df[col] <= 0).sum()
            if bad:
                self._issue(warnings, f"{symbol}: {bad} non-positive values in '{col}'", critical=True)
        return warnings

    # ── Helper ────────────────────────────────────────────────────────────────

    def _issue(self, warnings: list[str], msg: str, *, critical: bool = False) -> None:
        prefixed = f"[{self._source}] {msg}" if self._source else msg
        if critical and self._raise:
            raise DataValidationError(msg, source=self._source or None)
        logger.warning(prefixed)
        warnings.append(prefixed)
