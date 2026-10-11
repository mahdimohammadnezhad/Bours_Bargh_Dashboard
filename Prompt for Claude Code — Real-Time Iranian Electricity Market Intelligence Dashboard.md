# Build a Production-Grade Real-Time Iranian Electricity Market Intelligence Dashboard

You are a senior full-stack engineer, data engineer, quantitative analyst, and financial/energy-market software architect.

I want you to build a **production-grade real-time electricity market intelligence dashboard for Iran**.

The objective is NOT to create a simple visualization dashboard.

The objective is to build a system that continuously collects electricity-market data from Iranian market sources, stores historical data, analyzes market behavior, detects important patterns and anomalies, and provides actionable decision-support insights to the user.

The application should be designed so that it can later evolve into a serious electricity-market analytics platform.

---

# 1. Primary Data Sources

Investigate these sources thoroughly before implementing the collectors.

## Source 1 — TSETMC

Main website:

https://tsetmc.ir/

The relevant section is:

**Energy Exchange → Electricity**

The website provides near-real-time market information.

IMPORTANT:

Do NOT blindly scrape the visible HTML page.

First investigate the website architecture and identify:

- underlying API endpoints
- XHR/fetch requests
- JSON endpoints
- Web/API endpoints
- market-watch endpoints
- instrument/stock identifiers
- order-book endpoints
- transaction endpoints
- historical endpoints
- any endpoints specifically related to the electricity/energy exchange

Use browser/network inspection techniques where necessary.

Determine exactly how TSETMC obtains the data displayed on its frontend.

Prefer official/publicly exposed data endpoints over HTML scraping.

Investigate whether the following information is available:

- current electricity market instruments
- last price
- closing price
- price change
- percentage change
- traded volume
- traded value
- number of transactions
- bid/ask
- order book depth
- buy/sell quantities
- market status
- transaction history
- instrument metadata
- historical prices
- historical transactions
- electricity-market-specific information
- previous trading sessions
- any other useful information that is not directly visible on the initial page

Do not assume that the visible website contains all useful information.

---

# 2. Iranian Electricity Exchange / IEE

New website:

https://newsite.iee.ir/Market/PowerMarket/Statistics

Old website:

https://oldsite.iee.ir/PowerMarket/Statistics/Power

Investigate both websites.

The new website appears to be JavaScript-driven, so identify the underlying APIs/data services instead of relying only on HTML scraping.

Investigate:

- network requests
- API endpoints
- JSON responses
- historical statistics
- market statistics
- electricity trading information
- market volume
- prices
- supply/demand
- transaction counts
- market segmentation
- daily/monthly/yearly statistics
- historical records
- downloadable datasets
- hidden API endpoints
- legacy endpoints available on the old website

Compare the old and new systems.

If the old website exposes useful historical data that is unavailable or difficult to obtain from the new website, implement it as a secondary historical data source.

---

# 3. Important Principle: Data Discovery First

Before writing the final application, perform a proper data-source investigation.

Create:

`docs/DATA_SOURCES.md`

Document for every source:

- URL
- endpoint
- HTTP method
- required parameters
- response format
- important fields
- update frequency
- historical availability
- authentication requirements
- rate-limit behavior
- reliability
- whether the endpoint is public
- sample response
- data normalization requirements

Do NOT invent endpoints.

If an endpoint cannot be confirmed, mark it as:

`UNVERIFIED`

and continue investigating.

---

# 4. Recommended Architecture

Do NOT build the entire application as one Streamlit script.

Use a production-oriented architecture:

## Backend

Python + FastAPI

Responsibilities:

- REST API
- WebSocket API
- authentication-ready architecture
- analytics API
- dashboard API
- health checks
- data-source status
- configuration
- system monitoring

## Frontend

Prefer:

- Next.js
- React
- TypeScript
- Tailwind CSS
- a professional charting library

The frontend should behave like a modern financial/energy trading dashboard.

## Data Collection

Create independent asynchronous collectors.

Example:

`TSETMCCollector`

`IEENewCollector`

`IEEOldCollector`

Each collector should:

- fetch data
- validate responses
- normalize fields
- detect failures
- retry intelligently
- respect rate limits
- store timestamps
- expose collector health
- avoid duplicate requests

---

# 5. Real-Time Data Architecture

This is extremely important.

DO NOT implement:

frontend → TSETMC request every second

Instead implement:

TSETMC
↓
Data Collector
↓
Redis / in-memory cache
↓
Database
↓
FastAPI
↓
WebSocket
↓
Frontend

The frontend must NOT directly scrape external websites.

Only the backend collectors communicate with external sources.

---

# 6. Polling Strategy

The user wants near-real-time information.

However, do NOT blindly request the external source every second if it is unnecessary.

Implement an adaptive polling system.

For example:

During active market hours:

- poll the relevant real-time endpoint at the highest safe frequency supported by the source

During inactive periods:

- dramatically reduce polling frequency

If the endpoint supports incremental updates:

- retrieve only new records

If a timestamp / sequence number exists:

- use incremental synchronization

If nothing has changed:

- do not repeatedly store identical records

Implement:

- exponential backoff
- jitter
- timeout
- circuit breaker
- retry policy
- HTTP 429 handling
- HTTP 403 handling
- connection error handling
- stale-data detection

Respect the source's terms, robots policy, and reasonable request limits.

Never attempt to bypass access controls.

---

# 7. DO NOT Use IP Rotation as the Primary Strategy

Do NOT design the system around rotating proxy IPs or Cloudflare IPs to avoid bans.

Instead use:

1. Correct underlying API endpoints
2. Minimal requests
3. Centralized collector
4. Caching
5. Incremental updates
6. Adaptive polling
7. Exponential backoff
8. Request deduplication
9. Connection reuse
10. Proper User-Agent
11. Respectful rate limiting

If a source returns:

429

then immediately activate backoff.

If repeated 403/429 responses occur:

- stop aggressive polling
- mark source as degraded
- increase polling interval
- log the event
- continue using cached data

The dashboard should never crash because one external source is unavailable.

---

# 8. Database

Use PostgreSQL.

Prefer TimescaleDB if practical because the project is fundamentally time-series oriented.

Design normalized tables such as:

`data_sources`

`instruments`

`market_sessions`

`market_quotes`

`order_book_snapshots`

`transactions`

`market_statistics`

`electricity_market_statistics`

`historical_prices`

`historical_volumes`

`market_signals`

`anomalies`

`analytics_results`

`collector_logs`

`system_health`

Every time-series record must contain:

- timestamp
- source
- instrument/source identifier
- value
- ingestion timestamp

Use appropriate indexes and hypertables where useful.

---

# 9. Historical Data

Build a historical ingestion pipeline.

The system should automatically retrieve and normalize historical information from:

- TSETMC
- new IEE
- old IEE

Avoid duplicate records.

Create a unique strategy based on:

- source
- instrument
- date/time
- transaction ID where available

If historical records from multiple sources represent the same event, preserve the original source and also create a normalized representation.

---

# 10. Dashboard Design

Create a professional dark/light financial analytics interface.

The dashboard should NOT look like a generic Streamlit data app.

It should look closer to:

- Bloomberg-style analytical dashboards
- professional energy-market monitoring systems
- modern quantitative trading platforms

Main sections:

## Overview

Display:

- current market status
- latest electricity prices
- market volume
- traded value
- transaction count
- supply/demand indicators
- latest update timestamp
- data-source health
- real-time alerts

---

# 11. Real-Time Market Monitor

Create a dedicated real-time screen.

Display:

- live prices
- percentage changes
- volume
- traded value
- transaction count
- order-book information
- bid/ask
- market depth
- price movement
- latest transactions

Use:

- live updating tables
- sparklines
- real-time charts
- color-coded changes
- update timestamps

Use WebSockets instead of repeatedly refreshing the entire page.

---

# 12. Electricity Market Analytics

Create advanced analytical modules.

At minimum calculate:

### Price analytics

- mean
- median
- minimum
- maximum
- standard deviation
- coefficient of variation
- percentile distribution
- rolling mean
- rolling volatility

### Volume analytics

- daily volume
- weekly volume
- monthly volume
- rolling volume
- volume anomalies

### Price-volume relationships

Analyze:

- price vs volume
- price vs transaction count
- price momentum
- volume momentum

---

# 13. Historical Analysis

Allow users to select:

- date range
- market
- instrument
- electricity market segment

Display:

- price time series
- volume time series
- transaction counts
- price distribution
- rolling statistics
- seasonal patterns
- weekday effects
- monthly patterns
- year-over-year comparisons

Allow interactive zooming and filtering.

---

# 14. Market Regime Detection

Implement analytical logic to identify market regimes.

Examples:

- high-price regime
- low-price regime
- high-volatility regime
- high-volume regime
- abnormal-price regime
- supply-constrained regime if sufficient data exists

Do not claim causality without evidence.

Clearly distinguish:

`Observed`

from:

`Model-derived`

from:

`Interpretation`

---

# 15. Anomaly Detection

Implement multiple anomaly detection approaches.

At minimum:

- rolling z-score
- IQR
- robust z-score
- percentile-based detection

Optionally:

- Isolation Forest
- Local Outlier Factor

Detect:

- abnormal prices
- abnormal volumes
- abnormal transaction frequency
- unusual price-volume combinations

Every anomaly should have:

- timestamp
- severity
- metric
- observed value
- expected range
- explanation
- source

---

# 16. Decision Support

This is one of the most important parts of the project.

The system should not merely display charts.

It should provide useful decision-support insights.

For example:

"Current price is in the 92nd percentile of the last 12 months."

"Current trading volume is 1.8 standard deviations above its 30-day average."

"Price increased while volume decreased, indicating weak confirmation of the recent movement."

These statements must be generated from actual calculations.

Do NOT fabricate insights.

---

# 17. Historical Pattern Matching

Build a historical analog engine.

When current market conditions are unusual, search historical records for similar conditions.

Example feature vector:

- current price percentile
- recent price momentum
- volatility
- volume percentile
- transaction count
- time of day
- day of week
- recent trend

Find historically similar observations.

Then show:

### Historical Analogues

- Similar date
- Similarity score
- Market condition
- What happened afterward
- 1-hour outcome
- 1-day outcome
- 1-week outcome where applicable

This should be presented as historical evidence, NOT guaranteed prediction.

---

# 18. Scenario / What-If Analysis

Add a module where users can change assumptions.

For example:

- price increase/decrease
- volume increase/decrease
- volatility
- demand proxy
- supply proxy

Show possible consequences based on historical relationships.

Clearly label this:

`Scenario Analysis`

and not as a guaranteed forecast.

---

# 19. Forecasting

If sufficient historical data exists, implement forecasting models.

Start simple.

Baseline models:

- naive forecast
- moving average
- exponential smoothing
- ARIMA/SARIMA where appropriate

Then optionally:

- XGBoost
- LightGBM
- Random Forest
- temporal neural networks

Do not introduce complicated ML unless it demonstrably improves validation performance.

Use proper time-series validation.

Never use random train/test splitting for time-series forecasting.

Report:

- MAE
- RMSE
- MAPE where appropriate
- directional accuracy
- confidence intervals if available

---

# 20. Recommendation Engine

Create a recommendation engine that translates analytics into understandable actions.

For example:

### Market Condition

`High volatility + unusually high price + weak volume confirmation`

### Historical Evidence

`Similar historical conditions occurred 17 times.`

### Historical Outcome

`12/17 observations were followed by price declines within the next session.`

### Signal

`Caution`

### Confidence

`71%`

Important:

Do not present these as financial guarantees.

Every recommendation must show the evidence behind it.

---

# 21. Explainability

Every analytical recommendation should have a "Why?" section.

For example:

**Why is this flagged?**

- Price percentile: 94%
- 30-day volatility: +2.1σ
- Volume percentile: 38%
- Historical analogues: 23
- Historical directional consistency: 74%

This is extremely important for user trust.

---

# 22. Alert System

Create alerts for:

- unusual price movement
- unusual volume
- price threshold
- volatility threshold
- data-source failure
- stale data
- market opening
- market closing
- unusual order-book imbalance

Support:

- dashboard notifications
- optional Telegram notifications
- optional email notifications

Design notifications so they do not spam the user.

Implement cooldown periods.

---

# 23. Data Quality Monitoring

Create a dedicated Data Health page.

Display:

- source status
- last successful request
- response latency
- last data timestamp
- stale-data duration
- number of errors
- number of retries
- HTTP status distribution

Example:

TSETMC

`● Healthy`

Last update:

`14:32:17`

Latency:

`184 ms`

IEE:

`● Healthy`

Last update:

`14:31:59`

---

# 24. Caching

Use Redis.

Cache:

- latest market data
- instrument metadata
- recent transactions
- frequently requested historical aggregates
- analytical results

Use TTL intelligently.

Never cache data so aggressively that the real-time dashboard becomes stale.

---

# 25. WebSocket Architecture

Implement:

`/ws/market`

The backend should push only changed data to connected clients.

Do NOT send the entire dataset every second.

Implement:

- connection management
- heartbeat
- reconnect
- subscription model
- symbol-specific subscriptions where useful

---

# 26. API Design

Create clean FastAPI endpoints such as:

`GET /api/market/status`

`GET /api/market/overview`

`GET /api/market/instruments`

`GET /api/market/quotes`

`GET /api/market/transactions`

`GET /api/market/orderbook/{instrument_id}`

`GET /api/history/prices`

`GET /api/history/statistics`

`GET /api/analytics/overview`

`GET /api/analytics/anomalies`

`GET /api/analytics/patterns`

`GET /api/analytics/recommendations`

`GET /api/health/sources`

`WS /ws/market`

Use Pydantic schemas.

---

# 27. Project Structure

Use a clean structure similar to:

backend/

    app/
        api/
        collectors/
        analytics/
        models/
        schemas/
        services/
        database/
        cache/
        websocket/
        core/

    tests/

frontend/

    app/
    components/
    hooks/
    services/
    charts/
    pages/

scripts/

docs/

docker/

tests/

---

# 28. Configuration

Use environment variables.

Create:

`.env.example`

Possible variables:

DATABASE_URL

REDIS_URL

TSETMC_BASE_URL

IEE_NEW_BASE_URL

IEE_OLD_BASE_URL

POLL_INTERVAL

LOG_LEVEL

TELEGRAM_BOT_TOKEN

Do NOT hardcode credentials.

---

# 29. Logging

Implement structured logging.

Every collector should log:

- request start
- endpoint
- response time
- status code
- records received
- records inserted
- records skipped
- error
- retry
- backoff

Do not log sensitive credentials.

---

# 30. Error Handling

One source failing must NOT bring down the application.

For example:

If TSETMC fails:

- continue showing cached TSETMC data
- clearly display stale-data warning
- continue IEE collectors

If IEE fails:

- continue TSETMC

Implement circuit breakers.

---

# 31. Testing

Write tests for:

- collectors
- API parsing
- data normalization
- database operations
- analytics
- anomaly detection
- recommendation engine
- API endpoints
- WebSocket behavior

Create mocked responses for external sources.

Do not make tests dependent on live external websites.

---

# 32. Security

Implement basic production security:

- input validation
- CORS configuration
- rate limiting on our own API
- authentication-ready architecture
- secure environment variables
- no secrets in Git
- SQL injection protection
- dependency pinning

---

# 33. Docker

Create:

`Dockerfile`

`docker-compose.yml`

Services:

- backend
- frontend
- PostgreSQL/TimescaleDB
- Redis

The entire application should be runnable with:

`docker compose up`

---

# 34. Observability

Add:

- health endpoint
- collector health
- request latency
- database health
- Redis health
- source freshness
- error counters

If practical, expose Prometheus-compatible metrics.

---

# 35. UI Requirements

The UI must be highly polished.

Use:

- responsive design
- dark/light mode
- professional typography
- compact financial tables
- interactive charts
- sticky filters
- real-time indicators
- loading states
- skeleton states
- error states
- stale-data indicators

Avoid unnecessary visual decoration.

Prioritize information density and readability.

---

# 36. Main Dashboard Layout

Create approximately:

## Header

- Iranian Electricity Market
- market status
- last update
- connection status

## KPI Cards

- Current Price
- Price Change
- Market Volume
- Traded Value
- Transactions
- Volatility

## Main Chart

Interactive real-time price/volume chart.

## Market Depth

Bid/Ask visualization.

## Latest Transactions

Live transaction feed.

## Analytics Panel

- trend
- volatility
- anomaly
- market regime

## Decision Support

- current signal
- historical evidence
- confidence
- explanation

## Alerts

Latest important market events.

---

# 37. Historical Dashboard

Create tabs:

`Overview`

`Price`

`Volume`

`Transactions`

`Volatility`

`Patterns`

`Anomalies`

`Forecast`

`Recommendations`

---

# 38. Data Explorer

Create an advanced data explorer.

Allow users to:

- select source
- select market
- select instrument
- select date range
- select metrics

Allow CSV export.

---

# 39. Source Comparison

Create a page that compares data obtained from:

TSETMC

IEE New

IEE Old

Display:

- availability
- timestamps
- values
- discrepancies

If two sources report different values for the same metric, flag the discrepancy.

---

# 40. Important Data Engineering Requirement

Do not assume that every source has the same definition of:

- volume
- price
- transaction
- market session
- traded value

Create a canonical data model.

Document source-specific meanings.

Maintain:

`raw data`

and

`normalized data`

separately where practical.

This allows the system to be audited later.

---

# 41. Raw Data Storage

For important API responses, consider storing raw JSON responses.

Example:

`raw/source/date/hour/*.json`

or an equivalent database/object-storage strategy.

This is useful for:

- debugging
- reproducibility
- historical reconstruction
- parser changes

Do not store unnecessary duplicates indefinitely.

Implement retention policies.

---

# 42. Source Discovery Tools

During development, use:

- browser DevTools/network inspection
- requests/httpx
- Playwright only when necessary
- BeautifulSoup only for actual HTML data
- API inspection
- response schema analysis

Do not use browser automation if a stable JSON API exists.

---

# 43. Performance

The system must be able to support:

- continuous data collection
- multiple simultaneous dashboard users
- real-time updates
- historical queries
- analytical calculations

Do not run expensive analytics on every frontend request.

Precompute where appropriate.

Use background workers.

---

# 44. Background Workers

Consider:

Celery / Dramatiq / APScheduler / asyncio-based workers

Choose the simplest architecture that is reliable.

Do NOT introduce unnecessary infrastructure.

If asyncio + FastAPI background services are sufficient, use them.

If workload grows, make it easy to move collectors to dedicated workers.

---

# 45. Important: Start With an MVP

Do NOT try to implement every advanced feature before validating the data pipeline.

Implement in phases.

## Phase 1

- source discovery
- TSETMC collector
- IEE collector
- database
- real-time API
- WebSocket
- basic dashboard

## Phase 2

- historical ingestion
- analytics
- anomaly detection
- data explorer

## Phase 3

- historical analogues
- decision support
- forecasting
- recommendation engine

## Phase 4

- alerts
- monitoring
- optimization
- production hardening

---

# 46. Claude Code Workflow

Follow this exact workflow.

### Step 1

Inspect the current repository.

If an existing project exists, understand it before changing anything.

### Step 2

Investigate the external data sources.

Do not start by building the UI.

### Step 3

Create:

`docs/DATA_SOURCES.md`

and document discovered APIs/endpoints.

### Step 4

Design the architecture.

Create:

`docs/ARCHITECTURE.md`

### Step 5

Implement the minimum working data pipeline.

### Step 6

Test the collectors using real responses and mocked responses.

### Step 7

Implement the database.

### Step 8

Implement FastAPI.

### Step 9

Implement WebSocket real-time updates.

### Step 10

Implement frontend.

### Step 11

Implement analytics.

### Step 12

Implement anomaly detection and decision support.

### Step 13

Add tests.

### Step 14

Add Docker.

### Step 15

Run the complete system locally.

---

# 47. Very Important Development Rule

Before implementing any feature, verify whether the required data actually exists.

Do NOT create fake/mock production data and pretend it came from TSETMC or IEE.

Mock data may only be used inside automated tests.

---

# 48. Important Financial/Energy Analytics Rule

The system is a decision-support and market-intelligence tool.

It must NOT claim:

"this price will definitely increase"

or

"buy/sell this product with certainty."

Instead use language such as:

- bullish tendency
- bearish tendency
- elevated risk
- historical pattern
- anomaly detected
- caution
- favorable historical conditions
- unfavorable historical conditions

Every recommendation must show the evidence behind it.

---

# 49. Final Deliverables

At the end, provide:

1. Complete source code
2. `README.md`
3. `docs/DATA_SOURCES.md`
4. `docs/ARCHITECTURE.md`
5. `.env.example`
6. `Dockerfile`
7. `docker-compose.yml`
8. database migrations
9. tests
10. API documentation
11. setup instructions
12. deployment instructions
13. troubleshooting guide

---

# 50. Final Acceptance Criteria

The project is considered successful only if:

- TSETMC data can be collected automatically
- IEE data can be collected automatically
- historical data can be stored
- real-time data reaches the frontend without page refresh
- data-source failures are handled gracefully
- the database contains normalized time-series data
- historical analysis works
- anomalies are detected
- historical analogues can be found
- decision-support insights are generated from actual data
- users can understand WHY an insight was generated
- the application can run through Docker
- no credentials are hardcoded
- tests pass
- the system does not depend on IP rotation to function
- the system does not aggressively hammer external websites
- the architecture can later scale to additional electricity-market data sources

---

# Most Important Instruction

Think like a senior engineer building a real financial/energy-market intelligence product.

Do not rush into writing UI code.

First understand the data sources.

Then build a reliable data pipeline.

Then build the analytics layer.

Then build the dashboard.

The quality of this project depends much more on **correct real-time data acquisition, data engineering, historical storage, analytics, and decision-support logic** than on visual appearance.

When you encounter an unknown API or data structure, investigate it and document what you found instead of guessing.

Start by inspecting the repository and investigating the three data sources.