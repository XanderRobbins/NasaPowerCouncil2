# xFinance

**A Python financial data library with automatic multi-source failover.**

xFinance delivers yfinance's beloved simplicity with better reliability. When Yahoo Finance is rate-limited or unavailable, data transparently falls back to alternative sources (Stooq, SEC, ECB, Binance, CoinGecko). No code changes. No API keys needed.

## Why xFinance?

| Problem with yfinance | xFinance solution |
|---|---|
| Single point of failure (Yahoo only) | Circuit-breaker failover to 5 other sources |
| Frequent breakage when Yahoo changes | 6 independent adapters + plugin architecture |
| No caching; hammers APIs on every call | Per-instance in-memory cache (TTL 5 min) |
| Silent failures (empty DataFrames) | Rich exceptions with source provenance |
| Rate limits cause crashes | Transparent failover on 429 errors |

## Quick start

```python
import xfinance as xf

# Single ticker (multi-source failover, cached)
t = xf.Ticker("AAPL")
print(t.history(period="1y"))
print(t.info)
print(t.income_stmt)

# Multi-symbol concurrent download (50× faster than sequential)
df = xf.download(["AAPL", "MSFT", "GOOGL"], period="1y")
print(df["Close"])  # all close prices
print(df[["AAPL", "MSFT"]])  # subset of symbols

# Batch tickers
tickers = xf.Tickers(["AAPL", "MSFT", "GOOGL"])
print(tickers.history(period="6mo"))  # per-ticker DataFrames
print(tickers.download(period="6mo"))  # concurrent, one DataFrame
```

## Data sources

xFinance tries sources in this priority order, skipping any that don't support the requested data type:

| Source | Prices | Info | Forex | Crypto | Fundamentals | Options |
|---|---|---|---|---|---|---|
| **Yahoo Finance** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Stooq** | ✓ | — | ✓ | — | — | — |
| **SEC EDGAR** | — | ✓ | — | — | ✓ | — |
| **ECB Frankfurter** | — | — | ✓ | — | — | — |
| **Binance** | ✓ | ✓ | — | ✓ | — | — |
| **CoinGecko** | ✓ | ✓ | — | ✓ | — | — |

**Rate limits** (after which the circuit breaker opens for 60s, blocking further requests to that source):
- Yahoo: ~950 requests per session
- SEC: 10 requests/second
- ECB: No limit
- Binance: 1200 requests/minute
- CoinGecko: 30 requests/minute (free tier)

### Example: Forex data with automatic fallback

```python
# Try Yahoo → Stooq → ECB. The router handles failures silently.
t = xf.Ticker("USD/EUR")
df = t.history(period="1y", interval="1d")
# If Yahoo is rate-limited, Stooq tries next. If Stooq fails, ECB takes over.
# All transparent — one call, one DataFrame.
```

### Example: Crypto with multiple sources

```python
# Yahoo has crypto; Binance is free and fast.
# Router tries Yahoo first, falls back to Binance on failure.
t = xf.Ticker("BTC/USDT")
df = t.history(period="7d", interval="1h")
info = t.info  # market cap, current price, 24h change, etc.
```

### Example: Fundamentals from SEC when Yahoo is unavailable

```python
# SEC doesn't have OHLCV prices, but it has audited financials.
t = xf.Ticker("AAPL")
# Router tries Yahoo for prices (succeeds). Falls through to SEC on failure.
prices = t.history(period="1y")
# Yahoo has financials; SEC is a fallback.
income = t.income_stmt  # from Yahoo, or from t.sec_financials() if Yahoo fails
```

## API reference

### `xf.Ticker(symbol, session=None, proxy=None)`

Fetch data for a single symbol. All properties are lazy — they fetch on first access and cache for 5 minutes.

**Properties:**

- `history(period="1mo", interval="1d", start=None, end=None, **kwargs)` — OHLCV DataFrame (UTC index)
- `dividends` — Historical dividends (Series with DatetimeIndex)
- `splits` — Historical stock splits (Series, new/old ratio)
- `actions` — Combined dividends and splits (DataFrame)
- `info` — Company metadata (dict, 200+ fields)
- `income_stmt`, `balance_sheet`, `cashflow` — Annual financial statements
- `income_stmt_quarterly`, `balance_sheet_quarterly`, `cashflow_quarterly` — Quarterly financials
- `option_chain(expiry_date)` — Options data (NamedTuple with calls/puts DataFrames)
- `options` — Available expiry dates (list)
- `calendar`, `earnings_dates` — Earnings calendar (DataFrame)
- `recommendations` — Analyst recommendations (DataFrame)
- `analyst_price_targets` — Price targets by analyst (dict)
- `institutional_holders`, `major_holders`, `insider_transactions` — Ownership data
- `sustainability` — ESG scores and controversies
- `news` — Latest news headlines
- `fast_info` — Quick access wrapper with attribute-style access (e.g., `t.fast_info.market_cap`)

**Methods:**

- `sec_financials(concept, taxonomy)` — Fetch audited XBRL fundamentals from SEC EDGAR
- `get_shares_full()` — Historical share count (10-K/10-Q only)

### `xf.Tickers(symbols)`

Fetch data for multiple symbols with per-symbol error swallowing.

**Methods:**

- `history(period="1mo", interval="1d", **kwargs)` — List of per-ticker DataFrames
- `download(period="1mo", interval="1d", **kwargs)` — One MultiIndex DataFrame (concurrent)

### `xf.download(symbols, period="1mo", interval="1d", ..., group_by="price", na_fill=None)`

Concurrent multi-symbol download (yfinance-compatible signature).

**Parameters:**

- `symbols` — list of ticker symbols
- `period`, `interval`, `start`, `end` — date range
- `group_by` — `"price"` (default: columns = [Price, Ticker]) or `"ticker"` (columns = [Ticker, Price])
- `auto_adjust` — Adjust for splits/dividends (default True)
- `actions` — Include Dividends/Stock Splits columns (default True)
- `keepna` — Keep all-NaN rows (default False)
- `na_fill` — Fill remaining NaNs: `None` (default), `"ffill"`, `"bfill"`, or scalar
- `repair` — Detect and fix 100× unit errors, split-unadjusted bars (default False)
- `rounding` — Round to 2 decimals (default False)
- `proxy` — HTTP proxy URL (optional)

**Returns:** MultiIndex DataFrame with DatetimeIndex (UTC) and columns [Open, High, Low, Close, Volume, Adj Close, ...]

## How failover works

```
┌─────────────────────────────────────────┐
│ User calls: t.history(period="1y")      │
└────────────────┬────────────────────────┘
                 │
        ┌────────▼─────────┐
        │  DataSourceRouter │
        │  (circuit-breaker │
        │  per source)      │
        └────────┬─────────┘
                 │
        ┌────────▼──────────┐
        │ Yahoo Finance    │  Try #1
        │ (primary source) │
        └────────┬──────────┘
                 │
          ┌──────▼──────┐
          │ HTTP 429?   │──Yes──┐
          │ (rate limit)│       │
          └─────────────┘       │
                 │ No           │
          ┌──────▼──────┐       │
          │ Return data │       │
          └─────────────┘       │
                                │
                        ┌───────▼──────┐
                        │  Stooq       │  Try #2
                        │  (equities)  │
                        └───────┬──────┘
                                │
                        ┌───────▼──────┐
                        │  Success?    │──Yes──┐
                        │  Return data │       │
                        └───────┬──────┘       │
                                │ No          │
                        ┌───────▼──────┐       │
                        │  SEC / ECB   │  Try #3+
                        │  / Binance   │
                        └───────┬──────┘       │
                                │             │
                        ┌───────▼──────┐       │
                        │  Success?    │──Yes──┐
                        │  Return data │       │
                        └───────┬──────┘       │
                                │ No          │
                        ┌───────▼──────────┐   │
                        │ All sources      │   │
                        │ failed → raise   │   │
                        │ AllSourcesFailed │   │
                        └──────────────────┘   │
                                               │
                            ┌──────────────────┘
                            │
                    ┌───────▼──────────┐
                    │ User receives    │
                    │ data (origin     │
                    │ transparent)     │
                    └──────────────────┘
```

**Key features:**

- **Per-source circuit breakers:** After 5 consecutive failures, a source is "open" for 60 seconds. Further requests skip it without wasting HTTP calls.
- **Transparent fallback:** If a symbol isn't supported by the source (e.g., crypto on Yahoo), it's skipped without error.
- **Automatic retry on transient errors:** Network timeouts, 50x server errors, and rate limits trigger automatic exponential backoff (up to 4 attempts).

## Installation

```bash
pip install xfinance
```

Requires Python 3.10+. Installs dependencies: httpx, pandas, pydantic, pybreaker, tenacity.

## No API keys needed

All sources are public or free-tier:
- **Yahoo Finance:** Unofficial API, no key required
- **Stooq:** Free API, no key required
- **SEC EDGAR:** U.S. government data, public domain
- **ECB / Frankfurter:** Central bank data, public
- **Binance:** Public API, no key required
- **CoinGecko:** Free API tier (30 req/min), no key required

## Rate limit transparency

When Yahoo hits its ~950 request limit per session:

**Without xFinance (yfinance):**
```python
import yfinance as yf
t = yf.Ticker("AAPL")
df = t.history(period="1y")  # ← SourceRateLimitError: [yahoo] ...
# You're blocked. No automatic fallback.
```

**With xFinance:**
```python
import xfinance as xf
t = xf.Ticker("AAPL")
df = t.history(period="1y")  # ← Returns data from Stooq if Yahoo is throttled
# Silent fallback. Works every time.
```

## Caching

Each `Ticker` instance has a 5-minute in-memory cache:
```python
t = xf.Ticker("AAPL")
df1 = t.history(period="1y")  # Network call, cached
df2 = t.history(period="1y")  # Cache hit, instant

# Create a new Ticker instance = new cache
t2 = xf.Ticker("AAPL")
df3 = t2.history(period="1y")  # Network call (separate cache)
```

## Comparison with yfinance

| Feature | yfinance | xfinance |
|---|---|---|
| Single ticker | `yf.Ticker("AAPL").history()` | `xf.Ticker("AAPL").history()` |
| Multi-ticker (concurrent) | `yf.download(["A", "B", "C"])` | `xf.download(["A", "B", "C"])` |
| Failover on error | None | Yahoo → Stooq → SEC → ECB → Binance → CoinGecko |
| Rate limit handling | Crashes | Automatic fallback |
| Cache | None | Per-instance, 5-minute TTL |
| Extra sources | None | 5 alternatives + plugin architecture |

## Terms of service compliance

Users are responsible for complying with each data provider's ToS:

- **Yahoo Finance:** Unofficial API. Use for personal research only; respect rate limits.
- **Stooq:** Free historical data. Respect fair-use guidelines.
- **SEC EDGAR:** Public domain (U.S. government). No restrictions.
- **ECB:** Public data. Credit appreciated, not required.
- **Binance:** Free public API. See [terms](https://www.binance.com/en/terms).
- **CoinGecko:** Free tier has 30 req/min limit. See [free tier rules](https://www.coingecko.com/api/terms).

## Community plugins

xFinance supports custom data sources via Python entry points. Create a class implementing the `DataSource` protocol in under 100 lines:

```python
# my_source.py
from xfinance.sources.base import DataSource, PricesParams
from xfinance.models.source import DataSourceMeta, SupportedDataType

class MySource(DataSource):
    meta = DataSourceMeta(
        name="mysource",
        supported_types=[SupportedDataType.PRICES, SupportedDataType.INFO],
        rate_limit_per_minute=1000,
        risk_tier="low",
    )
    
    def supports(self, data_type, symbol):
        return data_type in self.meta.supported_types
    
    async def fetch_prices(self, params, *, client):
        # Your implementation
        pass
    
    async def fetch_info(self, symbol, *, client):
        # Your implementation
        pass
    
    async def health_check(self, *, client):
        return True
```

Register in `pyproject.toml`:
```toml
[project.entry-points."xfinance.sources"]
mysource = "my_source:MySource"
```

Install and use:
```bash
pip install my-source-package
```

The router will automatically discover and use your source.

## License

Apache 2.0
