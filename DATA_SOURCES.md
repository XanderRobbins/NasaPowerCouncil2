# Data Sources

xfinance fetches financial data from the following sources on behalf of users.
Users are responsible for complying with each source's terms of service.

## Risk Tiers

| Tier | Description |
|---|---|
| **1** | Government / institutional data — no copyright, freely redistributable |
| **2** | Official API with free tier — requires user agreement, may need API key |
| **3** | Unofficial/scraped — gray area; use at your own risk |

---

## Tier 1 — Government & Institutional Data (Safest)

### SEC EDGAR

- **URL**: https://data.sec.gov
- **Data**: Financial statements (income statement, balance sheet, cash flow),
  SEC filings, XBRL data for all SEC-registered companies
- **Auth**: None required
- **Rate limit**: 10 requests/second
- **Legal**: US government works are not copyrightable under
  [17 U.S.C. § 105](https://www.law.cornell.edu/uscode/text/17/105).
  SEC explicitly provides this API for programmatic access.
- **ToS**: https://www.sec.gov/privacy.htm
- **Redistribution**: Safe — government data

### ECB / Frankfurter

- **URL**: https://api.frankfurter.app (wraps ECB official feeds)
- **Data**: Exchange rates for 150+ currencies, updated daily at 16:00 CET
- **Auth**: None required
- **Rate limit**: None documented
- **Legal**: ECB exchange rate data is provided under open data principles
- **ToS**: https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html
- **Redistribution**: Generally safe

---

## Tier 2 — Official APIs with Free Tiers

### Binance Public API

- **URL**: https://api.binance.com
- **Data**: Crypto OHLCV for 2,000+ pairs, order books, trades
- **Auth**: None required for public endpoints
- **Rate limit**: 1200 requests/minute (weight-based)
- **ToS**: https://www.binance.com/en/terms
- **Note**: Commercial redistribution of API data requires enterprise agreement.
  xfinance fetches data on behalf of users only.

### CoinGecko

- **URL**: https://api.coingecko.com/api/v3
- **Data**: Market data for 14,000+ coins, info, categories
- **Auth**: None (free tier)
- **Rate limit**: 30 calls/minute (free tier)
- **ToS**: https://www.coingecko.com/en/terms
- **Note**: CoinGecko prohibits commercial redistribution without an enterprise
  agreement. xfinance accesses data on behalf of individual users.

### Finnhub *(not built-in, add via plugin or API key config)*

- **URL**: https://finnhub.io
- **Data**: Real-time US stocks, crypto, forex, company fundamentals
- **Auth**: Free API key required (https://finnhub.io/register)
- **Rate limit**: 60 calls/minute (free tier)
- **ToS**: https://finnhub.io/terms-of-service

### Alpha Vantage *(not built-in, add via plugin or API key config)*

- **URL**: https://www.alphavantage.co
- **Data**: Stocks, forex, crypto, 50+ technical indicators
- **Auth**: Free API key required
- **Rate limit**: 25 requests/day (free tier)
- **ToS**: https://www.alphavantage.co/terms_of_service/
- **Note**: Data licensed from NASDAQ; not for redistribution.

---

## Tier 3 — Unofficial / Scraped (Use with Caution)

### Yahoo Finance

- **URL**: https://query1.finance.yahoo.com (unofficial)
- **Data**: Prices, options chains, fundamentals for global stocks,
  ETFs, indices, crypto, forex
- **Auth**: None (session cookie + crumb token, auto-obtained)
- **Rate limit**: ~950 tickers/session before IP blocks (as of 2024)
- **ToS**: https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html
- **Legal status**: Yahoo's ToS prohibits automated access. However,
  the Ninth Circuit in *hiQ v. LinkedIn* (reaffirmed April 2022) held
  that scraping publicly accessible data does not violate the CFAA.
  Breach-of-contract risk exists but no enforcement action has been
  taken against open-source financial data tools.
- **Cloud hosting**: Datacenter IPs (AWS, GCP) are frequently blocked.
  Rate limiting tightened significantly in November 2024.
- **Redistribution**: Do NOT redistribute data obtained from Yahoo Finance.

---

## FRED (Federal Reserve Economic Data)

Not included — FRED's [2024 ToS](https://fred.stlouisfed.org/docs/api/terms_of_use.html)
prohibits caching and redistribution. Each user must access FRED directly with
their own API key (https://fred.stlouisfed.org/docs/api/api_key.html).

---

## Adding More Sources

Any source can be added as a community plugin by implementing the
`DataSource` protocol and registering via Python entry points:

```toml
[project.entry-points."xfinance.sources"]
my_source = "my_source_package:MySource"
```

See the source code in `src/xfinance/sources/base.py` for the protocol definition.
A new adapter typically requires fewer than 100 lines of code.

---

## Disclaimer

xfinance is a **client library** that fetches data on behalf of users.
It does not store, redistribute, or re-publish financial data.
Users are solely responsible for ensuring their use complies with
each data provider's terms of service, applicable laws, and exchange
data licensing requirements.

Data obtained via xfinance should not be used for commercial purposes
without independently verifying that your use case complies with each
provider's terms.
