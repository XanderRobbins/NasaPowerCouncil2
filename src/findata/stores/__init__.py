"""Three-tier cache/storage backends for findata.

L1 — In-memory LRU with TTL (always available)
L2 — diskcache SQLite-backed persistent cache (requires findata[cache])
L3 — DuckDB + Parquet historical store (requires findata[duckdb])
"""

from findata.stores.memory import MemoryCache
from findata.stores.manager import CacheManager

__all__ = ["CacheManager", "MemoryCache"]
