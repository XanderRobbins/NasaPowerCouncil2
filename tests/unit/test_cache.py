"""Unit tests for the cache layer."""

from __future__ import annotations

import time

import pytest

from findata.stores.memory import MemoryCache


class TestMemoryCache:
    def test_set_and_get(self):
        cache = MemoryCache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_missing_key_returns_none(self):
        cache = MemoryCache()
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        cache = MemoryCache(default_ttl=0.05)  # 50ms
        cache.set("key", "val")
        assert cache.get("key") == "val"
        time.sleep(0.1)
        assert cache.get("key") is None

    def test_custom_ttl_per_entry(self):
        cache = MemoryCache(default_ttl=3600)
        cache.set("short", "val", ttl=0.05)
        cache.set("long", "val", ttl=3600)
        time.sleep(0.1)
        assert cache.get("short") is None
        assert cache.get("long") == "val"

    def test_max_size_eviction(self):
        cache = MemoryCache(max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)  # evicts 'a'
        assert cache.get("a") is None
        assert cache.get("d") == 4
        assert len(cache) == 3

    def test_delete(self):
        cache = MemoryCache()
        cache.set("key", "val")
        cache.delete("key")
        assert cache.get("key") is None

    def test_clear(self):
        cache = MemoryCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert len(cache) == 0
        assert cache.get("a") is None

    def test_overwrite(self):
        cache = MemoryCache()
        cache.set("key", "old")
        cache.set("key", "new")
        assert cache.get("key") == "new"
        assert len(cache) == 1

    def test_stores_arbitrary_types(self):
        import pandas as pd

        cache = MemoryCache()
        df = pd.DataFrame({"a": [1, 2, 3]})
        cache.set("df", df)
        result = cache.get("df")
        pd.testing.assert_frame_equal(result, df)
