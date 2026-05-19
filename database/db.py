"""
Data layer — supports SQLite (local) and PostgreSQL (cloud) automatically.

Priority for DB connection string:
  1) st.secrets["DATABASE_URL"]   (Streamlit Cloud)
  2) env var DATABASE_URL
  3) Local SQLite at data/investment.db

All function signatures preserved from the original SQLite-only version so
app.py and scan_watchlist.py keep working without changes.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_DEFAULT_SQLITE = Path(__file__).parent.parent / "data" / "investment.db"
_engine: Optional[Engine] = None
_INITIALIZED = False


# ── Connection ───────────────────────────────────────────────────────────
def _resolve_db_url() -> str:
    # 1) Streamlit secrets (works in cloud)
    try:
        import streamlit as st  # noqa: WPS433
        url = st.secrets.get("DATABASE_URL", None)
        if url:
            return url
    except Exception:
        pass
    # 2) plain env var (works in any process)
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    # 3) fallback to local SQLite
    _DEFAULT_SQLITE.parent.mkdir(exist_ok=True)
    return f"sqlite:///{_DEFAULT_SQLITE}"


def _get_engine() -> Engine:
    global _engine
    if _engine is not None:
        return _engine
    url = _resolve_db_url()
    # Heroku-style postgres:// → SQLAlchemy expects postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    kwargs: Dict[str, Any] = {}
    if url.startswith("postgresql"):
        kwargs.update({"pool_pre_ping": True, "pool_recycle": 300})
    _engine = create_engine(url, **kwargs)
    return _engine


def _is_postgres() -> bool:
    return _get_engine().dialect.name == "postgresql"


# ── Schema ───────────────────────────────────────────────────────────────
def init_db():
    global _INITIALIZED
    if _INITIALIZED:
        return
    eng = _get_engine()
    pg = _is_postgres()
    auto_pk = "SERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with eng.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS analysis_history (
                id {auto_pk},
                symbol TEXT NOT NULL,
                analyzed_at TEXT NOT NULL,
                fundamental_score REAL,
                risk_level TEXT,
                valuation_status TEXT,
                invest_ratio REAL,
                recommendation TEXT,
                raw_json TEXT
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS watchlist (
                id {auto_pk},
                symbol TEXT UNIQUE NOT NULL,
                added_at TEXT NOT NULL,
                note TEXT,
                cost_basis REAL DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notification_log (
                symbol TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                notified_at TEXT NOT NULL,
                PRIMARY KEY (symbol, signal_type)
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS transactions (
                id {auto_pk},
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                price REAL NOT NULL,
                shares REAL NOT NULL,
                twd_amount REAL,
                currency TEXT DEFAULT 'TWD',
                note TEXT,
                created_at TEXT NOT NULL
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tx_symbol ON transactions(symbol)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(trade_date)"))
        # backfill cost_basis on legacy SQLite dbs (Postgres always has it from create)
        if not pg:
            try:
                conn.execute(text("ALTER TABLE watchlist ADD COLUMN cost_basis REAL DEFAULT 0"))
            except Exception:
                pass
    _INITIALIZED = True


# ── Notification dedup ───────────────────────────────────────────────────
def was_recently_notified(symbol: str, signal_type: str, hours: int = 24) -> bool:
    init_db()
    with _get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT notified_at FROM notification_log WHERE symbol=:s AND signal_type=:t"),
            {"s": symbol.upper(), "t": signal_type},
        ).fetchone()
    if not row:
        return False
    try:
        last = datetime.fromisoformat(row[0])
    except Exception:
        return False
    return (datetime.now() - last).total_seconds() < hours * 3600


def log_notification(symbol: str, signal_type: str):
    init_db()
    params = {"s": symbol.upper(), "t": signal_type, "n": datetime.now().isoformat()}
    with _get_engine().begin() as conn:
        if _is_postgres():
            conn.execute(text("""
                INSERT INTO notification_log (symbol, signal_type, notified_at)
                VALUES (:s, :t, :n)
                ON CONFLICT (symbol, signal_type)
                DO UPDATE SET notified_at = EXCLUDED.notified_at
            """), params)
        else:
            conn.execute(text("""
                INSERT OR REPLACE INTO notification_log (symbol, signal_type, notified_at)
                VALUES (:s, :t, :n)
            """), params)


# ── Watchlist ────────────────────────────────────────────────────────────
def set_watchlist_cost(symbol: str, cost_basis: float):
    init_db()
    with _get_engine().begin() as conn:
        conn.execute(
            text("UPDATE watchlist SET cost_basis=:c WHERE symbol=:s"),
            {"c": float(cost_basis), "s": symbol.upper()},
        )


def add_to_watchlist(symbol: str, note: str = ""):
    init_db()
    params = {"s": symbol.upper(), "a": datetime.now().isoformat(), "n": note}
    with _get_engine().begin() as conn:
        if _is_postgres():
            conn.execute(text("""
                INSERT INTO watchlist (symbol, added_at, note)
                VALUES (:s, :a, :n)
                ON CONFLICT (symbol)
                DO UPDATE SET added_at = EXCLUDED.added_at, note = EXCLUDED.note
            """), params)
        else:
            conn.execute(text("""
                INSERT OR REPLACE INTO watchlist (symbol, added_at, note)
                VALUES (:s, :a, :n)
            """), params)


def get_watchlist() -> List[Dict]:
    init_db()
    with _get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM watchlist ORDER BY added_at DESC")
        ).mappings().fetchall()
    return [dict(r) for r in rows]


def remove_from_watchlist(symbol: str):
    init_db()
    with _get_engine().begin() as conn:
        conn.execute(text("DELETE FROM watchlist WHERE symbol=:s"), {"s": symbol.upper()})


# ── Transactions ─────────────────────────────────────────────────────────
def add_transaction(symbol: str, action: str, trade_date: str,
                    price: float, shares: float,
                    twd_amount: Optional[float] = None,
                    currency: str = "TWD",
                    note: str = ""):
    init_db()
    with _get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO transactions
              (symbol, action, trade_date, price, shares, twd_amount, currency, note, created_at)
            VALUES (:sym, :act, :td, :pr, :sh, :twd, :ccy, :nt, :ct)
        """), {
            "sym": symbol.upper(),
            "act": action.lower(),
            "td": trade_date,
            "pr": float(price),
            "sh": float(shares),
            "twd": float(twd_amount) if twd_amount is not None else None,
            "ccy": currency,
            "nt": note,
            "ct": datetime.now().isoformat(),
        })


def get_transactions(symbol: Optional[str] = None) -> List[Dict]:
    init_db()
    with _get_engine().connect() as conn:
        if symbol:
            rows = conn.execute(
                text("SELECT * FROM transactions WHERE symbol=:s ORDER BY trade_date DESC, id DESC"),
                {"s": symbol.upper()},
            ).mappings().fetchall()
        else:
            rows = conn.execute(
                text("SELECT * FROM transactions ORDER BY trade_date DESC, id DESC")
            ).mappings().fetchall()
    return [dict(r) for r in rows]


def delete_transaction(tx_id: int):
    init_db()
    with _get_engine().begin() as conn:
        conn.execute(text("DELETE FROM transactions WHERE id=:i"), {"i": int(tx_id)})


def update_transaction(tx_id: int, **fields):
    """更新交易紀錄的指定欄位。
    允許欄位: symbol, action, trade_date, price, shares, twd_amount, currency, note
    """
    if not fields:
        return
    allowed = {"symbol", "action", "trade_date", "price",
               "shares", "twd_amount", "currency", "note"}
    sets = []
    params = {"i": int(tx_id)}
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k}=:{k}")
        if k == "symbol":
            v = str(v).upper()
        elif k == "action":
            v = str(v).lower()
        params[k] = v
    if not sets:
        return
    init_db()
    with _get_engine().begin() as conn:
        conn.execute(
            text(f"UPDATE transactions SET {', '.join(sets)} WHERE id=:i"),
            params,
        )


def get_holdings() -> List[Dict]:
    """FIFO 算法計算每檔目前持倉與加權平均成本。"""
    init_db()
    with _get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM transactions ORDER BY symbol, trade_date, id")
        ).mappings().fetchall()
    txs_by_sym: Dict[str, List[Dict]] = {}
    for r in rows:
        d = dict(r)
        txs_by_sym.setdefault(d["symbol"], []).append(d)

    holdings = []
    for sym, txs in txs_by_sym.items():
        lots: List[Dict] = []
        total_twd_invested = 0.0
        total_twd_realized = 0.0
        for tx in txs:
            if tx["action"] == "buy":
                lots.append({
                    "shares": tx["shares"],
                    "price": tx["price"],
                    "twd": tx.get("twd_amount") or 0,
                })
                total_twd_invested += tx.get("twd_amount") or 0
            else:  # sell
                remain = tx["shares"]
                proceeds = tx.get("twd_amount") or 0
                total_twd_realized += proceeds
                while remain > 0 and lots:
                    lot = lots[0]
                    if lot["shares"] <= remain:
                        remain -= lot["shares"]
                        lots.pop(0)
                    else:
                        ratio = remain / lot["shares"]
                        lot["shares"] -= remain
                        lot["twd"] *= (1 - ratio)
                        remain = 0

        if not lots:
            continue
        total_shares = sum(l["shares"] for l in lots)
        if total_shares <= 0:
            continue
        weighted_price = sum(l["shares"] * l["price"] for l in lots) / total_shares
        remaining_twd_cost = sum(l["twd"] for l in lots)

        holdings.append({
            "symbol": sym,
            "shares": total_shares,
            "avg_cost": weighted_price,
            "twd_cost": remaining_twd_cost,
            "twd_invested_total": total_twd_invested,
            "twd_realized": total_twd_realized,
            "currency": txs[-1].get("currency") or "TWD",
        })
    return holdings


def get_avg_cost(symbol: str) -> Optional[float]:
    for h in get_holdings():
        if h["symbol"] == symbol.upper():
            return h["avg_cost"]
    return None


# ── Analysis history ─────────────────────────────────────────────────────
def save_analysis(symbol: str, result: Dict[str, Any]):
    init_db()
    with _get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO analysis_history
              (symbol, analyzed_at, fundamental_score, risk_level,
               valuation_status, invest_ratio, recommendation, raw_json)
            VALUES (:sym, :at, :fs, :rl, :vs, :ir, :rec, :raw)
        """), {
            "sym": symbol.upper(),
            "at": datetime.now().isoformat(),
            "fs": result.get("fundamental", {}).get("total_score"),
            "rl": result.get("risk", {}).get("level"),
            "vs": result.get("valuation", {}).get("status"),
            "ir": result.get("allocation", {}).get("invest_ratio"),
            "rec": result.get("position", {}).get("action"),
            "raw": json.dumps(result, ensure_ascii=False, default=str),
        })


def get_history(symbol: Optional[str] = None, limit: int = 20, unique_symbols: bool = False) -> List[Dict]:
    init_db()
    with _get_engine().connect() as conn:
        if symbol:
            rows = conn.execute(
                text("SELECT * FROM analysis_history WHERE symbol=:s ORDER BY analyzed_at DESC LIMIT :l"),
                {"s": symbol.upper(), "l": int(limit)},
            ).mappings().fetchall()
        elif unique_symbols:
            rows = conn.execute(text("""
                SELECT * FROM analysis_history
                WHERE id IN (SELECT MAX(id) FROM analysis_history GROUP BY symbol)
                ORDER BY analyzed_at DESC LIMIT :l
            """), {"l": int(limit)}).mappings().fetchall()
        else:
            rows = conn.execute(
                text("SELECT * FROM analysis_history ORDER BY analyzed_at DESC LIMIT :l"),
                {"l": int(limit)},
            ).mappings().fetchall()
    return [dict(r) for r in rows]
