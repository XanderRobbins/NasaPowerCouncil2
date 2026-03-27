"""Unit tests for the in-memory cache."""

from __future__ import annotations

import time

import pandas as pd
import pytest

from xfinance.stores.memory import MemoryCache


class TestMemoryCache:
    def test_set_and_get(self):
        c = MemoryCache()
        c.set("k", "v")
        assert c.get("k") == "v"

    def test_missing_returns_none(self):
        assert MemoryCache().get("nope") is None

    def test_ttl_expiry(self):
        c = MemoryCache(default_ttl=0.05)
        c.set("k", "v")
        assert c.get("k") == "v"
        time.sleep(0.1)
        assert c.get("k") is None

    def test_custom_ttl(self):
        c = MemoryCache(default_ttl=3600)
        c.set("short", "v", ttl=0.05)
        c.set("long", "v", ttl=3600)
        time.sleep(0.1)
        assert c.get("short") is None
        assert c.get("long") == "v"

    def test_max_size_eviction(self):
        c = MemoryCache(max_size=2)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        assert c.get("a") is None
        assert c.get("c") == 3
        assert len(c) == 2

    def test_delete(self):
        c = MemoryCache()
        c.set("k", "v")
        c.delete("k")
        assert c.get("k") is None

    def test_clear(self):
        c = MemoryCache()
        c.set("a", 1); c.set("b", 2)
        c.clear()
        assert len(c) == 0

    def test_overwrite(self):
        c = MemoryCache()
        c.set("k", "old")
        c.set("k", "new")
        assert c.get("k") == "new"

    def test_stores_dataframe(self):
        c = MemoryCache()
        df = pd.DataFrame({"a": [1, 2, 3]})
        c.set("df", df)
        pd.testing.assert_frame_equal(c.get("df"), df)
