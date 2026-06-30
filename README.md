# Jenneson Climate-Finance Trading & Risk Platform

English U.S.-listed climate-finance research cockpit inspired by the earlier China trading dashboard, but rebuilt for the U.S. market system.

## What It Does

- U.S.-listed sector ETF allocation dashboard
- Daily climate-alert overlay that moves current ETF allocation from NWS active weather alerts
- Climate signal from temperature anomaly and weather disaster frequency proxies
- Climate-aware vs equal-weight ETF backtest
- Portfolio CVOR scenario matrix
- Company-level issuer scanner for market CVaR and climate value-at-risk components
- U.S. listed company search from NasdaqTrader listings
- Method 2 Climate VaR approximation for each queried issuer
- BAU vs 2C mitigation comparison for issuer-level Method 2 CVOR
- Data quality labels explaining when market cap, sector, beta, or growth data are inferred
- Current U.S. stock and ETF quote board
- Professional TradingView-style K-line chart with high-DPI candles, crosshair OHLC readout, volume, MA20, EMA50, VWAP, Bollinger Bands, RSI/MACD, fit, dark mode, and PNG snapshot export
- Rolling K-line chart with a Today 1-minute intraday mode plus 5D, 1M, 3M, 6M, 1Y, and 2Y windows
- Faster market refresh for the intraday K-line view
- ETF watchlist across core index, sector, rates/credit, climate/clean energy, and commodities
- Portfolio optimizer with ETF-only, ETF + stock, and stock-only construction modes
- Optimizer controls for capital size, short-term vs long-term holding period, and style selection
- Optimizer output with target weight, target dollars, estimated shares, market score, climate score, and action
- Official climate data inputs from NASA GISTEMP, NOAA GML CO2, and NOAA NCEI billion-dollar disaster events
- Current climate data panel combining daily NWS alerts with official NASA/NOAA/NCEI inputs
- Dedicated daily climate intelligence board linking current alerts to related stocks, ETF recommendations, and daily reminders
- Stock and ETF climate-relevance scoring from NWS alert type, alert intensity, market momentum, and climate exposure mapping
- Auto-refreshing market and climate allocation views for a cleaner investor cockpit
- Left-side section navigation for a China-platform-like trading cockpit workflow
- Market and issuer CVOR heat strips for faster visual scanning
- High-DPI chart rendering, responsive tables, and desktop/mobile layout scaling
- Plain-English client explanation panel

## U.S. Market Assumptions

- Uses U.S. tickers, sector ETFs, and USD portfolio sizing
- Does not use China A-share boards, daily price limits, 100-share lot rules, or China resale constraints
- Supports single-share/fractional-share style allocation logic
- Research prototype only; not live investment advice

## Method 2 Alignment

The issuer CVOR scanner follows the logic of Dietz, Bowen, Dixon and Gradwell (2016), "Climate value at risk of global financial assets":

- Compare the present value of a no-climate-damage cash-flow path with a climate-damaged path
- Express Climate VaR as the PV loss divided by the no-damage PV
- Use private-investor discounting rather than social discounting
- Use a DICE-style damage function: `g(T)=0.0028*T^2+(alpha3*T)^7`
- Sample uncertainty in productivity growth, climate sensitivity, and damage curvature
- Report mean, P95, P99, and CVOR95 tail expected loss for each issuer
- Report how much a 2C pathway reduces issuer P95/CVOR95 climate-impact risk
- Use current official climate inputs to set the current warming level and climate pressure multiplier

This is still a company-level approximation because true Method 2 DICE runs are global and require full IAM scenario paths. The platform maps the global method to U.S. issuers through sector sensitivity, beta, market capitalization, and available growth data.

## Portfolio Optimizer

The optimizer is designed for an asset-investor workflow:

- `ETF only`: builds diversified exposure from ETFs only
- `ETF + stock`: uses ETFs as the core sleeve and single stocks as satellite positions
- `Stock only`: allocates only across selected U.S.-listed companies
- `Short-term`: uses today's 1-minute intraday bars, momentum, volatility, liquidity, and the current climate alert overlay
- `Long-term`: uses recent daily trend, structural climate resilience, and Method 2 issuer CVOR
- `Balanced`: mixes market trend, climate score, and volatility control
- `Climate defense`: gives more weight to lower Climate VaR and resilient sectors
- `Growth`: gives more weight to market momentum and single-name upside
- `Low volatility`: reduces high-volatility and high-tail-risk exposure

For each asset, the optimizer estimates a score from market behavior, climate risk, and volatility, then converts it into a portfolio weight. It multiplies the weight by the selected capital amount to show target dollars and estimated shares.

## Climate Data Sources

- NASA GISTEMP land-ocean annual temperature anomaly CSV
- NOAA Global Monitoring Laboratory Mauna Loa monthly CO2 CSV
- NOAA National Centers for Environmental Information billion-dollar weather and climate disaster event JSON

The app caches official climate data locally under `data/official_climate_data_cache.json` and falls back to built-in proxy values if an external source is unavailable.

## Install

```powershell
pip install -r requirements.txt
```

`yfinance`, `pandas`, and `numpy` are optional but recommended. If market data is unavailable, the app falls back to deterministic simulated returns so the dashboard still runs.

## Run

```powershell
python app.py
```

Then open:

```text
http://127.0.0.1:8865
```
