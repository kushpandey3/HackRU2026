# Paper Trading Venue

A Flask paper-trading app for tracking simulated stock trades with market prices. Each browser gets a separate portfolio with a $100,000 starting balance. Trades are simulated; the app does not place real orders or move real money.

## Features

- Search stocks by company name or ticker and view a quote with its 30-day change.
- Buy and sell fractional shares at the selected date's most recent market close.
- Track cash, holdings, total account value, recent trades, and 30-day account history.
- Keep portfolio trades in PostgreSQL between app restarts.
- Save daily market prices in PostgreSQL and briefly cache market responses for faster page interactions.

## Requirements

- Python 3.10 or later
- A PostgreSQL database and its connection URL
- Internet access for Yahoo Finance market data

## Run locally

From the project directory, create and activate a virtual environment, install dependencies, and copy the example environment file:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env             # Windows PowerShell: Copy-Item .env.example .env
```

Edit `.env` and set `DATABASE_URL` to your PostgreSQL connection URL. For example:

```dotenv
DATABASE_URL=postgresql://username:password@host:5432/database?sslmode=require
INITIAL_CASH=100000
PORT=5000
```

Start the app:

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000). On startup, the app creates the `portfolios`, `trades`, and `prices` tables if they do not already exist. Keep `.env` private; it contains database credentials.

## Database and portfolio persistence

`DATABASE_URL` is required; there is no SQLite fallback. Use the same persistent PostgreSQL database after restarting or redeploying the app to keep trade records.

The app identifies a portfolio using a signed browser cookie. Locally, it creates and stores a signing key in `instance/secret_key`, which is ignored by Git. Keep that file between local runs. When deploying, set a private, stable `SECRET_KEY` in the hosting environment and keep it the same across restarts and app instances. The browser cookie is persistent for up to ten years.

Portfolios are per browser profile, not per named login. Clearing the browser's cookies or using another browser creates a different portfolio. A deployed app that needs account access across devices requires authentication.

`INITIAL_CASH` is applied when a browser's portfolio is created; changing it later does not reset existing portfolios. Market price rows are shared reference data, while trades and starting cash are scoped to each portfolio.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Required | PostgreSQL connection URL; include `sslmode=require` when required by your provider. |
| `SECRET_KEY` | Local key file | Stable Flask session signing key. Set this in deployment and keep it private. |
| `INITIAL_CASH` | `100000` | Starting cash for each newly created portfolio. |
| `PORT` | `5000` | Port used by the local Flask server. |
| `FLASK_DEBUG` | Off | Set to `1` to enable Flask debug mode for local development only. |

## Market data and trade pricing

The app requests stock search and daily price data from Yahoo Finance endpoints without an API key. These endpoints are unofficial, may be delayed or rate-limited, and can change. The displayed quote is based on available daily close data. Trades are filled using the most recent prior market close on or before the chosen date, so weekends and market holidays use the previous trading day's close. Trade dates are limited to the past 30 calendar days.

## API routes

- `GET /api/dashboard` — portfolio balance, holdings, account history, and recent trades.
- `GET /api/symbol-search?q=...` — stock name and ticker suggestions.
- `GET /api/quote/<symbol>` — a stock quote and its recent price history.
- `POST /api/trades` — validates and records a buy or sell trade. Send JSON fields `symbol`, `side` (`buy` or `sell`), `quantity`, and `date` (`YYYY-MM-DD`).

## Production deployment

Set `DATABASE_URL` and a stable `SECRET_KEY` as private environment variables in the hosting provider. Use a persistent PostgreSQL database. Install the requirements and run the app behind a WSGI server such as Gunicorn:

```bash
gunicorn app:app
```

## Project layout

```text
app.py                 Flask routes, PostgreSQL access, pricing, and trade validation
templates/index.html   Dashboard markup
static/app.js          Stock search, quote display, chart, and trade form
static/styles.css      Dashboard styles
requirements.txt       Python dependencies
.env.example           Example local configuration
```
