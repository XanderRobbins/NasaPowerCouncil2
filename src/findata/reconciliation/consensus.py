"""Median-based consensus reconciliation across multiple sources.

When multiple sources return price data for the same symbol, MedianConsensus:
1. Aligns DataFrames on their timestamp index.
2. Computes the median close price at each timestamp.
3. Flags any source deviating more than ``deviation_threshold`` (default 1%)
   from the median as potentially anomalous.
4. Returns the DataFrame from the source closest to the median.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_DEVIATION = 0.01  # 1%


class MedianConsensus:
    """Reconcile price DataFrames from multiple sources by median consensus.

    Parameters
    ----------
    deviation_threshold:
        Fraction (e.g. 0.01 = 1%) above which a source is flagged as anomalous.
    """

    def __init__(self, *, deviation_threshold: float = _DEFAULT_DEVIATION) -> None:
        self._threshold = deviation_threshold

    def reconcile(
        self,
        frames: dict[str, pd.DataFrame],
        *,
        symbol: str,
    ) -> tuple[pd.DataFrame, list[str]]:
        """Return ``(best_df, warnings)`` from *frames* keyed by source name.

        If only one source is provided it is returned immediately.
        """
        warnings: list[str] = []
        valid = {name: df for name, df in frames.items() if not df.empty}

        if not valid:
            raise ValueError(f"No valid DataFrames provided for {symbol!r}")

        if len(valid) == 1:
            return next(iter(valid.values())), warnings

        # Align on timestamp index, use 'close' column for consensus
        close_frames = {}
        for name, df in valid.items():
            if "close" in df.columns:
                close_frames[name] = df["close"].rename(name)

        if not close_frames:
            # Fallback: return first source if no 'close' column
            return next(iter(valid.values())), warnings

        aligned = pd.concat(close_frames.values(), axis=1, join="inner")
        if aligned.empty:
            # No overlapping timestamps; return source with most rows
            best = max(valid.items(), key=lambda kv: len(kv[1]))[0]
            warnings.append(
                f"{symbol}: Sources have no overlapping timestamps; using '{best}'"
            )
            return valid[best], warnings

        median = aligned.median(axis=1)

        # Detect anomalous sources
        anomalous = []
        deviations = {}
        for name in aligned.columns:
            series = aligned[name]
            pct_dev = ((series - median).abs() / median.replace(0, np.nan)).mean()
            deviations[name] = float(pct_dev)
            if pct_dev > self._threshold:
                anomalous.append(name)
                warnings.append(
                    f"{symbol}: Source '{name}' deviates {pct_dev:.2%} from "
                    f"median (threshold: {self._threshold:.2%}) — may have bad data"
                )

        # Pick the source with lowest deviation
        healthy = {k: v for k, v in deviations.items() if k not in anomalous}
        candidates = healthy if healthy else deviations
        best_name = min(candidates, key=candidates.__getitem__)

        logger.debug(
            "%s consensus: chose '%s' (dev=%.4f). All deviations: %s",
            symbol,
            best_name,
            deviations[best_name],
            deviations,
        )
        return valid[best_name], warnings
