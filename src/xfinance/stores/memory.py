"""L1 in-memory TTL cache."""

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
    def __init__(self, *, max_size: int = 512, default_ttl: float = 300.0) -> None:
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._store: dict[str, _Entry[Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.monotonic() > entry.expires_at:
                del self._store[key]
                return None
            return entry.value

    def set(self, key: str, value: Any, *, ttl: float | None = None) -> None:
        ttl = ttl if ttl is not None else self._default_ttl
        with self._lock:
            if key not in self._store and len(self._store) >= self._max_size:
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
