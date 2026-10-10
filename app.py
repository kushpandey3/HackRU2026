import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()
app = Flask(__name__)
DATABASE_URL = os.getenv("DATABASE_URL", "")
INITIAL_CASH = Decimal(os.getenv("INITIAL_CASH", "100000"))
SYMBOL_RE = re.compile(r"^[A-Z0-9.^=-]{1,15}$")

# The starter env file may have been copied before its placeholder URL was cleared.
if DATABASE_URL and ("@host:" in DATABASE_URL or "user:password@" in DATABASE_URL):
    print("DATABASE_URL is still the sample placeholder; using local SQLite. Set a real Tiger URL to use Tiger Cloud.")
    DATABASE_URL = ""


class DB:
    def __enter__(self):
        if DATABASE_URL:
            import psycopg
            self.conn = psycopg.connect(DATABASE_URL, connect_timeout=10)
            self.pg = True
        else:
            self.conn = sqlite3.connect(os.getenv("SQLITE_PATH", "paper_trading.db"))
            self.pg = False
        return self

    def __exit__(self, *_):
        self.conn.commit()
        self.conn.close()

    def execute(self, sql, args=()):
        if self.pg:
            return self.conn.execute(sql.replace("?", "%s"), args)
        return self.conn.execute(sql, args)


def init_db():
    with DB() as db:
        db.execute("CREATE TABLE IF NOT EXISTS trades (id TEXT PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL, quantity DOUBLE PRECISION NOT NULL, price DOUBLE PRECISION NOT NULL, traded_at TEXT NOT NULL, created_at TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS prices (symbol TEXT NOT NULL, price_date TEXT NOT NULL, close DOUBLE PRECISION NOT NULL, PRIMARY KEY(symbol, price_date))")
        db.execute("CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY, initial_cash DOUBLE PRECISION NOT NULL)")
        db.execute("INSERT INTO account (id, initial_cash) VALUES (1, ?) ON CONFLICT(id) DO NOTHING", (float(INITIAL_CASH),))


init_db()


def market_chart(symbol, period="1mo", start=None, end=None):
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
    return rows, name


def persist_prices(symbol, rows):
    with DB() as db:
        for day, close in rows:
            db.execute("INSERT INTO prices(symbol, price_date, close) VALUES (?, ?, ?) ON CONFLICT(symbol, price_date) DO UPDATE SET close=excluded.close", (symbol, day, close))


def get_trades():
    with DB() as db:
        rows = db.execute("SELECT id, symbol, side, quantity, price, traded_at FROM trades ORDER BY traded_at, created_at").fetchall()
        cash = Decimal(str(db.execute("SELECT initial_cash FROM account WHERE id=1").fetchone()[0]))
    return [dict(id=r[0], symbol=r[1], side=r[2], quantity=Decimal(str(r[3])), price=Decimal(str(r[4])), traded_at=date.fromisoformat(r[5])) for r in rows], cash


def latest_prices(symbols):
    result = {}
    for symbol in symbols:
        try:
            rows, _ = market_chart(symbol)
            persist_prices(symbol, rows)
            result[symbol] = Decimal(str(rows[-1][1]))
        except Exception:
            with DB() as db:
                row = db.execute("SELECT close FROM prices WHERE symbol=? ORDER BY price_date DESC LIMIT 1", (symbol,)).fetchone()
            if row:
                result[symbol] = Decimal(str(row[0]))
    return result


def portfolio():
    trades, cash = get_trades()
    symbols = sorted({t["symbol"] for t in trades})
    prices = latest_prices(symbols)
    holdings = {}
    for trade in trades:
        sign = Decimal(1) if trade["side"] == "buy" else Decimal(-1)
        holdings[trade["symbol"]] = holdings.get(trade["symbol"], Decimal(0)) + sign * trade["quantity"]
    market_value = sum((qty * prices.get(sym, Decimal(0)) for sym, qty in holdings.items()), Decimal(0))
    return trades, cash, holdings, prices, market_value


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/dashboard")
def dashboard():
    try:
        trades, cash, holdings, prices, market_value = portfolio()
        return jsonify({"cash": float(cash), "market_value": float(market_value), "equity": float(cash + market_value),
                        "holdings": [{"symbol": s, "quantity": float(q), "price": float(prices.get(s, 0)), "value": float(q * prices.get(s, 0))} for s, q in holdings.items() if q],
                        "history": history_data(trades, cash), "trades": [{"symbol": t["symbol"], "side": t["side"], "quantity": float(t["quantity"]), "price": float(t["price"]), "date": t["traded_at"].isoformat()} for t in reversed(trades[-8:])],
                        "market_data": "Yahoo Finance · delayed"})
    except Exception as exc:
        return jsonify(error=str(exc)), 503


def history_data(trades, initial_cash):
    today = date.today()
    start = today - timedelta(days=30)
    relevant = [t for t in trades if t["traded_at"] >= start]
    # Include securities opened before this chart window; they still contribute to equity.
    symbols = sorted({t["symbol"] for t in trades})
    prices = {}
    for symbol in symbols:
        try:
            rows, _ = market_chart(symbol, start=start, end=today)
            persist_prices(symbol, rows)
            prices[symbol] = {date.fromisoformat(d): Decimal(str(p)) for d, p in rows}
        except Exception:
            with DB() as db:
                prices[symbol] = {date.fromisoformat(r[0]): Decimal(str(r[1])) for r in db.execute("SELECT price_date, close FROM prices WHERE symbol=? AND price_date>=? ORDER BY price_date", (symbol, start.isoformat())).fetchall()}
    cash = initial_cash
    holdings = {}
    for t in trades:
        if t["traded_at"] < start:
            sign = Decimal(1) if t["side"] == "buy" else Decimal(-1)
            holdings[t["symbol"]] = holdings.get(t["symbol"], Decimal(0)) + sign * t["quantity"]
            cash -= sign * t["quantity"] * t["price"]
    output = []
    for offset in range(31):
        day = start + timedelta(days=offset)
        for t in trades:
            if t["traded_at"] == day:
                sign = Decimal(1) if t["side"] == "buy" else Decimal(-1)
                holdings[t["symbol"]] = holdings.get(t["symbol"], Decimal(0)) + sign * t["quantity"]
                cash -= sign * t["quantity"] * t["price"]
        value = Decimal(0)
        for symbol, qty in holdings.items():
            available = [p for d, p in prices.get(symbol, {}).items() if d <= day]
            if available:
                value += qty * available[-1]
        output.append({"date": day.isoformat(), "equity": float(cash + value)})
    return output


@app.get("/api/quote/<symbol>")
def quote(symbol):
    symbol = symbol.upper().strip()
    if not SYMBOL_RE.fullmatch(symbol):
        return jsonify(error="Enter a valid ticker symbol."), 400
    try:
        rows, name = market_chart(symbol)
        persist_prices(symbol, rows)
        return jsonify(symbol=symbol, name=name, price=rows[-1][1], change=rows[-1][1] - rows[0][1], change_percent=(rows[-1][1] / rows[0][1] - 1) * 100 if rows[0][1] else 0)
    except Exception as exc:
        return jsonify(error=str(exc)), 404


@app.post("/api/trades")
def place_trade():
    body = request.get_json(silent=True) or {}
    symbol = str(body.get("symbol", "")).upper().strip()
    side = body.get("side")
    try:
        quantity = Decimal(str(body.get("quantity", "")))
        traded_at = date.fromisoformat(body.get("date", date.today().isoformat()))
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
        # Include prior sessions so weekends and market holidays fill at the previous close.
        rows, _ = market_chart(symbol, start=traded_at - timedelta(days=7), end=traded_at)
        eligible = [r for r in rows if date.fromisoformat(r[0]) <= traded_at]
        if not eligible:
            return jsonify(error="No market price is available for that date. Choose a trading day."), 400
        fill_date, raw_price = eligible[-1]
        price = Decimal(str(raw_price))
        persist_prices(symbol, rows)
        trades, cash, holdings, _, _ = portfolio()
        owned = holdings.get(symbol, Decimal(0))
        amount = quantity * price
        if side == "buy" and amount > cash:
            return jsonify(error=f"Not enough cash. Available: ${cash:,.2f}."), 400
        if side == "sell" and quantity > owned:
            return jsonify(error=f"You own {owned:g} shares of {symbol}."), 400
        # Keep the ledger chronologically valid: a backdated fill cannot create a negative balance later.
        running_cash = INITIAL_CASH
        running_holdings = {}
        ordered = sorted(trades + [dict(symbol=symbol, side=side, quantity=quantity, price=price, traded_at=date.fromisoformat(fill_date))], key=lambda t: t["traded_at"])
        for item in ordered:
            signed = item["quantity"] if item["side"] == "buy" else -item["quantity"]
            running_cash -= signed * item["price"]
            running_holdings[item["symbol"]] = running_holdings.get(item["symbol"], Decimal(0)) + signed
            if running_cash < 0 or running_holdings[item["symbol"]] < 0:
                return jsonify(error="That backdated trade would make the account balance or shares negative on a later date."), 400
        with DB() as db:
            db.execute("INSERT INTO trades(id, symbol, side, quantity, price, traded_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (os.urandom(16).hex(), symbol, side, float(quantity), float(price), fill_date, datetime.now(timezone.utc).isoformat()))
        return jsonify(ok=True, message=f"{side.title()} {quantity:g} {symbol} at ${price:,.2f}", price=float(price)), 201
    except requests.RequestException:
        return jsonify(error="Market data is temporarily unavailable. Please try again."), 503
    except Exception as exc:
        return jsonify(error=str(exc)), 503


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
