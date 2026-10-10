# Papertrade

A small paper trading venue for practicing with real historical stock prices. Place a trade for any trading day in the last 30 days, then follow account value, cash, positions, and recent activity on one uncluttered dashboard.

> This is a learning project. Trades are simulated; no real orders or money are involved. Market data can be delayed and the Yahoo Finance chart endpoint is an unofficial, rate-limited source.

## Features

- Account equity chart covering the past 30 days.
- Buy or sell fractional shares, filled at the selected date's market close.
- Historical trade validation prevents negative cash or share balances.
- Current portfolio values and a trade ledger persist between visits.
- Yahoo Finance historical market prices are cached in the database.
- Tiger Cloud PostgreSQL storage via `DATABASE_URL`; local SQLite fallback for a quick preview.
- Periodic dashboard refresh while the page is open.

## Run locally

Requires Python 3.10 or newer.

```bash
git clone <your-repository-url>
cd papertrade
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open [http://localhost:5000](http://localhost:5000). With `DATABASE_URL` unset, the app creates `paper_trading.db` in the project directory. This mode is intended for an individual local preview; the SQLite file must be retained to keep the account between restarts.

## Connect Tiger Cloud

1. Create a PostgreSQL service in [Tiger Cloud](https://console.tigerdata.com/).
2. Copy its PostgreSQL connection string from the service's **Connect** panel.
3. Put the string in `.env` as `DATABASE_URL`. Keep the password private and do not commit `.env`.
4. Ensure the URL includes `sslmode=require` (Tiger Cloud requires TLS).
5. Start the app. It creates its small `account`, `trades`, and `prices` tables automatically on startup.

The same `DATABASE_URL` setting works for deployment. Use a persistent Tiger Cloud service and keep its credentials in the hosting provider's secret/environment-variable settings. A production deployment should run behind a WSGI server, for example:

```bash
gunicorn app:app
```

The database URL is the standard PostgreSQL URL accepted by psycopg 3, for example `postgresql://user:password@host:port/database?sslmode=require`.

## Market data and dates

The app fetches daily candles from Yahoo Finance's chart endpoint without an API key. This makes a hackathon setup quick, but that endpoint is unofficial and may throttle or change. Prices are not guaranteed to be real time. The quote shown is the latest available daily close. A historical order is filled at the close on the chosen date; on weekends or exchange holidays, the most recent prior trading day's close is used. The selected date must be within the past 30 calendar days.

Dashboard refreshes automatically every 60 seconds while open. Historical equity values are rebuilt from the trade ledger and cached daily closes; revisiting the page recalculates the account using newly available market prices.

## Account model

This compact hackathon starter runs one paper account per deployment/database. Anyone using the same deployed instance shares that account and its trade history. Add authentication and user-scoped account IDs before using it as a multi-user public service.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | empty | Tiger Cloud PostgreSQL URL; empty selects SQLite |
| `SQLITE_PATH` | `paper_trading.db` | Local SQLite database file |
| `INITIAL_CASH` | `100000` | Starting paper cash when the database is first initialized |
| `PORT` | `5000` | Flask development server port |
| `FLASK_DEBUG` | unset | Set to `1` for local Flask debugging only |

## Project layout

```text
app.py                 Flask routes, market data, trade ledger and valuation
templates/index.html   Dashboard structure
static/styles.css      Responsive dark interface
static/app.js          Chart, quote lookup, forms and live refresh
```
