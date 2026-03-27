"""Real-time quote streaming via Yahoo Finance WebSocket.

Usage
-----
>>> import xfinance as xf
>>> import asyncio

# Async usage (recommended):
>>> async def on_quote(data):
...     print(data["symbol"], data["price"])
...
>>> asyncio.run(xf.stream(["AAPL", "MSFT"], callback=on_quote))

# Sync generator usage:
>>> for quote in xf.stream_sync(["AAPL", "MSFT"], max_quotes=10):
...     print(quote)

Requires the ``websocket`` extra:
    pip install xfinance[websocket]
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, Generator
from typing import Any, Callable

logger = logging.getLogger(__name__)

_WS_URL = "wss://streamer.finance.yahoo.com/"
_POLL_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_POLL_INTERVAL = 5.0  # seconds between polls in fallback mode

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}


async def _poll_quotes(
    symbols: list[str],
    *,
    interval: float = _POLL_INTERVAL,
) -> AsyncGenerator[dict[str, Any], None]:
    """Async generator that polls Yahoo v8 chart API for latest price updates."""
    import httpx

    async with httpx.AsyncClient(http2=True, follow_redirects=True) as client:
        while True:
            for symbol in symbols:
                try:
                    resp = await client.get(
                        _POLL_URL.format(symbol=symbol),
                        params={"interval": "1m", "range": "1d"},
                        headers=_HEADERS,
                        timeout=10,
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    result = (data.get("chart") or {}).get("result") or []
                    if not result:
                        continue
                    r = result[0]
                    meta = r.get("meta", {})
                    yield {
                        "symbol": symbol,
                        "price": meta.get("regularMarketPrice"),
                        "previousClose": meta.get("chartPreviousClose"),
                        "currency": meta.get("currency"),
                        "exchange": meta.get("exchangeName"),
                        "timestamp": meta.get("regularMarketTime"),
                        "source": "poll",
                    }
                except Exception as exc:
                    logger.debug("Poll error for %s: %s", symbol, exc)
            await asyncio.sleep(interval)


async def _ws_stream(
    symbols: list[str],
) -> AsyncGenerator[dict[str, Any], None]:
    """Async generator using Yahoo Finance WebSocket (requires websockets package)."""
    try:
        import websockets  # type: ignore[import]
    except ImportError:
        raise ImportError(
            "WebSocket streaming requires the 'websockets' package. "
            "Install it with: pip install xfinance[websocket]"
        ) from None

    subscribe_msg = json.dumps({"subscribe": symbols})

    try:
        async with websockets.connect(
            _WS_URL,
            extra_headers={"User-Agent": _HEADERS["User-Agent"]},
            ping_interval=20,
            ping_timeout=10,
        ) as ws:
            await ws.send(subscribe_msg)
            logger.info("WebSocket connected, subscribed to: %s", symbols)

            async for raw in ws:
                try:
                    # Yahoo sends protobuf-encoded messages; try JSON fallback
                    if isinstance(raw, bytes):
                        try:
                            msg = json.loads(raw.decode("utf-8"))
                        except Exception:
                            # Protobuf — emit raw bytes for downstream decoding
                            yield {"raw": raw, "source": "websocket"}
                            continue
                    else:
                        msg = json.loads(raw)

                    msg["source"] = "websocket"
                    yield msg
                except Exception as exc:
                    logger.debug("WS message parse error: %s", exc)
    except Exception as exc:
        logger.warning("WebSocket error: %s — falling back to polling", exc)
        async for quote in _poll_quotes(symbols):
            yield quote


async def stream(
    symbols: list[str] | str,
    callback: Callable[[dict[str, Any]], Any] | None = None,
    *,
    use_websocket: bool = True,
    poll_interval: float = _POLL_INTERVAL,
    max_quotes: int | None = None,
) -> None:
    """Stream real-time quotes for one or more symbols.

    Attempts a WebSocket connection first; falls back to HTTP polling if
    WebSocket fails or the ``websockets`` package is not installed.

    Parameters
    ----------
    symbols:
        Single ticker string or list of ticker strings.
    callback:
        Async or sync callable invoked for each quote dict.
        If None, quotes are logged at INFO level.
    use_websocket:
        Try WebSocket first (default True). Set False to force polling.
    poll_interval:
        Seconds between polls in polling mode (default 5.0).
    max_quotes:
        Stop after this many quotes (useful for testing). None = infinite.

    Examples
    --------
    >>> async def handler(q):
    ...     print(q["symbol"], q["price"])
    >>> await xf.stream(["AAPL", "TSLA"], callback=handler, max_quotes=20)
    """
    if isinstance(symbols, str):
        symbols = [symbols.upper()]
    else:
        symbols = [s.upper() for s in symbols]

    gen: AsyncGenerator[dict[str, Any], None]
    if use_websocket:
        gen = _ws_stream(symbols)
    else:
        gen = _poll_quotes(symbols, interval=poll_interval)

    count = 0
    async for quote in gen:
        if callback is not None:
            result = callback(quote)
            if asyncio.iscoroutine(result):
                await result
        else:
            logger.info("Quote: %s", quote)

        count += 1
        if max_quotes is not None and count >= max_quotes:
            break


def stream_sync(
    symbols: list[str] | str,
    *,
    use_websocket: bool = True,
    poll_interval: float = _POLL_INTERVAL,
    max_quotes: int | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Synchronous generator wrapper around :func:`stream`.

    Yields quote dicts one at a time. Runs a dedicated event loop internally.

    Parameters
    ----------
    symbols:
        Single ticker string or list of ticker strings.
    use_websocket:
        Try WebSocket first (default True).
    poll_interval:
        Seconds between polls in polling mode (default 5.0).
    max_quotes:
        Maximum number of quotes to yield before stopping.

    Examples
    --------
    >>> for q in xf.stream_sync(["AAPL", "MSFT"], max_quotes=10):
    ...     print(q["symbol"], q["price"])
    """
    if isinstance(symbols, str):
        symbols = [symbols.upper()]
    else:
        symbols = [s.upper() for s in symbols]

    import queue
    import threading

    q: queue.Queue[dict[str, Any] | None] = queue.Queue()

    async def _producer() -> None:
        if use_websocket:
            gen = _ws_stream(symbols)
        else:
            gen = _poll_quotes(symbols, interval=poll_interval)

        count = 0
        async for quote in gen:
            q.put(quote)
            count += 1
            if max_quotes is not None and count >= max_quotes:
                break
        q.put(None)  # sentinel

    def _run_loop() -> None:
        asyncio.run(_producer())

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()

    while True:
        item = q.get()
        if item is None:
            break
        yield item

    thread.join()
