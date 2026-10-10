import os
import re
import secrets
import time
import psycopg
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session

load_dotenv()
app = Flask(__name__)


def get_secret_key():
    """Use a configured signing key, or persist a generated local key across restarts."""
    configured_key = os.getenv("SECRET_KEY")
    if configured_key:
        return configured_key

    os.makedirs(app.instance_path, exist_ok=True)
    key_path = os.path.join(app.instance_path, "secret_key")
    try:
        file_descriptor = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(file_descriptor, "w") as key_file:
            key_file.write(secrets.token_hex(32))

    with open(key_path, encoding="utf-8") as key_file:
        return key_file.read().strip()


app.secret_key = get_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=3650),
)
DATABASE_URL = os.getenv("DATABASE_URL")
INITIAL_CASH = Decimal(os.getenv("INITIAL_CASH", "100000"))
SYMBOL_RE = re.compile(r"^[A-Z0-9.^=-]{1,15}$")
MARKET_CACHE_SECONDS = 60
market_cache = {}

def connect_db():
    return psycopg.connect(DATABASE_URL, connect_timeout=10)


def as_date(value):
    """Normalize PostgreSQL text, DATE, or timestamp values to a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


class Database:
    def create_portfolios_table(self):
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS portfolios (
                        id TEXT PRIMARY KEY,
                        initial_cash DOUBLE PRECISION NOT NULL
                    )
                """)

    def create_trades_table(self):
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        id TEXT PRIMARY KEY,
                        portfolio_id TEXT NOT NULL DEFAULT 'legacy',
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        quantity DOUBLE PRECISION NOT NULL,
                        price DOUBLE PRECISION NOT NULL,
                        traded_at TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                # Add the owner column when upgrading a database created by an older app.
                cursor.execute("""
                    ALTER TABLE trades
                    ADD COLUMN IF NOT EXISTS portfolio_id TEXT NOT NULL DEFAULT 'legacy'
                """)

    def create_prices_table(self):
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS prices (
                        symbol TEXT NOT NULL,
                        price_date TEXT NOT NULL,
                        close DOUBLE PRECISION NOT NULL,
                        PRIMARY KEY (symbol, price_date)
                    )
                """)

    def create_account_table(self):
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS account (
                        id INTEGER PRIMARY KEY,
                        initial_cash DOUBLE PRECISION NOT NULL
                    )
                """)

    def add_initial_cash(self):
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO account (id, initial_cash)
                    VALUES (1, %s)
                    ON CONFLICT (id) DO NOTHING
                """, (float(INITIAL_CASH),))

    def initialize(self):
        self.create_portfolios_table()
        self.create_trades_table()
        self.create_prices_table()

    def ensure_portfolio(self, portfolio_id):
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO portfolios (id, initial_cash)
                    VALUES (%s, %s)
                    ON CONFLICT (id) DO NOTHING
                """, (portfolio_id, float(INITIAL_CASH)))

    def save_prices(self, symbol, rows):
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.executemany("""
                    INSERT INTO prices (symbol, price_date, close)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (symbol, price_date)
                    DO UPDATE SET close = EXCLUDED.close
                """, [(symbol, day, close) for day, close in rows])

    def get_trades(self, portfolio_id):
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, symbol, side, quantity, price, traded_at
                    FROM trades
                    WHERE portfolio_id = %s
                    ORDER BY traded_at, created_at
                """, (portfolio_id,))
                rows = cursor.fetchall()
        trades = [dict(id=row[0], symbol=row[1], side=row[2], quantity=Decimal(str(row[3])),
                       price=Decimal(str(row[4])), traded_at=as_date(row[5])) for row in rows]
        return trades

    def get_initial_cash(self, portfolio_id):
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT initial_cash FROM portfolios WHERE id = %s", (portfolio_id,))
                row = cursor.fetchone()
        return Decimal(str(row[0]))

    def get_latest_price(self, symbol):
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT close
                    FROM prices
                    WHERE symbol = %s
                    ORDER BY price_date DESC
                    LIMIT 1
                """, (symbol,))
                row = cursor.fetchone()
        return Decimal(str(row[0])) if row else None

    def get_price_history(self, symbol, start_date):
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT price_date, close
                    FROM prices
                    WHERE symbol = %s AND price_date >= %s
                    ORDER BY price_date
                """, (symbol, start_date))
                rows = cursor.fetchall()
        return {as_date(row[0]): Decimal(str(row[1])) for row in rows}

    def insert_trade(self, portfolio_id, trade_id, symbol, side, quantity, price, traded_at, created_at):
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO trades (id, portfolio_id, symbol, side, quantity, price, traded_at, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (trade_id, portfolio_id, symbol, side, quantity, price, traded_at, created_at))


database = Database()
database.initialize()


@app.before_request
def assign_portfolio():
    if request.endpoint == "static":
        return
    session.permanent = True
    portfolio_id = session.get("portfolio_id")
    if not portfolio_id:
        import uuid
        portfolio_id = uuid.uuid4().hex
        session["portfolio_id"] = portfolio_id
    database.ensure_portfolio(portfolio_id)


def market_chart(symbol, period="1mo", start=None, end=None):
    cache_key = (symbol, period, start, end)
    cached = market_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < MARKET_CACHE_SECONDS:
        return cached[1]
    params = {"interval": "1d", "events": "history"}
    if start and end:
        params.update(period1=int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp()),
                      period2=int(datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp()))
    else:
        params["range"] = period
    response = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}", params=params,
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
    response.raise_for_status()
    payload = response.json()["chart"]
    if payload.get("error") or not payload.get("result"):
        raise ValueError("No market data found for that symbol.")
    result = payload["result"][0]
    quotes = result["indicators"]["quote"][0]["close"]
    rows = [(datetime.fromtimestamp(ts, timezone.utc).date().isoformat(), float(close))
            for ts, close in zip(result.get("timestamp", []), quotes) if close is not None]
    if not rows:
        raise ValueError("No market prices found for that date range.")
    name = result.get("meta", {}).get("longName") or result.get("meta", {}).get("shortName") or symbol
    result = (rows, name)
    market_cache[cache_key] = (time.monotonic(), result)
    return result


def latest_prices(symbols):
    result = {}
    for symbol in symbols:
        try:
            rows, _ = market_chart(symbol)
            database.save_prices(symbol, rows)
            result[symbol] = Decimal(str(rows[-1][1]))
        except Exception:
            price = database.get_latest_price(symbol)
            if price is not None:
                result[symbol] = price
    return result


def portfolio(portfolio_id, refresh_prices=True):
    trades = database.get_trades(portfolio_id)
    cash = database.get_initial_cash(portfolio_id)
    symbols = sorted({trade["symbol"] for trade in trades})
    prices = latest_prices(symbols) if refresh_prices else {}
    holdings = {}
    for trade in trades:
        sign = Decimal(1) if trade["side"] == "buy" else Decimal(-1)
        holdings[trade["symbol"]] = holdings.get(trade["symbol"], Decimal(0)) + sign * trade["quantity"]
        # Buys use cash; sale proceeds return to the cash balance.
        cash -= sign * trade["quantity"] * trade["price"]
    market_value = sum((quantity * prices.get(symbol, Decimal(0))
                        for symbol, quantity in holdings.items()), Decimal(0))
    return trades, cash, holdings, prices, market_value


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/dashboard")
def dashboard():
    try:
        portfolio_id = session["portfolio_id"]
        trades, cash, holdings, prices, market_value = portfolio(portfolio_id)
        initial_cash = database.get_initial_cash(portfolio_id)
        return jsonify({
            "cash": float(cash),
            "market_value": float(market_value),
            "equity": float(cash + market_value),
            "holdings": [
                {"symbol": symbol, "quantity": float(quantity),
                 "price": float(prices.get(symbol, 0)),
                 "value": float(quantity * prices.get(symbol, 0))}
                for symbol, quantity in holdings.items() if quantity
            ],
            "history": history_data(trades, initial_cash),
            "trades": [
                {"symbol": trade["symbol"], "side": trade["side"],
                 "quantity": float(trade["quantity"]), "price": float(trade["price"]),
                 "date": trade["traded_at"].isoformat()}
                for trade in reversed(trades[-8:])
            ],
            "market_data": "Yahoo Finance · delayed",
        })
    except Exception as exc:
        return jsonify(error=str(exc)), 503


def history_data(trades, initial_cash):
    today = date.today()
    start = today - timedelta(days=30)
    symbols = sorted({trade["symbol"] for trade in trades})
    prices = {}
    for symbol in symbols:
        try:
            rows, _ = market_chart(symbol, start=start, end=today)
            database.save_prices(symbol, rows)
            prices[symbol] = {as_date(day): Decimal(str(price)) for day, price in rows}
        except Exception:
            prices[symbol] = database.get_price_history(symbol, start.isoformat())

    cash = initial_cash
    holdings = {}
    for trade in trades:
        if trade["traded_at"] < start:
            sign = Decimal(1) if trade["side"] == "buy" else Decimal(-1)
            holdings[trade["symbol"]] = holdings.get(trade["symbol"], Decimal(0)) + sign * trade["quantity"]
            cash -= sign * trade["quantity"] * trade["price"]

    output = []
    for offset in range(31):
        day = start + timedelta(days=offset)
        for trade in trades:
            if trade["traded_at"] == day:
                sign = Decimal(1) if trade["side"] == "buy" else Decimal(-1)
                holdings[trade["symbol"]] = holdings.get(trade["symbol"], Decimal(0)) + sign * trade["quantity"]
                cash -= sign * trade["quantity"] * trade["price"]
        market_value = Decimal(0)
        for symbol, quantity in holdings.items():
            available = [price for price_date, price in prices.get(symbol, {}).items() if price_date <= day]
            if available:
                market_value += quantity * available[-1]
        output.append({"date": day.isoformat(), "equity": float(cash + market_value)})
    return output


@app.get("/api/quote/<symbol>")
def quote(symbol):
    symbol = symbol.upper().strip()
    if not SYMBOL_RE.fullmatch(symbol):
        return jsonify(error="Enter a valid ticker symbol."), 400
    try:
        today = date.today()
        rows, name = market_chart(symbol, start=today - timedelta(days=30), end=today)
        database.save_prices(symbol, rows)
        return jsonify(
            symbol=symbol,
            name=name,
            price=rows[-1][1],
            change=rows[-1][1] - rows[0][1],
            change_percent=(rows[-1][1] / rows[0][1] - 1) * 100 if rows[0][1] else 0,
            history=[{"date": day, "close": close} for day, close in rows],
        )
    except Exception as exc:
        return jsonify(error=str(exc)), 404


@app.get("/api/symbol-search")
def symbol_search():
    query = request.args.get("q", "").strip()
    if len(query) < 1 or len(query) > 40:
        return jsonify(results=[])
    cache_key = ("search", query.casefold())
    cached = market_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < 300:
        return jsonify(results=cached[1])
    try:
        response = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": query, "quotesCount": 8, "newsCount": 0},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=3,
        )
        response.raise_for_status()
        quotes = response.json().get("quotes", [])
        results = [
            {"symbol": item.get("symbol"),
             "name": item.get("shortname") or item.get("longname") or item.get("symbol"),
             "exchange": item.get("exchDisp", "")}
            for item in quotes
            if item.get("quoteType") == "EQUITY" and item.get("symbol")
        ][:8]
        market_cache[cache_key] = (time.monotonic(), results)
        return jsonify(results=results)
    except requests.RequestException:
        return jsonify(results=[])


@app.post("/api/trades")
def place_trade():
    body = request.get_json(silent=True) or {}
    symbol = str(body.get("symbol", "")).upper().strip()
    side = body.get("side")
    try:
        quantity = Decimal(str(body.get("quantity", "")))
        traded_at = as_date(body.get("date") or date.today())
    except (InvalidOperation, ValueError, TypeError):
        return jsonify(error="Enter a valid quantity and date."), 400

    today = date.today()
    if not SYMBOL_RE.fullmatch(symbol) or side not in ("buy", "sell"):
        return jsonify(error="Enter a valid stock and trade type."), 400
    if quantity <= 0 or not quantity.is_finite():
        return jsonify(error="Quantity must be greater than zero."), 400
    if traded_at < today - timedelta(days=30) or traded_at > today:
        return jsonify(error="Choose a date within the past 30 days."), 400

    try:
        # Reuse prices loaded while the user selected the stock; fetch only on a cache miss.
        rows = None
        saved_prices = database.get_price_history(symbol, (traded_at - timedelta(days=7)).isoformat())
        eligible = [(day.isoformat(), float(price)) for day, price in saved_prices.items() if day <= traded_at]
        if not eligible:
            rows, _ = market_chart(symbol, start=traded_at - timedelta(days=7), end=traded_at)
            eligible = [row for row in rows if as_date(row[0]) <= traded_at]
        if not eligible:
            return jsonify(error="No market price is available for that date. Choose a trading day."), 400
        fill_date, raw_price = eligible[-1]
        price = Decimal(str(raw_price))
        if rows is not None:
            database.save_prices(symbol, rows)

        portfolio_id = session["portfolio_id"]
        trades, cash, holdings, _, _ = portfolio(portfolio_id, refresh_prices=False)
        owned = holdings.get(symbol, Decimal(0))
        amount = quantity * price
        if side == "buy" and amount > cash:
            return jsonify(error=f"Not enough cash. Available: ${cash:,.2f}."), 400
        if side == "sell" and quantity > owned:
            return jsonify(error=f"You own {owned:g} shares of {symbol}."), 400

        # Check that a backdated trade cannot create a negative balance or position later.
        running_cash = database.get_initial_cash(portfolio_id)
        running_holdings = {}
        proposed_trade = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "traded_at": as_date(fill_date),
        }
        ordered = sorted(trades + [proposed_trade], key=lambda trade: trade["traded_at"])
        for trade in ordered:
            signed_quantity = trade["quantity"] if trade["side"] == "buy" else -trade["quantity"]
            running_cash -= signed_quantity * trade["price"]
            running_holdings[trade["symbol"]] = running_holdings.get(trade["symbol"], Decimal(0)) + signed_quantity
            if running_cash < 0 or running_holdings[trade["symbol"]] < 0:
                return jsonify(error="That backdated trade would make the account balance or shares negative on a later date."), 400

        database.insert_trade(
            portfolio_id, os.urandom(16).hex(), symbol, side, float(quantity), float(price), fill_date,
            datetime.now(timezone.utc).isoformat(),
        )
        return jsonify(ok=True, message=f"{side.title()} {quantity:g} {symbol} at ${price:,.2f}", price=float(price)), 201
    except requests.RequestException:
        return jsonify(error="Market data is temporarily unavailable. Please try again."), 503
    except Exception as exc:
        return jsonify(error=str(exc)), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
