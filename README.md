# findata

**A multi-source, failover-capable Python financial data library.**

findata delivers yfinance's beloved simplicity with 10× the reliability through automatic failover across multiple data sources, intelligent three-tier caching, and a community plugin architecture.

## Why findata?

| Problem with yfinance | findata solution |
|---|---|
| Breaks 2–4×/year when Yahoo changes endpoints | Circuit-breaker failover to SEC, ECB, Binance |
| No built-in caching; hammers APIs on every call | Three-tier cache (memory → diskcache → Parquet) |
| No rate limiting; users get IP-blocked | Per-source adaptive rate limiters |
| Silent failures (empty DataFrames) | Rich exceptions with source provenance |
| Single unofficial API | 5+ sources, plugin architecture for more |

## Quick start

```bash
pip install findata
```

```python
import findata

# One line — works immediately, no API keys needed
df = findata.prices("AAPL", period="1mo")

# Multi-source with validation
client = findata.Client(sources=["yahoo", "sec", "ecb"])
df = client.prices("AAPL", start="2024-01-01", validate=True)

# Async batch fetching
import asyncio

async def main():
    async with findata.AsyncClient() as client:
        data = await client.prices(["AAPL", "GOOGL", "MSFT"], period="1y")

asyncio.run(main())

# Fundamentals from SEC EDGAR (free, no key needed)
info = findata.info("AAPL")

# Forex from ECB (free, no key, no rate limits)
fx = findata.forex("USD/EUR", period="1y")

# Crypto from Binance public API (free, no key)
btc = findata.prices("BTC/USDT", period="30d")
```

## Optional extras

```bash
pip install findata[cache]    # diskcache for persistent local caching
pip install findata[duckdb]   # DuckDB + Parquet for historical storage
pip install findata[polars]   # Polars DataFrame output
pip install findata[all]      # Everything
```

## Data sources (v0.1)

| Source | Data | Auth | Rate limit |
|---|---|---|---|
| Yahoo Finance | Prices, options, info | None (unofficial) | ~950 req/session |
| SEC EDGAR | Fundamentals, filings | None | 10 req/s |
| ECB / Frankfurter | Forex | None | No limit |
| Binance | Crypto OHLCV | None | 1200 req/min |
| CoinGecko | Crypto info | None (free tier) | 30 req/min |

See [DATA_SOURCES.md](DATA_SOURCES.md) for full terms-of-service details and risk tiers.

## Community plugins

Add new sources as pip-installable packages:

```toml
# In your plugin's pyproject.toml
[project.entry-points."findata.sources"]
tradingview = "findata_tradingview:TradingViewSource"
```

A new source adapter can be implemented in under 100 lines by implementing the `DataSource` protocol.

## Legal notice

findata fetches data on behalf of users as a client library. Users are responsible for complying with each data provider's terms of service. Government data (SEC EDGAR) is in the public domain. See [DATA_SOURCES.md](DATA_SOURCES.md) for source-specific guidance.

## License

Apache 2.0
