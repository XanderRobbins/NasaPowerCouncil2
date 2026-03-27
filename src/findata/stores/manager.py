"""CacheManager — unified interface across L1 (memory) and L2 (disk) caches.

TTL strategy by data type:
  - Real-time quotes:    5 seconds
  - Intraday prices:     5 minutes
  - Daily OHLCV:         6 hours during market hours, 24 hours after close
  - Fundamentals:        24 hours
  - Financial statements: 30 days
  - Asset info:          6 hours
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from findata.stores.memory import MemoryCache

logger = logging.getLogger(__name__)

# TTLs in seconds
_TTL_REALTIME = 5
_TTL_INTRADAY = 300         # 5 minutes
_TTL_DAILY = 6 * 3600       # 6 hours
_TTL_FUNDAMENTALS = 86400   # 24 hours
_TTL_STATEMENTS = 30 * 86400  # 30 days
_TTL_INFO = 6 * 3600        # 6 hours


def _cache_key(*parts: Any) -> str:
    raw = json.dumps(parts, default=str, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class CacheManager:
    """Two-tier cache: L1 memory always active; L2 disk optional.

    Parameters
    ----------
    use_disk:
        Whether to enable L2 diskcache.  Requires ``findata[cache]``.
    cache_dir:
        Directory for the diskcache database.
    """

    def __init__(self, *, use_disk: bool = False, cache_dir: str | None = None) -> None:
        self._l1 = MemoryCache(max_size=512, default_ttl=_TTL_DAILY)
        self._l2: Any | None = None

        if use_disk:
            try:
                from findata.stores.disk import DiskCache
                self._l2 = DiskCache(cache_dir)
            except Exception as exc:
                logger.warning("Could not initialise disk cache: %s", exc)

    # ── Prices ────────────────────────────────────────────────────────────────

    def get_prices(self, symbol: str, interval: str, start: Any, end: Any) -> pd.DataFrame | None:
        key = _cache_key("prices", symbol, interval, str(start), str(end))
        return self._get(key)

    def set_prices(
        self,
        symbol: str,
        interval: str,
        start: Any,
        end: Any,
        df: pd.DataFrame,
    ) -> None:
        ttl = _TTL_INTRADAY if interval != "1d" else _TTL_DAILY
        key = _cache_key("prices", symbol, interval, str(start), str(end))
        self._set(key, df, ttl=ttl)

    # ── Info ──────────────────────────────────────────────────────────────────

    def get_info(self, symbol: str) -> Any | None:
        key = _cache_key("info", symbol)
        return self._get(key)

    def set_info(self, symbol: str, info: Any) -> None:
        key = _cache_key("info", symbol)
        self._set(key, info, ttl=_TTL_INFO)

    # ── Generic helpers ───────────────────────────────────────────────────────

    def _get(self, key: str) -> Any | None:
        val = self._l1.get(key)
        if val is not None:
            return val
        if self._l2 is not None:
            val = self._l2.get(key)
            if val is not None:
                # Populate L1 on hit
                self._l1.set(key, val)
                return val
        return None

    def _set(self, key: str, value: Any, *, ttl: float) -> None:
        self._l1.set(key, value, ttl=ttl)
        if self._l2 is not None:
            try:
                self._l2.set(key, value, ttl=ttl)
            except Exception as exc:
                logger.warning("Disk cache write failed: %s", exc)

    def clear(self) -> None:
        self._l1.clear()
        if self._l2 is not None:
            self._l2.clear()
