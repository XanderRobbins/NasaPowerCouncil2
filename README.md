# xFinance

A Python financial data library with automatic multi-source failover.

xFinance wraps Yahoo Finance's API with the same interface you already know, but falls back transparently to Stooq, SEC EDGAR, ECB, Binance, and CoinGecko when Yahoo is rate-limited or unavailable. No code changes, no API keys needed.

## Quick start

```python
import xfinance as xf

t = xf.Ticker("AAPL")
print(t.history(period="1y"))
print(t.info)
print(t.income_stmt)

# Concurrent multi-symbol download
df = xf.download(["AAPL", "MSFT", "GOOGL"], period="1y")
print(df["Close"])
```

## Installation

```bash
pip install xfinance
```

Requires Python 3.10+. Dependencies: httpx, pandas, pydantic, pybreaker, tenacity.

## Data sources

Sources are tried in priority order. If a source doesn't support the requested data type, or returns an error, the next one is tried automatically.

| Source | Prices | Info | Forex | Crypto | Fundamentals | Options |
|---|---|---|---|---|---|---|
| **Yahoo Finance** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Stooq** | ✓ | — | ✓ | — | — | — |
| **SEC EDGAR** | — | ✓ | — | — | ✓ | — |
| **ECB Frankfurter** | — | — | ✓ | — | — | — |
| **Binance** | ✓ | ✓ | — | ✓ | — | — |
| **CoinGecko** | ✓ | ✓ | — | ✓ | — | — |

All sources are public or free-tier — no API keys required.

**Circuit breaker:** After 5 consecutive failures, a source is skipped for 60 seconds.

## API reference

### `xf.Ticker(symbol)`

All properties are lazy — fetched on first access, cached for 5 minutes.

**Properties:**
- `history(period="1mo", interval="1d", start=None, end=None, **kwargs)` — OHLCV DataFrame (UTC index)
- `dividends`, `splits`, `actions` — historical corporate actions
- `info` — company metadata dict (200+ fields)
- `income_stmt`, `balance_sheet`, `cashflow` — annual financial statements
- `income_stmt_quarterly`, `balance_sheet_quarterly`, `cashflow_quarterly`
- `option_chain(expiry_date)` — NamedTuple with `calls` and `puts` DataFrames
- `options` — available expiry dates
- `calendar`, `earnings_dates`
- `recommendations`, `analyst_price_targets`
- `institutional_holders`, `major_holders`, `insider_transactions`
- `sustainability`, `news`
- `fast_info` — quick access wrapper (`t.fast_info.market_cap`, `t.fast_info["marketCap"]`)

**Methods:**
- `sec_financials(concept, taxonomy)` — audited XBRL data from SEC EDGAR
- `get_shares_full()` — historical share count from 10-K/10-Q filings

### `xf.Tickers(symbols)`

```python
tickers = xf.Tickers(["AAPL", "MSFT", "GOOGL"])
tickers.history(period="6mo")   # dict of per-ticker DataFrames
tickers.download(period="6mo")  # concurrent, single MultiIndex DataFrame
```

### `xf.download(symbols, period, interval, ...)`

Concurrent multi-symbol download, yfinance-compatible signature.

| Parameter | Default | Description |
|---|---|---|
| `symbols` | — | list of ticker symbols |
| `period` / `interval` / `start` / `end` | — | date range |
| `group_by` | `"price"` | `"price"` or `"ticker"` column ordering |
| `auto_adjust` | `True` | adjust OHLC for splits and dividends |
| `actions` | `True` | include Dividends/Stock Splits columns |
| `keepna` | `False` | keep all-NaN rows |
| `na_fill` | `None` | `None`, `"ffill"`, `"bfill"`, or scalar |
| `repair` | `False` | fix 100× unit errors and split-unadjusted bars |
| `rounding` | `False` | round prices to 2 decimal places |

Returns a MultiIndex DataFrame with DatetimeIndex (UTC).

## Plugins

Custom sources can be added via Python entry points. Implement the `DataSource` protocol (see `src/xfinance/sources/base.py`) and register in `pyproject.toml`:

```toml
[project.entry-points."xfinance.sources"]
mysource = "my_source:MySource"
```

The router discovers and uses registered sources automatically.

## Terms of service

Users are responsible for complying with each provider's ToS:

- **Yahoo Finance:** Unofficial API. Personal research only; do not redistribute data.
- **Stooq:** Free historical data. Respect fair-use guidelines.
- **SEC EDGAR:** U.S. government data, public domain.
- **ECB / Frankfurter:** Public data.
- **Binance:** Commercial redistribution requires enterprise agreement.
- **CoinGecko:** Free tier: 30 req/min. Commercial redistribution requires enterprise agreement.

## License

Apache 2.0
