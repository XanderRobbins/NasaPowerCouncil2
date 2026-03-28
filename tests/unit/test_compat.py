"""Unit tests for yfinance compatibility fixes."""

from __future__ import annotations

import logging

import pandas as pd
import pytest


class TestEnableDebugMode:
    def test_sets_debug_level(self):
        import xfinance as xf
        xf.enable_debug_mode()
        root = logging.getLogger("xfinance")
        assert root.level == logging.DEBUG
        # Reset to avoid affecting other tests
        root.setLevel(logging.WARNING)

    def test_callable_without_args(self):
        from xfinance._logging import enable_debug_mode
        enable_debug_mode()  # should not raise
        logging.getLogger("xfinance").setLevel(logging.WARNING)

    def test_exported_from_package(self):
        import xfinance as xf
        assert callable(xf.enable_debug_mode)


class TestScreenFunction:
    def test_exported_from_package(self):
        import xfinance as xf
        assert callable(xf.screen)

    def test_returns_same_as_screener(self, monkeypatch):
        from xfinance import screener as screener_mod

        fake_results = [{"symbol": "AAPL"}, {"symbol": "MSFT"}]

        class FakeScreener:
            def __init__(self, *args, **kwargs):
                pass

            @property
            def results(self):
                return fake_results

        monkeypatch.setattr(screener_mod, "Screener", FakeScreener)

        result = screener_mod.screen("most_actives", count=10)
        assert result == fake_results

    def test_signature_accepts_count(self):
        from xfinance import screener as screener_mod
        import inspect
        sig = inspect.signature(screener_mod.screen)
        assert "count" in sig.parameters
        assert sig.parameters["count"].default == 25


class TestDownloadProxy:
    def test_proxy_parameter_exists(self):
        import inspect
        from xfinance.download import download
        sig = inspect.signature(download)
        assert "proxy" in sig.parameters
        assert sig.parameters["proxy"].default is None

    def test_async_proxy_parameter_exists(self):
        import inspect
        from xfinance.download import _download_async
        sig = inspect.signature(_download_async)
        assert "proxy" in sig.parameters
