"""L1 in-memory cache: thread-safe TTL dictionary."""

from __future__ import annotations

import threading
import time
from typing import Any, Generic, TypeVar

V = TypeVar("V")


class _Entry(Generic[V]):
    __slots__ = ("value", "expires_at")

    def __init__(self, value: V, ttl: float) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl


class MemoryCache:
    """Simple thread-safe in-memory cache with per-entry TTL.

    Parameters
    ----------
    max_size:
        Maximum number of entries to keep.  When exceeded, the oldest entry
        (by insertion order) is evicted.
    default_ttl:
        Default time-to-live in seconds.
    """

    def __init__(self, *, max_size: int = 512, default_ttl: float = 300.0) -> None:
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._store: dict[str, _Entry[Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        """Return cached value or ``None`` if missing or expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.monotonic() > entry.expires_at:
                del self._store[key]
                return None
            return entry.value

    def set(self, key: str, value: Any, *, ttl: float | None = None) -> None:
        """Store *value* under *key* with the given TTL (seconds)."""
        ttl = ttl if ttl is not None else self._default_ttl
        with self._lock:
            if key not in self._store and len(self._store) >= self._max_size:
                # Evict oldest (first) key
                oldest = next(iter(self._store))
                del self._store[oldest]
            self._store[key] = _Entry(value, ttl)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
